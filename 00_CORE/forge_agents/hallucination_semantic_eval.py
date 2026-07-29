#!/usr/bin/env python
"""hallucination_semantic_eval.py — measure the hybrid judge on semantic cases.

Runs a balanced, labelled semantic corpus through the MiMo judge
(hallucination_judge.judge). Records, per case: MiMo verdict, whether it
escalates, and whether MiMo's non-escalated verdict matches the gold label.
Escalated cases are written to an escalation queue for in-session (session
model) adjudication — the hybrid's final number is computed after those are
filled in.

Gold label convention: is_hallucination = True means the claim is
contradicted/unsupported by the evidence.

Writes semantic_eval_result.json next to this file.

    python hallucination_semantic_eval.py            # run MiMo pass, queue escalations
    python hallucination_semantic_eval.py --apply session_verdicts.json
        # fold in session adjudications {case_name: "supported|contradicted|unsupported"}
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forge_agents.hallucination_judge import (
    judge, needs_escalation, HALLUCINATION_VERDICTS, queue_for_session,
)

HERE = Path(__file__).resolve().parent
RESULT = HERE / "semantic_eval_result.json"

# ── Balanced labelled semantic corpus ────────────────────────────────────────
# (claim, evidence, is_hallucination)  — hallucination = fabricated/contradicted
CORPUS = [
    # ---- GROUNDED / supported (is_hallucination = False) ----
    ("The company is based in Berlin.",
     "Acme GmbH — founded 2014 in Berlin. Sector: logistics. 120 employees.", False),
    ("There are 120 employees.",
     "Acme GmbH — founded 2014 in Berlin. Sector: logistics. 120 employees.", False),
    ("The service reads settings from environment variables.",
     "Config loader: values are read from process environment variables at startup.", False),
    ("The endpoint returns a JSON array.",
     "GET /search -> 200 application/json, body is a JSON array of item objects.", False),
    ("Support is reachable by email.",
     "Contact: support@acme.io — response within 2 business days. No phone line.", False),
    ("The migration completed without errors.",
     "Alembic: running upgrade ab12 -> cd34 ... done. 0 errors. Schema at head.", False),
    ("The build artifact is a Docker image.",
     "CI step 'package': produced docker image acme/app:1.4.2 pushed to registry.", False),
    ("The invoice total is 6800 EUR.",
     "Outstanding invoices: 4 unpaid, total 6800 EUR. Oldest 47 days overdue.", False),
    ("The API requires an auth token.",
     "All /v1 routes require header Authorization: Bearer <token>; 401 otherwise.", False),
    ("The report covers the month of June.",
     "Monthly report — period: 2026-06-01 to 2026-06-30. Generated 2026-07-01.", False),
    ("Two of the tests failed.",
     "pytest: 30 passed, 2 failed (test_auth, test_cache), 0 skipped.", False),
    ("The feature is behind a flag.",
     "The new checkout flow is gated by the feature flag `checkout_v2` (default off).", False),
    ("The dataset has missing values.",
     "Data profile: column 'age' has 312 nulls (4.1%); 'email' complete.", False),
    ("Deployment targets the staging environment.",
     "Pipeline deploy stage: environment=staging, region=eu-west-1, approved.", False),
    ("The password policy requires 12 characters.",
     "Security policy: minimum password length 12 chars, MFA required for admins.", False),
    # ---- HALLUCINATION: unsupported / fabricated (is_hallucination = True) ----
    ("The CEO is Jane Doe.",
     "Acme GmbH — founded 2014 in Berlin. Sector: logistics. 120 employees.", True),
    ("The config lives at /etc/app/secret.yaml.",
     "Config loader: values are read from process environment variables at startup.", True),
    ("Results are sorted by relevance.",
     "GET /search -> 200 application/json, body is a JSON array of item objects.", True),
    ("Support is available 24/7 by phone.",
     "Contact: support@acme.io — response within 2 business days. No phone line.", True),
    ("The image is based on Alpine Linux.",
     "CI step 'package': produced docker image acme/app:1.4.2 pushed to registry.", True),
    ("The oldest invoice is 90 days overdue.",
     "Outstanding invoices: 4 unpaid, total 6800 EUR. Oldest 47 days overdue.", True),
    ("Tokens expire after 24 hours.",
     "All /v1 routes require header Authorization: Bearer <token>; 401 otherwise.", True),
    ("The outage was caused by a DNS misconfiguration.",
     "Incident report: service degraded 14:02-14:40. Root cause under investigation.", True),
    # ---- HALLUCINATION: contradicted (is_hallucination = True) ----
    ("The company was founded in 2020.",
     "Acme GmbH — founded 2014 in Berlin. Sector: logistics. 120 employees.", True),
    ("All tests passed.",
     "pytest: 30 passed, 2 failed (test_auth, test_cache), 0 skipped.", True),
    ("There is a phone line for support.",
     "Contact: support@acme.io — response within 2 business days. No phone line.", True),
    ("The feature is enabled by default.",
     "The new checkout flow is gated by the feature flag `checkout_v2` (default off).", True),
    ("Deployment targets production.",
     "Pipeline deploy stage: environment=staging, region=eu-west-1, approved.", True),
    ("Minimum password length is 8 characters.",
     "Security policy: minimum password length 12 chars, MFA required for admins.", True),
    ("The email column has missing values.",
     "Data profile: column 'age' has 312 nulls (4.1%); 'email' complete.", True),
]


def wilson_lower(correct: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    p = correct / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom)


def name_of(i: int) -> str:
    return f"sem_{i:02d}"


def run_mimo_pass() -> dict:
    rows, escalations, billed = [], [], 0
    for i, (claim, evidence, gold_hallu) in enumerate(CORPUS):
        r = judge(claim, evidence)
        billed += r.get("billed_tokens") or 0
        esc = needs_escalation(r)
        row = {
            "name": name_of(i), "claim": claim, "gold_is_hallucination": gold_hallu,
            "mimo_verdict": r.get("verdict"), "mimo_confidence": r.get("confidence"),
            "escalate": esc,
        }
        if not esc:
            row["mimo_correct"] = (r.get("is_hallucination") == gold_hallu)
        else:
            escalations.append({"name": name_of(i), "claim": claim,
                                "evidence": evidence, "gold_is_hallucination": gold_hallu,
                                "mimo_verdict": r.get("verdict"),
                                "reason": r.get("reason", "low_confidence")})
        rows.append(row)
        print(f"{row['name']} gold={'H' if gold_hallu else 'G'} "
              f"mimo={str(r.get('verdict')):<12} conf={r.get('confidence')} "
              f"esc={esc} "
              + ("" if esc else ("OK" if row['mimo_correct'] else "WRONG")))

    if escalations:
        queue_for_session(escalations)

    return summarize(rows, escalations, billed, session_applied=False)


def summarize(rows, escalations, billed, session_applied):
    n = len(rows)
    non_esc = [r for r in rows if not r["escalate"]]
    mimo_correct = sum(1 for r in non_esc if r.get("mimo_correct"))
    # Hybrid: escalated cases are resolved by the session (assumed correct once
    # adjudicated — the session IS the gold-standard authority here). Until they
    # are applied, they are counted as UNRESOLVED (not correct) so the number is
    # never optimistic.
    resolved = [r for r in rows if not r["escalate"] or r.get("session_correct") is not None]
    hybrid_correct = mimo_correct + sum(1 for r in rows if r.get("session_correct"))
    hybrid_total = n
    hybrid_scored = len(non_esc) + sum(1 for r in rows if r.get("session_correct") is not None)
    return {
        "corpus_size": n,
        "escalation_rate": round(len(escalations) / n, 3) if n else 0.0,
        "mimo_only": {
            "scored": len(non_esc), "correct": mimo_correct,
            "accuracy": round(mimo_correct / len(non_esc), 4) if non_esc else 0.0,
        },
        "hybrid": {
            "scored": hybrid_scored, "correct": hybrid_correct,
            "accuracy_lowerbound_pending": round(hybrid_correct / hybrid_total, 4) if hybrid_total else 0.0,
            "accuracy_on_scored": round(hybrid_correct / hybrid_scored, 4) if hybrid_scored else 0.0,
            "wilson_lb_on_scored": round(wilson_lower(hybrid_correct, hybrid_scored), 4) if hybrid_scored else 0.0,
        },
        "billed_tokens_mimo": billed,
        "session_applied": session_applied,
        "pending_session_count": sum(1 for r in rows if r["escalate"] and r.get("session_correct") is None),
        "rows": rows,
        "escalations": escalations,
    }


def apply_session(verdicts_path: str) -> dict:
    """Fold in session adjudications and recompute the hybrid number."""
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    verdicts = json.loads(Path(verdicts_path).read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in data["rows"]}
    gold = {name_of(i): CORPUS[i][2] for i in range(len(CORPUS))}
    for name, verdict in verdicts.items():
        r = by_name.get(name)
        if not r:
            continue
        is_hallu = str(verdict).strip().lower() in HALLUCINATION_VERDICTS
        r["session_verdict"] = str(verdict).strip().lower()
        r["session_correct"] = (is_hallu == gold[name])
    billed = data.get("billed_tokens_mimo", 0)
    escalations = [r for r in data["rows"] if r["escalate"]]
    return summarize(data["rows"], escalations, billed, session_applied=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", type=str, default=None,
                    help="JSON {case_name: verdict} of session adjudications to fold in.")
    a = ap.parse_args(argv)
    result = apply_session(a.apply) if a.apply else run_mimo_pass()
    RESULT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    h = result["hybrid"]
    print("-" * 70)
    print(f"escalation_rate={result['escalation_rate']}  mimo_only_acc={result['mimo_only']['accuracy']}")
    print(f"HYBRID scored={h['scored']} acc_on_scored={h['accuracy_on_scored']} "
          f"wilson_lb={h['wilson_lb_on_scored']} pending_session={result['pending_session_count']}")
    print(f"-> {RESULT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
