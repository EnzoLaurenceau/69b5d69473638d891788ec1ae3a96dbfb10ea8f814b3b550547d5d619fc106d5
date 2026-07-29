#!/usr/bin/env python
"""
run_trading.py — CLI du super-orchestrateur trading (conseiller only).

  python run_trading.py --analyze EURUSD [--equity 10000]
  python run_trading.py --selfcheck          # vérifs déterministes (offline, 0 dépendance)
  python run_trading.py --factory "<logique>"  # Phase 3 (alpha factory) — stub

TOKEN ESTIMATE affiché avant exécution (règle CLAUDE.md). Tout LLM = tier FREE (Phase 2+).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).resolve().parent / "00_CORE"))


def _token_estimate(task: str):
    try:
        from forge_agents.token_tracker import get_tracker
        t = get_tracker()
        t.estimate_budget(task)
        print(t.render_estimate_table())
    except Exception:
        print(f"[TOKEN ESTIMATE] {task}: Phase 1 déterministe ≈ 0 token LLM (SMC pandas).")


def main():
    ap = argparse.ArgumentParser(description="Super-orchestrateur trading Forge (conseiller only)")
    ap.add_argument("--analyze", metavar="PAIR", help="analyse une paire (ex: EURUSD)")
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--selfcheck", action="store_true", help="vérifs déterministes offline")
    ap.add_argument("--factory", metavar="PAIR", help="alpha factory : optimise+walk-forward+rapport HTML")
    ap.add_argument("--tf", default="1h", help="timeframe factory (1h/4h/1d)")
    ap.add_argument("--trials", type=int, default=40, help="essais optuna (in-sample)")
    ap.add_argument("--pine", action="store_true", help="exporter aussi la stratégie Pine v5")
    args = ap.parse_args()

    if args.selfcheck:
        from forge_trading.core import smc_engine, money_manager, backtest, pine_export
        smc_engine._demo()
        money_manager._demo()
        backtest._demo()
        pine_export._demo()
        print("ALL SELF-CHECKS OK")
        return

    if args.factory:
        pair = args.factory.upper()
        _token_estimate(f"factory {pair}")
        from forge_trading.core import data_feed, alpha_factory
        from forge_trading.core.backtest import Params
        df = data_feed.load(pair, args.tf, periods=3000)
        out = alpha_factory.run_factory(pair, df, n_trials=args.trials)
        print(f"\n✅ Factory {pair}: survivor={out['survivor']} | WF={out['walk_forward']}")
        print(f"   in-sample={out['in_sample']}\n   out-sample={out['out_sample']}")
        print(f"   rapport: {out['report']}")
        if args.pine:
            from forge_trading.core.pine_export import export
            print(f"   pine: {export(Params(**out['params']), pair)}")
        return

    if args.analyze:
        _token_estimate(f"analyze {args.analyze}")
        from forge_trading.core.orchestrator import analyze
        path = analyze(args.analyze.upper(), equity=args.equity)
        print(f"\n✅ Rapport conseil (AUCUN ordre placé): {path}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
