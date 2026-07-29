#!/usr/bin/env python3
"""
SMC Paper Trading - Lance le système en temps réel.
Surveille les marchés et exécute des paper trades sur les setups SMC.
"""

import asyncio
import sys
import logging
from pathlib import Path
from datetime import datetime

# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def simulate_with_real_data():
    """
    Simule le paper trading avec des données réelles récentes.
    Utilise les dernières 730h de données 1h (max yfinance).
    """
    import yfinance as yf
    import numpy as np
    import pandas as pd
    from forge_trading.strategies.smc_paper_trader import SMCPaperTrader
    
    pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']
    
    logger.info("=" * 60)
    logger.info("SMC PAPER TRADING - SIMULATION SUR DONNÉES RÉELLES")
    logger.info(f"Paires: {pairs}")
    logger.info(f"Timeframe: 1h")
    logger.info("=" * 60)
    
    trader = SMCPaperTrader(pairs, timeframe="1h", capital=50.0)
    
    # Télécharger les données réelles
    all_data = {}
    for pair in pairs:
        raw = yf.download(f'{pair}=X', period='1mo', interval='1h', progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        data = raw.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
        all_data[pair] = data
        logger.info(f"  {pair}: {len(data)} barres chargées")
    
    # Simuler le flux de bougies
    min_len = min(len(d) for d in all_data.values())
    logger.info(f"\nSimulation sur {min_len} barres...")
    logger.info("-" * 60)
    
    for i in range(200, min_len):
        for pair in pairs:
            data = all_data[pair]
            if i >= len(data):
                continue
            
            candle = {
                'open': float(data['open'].iloc[i]),
                'high': float(data['high'].iloc[i]),
                'low': float(data['low'].iloc[i]),
                'close': float(data['close'].iloc[i]),
                'volume': float(data['volume'].iloc[i]) if 'volume' in data.columns else 0,
                'timestamp': str(data.index[i]),
            }
            
            trader.on_candle(pair, candle)
    
    # Forcer la fermeture des trades ouverts
    for pair in pairs:
        data = all_data[pair]
        last_price = float(data['close'].iloc[-1])
        trader.engine.update(pair, last_price)
    
    # Afficher les résultats
    status = trader.get_status()
    perf = status['performance']
    
    logger.info("\n" + "=" * 60)
    logger.info("RÉSULTATS DU PAPER TRADING")
    logger.info("=" * 60)
    logger.info(f"  Trades:     {perf.get('total_trades', 0)}")
    logger.info(f"  Win Rate:   {perf.get('win_rate', 0):.1%}")
    logger.info(f"  Gagnants:   {perf.get('winning_trades', 0)}")
    logger.info(f"  Perdants:   {perf.get('losing_trades', 0)}")
    logger.info(f"  PnL:        ${perf.get('total_pnl', 0):.2f}")
    logger.info(f"  Capital:    ${perf.get('current_capital', 0):.2f}")
    
    if perf.get('winning_trades', 0) > 0 and perf.get('losing_trades', 0) > 0:
        logger.info(f"  Gain moy:   ${perf.get('avg_win', 0):.4f}")
        logger.info(f"  Perte moy:  ${perf.get('avg_loss', 0):.4f}")
        logger.info(f"  PF:         {perf.get('profit_factor', 0):.2f}")
    
    logger.info(f"\nDétails sauvegardés dans: logs/paper_trades.json")
    
    return perf


def run_live():
    """
    Lance le paper trading en mode live.
    Nécessite une connexion WebSocket (OANDA ou Binance).
    """
    logger.info("=" * 60)
    logger.info("SMC PAPER TRADING - MODE LIVE")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Pour le mode live, tu as besoin de:")
    logger.info("  1. Un compte OANDA (Forex) ou Binance (Crypto)")
    logger.info("  2. Les clés API dans config/secrets.yaml")
    logger.info("  3. Lancer: python scripts/websocket_forex.py")
    logger.info("")
    logger.info("En attendant, lance la simulation:")
    logger.info("  python scripts/run_paper_trading.py --simulate")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='SMC Paper Trading')
    parser.add_argument('--simulate', '-s', action='store_true', help='Simulation sur données réelles')
    parser.add_argument('--live', '-l', action='store_true', help='Mode live (nécessite WebSocket)')
    
    args = parser.parse_args()
    
    if args.simulate:
        simulate_with_real_data()
    elif args.live:
        run_live()
    else:
        # Par défaut: simulation
        simulate_with_real_data()
