"""
analysts.py — sous-agents "avis" (lentilles diverses). LLM tier FREE uniquement.

Token economy : chaque analyste reçoit SEULEMENT le setup distillé + contexte court
(jamais l'OHLCV brut), répond en UNE ligne stricte parsable :
    VOTE=LONG|SHORT|FLAT SCORE=0..10 REASON=<court>
Si forge_call indispo (pas de clé / offline) → fallback déterministe basé sur le setup.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from .smc_engine import Setup
import logging

logger = logging.getLogger(__name__)

# rôle -> (poids dans le jury, brief système)
ROLES: dict[str, tuple[float, str]] = {
    "TECHNIQUE":     (1.0, "Analyste technique. Juge alignement multi-TF, momentum, niveaux."),
    "INSTITUTIONNEL":(1.2, "Lecteur Smart-Money/ICT. Juge qualité OB/FVG/sweep, draw on liquidity, MSS."),
    "SENTIMENT":     (0.8, "Analyste sentiment. Juge news/positionnement retail vs le setup."),
    "MACRO":         (0.8, "Analyste macro. Juge risque event (CPI/FOMC/NFP), session, volatilité."),
    "RISK":          (1.0, "Risk manager profil MODÉRÉ. VETO si RR/conditions inacceptables (petits gains, risque borné)."),
}

_LINE = re.compile(r"VOTE\s*=\s*(LONG|SHORT|FLAT).*?SCORE\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.I | re.S)


@dataclass
class Opinion:
    role: str
    vote: str          # LONG | SHORT | FLAT
    score: float       # 0..10 (conviction)
    reason: str
    weight: float = 1.0


def _ctx(setup: Setup, market: dict) -> str:
    return (
        f"PAIR={setup.pair} TF={setup.tf} SIDE={setup.side} "
        f"CONF={setup.confidence:.0%} RR1={setup.rr1} "
        f"CONFLUENCES={'; '.join(setup.confluences)} "
        f"MTF={market.get('mtf_label','n/a')} SENTIMENT={market.get('sentiment','n/a')} "
        f"PAST={market.get('rag','n/a')}"
    )


def _fallback(role: str, setup: Setup, weight: float) -> Opinion:
    """Sans LLM : aligne sur le setup, pénalise la basse confiance ; RISK exige RR>=1."""
    if role == "RISK":
        ok = setup.rr1 >= 1.0 and setup.confidence >= 0.6
        return Opinion(role, setup.side.upper() if ok else "FLAT",
                       7.0 if ok else 4.0, "RR/confiance "+("ok" if ok else "faible"), weight)
    return Opinion(role, setup.side.upper(), round(setup.confidence * 10, 1),
                   "fallback déterministe (LLM indispo)", weight)


def run_analyst(role: str, setup: Setup, market: dict) -> Opinion:
    weight, brief = ROLES[role]
    prompt = (
        f"{brief}\nSetup: {_ctx(setup, market)}\n"
        f"Réponds EXACTEMENT une ligne: VOTE=LONG|SHORT|FLAT SCORE=0..10 REASON=<8 mots max>"
    )
    try:
        from forge_agents.forge_llm import forge_call, LLMTier
        out = forge_call(prompt, tier=LLMTier.HAIKU, max_tokens=60,
                         task_type="fast_extraction", node=f"analyst_{role}",
                         nano_mode=False, show_tokens=False)
        m = _LINE.search(out or "")
        if m:
            reason = (out[m.end():].strip() or out.strip())
            reason = re.sub(r"^\W*REASON\s*=\s*", "", reason, flags=re.I)[:80]
            return Opinion(role, m.group(1).upper(), float(m.group(2)), reason, weight)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return _fallback(role, setup, weight)


def run_all(setup: Setup, market: dict) -> list[Opinion]:
    return [run_analyst(r, setup, market) for r in ROLES]
