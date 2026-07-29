"""
data_feed.py — OHLCV forex. yfinance (1h/1d) si dispo, sinon fallback synthétique.

Dégradation gracieuse : aucune dépendance obligatoire pour faire tourner le pipeline.
1-minute fidèle MT5 (dukascopy) = Phase 3 (pas requis pour le conseiller MVP).
Cache parquet pour éviter re-télécharger.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from .config import FORGE_ROOT
import logging

logger = logging.getLogger(__name__)

_CACHE = FORGE_ROOT / "05_STATE" / "trading" / "cache"
_CACHE.mkdir(parents=True, exist_ok=True)

# paire Forge -> ticker yfinance
_YF = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X", "NZDUSD": "NZDUSD=X",
    "XAUUSD": "GC=F",
}
_TF_YF = {"1h": ("60m", "730d"), "4h": ("1h", "730d"), "1d": ("1d", "10y"), "15m": ("15m", "60d")}


def _synthetic(periods: int, tf: str, seed: int = 7) -> pd.DataFrame:
    """Random-walk OHLC déterministe (offline)."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.4, periods).cumsum()
    close = 100 + steps
    high = close + np.abs(rng.normal(0, 0.2, periods))
    low = close - np.abs(rng.normal(0, 0.2, periods))
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.date_range("2024-01-01", periods=periods, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(100, 1000, periods)}, index=idx)


def load(pair: str, tf: str = "1h", periods: int = 720) -> pd.DataFrame:
    """OHLCV pour (pair, tf). Tente yfinance, sinon synthétique. Toujours non-vide."""
    cache = _CACHE / f"{pair}_{tf}.parquet"
    try:
        import yfinance as yf  # optionnel
        ticker = _YF.get(pair.upper(), f"{pair.upper()}=X")
        interval, period = _TF_YF.get(tf, ("60m", "730d"))
        raw = yf.download(ticker, interval=interval, period=period,
                          progress=False, auto_adjust=False)
        if raw is not None and len(raw):
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
            if tf == "4h":
                df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                            "close": "last", "volume": "sum"}).dropna()
            df = df.tail(periods)
            try:
                df.to_parquet(cache)
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            return df
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    if cache.exists():
        try:
            return pd.read_parquet(cache).tail(periods)
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return _synthetic(periods, tf)


if __name__ == "__main__":
    d = load("EURUSD", "1h", 200)
    assert {"open", "high", "low", "close"}.issubset(d.columns) and len(d)
    print(f"data_feed OK: {len(d)} bars, last close={d['close'].iat[-1]:.4f}")
