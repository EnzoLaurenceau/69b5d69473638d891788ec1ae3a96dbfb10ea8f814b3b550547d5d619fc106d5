#!/usr/bin/env python
"""
daily_token_report.py — Rapport journalier de consommation token
===============================================================

Analyse complète de l'utilisation des tokens sur toutes les sources:
  - Hermes (state.db)
  - Claude Code (.claude/projects/*/*.jsonl)
  - Antigravity (.gemini/)

Pour CHAQUE tâche:
  - Description en une phrase (extrait du premier message)
  - Tokens estimés AVANT (basé sur complexité/type de tâche)
  - Tokens réellement consommés APRÈS
  - Delta (surconsommation ou économie)
  - Modèle utilisé

Usage:
  python daily_token_report.py                # Rapport du jour
  python daily_token_report.py --yesterday    # Rapport d'hier
  python daily_token_report.py --date 2026-07-17  # Date spécifique
  python daily_token_report.py --save         # Sauvegarder en .md
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

HERMES_DB = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
CLAUDE_DIR = Path.home() / ".claude"
GEMINI_DIR = Path.home() / ".gemini"
FORGE_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = FORGE_ROOT / "05_STATE" / "reports"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ─── Token estimation engine ─────────────────────────────────────────────────

# Average tokens per task type (input + output, single pass, no retries)
TASK_TYPE_ESTIMATES = {
    # Short tasks (1-5 min)
    "question":       {"in": 2_000,   "out": 500,     "description": "question simple"},
    "lookup":         {"in": 3_000,   "out": 1_000,   "description": "recherche d'info"},
    "fix_small":      {"in": 5_000,   "out": 2_000,   "description": "petit fix/bug"},
    # Medium tasks (5-30 min)
    "code_gen":       {"in": 10_000,  "out": 5_000,   "description": "génération de code"},
    "debug":          {"in": 15_000,  "out": 8_000,   "description": "debugging"},
    "config":         {"in": 8_000,   "out": 3_000,   "description": "configuration"},
    "research":       {"in": 20_000,  "out": 5_000,   "description": "recherche/analyse"},
    "refactor":       {"in": 25_000,  "out": 10_000,  "description": "refactoring"},
    # Long tasks (30min+)
    "full_feature":   {"in": 50_000,  "out": 25_000,  "description": "feature complète"},
    "architecture":   {"in": 40_000,  "out": 15_000,  "description": "architecture/design"},
    "migration":      {"in": 60_000,  "out": 30_000,  "description": "migration/mise à jour"},
    "integration":    {"in": 80_000,  "out": 40_000,  "description": "intégration complexe"},
    # Very long tasks (1h+)
    "full_stack":     {"in": 150_000, "out": 75_000,  "description": "full-stack complet"},
    "system_build":   {"in": 200_000, "out": 100_000, "description": "construction système"},
    # Hermes-specific (free models, can be more verbose)
    "hermes_chat":    {"in": 5_000,   "out": 2_000,   "description": "conversation Hermes"},
    "hermes_tool":    {"in": 15_000,  "out": 8_000,   "description": "Hermes + outils"},
}


def classify_task(title: str, first_msg: str = "", model: str = "", provider: str = "") -> str:
    """Classify a task into a type based on title and first message."""
    text = f"{title} {first_msg}".lower()

    if provider == "hermes":
        if any(kw in text for kw in ["tool", "terminal", "search", "find", "read", "write"]):
            return "hermes_tool"
        return "hermes_chat"

    # Complex tasks
    if any(kw in text for kw in ["full-stack", "fullstack", "entière", "complet", "système", "construire un"]):
        return "full_stack"
    if any(kw in text for kw in ["intégrer", "integrate", "connecter", "relier", "brancher"]):
        return "integration"
    if any(kw in text for kw in ["migrat", "upgrade", "mettre à jour", "passer de"]):
        return "migration"
    if any(kw in text for kw in ["architect", "design système", "structure", "organis"]):
        return "architecture"
    if any(kw in text for kw in ["feature", "fonctionnalité", "ajouter", "créer un", "implémenter"]):
        return "full_feature"
    if any(kw in text for kw in ["refactor", "restructur", "réorganis", "nettoyer", "clean"]):
        return "refactor"
    if any(kw in text for kw in ["recherch", "analyse", "cherche", "trouve", "étudie", "compare"]):
        return "research"
    if any(kw in text for kw in ["configur", "setup", "install", "paramètr"]):
        return "config"
    if any(kw in text for kw in ["debug", "erreur", "bug", "fix", "problème", "marche pas", "corrig"]):
        return "debug"
    if any(kw in text for kw in ["code", "script", "fonction", "classe", "module", "fichier"]):
        return "code_gen"
    if any(kw in text for kw in ["vérif", "check", "regarde", "liste", "montre"]):
        return "lookup"

    return "code_gen"  # default


def estimate_tokens(task_type: str, msg_count: int = 0, provider: str = "") -> dict:
    """Estimate expected token consumption for a task type."""
    base = TASK_TYPE_ESTIMATES.get(task_type, TASK_TYPE_ESTIMATES["code_gen"])

    est_in = base["in"]
    est_out = base["out"]

    # Multi-message sessions consume more (retries, context reloading)
    if msg_count > 20:
        est_in *= 2.5
        est_out *= 2.0
    elif msg_count > 10:
        est_in *= 1.8
        est_out *= 1.5
    elif msg_count > 5:
        est_in *= 1.3
        est_out *= 1.2

    return {
        "estimated_in": int(est_in),
        "estimated_out": int(est_out),
        "estimated_total": int(est_in + est_out),
        "task_type": task_type,
        "task_description": base["description"],
    }


def _summarize_task(first_msg: str, title: str = "") -> str:
    """Create a one-sentence task summary."""
    text = first_msg.strip() if first_msg else title.strip()
    if not text:
        return "Tâche sans description"
    # Take first sentence or first 120 chars
    text = re.sub(r'\s+', ' ', text)
    # Remove common prefixes
    for prefix in ["je voudrais", "peux-tu", "j'aimerais", "tu devras", "tu peux", "il faut"]:
        if text.lower().startswith(prefix):
            # Keep it but it's fine
            pass
    if len(text) > 120:
        text = text[:117] + "..."
    return text


# ─── Claude pricing ──────────────────────────────────────────────────────────

PRICING = {
    "claude-opus-4-8":           {"in": 15.0,  "out": 75.0, "cache_read": 1.5,  "cache_write": 18.75},
    "claude-sonnet-4-6":         {"in": 3.0,   "out": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5-20251001": {"in": 0.80,  "out": 4.0,  "cache_read": 0.08, "cache_write": 1.0},
    "claude-fable-5":            {"in": 3.0,   "out": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "mimo-v2.5-pro":             {"in": 0.0,   "out": 0.0,  "cache_read": 0.0,  "cache_write": 0.0},
    "hermes":                    {"in": 0.0,   "out": 0.0,  "cache_read": 0.0,  "cache_write": 0.0},
}
DEFAULT_PRICE = {"in": 3.0, "out": 15.0, "cache_read": 0.30, "cache_write": 3.75}

def _price(model: str) -> dict:
    for key, val in PRICING.items():
        if key in (model or "").lower():
            return val
    return DEFAULT_PRICE

def _cost(model: str, tin: int, tout: int, tcr: int = 0, tcw: int = 0) -> float:
    p = _price(model)
    return (tin * p["in"] + tout * p["out"] + tcr * p["cache_read"] + tcw * p["cache_write"]) / 1_000_000


# ─── Collectors ──────────────────────────────────────────────────────────────

def _get_first_user_message(conn, session_id: str) -> str:
    """Get the first user message for a session from the messages table."""
    try:
        row = conn.execute("""
            SELECT content FROM messages
            WHERE session_id = ? AND role = 'user'
            ORDER BY rowid ASC LIMIT 1
        """, (session_id,)).fetchone()
        if row and row["content"]:
            content = row["content"]
            # Handle JSON-encoded content (Hermes stores some as JSON arrays)
            if content.startswith("["):
                try:
                    parts = json.loads(content)
                    if isinstance(parts, list):
                        content = " ".join(
                            p.get("text", "") for p in parts if isinstance(p, dict)
                        )
                except (json.JSONDecodeError, AttributeError) as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            return content.strip()[:500]
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return ""


def collect_hermes(day_start: float, day_end: float) -> dict:
    if not HERMES_DB.exists():
        return {"sessions": [], "by_model": {}, "by_task": {}, "task_details": []}

    conn = sqlite3.connect(str(HERMES_DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, title, model, started_at, ended_at,
               message_count, tool_call_count,
               input_tokens, output_tokens,
               cache_read_tokens, cache_write_tokens, reasoning_tokens,
               actual_cost_usd, cwd
        FROM sessions
        WHERE started_at >= ? AND started_at < ?
        ORDER BY started_at
    """, (day_start, day_end)).fetchall()

    sessions = []
    by_model = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reasoning": 0, "cost": 0, "messages": 0, "tools": 0})
    by_task = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "cost": 0})
    task_details = []

    for r in rows:
        tin = r["input_tokens"] or 0
        tout = r["output_tokens"] or 0
        tcr = r["cache_read_tokens"] or 0
        tcw = r["cache_write_tokens"] or 0
        reasoning = r["reasoning_tokens"] or 0
        model = r["model"] or "unknown"
        title = r["title"] or ""
        cost = r["actual_cost_usd"] or _cost(model, tin, tout, tcr, tcw)
        msgs = r["message_count"] or 0
        tools = r["tool_call_count"] or 0
        total = tin + tout + tcr + tcw + reasoning

        # Fallback: get first user message when title is empty
        first_msg = ""
        if not title:
            first_msg = _get_first_user_message(conn, r["id"])
            if first_msg:
                title = first_msg[:80]

        sess = {
            "id": r["id"],
            "title": title or "Session sans titre",
            "model": model,
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "messages": msgs,
            "tools": tools,
            "input_tokens": tin,
            "output_tokens": tout,
            "cache_read": tcr,
            "cache_write": tcw,
            "reasoning": reasoning,
            "total": total,
            "cost": cost,
            "cwd": r["cwd"] or "",
            "first_message": first_msg,
        }
        sessions.append(sess)

        # Task estimation — compare against input+output only (cache is 90% discounted)
        actual_billable = tin + tout  # What actually costs money
        task_type = classify_task(title, first_msg or title, model, "hermes")
        est = estimate_tokens(task_type, msgs, "hermes")
        task_details.append({
            "provider": "hermes",
            "model": model,
            "summary": _summarize_task(first_msg or title, title),
            "actual_in": tin,
            "actual_out": tout,
            "actual_cache": tcr + tcw,
            "actual_total": total,
            "actual_billable": actual_billable,
            "actual_cost": cost,
            "messages": msgs,
            "tool_calls": tools,
            "est_in": est["estimated_in"],
            "est_out": est["estimated_out"],
            "est_total": est["estimated_total"],
            "task_type": task_type,
            "delta_pct": round(((actual_billable - est["estimated_total"]) / max(est["estimated_total"], 1)) * 100, 0),
        })

        m = by_model[model]
        m["count"] += 1; m["in"] += tin; m["out"] += tout
        m["cr"] += tcr; m["cw"] += tcw; m["reasoning"] += reasoning
        m["cost"] += cost; m["messages"] += msgs; m["tools"] += tools

        domain = _detect_domain(title or first_msg or "")
        t = by_task[domain]
        t["count"] += 1; t["in"] += tin; t["out"] += tout; t["cost"] += cost

    conn.close()
    return {"sessions": sessions, "by_model": dict(by_model), "by_task": dict(by_task), "task_details": task_details}


def collect_claude_code(day_start: float, day_end: float) -> dict:
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return {"sessions": [], "by_model": {}, "by_project": {}, "task_details": []}

    sessions = []
    by_model = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "cr": 0, "cc": 0, "cost": 0, "messages": 0})
    by_project = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "cost": 0})
    task_details = []

    for jsonl_file in projects_dir.rglob("*.jsonl"):
        mtime = jsonl_file.stat().st_mtime
        if mtime < day_start or mtime >= day_end:
            continue

        session_id = jsonl_file.stem
        project = jsonl_file.parent.name
        msg_count = 0; user_count = 0; assistant_count = 0
        total_in = 0; total_out = 0; total_cr = 0; total_cc = 0
        model = ""; title = ""; first_user_msg = ""

        try:
            with open(jsonl_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = entry.get("type", "")
                    msg_count += 1

                    if etype == "user":
                        user_count += 1
                        if not first_user_msg:
                            msg = entry.get("message", {})
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = " ".join(
                                    c.get("text", "") for c in content if isinstance(c, dict)
                                )
                            first_user_msg = str(content)[:300]

                    elif etype == "assistant":
                        assistant_count += 1
                        msg = entry.get("message", {})
                        m = msg.get("model", "")
                        if m and not model:
                            model = m
                        usage = msg.get("usage", entry.get("usage", {}))
                        if usage:
                            total_in += usage.get("input_tokens", 0)
                            total_out += usage.get("output_tokens", 0)
                            total_cr += usage.get("cache_read_input_tokens", 0)
                            total_cc += usage.get("cache_creation_input_tokens", 0)

                    elif etype in ("custom-title", "ai-title"):
                        title = entry.get("title", title)
                    elif etype == "result":
                        result = entry.get("result", {})
                        if isinstance(result, dict) and not title:
                            title = result.get("summary", "")[:80]
        except OSError:
            continue

        if msg_count == 0:
            continue

        cost = _cost(model, total_in, total_out, total_cr, total_cc)
        total = total_in + total_out + total_cr + total_cc

        sess = {
            "id": session_id,
            "project": project,
            "title": title or session_id[:12],
            "first_message": first_user_msg,
            "model": model or "claude",
            "messages": msg_count,
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_read": total_cr,
            "cache_creation": total_cc,
            "total": total,
            "cost": cost,
            "last_modified": mtime,
        }
        sessions.append(sess)

        # Task estimation — compare against input+output only (cache is 90% discounted)
        actual_billable = total_in + total_out  # What actually costs money
        task_type = classify_task(title, first_user_msg, model, "claude-code")
        est = estimate_tokens(task_type, msg_count, "claude-code")
        task_details.append({
            "provider": "claude-code",
            "model": model or "claude",
            "project": project,
            "summary": _summarize_task(first_user_msg, title),
            "actual_in": total_in,
            "actual_out": total_out,
            "actual_cache": total_cr + total_cc,
            "actual_total": total,
            "actual_billable": actual_billable,
            "actual_cost": cost,
            "messages": msg_count,
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "est_in": est["estimated_in"],
            "est_out": est["estimated_out"],
            "est_total": est["estimated_total"],
            "task_type": task_type,
            "delta_pct": round(((actual_billable - est["estimated_total"]) / max(est["estimated_total"], 1)) * 100, 0),
        })

        m = by_model[model or "claude"]
        m["count"] += 1; m["in"] += total_in; m["out"] += total_out
        m["cr"] += total_cr; m["cc"] += total_cc; m["cost"] += cost
        m["messages"] += msg_count

        p = by_project[project]
        p["count"] += 1; p["in"] += total_in; p["out"] += total_out; p["cost"] += cost

    return {"sessions": sessions, "by_model": dict(by_model), "by_project": dict(by_project), "task_details": task_details}


def _estimate_tokens_from_text(text: str) -> int:
    """Rough token estimate: ~4 chars per token for mixed EN/FR content."""
    return max(len(text) // 4, 1)


def collect_antigravity(day_start: float, day_end: float) -> dict:
    brain_dir = GEMINI_DIR / "antigravity" / "brain"
    if not brain_dir.exists():
        return {"sessions": [], "by_model": {}, "task_details": []}

    sessions = []
    task_details = []
    by_model = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "cost": 0})

    for entry in brain_dir.iterdir():
        if not entry.is_dir():
            continue
        mtime = entry.stat().st_mtime
        if mtime < day_start or mtime >= day_end:
            continue

        # Gather all content files
        md_files = list(entry.glob("*.md"))
        json_files = [f for f in entry.glob("*.metadata.json")]
        all_files = md_files + [f for f in entry.glob("*.json") if not f.name.endswith(".metadata.json")]

        # Read task description from metadata summaries
        task_desc = ""
        summaries = []
        for mf in json_files:
            try:
                meta = json.loads(mf.read_text(encoding="utf-8", errors="replace"))
                summary = meta.get("summary", "")
                if summary:
                    summaries.append(summary)
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Use first summary as task description
        if summaries:
            task_desc = summaries[0]

        # Fallback: read first .md file
        if not task_desc:
            for f in md_files:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")[:300]
                    if content.strip():
                        task_desc = content.strip()
                        break
                except OSError as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Estimate tokens from all content
        total_chars = 0
        for f in md_files:
            try:
                total_chars += f.stat().st_size
            except OSError as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Gemini generates ~3x output vs input for typical tasks
        # Input = prompt (~2K tokens avg), Output = generated content
        est_output = _estimate_tokens_from_text("a" * total_chars)
        est_input = max(est_output // 3, 2000)  # Conservative input estimate
        est_total = est_input + est_output

        sessions.append({
            "id": entry.name,
            "file_count": len(md_files) + len(json_files),
            "last_activity": mtime,
            "task_desc": task_desc,
            "est_chars": total_chars,
        })

        task_details.append({
            "provider": "antigravity",
            "model": "gemini-2.5-pro",
            "summary": _summarize_task(task_desc, entry.name[:12]),
            "actual_in": est_input,
            "actual_out": est_output,
            "actual_cache": 0,
            "actual_total": est_total,
            "actual_billable": est_total,
            "actual_cost": 0,  # Google AI Pro = fixed subscription
            "messages": len(md_files),
            "est_in": est_input,
            "est_out": est_output,
            "est_total": est_total,
            "task_type": classify_task(task_desc, task_desc, "gemini", "antigravity"),
            "delta_pct": 0,
        })

        m = by_model["gemini-2.5-pro"]
        m["count"] += 1; m["in"] += est_input; m["out"] += est_output; m["cost"] += 0

    return {"sessions": sessions, "by_model": dict(by_model), "task_details": task_details}


def _detect_domain(title: str) -> str:
    t = title.lower()
    for domain, kws in [
        ("coding", ["code", "python", "js", "debug", "fix", "script", "bug"]),
        ("research", ["research", "analyze", "study", "search", "recon"]),
        ("writing", ["write", "content", "blog", "article", "doc", "email"]),
        ("design", ["design", "ui", "ux", "landing", "css", "html"]),
        ("security", ["security", "audit", "pentest", "vuln", "bounty", "hack"]),
        ("bot", ["bot", "telegram", "discord", "automation"]),
        ("devops", ["deploy", "docker", "ci", "server", "infra", "daemon"]),
        ("forge", ["forge", "dashboard", "neural", "agent", "telemetry"]),
        ("prospect", ["prospect", "osint", "pipeline", "craft", "client"]),
    ]:
        if any(kw in t for kw in kws):
            return domain
    return "general"


# ─── Recommendations Engine ─────────────────────────────────────────────────

def generate_recommendations(hermes: dict, claude: dict, antigravity: dict) -> list[dict]:
    recs = []

    total_in = sum(s["input_tokens"] for s in hermes["sessions"])
    total_cr = sum(s["cache_read"] for s in hermes["sessions"])
    if total_in > 0:
        cache_ratio = total_cr / total_in
        if cache_ratio < 0.3:
            recs.append({
                "priority": "HIGH",
                "category": "Cache",
                "title": "Faible utilisation du cache prompt",
                "detail": f"Seulement {cache_ratio:.0%} des input tokens sont lus du cache.",
                "action": "Regrouper les sessions similaires. Garder le même system prompt.",
                "savings_potential": "30-50% sur les input tokens"
            })

    for model, stats in hermes["by_model"].items():
        total = stats["in"] + stats["out"]
        if total > 100_000 and "opus" in model.lower():
            recs.append({
                "priority": "HIGH",
                "category": "Modèle",
                "title": f"Opus utilisé massivement ({total:,} tokens)",
                "detail": "Opus coûte 5x plus cher que Sonnet.",
                "action": "Utiliser Opus uniquement pour architecture complexe.",
                "savings_potential": f"~${stats['cost'] * 0.6:.2f}/jour"
            })

    hermes_out = sum(s["output_tokens"] for s in hermes["sessions"])
    if total_in > 0:
        ratio = hermes_out / total_in
        if ratio > 0.5:
            recs.append({
                "priority": "MEDIUM",
                "category": "Verbosité",
                "title": f"Ratio output/input élevé ({ratio:.1%})",
                "detail": "Les output tokens coûtent 5x plus cher que les input tokens.",
                "action": "Demander des réponses concises.",
                "savings_potential": "15-25% sur les output tokens"
            })

    small = [s for s in hermes["sessions"] if s["total"] < 500 and s["total"] > 0]
    if len(small) > len(hermes["sessions"]) * 0.3:
        recs.append({
            "priority": "LOW",
            "category": "Sessions",
            "title": f"{len(small)} micro-sessions (< 500 tokens)",
            "detail": "Chaque session a un overhead de contexte.",
            "action": "Regrouper les questions simples dans une même session.",
            "savings_potential": "5-10%"
        })

    total_tools = sum(s["tools"] for s in hermes["sessions"])
    total_msgs = sum(s["messages"] for s in hermes["sessions"])
    if total_msgs > 0 and total_tools / total_msgs > 0.8:
        recs.append({
            "priority": "MEDIUM",
            "category": "Tools",
            "title": f"Ratio tool calls/messages élevé ({total_tools/total_msgs:.1f})",
            "detail": "Chaque tool call génère des tokens.",
            "action": "Combiner les opérations: execute_code au lieu de multiples appels.",
            "savings_potential": "10-20%"
        })

    # Check for overconsumption patterns in task_details
    all_tasks = hermes.get("task_details", []) + claude.get("task_details", [])
    overconsuming = [t for t in all_tasks if t["delta_pct"] > 200 and t["actual_total"] > 50_000]
    if overconsuming:
        worst = max(overconsuming, key=lambda t: t["delta_pct"])
        recs.append({
            "priority": "HIGH",
            "category": "Surconsommation",
            "title": f"{len(overconsuming)} tâches à >200% de l'estimation",
            "detail": f"Pire cas: {worst['summary'][:60]} ({worst['delta_pct']:.0f}% au-dessus)",
            "action": "Décomposer les tâches complexes en sous-tâches. Limiter les retries.",
            "savings_potential": "Variable"
        })

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 3))
    return recs


# ─── Report Generator ───────────────────────────────────────────────────────

def generate_report(date_str: str, save: bool = False) -> str:
    day_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
    day_end = day_start + 86400

    hermes = collect_hermes(day_start, day_end)
    claude = collect_claude_code(day_start, day_end)
    antigravity = collect_antigravity(day_start, day_end)

    prev_start = day_start - 86400
    prev_hermes = collect_hermes(prev_start, day_start)
    prev_claude = collect_claude_code(prev_start, day_start)

    recs = generate_recommendations(hermes, claude, antigravity)

    lines = []
    w = lines.append

    w(f"══════════════════════════════════════════════════════════════")
    w(f"  RAPPORT JOURNALIER — {date_str}")
    w(f"  Forge Telemetry | Hermes + Claude Code + Antigravity")
    w(f"══════════════════════════════════════════════════════════════")
    w("")

    # ── Summary ──
    h_total = sum(s["total"] for s in hermes["sessions"])
    h_in = sum(s["input_tokens"] for s in hermes["sessions"])
    h_out = sum(s["output_tokens"] for s in hermes["sessions"])
    h_cr = sum(s["cache_read"] for s in hermes["sessions"])
    h_cost = sum(s["cost"] for s in hermes["sessions"])

    cc_total = sum(s["total"] for s in claude["sessions"])
    cc_in = sum(s["input_tokens"] for s in claude["sessions"])
    cc_out = sum(s["output_tokens"] for s in claude["sessions"])
    cc_cr = sum(s["cache_read"] for s in claude["sessions"])
    cc_cost = sum(s["cost"] for s in claude["sessions"])

    ag_count = len(antigravity["sessions"])

    grand_total = h_total + cc_total
    grand_cost = h_cost + cc_cost

    prev_h_total = sum(s["total"] for s in prev_hermes["sessions"])
    prev_cc_total = sum(s["total"] for s in prev_claude["sessions"])
    prev_grand = prev_h_total + prev_cc_total

    def _delta(curr, prev):
        if prev == 0:
            return " (nouveau)" if curr > 0 else ""
        pct = ((curr - prev) / prev) * 100
        arrow = "↑" if pct > 0 else "↓" if pct < 0 else "="
        return f" ({arrow}{abs(pct):.0f}% vs hier)"

    w("  ┌─────────────────────────────────────────────────────┐")
    w(f"  │  TOTAL:        {grand_total:>15,} tokens{_delta(grand_total, prev_grand):>16s} │")
    w(f"  │  Sessions:     {len(hermes['sessions']) + len(claude['sessions']):>15,}                       │")
    w(f"  │  Coût estimé:  ${grand_cost:>14,.2f}                       │")
    w("  └─────────────────────────────────────────────────────┘")
    w("")

    # ── DÉTAIL PAR TÂCHE ──
    all_tasks = []
    for t in hermes.get("task_details", []):
        all_tasks.append(t)
    for t in claude.get("task_details", []):
        all_tasks.append(t)
    for t in antigravity.get("task_details", []):
        all_tasks.append(t)

    # Sort by actual total descending
    all_tasks.sort(key=lambda t: t["actual_total"], reverse=True)

    w("  ══════════════════════════════════════════════════════")
    w("  DÉTAIL PAR TÂCHE — Estimé vs Réel")
    w("  ══════════════════════════════════════════════════════")
    w("")

    for i, t in enumerate(all_tasks, 1):
        # Emoji based on delta
        if t["actual_total"] == 0:
            emoji = "⚪"
        elif t["delta_pct"] < -20:
            emoji = "🟢"  # Under estimate (good)
        elif t["delta_pct"] < 50:
            emoji = "🟡"  # Close to estimate
        elif t["delta_pct"] < 200:
            emoji = "🟠"  # Over estimate
        else:
            emoji = "🔴"  # Way over estimate

        provider_tag = {"hermes": "Hermes", "claude-code": "Claude", "antigravity": "Gemini"}.get(t["provider"], "?")

        w(f"  {emoji} #{i} [{provider_tag}] {t['model']}")
        w(f"     Tâche: {t['summary']}")

        if t["actual_total"] > 0:
            billable = t.get("actual_billable", t["actual_in"] + t["actual_out"])
            w(f"     Estimé:   {t['est_total']:>12,} tokens (ce que la tâche devait coûter)")
            w(f"     Réel:     {billable:>12,} tokens facturés (in={t['actual_in']:,} out={t['actual_out']:,})")
            if t["actual_cache"] > 0:
                w(f"     Cache:    {t['actual_cache']:>12,} tokens (90% off — quasi-gratuit)")
            w(f"     Total:    {t['actual_total']:>12,} tokens (facturé + cache)")

            delta = billable - t["est_total"]
            if t["est_total"] > 0:
                if delta > 0:
                    w(f"     Delta:    +{delta:>11,} tokens facturés ({t['delta_pct']:+.0f}% au-dessus)")
                elif delta < 0:
                    w(f"     Delta:    {delta:>12,} tokens facturés ({t['delta_pct']:+.0f}% en-dessous — économie)")
                else:
                    w(f"     Delta:    Exactement l'estimation ✓")
            else:
                w(f"     Delta:   Pas d'estimation disponible")

            if t.get("messages"):
                w(f"     Messages: {t['messages']} | Coût: ${t['actual_cost']:.2f}")
            if t.get("user_messages"):
                w(f"     User: {t['user_messages']} msgs | Assistant: {t['assistant_messages']} msgs")
        else:
            w(f"     (Pas de données token disponibles)")

        w("")

    # ── AGGREGATE ESTIMATION SUMMARY ──
    total_est = sum(t["est_total"] for t in all_tasks if t["est_total"] > 0)
    total_actual = sum(t["actual_total"] for t in all_tasks)
    if total_est > 0:
        overall_delta = total_actual - total_est
        overall_pct = ((total_actual - total_est) / total_est) * 100
        w("  ┌─────────────────────────────────────────────────────┐")
        w(f"  │  ESTIMATION TOTALE:  {total_est:>12,} tokens              │")
        w(f"  │  RÉEL TOTAL:         {total_actual:>12,} tokens              │")
        if overall_delta > 0:
            w(f"  │  DELTA:             +{overall_delta:>12,} ({overall_pct:+.0f}%)              │")
        else:
            w(f"  │  DELTA:              {overall_delta:>12,} ({overall_pct:+.0f}%)              │")
        w("  └─────────────────────────────────────────────────────┘")
        w("")

    # ── By Provider ──
    w("  ── PAR PROVIDER ─────────────────────────────────────")
    w(f"  {'Provider':<16} {'Sessions':>8} {'Input':>14} {'Output':>14} {'Cache':>14} {'Cost':>10}")
    w(f"  {'─'*16} {'─'*8} {'─'*14} {'─'*14} {'─'*14} {'─'*10}")
    if hermes["sessions"]:
        w(f"  {'Hermes':<16} {len(hermes['sessions']):>8} {h_in:>14,} {h_out:>14,} {h_cr:>14,} ${h_cost:>8.2f}")
    if claude["sessions"]:
        w(f"  {'Claude Code':<16} {len(claude['sessions']):>8} {cc_in:>14,} {cc_out:>14,} {cc_cr:>14,} ${cc_cost:>8.2f}")
    if ag_count:
        ag_in = sum(s.get("actual_in", 0) for s in antigravity.get("task_details", []))
        ag_out = sum(s.get("actual_out", 0) for s in antigravity.get("task_details", []))
        w(f"  {'Antigravity':<16} {ag_count:>8} {ag_in:>14,} {ag_out:>14,} {'—':>14} {'(sub)':>10}")
    w("")

    # ── By Model (Hermes) ──
    if hermes["by_model"]:
        w("  ── HERMES PAR MODÈLE ────────────────────────────────")
        w(f"  {'Model':<28} {'Sess':>5} {'In':>12} {'Out':>12} {'Cache':>12} {'Cost':>10}")
        w(f"  {'─'*28} {'─'*5} {'─'*12} {'─'*12} {'─'*12} {'─'*10}")
        for model, stats in sorted(hermes["by_model"].items(), key=lambda x: x[1]["in"]+x[1]["out"], reverse=True):
            w(f"  {model:<28} {stats['count']:>5} {stats['in']:>12,} {stats['out']:>12,} {stats['cr']:>12,} ${stats['cost']:>8.2f}")
        w("")

    # ── By Model (Claude Code) ──
    if claude["by_model"]:
        w("  ── CLAUDE CODE PAR MODÈLE ───────────────────────────")
        w(f"  {'Model':<28} {'Sess':>5} {'In':>12} {'Out':>12} {'Cache R':>12} {'Cost':>10}")
        w(f"  {'─'*28} {'─'*5} {'─'*12} {'─'*12} {'─'*12} {'─'*10}")
        for model, stats in sorted(claude["by_model"].items(), key=lambda x: x[1]["in"]+x[1]["out"], reverse=True):
            w(f"  {model:<28} {stats['count']:>5} {stats['in']:>12,} {stats['out']:>12,} {stats['cr']:>12,} ${stats['cost']:>8.2f}")
        w("")

    # ── By Task Domain ──
    if hermes["by_task"]:
        w("  ── PAR DOMAINE ──────────────────────────────────────")
        w(f"  {'Domain':<16} {'Sess':>5} {'Input':>12} {'Output':>12} {'Cost':>10}")
        w(f"  {'─'*16} {'─'*5} {'─'*12} {'─'*12} {'─'*10}")
        for task, stats in sorted(hermes["by_task"].items(), key=lambda x: x[1]["in"]+x[1]["out"], reverse=True):
            w(f"  {task:<16} {stats['count']:>5} {stats['in']:>12,} {stats['out']:>12,} ${stats['cost']:>8.2f}")
        w("")

    # ── By Project (Claude Code) ──
    if claude["by_project"]:
        w("  ── CLAUDE CODE PAR PROJET ───────────────────────────")
        w(f"  {'Project':<35} {'Sess':>5} {'Input':>12} {'Output':>12} {'Cost':>10}")
        w(f"  {'─'*35} {'─'*5} {'─'*12} {'─'*12} {'─'*10}")
        for proj, stats in sorted(claude["by_project"].items(), key=lambda x: x[1]["in"]+x[1]["out"], reverse=True):
            w(f"  {proj[:35]:<35} {stats['count']:>5} {stats['in']:>12,} {stats['out']:>12,} ${stats['cost']:>8.2f}")
        w("")

    # ── RecursiveMAS Optimizer ──
    optimizer_stats_file = FORGE_ROOT / "05_STATE" / "optimizer_stats.json"
    if optimizer_stats_file.exists():
        try:
            opt = json.loads(optimizer_stats_file.read_text(encoding="utf-8"))
            w("  ── RECURSIVE OPTIMIZER (RecursiveMAS) ─────────────────")
            violations = opt.get("session_violations", 0)
            over_tokens = opt.get("over_limit_tokens", 0)
            est_save = opt.get("est_savings", 0)
            ss = opt.get("shared_state", {})
            w(f"    Sessions hors limites:  {violations}")
            w(f"    Tokens au-dessus:       {over_tokens:,}")
            w(f"    Économie estimée:       ~{est_save:,.0f} tokens")
            w(f"    Shared state NMP:       {ss.get('nmp_size_bytes', 0)} bytes ({ss.get('compression_ratio', 1)}× compression)")
            if opt.get("top_violations"):
                w(f"    Pires contrevenants:")
                for v in opt["top_violations"][:3]:
                    w(f"      • {v['title'][:45]} — {', '.join(v['issues'])}")
            w("")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # ── Recommendations ──
    w("  ══════════════════════════════════════════════════════")
    w("  RECOMMANDATIONS D'OPTIMISATION")
    w("  ══════════════════════════════════════════════════════")
    w("")

    if recs:
        for i, rec in enumerate(recs, 1):
            icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(rec["priority"], "⚪")
            w(f"  {icon} [{rec['priority']}] {rec['title']}")
            w(f"     Catégorie: {rec['category']}")
            w(f"     {rec['detail']}")
            w(f"     → Action: {rec['action']}")
            w(f"     Économie potentielle: {rec['savings_potential']}")
            w("")
    else:
        w("  Aucune recommandation — consommation optimale.")
        w("")

    # ── Efficiency Score ──
    efficiency = 0
    factors = []
    if h_total > 0:
        cache_eff = min(h_cr / h_total * 100, 100) if h_total > 0 else 0
        factors.append(("Cache utilization", cache_eff, 30))
        cost_eff = max(0, 100 - (grand_cost / max(grand_total, 1) * 1000))
        factors.append(("Cost efficiency", cost_eff, 30))
        session_eff = max(0, 100 - len([s for s in hermes["sessions"] if s["total"] < 500]) / max(len(hermes["sessions"]), 1) * 100)
        factors.append(("Session efficiency", session_eff, 20))
        model_eff = 100 if any("mimo" in m.lower() or "hermes" in m.lower() for m in hermes["by_model"]) else 50
        factors.append(("Free model usage", model_eff, 20))
        efficiency = sum(score * weight / 100 for _, score, weight in factors)

    w(f"  ── SCORE D'EFFICACITÉ: {efficiency:.0f}/100 ─────────────────────")
    for name, score, weight in factors:
        bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
        w(f"    {name:<22} {bar} {score:.0f}% (×{weight}%)")
    w("")

    # ── Projections ──
    if grand_total > 0:
        monthly_projected = grand_total * 30
        monthly_cost = grand_cost * 30
        w(f"  ── PROJECTION MENSUELLE ─────────────────────────────")
        w(f"    Tokens/mois:    {monthly_projected:>15,}")
        w(f"    Coût/mois:      ${monthly_cost:>14,.2f}")
        w(f"    Sessions/mois:  {(len(hermes['sessions']) + len(claude['sessions'])) * 30:>15,}")
        w("")

    w(f"══════════════════════════════════════════════════════════════")
    w(f"  Rapport généré: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"══════════════════════════════════════════════════════════════")

    report = "\n".join(lines)

    if save:
        report_path = REPORTS_DIR / f"token_report_{date_str}.md"
        report_path.write_text(report, encoding="utf-8")

    return report


def main():
    parser = argparse.ArgumentParser(description="Rapport journalier de tokens")
    parser.add_argument("--yesterday", action="store_true", help="Rapport d'hier")
    parser.add_argument("--date", type=str, help="Date au format YYYY-MM-DD")
    parser.add_argument("--save", action="store_true", help="Sauvegarder en .md")
    args = parser.parse_args()

    if args.date:
        date_str = args.date
    elif args.yesterday:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    report = generate_report(date_str, save=args.save)
    print(report)


if __name__ == "__main__":
    main()
