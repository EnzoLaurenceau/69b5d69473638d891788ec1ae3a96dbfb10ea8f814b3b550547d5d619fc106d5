"""
mcp_tradingview.py — couche TA TradingView, distillée (token-éco).

Token economy : on appelle la lib `tradingview_ta` EN DIRECT (0 token de schéma en
contexte) au lieu de passer par le serveur MCP. Le serveur MCP reste pour l'usage
interactif. Chaque appel est tracké via forge_mcp_pruner (visibilité éco).

Renvoie un dict COMPACT (reco + quelques indicateurs), jamais le blob complet.
Dégrade gracieusement si la lib absente.
"""
from __future__ import annotations
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# symbole Forge -> (exchange, screener, symbol) TradingView
_TV = {
    "EURUSD": ("FX_IDC", "forex", "EURUSD"), "GBPUSD": ("FX_IDC", "forex", "GBPUSD"),
    "USDJPY": ("FX_IDC", "forex", "USDJPY"), "AUDUSD": ("FX_IDC", "forex", "AUDUSD"),
    "USDCAD": ("FX_IDC", "forex", "USDCAD"), "NZDUSD": ("FX_IDC", "forex", "NZDUSD"),
    "XAUUSD": ("OANDA", "cfd", "XAUUSD"),
}
_TF = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}


def _track(tokens: int = 0):
    try:
        from forge_agents.forge_mcp_pruner import get_pruner
        get_pruner().record_call("tradingview_ta", tokens=tokens)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


def ta(pair: str, tf: str = "1h") -> Optional[dict]:
    """TA distillée pour (pair, tf) : {reco, buy, sell, neutral, RSI, MACD}. None si indispo."""
    try:
        from tradingview_ta import TA_Handler, Interval
        ex, screener, sym = _TV.get(pair.upper(), ("FX_IDC", "forex", pair.upper()))
        interval = {
            "15m": Interval.INTERVAL_15_MINUTES, "1h": Interval.INTERVAL_1_HOUR,
            "4h": Interval.INTERVAL_4_HOURS, "1d": Interval.INTERVAL_1_DAY,
        }.get(tf, Interval.INTERVAL_1_HOUR)
        h = TA_Handler(symbol=sym, exchange=ex, screener=screener, interval=interval)
        a = h.get_analysis()
        _track(tokens=80)  # ~taille du résumé distillé
        ind = a.indicators
        return {
            "reco": a.summary.get("RECOMMENDATION"),
            "buy": a.summary.get("BUY"), "sell": a.summary.get("SELL"),
            "neutral": a.summary.get("NEUTRAL"),
            "RSI": round(ind.get("RSI", float("nan")), 1),
            "MACD": round(ind.get("MACD.macd", float("nan")), 5),
        }
    except Exception:
        return None


def multi_tf(pair: str, tfs=("1d", "4h", "1h")) -> dict[str, Optional[dict]]:
    """Alignement multi-TF (HTF→LTF). Dict tf -> ta distillée."""
    return {tf: ta(pair, tf) for tf in tfs}


def alignment_score(mtf: dict[str, Optional[dict]]) -> tuple[float, str]:
    """Score d'accord directionnel multi-TF. (-1..1, label)."""
    vals = []
    for d in mtf.values():
        if not d or not d.get("reco"):
            continue
        r = d["reco"].upper()
        vals.append(1 if "BUY" in r else -1 if "SELL" in r else 0)
    if not vals:
        return 0.0, "n/a (lib tradingview_ta absente)"
    s = sum(vals) / len(vals)
    lab = "haussier aligné" if s > 0.3 else "baissier aligné" if s < -0.3 else "mixte"
    return round(s, 2), lab


if __name__ == "__main__":
    print("mcp_tradingview:", ta("EURUSD", "1h") or "tradingview_ta non installé (fallback ok)")
