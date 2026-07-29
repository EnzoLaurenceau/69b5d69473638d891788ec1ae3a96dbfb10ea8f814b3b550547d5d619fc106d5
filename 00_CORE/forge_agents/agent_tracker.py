"""
agent_tracker.py — Agent Performance Tracker & Prompt Optimizer
================================================================

Tracks every agent invocation across multi-agent tasks.
Scores quality, detects drift, and adjusts future prompts.

Usage:
    # Start tracking a multi-agent task
    python agent_tracker.py start --task "build landing page"

    # Log an agent invocation
    python agent_tracker.py log --agent senior_dev --task "write CSS" \
        --expected "responsive CSS with HELB vars" \
        --actual "file written: main.css (245 lines)" \
        --score 8.5 --tokens 1200

    # End task — generate report + prompt adjustments
    python agent_tracker.py end

    # View agent history
    python agent_tracker.py history --agent senior_dev

    # Generate prompt adjustments for an agent
    python agent_tracker.py adjust --agent senior_dev

    # Full report of last task
    python agent_tracker.py report
"""

from __future__ import annotations
import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = FORGE_ROOT / "05_STATE"
TRACKER_DIR = state_path("agent_tracker")
HISTORY_FILE = TRACKER_DIR / "history.json"
ADJUSTMENTS_FILE = TRACKER_DIR / "prompt_adjustments.json"
CURRENT_TASK_FILE = TRACKER_DIR / "current_task.json"

# Ensure dirs
TRACKER_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat()


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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Current Task Management ──────────────────────────────────────────────

def start_task(task_name: str, agents: list[str] | None = None) -> dict:
    """Start tracking a multi-agent task."""
    task = {
        "task_name": task_name,
        "started_at": _now(),
        "agents_involved": agents or [],
        "invocations": [],
        "status": "running",
    }
    _save_json(CURRENT_TASK_FILE, task)
    return task


def end_task() -> dict:
    """End current task, generate report, compute adjustments."""
    task = _load_json(CURRENT_TASK_FILE)
    if not task or not task.get("task_name"):
        return {"error": "no active task"}

    task["ended_at"] = _now()
    task["status"] = "completed"

    # Compute per-agent stats
    agent_stats = _compute_agent_stats(task)
    task["agent_stats"] = agent_stats

    # Generate prompt adjustments
    adjustments = _generate_adjustments(task)
    task["prompt_adjustments"] = adjustments

    # Save to history
    _append_to_history(task)

    # Save adjustments
    _save_adjustments(adjustments)

    # Clear current task
    CURRENT_TASK_FILE.unlink(missing_ok=True)

    return task


# ── Invocation Logging ───────────────────────────────────────────────────

def log_invocation(
    agent: str,
    task: str,
    expected: str,
    actual: str,
    score: float,
    tokens: int = 0,
    tools_used: list[str] | None = None,
    errors: list[str] | None = None,
    duration_ms: int = 0,
) -> dict:
    """Log a single agent invocation."""
    current = _load_json(CURRENT_TASK_FILE)
    if not current.get("task_name"):
        # Auto-start if no active task
        current = start_task(f"auto_{agent}_{datetime.now().strftime('%H%M%S')}")

    invocation = {
        "agent": agent,
        "task": task,
        "expected": expected,
        "actual": actual,
        "score": score,  # 0-10
        "tokens": tokens,
        "tools_used": tools_used or [],
        "errors": errors or [],
        "duration_ms": duration_ms,
        "timestamp": _now(),
        "quality": _classify_quality(score),
    }

    current.setdefault("invocations", []).append(invocation)
    if agent not in current.get("agents_involved", []):
        current.setdefault("agents_involved", []).append(agent)

    _save_json(CURRENT_TASK_FILE, current)
    return invocation


def _classify_quality(score: float) -> str:
    """Classify score into quality tier."""
    if score >= 9.0:
        return "excellent"
    elif score >= 7.5:
        return "good"
    elif score >= 6.0:
        return "acceptable"
    elif score >= 4.0:
        return "poor"
    else:
        return "failed"


# ── Stats & Analysis ─────────────────────────────────────────────────────

def _compute_agent_stats(task: dict) -> dict:
    """Compute per-agent performance stats."""
    invocations = task.get("invocations", [])
    agents = {}

    for inv in invocations:
        agent = inv["agent"]
        if agent not in agents:
            agents[agent] = {
                "count": 0,
                "total_score": 0.0,
                "total_tokens": 0,
                "errors": [],
                "quality_distribution": {"excellent": 0, "good": 0, "acceptable": 0, "poor": 0, "failed": 0},
                "tasks": [],
                "tools_used": set(),
            }

        stats = agents[agent]
        stats["count"] += 1
        stats["total_score"] += inv["score"]
        stats["total_tokens"] += inv.get("tokens", 0)
        stats["quality_distribution"][inv["quality"]] += 1
        stats["tasks"].append(inv["task"])
        stats["tools_used"].update(inv.get("tools_used", []))
        stats["errors"].extend(inv.get("errors", []))

    # Finalize averages
    for agent, stats in agents.items():
        stats["avg_score"] = round(stats["total_score"] / stats["count"], 2) if stats["count"] else 0
        stats["tools_used"] = list(stats["tools_used"])
        stats["completion_rate"] = round(
            (stats["quality_distribution"]["excellent"] + stats["quality_distribution"]["good"]) / stats["count"] * 100, 1
        ) if stats["count"] else 0

    return agents


def _generate_adjustments(task: dict) -> dict:
    """Generate prompt adjustments based on agent performance."""
    adjustments = {}
    agent_stats = task.get("agent_stats", {})

    for agent, stats in agent_stats.items():
        adj = {
            "agent": agent,
            "avg_score": stats["avg_score"],
            "completion_rate": stats["completion_rate"],
            "suggestions": [],
            "prompt_additions": [],
            "prompt_removals": [],
        }

        # Low score → add precision instructions
        if stats["avg_score"] < 6.0:
            adj["prompt_additions"].append(
                "ATTENTION: Précisions requises. Décrire exactement ce qui est produit, pas de vague."
            )
            adj["prompt_additions"].append(
                "Vérifier chaque fichier produit existe et contient le contenu attendu."
            )

        # High error rate → add error handling instructions
        error_count = len(stats.get("errors", []))
        if error_count > 2:
            adj["prompt_additions"].append(
                f"ATTENTION: {error_count} erreurs dans la session précédente. "
                "Vérifier les imports, chemins, et syntaxe avant de rendre."
            )

        # Poor quality distribution → specific guidance
        poor_failed = stats["quality_distribution"]["poor"] + stats["quality_distribution"]["failed"]
        if poor_failed > stats["count"] * 0.3:
            adj["prompt_additions"].append(
                "QUALITÉ INSUFFISANTE: Livrer du code qui compile/roule du premier coup. "
                "Tester avant de valider."
            )

        # Good performance → note what worked
        if stats["avg_score"] >= 8.0:
            adj["suggestions"].append(
                f"Performance excellente ({stats['avg_score']}/10). Garder cette approche."
            )

        # Token efficiency
        if stats["total_tokens"] > 0 and stats["count"] > 0:
            avg_tokens = stats["total_tokens"] / stats["count"]
            if avg_tokens > 5000:
                adj["prompt_additions"].append(
                    "ÉCONOMIE: Réduire les explications. Fichiers > chat. Fragments > phrases."
                )

        # Tool usage patterns
        if stats["tools_used"]:
            adj["tools_effective"] = stats["tools_used"]

        adjustments[agent] = adj

    return adjustments


def _append_to_history(task: dict):
    """Append completed task to history file."""
    history = _load_json(HISTORY_FILE, {"tasks": []})
    history.setdefault("tasks", []).append(task)
    # Keep last 50 tasks
    history["tasks"] = history["tasks"][-50:]
    _save_json(HISTORY_FILE, history)


def _save_adjustments(adjustments: dict):
    """Merge new adjustments into the persistent adjustments file."""
    existing = _load_json(ADJUSTMENTS_FILE, {"agents": {}})
    for agent, adj in adjustments.items():
        if agent not in existing["agents"]:
            existing["agents"][agent] = {
                "history": [],
                "current_prompts": [],
                "avg_score_trend": [],
            }

        agent_data = existing["agents"][agent]
        agent_data["history"].append({
            "timestamp": _now(),
            "avg_score": adj["avg_score"],
            "completion_rate": adj["completion_rate"],
            "suggestions": adj["suggestions"],
        })
        agent_data["history"] = agent_data["history"][-20:]  # Keep last 20

        # Update current prompts (merge additions, remove removals)
        current = set(agent_data.get("current_prompts", []))
        current.update(adj.get("prompt_additions", []))
        current -= set(adj.get("prompt_removals", []))
        agent_data["current_prompts"] = list(current)

        # Track score trend
        agent_data["avg_score_trend"].append(adj["avg_score"])
        agent_data["avg_score_trend"] = agent_data["avg_score_trend"][-20:]

        # Compute trend direction
        trend = agent_data["avg_score_trend"]
        if len(trend) >= 3:
            recent = sum(trend[-3:]) / 3
            older = sum(trend[-6:-3]) / 3 if len(trend) >= 6 else sum(trend[:3]) / 3
            if recent > older + 0.5:
                agent_data["trend"] = "improving"
            elif recent < older - 0.5:
                agent_data["trend"] = "declining"
            else:
                agent_data["trend"] = "stable"

    _save_json(ADJUSTMENTS_FILE, existing)


# ── Prompt Injection ─────────────────────────────────────────────────────

def get_prompt_adjustments(agent: str) -> list[str]:
    """Get current prompt adjustments for an agent. Inject into prompts."""
    data = _load_json(ADJUSTMENTS_FILE, {"agents": {}})
    agent_data = data.get("agents", {}).get(agent, {})
    return agent_data.get("current_prompts", [])


def get_agent_context(agent: str, task: str) -> str:
    """Build context string with adjustments for an agent prompt."""
    adjustments = get_prompt_adjustments(agent)
    if not adjustments:
        return ""

    lines = [
        f"## Historique Performance — {agent}",
        f"Basé sur {len(adjustments)} observations passées:",
    ]
    for adj in adjustments:
        lines.append(f"- {adj}")

    # Add trend
    data = _load_json(ADJUSTMENTS_FILE, {"agents": {}})
    agent_data = data.get("agents", {}).get(agent, {})
    trend = agent_data.get("trend")
    if trend:
        lines.append(f"\nTendance: {trend}")

    return "\n".join(lines)


# ── History & Reports ────────────────────────────────────────────────────

def get_agent_history(agent: str) -> dict:
    """Get full history for an agent."""
    history = _load_json(HISTORY_FILE, {"tasks": []})
    agent_tasks = []
    for task in history.get("tasks", []):
        if agent in task.get("agent_stats", {}):
            agent_tasks.append({
                "task_name": task["task_name"],
                "started_at": task["started_at"],
                "stats": task["agent_stats"][agent],
            })
    return {"agent": agent, "tasks": agent_tasks}


def get_full_report() -> dict:
    """Generate full report of last task."""
    history = _load_json(HISTORY_FILE, {"tasks": []})
    if not history["tasks"]:
        return {"error": "no history"}
    return history["tasks"][-1]


# ── NMP Encoding ─────────────────────────────────────────────────────────

def encode_invocation_nmp(inv: dict) -> str:
    """Encode invocation in NMP format."""
    return (
        f"AGENT_INV|{inv['agent']}|{inv['task']}|"
        f"score={inv['score']}|quality={inv['quality']}|"
        f"tokens={inv.get('tokens', 0)}|"
        f"errors={len(inv.get('errors', []))}"
    )


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agent Performance Tracker")
    sub = parser.add_subparsers(dest="command")

    # start
    p_start = sub.add_parser("start", help="Start tracking a task")
    p_start.add_argument("--task", required=True, help="Task description")
    p_start.add_argument("--agents", nargs="*", help="Agents involved")

    # log
    p_log = sub.add_parser("log", help="Log an agent invocation")
    p_log.add_argument("--agent", required=True, help="Agent name")
    p_log.add_argument("--task", required=True, help="Subtask description")
    p_log.add_argument("--expected", required=True, help="Expected output")
    p_log.add_argument("--actual", required=True, help="Actual output")
    p_log.add_argument("--score", type=float, required=True, help="Quality score (0-10)")
    p_log.add_argument("--tokens", type=int, default=0, help="Tokens used")
    p_log.add_argument("--tools", nargs="*", default=[], help="Tools used")
    p_log.add_argument("--errors", nargs="*", default=[], help="Errors encountered")
    p_log.add_argument("--duration", type=int, default=0, help="Duration in ms")

    # end
    sub.add_parser("end", help="End current task, generate report")

    # report
    sub.add_parser("report", help="Show report of last task")

    # history
    p_hist = sub.add_parser("history", help="Show agent history")
    p_hist.add_argument("--agent", required=True, help="Agent name")

    # adjust
    p_adj = sub.add_parser("adjust", help="Show prompt adjustments")
    p_adj.add_argument("--agent", required=True, help="Agent name")

    # inject
    p_inj = sub.add_parser("inject", help="Get context string for agent prompt")
    p_inj.add_argument("--agent", required=True, help="Agent name")
    p_inj.add_argument("--task", default="", help="Task description")

    args = parser.parse_args()

    if args.command == "start":
        result = start_task(args.task, args.agents)
        print(f"✅ Task started: {result['task_name']}")
        print(f"   Agents: {result['agents_involved']}")

    elif args.command == "log":
        result = log_invocation(
            agent=args.agent,
            task=args.task,
            expected=args.expected,
            actual=args.actual,
            score=args.score,
            tokens=args.tokens,
            tools_used=args.tools,
            errors=args.errors,
            duration_ms=args.duration,
        )
        nmp = encode_invocation_nmp(result)
        print(f"✅ Logged: {nmp}")

    elif args.command == "end":
        try:
            from .sync_history import sync_all
            sync_all()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        result = end_task()
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"✅ Task completed: {result['task_name']}")
            print(f"   Duration: {result['started_at']} → {result['ended_at']}")
            print(f"   Agents: {list(result.get('agent_stats', {}).keys())}")
            for agent, stats in result.get("agent_stats", {}).items():
                print(f"   {agent}: avg={stats['avg_score']}/10, "
                      f"completion={stats['completion_rate']}%, "
                      f"tokens={stats['total_tokens']}")
            if result.get("prompt_adjustments"):
                print("\n   Prompt adjustments generated:")
                for agent, adj in result["prompt_adjustments"].items():
                    if adj.get("prompt_additions"):
                        for a in adj["prompt_additions"]:
                            print(f"     + {agent}: {a[:80]}")

    elif args.command == "report":
        result = get_full_report()
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "history":
        try:
            from .sync_history import sync_all
            sync_all()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        result = get_agent_history(args.agent)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "adjust":
        adjustments = get_prompt_adjustments(args.agent)
        if adjustments:
            print(f"Prompt adjustments for {args.agent}:")
            for a in adjustments:
                print(f"  - {a}")
        else:
            print(f"No adjustments for {args.agent}")

    elif args.command == "inject":
        context = get_agent_context(args.agent, args.task)
        if context:
            print(context)
        else:
            print(f"No context for {args.agent}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
