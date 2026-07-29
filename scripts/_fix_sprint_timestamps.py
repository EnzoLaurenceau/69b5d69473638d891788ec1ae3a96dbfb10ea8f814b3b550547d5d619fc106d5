import sqlite3
import json
import os
import datetime as _dt

PRICING = {
    "claude-3-5-sonnet-20240620": {"in": 3.0, "out": 15.0},
    "claude-3-opus-20240229": {"in": 15.0, "out": 75.0},
    "claude-3-haiku-20240307": {"in": 0.25, "out": 1.25},
}

def _estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    m = model.lower()
    for k, v in PRICING.items():
        if k in m:
            return (in_tok * v["in"] / 1000000) + (out_tok * v["out"] / 1000000)
    if "gpt-4o" in m:
        return (in_tok * 5.0 / 1000000) + (out_tok * 15.0 / 1000000)
    if "gpt-4-turbo" in m:
        return (in_tok * 10.0 / 1000000) + (out_tok * 30.0 / 1000000)
    if "gpt-3.5" in m or "gpt-35" in m:
        return (in_tok * 0.5 / 1000000) + (out_tok * 1.5 / 1000000)
    return 0.0

def main():
    db_path = r"C:\Users\Enzo\AppData\Local\hermes\state.db"
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM sessions")
        sessions = cur.fetchall()
    except Exception as e:
        print(f"Error querying sessions: {e}")
        return
    
    sprints = []
    
    for row in sessions:
        in_tok = row["input_tokens"] or 0
        if in_tok <= 0:
            continue
            
        out_tok = row["output_tokens"] or 0
        model = row["model"] or "unknown"
        
        cost = _estimate_cost(model, in_tok, out_tok)
        
        raw_ts = row["started_at"]
        if isinstance(raw_ts, (int, float)):
            iso_ts = _dt.datetime.fromtimestamp(raw_ts, tz=_dt.timezone.utc).isoformat()
        else:
            iso_ts = str(raw_ts) if raw_ts else ""
            
        sid = f"hermes_{row['id']}"
        
        # In sqlite, row.keys() can be used to check column existence
        keys = row.keys()
        hfc = row["hallucination_findings_count"] if "hallucination_findings_count" in keys else None
        
        rec = {
            "sprint_id": sid,
            "task_id": (row["title"] or "")[:50],
            "task_type": "hermes_session",
            "model": model,
            "tokens_actual_in": in_tok,
            "tokens_actual_out": out_tok,
            "cost_actual_usd": cost,
            "hallucination_findings_count": hfc,
            "hallucination_detected": None,
            "ts": iso_ts,
        }
        sprints.append(rec)
        
    sprints_path = r"c:\Users\Enzo\Documents\MODELS\.claude\05_STATE\token_sprints.json"
    
    # Ensure dir exists
    os.makedirs(os.path.dirname(sprints_path), exist_ok=True)
    
    # Overwrite the file with new valid items
    with open(sprints_path, "w", encoding="utf-8") as f:
        json.dump(sprints, f, indent=2)
        
    print(f"Imported {len(sprints)} sessions to {sprints_path}")

if __name__ == "__main__":
    main()
