"""
LLM-as-a-Judge — grounded eval, 5 metrics, majority vote, FREE tier.
Complements MiroFish/Herald. Never runs on Claude directly (cost).
Ref: 00_CORE/blueprints/ai_agent_best_practices.md §2
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict

METRICS = ("faithfulness", "correctness", "relevance", "completeness", "safety")


@dataclass
class Verdict:
    scores: dict          # metric -> 0..10
    overall: float
    low_confidence: bool  # True => route to human
    notes: str


def _one_pass(query: str, answer: str, context: str, reference: str) -> dict:
    from forge_agents.forge_llm import forge_call, LLMTier
    rubric = ", ".join(METRICS)
    shape = "{" + ", ".join(f'"{m}": <int 0-10>' for m in METRICS) + "}"
    prompt = (
        f"You are an evaluation judge. Grade the ANSWER 0-10 on each of: {rubric}.\n"
        f"Ground your grades in QUERY, CONTEXT and REFERENCE only.\n\n"
        f"QUERY:\n{query}\n\nCONTEXT:\n{context[:2000]}\n\n"
        f"REFERENCE:\n{reference[:1000]}\n\nANSWER:\n{answer[:2000]}\n\n"
        f"Return ONLY JSON: {shape}"
    )
    raw = forge_call(prompt, tier=LLMTier.HAIKU, task_type="score",
                     node="llm_judge", show_tokens=False,
                     use_openviking=False, nano_mode=False)
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}
    return {k: float(data.get(k, 0)) for k in METRICS}


def judge(query: str, answer: str, context: str = "", reference: str = "",
          votes: int = 1) -> Verdict:
    """Grade one answer. votes>1 => average N passes (majority-ish, robustness)."""
    try:
        passes = [_one_pass(query, answer, context, reference) for _ in range(max(1, votes))]
    except Exception as e:
        return Verdict({m: 0.0 for m in METRICS}, 0.0, True, f"judge unavailable: {e}")
    scores = {m: round(sum(p[m] for p in passes) / len(passes), 2) for m in METRICS}
    overall = round(sum(scores.values()) / len(METRICS), 2)
    # low confidence: any pass disagreed by >3 pts, or safety weak, or middling overall
    spread = max(max(p[m] for p in passes) - min(p[m] for p in passes)
                 for m in METRICS)
    low = spread > 3 or scores["safety"] < 6 or 4 <= overall <= 6
    return Verdict(scores, overall, low, f"votes={len(passes)} spread={spread}")


def evaluate_golden(dataset: list[dict], votes: int = 1) -> dict:
    """Offline eval over a golden set of {query, answer, context?, reference?}."""
    verdicts = [judge(d["query"], d["answer"], d.get("context", ""),
                      d.get("reference", ""), votes) for d in dataset]
    n = len(verdicts) or 1
    return {
        "n": len(verdicts),
        "mean_overall": round(sum(v.overall for v in verdicts) / n, 2),
        "flagged_for_human": [i for i, v in enumerate(verdicts) if v.low_confidence],
        "verdicts": [asdict(v) for v in verdicts],
    }


def demo() -> None:
    # structural self-check without hitting the LLM
    v = Verdict({m: 8.0 for m in METRICS}, 8.0, False, "x")
    assert set(v.scores) == set(METRICS) and v.overall == 8.0
    bad = judge("q", "a", votes=1)  # LLM likely absent -> graceful
    assert bad.low_confidence  # unavailable path flags for human
    print("judge demo ok")


if __name__ == "__main__":
    demo()
