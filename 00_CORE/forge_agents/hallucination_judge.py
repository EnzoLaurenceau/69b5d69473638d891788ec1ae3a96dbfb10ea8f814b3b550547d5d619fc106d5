#!/usr/bin/env python
"""hallucination_judge.py — semantic grounding judge (MiMo + session escalation).

Why this exists
---------------
hallucination_compare.py catches GROUNDED categories (numeric / negation /
error-masking) at a proven ≥97% in-scope reliability, but it structurally
cannot catch semantic fabrication — a claim inventing a fact with no numeric or
negation signal ("The CEO is Jane Doe"). Recall there is ~20%. Closing that gap
needs a model that understands meaning, i.e. an LLM judge.

Hybrid design (the operating mode: strong=session, bulk=MiMo)
-------------------------------------------------------------
1. MiMo (cheap bulk engine) judges every claim first → verdict + confidence.
2. Low-confidence / unparseable verdicts ESCALATE to the session (the strong
   subscription model) — written to an escalation queue for in-session
   adjudication. The session's verdict overrides MiMo's for those cases.

This keeps MiMo doing the volume and the expensive session touching only the
genuinely ambiguous minority — exactly the forge's cost model. The judge's own
reliability is then measured (hallucination_eval.py), never assumed.

verdict semantics
-----------------
  supported     — claim is stated in or directly entailed by the evidence
  contradicted  — evidence asserts otherwise
  unsupported   — evidence neither states nor entails it (fabrication/invention)
A claim is a HALLUCINATION when verdict ∈ {contradicted, unsupported}.

Usage:
    from forge_agents.hallucination_judge import judge, judge_hybrid
    r = judge(claim, evidence)              # MiMo pass only
    r = judge_hybrid(claim, evidence,       # MiMo + optional session override
                     session_verdict=None)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "05_STATE"


def _escalation_queue() -> Path:
    """File d'escalade cloisonnée par tenant (W5-03c), résolue à l'appel via forge_store.
    Sans tenant en contexte → repli GLOBAL historique (05_STATE/…) assuré par state_path."""
    try:
        from .forge_store import state_path
    except ImportError:
        from forge_agents.forge_store import state_path
    return state_path("hallucination_escalation_queue.json")

_JUDGE_SYSTEM = (
    "You are a strict grounding judge. You are given EVIDENCE (raw tool/context "
    "output) and a CLAIM. Decide the claim's relationship to the evidence:\n"
    "  supported     = stated in, or directly entailed by, the evidence\n"
    "  contradicted  = the evidence asserts otherwise\n"
    "  unsupported   = evidence neither states nor entails it (invented/fabricated)\n"
    "Judge ONLY against the evidence given. Do NOT use outside knowledge. If the "
    "evidence does not contain the fact, it is 'unsupported' even if it sounds "
    "plausible. Output ONLY compact JSON on a single line, no prose:\n"
    '{"verdict":"supported|contradicted|unsupported","confidence":0.0-1.0,'
    '"evidence_quote":"<short verbatim quote from evidence, or empty>"}'
)

_VALID = {"supported", "contradicted", "unsupported"}
HALLUCINATION_VERDICTS = {"contradicted", "unsupported"}


def _build_prompt(claim: str, evidence: str) -> str:
    ev = evidence if len(evidence) <= 4000 else evidence[:4000] + " …[truncated]"
    return f"EVIDENCE:\n{ev}\n\nCLAIM:\n{claim}\n\nJSON:"


def _parse_verdict(text: str) -> Optional[dict]:
    """Extract the JSON verdict from a model reply. Returns None if unparseable
    or structurally invalid — the caller treats None as 'escalate'."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)  # first {...} block (tolerates stray prose)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
    except Exception:
        return None
    verdict = str(obj.get("verdict", "")).strip().lower()
    if verdict not in _VALID:
        return None
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {"verdict": verdict, "confidence": conf,
            "evidence_quote": str(obj.get("evidence_quote", ""))[:200]}


def judge(claim: str, evidence: str, max_tokens: int = 1300) -> dict:
    """One MiMo grounding judgment. Returns a dict with:
      verdict, confidence, is_hallucination (bool), escalate (bool),
      raw (model text), billed_tokens.
    escalate=True when the reply is unparseable (the session must decide)."""
    from forge_agents.forge_mimo import mimo_call
    text, m = mimo_call(_build_prompt(claim, evidence), system=_JUDGE_SYSTEM,
                        max_tokens=max_tokens)
    parsed = _parse_verdict(text)
    if parsed is None:
        return {"verdict": None, "confidence": 0.0, "is_hallucination": None,
                "escalate": True, "raw": (text or "")[:300],
                "billed_tokens": m.get("billed_tokens"), "reason": "unparseable"}
    return {
        "verdict": parsed["verdict"],
        "confidence": parsed["confidence"],
        "is_hallucination": parsed["verdict"] in HALLUCINATION_VERDICTS,
        "escalate": False,
        "evidence_quote": parsed["evidence_quote"],
        "raw": (text or "")[:300],
        "billed_tokens": m.get("billed_tokens"),
    }


def needs_escalation(mimo_result: dict, confidence_gate: float = 0.75) -> bool:
    """ASYMMETRIC gate. MiMo may CLEAR a claim cheaply, but only the strong
    session may CONFIRM a hallucination flag. Escalate when:
      - the reply was unparseable, OR
      - confidence is below the gate, OR
      - MiMo flags a hallucination (verdict ∈ {contradicted, unsupported}).
    Rationale, proven on the live 30-case run: MiMo's errors were CONFIDENT
    false positives (grounded claims called 'unsupported' at conf 0.9-0.95), so a
    confidence gate alone never fired. The consequential, error-prone direction
    is the positive flag — so every flag gets strong-model confirmation. MiMo's
    recall on real hallucinations was 100%, so cheaply trusting its 'supported'
    verdicts is safe; a second cheap judge on negatives is the next hardening."""
    if mimo_result.get("escalate"):
        return True
    if float(mimo_result.get("confidence", 0.0)) < confidence_gate:
        return True
    return bool(mimo_result.get("is_hallucination"))


def judge_hybrid(claim: str, evidence: str, session_verdict: Optional[str] = None,
                 confidence_gate: float = 0.75) -> dict:
    """MiMo first; if it escalates and a session_verdict is supplied, the session
    overrides. Returns the final decision plus which engine decided it.

    session_verdict: 'supported' | 'contradicted' | 'unsupported' | None.
    When escalation is needed but no session_verdict is given, the result carries
    pending_session=True so a caller can queue it for in-session adjudication."""
    m = judge(claim, evidence)
    if not needs_escalation(m, confidence_gate):
        return {**m, "decided_by": "mimo", "pending_session": False}

    if session_verdict is not None:
        v = session_verdict.strip().lower()
        return {
            "verdict": v,
            "confidence": 1.0,
            "is_hallucination": v in HALLUCINATION_VERDICTS,
            "escalate": False,
            "decided_by": "session",
            "pending_session": False,
            "mimo_verdict": m.get("verdict"),
            "mimo_confidence": m.get("confidence"),
            "billed_tokens": m.get("billed_tokens"),
        }
    return {**m, "decided_by": "mimo", "pending_session": True}


def queue_for_session(items: list[dict]) -> Path:
    """Persist escalated (claim, evidence) items awaiting session adjudication."""
    escalation_queue = _escalation_queue()
    escalation_queue.parent.mkdir(parents=True, exist_ok=True)
    escalation_queue.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return escalation_queue


if __name__ == "__main__":
    # tiny live smoke test — proves MiMo returns parseable verdicts
    demos = [
        ("The CEO is Jane Doe.", "Company founded in Berlin, focus on logistics.", "unsupported"),
        ("The company is based in Berlin.", "Company founded in Berlin, focus on logistics.", "supported"),
        ("Scan found 42 vulnerabilities.", "Scan complete. 0 vulnerabilities detected.", "contradicted"),
    ]
    for claim, ev, exp in demos:
        r = judge(claim, ev)
        print(f"exp={exp:<13} got={str(r['verdict']):<13} conf={r['confidence']} "
              f"escalate={r['escalate']} billed={r['billed_tokens']}")
