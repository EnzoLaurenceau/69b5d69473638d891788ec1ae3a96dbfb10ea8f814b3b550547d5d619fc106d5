"""Quick diagnostic: check Hermes sessions and sprint data."""
import sqlite3, json, os
from pathlib import Path

# 1. Check Hermes DB
hermes_db = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
if not hermes_db.exists():
    print("ERROR: Hermes DB not found:", hermes_db)
else:
    conn = sqlite3.connect(str(hermes_db))
    conn.row_factory = sqlite3.Row
    
    # Total sessions with tokens
    total = conn.execute("SELECT COUNT(*) as c FROM sessions WHERE (archived=0 OR archived IS NULL) AND input_tokens>0").fetchone()["c"]
    print(f"Hermes sessions with tokens: {total}")
    
    # Date range
    date_range = conn.execute("SELECT MIN(started_at) as mn, MAX(started_at) as mx FROM sessions WHERE (archived=0 OR archived IS NULL) AND input_tokens>0").fetchone()
    print(f"Date range: {date_range['mn']} -> {date_range['mx']}")
    
    # Token stats
    stats = conn.execute("""
        SELECT 
            SUM(input_tokens) as total_in,
            SUM(output_tokens) as total_out,
            COUNT(DISTINCT model) as models,
            COUNT(DISTINCT substr(started_at, 1, 10)) as days
        FROM sessions 
        WHERE (archived=0 OR archived IS NULL) AND input_tokens>0
    """).fetchone()
    print(f"Total tokens in: {stats['total_in']:,}")
    print(f"Total tokens out: {stats['total_out']:,}")
    print(f"Unique models: {stats['models']}")
    print(f"Active days: {stats['days']}")
    
    # Recent 10 sessions
    print("\nRecent 10 sessions:")
    rows = conn.execute("""
        SELECT id, title, started_at, model, input_tokens, output_tokens
        FROM sessions 
        WHERE (archived=0 OR archived IS NULL) AND input_tokens>0
        ORDER BY started_at DESC LIMIT 10
    """).fetchall()
    for r in rows:
        sid = r["id"][:12]
        ts = (r["started_at"] or "")[:19]
        model = (r["model"] or "unknown")[:20]
        title = (r["title"] or "")[:40]
        print(f"  {sid}.. | {ts} | {model:20s} | in:{r['input_tokens']:>10,} out:{r['output_tokens']:>8,} | {title}")
    
    # Per-day breakdown
    print("\nPer-day breakdown:")
    day_rows = conn.execute("""
        SELECT substr(started_at, 1, 10) as day,
               COUNT(*) as sessions,
               SUM(input_tokens) as tok_in,
               SUM(output_tokens) as tok_out
        FROM sessions
        WHERE (archived=0 OR archived IS NULL) AND input_tokens>0
        GROUP BY day ORDER BY day
    """).fetchall()
    for d in day_rows:
        print(f"  {d['day']}: {d['sessions']:3d} sessions, in:{d['tok_in']:>12,} out:{d['tok_out']:>10,}")
    
    conn.close()

# 2. Check sprint JSON
sprint_file = Path("05_STATE/token_sprints.json")
if sprint_file.exists():
    sprints = json.loads(sprint_file.read_text(encoding="utf-8"))
    print(f"\nSprint JSON records: {len(sprints)}")
    sids = {r.get("sprint_id") for r in sprints}
    print(f"Unique sprint IDs: {len(sids)}")
else:
    print("\nSprint JSON not found")
