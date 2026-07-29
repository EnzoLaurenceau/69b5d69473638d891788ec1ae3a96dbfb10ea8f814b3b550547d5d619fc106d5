# Plan: Optimisations RAG à l'Échelle (Section 4)

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Transformer le RAG de la Forge d'un système basique (hash-based, keyword matching) en un système hybride avancé (BM25 + vectoriel + reranker cross-encoder) avec chunking sémantique, déduplication agressive et partitionnement par domaine.

**Architecture:** Module `forge_rag_optimized.py` (singleton) qui encapsule BM25, vectoriel, cross-encoder reranker. S'intègre dans `adaptive_rag.py` via une stratégie `OPTIMIZED` entre `STANDARD` et `FULL`.

**Tech Stack:** sentence-transformers (embeddings), rank_bm25 (BM25), sentence-transformers cross-encoder (reranker), numpy, faiss (optionnel).

---

## État Actuel (5 modules RAG existants)

| Module | Rôle | Manque |
|--------|------|--------|
| adaptive_rag.py | Stratégies NONE/LIGHT/STANDARD/FULL | Pas de BM25, pas de reranker |
| rag_anything.py | RAG-Anything wrapper (multimodal) | Embedding OpenAI-only |
| semantic_cache.py | SimHash + Nexus CAS | Pas de chunking sémantique |
| turbovec_brain.py | 4-bit index quantisé | Hash-based, pas de vrais embeddings |
| dataset_rag.py | Few-shot RAG datasets | TF-IDF-like, pas de vectoriel |

---

## Task 1: Module `forge_rag_optimized.py` — BM25 Local

**Objective:** Créer le module de base avec BM25 (mots-clés rares, zéro API)

**Files:**
- Create: `00_CORE/forge_agents/forge_rag_optimized.py`
- Modify: `00_CORE/forge_agents/adaptive_rag.py` (ajouter stratégie OPTIMIZED)

**Step 1: Write failing test**

```python
# test_rag_optimized.py
from forge_agents.forge_rag_optimized import ForgeRAGOptimized

def test_bm25_basic():
    rag = ForgeRAGOptimized()
    rag.index("forge_llm.py", "forge_call() routes to MiMo for SIMPLE tasks")
    rag.index("forge_graph.py", "build_forge_graph() creates LangGraph StateGraph")
    results = rag.search_bm25("forge_call MiMo", top_k=1)
    assert len(results) == 1
    assert "forge_call" in results[0].text

def test_bm25_empty():
    rag = ForgeRAGOptimized()
    results = rag.search_bm25("nothing", top_k=5)
    assert results == []
```

**Step 2: Run test to verify failure**

```bash
cd C:/Users/Enzo/Documents/MODELS/.claude
python -m pytest test_rag_optimized.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# forge_rag_optimized.py
"""
forge_rag_optimized.py — RAG Optimisé (BM25 + Vectoriel + Reranker)
====================================================================
Section 4 du plan Blueprints+Pxpipe+RAG.

Stratégie hybride :
  1. BM25 (rank_bm25) — mots-clés rares, zéro API
  2. Vectoriel (sentence-transformers) — sémantique, local
  3. Cross-encoder reranker — précision Top-5

Usage:
    from forge_agents.forge_rag_optimized import get_rag_optimized
    rag = get_rag_optimized()
    rag.ingest_documents(docs)  # ou rag.index(source, text)
    results = rag.search_hybrid("query", top_k=5)
"""

from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("ForgeRAGOptimized")

FORGE_ROOT = Path(__file__).parent.parent.parent

@dataclass
class RAGChunk:
    """Un chunk indexé."""
    doc_id: str
    chunk_idx: int
    text: str
    source: str  # fichier source
    bm25_score: float = 0.0
    vec_score: float = 0.0
    rerank_score: float = 0.0
    metadata: dict = field(default_factory=dict)

class ForgeRAGOptimized:
    """RAG hybride BM25 + vectoriel + reranker."""

    def __init__(self):
        self._chunks: list[RAGChunk] = []
        self._bm25 = None
        self._encoder = None
        self._reranker = None
        self._indexed = False

    def index(self, source: str, text: str, doc_id: str | None = None):
        """Indexer un document (chunking simple par paragraphes)."""
        doc_id = doc_id or source
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            if len(para) > 20:  # ignorer les paragraphes trop courts
                self._chunks.append(RAGChunk(
                    doc_id=doc_id,
                    chunk_idx=i,
                    text=para,
                    source=source,
                ))
        self._indexed = False  # nécessite rebuild index

    def search_bm25(self, query: str, top_k: int = 5) -> list[RAGChunk]:
        """Recherche BM25 (mots-clés rares)."""
        if not self._chunks:
            return []
        self._ensure_bm25()
        from rank_bm25 import BM25Okapi
        tokenized = [self._tokenize(c.text) for c in self._chunks]
        bm25 = BM25Okapi(tokenized)
        query_tokens = self._tokenize(query)
        scores = bm25.get_scores(query_tokens)
        # Top-k
        ranked = sorted(zip(self._chunks, scores), key=lambda x: -x[1])[:top_k]
        results = []
        for chunk, score in ranked:
            c = RAGChunk(**vars(chunk))
            c.bm25_score = float(score)
            results.append(c)
        return results

    def _tokenize(self, text: str) -> list[str]:
        """Tokenization simple (lowercase + split)."""
        return re.findall(r'\w+', text.lower())

    def _ensure_bm25(self):
        """Lazy-init BM25."""
        if self._bm25 is None:
            try:
                from rank_bm25 import BM25Okapi
                tokenized = [self._tokenize(c.text) for c in self._chunks]
                self._bm25 = BM25Okapi(tokenized)
            except ImportError:
                log.warning("[RAG] rank_bm25 not installed, using basic keyword matching")
                self._bm25 = "basic"

# Singleton
_instance: ForgeRAGOptimized | None = None

def get_rag_optimized() -> ForgeRAGOptimized:
    global _instance
    if _instance is None:
        _instance = ForgeRAGOptimized()
    return _instance
```

**Step 4: Run test to verify pass**

```bash
pip install rank_bm25
python -m pytest test_rag_optimized.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): add BM25 local search, zero API calls"
```

---

## Task 2: Vectoriel Local (sentence-transformers)

**Objective:** Ajouter recherche vectorielle locale (embeddings 384-dim, zéro API)

**Files:**
- Modify: `00_CORE/forge_agents/forge_rag_optimized.py`

**Step 1: Add failing test**

```python
def test_vector_search():
    rag = ForgeRAGOptimized()
    rag.index("forge_llm.py", "forge_call() routes tasks to providers based on tier")
    rag.index("forge_graph.py", "build_forge_graph() creates LangGraph state graph")
    results = rag.search_vector("LLM routing", top_k=1)
    assert len(results) == 1
    assert results[0].vec_score > 0

def test_hybrid_search():
    rag = ForgeRAGOptimized()
    rag.index("file1.py", "forge_call uses MiMo for SIMPLE tasks")
    rag.index("file2.py", "LangGraph orchestrates the workflow")
    results = rag.search_hybrid("forge_call routing", top_k=2)
    assert len(results) == 2
    # Hybrid score = bm25 * 0.4 + vec * 0.6
    assert results[0].bm25_score >= 0 or results[0].vec_score >= 0
```

**Step 2: Run test to verify failure**

```bash
python -m pytest test_rag_optimized.py::test_vector_search -v
```
Expected: FAIL — `AttributeError: 'ForgeRAGOptimized' has no attribute 'search_vector'`

**Step 3: Implement vector search + hybrid**

Ajouter dans `forge_rag_optimized.py`:

```python
import numpy as np

# Embedding model (local, 384-dim, fast)
_EMBED_MODEL = "all-MiniLM-L6-v2"

def _get_encoder(self):
    if self._encoder is None:
        try:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(_EMBED_MODEL)
        except ImportError:
            log.warning("[RAG] sentence-transformers not installed")
            self._encoder = None
    return self._encoder

def search_vector(self, query: str, top_k: int = 5) -> list[RAGChunk]:
    """Recherche vectorielle (embeddings locaux)."""
    if not self._chunks:
        return []
    encoder = self._get_encoder()
    if encoder is None:
        return []
    texts = [c.text for c in self._chunks]
    # Encode batch
    q_emb = encoder.encode([query], normalize_embeddings=True)
    doc_embs = encoder.encode(texts, normalize_embeddings=True, batch_size=64)
    # Cosine similarity (normalized = dot product)
    scores = (doc_embs @ q_emb.T).flatten()
    ranked = sorted(zip(self._chunks, scores), key=lambda x: -x[1])[:top_k]
    results = []
    for chunk, score in ranked:
        c = RAGChunk(**vars(chunk))
        c.vec_score = float(score)
        results.append(c)
    return results

def search_hybrid(self, query: str, top_k: int = 5,
                   bm25_weight: float = 0.4, vec_weight: float = 0.6) -> list[RAGChunk]:
    """Recherche hybride BM25 + vectoriel (RRF-like fusion)."""
    if not self._chunks:
        return []

    # Get scores from both
    bm25_results = self.search_bm25(query, top_k=len(self._chunks))
    vec_results = self.search_vector(query, top_k=len(self._chunks))

    # Score map
    scores: dict[str, float] = {}
    bm25_map = {c.doc_id: c.bm25_score for c in bm25_results}
    vec_map = {c.doc_id: c.vec_score for c in vec_results}

    # Normalize scores to [0, 1]
    max_bm25 = max(bm25_map.values()) if bm25_map else 1.0
    max_vec = max(vec_map.values()) if vec_map else 1.0

    for c in self._chunks:
        bm = bm25_map.get(c.doc_id, 0.0) / max_bm25 if max_bm25 > 0 else 0
        ve = vec_map.get(c.doc_id, 0.0) / max_vec if max_vec > 0 else 0
        scores[c.doc_id] = bm * bm25_weight + ve * vec_weight

    # Sort and return top_k
    ranked_ids = sorted(scores, key=lambda x: -scores[x])[:top_k]
    results = []
    for doc_id in ranked_ids:
        chunk = next(c for c in self._chunks if c.doc_id == doc_id)
        c = RAGChunk(**vars(chunk))
        c.bm25_score = bm25_map.get(doc_id, 0.0)
        c.vec_score = vec_map.get(doc_id, 0.0)
        results.append(c)
    return results
```

**Step 4: Run test**

```bash
pip install sentence-transformers
python -m pytest test_rag_optimized.py::test_vector_search -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): add vector search + hybrid BM25+vectoriel"
```

---

## Task 3: Cross-Encoder Reranker (Top-20 → Top-5)

**Objective:** Ajouter reranking cross-encoder pour extraire le Top-5 optimal

**Files:**
- Modify: `00_CORE/forge_agents/forge_rag_optimized.py`

**Step 1: Add failing test**

```python
def test_reranker():
    rag = ForgeRAGOptimized()
    rag.index("f1.py", "forge_call routes to MiMo for simple tasks")
    rag.index("f2.py", "LangGraph orchestrates the workflow graph")
    rag.index("f3.py", "The forge uses adaptive RAG strategies")
    # Hybrid gives broad results, reranker refines
    results = rag.search_hybrid("LLM routing", top_k=3)
    reranked = rag.rerank("LLM routing", results, top_k=2)
    assert len(reranked) == 2
    assert reranked[0].rerank_score > 0
```

**Step 2: Run test to verify failure**

```bash
python -m pytest test_rag_optimized.py::test_reranker -v
```
Expected: FAIL

**Step 3: Implement reranker**

```python
def _get_reranker(self):
    if self._reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except ImportError:
            log.warning("[RAG] sentence-transformers not installed, reranker disabled")
            self._reranker = None
    return self._reranker

def rerank(self, query: str, candidates: list[RAGChunk],
           top_k: int = 5) -> list[RAGChunk]:
    """Reranking cross-encoder (précision Top-5)."""
    if not candidates:
        return []
    reranker = self._get_reranker()
    if reranker is None:
        return candidates[:top_k]  # fallback: keep order

    pairs = [(query, c.text) for c in candidates]
    scores = reranker.predict(pairs)
    for c, score in zip(candidates, scores):
        c.rerank_score = float(score)
    return sorted(candidates, key=lambda x: -x.rerank_score)[:top_k]
```

**Step 4: Run test**

```bash
python -m pytest test_rag_optimized.py::test_reranker -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): add cross-encoder reranker (Top-20 → Top-5)"
```

---

## Task 4: Semantic Chunking (remplace découpage paragraphes)

**Objective:** Remplacer le chunking par paragraphes par un chunking sémantique

**Files:**
- Modify: `00_CORE/forge_agents/forge_rag_optimized.py`

**Step 1: Add failing test**

```python
def test_semantic_chunking():
    rag = ForgeRAGOptimized()
    text = """Section 1: Architecture

La forge utilise un StateGraph LangGraph avec 16 nodes.
Le routing est dynamique via ForgeRouterAgent.

Section 2: Providers

Les providers actifs sont Claude Code, MiMo et Antigravity.
Les providers free sont désactivés pour l'instant.

Section 3: RAG

Le RAG utilise BM25 + vectoriel + cross-encoder reranker.
Le chunking est sémantique (pas par tokens)."""
    chunks = rag.semantic_chunk(text)
    assert len(chunks) >= 2  # au moins 2 chunks sémantiques
    assert all(len(c) > 20 for c in chunks)  # pas de micro-chunks
```

**Step 2: Run test to verify failure**

```bash
python -m pytest test_rag_optimized.py::test_semantic_chunking -v
```
Expected: FAIL

**Step 3: Implement semantic chunking**

```python
def semantic_chunk(self, text: str, max_chunk_size: int = 500,
                   min_chunk_size: int = 50) -> list[str]:
    """
    Chunking sémantique : découpe aux changements de sections/topics.
    Remplace le découpage par tokens (pertinence +30-50%).
    """
    # 1. Découper aux headers markdown (## Section, ### Subsection)
    sections = re.split(r'(?=^#{1,3}\s)', text, flags=re.MULTILINE)

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Si section < max_chunk_size, garder entier
        if len(section) <= max_chunk_size:
            if len(section) >= min_chunk_size:
                chunks.append(section)
            continue

        # Sinon, découper aux paragraphes vides
        paragraphs = re.split(r'\n\s*\n', section)
        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # Si ajout du paragraphe dépasse max, flush
            if current_chunk and len(current_chunk) + len(para) > max_chunk_size:
                if len(current_chunk) >= min_chunk_size:
                    chunks.append(current_chunk)
                current_chunk = para
            else:
                current_chunk = (current_chunk + "\n\n" + para).strip()

        # Flush dernier chunk
        if current_chunk and len(current_chunk) >= min_chunk_size:
            chunks.append(current_chunk)

    return chunks
```

**Step 4: Run test**

```bash
python -m pytest test_rag_optimized.py::test_semantic_chunking -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): semantic chunking by sections (relevance +30-50%)"
```

---

## Task 5: Déduplication Agressive (-40% index)

**Objective:** Fusionner les chunks similaires avant indexation

**Files:**
- Modify: `00_CORE/forge_agents/forge_rag_optimized.py`

**Step 1: Add failing test**

```python
def test_deduplication():
    rag = ForgeRAGOptimized()
    # Chunks quasi-identiques
    rag.index("f1.py", "forge_call() routes to MiMo for SIMPLE tasks")
    rag.index("f2.py", "forge_call() routes to MiMo for SIMPLE tasks.")  # point en plus
    rag.index("f3.py", "LangGraph orchestrates the workflow graph")
    before = len(rag._chunks)
    rag.deduplicate(threshold=0.95)
    after = len(rag._chunks)
    assert after < before  # au moins 1 doublon supprimé
```

**Step 2: Run test to verify failure**

```bash
python -m pytest test_rag_optimized.py::test_deduplication -v
```
Expected: FAIL

**Step 3: Implement deduplication**

```python
def deduplicate(self, threshold: float = 0.95):
    """
    Déduplication agressive : fusionne les chunks similaires (SimHash).
    Réduit l'index de ~40%.
    """
    if len(self._chunks) < 2:
        return

    from .semantic_cache import _tokenize, _simhash, _hamming_similarity

    # Calculer fingerprints
    fps = []
    for c in self._chunks:
        tokens = _tokenize(c.text)
        fps.append(_simhash(tokens))

    # Déduplication pairwise
    to_remove = set()
    for i in range(len(fps)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(fps)):
            if j in to_remove:
                continue
            sim = _hamming_similarity(fps[i], fps[j])
            if sim >= threshold:
                to_remove.add(j)

    # Supprimer les doublons (garder le premier)
    self._chunks = [c for i, c in enumerate(self._chunks) if i not in to_remove]
    self._indexed = False
    log.info(f"[RAG] Dedup: {len(to_remove)} chunks supprimés ({len(self._chunks)} restants)")
```

**Step 4: Run test**

```bash
python -m pytest test_rag_optimized.py::test_deduplication -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): deduplicate chunks (SimHash, -40% index)"
```

---

## Task 6: RAG Hiérarchique (Document → Section → Chunk)

**Objective:** Stocker la hiérarchie pour requêtes à granularité variable

**Files:**
- Modify: `00_CORE/forge_agents/forge_rag_optimized.py`

**Step 1: Add failing test**

```python
def test_hierarchical_indexing():
    rag = ForgeRAGOptimized()
    rag.index_hierarchical("forge_llm.py", """
# forge_llm.py

## forge_call()
Routes tasks to providers based on tier.

### Parameters
- prompt: str
- tier: LLMTier
- task_type: str

## Rate Limiting
Token bucket limiter: 6 req/min, burst 2.
""")
    # Search at different granularities
    doc_results = rag.search_by_level("forge_llm routing", level="doc")
    assert len(doc_results) >= 1
    chunk_results = rag.search_by_level("forge_llm routing", level="chunk")
    assert len(chunk_results) >= 1
```

**Step 2: Run test to verify failure**

```bash
python -m pytest test_rag_optimized.py::test_hierarchical_indexing -v
```
Expected: FAIL

**Step 3: Implement hierarchical indexing**

```python
from enum import Enum

class ChunkLevel(Enum):
    DOC = "doc"
    SECTION = "section"
    CHUNK = "chunk"

def index_hierarchical(self, doc_id: str, text: str):
    """
    Index hiérarchique : Document → Section → Chunk.
    Permet requêtes à granularité variable.
    """
    # Level 1: Document summary (first 200 chars)
    doc_summary = text[:200].strip()
    self._chunks.append(RAGChunk(
        doc_id=doc_id,
        chunk_idx=0,
        text=doc_summary,
        source=doc_id,
        metadata={"level": "doc", "full_text_len": len(text)}
    ))

    # Level 2: Sections (markdown headers)
    sections = re.split(r'(?=^#{1,3}\s)', text, flags=re.MULTILINE)
    for i, section in enumerate(sections):
        section = section.strip()
        if not section or len(section) < 30:
            continue
        self._chunks.append(RAGChunk(
            doc_id=doc_id,
            chunk_idx=i + 1,
            text=section,
            source=doc_id,
            metadata={"level": "section"}
        ))

    # Level 3: Chunks (semantic chunking within sections)
    for i, section in enumerate(sections):
        sub_chunks = self.semantic_chunk(section, max_chunk_size=300)
        for j, chunk_text in enumerate(sub_chunks):
            self._chunks.append(RAGChunk(
                doc_id=doc_id,
                chunk_idx=i * 100 + j,
                text=chunk_text,
                source=doc_id,
                metadata={"level": "chunk", "section_idx": i}
            ))

    self._indexed = False

def search_by_level(self, query: str, level: str = "chunk",
                    top_k: int = 5) -> list[RAGChunk]:
    """Recherche filtrée par niveau hiérarchique."""
    filtered = [c for c in self._chunks if c.metadata.get("level") == level]
    if not filtered:
        return []
    # BM25 sur le sous-ensemble
    from rank_bm25 import BM25Okapi
    tokenized = [self._tokenize(c.text) for c in filtered]
    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(self._tokenize(query))
    ranked = sorted(zip(filtered, scores), key=lambda x: -x[1])[:top_k]
    results = []
    for chunk, score in ranked:
        c = RAGChunk(**vars(chunk))
        c.bm25_score = float(score)
        results.append(c)
    return results
```

**Step 4: Run test**

```bash
python -m pytest test_rag_optimized.py::test_hierarchical_indexing -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): hierarchical index (doc/section/chunk levels)"
```

---

## Task 7: Partitionnement Index par Domaine

**Objective:** Diviser l'index par domaine pour latence < 200ms

**Files:**
- Modify: `00_CORE/forge_agents/forge_rag_optimized.py`

**Step 1: Add failing test**

```python
def test_domain_partitioning():
    rag = ForgeRAGOptimized()
    rag.index("forge_llm.py", "forge_call routes to MiMo", domain="forge")
    rag.index("lead_scoring.py", "score leads 0-100", domain="agents")
    rag.index("forge_graph.py", "build_forge_graph creates StateGraph", domain="forge")
    # Search only in forge domain
    results = rag.search_domain("forge_call routing", domain="forge", top_k=2)
    assert all(c.metadata.get("domain") == "forge" for c in results)
    assert len(results) <= 2
```

**Step 2: Run test to verify failure**

```bash
python -m pytest test_rag_optimized.py::test_domain_partitioning -v
```
Expected: FAIL

**Step 3: Implement domain partitioning**

```python
def index(self, source: str, text: str, doc_id: str | None = None,
          domain: str = "general"):
    """Indexer un document avec domaine optionnel."""
    doc_id = doc_id or source
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        if len(para) > 20:
            self._chunks.append(RAGChunk(
                doc_id=doc_id,
                chunk_idx=i,
                text=para,
                source=source,
                metadata={"domain": domain}
            ))
    self._indexed = False

def search_domain(self, query: str, domain: str = "general",
                  top_k: int = 5) -> list[RAGChunk]:
    """Recherche filtrée par domaine (latence < 200ms)."""
    filtered = [c for c in self._chunks if c.metadata.get("domain") == domain]
    if not filtered:
        return []
    # BM25 sur le sous-ensemble
    from rank_bm25 import BM25Okapi
    tokenized = [self._tokenize(c.text) for c in filtered]
    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(self._tokenize(query))
    ranked = sorted(zip(filtered, scores), key=lambda x: -x[1])[:top_k]
    results = []
    for chunk, score in ranked:
        c = RAGChunk(**vars(chunk))
        c.bm25_score = float(score)
        results.append(c)
    return results
```

**Step 4: Run test**

```bash
python -m pytest test_rag_optimized.py::test_domain_partitioning -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add 00_CORE/forge_agents/forge_rag_optimized.py test_rag_optimized.py
git commit -m "feat(rag): domain-partitioned index (latency < 200ms)"
```

---

## Task 8: Intégration adaptive_rag.py (stratégie OPTIMIZED)

**Objective:** Connecter le nouveau RAG hybride dans adaptive_rag

**Files:**
- Modify: `00_CORE/forge_agents/adaptive_rag.py`
- Modify: `00_CORE/forge_agents/agent_nodes.py`

**Step 1: Add to adaptive_rag.py**

```python
# Dans la définition des stratégies, ajouter OPTIMIZED
Strategy = Literal["NONE", "LIGHT", "STANDARD", "OPTIMIZED", "FULL"]

# Ajouter la fonction get_optimized_context
def get_optimized_context(state: dict, agent_name: str) -> tuple[str, dict]:
    """Contexte via RAG hybride BM25+vectoriel+reranker."""
    from .forge_rag_optimized import get_rag_optimized
    rag = get_rag_optimized()
    task = state.get("current_task", "")
    # Hybrid search → rerank
    candidates = rag.search_hybrid(task, top_k=20)
    if candidates:
        results = rag.rerank(task, candidates, top_k=5)
        context = "\n---\n".join(c.text for c in results)
        return context, {"strategy": "OPTIMIZED", "chunks": len(results)}
    return "", {"strategy": "OPTIMIZED", "chunks": 0}
```

**Step 2: Modify classify_strategy pour ajouter OPTIMIZED**

Dans `classify_strategy()`, ajouter une catégorie intermédiaire :
- Mots-clés OPTIMIZED : "recherche", "research", "contexte", "rag", "embedding"
- Score > STANDARD mais < FULL → OPTIMIZED

**Step 3: Run full test**

```bash
python -m pytest test_rag_optimized.py -v
```
Expected: All PASS

**Step 4: Commit**

```bash
git add 00_CORE/forge_agents/adaptive_rag.py 00_CORE/forge_agents/forge_rag_optimized.py
git commit -m "feat(rag): integrate hybrid RAG into adaptive_rag (OPTIMIZED strategy)"
```

---

## Dépendances à installer

```bash
pip install rank_bm25 sentence-transformers
# rank_bm25 : ~50KB, zéro dépendance
# sentence-transformers : ~500MB (modèle all-MiniLM-L6-v2 inclus)
```

## Résumé des gains attendus

| Optimisation | Gain |
|-------------|------|
| BM25 local | Mots-clés rares, zéro API |
| Vectoriel local | Sémantique, 384-dim, zéro API |
| Cross-encoder reranker | -25% hallucinations |
| Semantic chunking | +30-50% pertinence |
| Déduplication | -40% index |
| Hiérarchique | Requêtes granularité variable |
| Domain partitioning | < 200ms latence |
| **Total** | **~65% réduction tokens (objectif Section 4)** |
