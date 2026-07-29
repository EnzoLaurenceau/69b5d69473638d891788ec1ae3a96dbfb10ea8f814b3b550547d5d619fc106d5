#!/usr/bin/env python
"""
hermes_session_tracker.py — Real-time Hermes session tracking for Dashboard
===========================================================================

This script reads from the Hermes session database and updates files that
the dashboard can read for real-time tracking.

Usage:
    python hermes_session_tracker.py              # Run once
    python hermes_session_tracker.py --watch      # Run continuously (every 30s)
    python hermes_session_tracker.py --update-all # Update all dashboard data

What it does:
1. Reads Hermes sessions from state.db
2. Updates 05_STATE/tool_index.json with actual usage data
3. Updates 05_STATE/experience_db.json with session outcomes
4. Updates 05_STATE/agent_tracker/history.json with agent performance
5. Writes 05_STATE/dashboard_stats.json for real-time display
"""

from __future__ import annotations
import json
import sqlite3
import sys
import time
import argparse
import re
import glob
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

HERMES_DB = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
FORGE_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = FORGE_ROOT / "05_STATE"

# Real tool-call ledger + comparative hallucination detection (no invented
# metrics — see 00_CORE/forge_agents/tool_call_ledger.py and
# hallucination_compare.py). Import failure degrades gracefully: the
# ledger/hallucination-derived fields are simply omitted, never guessed.
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
try:
    from forge_agents.tool_call_ledger import build_ledger, ingest_hermes
    from forge_agents.hallucination_compare import (
        scan_ledger,
        save_findings,
        _load_hallucinations as _load_hallucination_events,
    )
except ImportError as e:
    print(f"Warning: forge_agents ledger/hallucination modules not importable ({e}) "
          f"— ledger-derived fields will be omitted, not fabricated.")
    build_ledger = ingest_hermes = scan_ledger = save_findings = None
    _load_hallucination_events = None

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception as exc:
    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

# Ensure dirs exist
STATE_DIR.mkdir(parents=True, exist_ok=True)
(STATE_DIR / "agent_tracker").mkdir(exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat()


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


class HermesSessionTracker:
    """Tracks Hermes sessions and updates dashboard data."""
    
    def __init__(self):
        self.db_path = HERMES_DB
        if not self.db_path.exists():
            print(f"Warning: Hermes DB not found at {self.db_path}")
            self.db = None
        else:
            self.db = sqlite3.connect(str(self.db_path))
            self.db.row_factory = sqlite3.Row
    
    def update_antigravity_sessions(self):
        """Update Antigravity session data and write logs/sprints."""
        brain_dir = Path("C:/Users/Enzo/.gemini/antigravity/brain")
        if not brain_dir.exists():
            return []

        sprint_file = STATE_DIR / "token_sprints.json"
        existing_sprints = _load_json(sprint_file, [])
        existing_ids = {s.get("sprint_id") for s in existing_sprints}

        new_sprints = []
        transcript_files = glob.glob(str(brain_dir / "*" / ".system_generated" / "logs" / "transcript.jsonl"))
        
        for t_file_path in transcript_files:
            try:
                t_file = Path(t_file_path)
                session_id = t_file.parent.parent.parent.name
                
                try:
                    lines = t_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue
                if not lines:
                    continue
                
                title = "Antigravity Session"
                started_at = None
                ended_at = None
                
                input_tokens = 0
                output_tokens = 0
                message_count = 0
                tool_call_count = 0
                
                model_used = "Gemini 3.5 Flash"
                
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                        ts = step.get("created_at")
                        if not started_at:
                            started_at = ts
                        ended_at = ts
                        
                        stype = step.get("type")
                        source = step.get("source")
                        content = step.get("content") or ""
                        tool_calls = step.get("tool_calls") or []
                        
                        if stype == "USER_INPUT":
                            message_count += 1
                            if "USER_REQUEST" in content:
                                match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                                if match:
                                    req_lines = [l.strip() for l in match.group(1).splitlines() if l.strip()]
                                    if req_lines:
                                        title = req_lines[0][:100]
                            
                            settings = step.get("USER_SETTINGS_CHANGE") or ""
                            if "Model Selection" in settings:
                                m_match = re.search(r"Model Selection from .*? to (.*?)\.", settings)
                                if m_match:
                                    model_used = m_match.group(1).strip()
                        
                        elif stype == "PLANNER_RESPONSE":
                            message_count += 1
                            tool_call_count += len(tool_calls)
                        
                        tokens_est = len(content) // 4
                        if source == "MODEL":
                            output_tokens += tokens_est
                            if tool_calls:
                                output_tokens += len(json.dumps(tool_calls)) // 4
                        else:
                            input_tokens += tokens_est
                    except Exception:
                        continue
                
                sprint_id = f"antigravity_{session_id}"

                # tokens_estimated_in/out, cost_estimated_usd, variance_pct,
                # cost_actual_usd, latency_ms are OMITTED — this ingester
                # never computes a real Gemini cost or measures latency, so
                # asserting 0/$0 would falsely claim "verified $0"/"0ms"
                # rather than "not computed". hallucination_detected is also
                # omitted: tool_call_ledger has no Antigravity source, so
                # this session_id has zero ledger coverage — there is no
                # evidence to check, and False would falsely claim "verified
                # absent" for a check that never ran.
                sprint = {
                    "sprint_id": sprint_id,
                    "task_id": title,
                    "task_type": self._detect_domain(title),
                    "model": model_used,
                    "tokens_actual_in": input_tokens,
                    "tokens_actual_out": output_tokens,
                    "ts": ended_at or _now(),
                }

                log_data = {
                    "task": title,
                    "session_id": sprint_id,
                    "estimate_table": "",
                    "actual_table": "",
                    "recommendations": [f"Antigravity session {session_id}"],
                    # efficiency_score/savings_usd/efficiency_savings are
                    # OMITTED (not a fabricated 100.0/perfect-efficiency
                    # claim) — this ingester never runs the real efficiency
                    # computation token_tracker.py's TokenTracker performs
                    # for genuine forge sessions, so it has nothing honest to
                    # report here. token_tracker.savings_summary() sums these
                    # fields with .get(field, 0) across every 08_LOGS/tokens/
                    # *.json file, so omitting them is also safe: it
                    # contributes 0 to that real aggregate, same as the
                    # explicit-0 it replaces, without asserting a specific
                    # per-session efficiency figure that was never computed.
                    "raw_logs": [{
                        "model": model_used,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "node_name": "antigravity",
                        "task_type": self._detect_domain(title),
                        "timestamp": ended_at or _now()
                    }],
                    "retrospective": True,
                    "retro_model": model_used,
                    "retro_msg_count": message_count,
                    "retro_tool_calls": tool_call_count,
                }
                
                token_dir = FORGE_ROOT / "08_LOGS" / "tokens"
                token_dir.mkdir(parents=True, exist_ok=True)
                log_file = token_dir / f"TKL_{sprint_id}.json"
                _save_json(log_file, log_data)
                
                updated = False
                for idx, s in enumerate(existing_sprints):
                    if s.get("sprint_id") == sprint_id:
                        existing_sprints[idx] = sprint
                        updated = True
                        break
                if not updated:
                    existing_sprints.append(sprint)
                    new_sprints.append(sprint)
                    
            except Exception as e:
                print(f"Error parsing Antigravity session: {e}")
                
        existing_sprints = existing_sprints[-200:]
        _save_json(sprint_file, existing_sprints)
        print(f"✓ Antigravity sprints updated: {len(new_sprints)} new entries")
        return new_sprints

    def get_all_sessions(self) -> list[dict]:
        """Merge Hermes DB sessions with token log sessions (Antigravity & others)"""
        sessions = self.get_sessions(limit=100)
        session_ids = {s["session_id"] for s in sessions}

        token_dir = FORGE_ROOT / "08_LOGS" / "tokens"
        if token_dir.exists():
            for f in token_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    sid = data.get("session_id")
                    if not sid:
                        continue
                    if sid in session_ids:
                        continue
                    
                    raw_logs = data.get("raw_logs", [])
                    input_tokens = sum(log.get("input_tokens", 0) for log in raw_logs)
                    output_tokens = sum(log.get("output_tokens", 0) for log in raw_logs)
                    actual_cost = sum(log.get("cost_usd", 0) for log in raw_logs)
                    
                    started_at = None
                    if raw_logs:
                        started_at_str = raw_logs[0].get("timestamp")
                        if started_at_str:
                            try:
                                if "T" in started_at_str:
                                    dt = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                                    started_at = dt.timestamp()
                            except Exception as exc:
                                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
                    
                    if not started_at:
                        started_at = f.stat().st_mtime
                        
                    model = ""
                    if raw_logs:
                        model = raw_logs[0].get("model", "")
                    
                    msg_count = len(raw_logs) * 2
                    if "retrospective" in data:
                        msg_count = data.get("retro_msg_count", msg_count)
                    tool_calls = sum(log.get("tool_calls", 0) for log in raw_logs)
                    if "retrospective" in data:
                        tool_calls = data.get("retro_tool_calls", tool_calls)

                    sessions.append({
                        "session_id": sid,
                        "title": data.get("task") or f.stem,
                        "started_at": started_at,
                        "model": model,
                        "message_count": msg_count,
                        "tool_call_count": tool_calls,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "actual_cost_usd": actual_cost,
                        # No equivalent column in these token-log files —
                        # explicit None, never guessed.
                        "end_reason": None,
                        "ended_at": None,
                    })
                    session_ids.add(sid)
                except Exception as e:
                    print(f"Error parsing token log {f.name}: {e}")
                    
        for s in sessions:
            if isinstance(s["started_at"], str):
                try:
                    s["started_at"] = float(s["started_at"])
                except Exception:
                    try:
                        dt = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
                        s["started_at"] = dt.timestamp()
                    except Exception:
                        s["started_at"] = 0.0

        sessions.sort(key=lambda x: x["started_at"], reverse=True)
        return sessions
    
    def get_sessions(self, limit: int = 100) -> list[dict]:
        """Get recent Hermes sessions."""
        if not self.db:
            return []
        
        try:
            rows = self.db.execute("""
                SELECT id, title, started_at, ended_at, model,
                       message_count, tool_call_count,
                       input_tokens, output_tokens, actual_cost_usd, end_reason
                FROM sessions
                WHERE archived = 0 OR archived IS NULL
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            sessions = []
            for row in rows:
                sessions.append({
                    "session_id": row["id"],
                    "title": row["title"] or "",
                    "started_at": row["started_at"],
                    # Real column value, never guessed — None if the DB
                    # never recorded a real end time (e.g. still running).
                    "ended_at": row["ended_at"],
                    "model": row["model"] or "",
                    "message_count": row["message_count"] or 0,
                    "tool_call_count": row["tool_call_count"] or 0,
                    "input_tokens": row["input_tokens"] or 0,
                    "output_tokens": row["output_tokens"] or 0,
                    "actual_cost_usd": row["actual_cost_usd"] or 0,
                    # Real column value, never guessed — None if the session
                    # row hasn't recorded an end_reason (e.g. still running).
                    "end_reason": row["end_reason"],
                })
            return sessions
        except Exception as e:
            print(f"Error reading sessions: {e}")
            return []
    
    def get_session_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get messages from a specific session."""
        if not self.db:
            return []
        
        try:
            rows = self.db.execute("""
                SELECT id, role, content, timestamp, tool_calls
                FROM messages 
                WHERE session_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (session_id, limit)).fetchall()
            
            messages = []
            for row in rows:
                messages.append({
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"] or "",
                    "timestamp": row["timestamp"],
                    "tool_calls": row["tool_calls"],
                })
            return messages
        except Exception as e:
            print(f"Error reading messages: {e}")
            return []
    
    def update_dashboard_stats(self):
        """Update dashboard statistics from Hermes and Antigravity data."""
        sessions = self.get_all_sessions()
        
        # Calculate stats
        total_sessions = len(sessions)
        total_messages = sum(s.get("message_count", 0) for s in sessions)
        total_tool_calls = sum(s.get("tool_call_count", 0) for s in sessions)
        total_input_tokens = sum(s.get("input_tokens", 0) for s in sessions)
        total_output_tokens = sum(s.get("output_tokens", 0) for s in sessions)
        total_cost = sum(s.get("actual_cost_usd", 0) for s in sessions)
        
        # Recent sessions (last 24h)
        now = time.time()
        recent_sessions = [
            s for s in sessions 
            if s.get("started_at", 0) > now - 86400
        ]
        
        # Convert timestamp to ISO string for last_sessions before saving
        last_sessions_serialized = []
        for s in sessions[:15]:
            s_copy = dict(s)
            try:
                s_copy["started_at"] = datetime.fromtimestamp(s["started_at"]).isoformat()
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            last_sessions_serialized.append(s_copy)

        stats = {
            "timestamp": _now(),
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_tool_calls": total_tool_calls,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": round(total_cost, 4),
            "recent_sessions_24h": len(recent_sessions),
            "recent_messages_24h": sum(s.get("message_count", 0) for s in recent_sessions),
            "recent_tokens_24h": sum(
                s.get("input_tokens", 0) + s.get("output_tokens", 0) 
                for s in recent_sessions
            ),
            "last_sessions": last_sessions_serialized,
            "models_used": list(set(s.get("model", "") for s in sessions if s.get("model"))),
        }
        
        # Save to dashboard_stats.json
        _save_json(STATE_DIR / "dashboard_stats.json", stats)
        print(f"✓ Dashboard stats updated: {total_sessions} sessions, {total_messages} messages")
        
        return stats
    
    def update_tool_usage(self):
        """Update tool usage from REAL tool-call events (tool_call_ledger's
        ingest_hermes()) — tallies literal tool_name values recorded in the
        Hermes DB. Never guesses usage from session-title keyword matching
        (that could attribute a tool that was never actually called).

        Only tool_index.json entries with a real matching tool_name get
        use_count/last_used updated. Non-matching entries are left
        untouched — we have no evidence either way, and forcing them to 0
        would itself be an unverified claim."""
        if ingest_hermes is None:
            print("Warning: tool_call_ledger not importable — skipping real tool usage update")
            return {}

        records = ingest_hermes()

        tool_index = _load_json(STATE_DIR / "tool_index.json", [])
        index_names = {t.get("name") for t in tool_index}

        counts: dict[str, int] = {}
        last_used_ts: dict[str, float] = {}
        unmatched_names: set[str] = set()
        for rec in records:
            name = rec.get("tool_name")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            ts = rec.get("timestamp")
            if ts and (name not in last_used_ts or ts > last_used_ts[name]):
                last_used_ts[name] = ts
            if name not in index_names:
                unmatched_names.add(name)

        matched = 0
        for tool in tool_index:
            tool_name = tool.get("name", "")
            if tool_name in counts:
                tool["use_count"] = counts[tool_name]
                ts = last_used_ts.get(tool_name)
                if ts:
                    tool["last_used"] = datetime.fromtimestamp(ts).isoformat()
                matched += 1

        _save_json(STATE_DIR / "tool_index.json", tool_index)
        print(f"✓ Tool usage updated from real ledger: {matched} tool(s) matched real calls "
              f"out of {len(counts)} distinct tool_name(s) seen in {len(records)} ledger record(s)")
        if unmatched_names:
            print(f"  Taxonomy mismatch — ledger tool_name(s) not in tool_index.json: "
                  f"{sorted(unmatched_names)[:20]}")

        return counts
    
    def update_experience_db(self):
        """Update experience database from session data."""
        sessions = self.get_sessions(limit=50)
        
        # Load existing experience DB
        exp_db = _load_json(STATE_DIR / "experience_db.json", {"experiences": []})
        existing_ids = {e.get("id") for e in exp_db.get("experiences", [])}
        
        # Add new sessions as experiences
        new_experiences = []
        for session in sessions:
            session_id = session.get("session_id", "")
            if session_id in existing_ids:
                continue
            
            # Create experience from session. outcome is the REAL end_reason
            # column value (None if the DB never recorded one) — never
            # assumed "success" just because a row exists. quality_score is
            # dropped entirely: no ground-truth quality signal exists in the
            # Hermes DB, so inventing one would violate the no-invented-data
            # requirement (dashboard/graph already tolerate a missing key).
            exp = {
                "id": session_id[:12] if session_id else _now()[:12],
                "task": session.get("title", "Unknown task"),
                "outcome": session.get("end_reason"),
                "tokens_used": session.get("input_tokens", 0) + session.get("output_tokens", 0),
                "domain": self._detect_domain(session.get("title", "")),
                "timestamp": _now(),
                "metadata": {
                    "model": session.get("model", ""),
                    "message_count": session.get("message_count", 0),
                    "tool_calls": session.get("tool_call_count", 0),
                }
            }
            new_experiences.append(exp)
        
        # Add to experience DB
        exp_db.setdefault("experiences", []).extend(new_experiences)
        
        # Keep only last 200 experiences
        exp_db["experiences"] = exp_db["experiences"][-200:]
        
        _save_json(STATE_DIR / "experience_db.json", exp_db)
        print(f"✓ Experience DB updated: {len(new_experiences)} new entries")
        
        return new_experiences
    
    def _detect_domain(self, title: str) -> str:
        """Detect domain from session title."""
        title_lower = title.lower()
        
        if any(kw in title_lower for kw in ["code", "python", "javascript", "debug", "fix"]):
            return "coding"
        elif any(kw in title_lower for kw in ["research", "analyze", "study"]):
            return "research"
        elif any(kw in title_lower for kw in ["write", "content", "blog", "article"]):
            return "writing"
        elif any(kw in title_lower for kw in ["design", "ui", "ux", "landing"]):
            return "design"
        elif any(kw in title_lower for kw in ["security", "audit", "pentest", "vuln"]):
            return "security"
        elif any(kw in title_lower for kw in ["bot", "telegram", "discord"]):
            return "bot"
        else:
            return "general"
    
    def update_agent_tracker(self):
        """Update agent tracker from session data."""
        sessions = self.get_sessions(limit=50)
        
        # Load existing history
        history_file = STATE_DIR / "agent_tracker" / "history.json"
        history = _load_json(history_file, {"tasks": []})
        
        self._ensure_ledger()

        # Create tasks from sessions
        for session in sessions[:10]:  # Last 10 sessions
            task_name = session.get("title", "Unknown task")

            # Check if already in history
            existing = any(
                t.get("task_name") == task_name
                for t in history.get("tasks", [])
            )
            if existing:
                continue

            session_id = session.get("session_id", "")
            # Real, checked count of concrete claim-vs-tool-result mismatches
            # for this session — replaces the old invented 5-10 "score"
            # formula and hardcoded "quality": "good". None means "not
            # checked" (no ledger coverage for this session_id), never a
            # guessed number.
            hallucination_findings_count = self._real_hallucination_count(session_id)

            # Real end time (None if the DB never recorded one) — never the
            # write-time _now(), which would falsely assert "this session
            # ended right now" for a session that may have ended days ago.
            real_ended_at = session.get("ended_at")
            real_started_at = session.get("started_at")
            duration_ms = None
            if isinstance(real_ended_at, (int, float)) and isinstance(real_started_at, (int, float)) and real_ended_at > real_started_at:
                duration_ms = round((real_ended_at - real_started_at) * 1000)

            # Create task entry. Dropped vs. the old version: "expected"/
            # "actual" (a fabricated success narrative), "score" (an
            # ungrounded 7.0 + tool_call_count*0.1 formula), "quality"
            # (hardcoded "good"), and agent_stats' "quality_distribution"/
            # "completion_rate"/"trend" (all hardcoded constants with no
            # ground-truth signal). Nothing invented replaces them. "status"
            # is the session's real end_reason column (None if unrecorded —
            # e.g. still running), not a hardcoded "completed" narrative.
            task = {
                "task_name": task_name,
                "started_at": real_started_at,
                "ended_at": real_ended_at,
                "agents_involved": ["hermes"],
                "invocations": [{
                    "agent": "hermes",
                    "task": task_name,
                    "message_count": session.get("message_count", 0),
                    "tool_call_count": session.get("tool_call_count", 0),
                    "hallucination_findings_count": hallucination_findings_count,
                    "tokens": session.get("input_tokens", 0) + session.get("output_tokens", 0),
                    "tools_used": [],
                    "errors": [],
                    "duration_ms": duration_ms,
                    "timestamp": _now(),
                }],
                "status": session.get("end_reason"),
                "agent_stats": {
                    "hermes": {
                        "count": 1,
                        "total_tokens": session.get("input_tokens", 0) + session.get("output_tokens", 0),
                        "hallucination_findings_count": hallucination_findings_count,
                    }
                }
            }
            history.setdefault("tasks", []).append(task)
        
        # Keep only last 50 tasks
        history["tasks"] = history["tasks"][-50:]
        
        _save_json(history_file, history)
        print(f"✓ Agent tracker updated: {len(history.get('tasks', []))} total tasks")
        
        return history
    
    def _ensure_ledger(self):
        """Build/refresh 05_STATE/tool_call_ledger.jsonl once per tracker
        run (idempotent guard) so update_agent_tracker/update_sprint_data/
        update_hallucinations don't each redundantly re-query the Hermes DB
        and re-glob Claude Code transcripts within the same update cycle.

        Also records which session_ids the ledger actually covers
        (self._ledger_session_ids). The ledger only holds the ~500 most
        recent tool-call events per source, so most older sessions have
        ZERO ledger coverage. scan_ledger(session_id=X) returns an empty
        list both when a session genuinely has 0 findings AND when it has
        no ledger records at all — those are not the same claim. Callers
        MUST check `session_id in self._ledger_session_ids` before treating
        a 0 finding count as "verified clean" rather than "not checked"."""
        if getattr(self, "_ledger_ready", False):
            return
        self._ledger_session_ids: set = set()
        if build_ledger is None:
            self._ledger_ready = False
            return
        try:
            result = build_ledger()
            ledger_path = Path(result["out_path"])
            if ledger_path.exists():
                with ledger_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        sid = rec.get("session_id")
                        if sid:
                            self._ledger_session_ids.add(sid)
            self._ledger_ready = True
        except Exception as e:
            print(f"Warning: tool_call_ledger build failed: {e}")
            self._ledger_ready = False

    def _real_hallucination_count(self, session_id: str) -> Optional[int]:
        """Real, checked finding count for session_id, or None if the
        ledger has no coverage for it (never a guessed/defaulted 0)."""
        if not session_id or scan_ledger is None:
            return None
        if session_id not in getattr(self, "_ledger_session_ids", set()):
            return None
        return len(scan_ledger(session_id=session_id))

    def update_hallucinations(self):
        """Populate 05_STATE/hallucination_events.json with REAL findings
        from hallucination_compare.scan_ledger() — real, checked mismatches
        between a claim and the tool result it should be grounded in, not
        an unconditional False. Reuses hallucination_compare.save_findings()
        (which itself replicates 09_WEB/server.py's exact
        _load_hallucinations/_save_hallucinations/api_hallucination_report
        read-merge-cap500-write envelope) — no second divergent schema.

        Dedupes against already-recorded events (same agent/node/root_cause/
        session_id/timestamp) so re-scanning the same ledger window every
        cycle doesn't spam duplicate events for the same real tool call."""
        self._ensure_ledger()
        if scan_ledger is None or save_findings is None or _load_hallucination_events is None:
            print("Warning: hallucination_compare not importable — skipping hallucination refresh")
            return []

        findings = scan_ledger()
        existing = _load_hallucination_events()

        def _fingerprint(e: dict) -> tuple:
            ctx = e.get("context") or {}
            return (e.get("agent"), e.get("node"), e.get("root_cause"),
                    ctx.get("session_id"), ctx.get("timestamp"))

        seen = {_fingerprint(e) for e in existing}
        new_findings = [f for f in findings if _fingerprint(f) not in seen]

        saved = save_findings(new_findings) if new_findings else []
        print(f"✓ Hallucination scan: {len(findings)} finding(s) in ledger, "
              f"{len(saved)} new event(s) saved "
              f"({len(findings) - len(new_findings)} already recorded)")
        return saved

    def update_all(self):
        """Update all dashboard data."""
        print("=" * 60)
        print("HERMES & ANTIGRAVITY SESSION TRACKER — Updating Dashboard")
        print("=" * 60)
        print(f"Hermes DB: {self.db_path}")
        print()

        # 1. Update Antigravity sessions first
        self.update_antigravity_sessions()

        # 2. Run standard updates with merged data
        self.update_dashboard_stats()
        self.update_tool_usage()
        self.update_experience_db()
        self.update_agent_tracker()
        self.update_sprint_data()
        self.update_hallucinations()

        print()
        print("=" * 60)
        print("Update complete. Dashboard will refresh automatically.")
        print("=" * 60)

    def update_sprint_data(self):
        """Update sprint data from all sessions."""
        sessions = self.get_all_sessions()

        # Load existing sprint data
        sprint_file = STATE_DIR / "token_sprints.json"
        existing_sprints = _load_json(sprint_file, [])
        existing_ids = {s.get("sprint_id") for s in existing_sprints}

        self._ensure_ledger()

        # Create sprint entries from sessions
        new_sprints = []
        for session in sessions:
            session_id = session.get("session_id", "")
            if session_id in existing_ids:
                continue

            input_tokens = session.get("input_tokens", 0)
            output_tokens = session.get("output_tokens", 0)

            # Real, checked hallucination detection for this session — scans
            # only this session's tool_call_ledger records via
            # hallucination_compare.scan_ledger(session_id=...). None means
            # "not checked" (no ledger coverage for this session_id), which
            # is honest; it is never coerced to False.
            hallucination_findings_count = self._real_hallucination_count(session_id)

            # Create sprint entry. tokens_estimated_in/out and latency_ms are
            # DROPPED entirely — this tracker never produces an estimate or
            # measures latency, so a hardcoded 0 would falsely assert
            # "estimated 0 tokens"/"0ms" rather than "not applicable".
            sprint = {
                "sprint_id": session_id,
                "task_id": session.get("title", "Unknown task"),
                "task_type": self._detect_domain(session.get("title", "")),
                "model": session.get("model", "unknown"),
                "tokens_actual_in": input_tokens,
                "tokens_actual_out": output_tokens,
                "cost_actual_usd": session.get("actual_cost_usd", 0.0),
                "hallucination_findings_count": hallucination_findings_count,
                "hallucination_detected": (
                    hallucination_findings_count > 0
                    if hallucination_findings_count is not None else None
                ),
                "ts": _now(),
            }
            new_sprints.append(sprint)
        
        # Add to sprint data
        existing_sprints.extend(new_sprints)
        
        # Keep only last 200 sprints
        existing_sprints = existing_sprints[-200:]
        
        _save_json(sprint_file, existing_sprints)
        print(f"✓ Sprint data updated: {len(new_sprints)} new entries")
        
        return new_sprints
    
    def watch(self, interval: int = 30):
        """Watch for changes and update continuously."""
        print(f"Watching for Hermes session changes (interval: {interval}s)")
        print("Press Ctrl+C to stop")
        print()
        
        while True:
            try:
                self.update_all()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nStopped watching")
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(interval)
    
    def close(self):
        """Close database connection."""
        if self.db:
            self.db.close()


def main():
    parser = argparse.ArgumentParser(description="Hermes Session Tracker for Dashboard")
    parser.add_argument("--watch", action="store_true", help="Watch continuously")
    parser.add_argument("--update-all", action="store_true", help="Update all data once")
    parser.add_argument("--interval", type=int, default=30, help="Watch interval in seconds")
    args = parser.parse_args()
    
    tracker = HermesSessionTracker()
    
    try:
        if args.watch:
            tracker.watch(interval=args.interval)
        elif args.update_all:
            tracker.update_all()
        else:
            # Default: update all once
            tracker.update_all()
    finally:
        tracker.close()


if __name__ == "__main__":
    main()
