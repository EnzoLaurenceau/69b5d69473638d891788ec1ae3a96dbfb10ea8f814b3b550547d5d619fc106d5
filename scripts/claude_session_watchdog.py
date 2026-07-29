#!/usr/bin/env python3
"""
Claude Session Auto-Restart Daemon Script
Monitors Hermes SQLite database for sessions that stopped unexpectedly due to token exhaustion
and attempts to resume them.
"""

import os
import sys
import time
import json
import sqlite3
import logging
import argparse
import subprocess
import signal
from datetime import datetime, timedelta
import re

DB_PATH = r"C:\Users\Enzo\AppData\Local\hermes\state.db"
BASE_DIR = r"c:\Users\Enzo\Documents\MODELS\.claude"
STATE_DIR = os.path.join(BASE_DIR, "05_STATE")
LOG_FILE = os.path.join(STATE_DIR, "session_watchdog.log")
PID_FILE = os.path.join(STATE_DIR, "session_watchdog.pid")
STATE_FILE = os.path.join(STATE_DIR, "session_watchdog_state.json")

# Safety limits
MAX_RESTARTS_PER_HOUR = 5
MAX_SESSION_AGE_HOURS = 24
MAX_RETRIES_PER_SESSION = 3
RETRY_BACKOFFS = [30, 120, 300]  # seconds

# Token exhaustion patterns
EXHAUSTION_PATTERNS = [
    r'token.*limit',
    r'max_tokens',
    r'context_window',
    r'rate limit',
    r'insufficient.*tokens'
]

running = True

def signal_handler(signum, frame):
    global running
    logging.info("Received termination signal, shutting down gracefully...")
    running = False

def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)

def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        encoding='utf-8'
    )
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading state file: {e}")
    return {
        "attempted_sessions": {},  # session_id -> retry_count
        "last_check_timestamp": 0,
        "success_count": 0,
        "failure_count": 0,
        "skipped_sessions": [],
        "hourly_restarts": []  # list of timestamps
    }

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving state file: {e}")

def check_rate_limit(state):
    now = time.time()
    # Remove older than 1 hour
    state["hourly_restarts"] = [ts for ts in state.get("hourly_restarts", []) if now - ts < 3600]
    return len(state["hourly_restarts"]) < MAX_RESTARTS_PER_HOUR

def is_token_exhausted(cursor, session_id, tool_call_count):
    cursor.execute("SELECT content, role FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1", (session_id,))
    row = cursor.fetchone()
    if not row:
        return False
    
    content, role = row
    
    # Mid-task stoppage logic: high tool calls but no clear completion (if applicable)
    if tool_call_count and tool_call_count > 10 and role == 'assistant':
        return True

    if not content:
        return False
    
    content_lower = content.lower()
    
    # Check for patterns
    for pattern in EXHAUSTION_PATTERNS:
        if re.search(pattern, content_lower):
            return True
            
    # Check if last message is from assistant and truncated
    if role == 'assistant':
        content_stripped = content.strip()
        if not content_stripped.endswith(('.', '!', '?', '"', "'", '`', '}')):
            return True
            
    return False

def get_target_sessions():
    sessions_to_restart = []
    
    if not os.path.exists(DB_PATH):
        logging.error(f"Database not found at {DB_PATH}")
        return sessions_to_restart
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cutoff_time = time.time() - (MAX_SESSION_AGE_HOURS * 3600)
        
        cursor.execute('''
            SELECT id, title, model, input_tokens, output_tokens, tool_call_count, ended_at, started_at 
            FROM sessions 
            WHERE archived = 0 AND started_at >= ?
        ''', (cutoff_time,))
        
        for row in cursor.fetchall():
            session_id, title, model, input_tokens, output_tokens, tool_call_count, ended_at, started_at = row
            
            if is_token_exhausted(cursor, session_id, tool_call_count):
                sessions_to_restart.append({
                    "id": session_id,
                    "title": title,
                    "model": model,
                    "tokens": (input_tokens or 0) + (output_tokens or 0),
                    "detected_at": ended_at or started_at or time.time()
                })
                
        conn.close()
    except Exception as e:
        logging.error(f"Database error: {e}")
        
    return sessions_to_restart

OUTAGES_FILE = os.path.join(STATE_DIR, "quota_outages_history.json")

def load_outages_history():
    if os.path.exists(OUTAGES_FILE):
        try:
            with open(OUTAGES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_outage_record(session_id, blocked_at_ts, unblocked_at_ts, success):
    outages = load_outages_history()
    blocked_dt = datetime.fromtimestamp(blocked_at_ts).strftime('%Y-%m-%d %H:%M:%S')
    unblocked_dt = datetime.fromtimestamp(unblocked_at_ts).strftime('%Y-%m-%d %H:%M:%S') if unblocked_at_ts else None
    duration_min = round((unblocked_at_ts - blocked_at_ts) / 60.0, 2) if unblocked_at_ts else None

    record = {
        "session_id": session_id,
        "blocked_at": blocked_dt,
        "unblocked_at": unblocked_dt,
        "outage_duration_minutes": duration_min,
        "status": "RESOLVED" if success else "PENDING_RETRY"
    }
    outages.append(record)
    try:
        with open(OUTAGES_FILE, 'w', encoding='utf-8') as f:
            json.dump(outages, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving outage record: {e}")

def attempt_restart(session, state):
    session_id = session["id"]
    retries = state["attempted_sessions"].get(session_id, 0)
    blocked_at_ts = session.get("detected_at", time.time())
    
    if retries >= MAX_RETRIES_PER_SESSION:
        logging.warning(f"Session {session_id} exceeded max retries. Skipping.")
        if session_id not in state["skipped_sessions"]:
            state["skipped_sessions"].append(session_id)
        return False
        
    if retries > 0:
        backoff = RETRY_BACKOFFS[retries - 1]
        logging.info(f"Waiting {backoff}s before retry {retries} for session {session_id}")
        time.sleep(backoff)
        
    blocked_time_str = datetime.fromtimestamp(blocked_at_ts).strftime('%Y-%m-%d %H:%M:%S')
    logging.info(f"Attempting to restart session {session_id} (Blocked since: {blocked_time_str}, title='{session['title']}')")
    
    success = False
    target = session.get('title') if session.get('title') else session_id
    commands = [
        ["hermes", "chat", "-q", f"Reprends la tâche précédente (session {session_id})", "--profile", "forge"],
        ["claude", "--resume", target],
        ["claude", "--continue"]
    ]
    FAILURE_OUTPUT_PATTERNS = [
        r'failed to initialize',
        r'no module named',
        r'error:',
        r'traceback \(most recent call last\)',
        r'rate limit',
        r'quota exceeded',
        r'unauthorized',
        r'insufficient_quota'
    ]

    for cmd in commands:
        try:
            logging.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, input="", timeout=120)
            combined_output = (result.stdout + "\n" + result.stderr).lower()
            
            # Vérifie si la commande s'est exécutée proprement (returncode 0) ET sans message d'erreur fatal
            has_error = any(re.search(pat, combined_output) for pat in FAILURE_OUTPUT_PATTERNS)
            
            if result.returncode == 0 and not has_error and len(result.stdout.strip()) > 10:
                logging.info(f"Command successful: {result.stdout.strip()[:200]}")
                success = True
                break
            else:
                reason = "Error pattern detected in output" if has_error else f"Return code {result.returncode} or output too short"
                logging.warning(f"Command failed validation ({reason}). Output snippet: {combined_output[:250].strip()}")
        except Exception as e:
            logging.error(f"Command execution error: {e}")
        except FileNotFoundError:
            logging.error("claude/hermes command not found in PATH")
            break
            
    state["attempted_sessions"][session_id] = retries + 1
    unblocked_at_ts = time.time()
    
    if success:
        state["success_count"] += 1
        state["hourly_restarts"].append(unblocked_at_ts)
        duration_min = round((unblocked_at_ts - blocked_at_ts) / 60.0, 2)
        logging.info(f"[SUCCESS] Session {session_id} DEBLOQUEE à {datetime.fromtimestamp(unblocked_at_ts).strftime('%Y-%m-%d %H:%M:%S')} (Temps bloqué : {duration_min} min)")
        save_outage_record(session_id, blocked_at_ts, unblocked_at_ts, True)
    else:
        state["failure_count"] += 1
        save_outage_record(session_id, blocked_at_ts, None, False)
        
    save_state(state)
    return success

def perform_check():
    ensure_dirs()
    state = load_state()
    state["last_check_timestamp"] = time.time()
    
    logging.info("Checking for token-exhausted sessions...")
    
    sessions = get_target_sessions()
    for session in sessions:
        if not running:
            break
            
        session_id = session["id"]
        if session_id in state["skipped_sessions"]:
            continue
            
        if not check_rate_limit(state):
            logging.warning("Hourly restart limit reached. Delaying further restarts.")
            break
            
        attempt_restart(session, state)
        
    save_state(state)

def main():
    parser = argparse.ArgumentParser(description="Claude Session Auto-Restart Daemon")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    parser.add_argument("--check", action="store_true", help="Run a one-shot check")
    parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    args = parser.parse_args()
    
    ensure_dirs()
    setup_logging()
    
    if not (args.daemon or args.check):
        parser.print_help()
        return

    if args.check:
        perform_check()
        return

    if args.daemon:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logging.info(f"Starting daemon mode. Polling every {args.interval} seconds.")
        
        while running:
            try:
                perform_check()
            except Exception as e:
                logging.error(f"Unexpected error during check: {e}")
                
            for _ in range(args.interval):
                if not running:
                    break
                time.sleep(1)
                
        logging.info("Daemon stopped.")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

if __name__ == "__main__":
    main()
