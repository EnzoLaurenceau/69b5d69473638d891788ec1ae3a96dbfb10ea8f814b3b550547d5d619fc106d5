"""
rag.py — RAG trading + flywheel BigSet.

retrieve() : avant les analystes, ramène des setups passés similaires (turbovec) pour
contextualiser (string court, token-éco). index() : stocke le setup courant → enrichit
le RAG. Le résultat des trades (BigSet/forge_experience_db) repondère la confiance.

Tout best-effort : si turbovec/BigSet absents → renvoie "n/a" sans casser.
"""
from __future__ import annotations
from .smc_engine import Setup
import logging

logger = logging.getLogger(__name__)

_AGENT = "TRADING"


def _key(setup: Setup) -> str:
    return f"{setup.pair} {setup.tf} {setup.side} | " + "; ".join(setup.confluences)


def retrieve(setup: Setup, k: int = 3) -> str:
    """Top-k setups passés similaires (résumé court)."""
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain
        hits = get_turbovec_brain().search(_key(setup), k=k)
        if hits:
            return " || ".join(str(h.get("text", h))[:90] for h in hits[:k])
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return "n/a"


def index(setup: Setup, verdict_note: str = "") -> None:
    """Enrichit le RAG avec le setup courant (flywheel)."""
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain
        get_turbovec_brain().store(f"{_key(setup)} conf={setup.confidence} {verdict_note}",
                                   agent=_AGENT)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


def calibration(pair: str) -> str:
    """Stat de réputation depuis BigSet (win-rate domaine trading) si dispo."""
    try:
        from forge_agents.forge_experience_db import get_experience_db
        db = get_experience_db()
        exps = [e for e in getattr(db, "experiences", lambda: [])() if getattr(e, "domain", "") == "trading"]
        if exps:
            wins = sum(1 for e in exps if e.outcome == "success")
            return f"{wins}/{len(exps)} setups gagnants historiques"
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return "n/a (flywheel en démarrage)"
