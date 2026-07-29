"""
Forge Decomposer — Split any task into N subtasks that fit in 65K token sessions.

Usage:
    python decomposer.py --task "Build a full-stack app" --desc "Detailed description"
    python decomposer.py --from-brief session_transfer_brief.md
    python decomposer.py --from-kanban  (resume from board)

Output:
    - prompts/ subtask files (ready to copy-paste into hermes chat)
    - kanban/board.json updated
    - Summary with exact hermes commands
"""
import json
import os
import sys
import math
import hashlib
from datetime import datetime
from pathlib import Path
try:
    from forge_agents.forge_store import state_path
except ImportError:  # lancé comme script : 00_CORE n'est pas sur le chemin
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[2]))
DISPATCH_DIR = FORGE_ROOT / "00_CORE" / "forge_dispatch"
PROMPTS_DIR = DISPATCH_DIR / "prompts"
RESULTS_DIR = DISPATCH_DIR / "results"


def KANBAN_FILE() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("kanban/board.json")


CEILING = 65_000
SYSTEM_PROMPT_OVERHEAD = 11_500  # measured: forge rules + skills + memory
SAFETY_MARGIN = 5_000
USABLE = CEILING - SYSTEM_PROMPT_OVERHEAD - SAFETY_MARGIN  # 48,500 per session

# Calibration data (measured from real sessions)
CHARS_PER_TOKEN = 4    # measured
TOOL_OVERHEAD_PER_FILE = 500   # measured: average tool call overhead per file created
DEBUG_OVERHEAD = 11_500        # measured: pytest + patch + fix cycles
DISPATCH_OVERHEAD = 3_300      # measured: kanban + bilan + prompts
RESEARCH_PER_SKILL_VIEW = 4000 # measured: average skill_view output


def load_kanban() -> dict:
    if KANBAN_FILE().exists():
        return json.loads(KANBAN_FILE().read_text(encoding="utf-8"))
    return {"tasks": [], "created": datetime.now().isoformat(), "version": 1}


def save_kanban(board: dict):
    KANBAN_FILE().parent.mkdir(parents=True, exist_ok=True)
    KANBAN_FILE().write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def estimate_task_tokens(description: str, num_files: int = 0, has_tests: bool = True) -> int:
    """Calibrated token estimation based on real session data.
    
    Measured from tg-bot-workflow session (2026-06-16):
    - System prompt: 11,500 tok/session (FIXED)
    - Tool overhead per file: 500 tok (avg read+write+patch)
    - Debug cycle: 11,500 tok (pytest + patch + fix)
    - Dispatch overhead: 3,300 tok
    - chars_per_token: 4
    """
    # Base: description tokens
    base = estimate_tokens(description)
    
    # File generation: each file ~500 tok tool overhead + chars/4 output
    file_tokens = num_files * TOOL_OVERHEAD_PER_FILE
    
    # Debug overhead if tests needed
    debug = DEBUG_OVERHEAD if has_tests else 0
    
    # Dispatch overhead (always present)
    dispatch = DISPATCH_OVERHEAD
    
    total = base + file_tokens + debug + dispatch
    return total


def generate_task_id(name: str, index: int) -> str:
    short = hashlib.md5(f"{name}_{index}".encode()).hexdigest()[:6]
    return f"T{index:03d}_{short}"


def decompose_task(task: str, desc: str = "", subtask_descs: list[dict] = None) -> dict:
    """
    Decompose a task into subtasks.

    subtask_descs: optional list of {"name": str, "description": str, "files": [str], "depends_on": [str]}
    If not provided, generates a single subtask (manual decomposition needed).
    """
    board = load_kanban()

    if not subtask_descs:
        # Single task — user must decompose manually
        subtask_descs = [{"name": task, "description": desc or task, "files": [], "depends_on": []}]

    tasks = []
    for i, st in enumerate(subtask_descs):
        task_id = generate_task_id(st["name"], i + 1)
        est_tokens = estimate_task_tokens(st["description"], num_files=len(st.get("files", [])))

        tasks.append({
            "id": task_id,
            "name": st["name"],
            "description": st["description"],
            "files": st.get("files", []),
            "depends_on": st.get("depends_on", []),
            "est_tokens": est_tokens,
            "status": "pending",  # pending → in_progress → done → blocked
            "assigned_session": None,
            "started_at": None,
            "completed_at": None,
            "result_file": None,
        })

    session_count = len(tasks)
    total_est = sum(t["est_tokens"] for t in tasks)

    board["tasks"] = tasks
    board["parent_task"] = task
    board["parent_desc"] = desc
    board["total_est_tokens"] = total_est
    board["session_count"] = session_count
    board["updated"] = datetime.now().isoformat()
    save_kanban(board)

    return {
        "task_count": session_count,
        "total_est_tokens": total_est,
        "sessions_needed": session_count,
        "tasks": tasks,
    }


def generate_prompts(board: dict = None) -> list[dict]:
    """Generate hermes CLI commands + prompt files for each subtask."""
    if board is None:
        board = load_kanban()

    prompts = []
    for task in board["tasks"]:
        task_id = task["id"]

        # Build the prompt content
        prompt_lines = [
            f"# Task: {task['name']}",
            f"Task ID: {task_id}",
            f"",
            f"## Instructions",
            f"{task['description']}",
            f"",
        ]

        if task["files"]:
            prompt_lines.append("## Files to create/modify (YOUR SCOPE — do NOT touch other files)")
            for f in task["files"]:
                prompt_lines.append(f"  - {f}")
            prompt_lines.append("")

        if task["depends_on"]:
            prompt_lines.append("## Depends on (read these results first)")
            for dep in task["depends_on"]:
                result_file = RESULTS_DIR / f"{dep}.json"
                prompt_lines.append(f"  - {result_file}")
            prompt_lines.append("")

        # Kanban lock instruction
        prompt_lines.extend([
            "## Kanban Protocol (MANDATORY)",
            "1. READ the kanban board FIRST:",
            f"   cat {KANBAN_FILE()}",
            "2. Check your task status is 'pending' or 'in_progress'",
            "3. If another task is 'in_progress' on the SAME files → WAIT or skip",
            f"4. Update your task to 'in_progress' in the board",
            "5. Do the work",
            f"6. Write your result to: {RESULTS_DIR / f'{task_id}.json'}",
            f"7. Update your task to 'done' in the board",
            "8. NEVER modify files listed under another task's scope",
            "",
            "## Quality Gate",
            "- No placeholder code, no TODO stubs",
            "- Working code that runs",
            "- Tests if applicable",
            "",
        ])

        prompt_content = "\n".join(prompt_lines)

        # Write prompt file
        prompt_file = PROMPTS_DIR / f"{task_id}.md"
        prompt_file.write_text(prompt_content, encoding="utf-8")

        # Build hermes command
        hermes_cmd = f'hermes chat -q --profile forge "{task_id}: {task["name"]}"'

        prompts.append({
            "task_id": task_id,
            "name": task["name"],
            "prompt_file": str(prompt_file),
            "hermes_cmd": hermes_cmd,
            "est_tokens": task["est_tokens"],
        })

    return prompts


def print_summary(decomp: dict, prompts: list[dict]):
    """Print the full dispatch summary."""
    print()
    print("═" * 60)
    print("FORGE DISPATCH — MULTI-SESSION PLAN")
    print("═" * 60)
    print()
    print(f"  Task:      {decomp['task_count']} subtasks")
    print(f"  Tokens:    ~{decomp['total_est_tokens']:,} total estimated (calibrated)")
    print(f"  Sessions:  {decomp['sessions_needed']} × {CEILING:,} ceiling")
    print(f"  Usable:    {USABLE:,} per session (system={SYSTEM_PROMPT_OVERHEAD:,} + safety={SAFETY_MARGIN:,})")
    print(f"  Overhead:  +{SYSTEM_PROMPT_OVERHEAD * decomp['sessions_needed']:,} tok system prompt ({decomp['sessions_needed']} sessions)")
    print()

    print("─" * 60)
    print(f"{'ID':<12} {'Task':<30} {'Est Tok':>8} {'Status':>10}")
    print("─" * 60)
    for t in decomp["tasks"]:
        print(f"{t['id']:<12} {t['name'][:30]:<30} {t['est_tokens']:>8,} {t['status']:>10}")
    print("─" * 60)
    print()

    print("COMMANDS TO RUN (copy-paste each in a new terminal):")
    print("=" * 60)
    for i, p in enumerate(prompts, 1):
        print(f"\n--- Session {i}: {p['name']} ---")
        print(f"  cd /c/Users/Enzo/Documents/MODELS/.claude")
        print(f"  {p['hermes_cmd']}")
        print(f"  Prompt file: {p['prompt_file']}")
        print(f"  Est: ~{p['est_tokens']:,} tokens")

    print()
    print("SHARED MEMORY: Kanban board (read/write before each action)")
    print(f"  {KANBAN_FILE()}")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Forge Task Decomposer")
    parser.add_argument("--task", help="Task description")
    parser.add_argument("--desc", default="", help="Detailed description")
    parser.add_argument("--subtasks-json", help="JSON file with subtask definitions")
    parser.add_argument("--generate", action="store_true", help="Generate prompts from existing kanban")
    parser.add_argument("--status", action="store_true", help="Show kanban status")
    args = parser.parse_args()

    if args.status:
        board = load_kanban()
        if not board["tasks"]:
            print("No tasks on the board.")
        else:
            print(f"\nKanban — {len(board['tasks'])} tasks")
            print(f"Parent: {board.get('parent_task', 'N/A')}")
            print()
            for t in board["tasks"]:
                icon = {"pending": "⬜", "in_progress": "🔵", "done": "✅", "blocked": "🚫"}.get(t["status"], "?")
                print(f"  {icon} {t['id']} | {t['name'][:40]:<40} | {t['est_tokens']:>6} tok | {t['status']}")
        sys.exit(0)

    if args.generate:
        prompts = generate_prompts()
        for p in prompts:
            print(f"  {p['hermes_cmd']}")
        sys.exit(0)

    if not args.task:
        print("Usage: python decomposer.py --task 'description' [--desc 'details'] [--subtasks-json file.json]")
        sys.exit(1)

    subtask_descs = None
    if args.subtasks_json:
        subtask_descs = json.loads(Path(args.subtasks_json).read_text(encoding="utf-8"))

    decomp = decompose_task(args.task, args.desc, subtask_descs)
    prompts = generate_prompts()
    print_summary(decomp, prompts)
