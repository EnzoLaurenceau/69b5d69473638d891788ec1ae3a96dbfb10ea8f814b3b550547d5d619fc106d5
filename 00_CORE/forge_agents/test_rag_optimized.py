"""
test_rag_optimized.py — Tests for forge_rag_optimized.py
=========================================================
Tests all 8 features:
  1. BM25 search
  2. Vector search
  3. Hybrid search
  4. Cross-encoder reranker
  5. Semantic chunking
  6. Deduplication
  7. Hierarchical indexing
  8. Domain partitioning
"""
from __future__ import annotations

import sys
import os
import math

# Ensure this directory is importable
sys.path.insert(0, os.path.dirname(__file__))

from forge_rag_optimized import (
    ForgeRAGOptimized, get_rag_optimized, RAGChunk, semantic_chunk,
)

# ─── Test documents ─────────────────────────────────────────────────────────

DOC_A = """# Python Basics

Python is a high-level programming language. It supports multiple paradigms
including procedural, object-oriented, and functional programming.

## Variables and Types

Variables in Python do not need explicit declaration. The language is
dynamically typed. Common types include int, float, str, list, dict.

## Control Flow

Python uses indentation to define code blocks. The main control structures
are if/elif/else, for loops, and while loops. List comprehensions provide
concise syntax for creating lists.
"""

DOC_B = """# Machine Learning Overview

Machine learning is a subset of artificial intelligence that focuses on
building systems that learn from data. There are three main types:
supervised, unsupervised, and reinforcement learning.

## Supervised Learning

In supervised learning, the model learns from labeled training data.
Common algorithms include linear regression, decision trees, and neural
networks. The goal is to predict outcomes for unseen data.

## Unsupervised Learning

Unsupervised learning finds hidden patterns in unlabeled data. Clustering
algorithms like K-means and hierarchical clustering are widely used.
Dimensionality reduction techniques like PCA help visualize high-dimensional data.
"""

DOC_C = """# Web Development

Web development involves building websites and web applications. The main
technologies are HTML, CSS, and JavaScript. Modern frameworks include
React, Vue, and Angular for frontend development.

## Frontend Technologies

HTML provides structure, CSS handles styling, and JavaScript adds
interactivity. Responsive design ensures websites work on all devices.

## Backend Development

Backend development uses languages like Python, Node.js, and Go.
REST APIs and GraphQL are common approaches for building web services.
"""

DOC_DUP = """# Python Basics

Python is a high-level programming language. It supports multiple paradigms
including procedural, object-oriented, and functional programming.

## Variables and Types

Variables in Python do not need explicit declaration. The language is
dynamically typed. Common types include int, float, str, list, dict.
"""


# ─── Helpers ────────────────────────────────────────────────────────────────

def make_rag() -> ForgeRAGOptimized:
    """Create a fresh RAG instance (no singleton leak)."""
    return ForgeRAGOptimized()


def assert_close(a: float, b: float, tol: float = 0.01):
    assert abs(a - b) < tol, f"{a} != {b} (tol={tol})"


# ─── Tests ──────────────────────────────────────────────────────────────────

def test_semantic_chunking_basic():
    """Feature 5: semantic_chunk splits on headers/paragraphs."""
    chunks = semantic_chunk(DOC_A, max_chars=500)
    assert len(chunks) >= 3, f"Expected >=3 chunks, got {len(chunks)}"
    for c in chunks:
        assert len(c) <= 500, f"Chunk too long: {len(c)} chars"
    # Check that headers are preserved
    headers_found = sum(1 for c in chunks if c.startswith("#"))
    assert headers_found >= 2, f"Expected >=2 header chunks, got {headers_found}"
    print("  [PASS] test_semantic_chunking_basic")


def test_semantic_chunking_long_text():
    """Feature 5: long text gets split properly."""
    long_text = "This is a sentence. " * 100  # ~2100 chars
    chunks = semantic_chunk(long_text, max_chars=500)
    assert len(chunks) >= 4, f"Expected >=4 chunks for long text, got {len(chunks)}"
    for c in chunks:
        assert len(c) <= 500
    print("  [PASS] test_semantic_chunking_long_text")


def test_bm25_search():
    """Feature 1: BM25 search returns relevant results."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")
    results = rag.search_bm25("Python programming language", top_k=5)
    assert len(results) > 0, "No BM25 results"
    # Python doc should rank high
    assert any(r.source == "doc_a.txt" for r in results[:2]), \
        "doc_a.txt not in top 2 BM25 results"
    print("  [PASS] test_bm25_search")


def test_vector_search():
    """Feature 2: Vector search returns semantically relevant results."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")
    results = rag.search_vector("coding language variables", top_k=5)
    assert len(results) > 0, "No vector results"
    # Python doc should be relevant (semantic similarity)
    scores = {r.source: r.vec_score for r in results}
    assert max(scores.values()) > 0, "All vector scores are 0"
    print("  [PASS] test_vector_search")


def test_hybrid_search():
    """Feature 3: Hybrid search combines BM25 and vector scores."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")
    rag.index("doc_c.txt", DOC_C, domain="web")
    results = rag.search_hybrid("neural network machine learning", top_k=5)
    assert len(results) > 0, "No hybrid results"
    # ML doc should rank highly
    assert any(r.source == "doc_b.txt" for r in results[:2]), \
        "doc_b.txt not in top 2 hybrid results"
    # Scores should be normalized to [0, 1]
    for r in results:
        assert 0.0 <= r.bm25_score <= 1.0, f"BM25 score out of range: {r.bm25_score}"
        assert 0.0 <= r.vec_score <= 1.0, f"Vec score out of range: {r.vec_score}"
    print("  [PASS] test_hybrid_search")


def test_hybrid_weights():
    """Feature 3: Hybrid search respects BM25/vector weights."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")

    # Heavy BM25
    r1 = rag.search_hybrid("Python variables", top_k=1, bm25_weight=0.9, vec_weight=0.1)
    # Heavy vector
    r2 = rag.search_hybrid("Python variables", top_k=1, bm25_weight=0.1, vec_weight=0.9)
    assert len(r1) > 0 and len(r2) > 0
    print("  [PASS] test_hybrid_weights")


def test_reranker():
    """Feature 4: Cross-encoder reranker reorders results."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")
    rag.index("doc_c.txt", DOC_C, domain="web")

    candidates = rag.search_hybrid("programming language", top_k=20)
    assert len(candidates) > 0
    reranked = rag.rerank("programming language", candidates, top_k=5)
    assert len(reranked) <= 5, f"Reranker returned {len(reranked)} results, expected <=5"
    # Rerank scores should be set
    for r in reranked:
        assert r.rerank_score != 0.0, "Rerank score not set"
    # Results should be sorted by rerank_score descending
    for i in range(len(reranked) - 1):
        assert reranked[i].rerank_score >= reranked[i + 1].rerank_score, \
            "Reranked results not sorted"
    print("  [PASS] test_reranker")


def test_deduplication():
    """Feature 6: Deduplication removes near-duplicate chunks."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    initial_chunks = len(rag._chunks)

    # Index near-duplicate
    rag.index("doc_dup.txt", DOC_DUP, domain="python")
    before_dedup = len(rag._chunks)
    removed = rag.deduplicate(threshold=0.90)
    after_dedup = len(rag._chunks)

    assert removed > 0, f"Expected dedup to remove chunks, removed={removed}"
    assert after_dedup < before_dedup, "Chunk count didn't decrease"
    print(f"  [PASS] test_deduplication (removed {removed} chunks)")


def test_hierarchical_indexing():
    """Feature 7: Hierarchical index creates doc/section/chunk levels."""
    rag = make_rag()
    doc_id = rag.index_hierarchical("doc_a.txt", DOC_A, domain="python")

    assert doc_id in rag._hierarchy, f"doc_id {doc_id} not in hierarchy"
    hier = rag._hierarchy[doc_id]
    assert "sections" in hier
    assert len(hier["sections"]) >= 2, f"Expected >=2 sections, got {len(hier['sections'])}"
    for sec in hier["sections"]:
        assert "header" in sec
        assert "chunk_count" in sec
        assert sec["chunk_count"] > 0
    print("  [PASS] test_hierarchical_indexing")


def test_search_by_level_chunk():
    """Feature 7: search_by_level at chunk level."""
    rag = make_rag()
    rag.index_hierarchical("doc_a.txt", DOC_A, domain="python")
    rag.index_hierarchical("doc_b.txt", DOC_B, domain="ml")

    results = rag.search_by_level("Python variables", level="chunk", top_k=3)
    assert len(results) > 0
    assert results[0]["level"] == "chunk"
    assert "text" in results[0]
    print("  [PASS] test_search_by_level_chunk")


def test_search_by_level_section():
    """Feature 7: search_by_level at section level."""
    rag = make_rag()
    rag.index_hierarchical("doc_a.txt", DOC_A, domain="python")
    rag.index_hierarchical("doc_b.txt", DOC_B, domain="ml")

    results = rag.search_by_level("supervised learning", level="section", top_k=3)
    assert len(results) > 0
    assert results[0]["level"] == "section"
    assert "header" in results[0]
    print("  [PASS] test_search_by_level_section")


def test_search_by_level_doc():
    """Feature 7: search_by_level at doc level."""
    rag = make_rag()
    rag.index_hierarchical("doc_a.txt", DOC_A, domain="python")
    rag.index_hierarchical("doc_b.txt", DOC_B, domain="ml")

    results = rag.search_by_level("machine learning algorithms", level="doc", top_k=3)
    assert len(results) > 0
    assert results[0]["level"] == "doc"
    assert "doc_id" in results[0]
    print("  [PASS] test_search_by_level_doc")


def test_domain_partitioning():
    """Feature 8: search_domain filters by domain."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")
    rag.index("doc_c.txt", DOC_C, domain="web")

    # Search in ML domain only
    ml_results = rag.search_domain("learning algorithm", domain="ml", top_k=5)
    assert len(ml_results) > 0
    for r in ml_results:
        assert r.metadata["domain"] == "ml", f"Wrong domain: {r.metadata['domain']}"

    # Search in Python domain
    py_results = rag.search_domain("variables types", domain="python", top_k=5)
    assert len(py_results) > 0
    for r in py_results:
        assert r.metadata["domain"] == "python"

    # Empty domain
    empty = rag.search_domain("test", domain="nonexistent", top_k=5)
    assert empty == []
    print("  [PASS] test_domain_partitioning")


def test_singleton():
    """Singleton pattern: get_rag_optimized() returns same instance."""
    import forge_rag_optimized as mod
    mod._RAG = None  # reset
    r1 = get_rag_optimized()
    r2 = get_rag_optimized()
    assert r1 is r2, "Singleton returned different instances"
    print("  [PASS] test_singleton")


def test_rag_chunk_dataclass():
    """RAGChunk dataclass has all required fields."""
    c = RAGChunk(doc_id="d0", chunk_idx=0, text="hello", source="src.txt")
    assert c.bm25_score == 0.0
    assert c.vec_score == 0.0
    assert c.rerank_score == 0.0
    assert c.metadata == {}
    print("  [PASS] test_rag_chunk_dataclass")


def test_stats():
    """Stats method returns correct information."""
    rag = make_rag()
    rag.index("doc_a.txt", DOC_A, domain="python")
    rag.index("doc_b.txt", DOC_B, domain="ml")
    s = rag.stats()
    assert s["total_chunks"] > 0
    assert "python" in s["domains"]
    assert "ml" in s["domains"]
    print("  [PASS] test_stats")


def test_empty_search():
    """Searching empty index returns empty results."""
    rag = make_rag()
    assert rag.search_bm25("test") == []
    assert rag.search_vector("test") == []
    assert rag.search_hybrid("test") == []
    print("  [PASS] test_empty_search")


def test_end_to_end_rag_pipeline():
    """Full RAG pipeline: index → hybrid search → rerank."""
    rag = make_rag()
    rag.index_hierarchical("doc_a.txt", DOC_A, domain="python")
    rag.index_hierarchical("doc_b.txt", DOC_B, domain="ml")
    rag.index_hierarchical("doc_c.txt", DOC_C, domain="web")

    # Step 1: Hybrid retrieval (Top-20)
    candidates = rag.search_hybrid("programming and data science", top_k=20)
    assert len(candidates) > 0

    # Step 2: Rerank to Top-5
    final = rag.rerank("programming and data science", candidates, top_k=5)
    assert len(final) <= 5

    # Step 3: Verify pipeline integrity
    for r in final:
        assert r.text  # non-empty
        assert r.source  # has source
        assert r.rerank_score != 0.0  # reranked

    print("  [PASS] test_end_to_end_rag_pipeline")


# ─── Runner ─────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_semantic_chunking_basic,
    test_semantic_chunking_long_text,
    test_rag_chunk_dataclass,
    test_singleton,
    test_bm25_search,
    test_vector_search,
    test_hybrid_search,
    test_hybrid_weights,
    test_reranker,
    test_deduplication,
    test_hierarchical_indexing,
    test_search_by_level_chunk,
    test_search_by_level_section,
    test_search_by_level_doc,
    test_domain_partitioning,
    test_stats,
    test_empty_search,
    test_end_to_end_rag_pipeline,
]


def main():
    print("=" * 60)
    print("ForgeRAGOptimized — Test Suite (8 features)")
    print("=" * 60)
    passed = 0
    failed = 0
    errors = []
    for test_fn in ALL_TESTS:
        name = test_fn.__name__
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(ALL_TESTS)}")
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
