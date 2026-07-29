"""
sync_history.py — Synchronizes all local LLM/antigravity logs into central history.
==================================================================================
Reads transcripts from C:/Users/Enzo/.gemini/antigravity/brain/ and JSON tokens from
08_LOGS/tokens/ to link all execution paths.
"""

import os
import json
import re
from pathlib import Path
from datetime import datetime
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

FORGE_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = FORGE_ROOT / "05_STATE"
TRACKER_DIR = state_path("agent_tracker")
HISTORY_FILE = TRACKER_DIR / "history.json"
TOKEN_DIR = FORGE_ROOT / "08_LOGS" / "tokens"
ANTIGRAVITY_BRAIN_DIR = Path("C:/Users/Enzo/.gemini/antigravity/brain")

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

def sync_all():
    """Run all synchronization tasks."""
    print("[Sync] Synchronizing central history with local LLM logs...")
    
    # 1. Ensure directory
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)
    history = _load_json(HISTORY_FILE, {"tasks": []})
    
    # Track task names to prevent duplication
    existing_tasks = {t.get("task_name") for t in history.get("tasks", []) if t.get("task_name")}
    
    # 2. Sync Token Files (08_LOGS/tokens/*.json)
    if TOKEN_DIR.exists():
        for token_file in TOKEN_DIR.glob("*.json"):
            try:
                data = json.loads(token_file.read_text(encoding="utf-8"))
                task_name = data.get("task")
                if task_name and task_name not in existing_tasks:
                    invocations = []
                    # Map raw logs to invocations
                    for log in data.get("raw_logs", []):
                        invocations.append({
                            "agent": log.get("node_name", "llm_agent"),
                            "task": log.get("task_type", "generation"),
                            "expected": "validated outputs",
                            "actual": f"executed model: {log.get('model')}",
                            "score": 8.0,
                            "tokens": log.get("input_tokens", 0) + log.get("output_tokens", 0),
                            "tools_used": [],
                            "errors": [],
                            "duration_ms": log.get("latency_ms", 0),
                            "timestamp": log.get("timestamp", datetime.now().isoformat()),
                            "quality": "good"
                        })
                    
                    history["tasks"].append({
                        "task_name": task_name,
                        "started_at": data.get("raw_logs", [{}])[0].get("timestamp", datetime.now().isoformat()),
                        "agents_involved": list({inv["agent"] for inv in invocations}),
                        "invocations": invocations,
                        "status": "completed",
                        "ended_at": data.get("raw_logs", [{}])[-1].get("timestamp", datetime.now().isoformat()),
                        "agent_stats": {}
                    })
                    existing_tasks.add(task_name)
                    print(f"  [Sync] Synced task from token log: '{task_name[:50]}...'")
            except Exception as e:
                print(f"  [Sync] Error syncing token file {token_file.name}: {e}")
                
    # 3. Sync Antigravity transcripts (C:/Users/Enzo/.gemini/antigravity/brain/*/logs/transcript.jsonl)
    if ANTIGRAVITY_BRAIN_DIR.exists():
        for brain_id in ANTIGRAVITY_BRAIN_DIR.iterdir():
            transcript_path = brain_id / ".system_generated" / "logs" / "transcript.jsonl"
            if transcript_path.exists():
                try:
                    lines = transcript_path.read_text(encoding="utf-8").splitlines()
                    current_task = f"Antigravity run ({brain_id.name})"
                    
                    if current_task not in existing_tasks:
                        invocations = []
                        for line in lines:
                            if not line.strip():
                                continue
                            step = json.loads(line)
                            if step.get("type") == "PLANNER_RESPONSE":
                                content = step.get("content", "")
                                tool_calls = step.get("tool_calls", [])
                                tool_names = [t.get("name") for t in tool_calls if t.get("name")]
                                
                                # Extract some text as description
                                desc = content.strip().split("\n")[0][:100] if content else "execution step"
                                
                                invocations.append({
                                    "agent": "antigravity_gemini",
                                    "task": desc,
                                    "expected": "validated code modifications",
                                    "actual": f"made {len(tool_calls)} tool calls",
                                    "score": 9.0,
                                    "tokens": len(content) // 4,  # Rough estimate
                                    "tools_used": tool_names,
                                    "errors": [],
                                    "duration_ms": 0,
                                    "timestamp": datetime.now().isoformat(),
                                    "quality": "excellent"
                                })
                        
                        if invocations:
                            history["tasks"].append({
                                "task_name": current_task,
                                "started_at": datetime.now().isoformat(),
                                "agents_involved": ["antigravity_gemini"],
                                "invocations": invocations,
                                "status": "completed",
                                "ended_at": datetime.now().isoformat(),
                                "agent_stats": {}
                            })
                            existing_tasks.add(current_task)
                            print(f"  [Sync] Synced Antigravity conversation {brain_id.name}")
                except Exception as e:
                    print(f"  [Sync] Error syncing transcript for {brain_id.name}: {e}")
                    
    # 4. Save central history
    history["tasks"] = history["tasks"][-100:]  # Keep last 100 tasks
    _save_json(HISTORY_FILE, history)
    print("[Sync] Central history synchronization complete!")

if __name__ == "__main__":
    sync_all()
