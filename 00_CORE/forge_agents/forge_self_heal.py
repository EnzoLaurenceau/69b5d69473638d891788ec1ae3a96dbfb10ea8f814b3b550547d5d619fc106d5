"""
forge_self_heal.py — V6 Self-Healing System
Détecte les composants cassés, redondants, inutiles et agit :
  merge / remove / replace / optimize

Intègre le système de preuves (Evidence Layer) qui transforme
les données brutes en connaissances vérifiées.
"""

from __future__ import annotations
import json
import datetime
from pathlib import Path
from typing import Any, Optional, Literal
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


def HEAL_LOG_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("self_heal_log.json")


# ═══════════════════════════════════════════════════════════════════════════════
# EVIDENCE LAYER — BigSet devient système de preuves
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_TYPES = [
    "official_docs",      # Documentation officielle
    "github",             # Code source, issues, PRs
    "postmortems",        # Retours d'expérience
    "benchmarks",         # Benchmarks de performance
    "security_data",      # CVE, OWASP, audits
    "case_studies",       # Études de cas
    "reddit_feedback",    # Feedback communautaire
]

# Domain → evidence à récupérer systématiquement
DOMAIN_EVIDENCE_MAP: dict[str, list[str]] = {
    "web_dev": ["framework_docs", "dependency_docs", "github_patterns", "deployment_patterns", "testing_patterns"],
    "security": ["OWASP", "CWE", "CVE", "security_postmortems"],
    "ai_ml": ["papers", "benchmarks", "repos", "evaluations"],
    "product": ["user_feedback", "reddit", "reviews", "case_studies"],
    "devops": ["deployment_docs", "monitoring_patterns", "incident_postmortems"],
    "bot": ["api_docs", "webhook_patterns", "rate_limits"],
}


@dataclass
class Evidence:
    """Une preuve vérifiée."""
    id: str = ""
    evidence_type: str = ""         # un des EVIDENCE_TYPES
    source: str = ""                # URL, repo, doc
    content_summary: str = ""
    confidence: float = 0.0         # fiabilité de la source
    domain: str = ""
    verified: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now().isoformat()


def get_required_evidence(domain: str) -> list[str]:
    """Retourne les types de preuves requis pour un domaine."""
    return DOMAIN_EVIDENCE_MAP.get(domain, ["official_docs", "github"])


# ═══════════════════════════════════════════════════════════════════════════════
# ANTI-HALLUCINATION CHECKPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Checkpoint:
    """Checkpoint anti-hallucination (tous les X tokens)."""
    goal: str = ""
    known_facts: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    token_position: int = 0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now().isoformat()

    def is_consistent(self) -> bool:
        """Vérifie la cohérence interne du checkpoint."""
        # Pas d'unknowns qui sont dans known_facts
        contradictions = set(self.known_facts) & set(self.unknowns)
        return len(contradictions) == 0 and self.confidence >= 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointManager:
    """Gère les checkpoints anti-hallucination."""

    def __init__(self, checkpoint_interval: int = 2000):
        self._checkpoints: list[dict] = []
        self._interval = checkpoint_interval  # tokens entre checkpoints
        self._last_checkpoint_tokens = 0

    def should_checkpoint(self, current_tokens: int) -> bool:
        """Vérifie si on doit faire un checkpoint."""
        return (current_tokens - self._last_checkpoint_tokens) >= self._interval

    def create_checkpoint(self, goal: str, known_facts: list[str],
                          assumptions: list[str], unknowns: list[str],
                          sources: list[str], confidence: float,
                          token_position: int) -> Checkpoint:
        """Crée un nouveau checkpoint."""
        cp = Checkpoint(
            goal=goal,
            known_facts=known_facts,
            assumptions=assumptions,
            unknowns=unknowns,
            sources=sources,
            confidence=confidence,
            token_position=token_position,
        )
        self._checkpoints.append(cp.to_dict())
        self._last_checkpoint_tokens = token_position
        return cp

    def rollback_to_last(self) -> Optional[dict]:
        """Rollback au dernier checkpoint cohérent."""
        for cp in reversed(self._checkpoints):
            c = Checkpoint(**cp)
            if c.is_consistent():
                return cp
        return None

    def get_checkpoints(self) -> list[dict]:
        return self._checkpoints


# ═══════════════════════════════════════════════════════════════════════════════
# SELF-HEALING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HealAction:
    """Action de guérison."""
    action_type: Literal["merge", "remove", "replace", "optimize", "escalate"]
    target: str                     # composant ciblé
    reason: str
    priority: Literal["critical", "high", "medium", "low"]
    details: dict = field(default_factory=dict)
    executed: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now().isoformat()


class SelfHealingEngine:
    """
    Moteur de self-healing.
    Détecte les problèmes et propose/exécute des actions correctives.
    """

    def __init__(self):
        self._actions: list[dict] = []
        self._log_path = HEAL_LOG_PATH()
        self._load_log()

    def _load_log(self) -> None:
        if self._log_path.exists():
            try:
                data = json.loads(self._log_path.read_text(encoding="utf-8"))
                self._actions = data.get("actions", [])[-200:]
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def _save_log(self) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "actions": self._actions[-200:],
            "last_updated": datetime.datetime.now().isoformat(),
        }
        self._log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def diagnose(self, component_health: dict[str, dict]) -> list[HealAction]:
        """
        Diagnostique les composants et génère des actions de guérison.
        Input : component_health depuis ExperienceDB.
        """
        actions = []

        for cid, health in component_health.items():
            status = health.get("status", "unknown")

            # Dead → remove or replace
            if status == "dead":
                actions.append(HealAction(
                    action_type="remove",
                    target=cid,
                    reason=f"Component dead (success rate < 50%)",
                    priority="critical",
                    details={"total_calls": health.get("total_calls", 0)},
                ))

            # Degraded → optimize
            elif status == "degraded":
                actions.append(HealAction(
                    action_type="optimize",
                    target=cid,
                    reason=f"Component degraded (success rate 50-80%)",
                    priority="high",
                    details={
                        "total_calls": health.get("total_calls", 0),
                        "hallucinations": health.get("total_hallucinations", 0),
                    },
                ))

            # High hallucinations → replace
            if health.get("total_hallucinations", 0) > 5:
                hall_rate = health["total_hallucinations"] / max(health.get("total_calls", 1), 1)
                if hall_rate > 0.3:
                    actions.append(HealAction(
                        action_type="replace",
                        target=cid,
                        reason=f"High hallucination rate ({hall_rate:.0%})",
                        priority="high",
                        details={"hallucination_rate": hall_rate},
                    ))

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        actions.sort(key=lambda a: priority_order.get(a.priority, 9))

        return actions

    def execute_action(self, action: HealAction) -> bool:
        """
        Exécute une action de guérison.
        En mode Forge, on log l'action — l'exécution réelle est faite par le graph.
        """
        action.executed = True
        self._actions.append(asdict(action))
        self._save_log()
        return True

    def get_pending_actions(self) -> list[dict]:
        """Retourne les actions non exécutées."""
        return [a for a in self._actions if not a.get("executed")]

    def get_history(self, limit: int = 20) -> list[dict]:
        return self._actions[-limit:]

    def summary(self) -> dict:
        """Résumé du self-healing."""
        total = len(self._actions)
        executed = sum(1 for a in self._actions if a.get("executed"))
        by_type: dict[str, int] = {}
        for a in self._actions:
            t = a.get("action_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total_actions": total,
            "executed": executed,
            "pending": total - executed,
            "by_type": by_type,
        }


# Singleton
_healer: Optional[SelfHealingEngine] = None


def get_healer() -> SelfHealingEngine:
    global _healer
    if _healer is None:
        _healer = SelfHealingEngine()
    return _healer


if __name__ == "__main__":
    healer = get_healer()

    # Simulate component health
    health = {
        "old_scraper": {"status": "dead", "total_calls": 10, "total_hallucinations": 0},
        "flaky_agent": {"status": "degraded", "total_calls": 20, "total_hallucinations": 8},
        "good_agent": {"status": "healthy", "total_calls": 50, "total_hallucinations": 1},
    }

    actions = healer.diagnose(health)
    for a in actions:
        print(f"[{a.priority}] {a.action_type} {a.target}: {a.reason}")
        healer.execute_action(a)

    print(f"\nSummary: {json.dumps(healer.summary(), indent=2)}")
