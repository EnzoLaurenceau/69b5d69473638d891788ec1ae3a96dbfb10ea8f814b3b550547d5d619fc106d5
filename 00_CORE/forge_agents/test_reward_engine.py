"""
test_reward_engine.py — Tests des optimisations avancées du Moteur de Récompenses.
"""

import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from forge_agents.reward_engine import (
    RewardEngine,
    RewardSignal,
    REFLEX_MIN_REWARD_CONFIDENCE,
)


def test_reward_calculation(tmp_path: Path):
    test_file = tmp_path / "test_profiles.json"
    engine = RewardEngine(profiles_file=test_file)

    signals: list[RewardSignal] = [
        {
            "source": "mirofish",
            "signal_type": "verdict",
            "value": 0.8,
            "weight": 0.2,
            "timestamp": time.time(),
        },
        {
            "source": "harness",
            "signal_type": "harness_grade",
            "value": 0.9,
            "weight": 0.25,
            "timestamp": time.time(),
        },
    ]

    reward, gaming = engine.evaluate_signals("test_agent", signals, tokens_used=3500)
    assert reward > 0.5
    assert not gaming


def test_hard_security_veto(tmp_path: Path):
    """Test 1: Hard Security Veto (Faille de sécurité => -1.0 direct)"""
    test_file = tmp_path / "test_profiles_sec.json"
    engine = RewardEngine(profiles_file=test_file)

    signals: list[RewardSignal] = [
        {
            "source": "security",
            "signal_type": "idor_vulnerability",
            "value": -1.0,
            "weight": 1.0,
            "timestamp": time.time(),
        }
    ]

    reward, gaming = engine.evaluate_signals("vulnerable_agent", signals)
    assert reward == -1.0
    assert gaming is True


def test_verbosity_penalty(tmp_path: Path):
    """Test 2: Pénalité de verbosité (Length bias mitigation)"""
    test_file = tmp_path / "test_profiles_verb.json"
    engine = RewardEngine(profiles_file=test_file)

    signals: list[RewardSignal] = [
        {
            "source": "mirofish",
            "signal_type": "verdict",
            "value": 0.8,
            "weight": 0.5,
            "timestamp": time.time(),
        }
    ]

    reward_normal, _ = engine.evaluate_signals("agent_normal", signals, output_char_len=2000)
    reward_verbose, _ = engine.evaluate_signals("agent_verbose", signals, output_char_len=25000)

    assert reward_verbose < reward_normal


def test_reflex_confidence_gate(tmp_path: Path):
    """Test 3: Seuil de confiance pour l'ancrage réflexe Cervelet"""
    test_file = tmp_path / "test_profiles_reflex.json"
    engine = RewardEngine(profiles_file=test_file)

    # Récompenses faibles (0.5 < 0.75)
    assert not engine.can_anchor_reflex("agent_mediocre", [0.5, 0.6, 0.5])

    # Récompenses élevées (>= 0.75)
    assert engine.can_anchor_reflex("agent_excellent", [0.8, 0.85, 0.9])
