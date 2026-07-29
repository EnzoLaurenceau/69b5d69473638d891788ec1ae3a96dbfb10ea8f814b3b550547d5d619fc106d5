"""
Kanban Protocol — Shared state for multi-session Forge dispatch.

Every hermes session spawned by the dispatcher MUST:
1. Read this board before starting
2. Check no other session owns the same files
3. Update its task to in_progress
4. Write results to results/{task_id}.json
5. Update its task to done

The board is the single source of truth.
No session may modify files outside its assigned scope.
"""
import json
import sys
from pathlib import Path
from datetime import datetime
try:
    from forge_agents.forge_store import state_path
except ImportError:  # lancé comme script : 00_CORE n'est pas sur le chemin
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

FORGE_ROOT = Path(__file__).resolve().parents[2]


def KANBAN_FILE() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("kanban/board.json")


def load() -> dict:
    if not KANBAN_FILE().exists():
        return {"tasks": [], "version": 1}
    return json.loads(KANBAN_FILE().read_text(encoding="utf-8"))


def save(board: dict):
    board["updated"] = datetime.now().isoformat()
    KANBAN_FILE().write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")


def claim(task_id: str, session_id: str) -> bool:
    """Claim a task. Returns False if already claimed by another session."""
    board = load()
    for t in board["tasks"]:
        if t["id"] == task_id:
            if t["status"] == "in_progress" and t["assigned_session"] != session_id:
                return False  # owned by someone else
            t["status"] = "in_progress"
            t["assigned_session"] = session_id
            t["started_at"] = datetime.now().isoformat()
            save(board)
            return True
    return False


def complete(task_id: str, result_file: str = None) -> bool:
    """Mark a task as done."""
    board = load()
    for t in board["tasks"]:
        if t["id"] == task_id:
            t["status"] = "done"
            t["completed_at"] = datetime.now().isoformat()
            t["result_file"] = result_file
            save(board)
            return True
    return False


def block(task_id: str, reason: str = "") -> bool:
    """Mark a task as blocked."""
    board = load()
    for t in board["tasks"]:
        if t["id"] == task_id:
            t["status"] = "blocked"
            t["block_reason"] = reason
            save(board)
            return True
    return False


def check_conflicts(task_id: str) -> list[str]:
    """Check if any in_progress task shares files with this task."""
    board = load()
    target = None
    for t in board["tasks"]:
        if t["id"] == task_id:
            target = t
            break
    if not target:
        return []

    target_files = set(target.get("files", []))
    if not target_files:
        return []

    conflicts = []
    for t in board["tasks"]:
        if t["id"] == task_id or t["status"] != "in_progress":
            continue
        other_files = set(t.get("files", []))
        overlap = target_files & other_files
        if overlap:
            conflicts.append(f"{t['id']} ({', '.join(overlap)})")

    return conflicts


def status() -> str:
    """Human-readable board status."""
    board = load()
    if not board.get("tasks"):
        return "Board empty."

    lines = [
        f"Kanban — {board.get('parent_task', 'N/A')}",
        f"Sessions: {board.get('session_count', '?')} | Est: ~{board.get('total_est_tokens', 0):,} tok",
        "",
    ]

    counts = {"pending": 0, "in_progress": 0, "done": 0, "blocked": 0}
    for t in board["tasks"]:
        s = t["status"]
        counts[s] = counts.get(s, 0) + 1
        icon = {"pending": "⬜", "in_progress": "🔵", "done": "✅", "blocked": "🚫"}.get(s, "?")
        lines.append(f"  {icon} {t['id']} | {t['name'][:45]:<45} | {t['status']}")

    lines.append("")
    lines.append(f"Summary: ✅{counts['done']} 🔵{counts['in_progress']} ⬜{counts['pending']} 🚫{counts['blocked']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(status())
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "claim" and len(sys.argv) >= 4:
        ok = claim(sys.argv[2], sys.argv[3])
        print(f"Claim {'OK' if ok else 'FAILED (conflict)'}")
    elif cmd == "complete" and len(sys.argv) >= 3:
        result_file = sys.argv[3] if len(sys.argv) > 3 else None
        ok = complete(sys.argv[2], result_file)
        print(f"Complete {'OK' if ok else 'FAILED'}")
    elif cmd == "conflicts" and len(sys.argv) >= 3:
        c = check_conflicts(sys.argv[2])
        print(f"Conflicts: {c if c else 'none'}")
    elif cmd == "status":
        print(status())
    else:
        print("Usage: python kanban.py [claim <id> <session>|complete <id> [result]|conflicts <id>|status]")
