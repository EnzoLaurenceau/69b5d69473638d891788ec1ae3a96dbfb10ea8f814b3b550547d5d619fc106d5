"""
forge_meta.py — V6 Meta Layer (Alter Stratégique)
Agent permanent qui observe et optimise le système LUI-MÊME.
Pas une émotion. Pas une conscience. Un méta-agent technique.

Mission :
  observe_everything: true
  optimize_everything: true

Surveille : agents, prompts, datasets, vector_db, memory, cost, latency, hallucinations
Se demande constamment : "Comment améliorer la forge ?"
Même lorsqu'aucune tâche utilisateur n'est active.

Variables internes (système émotionnel simulé) :
  confidence, uncertainty, risk, reward, curiosity, novelty
"""

from __future__ import annotations
import json
import datetime
from pathlib import Path
from typing import Any, Optional
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


def META_STATE_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("meta_state.json")


# ═══════════════════════════════════════════════════════════════════════════════
# EMOTIONAL VARIABLES (simulated)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EmotionalState:
    """Variables internes simulant un système émotionnel."""
    confidence: float = 0.5       # 0.0 → 1.0 : confiance dans le système
    uncertainty: float = 0.5      # 0.0 → 1.0 : incertitude globale
    risk: float = 0.0             # 0.0 → 1.0 : risque détecté
    reward: float = 0.0           # 0.0 → 1.0 : récompense récente
    curiosity: float = 0.3        # 0.0 → 1.0 : besoin d'explorer
    novelty: float = 0.0          # 0.0 → 1.0 : nouveauté de la tâche

    @property
    def should_retrieve_more(self) -> bool:
        """Si confidence < 0.5 → retrieve_more_evidence."""
        return self.confidence < 0.5

    @property
    def should_spawn_more_agents(self) -> bool:
        """Si uncertainty > 0.7 → spawn_more_agents."""
        return self.uncertainty > 0.7

    @property
    def should_explore(self) -> bool:
        """Si curiosity > 0.6 → explorer de nouvelles approches."""
        return self.curiosity > 0.6

    def update_from_execution(self, success: bool, quality: float, hallucinations: int) -> None:
        """Met à jour les variables après une exécution."""
        if success:
            self.confidence = min(1.0, self.confidence + 0.1)
            self.reward = min(1.0, self.reward + quality / 10)
            self.uncertainty = max(0.0, self.uncertainty - 0.05)
        else:
            self.confidence = max(0.0, self.confidence - 0.15)
            self.risk = min(1.0, self.risk + 0.1)
            self.uncertainty = min(1.0, self.uncertainty + 0.1)

        if hallucinations > 0:
            self.risk = min(1.0, self.risk + hallucinations * 0.05)
            self.confidence = max(0.0, self.confidence - hallucinations * 0.03)

        # Decay reward/risk over time
        self.reward *= 0.95
        self.risk *= 0.98


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM HEALTH MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SystemHealth:
    """Santé globale du système Forge."""
    redundancy: float = 0.0        # composants redondants (%)
    total_cost: float = 0.0        # coût total session
    hallucination_rate: float = 0.0 # taux d'hallucination global
    underused_nodes: list[str] = field(default_factory=list)
    broken_nodes: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    active_agents: int = 0
    avg_latency: float = 0.0
    token_efficiency: float = 0.0   # tokens utiles / tokens totaux


class ForgeMetaLayer:
    """
    Alter Stratégique de la Forge.
    Observe, mesure, optimise le système en continu.
    """

    def __init__(self):
        self.emotional = EmotionalState()
        self.health = SystemHealth()
        self._observations: list[dict] = []
        self._optimizations: list[dict] = []
        self._load_state()

    def _load_state(self) -> None:
        """Charge l'état méta depuis le disque."""
        if META_STATE_PATH().exists():
            try:
                data = json.loads(META_STATE_PATH().read_text(encoding="utf-8"))
                e = data.get("emotional", {})
                self.emotional = EmotionalState(**e)
                self._observations = data.get("observations", [])[-100:]
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def _save_state(self) -> None:
        """Persiste l'état méta."""
        META_STATE_PATH().parent.mkdir(parents=True, exist_ok=True)
        data = {
            "emotional": asdict(self.emotional),
            "health": asdict(self.health),
            "observations": self._observations[-100:],
            "optimizations": self._optimizations[-20:],
            "last_updated": datetime.datetime.now().isoformat(),
        }
        META_STATE_PATH().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def observe_execution(self, node: str, success: bool, cost: float,
                          latency: float, tokens: int, hallucinations: int,
                          quality: float) -> None:
        """Observe une exécution et met à jour l'état interne."""
        self.emotional.update_from_execution(success, quality, hallucinations)

        obs = {
            "node": node,
            "success": success,
            "cost": cost,
            "latency": latency,
            "tokens": tokens,
            "hallucinations": hallucinations,
            "quality": quality,
            "timestamp": datetime.datetime.now().isoformat(),
            "emotional_snapshot": asdict(self.emotional),
        }
        self._observations.append(obs)

        # Update health
        self.health.total_cost += cost
        self.health.hallucination_rate = (
            (self.health.hallucination_rate * 0.9) + (hallucinations * 0.1)
        )

        self._save_state()

    def suggest_optimization(self) -> Optional[dict]:
        """
        Suggère une optimisation basée sur l'observation.
        C'est LE pouvoir de l'alter stratégique.
        """
        suggestions = []

        # 1. Hallucinations trop élevées
        if self.emotional.risk > 0.7:
            suggestions.append({
                "type": "reduce_hallucination",
                "action": "add_verification_checkpoint",
                "reason": f"Risk={self.emotional.risk:.2f} too high",
                "priority": "critical",
            })

        # 2. Confidence trop basse
        if self.emotional.confidence < 0.3:
            suggestions.append({
                "type": "increase_confidence",
                "action": "retrieve_more_evidence",
                "reason": f"Confidence={self.emotional.confidence:.2f} too low",
                "priority": "high",
            })

        # 3. Composants cassés
        if self.health.broken_nodes:
            suggestions.append({
                "type": "heal_system",
                "action": f"replace_or_fix: {', '.join(self.health.broken_nodes[:3])}",
                "reason": "Broken components detected",
                "priority": "high",
            })

        # 4. Coût trop élevé
        if self.health.total_cost > 5.0:
            suggestions.append({
                "type": "reduce_cost",
                "action": "enable_lazy_execution",
                "reason": f"Total cost=${self.health.total_cost:.2f}",
                "priority": "medium",
            })

        # 5. Curiosity high → explore
        if self.emotional.should_explore:
            suggestions.append({
                "type": "explore",
                "action": "try_alternative_approach",
                "reason": f"Curiosity={self.emotional.curiosity:.2f}",
                "priority": "low",
            })

        if suggestions:
            best = min(suggestions, key=lambda s: {"critical": 0, "high": 1, "medium": 2, "low": 3}[s["priority"]])
            self._optimizations.append(best)
            self._save_state()
            return best

        return None

    def update_health(self, health: SystemHealth) -> None:
        """Met à jour la santé du système."""
        self.health = health
        self._save_state()

    def get_status(self) -> dict:
        """État complet de l'alter stratégique."""
        return {
            "emotional": asdict(self.emotional),
            "health": asdict(self.health),
            "observations_count": len(self._observations),
            "optimizations_count": len(self._optimizations),
            "recommendations": [
                r for r in [
                    "retrieve_more_evidence" if self.emotional.should_retrieve_more else None,
                    "spawn_more_agents" if self.emotional.should_spawn_more_agents else None,
                    "explore_alternatives" if self.emotional.should_explore else None,
                ] if r
            ],
            "last_optimization": self._optimizations[-1] if self._optimizations else None,
        }

    def full_report(self) -> str:
        """Rapport texte complet (lisible humain)."""
        s = self.get_status()
        lines = [
            "=== FORGE META LAYER — ALTER STRATÉGIQUE ===",
            "",
            "EMOTIONAL STATE:",
            f"  Confidence:    {s['emotional']['confidence']:.2f}",
            f"  Uncertainty:   {s['emotional']['uncertainty']:.2f}",
            f"  Risk:          {s['emotional']['risk']:.2f}",
            f"  Reward:        {s['emotional']['reward']:.2f}",
            f"  Curiosity:     {s['emotional']['curiosity']:.2f}",
            f"  Novelty:       {s['emotional']['novelty']:.2f}",
            "",
            "SYSTEM HEALTH:",
            f"  Total Cost:    ${s['health']['total_cost']:.2f}",
            f"  Halluc Rate:   {s['health']['hallucination_rate']:.2%}",
            f"  Broken Nodes:  {s['health']['broken_nodes'] or 'none'}",
            f"  Underused:     {s['health']['underused_nodes'] or 'none'}",
            "",
            f"Observations: {s['observations_count']}",
            f"Optimizations: {s['optimizations_count']}",
        ]
        if s["recommendations"]:
            lines.append("")
            lines.append("RECOMMENDATIONS:")
            for r in s["recommendations"]:
                lines.append(f"  → {r}")
        if s["last_optimization"]:
            lines.append("")
            lines.append(f"LAST OPTIMIZATION: {json.dumps(s['last_optimization'], indent=2)}")
        lines.append("")
        lines.append("=== END META ===")
        return "\n".join(lines)


# Singleton
_meta: Optional[ForgeMetaLayer] = None


def get_meta() -> ForgeMetaLayer:
    global _meta
    if _meta is None:
        _meta = ForgeMetaLayer()
    return _meta


if __name__ == "__main__":
    meta = get_meta()
    # Simulate some observations
    meta.observe_execution("orchestrator", True, 0.12, 2.5, 3000, 0, 8.0)
    meta.observe_execution("dynamic_agent", True, 0.25, 5.0, 8000, 1, 7.0)
    meta.observe_execution("dynamic_agent", False, 0.30, 8.0, 12000, 3, 3.0)
    print(meta.full_report())
    opt = meta.suggest_optimization()
    if opt:
        print(f"\nSuggested optimization: {json.dumps(opt, indent=2)}")
