"""
forge_rag_optimized.py — Full-featured RAG engine for Forge
============================================================
8 features in one clean module:
  1. BM25 search (rank_bm25, zero API)
  2. Vector search (transformers, all-MiniLM-L6-v2)
  3. Hybrid search (BM25*0.4 + vector*0.6, normalized)
  4. Cross-encoder reranker (ms-marco-MiniLM-L-6-v2, Top-20→Top-5)
  5. Semantic chunking (markdown headers + paragraphs, max 500 chars)
  6. Deduplication (SimHash from semantic_cache)
  7. Hierarchical indexing (doc/section/chunk, 3 levels)
  8. Domain partitioning (index per domain, search_domain)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from rank_bm25 import BM25Okapi

# Relative imports with CLI fallback
try:
    from .semantic_cache import _tokenize, _simhash, _hamming_similarity
except ImportError:
    from semantic_cache import _tokenize, _simhash, _hamming_similarity

logger = logging.getLogger("ForgeRAGOptimized")

FORGE_ROOT = Path(__file__).parent.parent.parent

# ─── RAGChunk dataclass ─────────────────────────────────────────────────────

@dataclass
class RAGChunk:
    doc_id: str
    chunk_idx: int
    text: str
    source: str
    bm25_score: float = 0.0
    vec_score: float = 0.0
    rerank_score: float = 0.0
    metadata: dict = field(default_factory=dict)

# ─── Semantic chunking ──────────────────────────────────────────────────────

def semantic_chunk(text: str, max_chars: int = 500) -> list[str]:
    """Split on markdown headers + paragraphs, max max_chars per chunk."""
    raw_parts = re.split(r'\n(?=#{1,6}\s)|\n\n+', text)
    chunks: list[str] = []
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            chunks.append(part)
        else:
            sentences = re.split(r'(?<=[.!?])\s+', part)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) + 1 <= max_chars:
                    current = (current + " " + sent).strip() if current else sent
                else:
                    if current:
                        chunks.append(current)
                    current = sent
            if current:
                chunks.append(current)
    return chunks

# ─── Bi-encoder wrapper (replaces SentenceTransformer) ──────────────────────

class _BiEncoder:
    """Thin wrapper around transformers AutoModel for sentence embeddings."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from transformers import AutoModel, AutoTokenizer
        logger.info("Loading bi-encoder: %s", model_name)
        self._tok = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModel.from_pretrained(model_name)
        self._model.eval()

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        all_embs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = self._tok(batch, return_tensors="pt", padding=True,
                               truncation=True, max_length=256)
            with torch.no_grad():
                out = self._model(**inputs)
            # Mean pooling over tokens (respect attention mask)
            mask = inputs["attention_mask"].unsqueeze(-1).float()
            emb = (out.last_hidden_state * mask).sum(1) / mask.sum(1)
            # L2 normalize
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            all_embs.append(emb.cpu().numpy())
        return np.vstack(all_embs).astype(np.float32)


class _CrossEncoder:
    """Thin wrapper around transformers AutoModel for cross-encoding."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        logger.info("Loading cross-encoder: %s", model_name)
        self._tok = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores = []
        for i in range(0, len(pairs), 32):
            batch = pairs[i : i + 32]
            texts_a = [p[0] for p in batch]
            texts_b = [p[1] for p in batch]
            inputs = self._tok(texts_a, texts_b, return_tensors="pt",
                               padding=True, truncation=True, max_length=256)
            with torch.no_grad():
                logits = self._model(**inputs).logits.squeeze(-1)
            scores.extend(logits.cpu().tolist())
        return scores

# ─── ForgeRAGOptimized ──────────────────────────────────────────────────────

class ForgeRAGOptimized:
    """Full-featured RAG engine with 8 optimization features."""

    def __init__(self):
        self._chunks: list[RAGChunk] = []
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_tokenized: list[list[str]] = []
        self._encoder: Optional[_BiEncoder] = None
        self._vectors: Optional[np.ndarray] = None
        self._reranker: Optional[_CrossEncoder] = None
        self._hierarchy: dict[str, dict] = {}
        self._domains: dict[str, list[int]] = {}
        self._signatures: list[int] = []
        logger.info("ForgeRAGOptimized initialized")

    # ─── Lazy model loaders ─────────────────────────────────────────────────

    def _get_encoder(self) -> _BiEncoder:
        if self._encoder is None:
            self._encoder = _BiEncoder()
        return self._encoder

    def _get_reranker(self) -> _CrossEncoder:
        if self._reranker is None:
            self._reranker = _CrossEncoder()
        return self._reranker

    # ─── 1. Index ───────────────────────────────────────────────────────────

    def index(self, source: str, text: str, domain: str = "forge",
              doc_id: Optional[str] = None) -> str:
        """Index a document: chunk → BM25 + vector. Returns doc_id."""
        if doc_id is None:
            doc_id = f"doc_{len(self._hierarchy)}"
        chunks = semantic_chunk(text)
        for i, chunk_text in enumerate(chunks):
            chunk = RAGChunk(
                doc_id=doc_id, chunk_idx=i, text=chunk_text,
                source=source, metadata={"domain": domain},
            )
            self._chunks.append(chunk)
            self._domains.setdefault(domain, []).append(len(self._chunks) - 1)
            self._signatures.append(_simhash(_tokenize(chunk_text)))
        self._rebuild_bm25()
        self._rebuild_vectors()
        logger.info("Indexed doc=%s source=%s chunks=%d domain=%s",
                     doc_id, source, len(chunks), domain)
        return doc_id

    def _rebuild_bm25(self):
        self._bm25_tokenized = [_tokenize(c.text) for c in self._chunks]
        self._bm25 = BM25Okapi(self._bm25_tokenized) if self._bm25_tokenized else None

    def _rebuild_vectors(self):
        if not self._chunks:
            self._vectors = None
            return
        enc = self._get_encoder()
        self._vectors = enc.encode([c.text for c in self._chunks])

    # ─── 2. BM25 search ────────────────────────────────────────────────────

    def search_bm25(self, query: str, top_k: int = 10) -> list[RAGChunk]:
        if self._bm25 is None or not self._chunks:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            c = self._clone_chunk(self._chunks[idx])
            c.bm25_score = float(scores[idx])
            results.append(c)
        return results

    # ─── 3. Vector search ──────────────────────────────────────────────────

    def search_vector(self, query: str, top_k: int = 10) -> list[RAGChunk]:
        if self._vectors is None or not self._chunks:
            return []
        enc = self._get_encoder()
        q_vec = enc.encode([query])
        scores = (self._vectors @ q_vec.T).flatten()
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            c = self._clone_chunk(self._chunks[idx])
            c.vec_score = float(scores[idx])
            results.append(c)
        return results

    # ─── 4. Hybrid search ──────────────────────────────────────────────────

    def search_hybrid(self, query: str, top_k: int = 10,
                      bm25_weight: float = 0.4,
                      vec_weight: float = 0.6) -> list[RAGChunk]:
        if not self._chunks:
            return []
        bm25_scores = self._bm25.get_scores(_tokenize(query)) if self._bm25 else np.zeros(len(self._chunks))
        if self._vectors is not None:
            enc = self._get_encoder()
            q_vec = enc.encode([query])
            vec_scores = (self._vectors @ q_vec.T).flatten()
        else:
            vec_scores = np.zeros(len(self._chunks))
        bm25_norm = self._normalize(bm25_scores)
        vec_norm = self._normalize(vec_scores)
        combined = bm25_weight * bm25_norm + vec_weight * vec_norm
        top_indices = np.argsort(combined)[::-1][:top_k]
        results = []
        for idx in top_indices:
            c = self._clone_chunk(self._chunks[idx])
            c.bm25_score = float(bm25_norm[idx])
            c.vec_score = float(vec_norm[idx])
            results.append(c)
        return results

    @staticmethod
    def _normalize(scores: np.ndarray) -> np.ndarray:
        mn, mx = scores.min(), scores.max()
        if mx - mn < 1e-10:
            return np.zeros_like(scores)
        return (scores - mn) / (mx - mn)

    # ─── 5. Cross-encoder reranker ─────────────────────────────────────────

    def rerank(self, query: str, chunks: list[RAGChunk],
               top_k: int = 5) -> list[RAGChunk]:
        if not chunks:
            return []
        reranker = self._get_reranker()
        pairs = [(query, c.text) for c in chunks]
        scores = reranker.predict(pairs)
        for c, s in zip(chunks, scores):
            c.rerank_score = float(s)
        chunks.sort(key=lambda c: c.rerank_score, reverse=True)
        return chunks[:top_k]

    # ─── 6. Deduplication ──────────────────────────────────────────────────

    def deduplicate(self, threshold: float = 0.95) -> int:
        """Remove near-duplicate chunks. Returns number removed."""
        if not self._signatures:
            return 0
        keep: list[int] = []
        for i, sig in enumerate(self._signatures):
            is_dup = any(
                _hamming_similarity(sig, self._signatures[j]) >= threshold
                for j in keep
            )
            if not is_dup:
                keep.append(i)
        removed = len(self._chunks) - len(keep)
        if removed == 0:
            return 0
        keep_set = set(keep)
        self._chunks = [c for i, c in enumerate(self._chunks) if i in keep_set]
        self._signatures = [s for i, s in enumerate(self._signatures) if i in keep_set]
        self._rebuild_domains()
        self._rebuild_bm25()
        self._rebuild_vectors()
        logger.info("Deduplication removed %d chunks", removed)
        return removed

    def _rebuild_domains(self):
        self._domains = {}
        for i, c in enumerate(self._chunks):
            domain = c.metadata.get("domain", "forge")
            self._domains.setdefault(domain, []).append(i)

    # ─── 7. Hierarchical indexing ──────────────────────────────────────────

    def index_hierarchical(self, source: str, text: str,
                           domain: str = "forge") -> str:
        """Index with 3-level hierarchy: doc → sections → chunks."""
        doc_id = self.index(source, text, domain)
        sections = re.split(r'\n(?=#{1,6}\s)', text)
        section_summaries: list[dict] = []
        chunk_offset = 0
        for sec_idx, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
            sec_chunks = semantic_chunk(section)
            section_summaries.append({
                "section_idx": sec_idx,
                "header": section.split('\n')[0][:200],
                "chunk_count": len(sec_chunks),
                "chunk_offset": chunk_offset,
                "summary": section[:300],
            })
            chunk_offset += len(sec_chunks)
        self._hierarchy[doc_id] = {
            "source": source,
            "domain": domain,
            "sections": section_summaries,
            "total_chunks": chunk_offset,
        }
        logger.info("Hierarchical index for doc=%s: %d sections, %d chunks",
                     doc_id, len(section_summaries), chunk_offset)
        return doc_id

    def search_by_level(self, query: str, level: str = "chunk",
                        top_k: int = 5) -> list[dict]:
        """Search at a specific hierarchy level (doc/section/chunk)."""
        if level == "chunk":
            results = self.search_hybrid(query, top_k=top_k)
            return [{"level": "chunk", "text": c.text, "source": c.source,
                     "score": c.bm25_score + c.vec_score,
                     "doc_id": c.doc_id, "chunk_idx": c.chunk_idx}
                    for c in results]
        elif level == "section":
            results = self.search_hybrid(query, top_k=top_k * 3)
            seen: dict[str, dict] = {}
            for c in results:
                for doc_id, hier in self._hierarchy.items():
                    if c.doc_id != doc_id:
                        continue
                    for sec in hier["sections"]:
                        off = sec["chunk_offset"]
                        end = off + sec["chunk_count"]
                        if off <= c.chunk_idx < end:
                            key = f"{doc_id}:{sec['section_idx']}"
                            if key not in seen:
                                seen[key] = {
                                    "level": "section",
                                    "header": sec["header"],
                                    "summary": sec["summary"],
                                    "source": c.source,
                                    "score": c.bm25_score + c.vec_score,
                                    "doc_id": doc_id,
                                }
                            else:
                                seen[key]["score"] = max(
                                    seen[key]["score"],
                                    c.bm25_score + c.vec_score)
                            break
                    break
            return sorted(seen.values(), key=lambda x: x["score"],
                          reverse=True)[:top_k]
        elif level == "doc":
            results = self.search_hybrid(query, top_k=top_k * 5)
            seen: dict[str, dict] = {}
            for c in results:
                if c.doc_id not in seen:
                    hier = self._hierarchy.get(c.doc_id, {})
                    seen[c.doc_id] = {
                        "level": "doc", "doc_id": c.doc_id,
                        "source": c.source,
                        "domain": hier.get("domain", "unknown"),
                        "total_chunks": hier.get("total_chunks", 0),
                        "score": c.bm25_score + c.vec_score,
                    }
                else:
                    seen[c.doc_id]["score"] = max(
                        seen[c.doc_id]["score"],
                        c.bm25_score + c.vec_score)
            return sorted(seen.values(), key=lambda x: x["score"],
                          reverse=True)[:top_k]
        else:
            logger.warning("Unknown level: %s", level)
            return []

    # ─── 8. Domain partitioning ────────────────────────────────────────────

    def search_domain(self, query: str, domain: str,
                      top_k: int = 5) -> list[RAGChunk]:
        """Search within a specific domain only."""
        indices = self._domains.get(domain, [])
        if not indices:
            return []
        bm25_scores = self._bm25.get_scores(_tokenize(query)) if self._bm25 else np.zeros(len(self._chunks))
        if self._vectors is not None:
            enc = self._get_encoder()
            q_vec = enc.encode([query])
            vec_scores = (self._vectors @ q_vec.T).flatten()
        else:
            vec_scores = np.zeros(len(self._chunks))
        domain_bm25 = np.array([bm25_scores[i] for i in indices])
        domain_vec = np.array([vec_scores[i] for i in indices])
        bm25_n = self._normalize(domain_bm25)
        vec_n = self._normalize(domain_vec)
        combined = 0.4 * bm25_n + 0.6 * vec_n
        top_local = np.argsort(combined)[::-1][:top_k]
        results = []
        for li in top_local:
            idx = indices[li]
            c = self._clone_chunk(self._chunks[idx])
            c.bm25_score = float(bm25_n[li])
            c.vec_score = float(vec_n[li])
            results.append(c)
        return results

    # ─── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _clone_chunk(c: RAGChunk) -> RAGChunk:
        return RAGChunk(
            doc_id=c.doc_id, chunk_idx=c.chunk_idx, text=c.text,
            source=c.source, bm25_score=c.bm25_score,
            vec_score=c.vec_score, rerank_score=c.rerank_score,
            metadata=dict(c.metadata),
        )

    def stats(self) -> dict:
        return {
            "total_chunks": len(self._chunks),
            "domains": {d: len(v) for d, v in self._domains.items()},
            "hierarchical_docs": len(self._hierarchy),
            "has_vectors": self._vectors is not None,
            "vector_dim": self._vectors.shape[1] if self._vectors is not None else 0,
        }

# ─── Singleton ──────────────────────────────────────────────────────────────

_RAG: Optional[ForgeRAGOptimized] = None

def get_rag_optimized() -> ForgeRAGOptimized:
    global _RAG
    if _RAG is None:
        _RAG = ForgeRAGOptimized()
    return _RAG
