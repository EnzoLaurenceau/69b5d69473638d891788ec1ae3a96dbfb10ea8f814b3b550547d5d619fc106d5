"""hallucination_compare.py — GENUINE comparative hallucination detection.

Background bug this fixes
--------------------------
05_STATE/hallucination_events.json does not exist yet, and
scripts/hermes_session_tracker.py's update_sprint_data() hardcodes
"hallucination_detected": False unconditionally for every sprint record —
so the dashboard currently shows 0% hallucination meaning "never checked",
not "verified absent". This module actually checks: it compares a claim
(natural-language text asserting something) against the real, raw tool
result it should be grounded in, and only reports a finding when it finds
a concrete, quotable mismatch. No vague/unfounded scoring — every finding
quotes both the claim fragment and the tool evidence.

Input record shape (consumed from scripts/tool_call_ledger.py's ledger —
built in parallel against this exact documented shape; we code against the
shape, not the module, per instructions):
    {
        "source": str,            # e.g. "claude_code_cli", "self_test"
        "session_id": str,
        "tool_name": str,
        "tool_result_raw": str,   # the real, raw tool output
        "truncated": bool,        # True if tool_result_raw was cut short
        "claim_text": str | None, # NL claim that should be grounded in it
        "model": str,
        "timestamp": float,
        "is_error": bool | None,  # only meaningful for claude_code_cli
    }

Note: check_numeric_grounding()'s signature (claim_text, tool_result_raw)
intentionally has no access to `truncated` — a low-severity numeric finding
on a record with truncated=True should be read with that caveat in mind by
the consumer (dashboard), since the missing number could be in the part
that got cut off. This module does not invent extra suppression logic that
isn't in the specified signatures.

Finding schema (matches 09_WEB/server.py's dashboard contract exactly —
see _load_hallucinations/_save_hallucinations/api_hallucination_report,
lines ~739-821). We deliberately do NOT set id/timestamp/timestamp_iso/
resolved — server.py's save layer (api_hallucination_report) owns those;
--scan replicates that same read-merge-cap500-write contract locally.

Usage:
    from forge_agents.hallucination_compare import compare, scan_ledger
    findings = compare(record)          # list[dict], possibly empty
    findings = scan_ledger()            # scans the whole ledger JSONL

CLI:
    python hallucination_compare.py --self-test   # synthetic proof harness
    python hallucination_compare.py --scan        # scan ledger, write events
    python hallucination_compare.py --scan --ledger path/to/ledger.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import logging
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger(__name__)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception as exc:
    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

# ── Paths (match 09_WEB/server.py's FORGE_ROOT convention exactly) ──────────
FORGE_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = FORGE_ROOT / "05_STATE"
HALLUCINATION_FILE = state_path("hallucination_events.json")
DEFAULT_LEDGER_FILE = state_path("tool_call_ledger.jsonl")
# Plafond du ledger d'événements. Porté à 50 000 pour conserver l'historique complet d'apprentissage.
MAX_EVENTS = 50000
MAX_ACTUAL_CHARS = 300


# ── Finding schema (single source of truth for the dashboard envelope) ─────
@dataclass
class HallucinationFinding:
    """Mirrors the exact dict shape api_hallucination_report expects, minus
    the fields the save layer assigns (id/timestamp/timestamp_iso/resolved)."""
    agent: str
    node: str
    severity: str  # "low" | "medium" | "high"
    description: str
    expected: str
    actual: str
    root_cause: str
    context: dict[str, Any]

    def to_dict(self) -> dict:
        return asdict(self)


def _truncate(text: Optional[str], limit: int = MAX_ACTUAL_CHARS) -> str:
    """Truncate tool_result_raw for the 'actual' field — never dump the
    full raw output into a finding, but never invent content either."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated, {len(text)} chars total]"


# ── Check 1 — numeric grounding ─────────────────────────────────────────────
# Standalone = 2+ consecutive digits, delimited by non-digit/non-word chars
# on both sides (so "256" inside "sha256" is NOT extracted, but "2024" in
# "CVE-2024-1234" is, since hyphens are non-word boundaries). 2+ digits
# avoids noise from trivial "1"/"2" counts.
_NUMBER_RE = re.compile(r"\b\d{2,}\b")


def check_numeric_grounding(claim_text: Optional[str], tool_result_raw: str) -> list[dict]:
    """Extract standalone numbers from claim_text; flag any not present
    verbatim (exact substring) in tool_result_raw. One finding per distinct
    number value (a repeated but already-flagged number isn't re-flagged)."""
    findings: list[dict] = []
    if not claim_text:
        return findings
    tool_result_raw = tool_result_raw or ""

    # Boundary-aware grounding: a number counts as grounded only if it appears
    # as a STANDALONE token in the tool output, not welded inside a longer run
    # of digits. Plain substring ("45" in "4590") spuriously grounds and hides
    # real mismatches — proven by hallucination_eval.py's edge_no_substr case.
    tool_numbers = set(_NUMBER_RE.findall(tool_result_raw))

    seen: set[str] = set()
    for m in _NUMBER_RE.finditer(claim_text):
        number = m.group()
        if number in seen:
            continue
        seen.add(number)
        if number in tool_numbers:
            continue  # grounded — present as a standalone number in the tool output

        start, end = m.start(), m.end()
        ctx_start = max(0, start - 40)
        ctx_end = min(len(claim_text), end + 40)
        context = claim_text[ctx_start:ctx_end].strip()

        findings.append({
            "number": number,
            "claim_context": context,
            "description": (
                f'Claim cites the number "{number}" ("...{context}...") '
                f"which does not appear verbatim in the tool result it should be grounded in."
            ),
            "expected": f'"{number}" present verbatim in tool_result_raw',
            "actual": _truncate(tool_result_raw),
        })
    return findings


# ── Check 2 — negation / absence claim ──────────────────────────────────────
_NEGATION_PATTERNS = [
    re.compile(r"\bno\s+\S+(?:\s+\S+){0,4}\s+found\b", re.IGNORECASE),
    re.compile(r"\b0\s+\w+", re.IGNORECASE),
    re.compile(r"\baucune?\s+\w+", re.IGNORECASE),
    re.compile(r"\bzero\s+\w+", re.IGNORECASE),
]
_EMPTY_INDICATOR_SUBSTRINGS = ("not found", "no results")


def _tool_result_indicates_emptiness(tool_result_raw: str) -> bool:
    stripped = (tool_result_raw or "").strip()
    if stripped in ("", "[]", "{}"):
        return True
    lowered = stripped.lower()
    return any(ind in lowered for ind in _EMPTY_INDICATOR_SUBSTRINGS)


def check_negation_claim(claim_text: Optional[str], tool_result_raw: str) -> list[dict]:
    """If claim_text asserts absence/zero AND tool_result_raw is non-empty
    and doesn't itself indicate emptiness, flag a potential unfounded-
    absence claim, quoting both the claim phrase and the tool evidence."""
    findings: list[dict] = []
    if not claim_text:
        return findings
    tool_result_raw = tool_result_raw or ""
    if _tool_result_indicates_emptiness(tool_result_raw):
        return findings  # tool output itself says empty/no results — grounded

    match = None
    for pat in _NEGATION_PATTERNS:
        m = pat.search(claim_text)
        if m:
            match = m
            break
    if not match:
        return findings

    phrase = match.group().strip()
    findings.append({
        "matched_phrase": phrase,
        "description": (
            f'Claim asserts absence ("{phrase}") but tool_result_raw is non-empty '
            f"and does not itself indicate emptiness."
        ),
        "expected": f'tool_result_raw empty, "[]", "{{}}", or indicating no results (to support "{phrase}")',
        "actual": _truncate(tool_result_raw),
    })
    return findings


# ── Check 3 — error masking ──────────────────────────────────────────────────
_SUCCESS_TOKENS = ("success", "done", "completed", "fixed", "réussi", "termin")
_FAILURE_TOKENS = ("error", "fail", "exception", "crash", "erreur", "échec", "echec")


def check_error_masking(claim_text: Optional[str], tool_result_raw: str, is_error: Optional[bool]) -> list[dict]:
    """If is_error is True but claim_text uses success language without
    also mentioning error/failure, flag a claim-vs-ground-truth
    contradiction. Only meaningful for claude_code_cli records — records
    where is_error is not literally True are left alone."""
    findings: list[dict] = []
    if is_error is not True or not claim_text:
        return findings
    tool_result_raw = tool_result_raw or ""

    lowered = claim_text.lower()
    success_hit = next((tok for tok in _SUCCESS_TOKENS if tok in lowered), None)
    if not success_hit:
        return findings
    if any(tok in lowered for tok in _FAILURE_TOKENS):
        return findings  # claim already acknowledges error/failure — not masking

    findings.append({
        "matched_phrase": success_hit,
        "description": (
            f'Tool call recorded is_error=True but claim uses success language '
            f'("{success_hit}") without mentioning error/failure.'
        ),
        "expected": "claim should mention error/failure since is_error=True",
        "actual": _truncate(tool_result_raw),
    })
    return findings


# ── Combined comparison ─────────────────────────────────────────────────────
def compare(record: dict) -> list[dict]:
    """Run all three checks against one ledger record, mapped into the
    exact dashboard finding schema. Returns [] when nothing is grounded
    to flag — this function never manufactures a finding without a
    concrete quoted mismatch."""
    claim_text = record.get("claim_text")
    tool_result_raw = record.get("tool_result_raw") or ""
    is_error = record.get("is_error")
    agent = record.get("source", "unknown")
    node = record.get("tool_name", "")
    context = {
        "session_id": record.get("session_id"),
        "timestamp": record.get("timestamp"),
    }

    findings: list[HallucinationFinding] = []

    for raw in check_numeric_grounding(claim_text, tool_result_raw):
        findings.append(HallucinationFinding(
            agent=agent, node=node, severity="low",
            description=raw["description"], expected=raw["expected"], actual=raw["actual"],
            root_cause="check_numeric_grounding", context=context,
        ))

    for raw in check_negation_claim(claim_text, tool_result_raw):
        findings.append(HallucinationFinding(
            agent=agent, node=node, severity="medium",
            description=raw["description"], expected=raw["expected"], actual=raw["actual"],
            root_cause="check_negation_claim", context=context,
        ))

    for raw in check_error_masking(claim_text, tool_result_raw, is_error):
        findings.append(HallucinationFinding(
            agent=agent, node=node, severity="high",
            description=raw["description"], expected=raw["expected"], actual=raw["actual"],
            root_cause="check_error_masking", context=context,
        ))

    return [f.to_dict() for f in findings]


# ── Ledger scan ──────────────────────────────────────────────────────────────
def scan_ledger(ledger_path: "str | Path | None" = None, session_id: Optional[str] = None) -> list[dict]:
    """Read the tool_call_ledger JSONL and run compare() over every record.
    Malformed lines are skipped (never crash a scan over a large ledger);
    a missing ledger file returns an empty list rather than raising.

    session_id: if given, only records whose 'session_id' field matches
    exactly are compared — lets a caller scope a scan to one session
    (e.g. to report a real hallucination_findings_count per session)
    without a separate ledger file or duplicated scan logic."""
    path = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_FILE
    if not path.exists():
        return []

    findings: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if session_id is not None and record.get("session_id") != session_id:
                continue
            findings.extend(compare(record))
    return findings


def ledger_covered_session_ids(ledger_path: "str | Path | None" = None) -> set:
    """Return the set of session_id values present in the ledger. Callers
    (e.g. 09_WEB/server.py) use this to distinguish "0 real findings because
    we checked and found none" from "0 findings because this session_id has
    no ledger coverage at all" — the latter must never be reported as a
    verified-clean hallucination_detected=False."""
    path = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_FILE
    if not path.exists():
        return set()
    covered: set = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = record.get("session_id") if isinstance(record, dict) else None
            if sid:
                covered.add(sid)
    return covered


# ── Save layer — faithful replica of server.py's read-merge-cap500-write ───
# (09_WEB/server.py: _load_hallucinations / _save_hallucinations /
#  api_hallucination_report, lines ~739-821). Not imported directly because
# server.py pulls in fastapi/uvicorn/starlette at module scope — this module
# stays stdlib-only and importable without the web stack installed.
def _load_hallucinations() -> list:
    if HALLUCINATION_FILE.exists():
        try:
            return json.loads(HALLUCINATION_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return []


def _save_hallucinations(events: list) -> None:
    HALLUCINATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    HALLUCINATION_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")


def next_event_id(events: list) -> int:
    """Id monotone. `len(events)+1` était faux : combiné au plafond
    (les plus anciens sont éliminés), il réattribue des ids déjà utilisés —
    391 ids uniques pour 500 événements mesurés le 2026-07-22. `/resolve`
    marquait alors le mauvais événement."""
    max_id = 0
    for e in events:
        try:
            max_id = max(max_id, int(e.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return max_id + 1


def save_findings(findings: list[dict]) -> list[dict]:
    """Append findings to 05_STATE/hallucination_events.json.

    Deux corrections par rapport à la version d'origine :
      - `id` monotone (cf. next_event_id) au lieu de `len(events)+1` ;
      - `timestamp` = instant RÉEL de l'appel d'outil fautif (issu du ledger),
        pas l'instant du scan. Sinon un re-scan fait apparaître d'anciennes
        hallucinations comme « il y a 5 secondes » et `last_24h` ment.
        L'instant du scan reste tracé, séparément, dans `detected_at`.
    """
    events = _load_hallucinations()
    saved = []
    next_id = next_event_id(events)
    for finding in findings:
        ctx = finding.get("context") or {}
        occurred = ctx.get("timestamp")
        if not isinstance(occurred, (int, float)) or occurred <= 0:
            occurred = datetime.now().timestamp()
        event = {
            "id": next_id,
            "timestamp": occurred,
            "timestamp_iso": datetime.fromtimestamp(occurred).isoformat(),
            "detected_at": datetime.now().timestamp(),
            "agent": finding.get("agent", "unknown"),
            "node": finding.get("node", ""),
            "severity": finding.get("severity", "medium"),
            "description": finding.get("description", ""),
            "expected": finding.get("expected", ""),
            "actual": finding.get("actual", ""),
            "root_cause": finding.get("root_cause", ""),
            "context": finding.get("context", {}),
            "resolved": False,
        }
        next_id += 1
        events.append(event)
        saved.append(event)
    if len(events) > MAX_EVENTS:
        events = events[-MAX_EVENTS:]
    _save_hallucinations(events)
    return saved


# ── Self-test — genuine comparative proof harness ───────────────────────────
def _case(name: str, claim_text: str, tool_result_raw: str, is_error: Optional[bool], expected_to_flag: bool) -> dict:
    return {
        "name": name,
        "claim_text": claim_text,
        "tool_result_raw": tool_result_raw,
        "is_error": is_error,
        "expected_to_flag": expected_to_flag,
    }


_SELF_TEST_CASES: list[dict] = [
    # ── Genuine hallucinations these checks SHOULD catch ────────────────────
    _case(
        "numeric_mismatch_simple",
        "Found 42 vulnerabilities in the scan.",
        "Scan complete. 0 vulnerabilities detected across 12 files.",
        False, True,
    ),
    _case(
        "negation_vs_stacktrace",
        "No errors found in the test run.",
        "Traceback (most recent call last):\n"
        '  File "app.py", line 42, in <module>\n'
        "    raise ValueError('boom')\n"
        "ValueError: boom",
        False, True,
    ),
    _case(
        "error_masking_direct",
        "Successfully fixed the bug and all tests pass now.",
        'Traceback (most recent call last):\n  File "test.py", line 10\n    SyntaxError: invalid syntax',
        True, True,
    ),
    _case(
        "numeric_partial_mismatch",
        "The build ran 128 tests and 100 passed.",
        "Test run: 128 tests executed, 97 passed, 31 failed.",
        False, True,
    ),
    _case(
        "french_negation_vs_nonempty",
        "Aucune erreur détectée pendant l'exécution.",
        "ERROR: connection refused at 10.0.0.5:5432 after 3 retries.",
        False, True,
    ),
    # ── TRUE grounded claims these checks should NOT flag ───────────────────
    _case(
        "numeric_grounded_correct",
        "The scan found 15 warnings across the codebase.",
        "Lint report: 15 warnings, 0 errors. Files scanned: 42.",
        False, False,
    ),
    _case(
        "success_language_requires_is_error_true",
        "Successfully installed the dependencies listed in requirements.txt.",
        "Successfully installed Flask-3.0.0 Werkzeug-3.0.1 Jinja2-3.1.3",
        False, False,
    ),
    _case(
        "negation_grounded_empty_result",
        "No vulnerabilities found in the dependency scan.",
        "[]",
        False, False,
    ),
]


def run_comparative_tests() -> dict:
    """Hand-written synthetic (claim_text, tool_result_raw, is_error,
    expected_to_flag) cases run through the REAL compare() entry point —
    the same function scan_ledger() uses on real records. Prints pass/fail
    per case and the overall pass rate; never mocks internals."""
    print("=" * 78)
    print("hallucination_compare — comparative self-test (genuine, no mocking)")
    print("=" * 78)

    results = []
    passed = 0
    for i, case in enumerate(_SELF_TEST_CASES, start=1):
        record = {
            "source": "self_test",
            "session_id": f"self_test_case_{i}",
            "tool_name": "synthetic_tool",
            "tool_result_raw": case["tool_result_raw"],
            "truncated": False,
            "claim_text": case["claim_text"],
            "model": "self-test",
            "timestamp": 0.0,
            "is_error": case["is_error"],
        }
        findings = compare(record)
        actual_flag = len(findings) > 0
        ok = actual_flag == case["expected_to_flag"]
        passed += int(ok)
        status = "PASS" if ok else "FAIL"

        print(f"[{status}] case {i}/{len(_SELF_TEST_CASES)}: {case['name']}")
        print(f"       claim   : {case['claim_text']!r}")
        print(f"       expected_to_flag={case['expected_to_flag']}  actual_flag={actual_flag}  findings={len(findings)}")
        for f in findings:
            print(f"         -> [{f['severity']}] {f['root_cause']}: {f['description']}")

        results.append({
            "name": case["name"],
            "expected_to_flag": case["expected_to_flag"],
            "actual_flag": actual_flag,
            "passed": ok,
            "findings": findings,
        })

    total = len(_SELF_TEST_CASES)
    failed = total - passed
    pass_rate = (passed / total * 100.0) if total else 0.0

    print("-" * 78)
    print(f"RESULT: {passed}/{total} passed ({pass_rate:.1f}%)")
    print("=" * 78)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "cases": results,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comparative hallucination detection — flags only concrete, quotable "
                    "mismatches between a claim and the real tool result it should be grounded in."
    )
    parser.add_argument("--self-test", action="store_true",
                         help="Run the synthetic comparative proof harness and print pass/fail per case.")
    parser.add_argument("--scan", action="store_true",
                         help="Scan the tool_call_ledger JSONL and write findings to 05_STATE/hallucination_events.json.")
    parser.add_argument("--ledger", type=str, default=None,
                         help=f"Override ledger JSONL path (default: {DEFAULT_LEDGER_FILE}).")
    args = parser.parse_args(argv)

    if not args.self_test and not args.scan:
        parser.print_help()
        return 1

    exit_code = 0

    if args.self_test:
        result = run_comparative_tests()
        if result["failed"] > 0:
            exit_code = 1

    if args.scan:
        ledger_path = Path(args.ledger) if args.ledger else DEFAULT_LEDGER_FILE
        findings = scan_ledger(args.ledger)
        saved = save_findings(findings) if findings else []
        print(f"scan_ledger: {len(findings)} finding(s) from {ledger_path}")
        print(f"saved {len(saved)} event(s) to {HALLUCINATION_FILE}")
        if not ledger_path.exists():
            print(f"(ledger file does not exist yet at {ledger_path} — nothing to scan)")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
