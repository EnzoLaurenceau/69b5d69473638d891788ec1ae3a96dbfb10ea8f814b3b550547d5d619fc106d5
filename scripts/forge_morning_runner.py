"""
Forge Morning Runner — Analyse d'état + planification kanban
=============================================================
Script autonome exécuté par le cron job 05:30.
Génère un rapport JSON + plan d'exécution pour les sessions Claude Code.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Paths
LAFORGE = Path(r"C:\Users\Jack\Documents\LaForge")
LANGCHAIN_DIR = Path(r"C:\Users\Jack\Desktop\la-forge-langchain")
BOARD_RPG = LAFORGE / "05_STATE" / "kanban" / "board_rpg.json"
BOARD_FORGE = LAFORGE / "05_STATE" / "kanban" / "board.json"
REPORT_PATH = LAFORGE / "scripts" / "morning_report.json"


def load_board(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"tasks": []}


def analyze_rpg_kanban(board: dict) -> dict:
    tasks = board.get("tasks", [])
    by_status = {}
    by_epic = {}
    for t in tasks:
        s = t["status"]
        e = t.get("epic", "?")
        by_status[s] = by_status.get(s, 0) + 1
        by_epic.setdefault(e, {"done": 0, "pending": 0, "doing": 0, "total": 0})
        by_epic[e]["total"] += 1
        if s == "done":
            by_epic[e]["done"] += 1
        elif s == "pending":
            by_epic[e]["pending"] += 1
        else:
            by_epic[e][s] = by_epic[e].get(s, 0) + 1

    # Find executable tasks (pending with all deps done)
    done_ids = {t["id"] for t in tasks if t["status"] == "done"}
    pending = [t for t in tasks if t["status"] == "pending"]
    executable = []
    blocked = []
    for t in pending:
        deps = t.get("depends_on", [])
        if all(d in done_ids for d in deps):
            executable.append(t)
        else:
            blocked.append({
                "id": t["id"],
                "blocked_by": [d for d in deps if d not in done_ids]
            })

    # Sort executable by effort (smallest first = quickest wins)
    executable.sort(key=lambda t: (t.get("effort_days", 1), t["id"]))

    # Estimate time per task type
    effort_map = {"XS": 0.25, "S": 0.5, "M": 2.0, "H": 4.0}
    total_effort = sum(t.get("effort_days", 1) for t in executable)

    return {
        "total": len(tasks),
        "done": by_status.get("done", 0),
        "pending": by_status.get("pending", 0),
        "progress_pct": round(by_status.get("done", 0) / len(tasks) * 100, 1) if tasks else 0,
        "by_epic": by_epic,
        "executable_now": [
            {
                "id": t["id"],
                "epic": t.get("epic"),
                "name": t["name"][:80],
                "complexity": t.get("complexity"),
                "effort_days": t.get("effort_days"),
                "depends_on": t.get("depends_on", [])
            }
            for t in executable
        ],
        "blocked": blocked,
        "total_remaining_effort_days": total_effort,
        "recommended_order": [t["id"] for t in executable],
    }


def check_langsmith() -> dict:
    """Vérifie LangSmith et retourne l'état."""
    result = {
        "env_vars": {},
        "packages": {},
        "connection": None,
        "traces": [],
        "datasets": [],
    }

    # Check env vars
    for var in ["LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT", "XIAOMI_API_KEY"]:
        val = os.environ.get(var)
        result["env_vars"][var] = "SET" if val else "MISSING"

    # Try to load from .env
    env_file = LAFORGE / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k.startswith("LANGSMITH") or k.startswith("XIAOMI"):
                        os.environ[k] = v.strip().strip('"').strip("'")

    try:
        sys.path.insert(0, str(LANGCHAIN_DIR))
        from langsmith import Client
        client = Client()
        runs = list(client.list_runs(project_name="Cenyx", limit=20))
        datasets = list(client.list_datasets())
        result["connection"] = "OK"
        result["traces"] = [
            {"name": r.name, "type": r.run_type, "status": r.status}
            for r in runs
        ]
        result["datasets"] = [
            {"name": d.name, "description": (d.description or "")[:80]}
            for d in datasets
        ]
        result["trace_count"] = len(runs)
        result["dataset_count"] = len(datasets)
    except Exception as e:
        result["connection"] = f"ERROR: {e}"

    return result


def generate_report() -> dict:
    """Génère le rapport complet du matin."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "langsmith": check_langsmith(),
        "rpg_kanban": analyze_rpg_kanban(load_board(BOARD_RPG)),
        "forge_kanban_summary": {},
    }

    # Forge kanban summary
    forge_board = load_board(BOARD_FORGE)
    if forge_board.get("tasks"):
        ft = forge_board["tasks"]
        report["forge_kanban_summary"] = {
            "total": len(ft),
            "done": sum(1 for t in ft if t.get("status") == "done"),
        }

    return report


if __name__ == "__main__":
    report = generate_report()
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
