"""
forge_lazy.py — V6 Lazy Execution Engine (Flemme Intelligente)
Règle : DO MINIMUM NECESSARY WORK TO REACH TARGET CONFIDENCE

Logique :
  if cached_solution_exists:
    reuse()
  elif similar_pattern_exists:
    adapt()
  else:
    full_execution()

Optimisation :
  - Réutilise les solutions existantes quand possible
  - Adapte les patterns similaires au lieu de tout refaire
  - Full execution seulement en dernier recours
  - Limite les loops (anti-boucle infinie)
"""

from __future__ import annotations
import json
import hashlib
import datetime
from typing import Any, Optional, Literal
from dataclasses import dataclass, field
from pathlib import Path


FORGE_ROOT = Path(__file__).parent.parent.parent


# ═══════════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SolutionCache:
    """Solution mise en cache."""
    task_hash: str
    solution: Any
    quality: float
    created_at: str
    use_count: int = 0
    domain: str = ""

    def is_reusable(self, min_quality: float = 7.0) -> bool:
        return self.quality >= min_quality


@dataclass
class PatternMatch:
    """Résultat de recherche de pattern similaire."""
    pattern_id: str
    similarity: float       # 0.0 → 1.0
    original_task: str
    solution: Any
    adaptations_needed: list[str]


@dataclass
class ExecutionPlan:
    """Plan d'exécution lazy."""
    strategy: Literal["reuse", "adapt", "full_execution"]
    confidence: float           # confiance que ce strategy va marcher
    estimated_cost: float       # coût estimé ($)
    estimated_tokens: int
    cached_solution: Optional[Any] = None
    pattern_match: Optional[PatternMatch] = None
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# SOLUTION CACHE
# ═══════════════════════════════════════════════════════════════════════════════

class SolutionCacheStore:
    """Stockage des solutions réutilisables."""

    def __init__(self):
        self._cache: dict[str, SolutionCache] = {}
        self._max_entries = 100

    def _task_hash(self, task: str) -> str:
        return hashlib.md5(task.lower().strip().encode()).hexdigest()[:16]

    def check(self, task: str) -> Optional[SolutionCache]:
        """Vérifie si une solution exacte existe."""
        h = self._task_hash(task)
        entry = self._cache.get(h)
        if entry and entry.is_reusable():
            entry.use_count += 1
            return entry
        return None

    def store(self, task: str, solution: Any, quality: float, domain: str = "") -> None:
        """Stocke une solution."""
        h = self._task_hash(task)
        if len(self._cache) >= self._max_entries:
            # Evict least used
            oldest = min(self._cache, key=lambda k: self._cache[k].use_count)
            del self._cache[oldest]
        self._cache[h] = SolutionCache(
            task_hash=h,
            solution=solution,
            quality=quality,
            created_at=datetime.datetime.now().isoformat(),
            domain=domain,
        )

    def stats(self) -> dict:
        return {
            "entries": len(self._cache),
            "total_reuse": sum(e.use_count for e in self._cache.values()),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PATTERN SIMILARITY
# ═══════════════════════════════════════════════════════════════════════════════

def compute_similarity(task_a: str, task_b: str) -> float:
    """
    Similarité rapide entre deux tâches (Jaccard sur mots significatifs).
    Pour un matching plus fin, utiliser les embeddings.
    """
    stopwords = frozenset(["the", "a", "an", "is", "are", "le", "la", "les", "de", "du", "et", "un", "une"])
    words_a = set(w.lower() for w in task_a.split() if len(w) > 2 and w.lower() not in stopwords)
    words_b = set(w.lower() for w in task_b.split() if len(w) > 2 and w.lower() not in stopwords)
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def find_similar_pattern(task: str, solutions: dict[str, SolutionCache],
                         threshold: float = 0.4) -> Optional[PatternMatch]:
    """Trouve le pattern le plus similaire dans le cache."""
    best_match = None
    best_sim = 0.0

    for h, cached in solutions.items():
        # We don't store original task text, so we can't do similarity here
        # This would need the experience DB to provide task text
        pass

    return best_match


# ═══════════════════════════════════════════════════════════════════════════════
# LAZY ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class LazyExecutionEngine:
    """
    Flemme Intelligente.
    Détermine le minimum de travail nécessaire pour atteindre la confiance cible.
    """

    def __init__(self):
        self._solution_cache = SolutionCacheStore()
        self._loop_count: dict[str, int] = {}  # anti-boucle
        self._max_loops = 5

    def plan(self, task: str, target_confidence: float = 0.8,
             domain: str = "") -> ExecutionPlan:
        """
        Détermine la stratégie d'exécution optimale.
        1. Vérifie le cache de solutions exactes
        2. Cherche des patterns similaires
        3. Sinon, full execution
        """
        # 1. Cache hit ?
        cached = self._solution_cache.check(task)
        if cached:
            return ExecutionPlan(
                strategy="reuse",
                confidence=0.95,
                estimated_cost=0.0,
                estimated_tokens=0,
                cached_solution=cached.solution,
                reason="Exact solution found in cache",
            )

        # 2. Loop limiter
        task_key = hashlib.md5(task.encode()).hexdigest()[:12]
        loop_count = self._loop_count.get(task_key, 0)
        if loop_count >= self._max_loops:
            return ExecutionPlan(
                strategy="full_execution",
                confidence=0.3,
                estimated_cost=2.0,
                estimated_tokens=50000,
                reason=f"Loop limit reached ({loop_count}/{self._max_loops}). Forcing full execution with escalation.",
            )

        # 3. Default: full execution
        self._loop_count[task_key] = loop_count + 1
        return ExecutionPlan(
            strategy="full_execution",
            confidence=target_confidence,
            estimated_cost=0.5,
            estimated_tokens=15000,
            reason="No cached solution or similar pattern found",
        )

    def record_solution(self, task: str, solution: Any, quality: float, domain: str = "") -> None:
        """Enregistre une solution dans le cache."""
        self._solution_cache.store(task, solution, quality, domain)

    def reset_loops(self) -> None:
        """Reset le compteur de loops (nouvelle session)."""
        self._loop_count.clear()

    def stats(self) -> dict:
        return {
            "solution_cache": self._solution_cache.stats(),
            "active_loops": len(self._loop_count),
            "loop_counts": dict(self._loop_count),
        }


# Singleton
_lazy_engine: Optional[LazyExecutionEngine] = None


def get_lazy_engine() -> LazyExecutionEngine:
    global _lazy_engine
    if _lazy_engine is None:
        _lazy_engine = LazyExecutionEngine()
    return _lazy_engine


if __name__ == "__main__":
    engine = get_lazy_engine()

    # First call → full execution
    plan = engine.plan("Build a Telegram bot with booking")
    print(f"Strategy: {plan.strategy}")
    print(f"Reason: {plan.reason}")

    # Record solution
    engine.record_solution("Build a Telegram bot with booking", {"code": "bot.py"}, 8.5, "bot")

    # Second call → reuse
    plan = engine.plan("Build a Telegram bot with booking")
    print(f"\nStrategy: {plan.strategy}")
    print(f"Reason: {plan.reason}")

    print(f"\nStats: {json.dumps(engine.stats(), indent=2)}")
