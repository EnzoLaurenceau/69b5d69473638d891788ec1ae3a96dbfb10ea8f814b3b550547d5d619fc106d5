"""
forge_cache_orchestrator.py — Cache/Memory Orchestrator (V6.1)
================================================================
Point d'entrée UNIQUE pour toute décision de cache dans la Forge.
Implémente le principe de la session de design (ChatGPT, 2026-07) :
    "Cache = mémoire calculée" — traçable, invalidable, versionné,
    lié au graphe de connaissance. PAS un Redis amélioré.

Ne réinvente rien (règle DO NOT INVENT du CLAUDE.md) : compose les
modules dormants déjà écrits au lieu d'en ajouter des concurrents.

    Couche | Backing réel                              | Statut avant ce fichier
    -------|-------------------------------------------|------------------------
    L0     | forge_kernel (kernel courant, in-process)  | câblé (v6_init_node)
    L1     | forge_shared_brain.MCPProxyCache (RAM)     | câblé mais non persistant
    L2     | turbovec_brain (semantic, 4-bit)           | câblé mais find_similar_pattern
           |                                             | de forge_lazy était un stub mort
    L3     | forge_db (Postgres+pgvector / SQLite/JSON) | câblé, health() dégradé OK
    L4     | GitNexus (.gitnexus/) via forge_db.sync_*  | câblé, on-demand

Ce module ajoute ce qui manquait réellement :
  1. Une cascade de décision EXPLICITE (exact → sémantique → recompute → compute),
     alors qu'avant chaque couche décidait dans son coin.
  2. Un vrai substitut à find_similar_pattern() (mort dans forge_lazy.py) via
     turbovec_brain.search() — dégradation gracieuse si turbovec est absent.
  3. Une invalidation PAR ÉVÉNEMENT (pas de TTL global) via un compteur de
     génération par domaine — "toujours réévalué par confiance + version + contexte".
  4. Une trace L3 (table cache_entries) pour que chaque cache soit audit-able :
     qui l'a créé, pour quel agent/domaine, avec quelle confiance.

Usage :
    from forge_agents.forge_cache_orchestrator import get_cache_orchestrator
    orch = get_cache_orchestrator()

    decision = orch.decide("build a telegram booking bot", domain="bot")
    if decision.strategy in ("exact", "semantic"):
        result = decision.result          # réutilisation, zéro recompute
    else:
        result = do_the_real_work()
        orch.record(query, result, quality=8.5, agent="BUILDER", domain="bot")

    orch.invalidate("dependency_update", domain="bot")   # ciblé, pas global
    orch.stats()                                          # observabilité unifiée
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("forge_cache_orchestrator")

FORGE_ROOT = Path(__file__).parent.parent.parent


def GEN_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("cache_generations.json")


# Seuil de similarité sémantique par défaut — cf. spec: "si similarité > threshold -> skip compute"
SEMANTIC_THRESHOLD_DEFAULT = 0.85

Strategy = Literal["exact", "semantic", "recompute", "compute"]


@dataclass
class CacheDecision:
    """Résultat de orchestrator.decide() — ce que l'appelant doit faire."""
    strategy: Strategy
    confidence: float
    result: Optional[Any] = None
    source_layer: str = ""       # "L0_lazy_exact" | "L2_turbovec_semantic" | ""
    reason: str = ""
    similarity: float = 0.0
    generation_mismatch: bool = False


# ─── Génération par domaine (invalidation ciblée, pas de TTL global) ──────────

class GenerationStore:
    """
    Compteur de génération par domaine. Une entrée cachée est valide seulement
    si sa génération == génération courante du domaine au moment du decide().
    Invalider un domaine = incrémenter sa génération (O(1), pas de scan/delete).
    """

    def __init__(self):
        self._gens: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        try:
            if GEN_PATH().exists():
                self._gens = json.loads(GEN_PATH().read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"[cache_orch] generation load: {e}")

    def _save(self) -> None:
        try:
            GEN_PATH().parent.mkdir(parents=True, exist_ok=True)
            GEN_PATH().write_text(json.dumps(self._gens, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[cache_orch] generation save: {e}")

    def current(self, domain: str) -> int:
        return self._gens.get(domain or "_global", 0)

    def bump(self, domain: str) -> int:
        key = domain or "_global"
        self._gens[key] = self._gens.get(key, 0) + 1
        self._save()
        return self._gens[key]


# ─── Orchestrator ──────────────────────────────────────────────────────────────

class CacheOrchestrator:
    """
    Cascade de décision unique pour tous les agents/nodes de la Forge.

    Logique (spec utilisateur) :
        if exact_match_cache:            -> "exact"     (reuse, confiance max)
        if semantic_match > threshold:   -> "semantic"   (reuse compressé)
        if outdated (génération périmée):-> "recompute"  (appelant doit recalculer + record)
        else:                            -> "compute"    (rien en cache, calcul plein)
    """

    def __init__(self, semantic_threshold: float = SEMANTIC_THRESHOLD_DEFAULT):
        self.semantic_threshold = semantic_threshold
        self.generations = GenerationStore()
        self._entry_generation: dict[str, int] = {}   # task_hash -> génération au moment du record

        # Lazy imports : chaque couche est optionnelle, dégradation gracieuse.
        self._lazy = None
        self._turbovec = None
        self._mcp_cache = None
        self._db = None
        self._init_layers()

    def _init_layers(self) -> None:
        try:
            from .forge_lazy import get_lazy_engine
            self._lazy = get_lazy_engine()
        except Exception as e:
            logger.warning(f"[cache_orch] L0/exact indisponible: {e}")

        try:
            from .turbovec_brain import get_turbovec_brain
            self._turbovec = get_turbovec_brain()
        except Exception as e:
            logger.info(f"[cache_orch] L2/sémantique (turbovec) indisponible, "
                        f"cascade dégradée à exact-only : {e}")

        try:
            from .forge_shared_brain import get_mcp_cache
            self._mcp_cache = get_mcp_cache()
        except Exception as e:
            logger.debug(f"[cache_orch] L1/MCPProxyCache indisponible: {e}")

        try:
            from .forge_db import get_db
            self._db = get_db()
            self._ensure_cache_table()
        except Exception as e:
            logger.debug(f"[cache_orch] L3/forge_db indisponible: {e}")

    def _ensure_cache_table(self) -> None:
        """Table de trace L3 — audit qui/quand/confiance. No-op si PG down (fallback JSON gère déjà)."""
        if not self._db or not getattr(self._db, "pg_ok", False):
            return
        try:
            with self._db._pg.cursor() as cur:  # noqa: SLF001 — façade interne assumée, même module family
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        id TEXT PRIMARY KEY, domain TEXT, agent TEXT,
                        confidence REAL, generation INT, ts DOUBLE PRECISION,
                        summary TEXT
                    );
                """)
        except Exception as e:
            logger.debug(f"[cache_orch] _ensure_cache_table: {e}")

    @staticmethod
    def _task_hash(query: str) -> str:
        return hashlib.md5(query.lower().strip().encode()).hexdigest()[:16]

    # ── Décision ─────────────────────────────────────────────────────────────

    def decide(self, query: str, domain: str = "") -> CacheDecision:
        """Cascade complète. Ne calcule jamais rien elle-même — dit juste quoi faire."""
        task_hash = self._task_hash(query)
        current_gen = self.generations.current(domain)

        # 1. Exact match (L0 — forge_lazy.SolutionCacheStore)
        if self._lazy is not None:
            cached = self._lazy._solution_cache.check(query)  # noqa: SLF001
            if cached is not None:
                entry_gen = self._entry_generation.get(task_hash, 0)
                if entry_gen >= current_gen:
                    return CacheDecision(
                        strategy="exact", confidence=0.95, result=cached.solution,
                        source_layer="L0_lazy_exact", reason="Exact match trouvé, génération à jour.",
                    )
                # Génération périmée : le hit exact existe mais est daté -> recompute forcé
                return CacheDecision(
                    strategy="recompute", confidence=0.3, source_layer="L0_lazy_exact",
                    reason="Exact match trouvé mais génération périmée (invalidation événementielle).",
                    generation_mismatch=True,
                )

        # 2. Semantic match (L2 — turbovec_brain), seulement si dispo
        if self._turbovec is not None:
            try:
                results = self._turbovec.search(query, k=3)
            except Exception as e:
                logger.debug(f"[cache_orch] turbovec.search échec: {e}")
                results = []
            if results:
                best = results[0]
                if best["score"] >= self.semantic_threshold:
                    return CacheDecision(
                        strategy="semantic", confidence=best["score"], result=best["summary"],
                        source_layer="L2_turbovec_semantic", similarity=best["score"],
                        reason=f"Similarité sémantique {best['score']:.2f} >= seuil {self.semantic_threshold}.",
                    )

        # 3. Rien d'exploitable -> calcul complet
        return CacheDecision(
            strategy="compute", confidence=0.0,
            reason="Aucun match exact ni sémantique au-dessus du seuil.",
        )

    # ── Écriture (traçable, versionné) ──────────────────────────────────────

    def record(self, query: str, result: Any, quality: float,
               agent: str = "unknown", domain: str = "") -> None:
        """
        Écrit dans toutes les couches disponibles. Chaque écriture porte :
        agent, domaine, confiance, génération courante (versionné).
        """
        task_hash = self._task_hash(query)
        gen = self.generations.current(domain)
        self._entry_generation[task_hash] = gen

        if self._lazy is not None:
            self._lazy.record_solution(query, result, quality, domain)

        if self._turbovec is not None:
            try:
                summary = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)[:500]
                self._turbovec.store(summary, agent=agent, score=quality)
            except Exception as e:
                logger.debug(f"[cache_orch] turbovec.store échec: {e}")

        if self._db is not None:
            try:
                self._db.deep_insert("cache_entries", {
                    "id": f"{task_hash}-{int(time.time())}",
                    "domain": domain or "_global",
                    "agent": agent,
                    "confidence": float(quality),
                    "generation": gen,
                    "ts": time.time(),
                    "summary": (result if isinstance(result, str) else str(result))[:300],
                })
            except Exception as e:
                logger.debug(f"[cache_orch] L3 record échec (non bloquant): {e}")

    # ── Invalidation par événement (ciblée, jamais globale par défaut) ─────

    EVENT_SCOPE = {
        "file_change": "domain",
        "dependency_update": "domain",
        "schema_migration": "domain",
        "agent_patch": "agent",
        "cve_alert": "domain",
    }

    def invalidate(self, event_type: str, domain: str = "", agent: str = "", tool_name: str = "") -> dict:
        """
        Invalidation par événement, PAS par TTL global.
        - file_change / dependency_update / schema_migration / cve_alert -> bump génération du domaine
        - agent_patch -> invalide seulement le cache MCP de cet agent/outil (portée étroite)
        """
        report = {"event": event_type, "domain": domain, "agent": agent, "actions": []}

        scope = self.EVENT_SCOPE.get(event_type, "domain")
        if scope == "domain":
            new_gen = self.generations.bump(domain)
            report["actions"].append(f"generation bump -> {domain or '_global'}:{new_gen}")
        elif scope == "agent" and self._mcp_cache is not None:
            n = self._mcp_cache.invalidate(tool_name or None)
            report["actions"].append(f"mcp_cache invalidate({tool_name or 'ALL for agent'}) -> {n} entrées")

        logger.info(f"[cache_orch] INVALIDATE {event_type} scope={scope} -> {report['actions']}")
        return report

    # ── Observabilité unifiée ────────────────────────────────────────────────

    def stats(self) -> dict:
        out = {"semantic_threshold": self.semantic_threshold, "generations": dict(self.generations._gens)}  # noqa: SLF001
        if self._lazy is not None:
            out["lazy_exact"] = self._lazy.stats()
        if self._turbovec is not None:
            try:
                out["turbovec_semantic"] = self._turbovec.token_pressure()
            except Exception:
                out["turbovec_semantic"] = {"error": "unavailable"}
        else:
            out["turbovec_semantic"] = {"status": "not_installed (pip install turbovec numpy)"}
        if self._mcp_cache is not None:
            out["mcp_proxy_l1"] = self._mcp_cache.stats()
        if self._db is not None:
            out["forge_db_l3l4"] = self._db.health()
        return out


# ─── Singleton ────────────────────────────────────────────────────────────────

_orchestrator: Optional[CacheOrchestrator] = None


def get_cache_orchestrator() -> CacheOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CacheOrchestrator()
    return _orchestrator


# ─── CLI / self-test (fonctionne sans Docker, PG, Redis ni turbovec) ─────────

if __name__ == "__main__":
    orch = get_cache_orchestrator()
    q = "Build a Telegram hotel booking bot"

    d1 = orch.decide(q, domain="bot")
    print(f"1st decide -> {d1.strategy} ({d1.reason})")
    assert d1.strategy == "compute"

    orch.record(q, {"code": "bot.py"}, quality=8.5, agent="BUILDER", domain="bot")

    d2 = orch.decide(q, domain="bot")
    print(f"2nd decide -> {d2.strategy} ({d2.reason})")
    assert d2.strategy == "exact"

    report = orch.invalidate("dependency_update", domain="bot")
    print(f"invalidate -> {report}")

    d3 = orch.decide(q, domain="bot")
    print(f"3rd decide (post-invalidation) -> {d3.strategy} ({d3.reason})")
    assert d3.strategy == "recompute"

    print(f"\nstats -> {json.dumps(orch.stats(), indent=2, ensure_ascii=False)}")
    print("\nOK — cascade exact->semantic->recompute->compute validée (sans infra externe).")
