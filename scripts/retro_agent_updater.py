#!/usr/bin/env python3
"""
retro_agent_updater.py — Inject historical lessons into agent prompts
=====================================================================
Scans Hermes session history for agent outcomes (success/failure),
extracts anti-patterns and lessons, and updates agent instruction files
under 02_AGENTS/.

Usage:
    python scripts/retro_agent_updater.py              # dry-run
    python scripts/retro_agent_updater.py --apply       # actually update files
"""

from __future__ import annotations
import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = FORGE_ROOT / "02_AGENTS"
HERMES_DB = Path.home() / "AppData" / "Local" / "hermes" / "state.db"

# Known agent name mappings (session keywords → agent folder)
AGENT_MAPPINGS = {
    "audit": "audit_agent",
    "security": "audit_agent",
    "pentest": "audit_agent",
    "bug bounty": "audit_agent",
    "bbril": "audit_agent",
    "senior_dev": "senior_dev",
    "developer": "senior_dev",
    "coding": "senior_dev",
    "build": "senior_dev",
    "implement": "senior_dev",
    "marketing": "marketing_digital",
    "social": "marketing_digital",
    "tiktok": "marketing_digital",
    "snapchat": "marketing_digital",
    "closer": "closer_pro",
    "email": "closer_pro",
    "sales": "closer_pro",
    "prospect": "closer_pro",
    "pipeline": "closer_pro",
    "founder": "founder_ceo",
    "ceo": "founder_ceo",
    "strategy": "founder_ceo",
    "research": "research",
    "analyze": "research",
    "legal": "legal_officer",
    "law": "legal_officer",
    "prompt": "prompt_engineer",
    "scraper": "scraper",
    "scrape": "scraper",
    "critic": "critic",
    "review": "critic",
    "judge": "critic",
    "forge": "senior_dev",
    "optiforge": "senior_dev",
    "harness": "critic",
    "blueprint": "senior_dev",
    "mcp": "senior_dev",
    "rag": "research",
}


def scan_sessions() -> list[dict]:
    """Scan Hermes DB for Forge sessions with outcomes."""
    if not HERMES_DB.exists():
        return []

    conn = sqlite3.connect(str(HERMES_DB))
    conn.row_factory = sqlite3.Row

    sessions = []
    try:
        rows = conn.execute("""
            SELECT id, title, started_at, model,
                   message_count, tool_call_count,
                   input_tokens, output_tokens
            FROM sessions
            WHERE (archived = 0 OR archived IS NULL)
              AND message_count > 5
            ORDER BY started_at ASC
        """).fetchall()

        for row in rows:
            title = (row["title"] or "").lower()
            # Only Forge-related sessions
            forge_keywords = ["forge", "optiforge", "dispatch", "agent", "audit",
                            "marketing", "closer", "senior", "founder", "research",
                            "bug bounty", "prospect", "pipeline", "mcp", "cron",
                            "bbril", "harness", "blueprint", "pxpipe", "rag",
                            "versioning", "telemetry", "daemon"]
            if not any(kw in title for kw in forge_keywords):
                continue

            sessions.append({
                "session_id": row["id"],
                "title": row["title"] or "",
                "started_at": row["started_at"] or 0,
                "model": row["model"] or "",
                "msg_count": row["message_count"] or 0,
                "tool_calls": row["tool_call_count"] or 0,
                "input_tokens": row["input_tokens"] or 0,
                "output_tokens": row["output_tokens"] or 0,
            })
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

    return sessions


def identify_agents(session: dict) -> list[str]:
    """Identify which agents were involved in a session."""
    title = session["title"].lower()
    agents = set()
    for keyword, agent_name in AGENT_MAPPINGS.items():
        if keyword in title:
            agents.add(agent_name)
    return list(agents)


def extract_lessons(session: dict) -> list[str]:
    """Extract lessons from session data."""
    lessons = []
    title = session["title"]
    tokens = session["input_tokens"] + session["output_tokens"]
    msg_count = session["msg_count"]

    # High token usage → efficiency lesson
    if tokens > 500_000:
        lessons.append(
            f"Session à fort usage de tokens ({tokens:,} tok). "
            f"Considérer la décomposition en sous-tâches pour réduire le contexte."
        )

    # Many messages → complexity lesson
    if msg_count > 200:
        lessons.append(
            f"Session longue ({msg_count} messages). "
            f"Préférer la délégation à des subagents pour les tâches complexes."
        )

    # Tool-heavy sessions
    if session["tool_calls"] > 100:
        lessons.append(
            f"Session intensive en outils ({session['tool_calls']} appels). "
            f"Vérifier si des outils locaux peuvent remplacer les appels répétitifs."
        )

    # Title-based lessons
    if "error" in title.lower() or "fix" in title.lower() or "bug" in title.lower():
        lessons.append(
            f"Session de debug/fix: '{title[:60]}'. "
            f"Toujours exécuter les tests après chaque modification."
        )

    if "migration" in title.lower() or "upgrade" in title.lower():
        lessons.append(
            f"Migration/upgrade: '{title[:60]}'. "
            f"Faire un backup avant toute migration, tester sur un environnement isolé."
        )

    return lessons


def find_agent_instruction_file(agent_name: str) -> Path | None:
    """Find the instruction file for an agent."""
    agent_dir = AGENTS_DIR / agent_name
    if not agent_dir.exists():
        return None

    # Priority: SKILL.md > *.md > prompt.txt
    for pattern in ["*SKILL*.md", "*AGENT*.md", "*.md", "prompt.txt"]:
        candidates = list(agent_dir.glob(pattern))
        if candidates:
            # Prefer files with agent name
            for c in candidates:
                if agent_name.lower().replace("_", "") in c.stem.lower().replace("_", ""):
                    return c
            return candidates[0]
    return None


def update_agent_file(file_path: Path, lessons: list[str], dry_run: bool = True) -> bool:
    """Update an agent instruction file with lessons."""
    if not file_path.exists():
        return False

    content = file_path.read_text(encoding="utf-8")
    marker = "## Leçons Apprises des Sessions Historiques"

    # Filter out lessons already present
    new_lessons = []
    for lesson in lessons:
        if lesson[:50] not in content:
            new_lessons.append(lesson)

    if not new_lessons:
        return False

    date_str = datetime.now().strftime("%Y-%m")
    lesson_lines = "\n".join(f"- [{date_str}] {l}" for l in new_lessons)

    if marker not in content:
        new_section = f"\n\n{marker}\n{lesson_lines}\n"
    else:
        new_section = f"\n{lesson_lines}\n"

    if dry_run:
        print(f"  [DRY] Would update {file_path.name} with {len(new_lessons)} lessons")
        for l in new_lessons:
            print(f"    → {l[:80]}")
        return True

    if marker not in content:
        with file_path.open("a", encoding="utf-8") as f:
            f.write(new_section)
    else:
        updated = content.rstrip() + f"\n{lesson_lines}\n"
        file_path.write_text(updated, encoding="utf-8")

    print(f"  ✓ {file_path.name} — {len(new_lessons)} lessons added")
    return True


def main():
    parser = argparse.ArgumentParser(description="Retroactive agent updater")
    parser.add_argument("--apply", action="store_true", help="Actually update files")
    args = parser.parse_args()
    dry_run = not args.apply

    print("=" * 60)
    print("RETROACTIVE AGENT UPDATER")
    print("=" * 60)

    # Scan sessions
    sessions = scan_sessions()
    print(f"\nFound {len(sessions)} Forge-related sessions")

    if not sessions:
        print("No sessions found.")
        return

    # Aggregate lessons per agent
    agent_lessons: dict[str, list[str]] = {}
    total_lessons = 0

    for session in sessions:
        agents = identify_agents(session)
        lessons = extract_lessons(session)

        if not agents or not lessons:
            continue

        for agent in agents:
            agent_lessons.setdefault(agent, []).extend(lessons)
            total_lessons += len(lessons)

    print(f"Lessons extracted: {total_lessons} for {len(agent_lessons)} agents")

    # Update agent files
    print(f"\n── Agent Updates {'(DRY RUN)' if dry_run else '(APPLY)'} ──")
    updated_count = 0
    for agent_name, lessons in agent_lessons.items():
        instruction_file = find_agent_instruction_file(agent_name)
        if not instruction_file:
            print(f"  skip {agent_name} — no instruction file found")
            continue

        if update_agent_file(instruction_file, lessons, dry_run):
            updated_count += 1

    # Summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY:")
    print(f"  Sessions scanned:  {len(sessions)}")
    print(f"  Agents identified: {len(agent_lessons)}")
    print(f"  Total lessons:     {total_lessons}")
    print(f"  Files {'to update' if dry_run else 'updated'}: {updated_count}")

    if dry_run:
        print(f"\nRun with --apply to actually update the files.")


if __name__ == "__main__":
    main()
