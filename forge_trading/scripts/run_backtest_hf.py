#!/usr/bin/env python3
"""
Backtest HAUTE FRÉQUENCE - Milliers de trades sur 10 ans.
Utilise le timeframe 1h ou 15m pour générer beaucoup plus de signaux.
"""

import argparse
import sys
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))

from forge_trading.backtesting.multi_platform import MultiPlatformBacktester
from forge_trading.backtesting.data_loader import HistoricalDataLoader
from forge_trading.backtesting.data_validator import get_data_quality_report
from forge_trading.strategies.micro_arb import MicroArbitrageStrategy
from forge_trading.reflection_db.database import ReflectionDatabase
from forge_trading.strategies.forge_integration import ForgeReflectionIntegration
from forge_trading.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_intraday_data(pair: str, years: int, timeframe: str = "1h") -> pd.DataFrame:
    """
    Charge des données intraday.
    yfinance supporte: 1h (max 730 jours), 15m/5m/1m (max 60 jours)
    
    Pour 10 ans d'intraday, on combine:
    - Données daily pour la tendance long terme
    - Données 1h récentes (2 ans max via yfinance)
    - Données synthétiques intraday basées sur la volatilité réelle
    """
    loader = HistoricalDataLoader()
    
    try:
        # Essayer de charger les données 1h (max 2 ans)
        logger.info(f"Tentative de chargement {pair} en {timeframe}...")
        
        import yfinance as yf
        
        # yfinance limite: 1h = 730 jours max
        if timeframe == "1h":
            max_days = 730
        elif timeframe in ["15m", "5m"]:
            max_days = 60
        elif timeframe == "1m":
            max_days = 7
        else:
            max_days = years * 365
        
        end_date = datetime.now()
        start_date = end_date - pd.Timedelta(days=min(max_days, years * 365))
        
        ticker = f"{pair}=X" if not pair.endswith("USD") or pair.startswith("BTC") else pair
        if pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]:
            ticker = f"{pair}=X"
        
        data = yf.download(
            ticker,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval=timeframe,
            progress=False
        )
        
        if data.empty:
            raise ValueError("No data returned")
        
        df = pd.DataFrame({
            'timestamp': data.index,
            'open': data['Open'].values.flatten(),
            'high': data['High'].values.flatten(),
            'low': data['Low'].values.flatten(),
            'close': data['Close'].values.flatten(),
            'volume': data['Volume'].values.flatten() if 'Volume' in data.columns else 0
        })
        
        df = df.reset_index(drop=True)
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        logger.info(f"Données intraday chargées: {len(df)} barres {timeframe} ({df['timestamp'].min()} → {df['timestamp'].max()})")
        
        # Si on a moins de données que demandé, extrapoler avec la volatilité réelle
        if len(df) < years * 252 * (24 if timeframe == "1h" else 96):
            logger.info(f"Extrapolation pour {years} ans de données {timeframe}...")
            df = extrapolate_intraday(df, years, timeframe)
        
        return df
        
    except Exception as e:
        logger.warning(f"Erreur chargement intraday: {e}")
        logger.info("Génération de données synthétiques intraday basées sur la volatilité réelle...")
        return generate_realistic_intraday(pair, years, timeframe)


def extrapolate_intraday(df: pd.DataFrame, target_years: int, timeframe: str) -> pd.DataFrame:
    """
    Extrapoler les données intraday en utilisant la volatilité réelle observée.
    """
    # Calculer les statistiques de la période réelle
    returns = df['close'].pct_change().dropna()
    daily_vol = returns.std()
    trend = returns.mean()
    
    # Calculer le nombre de barres nécessaires
    if timeframe == "1h":
        bars_per_day = 24
    elif timeframe == "15m":
        bars_per_day = 96
    elif timeframe == "5m":
        bars_per_day = 288
    else:
        bars_per_day = 24
    
    total_bars = target_years * 252 * bars_per_day
    
    # Générer les données supplémentaires
    np.random.seed(42)
    
    # Utiliser la distribution réelle des returns (avec kurtosis)
    extra_bars = total_bars - len(df)
    
    if extra_bars > 0:
        # Générer des returns avec les mêmes stats que les données réelles
        extra_returns = np.random.choice(returns.values, size=extra_bars, replace=True)
        
        # Ajouter de l'autocorrélation (stylisé des marchés réels)
        for i in range(1, len(extra_returns)):
            extra_returns[i] += extra_returns[i-1] * 0.01  # Mean reversion faible
        
        # Construire les prix
        last_price = df['close'].iloc[-1]
        extra_prices = last_price * np.exp(np.cumsum(extra_returns))
        
        # Créer OHLCV réaliste
        extra_timestamps = pd.date_range(
            start=df['timestamp'].iloc[-1] + pd.Timedelta(hours=1),
            periods=extra_bars,
            freq=timeframe.replace('m', 'T') if 'm' in timeframe else timeframe
        )
        
        # Générer des bougies réalistes
        extra_high = extra_prices * (1 + np.abs(np.random.normal(0, daily_vol * 0.5, extra_bars)))
        extra_low = extra_prices * (1 - np.abs(np.random.normal(0, daily_vol * 0.5, extra_bars)))
        extra_open = extra_prices * (1 + np.random.normal(0, daily_vol * 0.2, extra_bars))
        extra_volume = np.random.lognormal(10, 1, extra_bars)
        
        extra_df = pd.DataFrame({
            'timestamp': extra_timestamps,
            'open': extra_open,
            'high': np.maximum(extra_high, np.maximum(extra_open, extra_prices)),
            'low': np.minimum(extra_low, np.minimum(extra_open, extra_prices)),
            'close': extra_prices,
            'volume': extra_volume
        })
        
        df = pd.concat([extra_df, df], ignore_index=True)
    
    logger.info(f"Données extrapolées: {len(df)} barres")
    return df


def generate_realistic_intraday(pair: str, years: int, timeframe: str) -> pd.DataFrame:
    """
    Génère des données intraday réalistes basées sur les propriétés statistiques du Forex.
    """
    np.random.seed(42)
    
    # Paramètres réalistes pour EURUSD
    if pair in ["EURUSD", "GBPUSD", "AUDUSD"]:
        start_price = 1.1000
        daily_vol = 0.005  # 0.5% par jour
        annual_drift = 0.001  # Légère tendance
    elif pair in ["USDJPY"]:
        start_price = 110.0
        daily_vol = 0.004
        annual_drift = -0.002
    else:
        start_price = 1.0
        daily_vol = 0.005
        annual_drift = 0
    
    # Nombre de barres
    if timeframe == "1h":
        bars_per_day = 24
    elif timeframe == "15m":
        bars_per_day = 96
    elif timeframe == "5m":
        bars_per_day = 288
    else:
        bars_per_day = 24
    
    total_bars = years * 252 * bars_per_day
    
    # Générer les returns avec propriétés stylisées:
    # 1. Fat tails (kurtosis élevée)
    # 2. Volatilité clustering (GARCH-like)
    # 3. Mean reversion intraday
    
    base_return = annual_drift / (252 * bars_per_day)
    base_vol = daily_vol / np.sqrt(bars_per_day)
    
    # Returns avec kurtosis
    returns = np.random.standard_t(df=5, size=total_bars) * base_vol + base_return
    
    # Volatilité clustering (simple GARCH)
    vol_series = np.ones(total_bars) * base_vol
    for i in range(1, total_bars):
        vol_series[i] = 0.9 * vol_series[i-1] + 0.1 * abs(returns[i-1])
    
    returns = returns * (vol_series / base_vol)
    
    # Mean reversion intraday
    prices = np.zeros(total_bars)
    prices[0] = start_price
    
    for i in range(1, total_bars):
        # Mean reversion vers le prix d'ouverture du jour
        day_start = (i // bars_per_day) * bars_per_day
        day_open = prices[day_start]
        mean_rev = (day_open - prices[i-1]) * 0.001  # 0.1% de mean reversion
        
        prices[i] = prices[i-1] * (1 + returns[i] + mean_rev)
    
    # Générer OHLCV réaliste
    timestamps = pd.date_range(
        end=datetime.now(),
        periods=total_bars,
        freq=timeframe.replace('m', 'T') if 'm' in timeframe else timeframe
    )
    
    # High/Low basés sur la volatilité intrabar
    intra_vol = base_vol * 0.3
    highs = prices * (1 + np.abs(np.random.normal(0, intra_vol, total_bars)))
    lows = prices * (1 - np.abs(np.random.normal(0, intra_vol, total_bars)))
    opens = np.roll(prices, 1)
    opens[0] = start_price
    
    # Volume avec pattern intraday (plus de volume aux heures de marché)
    hour_of_day = np.array([t.hour for t in timestamps])
    volume_pattern = np.where((hour_of_day >= 8) & (hour_of_day <= 17), 2.0, 0.5)
    volumes = np.random.lognormal(10, 1, total_bars) * volume_pattern
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': np.maximum(highs, np.maximum(opens, prices)),
        'low': np.minimum(lows, np.minimum(opens, prices)),
        'close': prices,
        'volume': volumes
    })
    
    logger.info(f"Données synthétiques réalistes: {len(df)} barres {timeframe} ({years} ans)")
    return df


def run_high_frequency_backtest(
    strategy_name: str,
    pairs: list,
    years: int,
    initial_capital: float,
    timeframe: str = "1h",
    verbose: bool = False
):
    """
    Backtest haute fréquence sur multiple paires.
    """
    logger.info("="*70)
    logger.info("BACKTEST HAUTE FRÉQUENCE")
    logger.info(f"Stratégie: {strategy_name}")
    logger.info(f"Paires: {pairs}")
    logger.info(f"Période: {years} ans | Timeframe: {timeframe}")
    logger.info(f"Capital: ${initial_capital}")
    logger.info("="*70)
    
    all_results = []
    all_trades = []
    
    for pair in pairs:
        logger.info(f"\n{'='*50}")
        logger.info(f"BACKTEST: {pair}")
        logger.info(f"{'='*50}")
        
        # Charger les données
        data = load_intraday_data(pair, years, timeframe)
        
        if len(data) < 1000:
            logger.warning(f"Pas assez de données pour {pair}: {len(data)} barres")
            continue
        
        # Afficher les stats des données
        logger.info(f"Barres: {len(data)} | Prix: {data['close'].iloc[0]:.5f} → {data['close'].iloc[-1]:.5f}")
        
        # Créer une stratégie fraîche pour chaque paire
        strategy = MicroArbitrageStrategy({
            'gap_threshold': 0.001,      # Plus petit pour intraday
            'lookback_period': 20,
            'exit_at_mean': True,
            'stop_loss_atr_mult': 1.5,   # Plus serré pour intraday
            'take_profit_atr_mult': 2.0,
            'min_volume_percentile': 20,  # Moins restrictif
            'rsi_oversold': 35,
            'rsi_overbought': 65,
            'require_confirmation': False, # Moins restrictif pour plus de trades
            'max_spread': 0.01,
        })
        
        # Backtest sur OANDA (meilleur pour $50 capital)
        backtester = MultiPlatformBacktester(strategy, initial_capital)
        
        try:
            result = backtester.backtest_platform("oanda", data, pair, verbose)
            all_results.append(result)
            
            # Stocker les trades
            for trade in result.result.trades:
                trade.pair = pair
                all_trades.append(trade)
            
            logger.info(f"  Trades: {result.result.total_trades} | WR: {result.effective_win_rate:.1%} | Net: ${result.net_after_fees:.2f}")
            
        except Exception as e:
            logger.error(f"  Erreur: {e}")
    
    # Résumé global
    logger.info("\n" + "="*70)
    logger.info("RÉSUMÉ GLOBAL HAUTE FRÉQUENCE")
    logger.info("="*70)
    
    total_trades = sum(r.result.total_trades for r in all_results)
    total_pnl = sum(r.net_after_fees for r in all_results)
    total_wins = sum(r.result.winning_trades for r in all_results)
    
    if total_trades > 0:
        global_wr = total_wins / total_trades
        
        print(f"\n📊 STATISTIQUES GLOBALES:")
        print(f"   Total trades:     {total_trades:,}")
        print(f"   Trades gagnants:  {total_wins:,}")
        print(f"   Trades perdants:  {total_trades - total_wins:,}")
        print(f"   Win Rate:         {global_wr:.1%}")
        print(f"   PnL Net total:    ${total_pnl:.2f}")
        print(f"   PnL moyen/trade:  ${total_pnl/total_trades:.4f}")
        
        # Stats par paire
        print(f"\n📈 PAR PAIRE:")
        for r in all_results:
            print(f"   {r.platform_name:20} | {r.result.total_trades:5} trades | WR: {r.effective_win_rate:.1%} | Net: ${r.net_after_fees:.2f}")
        
        # Distribution des trades
        if all_trades:
            pnls = [t.net_pnl for t in all_trades]
            print(f"\n📉 DISTRIBUTION:")
            print(f"   Gain moyen:   ${np.mean([p for p in pnls if p > 0]):.4f}" if any(p > 0 for p in pnls) else "   Aucun gain")
            print(f"   Perte moyenne: ${np.mean([p for p in pnls if p < 0]):.4f}" if any(p < 0 for p in pnls) else "   Aucune perte")
            print(f"   Meilleur trade: ${max(pnls):.4f}")
            print(f"   Pire trade:    ${min(pnls):.4f}")
        
        # Sauvegarder dans la DB
        logger.info("\n--- SAUVEGARDE DANS LA BASE DE RÉFLEXION ---")
        db = ReflectionDatabase()
        reflection = ForgeReflectionIntegration(db)
        
        for trade in all_trades:
            reflection.on_trade_closed(trade)
        
        summary = db.get_performance_summary(strategy_name)
        print(f"\n📚 Base de réflexion:")
        print(f"   Trades sauvegardés: {summary['total_trades']}")
        print(f"   Win rate global: {summary['win_rate']:.1%}")
        print(f"   Leçons apprises: {summary['lessons_learned']}")
    
    else:
        print("\n❌ Aucun trade généré")


def main():
    parser = argparse.ArgumentParser(description='Backtest haute fréquence')
    
    parser.add_argument('--strategy', '-s', type=str, default='micro_arb')
    parser.add_argument('--pairs', '-p', type=str, nargs='+', 
                       default=['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'])
    parser.add_argument('--years', '-y', type=int, default=10)
    parser.add_argument('--capital', '-c', type=float, default=50.0)
    parser.add_argument('--timeframe', '-t', type=str, default='1h',
                       choices=['1h', '15m', '5m'])
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    run_high_frequency_backtest(
        strategy_name=args.strategy,
        pairs=args.pairs,
        years=args.years,
        initial_capital=args.capital,
        timeframe=args.timeframe,
        verbose=args.verbose,
    )


if __name__ == '__main__':
    main()
