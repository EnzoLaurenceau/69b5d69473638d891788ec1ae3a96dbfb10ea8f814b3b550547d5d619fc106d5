#!/usr/bin/env python3
"""
Script principal pour exécuter les backtests.
Usage: python run_backtest.py --strategy micro_arb --pair EURUSD --years 10
"""

import argparse
import sys
import logging
from datetime import datetime
from pathlib import Path

# Ajouter le parent au path
# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))

from forge_trading.backtesting.engine import BacktestEngine
from forge_trading.backtesting.data_loader import HistoricalDataLoader
from forge_trading.strategies.micro_arb import MicroArbitrageStrategy
from forge_trading.reflection_db.database import ReflectionDatabase
from forge_trading.strategies.forge_integration import ForgeReflectionIntegration
from forge_trading.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_strategy(name: str, params: dict = None):
    """Factory pour les stratégies."""
    strategies = {
        'micro_arb': MicroArbitrageStrategy,
    }
    
    if name not in strategies:
        raise ValueError(f"Stratégie inconnue: {name}. Disponibles: {list(strategies.keys())}")
    
    return strategies[name](params)


def run_backtest(
    strategy_name: str,
    pair: str,
    market: str,
    years: int,
    initial_capital: float,
    timeframe: str = "1d",
    optimize: bool = True,
    verbose: bool = False
):
    """
    Exécute un backtest complet.
    """
    logger.info(f"="*60)
    logger.info(f"BACKTEST: {strategy_name} sur {pair} ({years} ans)")
    logger.info(f"Capital initial: ${initial_capital}")
    logger.info(f"="*60)
    
    # 1. Charger les données historiques
    loader = HistoricalDataLoader()
    
    try:
        if market == "forex":
            data = loader.load_forex(pair, years, timeframe)
        elif market == "crypto":
            data = loader.load_crypto(pair, years, timeframe)
        else:
            raise ValueError(f"Marché inconnu: {market}")
    except Exception as e:
        logger.warning(f"Erreur chargement données: {e}")
        logger.info("Utilisation de données synthétiques...")
        data = loader.generate_synthetic_data(years)
    
    logger.info(f"Données chargées: {len(data)} barres")
    
    # 2. Créer la stratégie
    strategy = get_strategy(strategy_name)
    logger.info(f"Stratégie: {strategy.name}")
    
    # 3. Créer le moteur de backtesting
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        commission_percent=0.001,  # 0.1%
        slippage_percent=0.0005,   # 0.05%
    )
    
    # 4. Exécuter le backtest
    logger.info("Démarrage du backtest...")
    
    result = engine.run(
        data=data,
        pair=pair,
        market=market,
        verbose=verbose
    )
    
    # 5. Afficher les résultats
    logger.info("\n" + "="*60)
    logger.info("RÉSULTATS DU BACKTEST")
    logger.info("="*60)
    
    stats = result.to_dict()
    for key, value in stats.items():
        logger.info(f"{key:25}: {value}")
    
    # 6. Vérifier les objectifs
    logger.info("\n" + "="*60)
    logger.info("VÉRIFICATION DES OBJECTIFS")
    logger.info("="*60)
    
    if result.win_rate >= config.target_win_rate:
        logger.info(f"✅ Win rate {result.win_rate:.1%} >= objectif {config.target_win_rate:.1%}")
    elif result.win_rate >= config.min_win_rate:
        logger.info(f"⚠️ Win rate {result.win_rate:.1%} >= minimum {config.min_win_rate:.1%} mais sous l'objectif")
    else:
        logger.error(f"❌ Win rate {result.win_rate:.1%} < minimum {config.min_win_rate:.1%}")
    
    if result.profit_factor >= config.min_profit_factor:
        logger.info(f"✅ Profit factor {result.profit_factor:.2f} >= minimum {config.min_profit_factor}")
    else:
        logger.warning(f"⚠️ Profit factor {result.profit_factor:.2f} < minimum {config.min_profit_factor}")
    
    if result.max_drawdown <= config.max_drawdown:
        logger.info(f"✅ Max drawdown {result.max_drawdown:.1%} <= maximum {config.max_drawdown:.1%}")
    else:
        logger.error(f"❌ Max drawdown {result.max_drawdown:.1%} > maximum {config.max_drawdown:.1%}")
    
    # 7. Optimisation
    if optimize and len(result.trades) >= 50:
        logger.info("\n" + "="*60)
        logger.info("OPTIMISATION")
        logger.info("="*60)
        
        suggestions = engine.get_optimization_suggestions()
        for key, value in suggestions.items():
            logger.info(f"{key:25}: {value}")
        
        # Optimiser les paramètres
        new_params = strategy.optimize(result.trades)
        logger.info(f"\nNouveaux paramètres optimisés:")
        for key, value in new_params.items():
            logger.info(f"  {key}: {value}")
    
    # 8. Sauvegarder dans la base de réflexion
    logger.info("\n" + "="*60)
    logger.info("SAUVEGARDE DANS LA BASE DE RÉFLEXION")
    logger.info("="*60)
    
    db = ReflectionDatabase()
    reflection = ForgeReflectionIntegration(db)
    
    for trade in result.trades:
        reflection.on_trade_closed(trade)
    
    # Générer le rapport
    summary = db.get_performance_summary(strategy_name)
    logger.info(f"Trades sauvegardés: {summary['total_trades']}")
    logger.info(f"Win rate global: {summary['win_rate']:.1%}")
    logger.info(f"Leçons apprises: {summary['lessons_learned']}")
    
    # 9. Recommandations
    recommendations = reflection.get_strategy_recommendations(strategy_name)
    if recommendations:
        logger.info("\nRecommandations:")
        for i, rec in enumerate(recommendations[:5], 1):
            logger.info(f"  {i}. {rec}")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Exécuter un backtest de trading')
    
    parser.add_argument(
        '--strategy', '-s',
        type=str,
        default='micro_arb',
        help='Nom de la stratégie (défaut: micro_arb)'
    )
    
    parser.add_argument(
        '--pair', '-p',
        type=str,
        default='EURUSD',
        help='Paire de trading (défaut: EURUSD)'
    )
    
    parser.add_argument(
        '--market', '-m',
        type=str,
        default='forex',
        choices=['forex', 'crypto'],
        help='Marché (défaut: forex)'
    )
    
    parser.add_argument(
        '--years', '-y',
        type=int,
        default=10,
        help='Nombre d\'années d\'historique (défaut: 10)'
    )
    
    parser.add_argument(
        '--capital', '-c',
        type=float,
        default=50.0,
        help='Capital initial en $ (défaut: 50)'
    )
    
    parser.add_argument(
        '--timeframe', '-t',
        type=str,
        default='1d',
        help='Temporalité (défaut: 1d)'
    )
    
    parser.add_argument(
        '--no-optimize',
        action='store_true',
        help='Désactiver l\'optimisation'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Mode verbose'
    )
    
    args = parser.parse_args()
    
    # Exécuter le backtest
    result = run_backtest(
        strategy_name=args.strategy,
        pair=args.pair,
        market=args.market,
        years=args.years,
        initial_capital=args.capital,
        timeframe=args.timeframe,
        optimize=not args.no_optimize,
        verbose=args.verbose
    )
    
    # Code de sortie basé sur les résultats
    if result.win_rate >= config.min_win_rate and result.profit_factor >= 1.0:
        sys.exit(0)  # Succès
    else:
        sys.exit(1)  # Échec


if __name__ == '__main__':
    main()
