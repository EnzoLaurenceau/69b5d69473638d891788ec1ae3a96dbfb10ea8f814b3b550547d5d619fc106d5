"""
money_manager.py — sizing + échelle TP "petits gains" + caps. Profil MODÉRÉ.

Fonctions pures (testables). Aucune exécution broker — calcule un PLAN.
Philosophie : TP1 rapide partiel + breakeven → encaisse souvent, risque borné.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .config import TradingConfig
from .smc_engine import Setup


@dataclass
class TradePlan:
    units: float                      # taille position (unités base)
    risk_amount: float                # $ risqué
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp1_close_pct: float              # fraction fermée à TP1
    move_be_after_tp1: bool
    notes: list[str] = field(default_factory=list)


def position_size(equity: float, risk_pct: float, entry: float, stop: float,
                  pip_value: float = 1.0) -> tuple[float, float]:
    """Unités telles que (perte au stop) = risk_pct% de l'equity. (units, risk_$)."""
    risk_amount = equity * (risk_pct / 100.0)
    per_unit_loss = abs(entry - stop) * pip_value
    if per_unit_loss <= 0:
        return 0.0, 0.0
    return risk_amount / per_unit_loss, risk_amount


def caps_ok(equity: float, day_pnl: float, week_pnl: float, cfg: TradingConfig) -> tuple[bool, str]:
    """Vrai si on peut encore trader (caps perte jour/semaine non atteints)."""
    if day_pnl <= -equity * cfg.daily_loss_cap_pct / 100.0:
        return False, f"daily loss cap {cfg.daily_loss_cap_pct}% atteint — STOP"
    if week_pnl <= -equity * cfg.weekly_loss_cap_pct / 100.0:
        return False, f"weekly loss cap {cfg.weekly_loss_cap_pct}% atteint — STOP"
    return True, "ok"


def build_plan(setup: Setup, equity: float, cfg: TradingConfig,
               pip_value: float = 1.0) -> TradePlan:
    units, risk_amount = position_size(equity, cfg.risk_per_trade_pct,
                                       setup.entry, setup.stop, pip_value)
    notes = [
        f"risque {cfg.risk_per_trade_pct}% = ${risk_amount:.2f}",
        f"TP1 {cfg.tp1_r}R: ferme {cfg.tp1_partial:.0%} (petit gain rapide)",
    ]
    if cfg.move_be_after_tp1:
        notes.append("SL -> breakeven apres TP1")
    return TradePlan(
        units=round(units, 4), risk_amount=round(risk_amount, 2),
        entry=setup.entry, stop=setup.stop, tp1=setup.tp1, tp2=setup.tp2,
        tp1_close_pct=cfg.tp1_partial, move_be_after_tp1=cfg.move_be_after_tp1,
        notes=notes,
    )


def _demo():
    from .config import MODERATE
    from .smc_engine import Setup
    s = Setup(side="long", entry=100.0, stop=99.0, tp1=101.0, tp2=103.0,
              confidence=0.8, confluences=["x"], rr1=1.0)
    units, risk = position_size(10_000, 0.5, 100.0, 99.0)
    assert abs(risk - 50.0) < 1e-6, "0.5% de 10k = 50$"
    assert abs(units - 50.0) < 1e-6, "stop=1.0 -> 50 unités"
    ok, _ = caps_ok(10_000, -250, -100, MODERATE)
    assert not ok, "daily cap 2% (=200$) doit bloquer à -250$"
    plan = build_plan(s, 10_000, MODERATE)
    assert plan.units > 0 and plan.tp1_close_pct == MODERATE.tp1_partial
    print("money_manager self-check OK:", plan)


if __name__ == "__main__":
    _demo()
