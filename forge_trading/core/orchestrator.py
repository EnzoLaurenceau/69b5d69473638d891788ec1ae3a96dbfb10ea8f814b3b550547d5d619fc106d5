"""
orchestrator.py — super-orchestrateur trading (conseiller only).

Pipeline 1 paire : data (HTF+LTF) → setup SMC déterministe → confluence TA multi-TF
→ money-management → rapport fichier → log BigSet (flywheel).

CONSEILLER ONLY : aucune exécution broker (HITL gate Phase 4). Phase 1 = pas de LLM ;
analystes + jury MiroFish = Phase 2 (hook prêt, no-op si absent).
"""
from __future__ import annotations
from pathlib import Path

from .config import TradingConfig, MODERATE
from . import data_feed, smc_engine, money_manager, mcp_tradingview, report, rag
from .jury import run_jury
import logging

logger = logging.getLogger(__name__)


def _log_bigset(pair: str, setup, verdict):
    """Flywheel : enregistre le setup dans forge_experience_db (BigSet). No-op si absent."""
    try:
        from forge_agents.forge_experience_db import get_experience_db, Experience
        get_experience_db().record(Experience(
            task=f"trade_setup {pair}",
            used_nodes=["smc_engine", "jury"] + (setup.confluences if setup else []),
            outcome="partial",            # issue réelle mise à jour quand le trade se résout
            reason=(verdict.note if verdict else "no setup"),
            quality_score=(setup.confidence * 10) if setup else 0.0,
            domain="trading",
            metadata={"pair": pair, "side": getattr(setup, "side", None),
                      "confidence": getattr(setup, "confidence", 0.0),
                      "verdict": getattr(verdict, "decision", None)},
        ))
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


def analyze(pair: str, equity: float = 10_000.0, cfg: TradingConfig = MODERATE) -> Path:
    """Analyse une paire et écrit un rapport conseil. Retourne le chemin."""
    # 1. data biais HTF + TF d'entrée
    htf = data_feed.load(pair, cfg.htf, periods=400)
    ltf = data_feed.load(pair, cfg.entry_tf, periods=720)

    # 2. biais HTF découplé, puis setup déterministe sur LTF (0 token)
    bias = smc_engine.htf_bias(htf, cfg.htf_ema)
    setup = smc_engine.detect_setup(
        ltf, bias=bias, k=cfg.swing_lookback, ema=cfg.htf_ema,
        require_close_back=cfg.sweep_close_back, pair=pair, tf=cfg.entry_tf,
    )

    # 3. confluence TA multi-TF (distillée, token-éco) — facultatif
    mtf = mcp_tradingview.multi_tf(pair, (cfg.htf, cfg.entry_tf))
    _, mtf_label = mcp_tradingview.alignment_score(mtf)

    # 4. jury (avis comparés) — UNIQUEMENT si setup (sinon 0 token LLM)
    verdict = None
    if setup:
        market = {"mtf_label": mtf_label, "sentiment": "n/a",
                  "rag": rag.retrieve(setup), "calibration": rag.calibration(pair)}
        verdict = run_jury(setup, market)
        rag.index(setup, verdict.note)            # flywheel : enrichit le RAG

    # 5. money-management (seulement si le jury n'a pas rejeté)
    plan = money_manager.build_plan(setup, equity, cfg) \
        if setup and verdict and verdict.decision != "REJECT" else None

    # 6. rapport + 7. flywheel BigSet
    path = report.render(pair, setup, plan, mtf_label, cfg, verdict=verdict)
    _log_bigset(pair, setup, verdict)
    return path


if __name__ == "__main__":
    p = analyze("EURUSD")
    print("rapport:", p)
