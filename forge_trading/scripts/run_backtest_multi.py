#!/usr/bin/env python3
"""
Script de backtest multi-plateforme.
Teste la stratégie sur TOUTES les plateformes avec conditions réelles.
"""

import argparse
import sys
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd

# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))

from forge_trading.backtesting.engine import BacktestEngine
from forge_trading.backtesting.multi_platform import MultiPlatformBacktester
from forge_trading.backtesting.data_loader import HistoricalDataLoader
from forge_trading.backtesting.data_validator import validate_historical_data, get_data_quality_report
from forge_trading.strategies.micro_arb import MicroArbitrageStrategy
from forge_trading.reflection_db.database import ReflectionDatabase
from forge_trading.strategies.forge_integration import ForgeReflectionIntegration
from forge_trading.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_strategy(name: str, params: dict = None):
    """Factory pour les stratégies."""
    strategies = {
        'micro_arb': MicroArbitrageStrategy,
    }
    if name not in strategies:
        raise ValueError(f"Stratégie inconnue: {name}")
    return strategies[name](params)


def run_multi_platform_backtest(
    strategy_name: str,
    pair: str,
    years: int,
    initial_capital: float,
    timeframe: str = "1d",
    platform_type: str = None,
    verbose: bool = False
):
    """
    Exécute le backtest sur toutes les plateformes.
    """
    logger.info("="*70)
    logger.info("BACKTEST MULTI-PLATEFORME")
    logger.info(f"Stratégie: {strategy_name} | Paire: {pair} | Période: {years} ans")
    logger.info(f"Capital: ${initial_capital}")
    logger.info("="*70)
    
    # 1. Charger les données
    loader = HistoricalDataLoader()
    
    try:
        if pair.endswith("USD") and not pair.startswith("BTC") and not pair.startswith("ETH"):
            data = loader.load_forex(pair, years, timeframe)
            market = "forex"
        else:
            data = loader.load_crypto(pair, years, timeframe)
            market = "crypto"
    except Exception as e:
        logger.warning(f"Erreur chargement données réelles: {e}")
        logger.info("Utilisation de données synthétiques...")
        data = loader.generate_synthetic_data(years)
        market = "forex"
    
    # 2. Valider les données
    logger.info("\n--- VALIDATION DES DONNÉES ---")
    is_valid, report = validate_historical_data(data, pair, strict=False)
    print(get_data_quality_report(data, pair))
    
    if not is_valid:
        logger.warning("Données avec problèmes - résultats peuvent être imprécis")
    
    # 3. Créer la stratégie
    strategy = get_strategy(strategy_name)
    
    # 4. Backtest multi-plateforme
    logger.info("\n--- BACKTEST MULTI-PLATEFORME ---")
    backtester = MultiPlatformBacktester(strategy, initial_capital)
    
    comparison = backtester.compare_platforms(data, pair, verbose)
    
    # 5. Afficher les résultats
    print("\n" + "="*70)
    print("COMPARAISON DES PLATEFORMES")
    print("="*70)
    
    if len(comparison) > 0:
        # Formater le DataFrame pour l'affichage
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 20)
        
        print("\n" + comparison.to_string(index=False))
        
        # 6. Trouver la meilleure plateforme
        best = backtester.find_best_platform(data, pair, min_win_rate=0.51, min_profit_factor=1.0)
        
        print("\n" + "="*70)
        print("MEILLEURE PLATEFORME")
        print("="*70)
        
        if best:
            print(f"\n🏆 {best.platform_name}")
            print(f"   Win Rate: {best.effective_win_rate:.1%}")
            print(f"   Net PnL: ${best.net_after_fees:.2f}")
            print(f"   Profit Factor: {best.result.profit_factor:.2f}")
            print(f"   Max Drawdown: {best.result.max_drawdown:.1%}")
            print(f"   Commission: {best.platform_config.commission_percent:.4%}")
            print(f"   Spread: {best.platform_config.spread_pips} pips")
        else:
            print("\n❌ Aucune plateforme profitable trouvée avec les critères actuels")
        
        # 7. Analyse détaillée par type
        print("\n" + "="*70)
        print("ANALYSE PAR TYPE DE PLATEFORME")
        print("="*70)
        
        for ptype in ['forex_ecn', 'forex_standard', 'dex_v3', 'dex_v2', 'cex']:
            type_results = comparison[comparison['Type'] == ptype]
            if len(type_results) > 0:
                print(f"\n📊 {ptype.upper()}:")
                
                # Convertir les win rates en float pour la moyenne
                wr_values = type_results['Win Rate'].str.rstrip('%').astype(float) / 100
                avg_wr = wr_values.mean()
                
                # Convertir les PnL en float
                pnl_values = type_results['Net PnL'].str.replace('$', '').str.replace(',', '').astype(float)
                avg_pnl = pnl_values.mean()
                
                print(f"   Plateformes testées: {len(type_results)}")
                print(f"   Win Rate moyen: {avg_wr:.1%}")
                print(f"   PnL moyen: ${avg_pnl:.2f}")
                
                if avg_wr >= 0.51:
                    print(f"   ✅ Rentable en moyenne")
                else:
                    print(f"   ❌ Non rentable en moyenne")
        
        # 8. Sauvegarder dans la DB de réflexion
        logger.info("\n--- SAUVEGARDE DANS LA BASE DE RÉFLEXION ---")
        db = ReflectionDatabase()
        reflection = ForgeReflectionIntegration(db)
        
        # Sauvegarder le meilleur résultat
        if best and best.result.trades:
            for trade in best.result.trades:
                trade.metadata['platform'] = best.platform_name
                trade.metadata['platform_type'] = best.platform_config.platform_type.value
                reflection.on_trade_closed(trade)
            
            summary = db.get_performance_summary(strategy_name)
            print(f"\n📚 Base de réflexion mise à jour:")
            print(f"   Trades sauvegardés: {summary['total_trades']}")
            print(f"   Win rate global: {summary['win_rate']:.1%}")
            print(f"   Leçons apprises: {summary['lessons_learned']}")
        
        # 9. Exporter le rapport
        report_path = Path(__file__).parent.parent / "logs" / f"multi_platform_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        comparison.to_csv(report_path, index=False)
        print(f"\n📄 Rapport exporté: {report_path}")
    
    else:
        print("\n❌ Aucun résultat disponible")
    
    return comparison


def main():
    parser = argparse.ArgumentParser(description='Backtest multi-plateforme')
    
    parser.add_argument('--strategy', '-s', type=str, default='micro_arb')
    parser.add_argument('--pair', '-p', type=str, default='EURUSD')
    parser.add_argument('--years', '-y', type=int, default=10)
    parser.add_argument('--capital', '-c', type=float, default=50.0)
    parser.add_argument('--timeframe', '-t', type=str, default='1d')
    parser.add_argument('--type', type=str, choices=['forex', 'crypto', 'all'], default='all')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    comparison = run_multi_platform_backtest(
        strategy_name=args.strategy,
        pair=args.pair,
        years=args.years,
        initial_capital=args.capital,
        timeframe=args.timeframe,
        platform_type=args.type if args.type != 'all' else None,
        verbose=args.verbose,
    )
    
    # Code de sortie
    if len(comparison) > 0:
        pnl_values = comparison['Net PnL'].str.replace('$', '').str.replace(',', '').astype(float)
        if pnl_values.max() > 0:
            sys.exit(0)
    sys.exit(1)


if __name__ == '__main__':
    main()
