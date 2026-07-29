#!/usr/bin/env python3
"""
retro_index_tokens.py — Retrospective token indexing from Hermes sessions
=========================================================================
Reads actual token data from Hermes state.db and creates token log entries
in 08_LOGS/tokens/ so the dashboard shows real aggregated data.

Usage:
    python scripts/retro_index_tokens.py              # dry-run
    python scripts/retro_index_tokens.py --apply       # actually write logs
"""

from __future__ import annotations
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parent.parent
TOKEN_LOGS_DIR = FORGE_ROOT / "08_LOGS" / "tokens"
TOKEN_LOGS_DIR.mkdir(parents=True, exist_ok=True)

HERMES_DB = Path.home() / "AppData" / "Local" / "hermes" / "state.db"


def scan_sessions() -> list[dict]:
    """Scan Hermes DB for Forge-related sessions with real token data."""
    if not HERMES_DB.exists():
        print(f"Hermes DB not found: {HERMES_DB}")
        return []

    conn = sqlite3.connect(str(HERMES_DB))
    conn.row_factory = sqlite3.Row

    # Keywords that indicate Forge-related work
    forge_keywords = [
        "forge", "optiforge", "dispatch", "blueprint", "harness",
        "inference", "rag", "versioning", "pxpipe", "kuzu", "curator",
        "graph_db", "event_bus", "telemetry", "daemon", "guardian",
        "token_tracker", "auto_index", "gitnexus", "knowledge",
        "neural_markov", "cervelet", "auto_complexification",
        "post_mortem", "dynamic_agent", "orchestrator",
    ]

    sessions = []
    try:
        rows = conn.execute("""
            SELECT id, title, started_at, ended_at, model,
                   message_count, tool_call_count,
                   input_tokens, output_tokens, cache_read_tokens,
                   estimated_cost_usd, actual_cost_usd, cwd
            FROM sessions
            WHERE archived = 0 OR archived IS NULL
            ORDER BY started_at ASC
        """).fetchall()

        for row in rows:
            title = (row["title"] or "").lower()
            cwd = (row["cwd"] or "").lower()

            # Match by title keywords OR by working directory
            is_forge = (
                any(kw in title for kw in forge_keywords) or
                ".claude" in cwd or
                "models" in cwd
            )

            if not is_forge:
                continue

            # Skip sessions with no token data
            input_tok = row["input_tokens"] or 0
            output_tok = row["output_tokens"] or 0
            if input_tok == 0 and output_tok == 0:
                continue

            sessions.append({
                "session_id": row["id"],
                "title": row["title"] or "unknown",
                "started_at": str(row["started_at"] or ""),
                "ended_at": str(row["ended_at"] or ""),
                "model": row["model"] or "unknown",
                "msg_count": row["message_count"] or 0,
                "tool_calls": row["tool_call_count"] or 0,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cache_read_tokens": row["cache_read_tokens"] or 0,
                "estimated_cost_usd": row["estimated_cost_usd"] or 0.0,
                "actual_cost_usd": row["actual_cost_usd"] or 0.0,
                "cwd": row["cwd"] or "",
            })
    except Exception as e:
        print(f"Error scanning sessions: {e}")
    finally:
        conn.close()

    return sessions


def create_token_log(session: dict) -> dict:
    """Create a token log entry compatible with the existing format."""
    sid = session["session_id"]
    model = session["model"]
    input_tok = session["input_tokens"]
    output_tok = session["output_tokens"]
    cost = session["actual_cost_usd"] or session["estimated_cost_usd"]

    log = {
        "task": session["title"][:200],
        "session_id": sid,
        "estimate_table": {
            model: {
                "input": input_tok,
                "output": output_tok,
                "cost": cost,
            }
        },
        "actual_table": {
            model: {
                "input": input_tok,
                "output": output_tok,
                "cost": cost,
            }
        },
        "recommendations": [
            f"Retrospective from Hermes session {sid}",
            f"Model: {model}, Msgs: {session['msg_count']}, Tools: {session['tool_calls']}",
            f"Cache read: {session['cache_read_tokens']} tokens",
        ],
        "efficiency_score": 75,
        "savings_usd": 0.0,  # will be calculated if free model
        "efficiency_savings": {
            "tokens_saved": 0,
            "money_saved": 0.0,
            "latency_saved_ms": 0,
            "calls_avoided": 0,
        },
        "raw_logs": [],
        "retrospective": True,
        "retro_model": model,
        "retro_msg_count": session["msg_count"],
        "retro_tool_calls": session["tool_calls"],
        "retro_started": session["started_at"],
        "retro_ended": session["ended_at"],
    }

    return log


def main():
    parser = argparse.ArgumentParser(description="Retrospective token indexing")
    parser.add_argument("--apply", action="store_true", help="Actually write log files")
    args = parser.parse_args()

    print("=" * 60)
    print("RETROSPECTIVE TOKEN INDEXING")
    print("=" * 60)

    sessions = scan_sessions()
    print(f"\nFound {len(sessions)} Forge-related sessions with token data")

    if not sessions:
        print("No sessions found. Nothing to index.")
        return

    total_input = 0
    total_output = 0
    total_cost = 0.0
    total_cache = 0

    logs_to_write = []

    for s in sessions:
        log = create_token_log(s)
        logs_to_write.append((s, log))

        total_input += s["input_tokens"]
        total_output += s["output_tokens"]
        total_cost += s["actual_cost_usd"] or s["estimated_cost_usd"]
        total_cache += s["cache_read_tokens"]

        date = s["started_at"][:10] if s["started_at"] else "?"
        print(f"\n  [{date}] {s['title'][:60]}")
        print(f"    Model: {s['model']} | Msgs: {s['msg_count']} | Tools: {s['tool_calls']}")
        print(f"    Tokens: in={s['input_tokens']:,} out={s['output_tokens']:,} cache={s['cache_read_tokens']:,}")
        print(f"    Cost: ${s['actual_cost_usd'] or s['estimated_cost_usd']:.4f}")

    print(f"\n{'=' * 60}")
    print(f"TOTALS:")
    print(f"  Sessions:      {len(sessions)}")
    print(f"  Input tokens:  {total_input:,}")
    print(f"  Output tokens: {total_output:,}")
    print(f"  Cache read:    {total_cache:,}")
    print(f"  Total cost:    ${total_cost:.4f}")
    print(f"{'=' * 60}")

    if args.apply:
        print(f"\nWriting {len(logs_to_write)} token logs...")
        for s, log in logs_to_write:
            sid = s["session_id"]
            # Sanitize filename
            safe_id = sid.replace("/", "_").replace("\\", "_").replace(":", "_")[:50]
            filename = f"retro_{safe_id}.json"
            filepath = TOKEN_LOGS_DIR / filename
            filepath.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  ✓ {filename}")

        print(f"\nDone! {len(logs_to_write)} retrospective logs written to {TOKEN_LOGS_DIR}")
        print("Restart the dashboard server to see updated metrics.")
    else:
        print(f"\n[DRY RUN] Would write {len(logs_to_write)} logs.")
        print("Run with --apply to actually write the files.")


if __name__ == "__main__":
    main()
