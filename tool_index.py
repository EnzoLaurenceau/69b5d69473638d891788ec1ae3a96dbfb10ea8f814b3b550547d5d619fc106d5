"""
tool_index.py — OptiForge Token-Saving Tool Index
==================================================
Indexe chaque outil/approach qui réduit la charge token.
Quand une tâche similaire revient, lookup d'abord → réutiliser.

Usage:
  python tool_index.py add --name <tool> --savings <pct> --pattern <task_pattern>
  python tool_index.py lookup <task_description>
  python tool_index.py list
"""

import json
import re
import datetime
from pathlib import Path
from difflib import SequenceMatcher
import sys

# Add 00_CORE to path for imports
sys.path.insert(0, str(Path(__file__).parent / "00_CORE"))

FORGE_ROOT = Path(__file__).parent
INDEX_FILE = FORGE_ROOT / "05_STATE" / "tool_index.json"
INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> list[dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return []


def _save(tools: list[dict]):
    """Save tools in NMP format."""
    from forge_agents.nmp_encoder import encode_tool_index_nmp
    
    # Encode tools to NMP format
    nmp_tools = encode_tool_index_nmp({t["name"]: t for t in tools})
    
    # Convert back to list format for compatibility
    encoded_tools = []
    for tool in tools:
        nmp_str = nmp_tools.get(tool["name"], "")
        encoded_tool = tool.copy()
        encoded_tool["_nmp"] = nmp_str
        encoded_tools.append(encoded_tool)
    
    INDEX_FILE.write_text(json.dumps(encoded_tools, indent=2, ensure_ascii=False), encoding="utf-8")


def add_tool(name: str, savings_pct: float, pattern: str, approach: str, source: str = ""):
    """Enregistre un outil qui économise des tokens."""
    tools = _load()
    # Vérifier doublon
    for t in tools:
        if t["name"] == name:
            t["savings_pct"] = max(t["savings_pct"], savings_pct)
            t["use_count"] = t.get("use_count", 0)
            t["last_used"] = datetime.datetime.now().isoformat()
            _save(tools)
            return t

    entry = {
        "name": name,
        "savings_pct": savings_pct,
        "pattern": pattern.lower(),
        "approach": approach,
        "source": source,
        "added": datetime.datetime.now().isoformat(),
        "use_count": 0,
        "last_used": None,
    }
    tools.append(entry)
    _save(tools)
    return entry


def lookup(task_description: str, min_savings: float = 10.0) -> list[dict]:
    """Cherche des outils indexés pour une tâche similaire."""
    tools = _load()
    matches = []
    task_lower = task_description.lower()

    for t in tools:
        # Similarité entre la tâche demandée et le pattern enregistré
        sim = SequenceMatcher(None, task_lower, t["pattern"]).ratio()
        if sim > 0.3 or any(kw in task_lower for kw in t["pattern"].split()):
            if t["savings_pct"] >= min_savings:
                matches.append({**t, "similarity": round(sim, 2)})

    return sorted(matches, key=lambda x: x["similarity"] * x["savings_pct"], reverse=True)


def record_use(name: str):
    """Incrémente le compteur d'utilisation d'un outil."""
    tools = _load()
    for t in tools:
        if t["name"] == name:
            t["use_count"] = t.get("use_count", 0) + 1
            t["last_used"] = datetime.datetime.now().isoformat()
            _save(tools)
            return
    # Auto-enregistrer si inconnu
    add_tool(name, 0, name, "auto-registered", "auto")


def list_tools() -> list[dict]:
    """Liste tous les outils indexés triés par savings."""
    return sorted(_load(), key=lambda x: x["savings_pct"], reverse=True)


# ─── Pre-loaded efficient tools (known token savers) ────────────────────────

DEFAULT_TOOLS = [
    ("search_files", 80, "find file content", "search_files() au lieu de lire fichiers entiers", "optiforge"),
    ("terminal-curl", 70, "api request", "curl + jq au lieu de LLM pour extraction simple", "optiforge"),
    ("read_file-offset", 60, "read large file", "read_file(offset=N, limit=M) au lieu de lire entier", "optiforge"),
    ("execute_code", 50, "multi-step processing", "execute_code() pour N opérations en 1 appel", "optiforge"),
    ("delegate_task", 40, "complex subtask", "delegate_task() isole le contexte dans un subagent", "optiforge"),
    ("web_extract", 65, "scrape webpage", "web_extract() au lieu de browser navigate + snapshot", "optiforge"),
    ("gh-api", 75, "github operations", "gh CLI / REST API au lieu de browser GitHub", "optiforge"),
    ("semgrep", 85, "code audit", "semgrep CLI scan pattern au lieu de LLM code review", "optiforge"),
    ("ripgrep", 90, "code search", "rg pattern au lieu de LLM pour chercher du code", "optiforge"),
    ("python-oneliner", 70, "data transform", "python -c au lieu de LLM pour transformation simple", "optiforge"),
]


def seed_defaults():
    """Pré-charge les outils connus qui économisent des tokens."""
    existing = {t["name"] for t in _load()}
    for name, savings, pattern, approach, source in DEFAULT_TOOLS:
        if name not in existing:
            add_tool(name, savings, pattern, approach, source)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OptiForge Tool Index")
    sub = parser.add_subparsers(dest="cmd")

    add = sub.add_parser("add", help="Add a tool")
    add.add_argument("--name", required=True)
    add.add_argument("--savings", type=float, required=True)
    add.add_argument("--pattern", required=True)
    add.add_argument("--approach", required=True)
    add.add_argument("--source", default="")

    lk = sub.add_parser("lookup", help="Lookup tools for a task")
    lk.add_argument("task")

    sub.add_parser("list", help="List all indexed tools")
    sub.add_parser("seed", help="Seed default tools")

    args = parser.parse_args()

    if args.cmd == "add":
        e = add_tool(args.name, args.savings, args.pattern, args.approach, args.source)
        print(f"✅ Indexed: {e['name']} (saves {e['savings_pct']}%)")
    elif args.cmd == "lookup":
        matches = lookup(args.task)
        if matches:
            print(f"🔍 {len(matches)} tool(s) found for: {args.task}")
            for m in matches:
                print(f"  → {m['name']} (saves {m['savings_pct']}%, sim={m['similarity']})")
                print(f"    {m['approach']}")
        else:
            print(f"❌ No indexed tools for: {args.task}")
    elif args.cmd == "list":
        tools = list_tools()
        print(f"📦 {len(tools)} tools indexed:")
        for t in tools:
            print(f"  [{t['savings_pct']:>3.0f}%] {t['name']}: {t['approach']} (used {t.get('use_count',0)}x)")
    elif args.cmd == "seed":
        seed_defaults()
        print(f"✅ Defaults seeded. Total: {len(list_tools())} tools.")
    else:
        parser.print_help()
