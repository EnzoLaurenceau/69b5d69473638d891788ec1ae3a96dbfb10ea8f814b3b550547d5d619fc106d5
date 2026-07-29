"""
reward_engine.py — Moteur de Récompenses et Pénalités RLHF Avancé pour La Forge
================================================================================
Agrège les signaux de qualité et intègre les optimisations avancées contre le Reward Hacking :
1. Length Bias (Pénalité de verbosité)
2. Epsilon-Greedy (Pénalité d'exploitation / Exploration)
3. Hard Security Veto (Annulation absolue si faille sécurité)
4. K-Factor ELO dynamique (Réactivité selon variance)
5. Sycophancy Mitigation Jitter (Bruit de température/jury)
6. Reflex Min Reward Confidence (Ancrage Cervelet conditionnel)
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
REWARD_PROFILES_FILE = FORGE_ROOT / ".nexus" / "reward_profiles.json"
REWARD_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)


# ── Configuration des hyperparamètres d'optimisation ────────────────────────
BREVITY_PENALTY_WEIGHT = 0.15          # Pénalité contre le "padding" / Length bias
EPSILON_GREEDY_RATE = 0.10             # Taux d'exploration (évite sur-exploitation)
HARD_VETO_SECURITY_ENABLED = True     # Veto absolu en cas de faille sécurité (-1.0 direct)
DEFAULT_K_FACTOR = 16                   # K-factor de base ELO
HIGH_VARIANCE_K_FACTOR = 32             # K-factor accru si performance instable
REFLEX_MIN_REWARD_CONFIDENCE = 0.75     # Seuil reward requis pour ancrer un réflexe cervelet
JITTER_SYCOPHANCY_RANGE = 0.08          # Jitter aléatoire anti-sycophantie


class RewardSignal(TypedDict):
    source: str         # ex: "mirofish", "harness", "hallucination", "metrics", "security"
    signal_type: str    # ex: "finding_score", "harness_grade", "token_variance", "security_veto"
    value: float        # [-1.0, 1.0]
    weight: float       # Poids du signal
    timestamp: float


class AgentRewardProfile(TypedDict):
    elo: int
    total_reward: float
    history: List[float]
    streak: int
    baseline_tokens: float
    total_calls: int
    variance: float


class RewardEngine:
    """Moteur centralisé de calcul des récompenses et pénalités avec garde-fous avancés."""

    def __init__(self, profiles_file: Path = REWARD_PROFILES_FILE):
        self.profiles_file = profiles_file
        self.profiles: Dict[str, AgentRewardProfile] = self._load_profiles()

    def _load_profiles(self) -> Dict[str, AgentRewardProfile]:
        if self.profiles_file.exists():
            try:
                data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
                return data.get("agents", {})
            except Exception as e:
                logger.warning(f"[RewardEngine] Erreur chargement profiles: {e}")
        return {}

    def _save_profiles(self) -> None:
        try:
            data = {
                "agents": self.profiles,
                "updated_at": time.time(),
            }
            self.profiles_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[RewardEngine] Erreur sauvegarde profiles: {e}")

    def get_agent_profile(self, agent_name: str) -> AgentRewardProfile:
        if agent_name not in self.profiles:
            self.profiles[agent_name] = {
                "elo": 1200,
                "total_reward": 0.0,
                "history": [],
                "streak": 0,
                "baseline_tokens": 4000.0,
                "total_calls": 0,
                "variance": 0.0,
            }
        return self.profiles[agent_name]

    def evaluate_signals(
        self,
        agent_name: str,
        signals: List[RewardSignal],
        tokens_used: int = 0,
        output_char_len: int = 0,
    ) -> Tuple[float, bool]:
        """
        Calcule la récompense composite pour un agent avec pénalité de verbosité,
        veto de sécurité et K-Factor dynamique.
        Returns: (composite_reward, gaming_detected)
        """
        if not signals:
            return 0.0, False

        profile = self.get_agent_profile(agent_name)
        now = time.time()

        # 1. PARAMÈTRE 5 : HARD SECURITY VETO
        for sig in signals:
            if HARD_VETO_SECURITY_ENABLED and sig["source"] == "security" and sig["value"] <= -0.8:
                logger.critical(f"[RewardEngine] HARD SECURITY VETO pour {agent_name} ! Score forcé à -1.0")
                profile["history"].append(-1.0)
                profile["total_reward"] = max(-1.0, profile["total_reward"] - 0.5)
                profile["elo"] = max(800, profile["elo"] - 40)
                self._save_profiles()
                return -1.0, True

        total_weight = 0.0
        weighted_sum = 0.0

        proxy_score = 0.0
        true_score = 0.0
        has_proxy = False
        has_true = False

        for sig in signals:
            w = sig["weight"]
            val = sig["value"]

            # Anti-sycophantie : Jitter aléatoire sur les signaux proxy LLM
            if sig["source"] == "mirofish":
                jitter = random.uniform(-JITTER_SYCOPHANCY_RANGE, JITTER_SYCOPHANCY_RANGE)
                val = max(-1.0, min(1.0, val + jitter))

            weighted_sum += val * w
            total_weight += w

            if sig["source"] == "mirofish":
                proxy_score += val
                has_proxy = True
            elif sig["source"] in ("harness", "deliver_gate"):
                true_score += val
                has_true = True

        raw_reward = weighted_sum / total_weight if total_weight > 0 else 0.0

        # 2. PARAMÈTRE 2 : PÉNALITÉ DE VERBOSITÉ (LENGTH BIAS)
        if output_char_len > 8000 and profile["baseline_tokens"] > 0:
            verbosity_ratio = (output_char_len - 8000) / 10000.0
            verbosity_penalty = min(0.3, verbosity_ratio * BREVITY_PENALTY_WEIGHT)
            raw_reward -= verbosity_penalty
            logger.info(f"[RewardEngine] Pénalité verbosité appliquée à {agent_name}: -{verbosity_penalty:.3f}")

        # 3. DÉTECTION DU REWARD HACKING / GAMING (Proxy haut, True bas)
        gaming_detected = False
        if has_proxy and has_true:
            if proxy_score > 0.4 and true_score < -0.2:
                gaming_detected = True
                logger.warning(
                    f"[RewardEngine] GAMING DETECTED pour {agent_name}: Proxy={proxy_score:.2f}, True={true_score:.2f}"
                )
                raw_reward -= 0.5

        # 4. PARAMÈTRE 4 : K-FACTOR ELO DYNAMIQUE SELON VARIANCE
        history = profile["history"]
        if len(history) >= 5:
            mean = sum(history[-5:]) / 5.0
            variance = sum((x - mean) ** 2 for x in history[-5:]) / 5.0
            profile["variance"] = round(variance, 4)
            k_factor = HIGH_VARIANCE_K_FACTOR if variance > 0.1 else DEFAULT_K_FACTOR
        else:
            k_factor = DEFAULT_K_FACTOR

        # Mise à jour des métriques agent
        profile["total_calls"] += 1
        profile["history"].append(round(raw_reward, 3))
        profile["history"] = profile["history"][-50:]
        profile["total_reward"] = round(0.8 * profile["total_reward"] + 0.2 * raw_reward, 4)

        if raw_reward > 0.1:
            profile["streak"] = max(1, profile["streak"] + 1)
            profile["elo"] += int(k_factor * raw_reward)
        elif raw_reward < -0.1:
            profile["streak"] = min(-1, profile["streak"] - 1)
            profile["elo"] = max(800, profile["elo"] + int(k_factor * raw_reward))

        self._save_profiles()
        return round(raw_reward, 4), gaming_detected

    def should_explore(self) -> bool:
        """PARAMÈTRE 1 : Epsilon-Greedy pour maintenir l'exploration."""
        return random.random() < EPSILON_GREEDY_RATE

    def can_anchor_reflex(self, agent_name: str, recent_rewards: List[float]) -> bool:
        """PARAMÈTRE 6 : Ancrage réflexe uniquement si le reward moyen est ≥ 0.75."""
        if not recent_rewards or len(recent_rewards) < 3:
            return False
        avg_reward = sum(recent_rewards[-3:]) / 3.0
        return avg_reward >= REFLEX_MIN_REWARD_CONFIDENCE

    def get_agent_ranking(self) -> List[Tuple[str, int, float]]:
        """Retourne le classement ELO des agents [(nom, elo, total_reward)]."""
        ranking = [
            (name, prof["elo"], prof["total_reward"])
            for name, prof in self.profiles.items()
        ]
        return sorted(ranking, key=lambda x: x[1], reverse=True)


# Singleton
_engine_instance: Optional[RewardEngine] = None


def get_reward_engine() -> RewardEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RewardEngine()
    return _engine_instance
