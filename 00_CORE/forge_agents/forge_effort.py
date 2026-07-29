"""forge_effort.py — Effort/Thinking Router pour La Forge
========================================================

Mappe un niveau d'effort (low/medium/high/max) vers les paramètres concrets :
  - Claude CLI : --thinking, --model, --max-tokens
  - MiMo       : max_tokens, temperature
  - ds2api/Groq : max_tokens

Usage :
    from forge_agents.forge_effort import EffortLevel, effort_params, effort_for_task

    params = effort_params(EffortLevel.HIGH)
    # → {"claude_thinking": True, "claude_model": "opus", "max_tokens": 8000, ...}
"""

from __future__ import annotations
from enum import Enum
from typing import Optional


class EffortLevel(str, Enum):
    """Niveaux d'effort — du plus économique au plus puissant."""
    LOW    = "low"      # extraction, format, score → MiMo ou Haiku, 0 thinking
    MEDIUM = "medium"   # code, research, build → Sonnet, thinking off par défaut
    HIGH   = "high"     # orchestration, audit, critique → Opus, thinking adaptatif
    MAX    = "max"      # plan d'implémentation complexe → Opus, thinking forcé


# ── Mapping effort → paramètres concrets ──────────────────────────────────────

EFFORT_MAP: dict[EffortLevel, dict] = {
    EffortLevel.LOW: {
        "claude_model": "haiku",        # alias CLI
        "claude_thinking": False,       # pas de thinking
        "mimo_max_tokens": 1000,
        "mimo_temperature": 0.3,        # factuel, peu créatif
        "description": "Extraction, format, score — pas de raisonnement",
    },
    EffortLevel.MEDIUM: {
        "claude_model": "sonnet",
        "claude_thinking": False,       # Sonnet lean, pas de thinking
        "mimo_max_tokens": 2000,
        "mimo_temperature": 0.5,        # équilibré
        "description": "Code, research, build — raisonnement standard",
    },
    EffortLevel.HIGH: {
        "claude_model": "opus",
        "claude_thinking": True,        # extended thinking adaptatif
        "mimo_max_tokens": 4000,
        "mimo_temperature": 0.7,        # plus créatif pour l'orchestration
        "description": "Orchestration, audit, critique — raisonnement profond",
    },
    EffortLevel.MAX: {
        "claude_model": "opus",
        "claude_thinking": True,        # extended thinking forcé
        "mimo_max_tokens": 8000,
        "mimo_temperature": 0.8,        # maximum créativité
        "description": "Plan d'implémentation complexe — raisonnement maximal",
    },
}


def effort_params(level: EffortLevel | str) -> dict:
    """Retourne les paramètres concrets pour un niveau d'effort."""
    if isinstance(level, str):
        level = EffortLevel(level.lower())
    return EFFORT_MAP.get(level, EFFORT_MAP[EffortLevel.MEDIUM])


def effort_for_task(task_type: str) -> EffortLevel:
    """Déduit le niveau d'effort optimal d'après le type de tâche.

    Mapping aligné sur TASK_TIER_MAP de forge_llm.py mais avec granularité effort.
    """
    task_lower = (task_type or "").lower().strip()

    # ── LOW : extraction, format, score ──────────────────────────────────
    LOW_TASKS = {
        "score", "summarize", "format", "extract", "classify",
        "translate", "rewrite", "template", "fast_extraction",
        "write_email", "write_post", "write_caption", "generate",
        "jury",
    }
    if task_lower in LOW_TASKS:
        return EffortLevel.LOW

    # ── HIGH : orchestration, audit, critique ────────────────────────────
    HIGH_TASKS = {
        "orchestrate", "critique", "audit", "plan", "implementation_plan",
        "architect",
    }
    if task_lower in HIGH_TASKS:
        return EffortLevel.HIGH

    # ── MEDIUM : code, research, build ───────────────────────────────────
    MEDIUM_TASKS = {
        "market_scan", "research", "build", "close", "hunt",
        "massive_context", "general_purpose", "code", "coding_only",
        "refactor", "debug",
    }
    if task_lower in MEDIUM_TASKS:
        return EffortLevel.MEDIUM

    # Défaut : MEDIUM (sûr, pas trop cher)
    return EffortLevel.MEDIUM


def effort_cli_args(level: EffortLevel | str) -> list[str]:
    """Construit les arguments CLI Claude pour un niveau d'effort.

    Retourne une liste d'arguments à ajouter à la commande `claude -p`.
    """
    params = effort_params(level)
    args = ["--model", params["claude_model"]]
    if params["claude_thinking"]:
        args.append("--thinking")   # extended thinking activé
    return args


# ── Self-check ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Vérifie que tous les niveaux ont des paramètres valides
    for level in EffortLevel:
        p = effort_params(level)
        assert "claude_model" in p, f"{level}: missing claude_model"
        assert "claude_thinking" in p, f"{level}: missing claude_thinking"
        assert p["claude_model"] in ("haiku", "sonnet", "opus"), f"{level}: bad model {p['claude_model']}"

    # Vérifie le mapping task → effort
    assert effort_for_task("score") == EffortLevel.LOW
    assert effort_for_task("build") == EffortLevel.MEDIUM
    assert effort_for_task("orchestrate") == EffortLevel.HIGH
    assert effort_for_task("unknown_task") == EffortLevel.MEDIUM  # défaut

    # Vérifie les arguments CLI
    assert "--thinking" in effort_cli_args("high")
    assert "--thinking" not in effort_cli_args("low")
    assert effort_cli_args("low") == ["--model", "haiku"]
    assert effort_cli_args("max") == ["--model", "opus", "--thinking"]

    print("forge_effort self-check: ALL TESTS PASSED")
    print(f"  LOW    → {effort_cli_args('low')}")
    print(f"  MEDIUM → {effort_cli_args('medium')}")
    print(f"  HIGH   → {effort_cli_args('high')}")
    print(f"  MAX    → {effort_cli_args('max')}")
