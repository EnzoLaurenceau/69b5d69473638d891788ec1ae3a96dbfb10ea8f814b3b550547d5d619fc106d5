"""
report.py — rapport conseil markdown → FICHIER (jamais inline, règle Fable).
"""
from __future__ import annotations
import datetime
from pathlib import Path

from .config import TradingConfig
from .smc_engine import Setup
from .money_manager import TradePlan


def render(pair: str, setup: Setup | None, plan: TradePlan | None,
           mtf_label: str, cfg: TradingConfig, extra: dict | None = None,
           verdict=None) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = cfg.state_dir / f"{pair}_{ts}.md"
    extra = extra or {}
    lines = [
        f"# Conseil trading — {pair} ({cfg.entry_tf})",
        f"_généré {ts} — **CONSEILLER ONLY, aucun ordre placé**_", "",
        f"**Alignement multi-TF :** {mtf_label}",
        f"**Sentiment/news :** {extra.get('sentiment', 'n/a (phase 2)')}", "",
    ]
    if verdict is not None:
        lines += [
            f"## 🧑‍⚖️ Jury (avis comparés) — **{verdict.decision}** ({verdict.side})",
            f"_{verdict.note}_", "",
            "| Analyste | Vote | Score | Raison |", "|---|---|---|---|",
            *[f"| {o.role} | {o.vote} | {o.score:.1f} | {o.reason} |" for o in verdict.opinions],
            "",
        ]
    if not setup:
        lines += ["## Verdict : PAS DE SETUP", "Aucune confluence OB+FVG+sweep suffisante maintenant.",
                  "Attendre une prise de liquidité + MSS dans le sens du biais HTF."]
    else:
        ok = setup.confidence * 5 >= cfg.min_confluences
        lines += [
            f"## Setup {setup.side.upper()} — confiance {setup.confidence:.0%} "
            f"({'VALIDE' if ok else 'FAIBLE — sous le seuil'})",
            f"- Confluences: {', '.join(setup.confluences)}",
            f"- Entrée: `{setup.entry:.5f}`  Stop: `{setup.stop:.5f}`  "
            f"TP1: `{setup.tp1:.5f}` (1R)  TP2: `{setup.tp2:.5f}`",
            f"- RR vers TP1: {setup.rr1:.2f}  •  bougie: {setup.bar_time}", "",
        ]
        if plan:
            lines += [
                "## Plan money-management (MODÉRÉ + petits gains)",
                f"- Taille: `{plan.units}` unités  •  risque: ${plan.risk_amount}",
                f"- TP1 ferme {plan.tp1_close_pct:.0%}"
                + ("  •  SL→breakeven ensuite" if plan.move_be_after_tp1 else ""),
                "- " + "  \n- ".join(plan.notes),
            ]
    lines += ["", "---", "_Non un conseil financier. Vérifie avant d'agir._"]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
