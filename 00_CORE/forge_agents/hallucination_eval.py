#!/usr/bin/env python
"""hallucination_eval.py — RUTHLESS reliability harness for the detector.

Purpose
-------
`hallucination_compare.compare()` is the real detector (claim vs. the raw tool
evidence it should be grounded in). Its own self-test has 8 cases — far too few
to claim any reliability number. This harness measures the detector against a
large, adversarial, labelled corpus and reports HONEST metrics with a
statistical lower bound, not a point estimate.

The reliability standard (the "97%" gate)
-----------------------------------------
We do NOT report the raw accuracy. We report the **Wilson 95% lower bound** on
accuracy. A detector is declared RELIABLE only if that lower bound >= 0.97 —
i.e. even in the pessimistic tail of the confidence interval it still clears
97%. This is deliberately merciless: a lucky point estimate of 98% on a small
sample can have a lower bound well under 97% and is correctly rejected.

Honesty split (this is the whole point)
---------------------------------------
The detector checks THREE grounded categories only:
  numeric grounding, negation/absence, error-masking.
The corpus is split into:
  IN-SCOPE     — cases inside those three categories. The reliability gate is
                 evaluated on THIS set. This is what the detector actually claims.
  OUT-OF-SCOPE — semantic hallucinations (fabricated entities, invented paths,
                 wrong causal claims) that these string-checks structurally
                 cannot catch. Reported separately so the recall gap is visible
                 and never hidden behind an in-scope 97%.

Reporting both prevents the classic lie: quoting a high number by silently
narrowing the test set to only what the tool already handles.

Usage:
    python hallucination_eval.py            # full report
    python hallucination_eval.py --json     # machine-readable, writes eval_report.json
    python hallucination_eval.py --gate 0.97  # override the reliability threshold

Deterministic: fixed RNG seed, so the number is reproducible run-to-run.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception as exc:
    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forge_agents.hallucination_compare import compare  # the REAL detector
import logging

logger = logging.getLogger(__name__)

SEED = 20260721
HERE = Path(__file__).resolve().parent


# ── Corpus record ────────────────────────────────────────────────────────────
@dataclass
class Case:
    name: str
    claim_text: Optional[str]
    tool_result_raw: str
    is_error: Optional[bool]
    expected_flag: bool          # ground-truth label: should compare() flag it?
    scope: str                   # "in" (3 checks) | "out" (semantic, uncatchable)
    category: str

    def to_record(self, i: int) -> dict:
        return {
            "source": "eval_harness",
            "session_id": f"eval_{i}",
            "tool_name": "synthetic",
            "tool_result_raw": self.tool_result_raw,
            "truncated": False,
            "claim_text": self.claim_text,
            "model": "eval",
            "timestamp": 0.0,
            "is_error": self.is_error,
        }


# ── Generators (deterministic, label-correct by construction) ────────────────
def _distinct_number(rng: random.Random, avoid: str, lo=10, hi=99999) -> int:
    """Return an int whose decimal form is NOT a substring of `avoid`."""
    for _ in range(200):
        n = rng.randint(lo, hi)
        if str(n) not in avoid:
            return n
    # fallback: a very large number is astronomically unlikely to collide
    return rng.randint(10**7, 10**8)


def gen_numeric_grounded(rng: random.Random, k: int) -> list[Case]:
    """Claim cites a number that IS present verbatim in the tool output. No flag."""
    out = []
    for i in range(k):
        n = rng.randint(10, 9999)
        extra = _distinct_number(rng, str(n))
        tool = f"Lint report: {n} warnings, 0 errors. Files scanned: {extra}."
        claim = f"The scan found {n} warnings across the codebase."
        out.append(Case(f"num_grounded_{i}", claim, tool, False, False, "in", "numeric"))
    return out


def gen_numeric_mismatch(rng: random.Random, k: int) -> list[Case]:
    """Claim cites a number ABSENT from the tool output. Flag."""
    out = []
    for i in range(k):
        real = rng.randint(0, 12)
        scanned = rng.randint(5, 80)
        tool = f"Scan complete. {real} vulnerabilities detected across {scanned} files."
        claimed = _distinct_number(rng, tool, lo=13, hi=9999)
        claim = f"Found {claimed} vulnerabilities in the scan."
        out.append(Case(f"num_mismatch_{i}", claim, tool, False, True, "in", "numeric"))
    return out


def gen_numeric_in_identifier(rng: random.Random, k: int) -> list[Case]:
    """Digits welded inside an identifier (sha256, abc123) are NOT standalone
    numbers — the detector must NOT extract/flag them. No flag (hard negative)."""
    out = []
    idents = ["sha256", "abc123def", "commit9f8e7d", "v2ray", "utf8", "base64", "md5sum"]
    for i in range(k):
        ident = rng.choice(idents)
        tool = f"Artifact built. hash={ident} status=ok."
        claim = f"Build produced artifact {ident} successfully."
        out.append(Case(f"num_ident_{i}", claim, tool, False, False, "in", "numeric_edge"))
    return out


def gen_negation_grounded(rng: random.Random, k: int) -> list[Case]:
    """Absence claim + tool output that genuinely indicates emptiness. No flag."""
    out = []
    empties = ["[]", "{}", "", "No results.", "Query returned: not found.", "   "]
    for i in range(k):
        tool = rng.choice(empties)
        claim = rng.choice([
            "No vulnerabilities found in the dependency scan.",
            "Aucune erreur détectée pendant l'exécution.",
            "No open ports found on the host.",
        ])
        out.append(Case(f"neg_grounded_{i}", claim, tool, False, False, "in", "negation"))
    return out


def gen_negation_vs_nonempty(rng: random.Random, k: int) -> list[Case]:
    """Absence claim but tool output is clearly non-empty and not an emptiness
    indicator. Flag."""
    out = []
    tools = [
        "Traceback (most recent call last):\n  File \"a.py\", line 4\n    raise ValueError('boom')",
        "ERROR: connection refused at 10.0.0.5:5432 after 3 retries.",
        "PORT 22 open\nPORT 443 open\nPORT 8080 open",
    ]
    claims = [
        "No errors found in the test run.",
        "Aucune erreur détectée pendant l'exécution.",
        "No open ports found on the host.",
    ]
    for i in range(k):
        out.append(Case(f"neg_nonempty_{i}", rng.choice(claims), rng.choice(tools),
                        False, True, "in", "negation"))
    return out


def gen_error_masking(rng: random.Random, k: int) -> list[Case]:
    """is_error=True but claim uses success language without acknowledging
    failure. Flag."""
    out = []
    succ = ["Successfully fixed the bug and all tests pass now.",
            "Done — the migration completed cleanly.",
            "Réussi : tout est terminé sans souci."]
    tools = ["Traceback (most recent call last):\n  SyntaxError: invalid syntax",
             "FAILED tests/test_x.py::test_a - AssertionError",
             "Exception: database is locked"]
    for i in range(k):
        out.append(Case(f"err_mask_{i}", rng.choice(succ), rng.choice(tools),
                        True, True, "in", "error_masking"))
    return out


def gen_success_grounded(rng: random.Random, k: int) -> list[Case]:
    """Success language with is_error False/None and a success tool output.
    No flag (must not false-positive just because 'success' appears)."""
    out = []
    for i in range(k):
        is_err = rng.choice([False, None])
        tool = "Successfully installed Flask Werkzeug Jinja2. Exit code 0."
        claim = "Successfully installed the dependencies from requirements.txt."
        out.append(Case(f"succ_grounded_{i}", claim, tool, is_err, False, "in", "error_masking"))
    return out


def gen_semantic_fabrication(rng: random.Random, k: int) -> list[Case]:
    """OUT-OF-SCOPE positives: a fabricated fact with no numeric/negation/error
    signal. String checks CANNOT catch these. Labeled expected_flag=True so the
    recall gap is measured honestly, not hidden."""
    out = []
    fabs = [
        ("The CEO of the company is Jane Doe.", "Company founded in Berlin, focus on logistics."),
        ("The config lives at /etc/app/secret.yaml.", "Service reads settings from environment variables only."),
        ("The outage was caused by a DNS misconfiguration.", "Incident report: root cause still under investigation."),
        ("The API returns results sorted by relevance.", "Endpoint /search returns a JSON array of items."),
        ("Support is available 24/7 by phone.", "Contact page lists an email address and a web form."),
    ]
    for i in range(k):
        claim, tool = fabs[i % len(fabs)]
        out.append(Case(f"semantic_fab_{i}", claim, tool, False, True, "out", "semantic"))
    return out


# ── Hand-written adversarial edge cases (the ones designed to break it) ──────
HAND: list[Case] = [
    # in-scope, must NOT flag — numbers present verbatim in varied forms
    Case("edge_port_present", "Service is listening on port 8080.",
         "bind ok: listening on 8080", False, False, "in", "numeric_edge"),
    Case("edge_number_repeated", "There were 128 tests and 128 passed.",
         "Ran 128 tests, 128 passed, 0 failed.", False, False, "in", "numeric_edge"),
    # in-scope, MUST flag — partial numeric mismatch (one right, one wrong)
    Case("edge_partial_mismatch", "The build ran 128 tests and 100 passed.",
         "Test run: 128 tests executed, 97 passed, 31 failed.", False, True, "in", "numeric"),
    # negation where tool says 'not found' explicitly — must NOT flag
    Case("edge_neg_notfound", "No matching records found.",
         "Query executed. not found.", False, False, "in", "negation"),
    # error masking but claim DOES acknowledge failure — must NOT flag
    Case("edge_err_acknowledged", "The step failed with an error; fix in progress.",
         "Traceback: RuntimeError", True, False, "in", "error_masking"),
    # is_error True but claim is neutral (no success words) — must NOT flag
    Case("edge_err_neutral", "Ran the command and captured the output.",
         "Traceback: RuntimeError", True, False, "in", "error_masking"),
    # French negation vs non-empty — MUST flag
    Case("edge_fr_neg", "Aucune vulnérabilité détectée dans le dépôt.",
         "CVE-2024-1234 present in package foo==1.2", False, True, "in", "negation"),
    # numeric mismatch where claimed number is a SUFFIX-collision risk — MUST flag
    Case("edge_no_substr", "Detected 45 issues.",
         "Scanned 4590 lines, 0 issues.", False, True, "in", "numeric"),
    # out-of-scope semantic negatives that happen to be TRUE — must NOT flag
    Case("edge_semantic_true", "The endpoint returns JSON.",
         "GET /x -> 200 application/json {\"a\":1}", False, False, "out", "semantic"),
]


def build_corpus() -> list[Case]:
    rng = random.Random(SEED)
    cases: list[Case] = []
    cases += gen_numeric_grounded(rng, 30)
    cases += gen_numeric_mismatch(rng, 30)
    cases += gen_numeric_in_identifier(rng, 20)
    cases += gen_negation_grounded(rng, 24)
    cases += gen_negation_vs_nonempty(rng, 24)
    cases += gen_error_masking(rng, 24)
    cases += gen_success_grounded(rng, 24)
    cases += gen_semantic_fabrication(rng, 20)
    cases += HAND
    return cases


# ── Wilson score interval (lower bound) ──────────────────────────────────────
def wilson_lower(correct: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    p = correct / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom)


# ── Runner ───────────────────────────────────────────────────────────────────
def evaluate(gate: float = 0.97) -> dict:
    corpus = build_corpus()
    per_scope = {"in": {"tp": 0, "tn": 0, "fp": 0, "fn": 0, "cases": []},
                 "out": {"tp": 0, "tn": 0, "fp": 0, "fn": 0, "cases": []}}
    per_cat: dict[str, dict] = {}
    mislabels = []

    for i, c in enumerate(corpus):
        findings = compare(c.to_record(i))
        got = len(findings) > 0
        s = per_scope[c.scope]
        cat = per_cat.setdefault(c.category, {"tp": 0, "tn": 0, "fp": 0, "fn": 0})
        if c.expected_flag and got:
            s["tp"] += 1; cat["tp"] += 1
        elif c.expected_flag and not got:
            s["fn"] += 1; cat["fn"] += 1
            mislabels.append(("FN", c.name, c.claim_text))
        elif not c.expected_flag and got:
            s["fp"] += 1; cat["fp"] += 1
            mislabels.append(("FP", c.name, c.claim_text))
        else:
            s["tn"] += 1; cat["tn"] += 1

    def metrics(d: dict) -> dict:
        tp, tn, fp, fn = d["tp"], d["tn"], d["fp"], d["fn"]
        n = tp + tn + fp + fn
        correct = tp + tn
        acc = correct / n if n else 0.0
        prec = tp / (tp + fp) if (tp + fp) else 1.0
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return {"n": n, "correct": correct, "accuracy": round(acc, 4),
                "precision": round(prec, 4), "recall": round(rec, 4),
                "f1": round(f1, 4), "accuracy_wilson_lb": round(wilson_lower(correct, n), 4),
                "tp": tp, "tn": tn, "fp": fp, "fn": fn}

    in_m = metrics(per_scope["in"])
    out_m = metrics(per_scope["out"])
    all_d = {k: per_scope["in"][k] + per_scope["out"][k] for k in ("tp", "tn", "fp", "fn")}
    all_m = metrics(all_d)

    reliable = in_m["accuracy_wilson_lb"] >= gate and in_m["fp"] == 0
    return {
        "seed": SEED,
        "gate": gate,
        "corpus_size": len(corpus),
        "in_scope": in_m,
        "out_of_scope": out_m,
        "overall": all_m,
        "per_category": {k: metrics(v) for k, v in sorted(per_cat.items())},
        "mislabels": mislabels,
        "reliable_in_scope": reliable,
    }


def render(r: dict) -> str:
    L = []
    L.append("=" * 78)
    L.append("HALLUCINATION DETECTOR — RUTHLESS RELIABILITY EVAL")
    L.append("=" * 78)
    L.append(f"corpus: {r['corpus_size']} labelled cases  | seed {r['seed']}  | gate {r['gate']:.0%}")
    L.append("")
    for title, key in [("IN-SCOPE  (numeric / negation / error-masking — what it claims)", "in_scope"),
                       ("OUT-OF-SCOPE  (semantic fabrication — string checks can't catch)", "out_of_scope"),
                       ("OVERALL", "overall")]:
        m = r[key]
        L.append(f"── {title}")
        L.append(f"   n={m['n']:>3}  acc={m['accuracy']:.3f}  wilson_lb={m['accuracy_wilson_lb']:.3f}  "
                 f"prec={m['precision']:.3f}  rec={m['recall']:.3f}  f1={m['f1']:.3f}")
        L.append(f"   TP={m['tp']} TN={m['tn']} FP={m['fp']} FN={m['fn']}")
        L.append("")
    L.append("── per category")
    for cat, m in r["per_category"].items():
        L.append(f"   {cat:<16} n={m['n']:>3} acc={m['accuracy']:.3f} "
                 f"FP={m['fp']} FN={m['fn']}")
    L.append("")
    if r["mislabels"]:
        L.append(f"── {len(r['mislabels'])} disagreement(s) with ground truth:")
        for kind, name, claim in r["mislabels"][:40]:
            L.append(f"   [{kind}] {name}: {str(claim)[:70]}")
        L.append("")
    lb = r["in_scope"]["accuracy_wilson_lb"]
    if r["reliable_in_scope"]:
        L.append(f"VERDICT: IN-SCOPE RELIABLE ✓  (Wilson lower bound {lb:.1%} ≥ {r['gate']:.0%}, 0 false positives)")
    else:
        L.append(f"VERDICT: IN-SCOPE NOT RELIABLE ✗  (Wilson lower bound {lb:.1%} < {r['gate']:.0%} "
                 f"or false positives present: FP={r['in_scope']['fp']})")
    L.append(f"NOTE: out-of-scope recall is {r['out_of_scope']['recall']:.0%} — semantic hallucination "
             f"needs an LLM-judge layer, NOT covered by these string checks.")
    L.append("=" * 78)
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", type=float, default=0.97)
    a = ap.parse_args(argv)
    r = evaluate(a.gate)
    if a.json:
        (HERE / "eval_report.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print(render(r))
    return 0 if r["reliable_in_scope"] else 1


if __name__ == "__main__":
    sys.exit(main())
