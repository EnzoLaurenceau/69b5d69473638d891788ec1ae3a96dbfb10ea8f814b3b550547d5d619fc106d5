"""
RAG quality helpers — re-ranking, hybrid fusion, grounding/hallucination check.
Grounding delegates to the existing NeuroSymbolicGuard (no reinvention).
Ref: 00_CORE/blueprints/ai_agent_best_practices.md §1
"""
from __future__ import annotations
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(*ranked_lists: list, k: int = 60) -> list:
    """Hybrid search: merge keyword-ranked + vector-ranked doc-id lists via RRF.
    Each arg is an ordered list of doc ids (best first). Returns fused order.
    ponytail: RRF over tuning BM25/vector weights — parameter-free, strong default."""
    scores: dict = {}
    for lst in ranked_lists:
        for rank, doc in enumerate(lst):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return [d for d, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def rerank(query: str, docs: list[str], top_n: int = 5) -> list[tuple[str, float]]:
    """Re-rank candidate chunks by relevance to query, FREE-tier scorer.
    Falls back to lexical overlap if LLM scorer unavailable."""
    try:
        from forge_agents.forge_llm import forge_score
        scored = [(d, forge_score(d, f"relevance to query: {query}")) for d in docs]
    except Exception:
        qset = set(query.lower().split())
        scored = [(d, len(qset & set(d.lower().split())) / (len(qset) or 1)) for d in docs]
    return sorted(scored, key=lambda x: x[1], reverse=True)[:top_n]


@dataclass
class GroundingResult:
    grounded: bool
    confidence: float
    unsupported: list[str]
    explanation: str


def ground_check(answer: str, sources: list[str]) -> GroundingResult:
    """Hallucination guard + grounding. Wraps NeuroSymbolicGuard.
    Prefer 'I don't know' when confidence is low upstream."""
    try:
        from forge_agents.neuro_symbolic_guard import NeuroSymbolicGuard
        g = NeuroSymbolicGuard()
        vr = g.verify_claim(answer, grounding_sources=sources) \
            if hasattr(g, "verify_claim") else None
        if vr is not None:
            return GroundingResult(vr.is_valid, vr.confidence,
                                   vr.contradictions, vr.explanation)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    # ponytail fallback: lexical support ratio when guard API differs/absent
    joined = " ".join(sources).lower()
    toks = [t for t in answer.lower().split() if len(t) > 4]
    supported = sum(t in joined for t in toks)
    conf = supported / (len(toks) or 1)
    return GroundingResult(conf >= 0.5, conf, [],
                           f"lexical support {supported}/{len(toks)}")


def demo() -> None:
    fused = reciprocal_rank_fusion(["a", "b", "c"], ["b", "d", "a"])
    assert fused[0] == "b" and set(fused) == {"a", "b", "c", "d"}
    top = rerank("python web framework", ["django is a python web framework", "banana bread recipe"])
    assert top[0][0].startswith("django")
    assert ground_check("django is a python web framework",
                        ["django is a python web framework"]).grounded
    print("rag demo ok")


if __name__ == "__main__":
    demo()
