"""
Forge Dispatcher — Main entry point.

Usage:
    python forge_dispatcher.py decompose --task "Build X" --subtasks subtasks.json
    python forge_dispatcher.py prompts   (generate hermes commands from kanban)
    python forge_dispatcher.py status    (show kanban board)
    python forge_dispatcher.py reset     (clear kanban)

Subtasks JSON format:
[
    {"name": "Task 1", "description": "Do X", "files": ["a.py", "b.py"], "depends_on": []},
    {"name": "Task 2", "description": "Do Y", "files": ["c.py"], "depends_on": ["T001"]}
]
"""
import json
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_dispatch"))

from decomposer import decompose_task, generate_prompts, print_summary
from kanban import status, load, save


def cmd_decompose(args):
    task = args.get("--task", "Unknown task")
    desc = args.get("--desc", "")
    subtasks_file = args.get("--subtasks-json")

    subtask_descs = None
    if subtasks_file:
        subtask_descs = json.loads(Path(subtasks_file).read_text(encoding="utf-8"))

    decomp = decompose_task(task, desc, subtask_descs)
    prompts = generate_prompts()
    print_summary(decomp, prompts)


def cmd_prompts(args):
    prompts = generate_prompts()
    if not prompts:
        print("No tasks on the board. Run 'decompose' first.")
        return
    print()
    print("HERMES COMMANDS (copy-paste each in a new terminal):")
    print("=" * 60)
    for i, p in enumerate(prompts, 1):
        print(f"\n--- Session {i}: {p['name']} ---")
        print(f"  cd /c/Users/Enzo/Documents/MODELS/.claude")
        print(f"  {p['hermes_cmd']}")
        print(f"  Prompt: {p['prompt_file']}")
        print(f"  Est: ~{p['est_tokens']:,} tokens")
    print()


def cmd_status(args):
    print(status())


def cmd_reset(args):
    board = {"tasks": [], "version": 1}
    save(board)
    print("Kanban cleared.")


def cmd_estimate(args):
    """Estimate how many sessions a task needs."""
    task = args.get("--task", "")
    desc = args.get("--desc", "")
    # Rough estimation
    total_chars = len(task) + len(desc)
    est_tokens = total_chars // 4 + 10000  # base overhead
    sessions = max(1, math.ceil(est_tokens / 55000))
    print(f"\nEstimation:")
    print(f"  Task chars:    {total_chars:,}")
    print(f"  Est tokens:    ~{est_tokens:,}")
    print(f"  Sessions:      {sessions} × 65K ceiling")
    print(f"  Usable/sess:   55K (10K safety for system prompt)")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    # Parse --key value args
    args = {}
    i = 2
    while i < len(sys.argv):
        if sys.argv[i].startswith("--") and i + 1 < len(sys.argv):
            args[sys.argv[i]] = sys.argv[i + 1]
            i += 2
        else:
            args[sys.argv[i]] = True
            i += 1

    {"decompose": cmd_decompose, "prompts": cmd_prompts, "status": cmd_status, "reset": cmd_reset, "estimate": cmd_estimate}.get(cmd, lambda a: print(f"Unknown command: {cmd}"))(args)
