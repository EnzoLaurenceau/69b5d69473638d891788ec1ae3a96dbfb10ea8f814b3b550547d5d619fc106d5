"""
dataset_rag.py — Live Dataset Retrieval for Forge Agents
=========================================================
Intègre les datasets téléchargés DIRECTEMENT dans le cerveau de la Forge.
Les agents piochent des exemples pertinents en temps réel (few-shot RAG).

AVANT : datasets = fichiers morts sur disque (juste pour fine-tuning)
APRÈS : datasets = mémoire vive de la Forge (retrieval temps réel)

Architecture :
  1. Au démarrage, indexe les datasets par catégorie/domaine (lazy, une seule fois)
  2. À chaque tâche agent, retrieve() retourne les N meilleurs exemples
  3. Les exemples sont injectés dans le contexte agent (via adaptive_rag)

Stratégie d'indexation (1.1M+ rows → index léger) :
  - Pas de vectorisation (trop cher pour 1.1M rows)
  - Index par catégorie + sampling représentatif
  - Keyword matching TF-IDF-like sur l'index
  - Cache LRU pour les requêtes fréquentes

Usage :
  from forge_agents.dataset_rag import get_dataset_rag
  rag = get_dataset_rag()
  examples = rag.retrieve("build a REST API with FastAPI", top_k=3)
  # → retourne 3 exemples de code instruction les plus pertinents
"""

from __future__ import annotations

import json
import hashlib
import logging
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("DatasetRAG")

FORGE_ROOT = Path(__file__).parent.parent.parent
DATASETS_ROOT = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "datasets"
INDEX_CACHE = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "dataset_rag_index.json"

# ─── Config ──────────────────────────────────────────────────────────────────

MAX_EXAMPLES_PER_CATEGORY = 50      # Sample N examples per category for index
MAX_CONTEXT_CHARS = 1500            # Max chars injected into agent context
MAX_EXAMPLE_LEN = 500               # Truncate individual examples
CACHE_TTL = 300                     # Cache results for 5 minutes


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class RetrievedExample:
    """Un exemple récupéré du dataset."""
    source: str              # dataset slug
    category: str            # category/domain
    instruction: str         # user message
    response: str            # assistant response
    relevance_score: float   # 0.0-1.0
    
    def to_context(self, max_len: int = MAX_EXAMPLE_LEN) -> str:
        """Formate l'exemple pour injection dans le contexte agent."""
        inst = self.instruction[:max_len // 2]
        resp = self.response[:max_len // 2]
        return f"[{self.source}/{self.category}] Q: {inst}\nA: {resp}"


@dataclass
class CategoryIndex:
    """Index d'une catégorie de données."""
    name: str
    keywords: set[str] = field(default_factory=set)
    examples: list[dict] = field(default_factory=list)  # sampled examples
    total_rows: int = 0
    source: str = ""


# ─── KEYWORD EXTRACTION ─────────────────────────────────────────────────────

_STOPS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "les", "des", "pour", "dans", "que", "qui", "une", "est", "pas",
    "sur", "avec", "plus", "son", "ses", "cette", "par", "mais",
    "and", "but", "or", "if", "this", "that", "it", "its", "my", "your",
    "his", "her", "our", "their", "what", "which", "who", "whom",
    "you", "me", "him", "them", "we", "they", "she", "he",
    "write", "create", "make", "build", "implement", "using", "use",
})

def _tokenize(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return [w for w in words if w not in _STOPS]


def _keyword_overlap(query_tokens: set[str], target_keywords: set[str]) -> float:
    """Jaccard-like similarity between query and category keywords."""
    if not query_tokens or not target_keywords:
        return 0.0
    intersection = query_tokens & target_keywords
    # Weighted: more intersection = better, but normalize by query size
    # (we want categories that cover the query, not the other way around)
    if not intersection:
        return 0.0
    return len(intersection) / len(query_tokens)


# ─── DATASET RAG ENGINE ─────────────────────────────────────────────────────

class DatasetRAG:
    """
    Live retrieval engine for Forge datasets.
    Indexes datasets by category, retrieves relevant examples at query time.
    """

    def __init__(self):
        self._categories: list[CategoryIndex] = []
        self._indexed = False
        self._cache: dict[str, tuple[float, list[RetrievedExample]]] = {}
        self._index_time: float = 0.0

    # ── INDEX ─────────────────────────────────────────────────────────────────

    def _ensure_indexed(self) -> None:
        """Lazy-index all datasets on first use."""
        if self._indexed:
            return

        t0 = time.time()
        logger.info("[DatasetRAG] Indexing datasets...")

        # Try loading cached index first
        if INDEX_CACHE.exists():
            try:
                cached = json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
                if time.time() - cached.get("indexed_at", 0) < 86400:  # 24h cache
                    self._categories = [
                        CategoryIndex(
                            name=c["name"],
                            keywords=set(c["keywords"]),
                            examples=c["examples"],
                            total_rows=c["total_rows"],
                            source=c["source"],
                        )
                        for c in cached.get("categories", [])
                    ]
                    self._indexed = True
                    self._index_time = time.time() - t0
                    logger.info(f"[DatasetRAG] Loaded cached index: {len(self._categories)} categories ({self._index_time:.1f}s)")
                    return
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Index each dataset
        for dataset_dir in DATASETS_ROOT.iterdir():
            if not dataset_dir.is_dir():
                continue
            chatml_path = dataset_dir / "chatml.jsonl"
            if not chatml_path.exists():
                continue
            
            slug = dataset_dir.name
            self._index_dataset(slug, chatml_path)

        # Save cache
        self._save_index_cache()
        self._indexed = True
        self._index_time = time.time() - t0
        logger.info(f"[DatasetRAG] Indexed {len(self._categories)} categories ({self._index_time:.1f}s)")

    def _index_dataset(self, slug: str, chatml_path: Path) -> None:
        """Index a single dataset by extracting categories and sampling examples."""
        categories: dict[str, list[dict]] = defaultdict(list)
        all_keywords: dict[str, set[str]] = defaultdict(set)

        # Read metadata for category info
        meta_path = chatml_path.parent / "metadata.json"
        has_categories = False
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if "category" in meta.get("columns", []):
                    has_categories = True
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Scan dataset
        row_count = 0
        with open(chatml_path, "r", encoding="utf-8") as f:
            for line in f:
                row_count += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                messages = row.get("messages", [])
                if len(messages) < 2:
                    continue

                # Extract instruction and response
                instruction = ""
                response = ""
                for m in messages:
                    if m.get("role") == "user" and not instruction:
                        instruction = m.get("content", "")
                    elif m.get("role") == "assistant" and not response:
                        response = m.get("content", "")

                if not instruction or not response:
                    continue

                # Determine category
                if has_categories:
                    # Try to get category from raw data
                    raw_path = chatml_path.parent / "raw.jsonl"
                    # We'll use instruction-based categorization instead for efficiency
                    category = self._auto_categorize(instruction, slug)
                else:
                    category = self._auto_categorize(instruction, slug)

                # Collect keywords from instruction
                tokens = _tokenize(instruction)
                all_keywords[category].update(tokens[:20])

                # Store example (will be sampled later)
                categories[category].append({
                    "instruction": instruction[:300],
                    "response": response[:300],
                })

        # Sample and create category indices
        for cat_name, examples in categories.items():
            sampled = random.sample(examples, min(MAX_EXAMPLES_PER_CATEGORY, len(examples)))
            self._categories.append(CategoryIndex(
                name=cat_name,
                keywords=all_keywords.get(cat_name, set()),
                examples=sampled,
                total_rows=len(examples),
                source=slug,
            ))

        logger.info(f"  [{slug}] {row_count} rows → {len(categories)} categories")

    def _auto_categorize(self, instruction: str, dataset_slug: str) -> str:
        """Auto-categorize an instruction by keywords."""
        text = instruction.lower()

        # Coding categories
        if any(kw in text for kw in ("python", "django", "flask", "fastapi", "pip")):
            return f"{dataset_slug}/python"
        if any(kw in text for kw in ("javascript", "typescript", "react", "vue", "node", "npm", "next")):
            return f"{dataset_slug}/javascript"
        if any(kw in text for kw in ("html", "css", "tailwind", "frontend", "ui", "design")):
            return f"{dataset_slug}/frontend"
        if any(kw in text for kw in ("api", "rest", "graphql", "endpoint", "backend", "server")):
            return f"{dataset_slug}/api"
        if any(kw in text for kw in ("database", "sql", "postgres", "mongo", "redis", "query")):
            return f"{dataset_slug}/database"
        if any(kw in text for kw in ("docker", "kubernetes", "deploy", "ci/cd", "devops", "cloud")):
            return f"{dataset_slug}/devops"
        if any(kw in text for kw in ("test", "debug", "fix", "error", "bug", "exception")):
            return f"{dataset_slug}/debug"
        if any(kw in text for kw in ("security", "auth", "encrypt", "token", "jwt", "oauth")):
            return f"{dataset_slug}/security"
        if any(kw in text for kw in ("machine learning", "model", "train", "neural", "ai", "llm")):
            return f"{dataset_slug}/ml"

        # Metacognition categories
        if any(kw in text for kw in ("think", "reason", "reflect", "analyze", "evaluate")):
            return f"{dataset_slug}/reasoning"
        if any(kw in text for kw in ("plan", "strategy", "approach", "method", "step")):
            return f"{dataset_slug}/planning"

        # General
        if any(kw in text for kw in ("explain", "describe", "what is", "how does")):
            return f"{dataset_slug}/explanation"
        if any(kw in text for kw in ("write", "generate", "create", "compose")):
            return f"{dataset_slug}/generation"

        return f"{dataset_slug}/general"

    def _save_index_cache(self) -> None:
        """Save index to disk for fast reload."""
        try:
            cache_data = {
                "indexed_at": time.time(),
                "categories": [
                    {
                        "name": c.name,
                        "keywords": list(c.keywords)[:100],  # Limit keywords per category
                        "examples": c.examples[:MAX_EXAMPLES_PER_CATEGORY],
                        "total_rows": c.total_rows,
                        "source": c.source,
                    }
                    for c in self._categories
                ],
            }
            INDEX_CACHE.write_text(
                json.dumps(cache_data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[DatasetRAG] Cache save failed: {e}")

    # ── RETRIEVE ──────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 3,
                 max_chars: int = MAX_CONTEXT_CHARS) -> list[RetrievedExample]:
        """
        Retrieve the most relevant examples for a query.
        Used by agents at execution time for few-shot learning.
        """
        self._ensure_indexed()

        if not self._categories:
            return []

        # Check cache
        cache_key = hashlib.md5(f"{query}:{top_k}".encode()).hexdigest()
        if cache_key in self._cache:
            cached_time, cached_results = self._cache[cache_key]
            if time.time() - cached_time < CACHE_TTL:
                return cached_results

        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return []

        # Score each category
        scored_categories: list[tuple[float, CategoryIndex]] = []
        for cat in self._categories:
            score = _keyword_overlap(query_tokens, cat.keywords)
            if score > 0:
                scored_categories.append((score, cat))

        # Sort by relevance
        scored_categories.sort(key=lambda x: x[0], reverse=True)

        # Collect examples from top categories
        results: list[RetrievedExample] = []
        total_chars = 0

        for score, cat in scored_categories[:top_k * 2]:  # Check more cats than needed
            if len(results) >= top_k:
                break

            # Pick the best matching example from this category
            best_example = None
            best_score = 0.0

            for ex in cat.examples:
                ex_tokens = set(_tokenize(ex.get("instruction", "")))
                ex_score = _keyword_overlap(query_tokens, ex_tokens)
                if ex_score > best_score:
                    best_score = ex_score
                    best_example = ex

            if best_example:
                example = RetrievedExample(
                    source=cat.source,
                    category=cat.name,
                    instruction=best_example["instruction"],
                    response=best_example["response"],
                    relevance_score=score * 0.6 + best_score * 0.4,
                )
                ctx = example.to_context()
                if total_chars + len(ctx) <= max_chars:
                    results.append(example)
                    total_chars += len(ctx)

        # Cache results
        self._cache[cache_key] = (time.time(), results)
        return results

    def retrieve_for_context(self, query: str, top_k: int = 3,
                             max_chars: int = MAX_CONTEXT_CHARS) -> str:
        """
        Retrieve and format examples as injectable context string.
        This is the main interface used by adaptive_rag.py.
        """
        examples = self.retrieve(query, top_k, max_chars)
        if not examples:
            return ""

        lines = ["[DatasetRAG/Few-Shot Examples]"]
        for i, ex in enumerate(examples, 1):
            lines.append(f"--- Example {i} ({ex.source}, relevance={ex.relevance_score:.0%}) ---")
            lines.append(f"Q: {ex.instruction}")
            lines.append(f"A: {ex.response}")
        
        return "\n".join(lines)

    # ── STATS ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        self._ensure_indexed()
        return {
            "categories": len(self._categories),
            "total_examples_indexed": sum(len(c.examples) for c in self._categories),
            "total_rows_covered": sum(c.total_rows for c in self._categories),
            "sources": list(set(c.source for c in self._categories)),
            "index_time_s": self._index_time,
            "cache_entries": len(self._cache),
            "top_categories": [
                {"name": c.name, "examples": len(c.examples), "total": c.total_rows}
                for c in sorted(self._categories, key=lambda x: x.total_rows, reverse=True)[:10]
            ],
        }

    def invalidate_cache(self) -> None:
        """Force re-index on next use."""
        self._cache.clear()
        self._categories.clear()
        self._indexed = False
        if INDEX_CACHE.exists():
            INDEX_CACHE.unlink()


# ═══════════════════════════════════════════════════════════════════════════
# DATASET QUALITY — vague AAOS (items 92/94/95/96/98/100/101)
# 09_TASKS/aaos_devops_plan.md — health check, acceptance policy,
# dataset memory, regression guard, knowledge gaps.
# Protocole DATASETS (CLAUDE.md) respecté : AUCUN téléchargement automatique,
# le trigger enregistre le gap et la recommandation pour validation user.
# ═══════════════════════════════════════════════════════════════════════════

DATASET_MEMORY_PATH = DATASETS_ROOT / "dataset_memory.json"
KNOWLEDGE_GAPS_PATH = DATASETS_ROOT / "knowledge_gaps.json"

QUALITY_ACCEPT = 80.0      # item 96 : ≥ 80 accepté
QUALITY_QUARANTINE = 60.0  # 60-80 quarantaine (validation humaine), < 60 rejeté
FRESHNESS_MAX_DAYS = 365   # au-delà, score fraîcheur = 0


def _read_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def health_check(dataset_dir: Path | str) -> dict:
    """
    Items 94/95/96 : santé d'un dataset AVANT usage/ingestion.
    Scanne chatml.jsonl + metadata.json → métriques + quality_score 0-100 + décision.
    Déterministe, 0 token.
    """
    dataset_dir = Path(dataset_dir)
    chatml = dataset_dir / "chatml.jsonl"
    if not chatml.exists():
        return {"dataset": dataset_dir.name, "quality_score": 0.0,
                "decision": "rejected", "error": "chatml.jsonl absent"}

    total = complete = 0
    seen_hashes: set[str] = set()
    duplicates = 0
    with open(chatml, "r", encoding="utf-8") as f:
        for line in f:
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs = row.get("messages", [])
            inst = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
            resp = next((m.get("content", "") for m in msgs if m.get("role") == "assistant"), "")
            if inst.strip() and resp.strip():
                complete += 1
                h = hashlib.md5(inst.strip().encode()).hexdigest()
                if h in seen_hashes:
                    duplicates += 1
                else:
                    seen_hashes.add(h)

    completeness = complete / total if total else 0.0
    dup_ratio = duplicates / complete if complete else 0.0
    consistency = 1.0 - dup_ratio

    age_days = (time.time() - chatml.stat().st_mtime) / 86400
    freshness = max(0.0, 1.0 - age_days / FRESHNESS_MAX_DAYS)

    meta = _read_json(dataset_dir / "metadata.json", {})
    license_ok = bool(meta.get("license"))
    trust = 1.0 if meta.get("source") else 0.5
    documented = 1.0 if meta else 0.0

    # Item 95 — score pondéré (label_quality≈completeness, bias non mesurable → neutre 0.5)
    quality_score = round(100 * (
        0.2 * completeness +
        0.15 * consistency +
        0.15 * freshness +
        0.15 * trust +
        0.15 * completeness +       # label quality proxy
        0.1 * 0.5 +                 # bias : neutre sans labels
        0.1 * documented
    ), 1)

    # Item 96 — acceptance policy
    if quality_score >= QUALITY_ACCEPT:
        decision = "accepted"
    elif quality_score >= QUALITY_QUARANTINE:
        decision = "quarantine"     # validation humaine requise
    else:
        decision = "rejected"

    return {
        "dataset": dataset_dir.name,
        "total_rows": total,
        "completeness": round(completeness, 3),
        "duplicates": duplicates,
        "consistency": round(consistency, 3),
        "freshness": round(freshness, 3),
        "license": meta.get("license", ""),
        "license_ok": license_ok,
        "source_trust": trust,
        "quality_score": quality_score,
        "decision": decision,
    }


def register_dataset(slug: str, source: str = "", license: str = "",
                     version: str = "1.0", performance_gain: float = 0.0) -> dict:
    """Item 100 : mémoire des datasets (id, source, score, licence, usage)."""
    mem = _read_json(DATASET_MEMORY_PATH, {})
    hc = health_check(DATASETS_ROOT / slug)
    entry = mem.get(slug, {"usage_count": 0, "date_added": time.strftime("%Y-%m-%d")})
    entry.update({
        "dataset_id": slug,
        "source": source or entry.get("source", ""),
        "quality_score": hc["quality_score"],
        "decision": hc["decision"],
        "version": version,
        "license": license or hc.get("license", ""),
        "performance_gain": performance_gain,
    })
    mem[slug] = entry
    _write_json(DATASET_MEMORY_PATH, mem)
    return entry


def bump_dataset_usage(slug: str) -> None:
    mem = _read_json(DATASET_MEMORY_PATH, {})
    if slug in mem:
        mem[slug]["usage_count"] = mem[slug].get("usage_count", 0) + 1
        _write_json(DATASET_MEMORY_PATH, mem)


def benchmark_retrieval(queries: list[str]) -> float:
    """Relevance moyenne du top-1 retrieval sur un set de questions fixe.
    Sert de benchmark déterministe (0 token) au regression guard."""
    rag = get_dataset_rag()
    scores = []
    for q in queries:
        res = rag.retrieve(q, top_k=1)
        scores.append(res[0].relevance_score if res else 0.0)
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def regression_guard(before: float, after: float, tolerance: float = 0.05) -> dict:
    """Item 101 : un nouveau dataset ne doit pas dégrader le benchmark.
    Usage : b = benchmark_retrieval(Q) → ingérer → a = benchmark_retrieval(Q)
            → regression_guard(b, a). regression=True → rollback l'ingestion."""
    regression = after < before - tolerance
    return {
        "before": before,
        "after": after,
        "delta": round(after - before, 4),
        "regression": regression,
        "verdict": "ROLLBACK" if regression else "KEEP",
    }


def record_knowledge_gap(task: str, score: float, agent: str = "") -> dict:
    """
    Items 92/98 : trigger Data Acquisition quand quality_score < seuil.
    N'ingère et ne télécharge RIEN (protocole DATASETS : prévenir le user
    d'abord) — enregistre le gap + une recommandation actionnable.
    """
    gaps = _read_json(KNOWLEDGE_GAPS_PATH, [])
    gap = {
        "task": task[:300],
        "score": score,
        "agent": agent,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "recommendation": ("chercher un dataset (awesome-public-datasets / HuggingFace) "
                           "couvrant cette tâche, valider via health_check() avant ingestion"),
        "status": "pending_user_approval",
    }
    gaps.append(gap)
    _write_json(KNOWLEDGE_GAPS_PATH, gaps[-200:])
    logger.warning(f"[DataAcquisition] Gap enregistré (score={score}) : {task[:80]}")
    return gap


# ─── Singleton ───────────────────────────────────────────────────────────────

_rag: Optional[DatasetRAG] = None


def get_dataset_rag() -> DatasetRAG:
    global _rag
    if _rag is None:
        _rag = DatasetRAG()
    return _rag


# ─── CLI TEST ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    rag = get_dataset_rag()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "build a FastAPI REST API with PostgreSQL"

    print(f"Query: {query}\n")
    ctx = rag.retrieve_for_context(query, top_k=3)
    print(ctx or "(no results)")
    print(f"\nStats: {json.dumps(rag.stats(), indent=2)}")
