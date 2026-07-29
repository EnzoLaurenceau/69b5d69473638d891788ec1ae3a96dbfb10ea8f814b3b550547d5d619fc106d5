#!/usr/bin/env python
"""
forge_telemetry_daemon.py — Unified Telemetry Daemon for La Forge Dashboard
=============================================================================

Collects real-time telemetry from THREE sources:
  1. Hermes  — AppData/Local/hermes/state.db (sessions, tokens, costs)
  2. Claude Code — .claude/ (sessions, history, context-mode)
  3. Antigravity — .gemini/ (brain sessions, projects, state)

Writes unified dashboard data to: 05_STATE/dashboard_stats.json
Also updates: tool_index.json, experience_db.json, agent_tracker/

Run modes:
  --daemon       Run as background process (default)
  --install      Register as Windows Task Scheduler job (auto-start on boot)
  --uninstall    Remove the scheduled task
  --once         Run a single collection cycle and exit
  --status       Show daemon status

Author: Forge Telemetry System
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import argparse
import subprocess
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────
HOME = Path.home()
HERMES_DB = HOME / "AppData" / "Local" / "hermes" / "state.db"
CLAUDE_DIR = HOME / ".claude"
GEMINI_DIR = HOME / ".gemini"
FORGE_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = FORGE_ROOT / "05_STATE"
PID_FILE = STATE_DIR / "telemetry_daemon.pid"
LOG_FILE = STATE_DIR / "telemetry_daemon.log"

TASK_NAME = "ForgeTelemetryDaemon"

# Ensure dirs
STATE_DIR.mkdir(parents=True, exist_ok=True)
(STATE_DIR / "agent_tracker").mkdir(exist_ok=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().isoformat()

def _now_ts() -> float:
    return time.time()

def _load_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default

def _save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log(f"Failed to write temp file {tmp.name}: {e}")
        return

    # Retry replace on Windows to handle locks gracefully
    for i in range(5):
        try:
            if path.exists():
                try:
                    path.unlink()
                except OSError as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            tmp.replace(path)
            return
        except OSError:
            time.sleep(0.1)
            
    # Final fallback: direct write
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log(f"Failed direct write to {path.name}: {e}")

def _log(msg: str):
    line = f"[{_now_iso()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


# Real tool-call ledger + comparative hallucination detection (no invented
# metrics — see 00_CORE/forge_agents/tool_call_ledger.py and
# hallucination_compare.py). Import failure degrades gracefully: the
# ledger/hallucination-derived fields are simply omitted, never guessed.
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
try:
    from forge_agents.tool_call_ledger import ingest_hermes, build_ledger
    from forge_agents.hallucination_compare import (
        scan_ledger, ledger_covered_session_ids, save_findings,
        _load_hallucinations as _load_halluc_events)
except ImportError as e:
    _log(f"Warning: forge_agents ledger/hallucination modules not importable ({e}) "
         f"— ledger-derived fields will be omitted, not fabricated.")
    ingest_hermes = scan_ledger = ledger_covered_session_ids = None
    build_ledger = save_findings = _load_halluc_events = None

# Le scan lit ~1 000 enregistrements et en compare le texte : inutile de le
# refaire au rythme du dashboard (5 s). Une fois par minute suffit largement
# pour un tracker « temps réel » côté humain.
HALLUC_SCAN_INTERVAL_SEC = 60


# ─── Hermes Collector ────────────────────────────────────────────────────────

class HermesCollector:
    """Collects telemetry from Hermes state.db"""

    def __init__(self):
        self.db_path = HERMES_DB

    def _connect(self):
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None

    def collect_sessions(self, limit=100) -> list[dict]:
        conn = self._connect()
        if not conn:
            return []
        try:
            rows = conn.execute("""
                SELECT id, title, started_at, ended_at, model,
                       message_count, tool_call_count,
                       input_tokens, output_tokens,
                       cache_read_tokens, cache_write_tokens,
                       reasoning_tokens,
                       actual_cost_usd, estimated_cost_usd,
                       billing_provider, cwd, source, end_reason
                FROM sessions
                WHERE archived = 0 OR archived IS NULL
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            sessions = []
            for r in rows:
                sessions.append({
                    "session_id": r["id"],
                    "source": r["source"] or "hermes",
                    "title": r["title"] or "",
                    "started_at": r["started_at"],
                    "ended_at": r["ended_at"],
                    # Real column value, never guessed — None if the DB
                    # never recorded one (e.g. still running).
                    "end_reason": r["end_reason"],
                    "model": r["model"] or "",
                    "message_count": r["message_count"] or 0,
                    "tool_call_count": r["tool_call_count"] or 0,
                    "input_tokens": r["input_tokens"] or 0,
                    "output_tokens": r["output_tokens"] or 0,
                    "cache_read_tokens": r["cache_read_tokens"] or 0,
                    "cache_write_tokens": r["cache_write_tokens"] or 0,
                    "reasoning_tokens": r["reasoning_tokens"] or 0,
                    "actual_cost_usd": r["actual_cost_usd"] or 0,
                    "estimated_cost_usd": r["estimated_cost_usd"] or 0,
                    "billing_provider": r["billing_provider"] or "",
                    "cwd": r["cwd"] or "",
                    "provider": "hermes",
                })
            return sessions
        except Exception as e:
            _log(f"[Hermes] Error: {e}")
            return []
        finally:
            conn.close()

    def collect_stats(self) -> dict:
        sessions = self.collect_sessions(200)
        now = _now_ts()
        recent = [s for s in sessions if (s.get("started_at") or 0) > now - 86400]

        total_in = sum(s["input_tokens"] for s in sessions)
        total_out = sum(s["output_tokens"] for s in sessions)
        total_cache = sum(s["cache_read_tokens"] + s["cache_write_tokens"] for s in sessions)
        total_reasoning = sum(s["reasoning_tokens"] for s in sessions)

        return {
            "provider": "hermes",
            "session_count": len(sessions),
            "message_count": sum(s["message_count"] for s in sessions),
            "tool_call_count": sum(s["tool_call_count"] for s in sessions),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_tokens": total_cache,
            "reasoning_tokens": total_reasoning,
            "total_tokens": total_in + total_out + total_cache + total_reasoning,
            "total_cost_usd": round(sum(s["actual_cost_usd"] for s in sessions), 4),
            "sessions_24h": len(recent),
            "tokens_24h": sum(s["input_tokens"] + s["output_tokens"] for s in recent),
            "cost_24h": round(sum(s["actual_cost_usd"] for s in recent), 4),
            "models": list(set(s["model"] for s in sessions if s["model"])),
            "last_sessions": sessions[:10],
        }


# ─── Claude Code Collector ───────────────────────────────────────────────────

class ClaudeCodeCollector:
    """Collects telemetry from Claude Code (.claude/)
    
    Data sources:
    - sessions/*.json        — live session descriptors (pid, sessionId, cwd, startedAt)
    - projects/*//*.jsonl    — conversation logs with token usage in assistant messages
    - history.jsonl          — command history
    - context-mode/sessions/*.db — context-mode session DBs
    """

    def __init__(self):
        self.claude_dir = CLAUDE_DIR
        self.sessions_dir = CLAUDE_DIR / "sessions"
        self.projects_dir = CLAUDE_DIR / "projects"
        self.history_file = CLAUDE_DIR / "history.jsonl"

    def _scan_live_sessions(self) -> list[dict]:
        """Read live session descriptors from sessions/*.json."""
        sessions = []
        if not self.sessions_dir.exists():
            return sessions
        for f in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("sessionId", f.stem),
                    "source": "claude-code",
                    "provider": "claude-code",
                    "pid": data.get("pid"),
                    "cwd": data.get("cwd", ""),
                    "started_at": (data.get("startedAt", 0) / 1000) if data.get("startedAt", 0) > 1e12 else data.get("startedAt", 0),
                    "version": data.get("version", ""),
                    "kind": data.get("kind", ""),
                    "entrypoint": data.get("entrypoint", ""),
                    "name": data.get("name", ""),
                    "model": "claude",
                })
            except (json.JSONDecodeError, OSError) as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return sessions

    def _scan_conversations(self) -> list[dict]:
        """Parse project conversation JSONL files for tokens, models, messages."""
        convos = []  # one dict per conversation file
        if not self.projects_dir.exists():
            return convos

        for jsonl_file in sorted(self.projects_dir.rglob("*.jsonl"), 
                                  key=lambda f: f.stat().st_mtime, reverse=True):
            session_id = jsonl_file.stem
            project = jsonl_file.parent.name

            msg_count = 0
            user_count = 0
            assistant_count = 0
            total_in = 0
            total_out = 0
            total_cache_read = 0
            total_cache_create = 0
            model = ""
            first_ts = 0
            last_ts = 0
            title = ""

            try:
                with open(jsonl_file, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        etype = entry.get("type", "")
                        msg_count += 1

                        # Track timestamps from UUIDs (first seen = oldest)
                        if not first_ts:
                            first_ts = jsonl_file.stat().st_mtime

                        if etype == "user":
                            user_count += 1
                        elif etype == "assistant":
                            assistant_count += 1
                            msg = entry.get("message", {})
                            # Extract model
                            m = msg.get("model", "")
                            if m and not model:
                                model = m
                            # Extract token usage from the message's usage field
                            usage = msg.get("usage", {})
                            if not usage:
                                # Also check top-level usage
                                usage = entry.get("usage", {})
                            if usage:
                                total_in += usage.get("input_tokens", 0)
                                total_out += usage.get("output_tokens", 0)
                                total_cache_read += usage.get("cache_read_input_tokens", 0)
                                total_cache_create += usage.get("cache_creation_input_tokens", 0)
                        elif etype == "custom-title":
                            title = entry.get("title", "")
                        elif etype == "ai-title":
                            title = entry.get("title", title)
                        elif etype == "result":
                            # Result entries may have summary info
                            result = entry.get("result", {})
                            if isinstance(result, dict) and not title:
                                title = result.get("summary", "")[:80]

                last_ts = jsonl_file.stat().st_mtime

            except OSError:
                continue

            if msg_count == 0:
                continue

            convos.append({
                "session_id": session_id,
                "source": "claude-code",
                "provider": "claude-code",
                "project": project,
                "title": title or session_id[:12],
                "started_at": first_ts,
                "ended_at": last_ts,
                "model": model or "claude",
                "message_count": msg_count,
                "user_messages": user_count,
                "assistant_messages": assistant_count,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "cache_read_tokens": total_cache_read,
                "cache_creation_tokens": total_cache_create,
                "total_tokens": total_in + total_out + total_cache_read + total_cache_create,
            })

        return convos

    def _scan_history(self) -> list[dict]:
        """Read last N entries from history.jsonl."""
        entries = []
        if not self.history_file.exists():
            return entries
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError as exc:
                            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        except OSError as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return entries[-50:]

    def collect_stats(self) -> dict:
        live_sessions = self._scan_live_sessions()
        convos = self._scan_conversations()
        history = self._scan_history()

        total_in = sum(c.get("input_tokens", 0) for c in convos)
        total_out = sum(c.get("output_tokens", 0) for c in convos)
        total_cache_read = sum(c.get("cache_read_tokens", 0) for c in convos)
        total_cache_create = sum(c.get("cache_creation_tokens", 0) for c in convos)

        # Estimate cost: Claude pricing (approximate)
        # Opus: $15/M in, $75/M out; Sonnet: $3/M in, $15/M out
        # Use blended average since we mix models
        cost_estimate = (total_in * 6 + total_out * 30) / 1_000_000  # rough blend

        return {
            "provider": "claude-code",
            "session_count": len(convos),
            "live_session_count": len(live_sessions),
            "conversation_count": len(convos),
            "message_count": sum(c.get("message_count", 0) for c in convos),
            "history_entries": len(history),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_read_tokens": total_cache_read,
            "cache_creation_tokens": total_cache_create,
            "total_tokens": total_in + total_out + total_cache_read + total_cache_create,
            "total_cost_usd": round(cost_estimate, 4),
            "models": list(set(c.get("model", "") for c in convos if c.get("model"))),
            "projects": list(set(c.get("project", "") for c in convos if c.get("project"))),
            "last_sessions": convos[:10],
            "live_sessions": live_sessions,
            "recent_commands": history[-10:],
        }


# ─── Antigravity Collector ───────────────────────────────────────────────────

class AntigravityCollector:
    """Collects telemetry from Antigravity/Gemini (.gemini/)"""

    def __init__(self):
        self.gemini_dir = GEMINI_DIR
        self.brain_dir = GEMINI_DIR / "antigravity" / "brain"

    def _scan_brain_sessions(self) -> list[dict]:
        """Scan antigravity brain sessions."""
        sessions = []
        if not self.brain_dir.exists():
            return sessions

        for entry in sorted(self.brain_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            session_id = entry.name

            # Look for any metadata files
            meta = {}
            for fname in ["meta.json", "session.json", "config.json"]:
                fpath = entry / fname
                if fpath.exists():
                    try:
                        meta.update(json.loads(fpath.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

            # Check for instruction files as activity indicators
            files = list(entry.glob("*.md")) + list(entry.glob("*.json"))
            mtime = max((f.stat().st_mtime for f in files), default=entry.stat().st_mtime)

            sessions.append({
                "session_id": session_id,
                "source": "antigravity",
                "provider": "antigravity",
                "title": meta.get("title", session_id[:12]),
                "started_at": meta.get("started_at", mtime),
                "model": meta.get("model", "gemini"),
                "file_count": len(files),
                "last_activity": mtime,
            })

            if len(sessions) >= 50:
                break

        return sessions

    def _scan_projects(self) -> list[str]:
        """Read project list from projects.json."""
        pf = self.gemini_dir / "projects.json"
        if not pf.exists():
            return []
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            return list(data.get("projects", {}).values())
        except (json.JSONDecodeError, OSError):
            return []

    def collect_stats(self) -> dict:
        sessions = self._scan_brain_sessions()
        projects = self._scan_projects()

        return {
            "provider": "antigravity",
            "session_count": len(sessions),
            "project_count": len(projects),
            "projects": projects,
            "last_sessions": sessions[:10],
        }


# ─── Forge-Local Collector (headless forge / MiMo / pipeline LLM runs) ───────

class ForgeLocalCollector:
    """Collects forge-internal LLM sessions from 08_LOGS/tokens/*.json.

    These are runs produced by run_forge.py / forge_call() / token_tracker
    (models: ds2api, groq, gemini, claude, mimo…) that never went through
    the Hermes CLI, so no other collector sees them. TKL_antigravity_* files
    are SKIPPED here — those same sessions are already counted by
    AntigravityCollector, and double-counting would inflate every total.
    List-shaped files (mimo pipeline run_*.json = prospects/latency, not LLM
    tokens) are skipped too: they carry no token/cost signal to aggregate."""

    def __init__(self):
        self.tokens_dir = FORGE_ROOT / "08_LOGS" / "tokens"

    def collect_sessions(self, limit: int = 200) -> list[dict]:
        sessions = []
        if not self.tokens_dir.exists():
            return sessions
        for f in sorted(self.tokens_dir.glob("*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            if f.name.startswith("TKL_antigravity_"):
                continue  # dedupe: already in antigravity provider
            data = _load_json(f, None)
            if not isinstance(data, dict):
                continue  # list-shaped mimo pipeline runs carry no LLM tokens
            raw = data.get("raw_logs", [])
            if not raw:
                continue
            total_in = sum(r.get("input_tokens", 0) for r in raw)
            total_out = sum(r.get("output_tokens", 0) for r in raw)
            # cost_usd is a real per-call field written by token_tracker; None
            # where a call never recorded one — summed as 0, never guessed.
            total_cost = sum(r.get("cost_usd", 0) or 0 for r in raw)
            model = raw[0].get("model", "") if raw else ""
            # Real recorded counts when present (retrospective ingests store
            # them); else fall back to the concrete number of logged calls —
            # never an invented multiplier.
            msg_count = data.get("retro_msg_count", len(raw) * 2)
            tool_calls = data.get("retro_tool_calls", 0)
            started_at = f.stat().st_mtime
            if raw and raw[0].get("timestamp"):
                ts = raw[0]["timestamp"]
                try:
                    if isinstance(ts, str) and "T" in ts:
                        started_at = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")).timestamp()
                    elif isinstance(ts, (int, float)):
                        started_at = ts
                except (ValueError, TypeError) as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            sessions.append({
                "session_id": data.get("session_id") or f.stem,
                "source": "forge",
                "provider": "forge",
                "title": data.get("task") or f.stem,
                "started_at": started_at,
                "ended_at": None,
                "end_reason": None,
                "model": model or "unknown",
                "message_count": msg_count,
                "tool_call_count": tool_calls,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
                "actual_cost_usd": round(total_cost, 4),
            })
            if len(sessions) >= limit:
                break
        return sessions

    def collect_stats(self) -> dict:
        sessions = self.collect_sessions()
        total_in = sum(s["input_tokens"] for s in sessions)
        total_out = sum(s["output_tokens"] for s in sessions)
        return {
            "provider": "forge",
            "session_count": len(sessions),
            "message_count": sum(s["message_count"] for s in sessions),
            "tool_call_count": sum(s["tool_call_count"] for s in sessions),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "total_cost_usd": round(sum(s["actual_cost_usd"] for s in sessions), 4),
            "models": list(set(s["model"] for s in sessions if s["model"])),
            "last_sessions": sessions[:10],
        }


# ─── Unified Dashboard Writer ────────────────────────────────────────────────

class ForgeTelemetryDaemon:
    """Unified daemon that collects from all sources and writes dashboard data."""

    def __init__(self, interval: int = 5):
        self.interval = interval
        self.running = False
        self.hermes = HermesCollector()
        self.claude = ClaudeCodeCollector()
        self.antigravity = AntigravityCollector()
        self.forge = ForgeLocalCollector()

    def collect_all(self) -> dict:
        """Collect from all three sources and merge."""
        hermes_stats = self.hermes.collect_stats()
        claude_stats = self.claude.collect_stats()
        antigravity_stats = self.antigravity.collect_stats()
        forge_stats = self.forge.collect_stats()

        # Unified dashboard stats
        dashboard = {
            "timestamp": _now_iso(),
            "daemon_version": "2.1.0",
            "sources": {
                "hermes": hermes_stats,
                "claude_code": claude_stats,
                "antigravity": antigravity_stats,
                "forge": forge_stats,
            },
            # Aggregated totals — every provider that carries the signal is
            # summed. Previously messages/tool_calls were Hermes-only, which
            # silently dropped all Claude Code + forge-headless activity from
            # the headline numbers (the "missing history" bug).
            "total_sessions": (
                hermes_stats["session_count"]
                + claude_stats["session_count"]
                + antigravity_stats["session_count"]
                + forge_stats["session_count"]
            ),
            "total_messages": (
                hermes_stats["message_count"]
                + claude_stats.get("message_count", 0)
                + forge_stats["message_count"]
            ),
            "total_tool_calls": (
                hermes_stats["tool_call_count"]
                + forge_stats["tool_call_count"]
            ),
            "total_input_tokens": (
                hermes_stats["input_tokens"] + claude_stats["input_tokens"]
                + forge_stats["input_tokens"]
            ),
            "total_output_tokens": (
                hermes_stats["output_tokens"] + claude_stats["output_tokens"]
                + forge_stats["output_tokens"]
            ),
            "total_tokens": (
                hermes_stats["total_tokens"] + claude_stats["total_tokens"]
                + forge_stats["total_tokens"]
            ),
            "total_cost_usd": round(
                hermes_stats["total_cost_usd"] + claude_stats["total_cost_usd"]
                + forge_stats["total_cost_usd"], 4
            ),
            # 24h window (Hermes only — others don't have reliable timestamps)
            "recent_sessions_24h": hermes_stats["sessions_24h"],
            "recent_tokens_24h": hermes_stats["tokens_24h"],
            "recent_cost_24h": hermes_stats["cost_24h"],
            # Models across all sources
            "models_used": list(set(
                hermes_stats.get("models", [])
                + claude_stats.get("models", [])
                + forge_stats.get("models", [])
            )),
            # Provider breakdown
            "provider_summary": {
                "hermes": {
                    "sessions": hermes_stats["session_count"],
                    "tokens": hermes_stats["total_tokens"],
                    "cost_usd": hermes_stats["total_cost_usd"],
                },
                "claude_code": {
                    "sessions": claude_stats["session_count"],
                    "tokens": claude_stats["total_tokens"],
                    "cost_usd": claude_stats["total_cost_usd"],
                },
                "forge": {
                    "sessions": forge_stats["session_count"],
                    "tokens": forge_stats["total_tokens"],
                    "cost_usd": forge_stats["total_cost_usd"],
                },
                "antigravity": {
                    "sessions": antigravity_stats["session_count"],
                    "projects": antigravity_stats["project_count"],
                },
            },
            # Last sessions across all (sorted by time)
            "last_sessions": sorted(
                hermes_stats.get("last_sessions", [])
                + claude_stats.get("last_sessions", [])
                + forge_stats.get("last_sessions", [])
                + antigravity_stats.get("last_sessions", []),
                key=lambda s: s.get("started_at", 0) or 0,
                reverse=True,
            )[:15],
        }

        return dashboard

    def update_dashboard(self):
        """Collect and write all dashboard data."""
        dashboard = self.collect_all()
        _save_json(STATE_DIR / "dashboard_stats.json", dashboard)

        # Also update tool_index and experience_db (from Hermes data)
        self._update_tool_index(dashboard)
        self._update_experience_db(dashboard)
        self._update_agent_tracker(dashboard)
        self._update_sprint_data(dashboard)
        
        # RecursiveMAS optimizer integration
        self._update_optimizer(dashboard)

        # Détection d'hallucinations — LE producteur du tracker temps réel.
        # Avant : personne n'appelait cette chaîne. Le daemon comptait les
        # findings pour les stats mais n'en persistait aucun, et
        # hermes_session_tracker.update_hallucinations() (qui le faisait)
        # n'était référencé nulle part → dernier événement figé au 2026-07-18
        # alors que 1 586 findings inédits attendaient dans le ledger.
        self._update_hallucinations()

        _log(
            f"Dashboard updated: "
            f"{dashboard['total_sessions']} sessions, "
            f"{dashboard['total_messages']} messages, "
            f"{dashboard['total_tokens']} tokens"
        )

    _last_halluc_scan: float = 0.0

    def _update_hallucinations(self, force: bool = False):
        """Reconstruit le ledger, scanne les revendications non groundées,
        dédoublonne et persiste. Throttlé à HALLUC_SCAN_INTERVAL_SEC.

        Le fichier écrit ici est surveillé par `_hallucination_watcher()` dans
        09_WEB/server.py, qui diffuse les nouveaux événements en WebSocket —
        c'est ce couplage fichier→watcher qui rend le tracker temps réel sans
        que le producteur ait à connaître le transport.
        """
        if scan_ledger is None or save_findings is None or _load_halluc_events is None:
            return []
        now = time.time()
        if not force and (now - self._last_halluc_scan) < HALLUC_SCAN_INTERVAL_SEC:
            return []
        self._last_halluc_scan = now

        try:
            if build_ledger is not None:
                build_ledger()          # ingère Hermes + Claude Code → JSONL
            findings = scan_ledger()
            existing = _load_halluc_events()

            def _fp(e: dict) -> tuple:
                ctx = e.get("context") or {}
                return (e.get("agent"), e.get("node"), e.get("root_cause"),
                        ctx.get("session_id"), ctx.get("timestamp"))

            seen = {_fp(e) for e in existing}
            new = [f for f in findings if _fp(f) not in seen]
            saved = save_findings(new) if new else []
            if saved:
                _log(f"Hallucination scan: {len(findings)} finding(s) in ledger, "
                     f"{len(saved)} new event(s) saved")
            return saved
        except Exception as e:
            _log(f"Warning: hallucination scan failed ({e}) — no event fabricated")
            return []

    def _update_tool_index(self, dashboard: dict):
        """Update tool usage index from REAL tool-call events
        (tool_call_ledger.ingest_hermes()) — tallies literal tool_name
        values recorded in the Hermes DB. Never guesses usage from
        session-title keyword matching (that could attribute a tool that
        was never actually called). Non-matching entries are left
        untouched — no evidence either way, and forcing them to 0 would
        itself be an unverified claim."""
        tool_index = _load_json(STATE_DIR / "tool_index.json", [])
        if not isinstance(tool_index, list):
            tool_index = []

        if ingest_hermes is None:
            _log("Warning: tool_call_ledger not importable — skipping real tool usage update")
            _save_json(STATE_DIR / "tool_index.json", tool_index)
            return

        records = ingest_hermes()
        counts: dict[str, int] = {}
        last_used_ts: dict[str, float] = {}
        for rec in records:
            name = rec.get("tool_name")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            ts = rec.get("timestamp")
            if ts and (name not in last_used_ts or ts > last_used_ts[name]):
                last_used_ts[name] = ts

        for tool in tool_index:
            name = tool.get("name", "")
            if name in counts:
                tool["use_count"] = counts[name]
                ts = last_used_ts.get(name)
                if ts:
                    tool["last_used"] = datetime.fromtimestamp(ts).isoformat()

        _save_json(STATE_DIR / "tool_index.json", tool_index)

    def _update_experience_db(self, dashboard: dict):
        """Update experience database."""
        exp_db = _load_json(STATE_DIR / "experience_db.json", {"experiences": []})
        existing_ids = {e.get("id") for e in exp_db.get("experiences", [])}

        for session in dashboard.get("last_sessions", []):
            sid = session.get("session_id", "")[:12]
            if sid in existing_ids:
                continue
            exp_db.setdefault("experiences", []).append({
                "id": sid,
                "task": session.get("title", "Unknown"),
                # Real end_reason column value (None if the DB never
                # recorded one) — never assumed "success" just because a
                # row exists. quality_score is dropped entirely: no
                # ground-truth quality signal exists in the Hermes DB, so
                # inventing one would violate the no-invented-data
                # requirement (dashboard already tolerates a missing key).
                "outcome": session.get("end_reason"),
                "tokens_used": session.get("input_tokens", 0) + session.get("output_tokens", 0),
                "domain": self._detect_domain(session.get("title", "")),
                "provider": session.get("provider", "unknown"),
                "timestamp": _now_iso(),
                "metadata": {
                    "model": session.get("model", ""),
                    "source": session.get("source", ""),
                },
            })

        exp_db["experiences"] = exp_db["experiences"][-200:]
        _save_json(STATE_DIR / "experience_db.json", exp_db)

    def _update_agent_tracker(self, dashboard: dict):
        """Update agent tracker history."""
        history_file = STATE_DIR / "agent_tracker" / "history.json"
        history = _load_json(history_file, {"tasks": []})
        existing_names = {t.get("task_name") for t in history.get("tasks", [])}

        covered = ledger_covered_session_ids() if ledger_covered_session_ids else set()

        for session in dashboard.get("last_sessions", [])[:10]:
            task_name = session.get("title", "Unknown")
            if task_name in existing_names:
                continue

            sid = session.get("session_id", "")
            hfc = len(scan_ledger(session_id=sid)) if (scan_ledger and sid in covered) else None

            history.setdefault("tasks", []).append({
                "task_name": task_name,
                "provider": session.get("provider", "unknown"),
                "started_at": session.get("started_at"),
                # Real ended_at (only populated for Hermes-sourced sessions,
                # which have the real DB column) — never _now_iso(), which
                # would falsely assert "this session ended right now".
                "ended_at": session.get("ended_at"),
                "agents_involved": [session.get("provider", "unknown")],
                # Real end_reason column value (None if unavailable/still
                # running) — never a hardcoded "completed" narrative.
                "status": session.get("end_reason"),
                # Real, checked count of concrete claim-vs-tool-result
                # mismatches for this session. None means "not checked" (no
                # ledger coverage for this session_id), never a guessed 0.
                "hallucination_findings_count": hfc,
            })

        history["tasks"] = history["tasks"][-50:]
        _save_json(history_file, history)

    def _update_sprint_data(self, dashboard: dict):
        """Update sprint/token data."""
        sprint_file = STATE_DIR / "token_sprints.json"
        sprints = _load_json(sprint_file, [])
        existing_ids = {s.get("sprint_id") for s in sprints}

        for session in dashboard["sources"]["hermes"].get("last_sessions", []):
            sid = session.get("session_id", "")
            if sid in existing_ids:
                continue
            sprints.append({
                "sprint_id": sid,
                "task_id": session.get("title", "Unknown"),
                "model": session.get("model", "unknown"),
                "provider": session.get("provider", "hermes"),
                "tokens_actual_in": session.get("input_tokens", 0),
                "tokens_actual_out": session.get("output_tokens", 0),
                "cost_actual_usd": session.get("actual_cost_usd", 0),
                "ts": _now_iso(),
            })

        sprints = sprints[-200:]
        _save_json(sprint_file, sprints)

    @staticmethod
    def _detect_domain(title: str) -> str:
        t = title.lower()
        for domain, keywords in [
            ("coding", ["code", "python", "javascript", "debug", "fix", "script"]),
            ("research", ["research", "analyze", "study", "search"]),
            ("writing", ["write", "content", "blog", "article", "doc"]),
            ("design", ["design", "ui", "ux", "landing", "css"]),
            ("security", ["security", "audit", "pentest", "vuln", "bounty"]),
            ("bot", ["bot", "telegram", "discord", "automation"]),
            ("devops", ["deploy", "docker", "ci", "server", "infra"]),
        ]:
            if any(kw in t for kw in keywords):
                return domain
        return "general"

    def _update_optimizer(self, dashboard: dict):
        """Run RecursiveMAS optimizer checks and write results."""
        try:
            # Import optimizer
            sys.path.insert(0, str(FORGE_ROOT / "scripts"))
            from recursive_optimizer import SharedStateManager, SessionLimiter, to_nmp
            from datetime import datetime as _dt
            
            # Update shared state
            shared = SharedStateManager()
            shared.set_shared("dashboard", {
                "sessions": dashboard.get("total_sessions", 0),
                "tokens": dashboard.get("total_tokens", 0),
                "cost": dashboard.get("total_cost_usd", 0),
            })
            
            # Check session limits
            limiter = SessionLimiter()
            violations = limiter.check_sessions()
            
            # Write optimizer stats
            optimizer_stats = {
                "timestamp": _dt.now().isoformat(),
                "shared_state": shared.get_stats(),
                "session_violations": len(violations),
                "over_limit_tokens": sum(v.get("tokens", 0) for v in violations),
                "est_savings": sum(v.get("tokens", 0) for v in violations) * 0.6,
                "top_violations": [
                    {"title": v["title"][:50], "issues": v["issues"]}
                    for v in violations[:5]
                ],
            }
            _save_json(STATE_DIR / "optimizer_stats.json", optimizer_stats)
            
        except Exception as e:
            _log(f"[Optimizer] error: {e}")

    def run_daemon(self):
        """Run as a long-lived daemon process."""
        self.running = True

        # Write PID file
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

        _log("=" * 60)
        _log("FORGE TELEMETRY DAEMON v2.0 — Starting")
        _log(f"  Hermes:      {HERMES_DB}")
        _log(f"  Claude Code: {CLAUDE_DIR}")
        _log(f"  Antigravity: {GEMINI_DIR}")
        _log(f"  Interval:    {self.interval}s")
        _log(f"  PID:         {os.getpid()}")
        _log("=" * 60)

        # Handle graceful shutdown
        def _shutdown(signum, frame):
            _log("Shutdown signal received, stopping...")
            self.running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        while self.running:
            try:
                self.update_dashboard()
            except Exception as e:
                _log(f"Error in collection cycle: {e}")
            time.sleep(self.interval)

        # Cleanup
        if PID_FILE.exists():
            PID_FILE.unlink()
        _log("Daemon stopped.")

    def run_once(self):
        """Single collection cycle."""
        _log("Running single collection cycle...")
        self.update_dashboard()
        _log("Done.")


# ─── Windows Task Scheduler Integration ─────────────────────────────────────

def install_task():
    """Register as Windows Task Scheduler job (auto-start on boot)."""
    python_exe = sys.executable
    script_path = str(Path(__file__).resolve())

    # Delete existing task if present
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True
    )

    # Create task: run at logon, repeat every 1 minute indefinitely
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{python_exe}" "{script_path}" --daemon',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
        "/F",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        _log(f"✓ Task '{TASK_NAME}' registered. Will start on logon.")
        _log(f"  To start now: schtasks /Run /TN {TASK_NAME}")
    else:
        _log(f"✗ Failed to register task: {result.stderr}")
        # Fallback: create a startup shortcut
        _create_startup_shortcut(python_exe, script_path)


def _create_startup_shortcut(python_exe: str, script_path: str):
    """Fallback: create a .bat in Windows Startup folder."""
    startup = Path(os.environ.get("APPDATA", "")) / \
              "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    bat_path = startup / "ForgeTelemetryDaemon.bat"

    bat_content = f'@echo off\nstart /min "" "{python_exe}" "{script_path}" --daemon\n'
    bat_path.write_text(bat_content, encoding="utf-8")
    _log(f"✓ Startup shortcut created: {bat_path}")


def uninstall_task():
    """Remove the scheduled task."""
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        _log(f"✓ Task '{TASK_NAME}' removed.")
    else:
        _log(f"Task not found or error: {result.stderr}")

    # Also remove startup shortcut
    startup = Path(os.environ.get("APPDATA", "")) / \
              "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    bat_path = startup / "ForgeTelemetryDaemon.bat"
    if bat_path.exists():
        bat_path.unlink()
        _log(f"✓ Startup shortcut removed: {bat_path}")


def show_status():
    """Show daemon status."""
    print("=" * 50)
    print("FORGE TELEMETRY DAEMON — Status")
    print("=" * 50)

    # Check PID file
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        # Check if process is alive
        try:
            os.kill(int(pid), 0)
            print(f"  Daemon:    RUNNING (PID {pid})")
        except (OSError, ValueError):
            print(f"  Daemon:    STALE PID file (process {pid} not found)")
    else:
        print("  Daemon:    NOT RUNNING")

    # Check scheduled task
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  Task:      REGISTERED")
    else:
        print(f"  Task:      NOT REGISTERED")

    # Check data freshness
    stats_file = STATE_DIR / "dashboard_stats.json"
    if stats_file.exists():
        try:
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
            ts = stats.get("timestamp", "unknown")
            print(f"  Last update: {ts}")
            print(f"  Sessions:    {stats.get('total_sessions', 0)}")
            print(f"  Messages:    {stats.get('total_messages', 0)}")
            print(f"  Tokens:      {stats.get('total_tokens', 0):,}")
            print(f"  Cost:        ${stats.get('total_cost_usd', 0):.4f}")

            providers = stats.get("provider_summary", {})
            for name, ps in providers.items():
                print(f"    [{name}] sessions={ps.get('sessions', 0)} "
                      f"tokens={ps.get('tokens', 0):,} "
                      f"cost=${ps.get('cost_usd', 0):.4f}")
        except Exception:
            print("  Stats:     CORRUPT")
    else:
        print("  Stats:     NO DATA")

    print("=" * 50)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Forge Telemetry Daemon — Unified Hermes/Claude/Antigravity tracking"
    )
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--install", action="store_true", help="Register as Windows scheduled task")
    parser.add_argument("--uninstall", action="store_true", help="Remove scheduled task")
    parser.add_argument("--once", action="store_true", help="Run single collection cycle")
    parser.add_argument("--status", action="store_true", help="Show daemon status")
    parser.add_argument("--interval", type=int, default=5, help="Collection interval in seconds (default: 5)")
    args = parser.parse_args()

    if args.install:
        install_task()
        # Also run once to populate data immediately
        daemon = ForgeTelemetryDaemon()
        daemon.run_once()
    elif args.uninstall:
        uninstall_task()
    elif args.status:
        show_status()
    elif args.once:
        daemon = ForgeTelemetryDaemon(interval=args.interval)
        daemon.run_once()
    else:
        # Default: run as daemon
        daemon = ForgeTelemetryDaemon(interval=args.interval)
        daemon.run_daemon()


if __name__ == "__main__":
    main()
