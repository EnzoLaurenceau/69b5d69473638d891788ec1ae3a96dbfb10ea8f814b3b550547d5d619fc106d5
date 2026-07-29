"""
smc_engine.py — confirmation model OB + FVG + Liquidity Sweep (déterministe).

ZÉRO token LLM. Encode la séquence Smart-Money / ICT publique standard :
  1. biais HTF (proxy = pente EMA)            -> direction recherchée
  2. liquidity sweep d'un swing opposé        -> déclencheur (stop-hunt)
  3. MSS/BOS dans le sens du biais            -> confirmation de retournement
  4. order block (dernière bougie opposée)    -> zone d'entrée
  5. FVG (imbalance) dans la jambe MSS         -> confluence
  6. entry OB/FVG, SL au-delà du sweep, TP vers liquidité opposée

Sortie = Setup (dataclass). Les LLM (analystes/jury) ne font QUE pondérer ensuite.

Convention OHLC : DataFrame colonnes open/high/low/close[/volume], index temporel croissant.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal

import numpy as np
import pandas as pd

Side = Literal["long", "short"]


@dataclass
class Setup:
    side: Side
    entry: float
    stop: float
    tp1: float
    tp2: float
    confidence: float                       # 0..1 = confluences/total
    confluences: list[str] = field(default_factory=list)
    rr1: float = 0.0                        # reward:risk vers tp1
    bar_time: str = ""
    pair: str = ""
    tf: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# ── détecteurs primitifs ─────────────────────────────────────────────────────

def swing_points(df: pd.DataFrame, k: int = 2) -> tuple[pd.Series, pd.Series]:
    """Pivots fractals : high pivot si high[i] est le max de [i-k, i+k]."""
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    is_hi = np.zeros(n, dtype=bool)
    is_lo = np.zeros(n, dtype=bool)
    for i in range(k, n - k):
        w_hi = hi[i - k:i + k + 1]
        w_lo = lo[i - k:i + k + 1]
        if hi[i] == w_hi.max() and (w_hi.argmax() == k):
            is_hi[i] = True
        if lo[i] == w_lo.min() and (w_lo.argmin() == k):
            is_lo[i] = True
    return pd.Series(is_hi, index=df.index), pd.Series(is_lo, index=df.index)


def fvg(df: pd.DataFrame, i: int) -> Optional[Side]:
    """FVG 3-bougies à la bougie i (gap entre i-2 et i). bullish/bearish."""
    if i < 2:
        return None
    if df["low"].iat[i] > df["high"].iat[i - 2]:
        return "long"       # imbalance haussière
    if df["high"].iat[i] < df["low"].iat[i - 2]:
        return "short"      # imbalance baissière
    return None


def htf_bias(df: pd.DataFrame, ema: int = 50) -> Side:
    """Proxy biais : pente de l'EMA sur les dernières bougies."""
    e = df["close"].ewm(span=ema, adjust=False).mean()
    return "long" if e.iat[-1] >= e.iat[-min(len(e), ema)] else "short"


# ── confirmation model ───────────────────────────────────────────────────────

def detect_setup(df: pd.DataFrame, bias: Optional[Side] = None, k: int = 2, ema: int = 50,
                 require_close_back: bool = True, pair: str = "", tf: str = "") -> Optional[Setup]:
    """
    Cherche un setup confirmé se terminant sur la DERNIÈRE bougie close.
    `bias` = direction HTF (découplée du LTF — sinon le sweep fausse la lecture).
    Si None, fallback sur la pente EMA du df fourni. Retourne None si pas de confluence.
    """
    if len(df) < max(k * 2 + 3, ema):
        return None

    if bias is None:
        bias = htf_bias(df, ema)
    is_hi, is_lo = swing_points(df, k)
    o, h, l, c = (df[col].to_numpy() for col in ("open", "high", "low", "close"))
    n = len(df)
    i = n - 1                                   # bougie de signal = dernière close

    swing_his = np.where(is_hi.to_numpy())[0]
    swing_los = np.where(is_lo.to_numpy())[0]
    if len(swing_his) == 0 or len(swing_los) == 0:
        return None

    conf: list[str] = []

    if bias == "long":
        prior_low_idx = swing_los[swing_los < i]
        if len(prior_low_idx) == 0:
            return None
        sl_level = l[prior_low_idx[-1]]
        conf.append(f"HTF bias long (EMA{ema})")
        # 2. sweep sous le swing low : mèche dépasse, clôture revient au-dessus
        swept = l[i] < sl_level and (c[i] > sl_level if require_close_back else True)
        if not swept:
            return None
        conf.append("liquidity sweep (buy-side)")
        # 3. MSS : clôture au-dessus du dernier swing high opposé
        prior_hi_idx = swing_his[swing_his < i]
        if len(prior_hi_idx):
            if c[i] > h[prior_hi_idx[-1]]:
                conf.append("MSS/BOS up")
        # 4. order block : dernière bougie baissière avant la bougie de signal
        ob_idx = next((j for j in range(i - 1, max(i - 6, -1), -1) if c[j] < o[j]), None)
        ob_top = h[ob_idx] if ob_idx is not None else o[i]
        if ob_idx is not None:
            conf.append("order block (bull)")
        # 5. FVG dans la jambe
        if any(fvg(df, j) == "long" for j in range(max(i - 3, 2), i + 1)):
            conf.append("FVG bull")
        entry = ob_top
        stop = min(sl_level, l[i]) - 1e-9
        # 6. TP vers liquidité opposée (dernier swing high) sinon ratio
        tp_liq = h[prior_hi_idx[-1]] if len(prior_hi_idx) else entry + 2 * (entry - stop)
        side: Side = "long"
    else:
        prior_hi_idx = swing_his[swing_his < i]
        if len(prior_hi_idx) == 0:
            return None
        sh_level = h[prior_hi_idx[-1]]
        conf.append(f"HTF bias short (EMA{ema})")
        swept = h[i] > sh_level and (c[i] < sh_level if require_close_back else True)
        if not swept:
            return None
        conf.append("liquidity sweep (sell-side)")
        prior_low_idx = swing_los[swing_los < i]
        if len(prior_low_idx):
            if c[i] < l[prior_low_idx[-1]]:
                conf.append("MSS/BOS down")
        ob_idx = next((j for j in range(i - 1, max(i - 6, -1), -1) if c[j] > o[j]), None)
        ob_bot = l[ob_idx] if ob_idx is not None else o[i]
        if ob_idx is not None:
            conf.append("order block (bear)")
        if any(fvg(df, j) == "short" for j in range(max(i - 3, 2), i + 1)):
            conf.append("FVG bear")
        entry = ob_bot
        stop = max(sh_level, h[i]) + 1e-9
        tp_liq = l[prior_low_idx[-1]] if len(prior_low_idx) else entry - 2 * (stop - entry)
        side = "short"

    risk = abs(entry - stop)
    if risk <= 0:
        return None
    tp1 = entry + risk if side == "long" else entry - risk        # 1R = petit gain rapide
    tp2 = tp_liq
    rr1 = abs(tp1 - entry) / risk

    total = 5  # bias, sweep, MSS, OB, FVG
    return Setup(
        side=side, entry=float(entry), stop=float(stop), tp1=float(tp1), tp2=float(tp2),
        confidence=round(len(conf) / total, 2), confluences=conf, rr1=round(rr1, 2),
        bar_time=str(df.index[i]), pair=pair, tf=tf,
    )


# ── self-check (ponytail: une vérif runnable) ────────────────────────────────

def _demo():
    """LTF avec swing low récent (idx 54) puis bougie de sweep finale + biais HTF long."""
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = np.full(n, 100.0)
    close[:40] = np.linspace(101, 99.6, 40)      # structure
    close[40:54] = 99.6
    close[52], close[53], close[54], close[55], close[56] = 100.0, 99.5, 99.0, 99.4, 100.0  # pivot low @54
    close[57], close[58], close[59] = 99.9, 99.7, 99.6                                       # 58 baissière (OB)
    high = close + 0.2
    low = close - 0.2
    low[54] = 99.0
    low[59] = 98.4                                # mèche de sweep sous le swing low (99.0)
    high[59] = 99.7                               # clôture revient au-dessus (99.6 > 99.0)
    open_ = np.r_[close[0], close[:-1]]
    open_[58] = 99.95                             # bar 58 bearish (close 99.7 < open)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
    s = detect_setup(df, bias="long", k=2, ema=20, pair="TEST", tf="1h")
    assert s is not None, "setup attendu sur sweep long synthétique"
    assert s.side == "long", f"side long attendu, got {s.side}"
    assert s.stop < s.entry < s.tp1, f"ordre prix long incohérent: {s.as_dict()}"
    assert "liquidity sweep (buy-side)" in s.confluences
    assert s.rr1 > 0
    print("smc_engine self-check OK:", s.as_dict())


if __name__ == "__main__":
    _demo()
