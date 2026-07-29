"""
config.py — profil de risque + money-management + paramètres SMC.

Profil MODÉRÉ + philosophie "petits gains accumulés" (data flywheel) :
fréquence haute, TP1 rapide partiel, breakeven, runner court, caps stricts.
Tout est tunable — une seule dataclass, pas de config externe (YAGNI).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = FORGE_ROOT / "05_STATE" / "trading"


@dataclass
class TradingConfig:
    # ── Risque (profil MODÉRÉ) ──────────────────────────────
    risk_per_trade_pct: float = 0.5      # % equity risqué / trade
    daily_loss_cap_pct: float = 2.0      # stop trading si atteint
    weekly_loss_cap_pct: float = 4.0
    max_concurrent: int = 3              # positions simultanées max

    # ── Petits gains (échelle TP courte) ────────────────────
    tp1_r: float = 1.0                   # TP1 à 1R — sortie partielle rapide
    tp1_partial: float = 0.6             # 60% fermé à TP1
    move_be_after_tp1: bool = True       # SL → breakeven après TP1
    tp2_r: float = 2.0                   # runner court

    # ── Détection SMC (fenêtres déterministes) ──────────────
    swing_lookback: int = 2              # pivots fractals (k bougies de chaque côté)
    sweep_close_back: bool = True        # exige clôture revenue dans le range
    htf_ema: int = 50                    # pente EMA = proxy biais HTF
    min_confluences: int = 3             # confluences requises pour valider un setup

    # ── Univers & timeframes ────────────────────────────────
    pairs: list[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD",
    ])
    entry_tf: str = "1h"                 # TF d'exécution
    htf: str = "4h"                      # TF de biais
    sessions: list[str] = field(default_factory=lambda: ["London", "NY"])

    # ── Chemins ─────────────────────────────────────────────
    state_dir: Path = STATE_DIR

    def __post_init__(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)


MODERATE = TradingConfig()
