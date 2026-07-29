"""
tool_call_ledger.py — Real per-tool-call ledger for the anti-hallucination system.

Ingests ONLY real, already-recorded tool-call events from two verified sources.
This module never invents, scores, or infers anything — every field in a
ledger record is read directly off source data. A field with no equivalent in
a source is left `None`, never defaulted to a value that would assert
something untrue (e.g. `is_error` is never coerced to `False` for a source
that doesn't track success/failure at all — that would be a false claim of
success).

SOURCE 1 — Hermes DB (sqlite): Path.home()/"AppData"/"Local"/"hermes"/"state.db"
  Verified schema (checked live against the real DB before writing this module):
    sessions(id, source, user_id, model, model_config, system_prompt,
      parent_session_id, started_at, ended_at, end_reason, message_count,
      tool_call_count, input_tokens, output_tokens, cache_read_tokens,
      cache_write_tokens, reasoning_tokens, billing_provider, billing_base_url,
      billing_mode, estimated_cost_usd, actual_cost_usd, cost_status,
      cost_source, pricing_version, title, api_call_count, cwd, handoff_state,
      handoff_platform, handoff_error, rewind_count, archived)
    messages(id, session_id, role, content, tool_call_id, tool_calls,
      tool_name, timestamp, token_count, finish_reason, reasoning,
      reasoning_content, reasoning_details, codex_reasoning_items,
      codex_message_items, platform_message_id, observed, active)
  role='tool' rows hold the raw tool output as a JSON-encoded string in
  `content` (shape varies per tool — we do not parse it, just carry the raw
  string through). `timestamp` is already a unix float (REAL column) — no
  conversion needed. The claim about a tool result, if any, is the next
  role='assistant' row with non-empty `content` within a bounded lookahead
  (HERMES_LOOKAHEAD_ROWS rows) in the SAME session_id; if no such row exists
  in the window, claim_text is left None rather than guessed.

SOURCE 2 — Claude Code CLI transcripts (JSONL):
  Path.home()/".claude"/"projects"/*/*.jsonl (one folder per project, one
  file per session; verified real shapes checked against live transcripts
  before writing this module).
    type=="assistant" records: message.content is a list of blocks;
      tool_use blocks carry {"type":"tool_use","id","name","input","caller"}.
      message.model / message.usage live on the same record.
    type=="user" records: message.content may hold tool_result blocks
      {"type":"tool_result","tool_use_id","is_error","content"} — content is
      either a string or a list of sub-blocks (both real shapes observed).
    Top-level "timestamp" is an ISO-8601 string (e.g.
      "2026-06-19T23:11:57.021Z"), NOT a unix float — converted here, never
      guessed; unparsable/missing -> None.
  A tool_result is matched to its tool_use by tool_use_id, within the same
  file. The claim is the next assistant record carrying a non-empty text
  block within a bounded lookahead (CLAUDE_CODE_LOOKAHEAD_LINES records),
  same file; none found -> claim_text is None.

Both ingesters emit records with EXACTLY these fields, nothing invented:
  source ("hermes_mimo" | "claude_code_cli"), session_id, tool_name,
  tool_result_raw (string, truncated to RAW_TRUNCATE_LEN chars), truncated
  (bool), claim_text (string or None), model, timestamp (unix float or None),
  is_error (bool or None).

Ordering / limit semantics (an ingestion policy choice, not a data claim):
sessions/files are walked most-recent-first — Hermes by sessions.started_at
DESC, Claude Code by file mtime DESC — chronologically within each session or
file. Ingestion stops as soon as `limit` records have been collected, so the
result is "the `limit` most recent tool-call events" grouped by
session/file recency.

Persistence: build_ledger() overwrites 05_STATE/tool_call_ledger.jsonl fresh
on every run — it is a derived cache, not a source of truth.

Stdlib only: sqlite3, json, pathlib, glob, re.
"""

from __future__ import annotations

import glob
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

FORGE_ROOT = Path(__file__).parent.parent.parent
HERMES_DB_PATH = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
CLAUDE_PROJECTS_GLOB = str(Path.home() / ".claude" / "projects" / "*" / "*.jsonl")


def DEFAULT_OUT_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("tool_call_ledger.jsonl")


RAW_TRUNCATE_LEN = 4000
HERMES_LOOKAHEAD_ROWS = 5          # per verified spec: "e.g. 5 rows"
CLAUDE_CODE_LOOKAHEAD_LINES = 50   # empirically measured max real gap = 15 lines; generous bound


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _truncate(raw: str) -> tuple[str, bool]:
    """Truncate to RAW_TRUNCATE_LEN chars. Returns (text, truncated_flag)."""
    if not raw:
        return "", False
    if len(raw) <= RAW_TRUNCATE_LEN:
        return raw, False
    return raw[:RAW_TRUNCATE_LEN], True


def _stringify_tool_result_content(content: Any) -> str:
    """Claude Code tool_result.content is either a string or a list of blocks
    (both real shapes observed). A list is serialized verbatim as JSON so the
    raw field stays a faithful copy of the real record — never reworded."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _parse_iso_timestamp(ts: Optional[str]) -> Optional[float]:
    """Claude Code top-level timestamps are ISO-8601 strings like
    '2026-06-19T23:11:57.021Z'. Converts to unix float; returns None if
    missing/unparseable rather than guessing a time that was never recorded."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ─── SOURCE 1 — Hermes (sqlite) ───────────────────────────────────────────────

def ingest_hermes(limit: int = 500) -> list[dict]:
    """Read real tool-call rows from the Hermes state.db.

    For each role='tool' message, the claim is the next role='assistant'
    message with non-empty content within HERMES_LOOKAHEAD_ROWS rows of the
    SAME session_id. is_error has no equivalent column in this schema and is
    ALWAYS None here — never defaulted to False.
    """
    if not HERMES_DB_PATH.exists():
        return []

    uri = HERMES_DB_PATH.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()

        cur.execute("SELECT id, model FROM sessions ORDER BY started_at DESC")
        session_model: dict[str, Optional[str]] = {}
        session_order: list[str] = []
        for row in cur.fetchall():
            session_model[row["id"]] = row["model"]
            session_order.append(row["id"])

        cur.execute(
            "SELECT id, session_id, role, tool_name, content, timestamp "
            "FROM messages ORDER BY session_id, id ASC"
        )
        rows_by_session: dict[str, list[sqlite3.Row]] = {}
        for row in cur.fetchall():
            rows_by_session.setdefault(row["session_id"], []).append(row)

        # Sessions present in `sessions`, most-recent-first, then any orphaned
        # session_ids found only in `messages` (data inconsistency safeguard —
        # keeps real rows from being silently dropped; recency unknown for
        # these so they're processed last).
        ordered_session_ids = list(session_order)
        for sid in rows_by_session:
            if sid not in session_model:
                ordered_session_ids.append(sid)

        out: list[dict] = []
        for session_id in ordered_session_ids:
            rows = rows_by_session.get(session_id, [])
            for idx, row in enumerate(rows):
                if len(out) >= limit:
                    return out
                if row["role"] != "tool":
                    continue

                claim_text: Optional[str] = None
                window = rows[idx + 1: idx + 1 + HERMES_LOOKAHEAD_ROWS]
                for lookahead_row in window:
                    if lookahead_row["role"] == "assistant" and lookahead_row["content"]:
                        claim_text = lookahead_row["content"]
                        break

                raw_text, truncated = _truncate(row["content"] or "")
                out.append({
                    "source": "hermes_mimo",
                    "session_id": row["session_id"],
                    "tool_name": row["tool_name"],
                    "tool_result_raw": raw_text,
                    "truncated": truncated,
                    "claim_text": claim_text,
                    "model": session_model.get(session_id),
                    "timestamp": row["timestamp"],
                    "is_error": None,  # no equivalent field in this schema
                })
        return out
    finally:
        con.close()


# ─── SOURCE 2 — Claude Code CLI (JSONL transcripts) ───────────────────────────

def _tool_use_blocks(record: dict) -> list[dict]:
    if record.get("type") != "assistant":
        return []
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def _tool_result_blocks(record: dict) -> list[dict]:
    if record.get("type") != "user":
        return []
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def _assistant_claim_text(record: dict) -> Optional[str]:
    """Non-empty concatenated text of an assistant record's text blocks, or None."""
    if record.get("type") != "assistant":
        return None
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    texts = [
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
    ]
    return "\n".join(texts) if texts else None


def ingest_claude_code(limit: int = 500) -> list[dict]:
    """Read real tool-call events from Claude Code CLI JSONL transcripts.

    An assistant record's tool_use blocks are resolved by a later user
    record's tool_result block with matching tool_use_id (both within the
    same file). The claim is the next assistant record with a non-empty text
    block within CLAUDE_CODE_LOOKAHEAD_LINES records, same file.
    """
    files = sorted(
        (Path(p) for p in glob.glob(CLAUDE_PROJECTS_GLOB)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    out: list[dict] = []
    for path in files:
        if len(out) >= limit:
            break

        records: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # skip unparsable line — never fabricate a record for it

        # tool_use_id -> {name, model}, indexed from assistant records only.
        tool_use_index: dict[str, dict] = {}
        for record in records:
            for block in _tool_use_blocks(record):
                tool_use_id = block.get("id")
                if not tool_use_id:
                    continue
                tool_use_index[tool_use_id] = {
                    "name": block.get("name"),
                    "model": (record.get("message") or {}).get("model"),
                }

        for idx, record in enumerate(records):
            if len(out) >= limit:
                break
            for block in _tool_result_blocks(record):
                if len(out) >= limit:
                    break
                tool_use_id = block.get("tool_use_id")
                tool_use_info = tool_use_index.get(tool_use_id)
                if tool_use_info is None:
                    continue  # unresolved tool_use in this file — don't fabricate tool_name

                claim_text: Optional[str] = None
                window = records[idx + 1: idx + 1 + CLAUDE_CODE_LOOKAHEAD_LINES]
                for lookahead_record in window:
                    text = _assistant_claim_text(lookahead_record)
                    if text:
                        claim_text = text
                        break

                raw = _stringify_tool_result_content(block.get("content"))
                raw_text, truncated = _truncate(raw)

                is_error = block.get("is_error")
                if not isinstance(is_error, bool):
                    is_error = None

                out.append({
                    "source": "claude_code_cli",
                    "session_id": record.get("sessionId"),
                    "tool_name": tool_use_info["name"],
                    "tool_result_raw": raw_text,
                    "truncated": truncated,
                    "claim_text": claim_text,
                    "model": tool_use_info["model"],
                    "timestamp": _parse_iso_timestamp(record.get("timestamp")),
                    "is_error": is_error,
                })

    return out


# ─── Ledger assembly + persistence ────────────────────────────────────────────

def build_ledger(out_path=None) -> dict:
    """Ingest both sources and persist as JSONL to 05_STATE/tool_call_ledger.jsonl
    (or out_path), OVERWRITING it fresh every run — this is a derived cache,
    not a source of truth.

    Returns {hermes_count, claude_code_count, total, out_path}.
    """
    resolved_out_path = Path(out_path) if out_path else DEFAULT_OUT_PATH()
    resolved_out_path.parent.mkdir(parents=True, exist_ok=True)

    hermes_records = ingest_hermes()
    claude_code_records = ingest_claude_code()
    all_records = hermes_records + claude_code_records

    with resolved_out_path.open("w", encoding="utf-8") as f:
        for record in all_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "hermes_count": len(hermes_records),
        "claude_code_count": len(claude_code_records),
        "total": len(all_records),
        "out_path": str(resolved_out_path),
    }


if __name__ == "__main__":
    print(json.dumps(build_ledger(), indent=2))
