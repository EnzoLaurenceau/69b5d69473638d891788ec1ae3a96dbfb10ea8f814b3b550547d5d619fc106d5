"""S-24 — Le routeur LLM utilise Claude → MiMo (plus de ds2api/Groq).

POURQUOI CES TESTS EXISTENT
----------------------------
Décisions 5+6 (2026-07-25) : plus aucun tier gratuit. ds2api et Groq retirés.
Le routeur `_call_anthropic` doit maintenant :
1. Essayer Claude d'abord (tous les tiers).
2. Basculer sur MiMo si Claude échoue (indisponible ou budget épuisé).
3. Lever BudgetExceeded si le budget MiMo est épuisé AVANT d'appeler.
4. Ne jamais référencer ds2api ou Groq dans la cascade.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))


def test_la_cascade_ne_mentionne_plus_ds2api_ni_groq():
    """Le code de routage de _call_anthropic ne doit plus acheminer vers ds2api ni Groq."""
    src = (ROOT / "00_CORE" / "forge_agents" / "forge_llm.py").read_text(encoding="utf-8")
    # Extraire le corps de _call_anthropic (après la docstring)
    start = src.index("def _call_anthropic(")
    body_start = src.index('"""', start + 1)
    body_start = src.index('"""', body_start + 3) + 3  # fin de la docstring
    # Chercher la fin de la fonction (prochaine def au niveau top-level)
    rest = src[body_start:]
    lines = rest.split("\n")
    end_idx = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("def ") or (line and not line[0].isspace() and "=" in line and line.index("=") < 10):
            end_idx = i
            break
    func_body = "\n".join(lines[:end_idx]).lower()
    # Les seules références à ds2api/groq doivent être dans des commentaires "retiré"
    for line in func_body.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert "ds2api" not in stripped, f"_call_anthropic route encore vers ds2api: {stripped}"
        assert "groq" not in stripped, f"_call_anthropic route encore vers groq: {stripped}"


def test_la_cascade_memo_avec_budget_check(monkeypatch):
    """Quand Claude échoue, MiMo est tenté avec un budget check."""
    from forge_agents import forge_llm, forge_mimo, mimo_budget

    # Claude échoue toujours
    monkeypatch.setattr(forge_llm, "_claude_enabled", lambda env=None: True)

    call_log = []

    def _failing_claude(*_a, **_kw):
        raise RuntimeError("Claude indisponible (test)")

    def _recording_mimo(prompt, system="", max_tokens=1000, timeout=60):
        call_log.append("mimo")
        return "réponse mimo", {"in": 100, "out": 50, "billed_tokens": 1000,
                                 "latency_ms": 10, "calls": 1}

    monkeypatch.setattr(forge_llm, "_call_claude", _failing_claude)
    monkeypatch.setattr(forge_mimo, "mimo_call", _recording_mimo)
    monkeypatch.setattr(forge_mimo, "is_available", lambda: True)
    monkeypatch.setattr(mimo_budget, "plan_tokens", lambda: 999_999_999_999)
    monkeypatch.setattr(mimo_budget, "used", lambda _period=None: 0)

    from forge_agents.forge_llm import _call_anthropic, LLMTier

    result = _call_anthropic("test prompt", "test system", LLMTier.SONNET, 500)
    assert result == "réponse mimo"
    assert call_log == ["mimo"], "MiMo doit être appelé quand Claude échoue"


def test_budget_exceeded_empeche_mimo(monkeypatch):
    """BudgetExceeded levé quand le budget MiMo est épuisé — même si MiMo est disponible."""
    from forge_agents import forge_llm, forge_mimo, mimo_budget

    monkeypatch.setattr(forge_llm, "_claude_enabled", lambda env=None: True)

    def _failing_claude(*_a, **_kw):
        raise RuntimeError("Claude indisponible")

    def _should_not_be_called(*_a, **_kw):
        raise AssertionError("mimo_call ne doit pas être appelé quand le budget est épuisé")

    monkeypatch.setattr(forge_llm, "_call_claude", _failing_claude)
    monkeypatch.setattr(forge_mimo, "mimo_call", _should_not_be_called)
    monkeypatch.setattr(forge_mimo, "is_available", lambda: True)
    monkeypatch.setattr(mimo_budget, "plan_tokens", lambda: 100)
    monkeypatch.setattr(mimo_budget, "used", lambda _period=None: 100)

    from forge_agents.forge_llm import _call_anthropic, LLMTier
    from forge_agents.mimo_budget import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        _call_anthropic("test", "system", LLMTier.SONNET, 500)


def test_erreur_ne_mentionne_que_claude_et_mimo(monkeypatch):
    """Le message d'erreur ne mentionne que Claude et MiMo (pas ds2api/Groq)."""
    from forge_agents import forge_llm, forge_mimo, mimo_budget

    monkeypatch.setattr(forge_llm, "_claude_enabled", lambda env=None: True)
    monkeypatch.setattr(forge_llm, "_call_claude",
                        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("claude fail")))
    monkeypatch.setattr(forge_mimo, "is_available", lambda: False)
    monkeypatch.setattr(mimo_budget, "plan_tokens", lambda: 999_999_999_999)
    monkeypatch.setattr(mimo_budget, "used", lambda _period=None: 0)

    from forge_agents.forge_llm import _call_anthropic, LLMTier

    with pytest.raises(EnvironmentError, match="Claude et MiMo"):
        _call_anthropic("test", "system", LLMTier.SONNET, 500)
