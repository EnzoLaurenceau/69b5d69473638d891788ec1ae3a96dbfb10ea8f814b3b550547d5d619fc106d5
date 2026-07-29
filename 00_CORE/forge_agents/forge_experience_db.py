"""
forge_experience_db.py — V6 Experience Database (BigSet replacement)
Stocke UNIQUEMENT les expériences d'exécution réelles.
Pas de raw data — que du signal : quels composants fonctionnent vraiment,
lesquels sont inutiles, lesquels hallucinent.

Types stockés :
  - Experience : résultat d'une exécution (success/failure + métriques)
  - WorkflowScore : réputation d'un workflow (agrégée)
  - ComponentHealth : santé d'un composant Forge

Le subconscient utilise cette DB pour apprendre en arrière-plan.
"""

from __future__ import annotations
import json
import time
import hashlib
import datetime
from pathlib import Path
from typing import Any, Literal, Optional
from dataclasses import dataclass, field, asdict
import logging
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger(__name__)


FORGE_ROOT = Path(__file__).parent.parent.parent


def EXP_DB_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("experience_db.json")


# ═══════════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Experience:
    """Une exécution enregistrée."""
    id: str = ""
    kernel_id: str = ""             # lien vers le kernel
    task: str = ""                  # tâche (résumé)
    used_nodes: list[str] = field(default_factory=list)  # composants utilisés
    outcome: Literal["success", "failure", "partial"] = "success"
    reason: str = ""                # pourquoi success/failure
    cost: float = 0.0               # coût total ($)
    latency: float = 0.0            # temps total (sec)
    tokens_used: int = 0
    hallucination_flags: int = 0    # nombre d'hallucinations détectées
    quality_score: float = 0.0      # 0.0 → 10.0
    domain: str = ""
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            raw = f"{self.task}|{self.outcome}|{time.time()}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.timestamp:
            self.timestamp = datetime.datetime.now().isoformat()


@dataclass
class WorkflowScore:
    """Réputation agrégée d'un workflow."""
    workflow_id: str = ""
    workflow_name: str = ""
    total_runs: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_quality: float = 0.0
    avg_cost: float = 0.0
    avg_latency: float = 0.0
    avg_hallucinations: float = 0.0
    reputation: float = 50.0        # 0 → 100 (score de confiance)
    last_used: str = ""
    domains: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.total_runs, 1)

    def update(self, exp: Experience) -> None:
        """Met à jour le score avec une nouvelle expérience."""
        self.total_runs += 1
        if exp.outcome == "success":
            self.success_count += 1
        elif exp.outcome == "failure":
            self.failure_count += 1

        # Rolling average
        n = self.total_runs
        self.avg_quality = ((self.avg_quality * (n - 1)) + exp.quality_score) / n
        self.avg_cost = ((self.avg_cost * (n - 1)) + exp.cost) / n
        self.avg_latency = ((self.avg_latency * (n - 1)) + exp.latency) / n
        self.avg_hallucinations = ((self.avg_hallucinations * (n - 1)) + exp.hallucination_flags) / n

        # Reputation = weighted score
        self.reputation = (
            self.success_rate * 40 +
            max(0, (10 - self.avg_hallucinations)) * 4 +
            min(self.avg_quality, 10) * 2
        )
        self.last_used = datetime.datetime.now().isoformat()
        if exp.domain and exp.domain not in self.domains:
            self.domains.append(exp.domain)


@dataclass
class ComponentHealth:
    """Santé d'un composant Forge (agent, MCP, tool)."""
    component_id: str = ""
    component_type: str = ""        # "agent", "mcp", "tool", "workflow"
    total_calls: int = 0
    success_count: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    total_hallucinations: int = 0
    avg_latency: float = 0.0
    last_used: str = ""
    status: Literal["healthy", "degraded", "dead", "unknown"] = "unknown"

    def update_status(self) -> None:
        """Recalcule le statut basé sur les métriques."""
        if self.total_calls == 0:
            self.status = "unknown"
        elif self.success_count / self.total_calls >= 0.8:
            self.status = "healthy"
        elif self.success_count / self.total_calls >= 0.5:
            self.status = "degraded"
        else:
            self.status = "dead"


# ═══════════════════════════════════════════════════════════════════════════════
# EXPERIENCE DB
# ═══════════════════════════════════════════════════════════════════════════════

class ExperienceDB:
    """
    Base de données d'expériences de la Forge.
    Persistée en JSON (lisible par Claude/Hermes).
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or EXP_DB_PATH()
        self._experiences: list[dict] = []
        self._workflow_scores: dict[str, dict] = {}
        self._component_health: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Charge la DB depuis le fichier."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._experiences = data.get("experiences", [])
                self._workflow_scores = data.get("workflow_scores", {})
                self._component_health = data.get("component_health", {})
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def _save(self) -> None:
        """Persiste la DB."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "experiences": self._experiences[-500:],  # garder 500 dernières
            "workflow_scores": self._workflow_scores,
            "component_health": self._component_health,
            "last_updated": datetime.datetime.now().isoformat(),
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def record(self, exp: Experience) -> str:
        """Enregistre une expérience et met à jour les scores."""
        self._experiences.append(asdict(exp))

        # Update workflow scores
        for node in exp.used_nodes:
            wf_key = node
            if wf_key not in self._workflow_scores:
                self._workflow_scores[wf_key] = asdict(WorkflowScore(workflow_id=wf_key, workflow_name=node))
            wf = WorkflowScore(**self._workflow_scores[wf_key])
            wf.update(exp)
            self._workflow_scores[wf_key] = asdict(wf)

            # Update component health
            if wf_key not in self._component_health:
                self._component_health[wf_key] = asdict(ComponentHealth(component_id=wf_key))
            ch = ComponentHealth(**self._component_health[wf_key])
            ch.total_calls += 1
            if exp.outcome == "success":
                ch.success_count += 1
            ch.total_cost += exp.cost
            ch.total_tokens += exp.tokens_used
            ch.total_hallucinations += exp.hallucination_flags
            n = ch.total_calls
            ch.avg_latency = ((ch.avg_latency * (n - 1)) + exp.latency) / n
            ch.last_used = datetime.datetime.now().isoformat()
            ch.update_status()
            self._component_health[wf_key] = asdict(ch)

        self._save()
        return exp.id

    def get_best_workflow(self, domain: str = None) -> Optional[str]:
        """Retourne le workflow avec la meilleure réputation."""
        candidates = self._workflow_scores.values()
        if domain:
            candidates = [w for w in candidates if domain in w.get("domains", [])]
        if not candidates:
            return None
        best = max(candidates, key=lambda w: w.get("reputation", 0))
        return best.get("workflow_name")

    def get_dead_components(self) -> list[str]:
        """Retourne les composants morts (status=dead)."""
        return [
            cid for cid, ch in self._component_health.items()
            if ch.get("status") == "dead"
        ]

    def get_degraded_components(self) -> list[str]:
        """Retourne les composants dégradés."""
        return [
            cid for cid, ch in self._component_health.items()
            if ch.get("status") == "degraded"
        ]

    def get_hallucination_sources(self) -> list[dict]:
        """Retourne les composants qui hallucinent le plus."""
        sources = []
        for cid, ch in self._component_health.items():
            if ch.get("total_hallucinations", 0) > 0:
                rate = ch["total_hallucinations"] / max(ch.get("total_calls", 1), 1)
                sources.append({"component": cid, "hallucination_rate": rate, "total": ch["total_hallucinations"]})
        return sorted(sources, key=lambda x: x["hallucination_rate"], reverse=True)

    def summary(self) -> dict:
        """Résumé global de la DB."""
        return {
            "total_experiences": len(self._experiences),
            "workflows_tracked": len(self._workflow_scores),
            "components_tracked": len(self._component_health),
            "dead_components": self.get_dead_components(),
            "degraded_components": self.get_degraded_components(),
            "top_hallucination_sources": self.get_hallucination_sources()[:3],
            "best_workflows": sorted(
                self._workflow_scores.values(),
                key=lambda w: w.get("reputation", 0),
                reverse=True
            )[:5],
        }

    def subsystem_consolidation(self) -> dict:
        """
        Subconscient : consolidation mémoire.
        Identifie patterns de success/failure, nettoie les données périmées.
        """
        # Success patterns
        success_exps = [e for e in self._experiences if e.get("outcome") == "success"]
        failure_exps = [e for e in self._experiences if e.get("outcome") == "failure"]

        # Domain distribution
        domains: dict[str, int] = {}
        for e in self._experiences:
            d = e.get("domain", "unknown")
            domains[d] = domains.get(d, 0) + 1

        # Cost trends
        recent = self._experiences[-50:]
        avg_cost_recent = sum(e.get("cost", 0) for e in recent) / max(len(recent), 1)
        avg_cost_all = sum(e.get("cost", 0) for e in self._experiences) / max(len(self._experiences), 1)

        return {
            "total": len(self._experiences),
            "success_rate": len(success_exps) / max(len(self._experiences), 1),
            "domain_distribution": domains,
            "cost_trend": "improving" if avg_cost_recent < avg_cost_all else "degrading",
            "avg_cost_recent": avg_cost_recent,
            "avg_cost_all": avg_cost_all,
            "recommendations": self._generate_recommendations(),
        }

    def _generate_recommendations(self) -> list[str]:
        """Génère des recommandations basées sur les données."""
        recs = []
        dead = self.get_dead_components()
        if dead:
            recs.append(f"REMOVE dead components: {', '.join(dead[:3])}")

        degraded = self.get_degraded_components()
        if degraded:
            recs.append(f"INVESTIGATE degraded: {', '.join(degraded[:3])}")

        halluc_sources = self.get_hallucination_sources()
        if halluc_sources:
            top = halluc_sources[0]
            recs.append(f"FIX hallucinations in {top['component']} (rate={top['hallucination_rate']:.1%})")

        return recs


# Singleton
_exp_db: Optional[ExperienceDB] = None


def get_experience_db() -> ExperienceDB:
    global _exp_db
    if _exp_db is None:
        _exp_db = ExperienceDB()
    return _exp_db


# CLI
if __name__ == "__main__":
    db = get_experience_db()

    # Record a test experience
    exp = Experience(
        task="Build hotel bot",
        used_nodes=["orchestrator", "dynamic_agent", "forge_llm"],
        outcome="success",
        reason="All components worked",
        cost=0.43,
        latency=12.5,
        tokens_used=15000,
        hallucination_flags=0,
        quality_score=8.5,
        domain="bot",
    )
    exp_id = db.record(exp)
    print(f"Recorded: {exp_id}")
    print(json.dumps(db.summary(), indent=2, default=str))
