#!/usr/bin/env python
"""
recursive_optimizer.py — RecursiveMAS-inspired optimizations for La Forge
=========================================================================

Applies latent-space recursion principles to reduce token consumption:
1. Shared State File — agents read/write compressed state instead of full text
2. Session Limits — auto-trim sessions exceeding token budgets
3. Prompt Compression — NMP format, minimal system prompts
4. Recursive Refinement — short Planner→Solver→Critic loops

Based on RecursiveMAS (UIUC/Stanford/NVIDIA/MIT, arxiv:2604.25917)
Principles applied without requiring GPU — works with API-based agents.

Usage:
  python recursive_optimizer.py --status      # Show current optimization state
  python recursive_optimizer.py --compress     # Compress shared state
  python recursive_optimizer.py --trim-sessions # Trim long sessions
  python recursive_optimizer.py --daemon       # Run as background optimizer
"""

from __future__ import annotations

import json
import time
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────
FORGE_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = FORGE_ROOT / "05_STATE"
SHARED_STATE = STATE_DIR / "shared_context.json"
COMPRESSED_STATE = STATE_DIR / "compressed_context.nmp"
OPTIMIZER_LOG = STATE_DIR / "optimizer.log"
HERMES_DB = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
CLAUDE_DIR = Path.home() / ".claude"

STATE_DIR.mkdir(parents=True, exist_ok=True)

# ─── NMP Format (compact JSON) ──────────────────────────────────────────────
def to_nmp(data: Any, depth: int = 0) -> str:
    """Convert to NMP (Nous Minimal Protocol) — ultra-compact JSON.
    
    Rules:
    - No whitespace except between key-value pairs
    - Short keys (abbreviated)
    - Numbers not strings where possible
    - Arrays of primitives on one line
    - Nested objects flattened when possible
    """
    if isinstance(data, dict):
        if depth == 0:
            items = [f"{k}:{to_nmp(v, depth+1)}" for k, v in data.items()]
            return "{" + ",".join(items) + "}"
        items = [f"{k}:{to_nmp(v, depth+1)}" for k, v in data.items()]
        return "{" + ",".join(items) + "}"
    elif isinstance(data, list):
        if len(data) <= 10 and all(isinstance(x, (int, float, str, bool)) for x in data):
            return "[" + ",".join(repr(x) if isinstance(x, str) else str(x) for x in data) + "]"
        return "[" + ",".join(to_nmp(x, depth+1) for x in data) + "]"
    elif isinstance(data, str):
        if len(data) > 100:
            return repr(data[:97] + "...")
        return repr(data)
    elif isinstance(data, bool):
        return "1" if data else "0"
    elif isinstance(data, float):
        return f"{data:.4g}"
    else:
        return str(data)


# ─── 1. SHARED STATE FILE ───────────────────────────────────────────────────

class SharedStateManager:
    """Manages a compressed shared context state.
    
    Instead of agents sending full context in every message,
    they read from SHARED_STATE and only send deltas.
    
    Inspired by RecursiveMAS's latent-space state transfer.
    """
    
    def __init__(self):
        self.state_path = SHARED_STATE
        self.compressed_path = COMPRESSED_STATE
        self.state = self._load()
    
    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return {
            "v": 2,  # schema version
            "ts": 0,  # last update timestamp
            "agents": {},  # per-agent compressed state
            "shared": {},  # truly shared context
            "tasks": [],  # active task queue
            "cache": {},  # reusable context snippets
        }
    
    def save(self):
        self.state["ts"] = time.time()
        # Write full state
        self.state_path.write_text(
            json.dumps(self.state, indent=1, ensure_ascii=False),
            encoding="utf-8"
        )
        # Write NMP compressed version
        self.compressed_path.write_text(
            to_nmp(self.state),
            encoding="utf-8"
        )
    
    def update_agent(self, agent_id: str, data: dict):
        """Update a specific agent's state (delta only)."""
        if agent_id not in self.state["agents"]:
            self.state["agents"][agent_id] = {}
        self.state["agents"][agent_id].update(data)
        self.state["agents"][agent_id]["_ts"] = time.time()
        self.save()
    
    def get_context_for(self, agent_id: str, max_tokens: int = 500) -> str:
        """Get compressed context for an agent.
        
        Returns only what's relevant, in NMP format.
        Target: < max_tokens worth of context.
        """
        ctx = {
            "shared": self.state.get("shared", {}),
            "agent_state": self.state.get("agents", {}).get(agent_id, {}),
            "active_tasks": self.state.get("tasks", [])[:3],  # Top 3 tasks only
        }
        
        # Remove empty keys
        ctx = {k: v for k, v in ctx.items() if v}
        
        nmp = to_nmp(ctx)
        
        # Rough token estimate: 1 token ≈ 4 chars
        est_tokens = len(nmp) // 4
        if est_tokens > max_tokens:
            # Truncate tasks further
            ctx["active_tasks"] = ctx.get("active_tasks", [])[:1]
            nmp = to_nmp(ctx)
        
        return nmp
    
    def add_task(self, task: dict):
        """Add a task to the shared queue."""
        self.state.setdefault("tasks", []).append({
            "id": task.get("id", str(int(time.time()))),
            "desc": task.get("desc", "")[:100],
            "status": task.get("status", "pending"),
            "ts": time.time(),
        })
        # Keep only last 10 tasks
        self.state["tasks"] = self.state["tasks"][-10:]
        self.save()
    
    def set_shared(self, key: str, value: Any):
        """Set a shared context value."""
        self.state.setdefault("shared", {})[key] = value
        self.save()
    
    def get_stats(self) -> dict:
        """Get optimization stats."""
        full_size = len(json.dumps(self.state, ensure_ascii=False))
        nmp_size = len(to_nmp(self.state))
        return {
            "full_size_bytes": full_size,
            "nmp_size_bytes": nmp_size,
            "compression_ratio": round(full_size / max(nmp_size, 1), 2),
            "agents": len(self.state.get("agents", {})),
            "tasks": len(self.state.get("tasks", [])),
            "last_update": self.state.get("ts", 0),
        }


# ─── 2. SESSION LIMITS ─────────────────────────────────────────────────────

class SessionLimiter:
    """Auto-trim sessions that exceed token budgets.
    
    Inspired by RecursiveMAS's efficient recursion loops:
    instead of 950 messages in one session, cap at 200 and
    start fresh with compressed context.
    """
    
    MAX_MESSAGES = 200
    MAX_TOKENS_PER_SESSION = 5_000_000  # 5M tokens max
    
    def __init__(self):
        self.db_path = HERMES_DB
    
    def check_sessions(self) -> list[dict]:
        """Find sessions exceeding limits."""
        if not self.db_path.exists():
            return []
        
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        rows = conn.execute("""
            SELECT id, title, message_count, input_tokens, output_tokens,
                   (input_tokens + output_tokens) as total_tokens,
                   started_at, model
            FROM sessions
            WHERE archived = 0 OR archived IS NULL
            ORDER BY started_at DESC
            LIMIT 50
        """).fetchall()
        
        violations = []
        for r in rows:
            issues = []
            if (r["message_count"] or 0) > self.MAX_MESSAGES:
                issues.append(f"messages={r['message_count']} > {self.MAX_MESSAGES}")
            if (r["total_tokens"] or 0) > self.MAX_TOKENS_PER_SESSION:
                issues.append(f"tokens={r['total_tokens']:,} > {self.MAX_TOKENS_PER_SESSION:,}")
            
            if issues:
                violations.append({
                    "id": r["id"],
                    "title": r["title"] or "",
                    "messages": r["message_count"] or 0,
                    "tokens": r["total_tokens"] or 0,
                    "issues": issues,
                })
        
        conn.close()
        return violations
    
    def get_session_report(self) -> str:
        """Generate a session health report."""
        violations = self.check_sessions()
        if not violations:
            return "✓ Toutes les sessions dans les limites"
        
        lines = [f"⚠ {len(violations)} session(s) dépassent les limites:"]
        for v in violations[:5]:
            lines.append(f"  • {v['title'][:40]} — {', '.join(v['issues'])}")
        return "\n".join(lines)


# ─── 3. PROMPT COMPRESSION ─────────────────────────────────────────────────

class PromptCompressor:
    """Compress prompts and context using NMP format.
    
    Inspired by RecursiveMAS's latent-space compression:
    instead of verbose text, use structured minimal data.
    """
    
    # Common patterns to compress
    COMPRESSION_MAP = {
        "je voudrais que tu": "fais",
        "peux-tu": "fais",
        "j'aimerais que tu": "fais",
        "est-ce que tu peux": "fais",
        "il faut que tu": "fais",
        "s'il te plaît": "",
        "pourrais-tu": "fais",
        "serait-il possible de": "fais",
        "tu devrais": "",
        "en fait": "",
        "donc": "",
        "voici ce qu'il faut faire:": "",
        "étape par étape:": "",
    }
    
    # Stop words that add no meaning
    STOP_WORDS = {
        "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou",
        "mais", "donc", "car", "ni", "que", "qui", "quoi", "dont",
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
    }
    
    @staticmethod
    def compress_prompt(text: str) -> str:
        """Compress a user prompt to minimal form."""
        result = text.strip()
        
        # Apply pattern compression
        for old, new in PromptCompressor.COMPRESSION_MAP.items():
            result = result.replace(old, new)
        
        # Remove multiple spaces
        while "  " in result:
            result = result.replace("  ", " ")
        
        return result.strip()
    
    @staticmethod
    def compress_context(context: dict) -> str:
        """Compress a context dict to NMP format."""
        return to_nmp(context)
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token count estimate."""
        return len(text) // 4
    
    @staticmethod
    def truncate_smart(text: str, max_tokens: int = 500) -> str:
        """Smart truncation that preserves meaning."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        
        # Try to cut at sentence boundary
        truncated = text[:max_chars]
        last_period = truncated.rfind(".")
        last_newline = truncated.rfind("\n")
        cut_point = max(last_period, last_newline)
        
        if cut_point > max_chars * 0.7:
            return truncated[:cut_point + 1]
        return truncated + "..."


# ─── 4. RECURSIVE REFINEMENT ───────────────────────────────────────────────

class RecursiveRefiner:
    """Short-loop Planner→Solver→Critic pattern.
    
    Instead of one long 950-message session, use 3 short passes:
    1. Planner: analyze task, create plan (20-30 messages)
    2. Solver: execute plan (50-80 messages)
    3. Critic: verify result, flag issues (10-20 messages)
    
    Total: 80-130 messages instead of 950.
    Each pass starts fresh with compressed context from previous.
    """
    
    PHASES = ["plan", "solve", "verify"]
    PHASE_LIMITS = {
        "plan": 30,    # max messages for planning
        "solve": 80,   # max messages for solving
        "verify": 20,  # max messages for verification
    }
    
    def __init__(self):
        self.shared = SharedStateManager()
    
    def create_refinement_task(self, task_desc: str) -> dict:
        """Create a refinement task with 3 phases."""
        task = {
            "id": f"ref_{int(time.time())}",
            "desc": task_desc[:200],
            "phases": {
                "plan": {"status": "pending", "msgs": 0, "output": ""},
                "solve": {"status": "pending", "msgs": 0, "output": ""},
                "verify": {"status": "pending", "msgs": 0, "output": ""},
            },
            "current_phase": "plan",
            "created_at": time.time(),
        }
        self.shared.add_task(task)
        return task
    
    def get_phase_prompt(self, phase: str, task_desc: str, prev_output: str = "") -> str:
        """Get compressed prompt for a specific phase."""
        if phase == "plan":
            return f"PLAN: {task_desc}\nOutput: JSON plan with steps"
        elif phase == "solve":
            ctx = PromptCompressor.compress_context({
                "task": task_desc[:100],
                "plan": prev_output[:200],
            })
            return f"SOLVE: {ctx}\nExecute plan. Be concise."
        elif phase == "verify":
            ctx = PromptCompressor.compress_context({
                "task": task_desc[:100],
                "result": prev_output[:200],
            })
            return f"VERIFY: {ctx}\nCheck correctness. Report issues only."
        return ""
    
    def should_advance(self, phase: str, msg_count: int) -> bool:
        """Check if we should advance to next phase."""
        limit = self.PHASE_LIMITS.get(phase, 50)
        return msg_count >= limit


# ─── CLI ────────────────────────────────────────────────────────────────────

def show_status():
    """Show optimizer status."""
    shared = SharedStateManager()
    limiter = SessionLimiter()
    
    stats = shared.get_stats()
    violations = limiter.check_sessions()
    
    print("=" * 60)
    print("RECURSIVE OPTIMIZER — Status")
    print("=" * 60)
    print(f"  Shared State:")
    print(f"    Full size:    {stats['full_size_bytes']:,} bytes")
    print(f"    NMP size:     {stats['nmp_size_bytes']:,} bytes")
    print(f"    Compression:  {stats['compression_ratio']}×")
    print(f"    Agents:       {stats['agents']}")
    print(f"    Active tasks: {stats['tasks']}")
    print()
    print(f"  Session Limits:")
    print(f"    Max messages: {SessionLimiter.MAX_MESSAGES}")
    print(f"    Max tokens:   {SessionLimiter.MAX_TOKENS_PER_SESSION:,}")
    if violations:
        print(f"    ⚠ {len(violations)} violation(s)")
        for v in violations[:3]:
            print(f"      • {v['title'][:40]} — {', '.join(v['issues'])}")
    else:
        print(f"    ✓ All sessions within limits")
    print()
    
    # Estimated savings
    if violations:
        total_over = sum(v["tokens"] for v in violations)
        est_savings = total_over * 0.6  # 60% savings from trimming
        print(f"  Estimated savings from trimming:")
        print(f"    {total_over:,} tokens over limit")
        print(f"    ~{est_savings:,.0f} tokens could be saved")
    print("=" * 60)


def compress_state():
    """Compress current shared state."""
    shared = SharedStateManager()
    
    # Populate from current Forge state
    # Read existing dashboard stats
    stats_file = STATE_DIR / "dashboard_stats.json"
    if stats_file.exists():
        try:
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
            shared.set_shared("last_stats", {
                "sessions": stats.get("total_sessions", 0),
                "messages": stats.get("total_messages", 0),
                "tokens": stats.get("total_tokens", 0),
                "cost": stats.get("total_cost_usd", 0),
            })
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    
    # Read current checkpoint
    checkpoint_file = STATE_DIR / "checkpoint.json"
    if checkpoint_file.exists():
        try:
            cp = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            shared.set_shared("checkpoint", {
                "level": cp.get("current_level", ""),
                "cycle": cp.get("cycle_count", 0),
                "task": cp.get("current_task", "")[:80],
            })
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    
    shared.save()
    stats = shared.get_stats()
    print(f"✓ Shared state compressed: {stats['nmp_size_bytes']} bytes NMP ({stats['compression_ratio']}×)")


def trim_sessions():
    """Report on sessions that need trimming."""
    limiter = SessionLimiter()
    print(limiter.get_session_report())


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RecursiveMAS-inspired Forge optimizer")
    parser.add_argument("--status", action="store_true", help="Show optimizer status")
    parser.add_argument("--compress", action="store_true", help="Compress shared state")
    parser.add_argument("--trim-sessions", action="store_true", help="Check session limits")
    parser.add_argument("--daemon", action="store_true", help="Run as background optimizer")
    parser.add_argument("--interval", type=int, default=30, help="Daemon interval (seconds)")
    args = parser.parse_args()
    
    if args.status:
        show_status()
    elif args.compress:
        compress_state()
    elif args.trim_sessions:
        trim_sessions()
    elif args.daemon:
        print(f"Recursive optimizer daemon running (interval={args.interval}s)")
        while True:
            try:
                compress_state()
                trim_sessions()
            except Exception as e:
                print(f"Error: {e}")
            time.sleep(args.interval)
    else:
        show_status()


if __name__ == "__main__":
    main()
