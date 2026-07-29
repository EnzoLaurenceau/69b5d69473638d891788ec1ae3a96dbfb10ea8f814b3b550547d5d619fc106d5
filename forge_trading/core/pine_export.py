"""
pine_export.py — génère une stratégie Pine v5 depuis des Params backtest.

Logique simple (sweep + reclaim d'un swing, TP/SL en R) = traduisible 1:1 → testable
et paper-tradée nativement dans l'UI TradingView (le MCP ne place pas de paper-trade).
Déterministe (template, 0 token). Colle le .pine dans Pine Editor → Add to chart.
"""
from __future__ import annotations
from pathlib import Path
from .backtest import Params
from .config import MODERATE


def to_pine(params: Params, pair: str = "") -> str:
    both = "true" if params.both_sides else "false"
    return f"""//@version=5
// Auto-généré par Forge alpha_factory — {pair}  (CONSEIL/RECHERCHE, pas un conseil financier)
strategy("Forge SMC Sweep {pair}", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     pyramiding=0, calc_on_every_tick=false)

k        = input.int({params.k}, "Swing lookback")
tpR      = input.float({params.tp_r}, "TP (R)")
slBuf    = input.float({params.sl_buffer}, "SL buffer (ATR)")
maxHold  = input.int({params.max_hold}, "Max hold (bars)")
bothSide = input.bool({both}, "Both sides")

atr   = ta.atr({params.atr_n})
ph    = ta.pivothigh(high, k, k)
pl    = ta.pivotlow(low, k, k)
var float loLvl = na
var float hiLvl = na
loLvl := na(pl) ? loLvl : pl
hiLvl := na(ph) ? hiLvl : ph

longSig  = not na(loLvl) and low < loLvl and close > loLvl
shortSig = bothSide and not na(hiLvl) and high > hiLvl and close < hiLvl

floorR = 0.5 * atr
if longSig and strategy.position_size == 0
    stop = math.min(math.min(low, loLvl) - slBuf*atr, close - floorR)
    risk = close - stop
    strategy.entry("L", strategy.long)
    strategy.exit("Lx", "L", stop=stop, limit=close + tpR*risk)
if shortSig and strategy.position_size == 0
    stop = math.max(math.max(high, hiLvl) + slBuf*atr, close + floorR)
    risk = stop - close
    strategy.entry("S", strategy.short)
    strategy.exit("Sx", "S", stop=stop, limit=close - tpR*risk)

if strategy.position_size != 0 and (bar_index - strategy.opentrades.entry_bar_index(0)) >= maxHold
    strategy.close_all("time")
"""


def export(params: Params, pair: str, out_dir: Path = None) -> Path:
    out_dir = out_dir or MODERATE.state_dir
    path = out_dir / f"{pair}_strategy.pine"
    path.write_text(to_pine(params, pair), encoding="utf-8")
    return path


def _demo():
    p = export(Params(), "TEST")
    txt = p.read_text(encoding="utf-8")
    assert "strategy(" in txt and "strategy.entry" in txt
    print("pine_export self-check OK:", p)


if __name__ == "__main__":
    _demo()
