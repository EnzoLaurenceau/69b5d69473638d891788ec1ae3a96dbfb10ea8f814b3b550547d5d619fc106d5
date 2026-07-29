"""
backtest.py — backtester vectorisé minimal (pas de vectorbt/numba).

Stratégie SMC simplifiée bidirectionnelle (sweep + reclaim d'un swing), entrée à
l'open de la bougie suivante (réaliste), sortie TP/SL ou après max_hold bougies.
PnL exprimé en R (multiples de risque) → equity = cumsum(R). ~1 position à la fois.

Logique simple = traduisible Python→Pine/MQL5 (contrainte de la vidéo).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from .smc_engine import swing_points


@dataclass
class Params:
    k: int = 2                 # fenêtre fractale (swing)
    tp_r: float = 1.0          # TP en multiples de R (petits gains)
    sl_buffer: float = 0.1     # marge SL au-delà du sweep (en ATR)
    max_hold: int = 12         # bougies max en position
    atr_n: int = 14
    both_sides: bool = True
    trend_ema: int = 50        # filtre biais : sweep DANS le sens de la tendance (0 = off)


@dataclass
class Result:
    trades: list[float] = field(default_factory=list)   # PnL par trade en R
    equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    @property
    def n(self) -> int: return len(self.trades)

    def stats(self) -> dict:
        r = np.array(self.trades, dtype=float)
        if r.size == 0:
            return {"trades": 0, "pf": 0.0, "win_rate": 0.0, "sharpe": 0.0,
                    "max_dd": 0.0, "total_r": 0.0, "expectancy": 0.0}
        pos, neg = r[r > 0].sum(), r[r < 0].sum()
        eq = r.cumsum()
        dd = (np.maximum.accumulate(eq) - eq).max()
        return {
            "trades": int(r.size),
            "pf": float(pos / abs(neg)) if neg < 0 else float("inf"),
            "win_rate": float((r > 0).mean()),
            "sharpe": float(r.mean() / r.std()) if r.std() > 0 else 0.0,  # par-trade
            "max_dd": float(dd),
            "total_r": float(r.sum()),
            "expectancy": float(r.mean()),
        }


def _atr(h, l, c, n):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = np.full(len(c), np.nan)
    if len(tr) >= n:
        atr[n:] = pd.Series(tr).rolling(n).mean().to_numpy()[n - 1:]
    atr = pd.Series(atr).bfill().ffill().to_numpy()
    return np.nan_to_num(atr, nan=np.nanmean(np.abs(h - l)) or 1e-6)


def run(df: pd.DataFrame, p: Params) -> Result:
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(df)
    is_hi, is_lo = swing_points(df, p.k)
    # niveau du dernier swing low/high connu à chaque barre (forward-fill)
    lo_lvl = pd.Series(np.where(is_lo.to_numpy(), l, np.nan)).ffill().to_numpy()
    hi_lvl = pd.Series(np.where(is_hi.to_numpy(), h, np.nan)).ffill().to_numpy()
    atr = _atr(h, l, c, p.atr_n)
    ema = (df["close"].ewm(span=p.trend_ema, adjust=False).mean().to_numpy()
           if p.trend_ema else None)

    trades: list[float] = []
    eq_t, eq_v, cum = [], [], 0.0
    i = p.k + 1
    while i < n - 1:
        up = ema is None or c[i] >= ema[i]        # biais haussier
        dn = ema is None or c[i] <= ema[i]        # biais baissier
        long_sig = up and not np.isnan(lo_lvl[i]) and l[i] < lo_lvl[i] and c[i] > lo_lvl[i]
        short_sig = dn and p.both_sides and not np.isnan(hi_lvl[i]) and h[i] > hi_lvl[i] and c[i] < hi_lvl[i]
        side = "long" if long_sig else ("short" if short_sig else None)
        if side is None:
            i += 1
            continue
        entry = o[i + 1]
        floor = 0.5 * atr[i]                       # évite les micro-stops que le bruit tape
        if side == "long":
            stop = min(min(l[i], lo_lvl[i]) - p.sl_buffer * atr[i], entry - floor)
            risk = entry - stop
            tp = entry + p.tp_r * risk
        else:
            stop = max(max(h[i], hi_lvl[i]) + p.sl_buffer * atr[i], entry + floor)
            risk = stop - entry
            tp = entry - p.tp_r * risk
        if risk <= 0:
            i += 1
            continue
        # simule la détention
        outcome = None
        j = i + 1
        end = min(i + 1 + p.max_hold, n)
        while j < end:
            if side == "long":
                if l[j] <= stop: outcome = -1.0; break
                if h[j] >= tp:  outcome = p.tp_r; break
            else:
                if h[j] >= stop: outcome = -1.0; break
                if l[j] <= tp:  outcome = p.tp_r; break
            j += 1
        if outcome is None:  # clôture au marché en fin de fenêtre
            exitp = c[min(j, n - 1)]
            outcome = ((exitp - entry) if side == "long" else (entry - exitp)) / risk
        trades.append(float(outcome))
        cum += outcome
        eq_t.append(df.index[min(j, n - 1)]); eq_v.append(cum)
        i = j + 1  # pas de chevauchement
    return Result(trades=trades, equity=pd.Series(eq_v, index=pd.Index(eq_t)))


def _demo():
    rng = np.random.default_rng(3)
    n = 600
    close = 100 + rng.normal(0, 0.5, n).cumsum()
    df = pd.DataFrame({"open": np.r_[close[0], close[:-1]],
                       "high": close + np.abs(rng.normal(0, 0.3, n)),
                       "low": close - np.abs(rng.normal(0, 0.3, n)),
                       "close": close},
                      index=pd.date_range("2024-01-01", periods=n, freq="h"))
    res = run(df, Params())
    s = res.stats()
    assert s["trades"] > 0, "doit générer des trades sur 600 barres"
    assert -1.0 <= s["win_rate"] <= 1.0
    print("backtest self-check OK:", s)


if __name__ == "__main__":
    _demo()
