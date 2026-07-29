#!/usr/bin/env python3
"""
Backtest VECTORISÉ - Ultra-rapide, des milliers de trades en secondes.
Utilise numpy/pandas au lieu de boucles Python.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd

# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def generate_forex_data(pair: str, years: int, timeframe: str = "1h") -> pd.DataFrame:
    """Génère des données Forex réalistes."""
    np.random.seed(hash(pair) % 2**32)
    
    # Paramètres par paire
    params = {
        "EURUSD": {"start": 1.10, "vol": 0.005, "drift": 0.001},
        "GBPUSD": {"start": 1.30, "vol": 0.006, "drift": -0.001},
        "USDJPY": {"start": 110.0, "vol": 0.004, "drift": -0.002},
        "AUDUSD": {"start": 0.75, "vol": 0.005, "drift": 0.0005},
        "USDCAD": {"start": 1.30, "vol": 0.004, "drift": 0.001},
    }.get(pair, {"start": 1.0, "vol": 0.005, "drift": 0})
    
    # Calculer le nombre de barres
    bars_per_day = {"1h": 24, "15m": 96, "5m": 288, "1m": 1440}.get(timeframe, 24)
    total_bars = years * 252 * bars_per_day
    
    # Générer les returns avec fat tails et vol clustering
    base_vol = params["vol"] / np.sqrt(bars_per_day)
    base_return = params["drift"] / (252 * bars_per_day)
    
    # Returns avec distribution de Student (fat tails)
    returns = np.random.standard_t(df=5, size=total_bars) * base_vol + base_return
    
    # Volatilité clustering (GARCH-like)
    vol = np.ones(total_bars) * base_vol
    for i in range(1, total_bars):
        vol[i] = 0.94 * vol[i-1] + 0.06 * abs(returns[i-1])
    returns = returns * (vol / base_vol)
    
    # Construire les prix
    log_prices = np.cumsum(returns) + np.log(params["start"])
    close = np.exp(log_prices)
    
    # OHLCV réaliste
    intra_vol = base_vol * 0.3
    high = close * (1 + np.abs(np.random.normal(0, intra_vol, total_bars)))
    low = close * (1 - np.abs(np.random.normal(0, intra_vol, total_bars)))
    open_p = np.roll(close, 1)
    open_p[0] = params["start"]
    
    # Volume avec pattern intraday
    hours = np.tile(np.arange(24), total_bars // 24 + 1)[:total_bars]
    vol_pattern = np.where((hours >= 8) & (hours <= 17), 2.0, 0.5)
    volume = np.random.lognormal(10, 1, total_bars) * vol_pattern
    
    timestamps = pd.date_range(end=datetime.now(), periods=total_bars, freq=timeframe.replace('m', 'T') if 'm' in timeframe else timeframe)
    
    return pd.DataFrame({
        'timestamp': timestamps,
        'open': open_p,
        'high': np.maximum(high, np.maximum(open_p, close)),
        'low': np.minimum(low, np.minimum(open_p, close)),
        'close': close,
        'volume': volume
    })


def vectorized_backtest(
    data: pd.DataFrame,
    pair: str,
    gap_threshold: float = 0.001,
    lookback: int = 20,
    stop_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.0,
    commission: float = 0.0001,  # 0.01% (OANDA-like)
    spread_cost: float = 0.00012,  # 1.2 pips
    initial_capital: float = 50.0,
) -> dict:
    """
    Backtest vectorisé ultra-rapide.
    Retourne des statistiques détaillées.
    """
    close = data['close'].values
    high = data['high'].values
    low = data['low'].values
    n = len(close)
    
    # === CALCUL DES INDICATEURS (vectorisé) ===
    
    # SMA
    sma = pd.Series(close).rolling(lookback).mean().values
    
    # ATR
    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - np.roll(close, 1)),
            np.abs(low - np.roll(close, 1))
        )
    )
    atr = pd.Series(tr).rolling(14).mean().values
    
    # RSI
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(14).mean().values
    avg_loss = pd.Series(loss).rolling(14).mean().values
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))
    
    # Gap par rapport à la SMA
    gap = (close - sma) / sma
    
    # === GÉNÉRATION DES SIGNAUX (vectorisé) ===
    
    # Signaux d'achat: gap négatif + RSI bas
    buy_signals = (gap < -gap_threshold) & (rsi < 40) & (np.arange(n) > lookback)
    
    # Signaux de vente: gap positif + RSI haut
    sell_signals = (gap > gap_threshold) & (rsi > 60) & (np.arange(n) > lookback)
    
    # === SIMULATION DES TRADES ===
    
    capital = initial_capital
    trades = []
    in_trade = False
    trade_entry = 0
    trade_direction = 0
    trade_stop = 0
    trade_tp = 0
    trade_entry_idx = 0
    
    for i in range(lookback, n):
        if not in_trade:
            # Chercher un signal
            if buy_signals[i]:
                entry_price = close[i] * (1 + spread_cost)  # Spread
                trade_stop = entry_price - atr[i] * stop_atr_mult
                trade_tp = entry_price + atr[i] * tp_atr_mult
                trade_entry = entry_price
                trade_direction = 1  # Long
                trade_entry_idx = i
                in_trade = True
                
            elif sell_signals[i]:
                entry_price = close[i] * (1 - spread_cost)  # Spread
                trade_stop = entry_price + atr[i] * stop_atr_mult
                trade_tp = entry_price - atr[i] * tp_atr_mult
                trade_entry = entry_price
                trade_direction = -1  # Short
                trade_entry_idx = i
                in_trade = True
        else:
            # Vérifier sorties
            exit_price = None
            
            if trade_direction == 1:  # Long
                if low[i] <= trade_stop:
                    exit_price = trade_stop
                elif high[i] >= trade_tp:
                    exit_price = trade_tp
                elif close[i] >= sma[i]:  # Retour à la moyenne
                    exit_price = close[i]
            else:  # Short
                if high[i] >= trade_stop:
                    exit_price = trade_stop
                elif low[i] <= trade_tp:
                    exit_price = trade_tp
                elif close[i] <= sma[i]:  # Retour à la moyenne
                    exit_price = close[i]
            
            if exit_price is not None:
                # Appliquer spread de sortie
                if trade_direction == 1:
                    exit_price *= (1 - spread_cost)
                else:
                    exit_price *= (1 + spread_cost)
                
                # Calculer PnL
                if trade_direction == 1:
                    pnl_pct = (exit_price - trade_entry) / trade_entry
                else:
                    pnl_pct = (trade_entry - exit_price) / trade_entry
                
                # Taille de position (2% risk)
                risk_amount = capital * 0.02
                position_size = risk_amount / (abs(trade_entry - trade_stop) / trade_entry) if trade_entry != trade_stop else 0
                
                pnl_dollar = position_size * pnl_pct * trade_entry
                fees = position_size * trade_entry * commission * 2  # Entrée + sortie
                
                net_pnl = pnl_dollar - fees
                capital += net_pnl
                
                trades.append({
                    'pair': pair,
                    'direction': 'BUY' if trade_direction == 1 else 'SELL',
                    'entry': trade_entry,
                    'exit': exit_price,
                    'pnl_pct': pnl_pct,
                    'pnl_dollar': net_pnl,
                    'fees': fees,
                    'duration_bars': i - trade_entry_idx,
                    'is_winner': net_pnl > 0,
                    'entry_idx': trade_entry_idx,
                    'exit_idx': i,
                })
                
                in_trade = False
    
    # === CALCUL DES STATISTIQUES ===
    
    if not trades:
        return {
            'pair': pair,
            'total_trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'profit_factor': 0,
            'max_drawdown': 0,
            'trades': []
        }
    
    trades_df = pd.DataFrame(trades)
    winners = trades_df[trades_df['is_winner']]
    losers = trades_df[~trades_df['is_winner']]
    
    gross_profit = winners['pnl_dollar'].sum() if len(winners) > 0 else 0
    gross_loss = abs(losers['pnl_dollar'].sum()) if len(losers) > 0 else 0
    
    # Equity curve et drawdown
    equity = initial_capital + trades_df['pnl_dollar'].cumsum()
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak
    max_dd = drawdown.min()
    
    return {
        'pair': pair,
        'total_trades': len(trades),
        'winning_trades': len(winners),
        'losing_trades': len(losers),
        'win_rate': len(winners) / len(trades),
        'total_pnl': trades_df['pnl_dollar'].sum(),
        'avg_win': winners['pnl_dollar'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl_dollar'].mean() if len(losers) > 0 else 0,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
        'max_drawdown': max_dd,
        'avg_duration_bars': trades_df['duration_bars'].mean(),
        'final_capital': capital,
        'total_fees': trades_df['fees'].sum(),
        'trades': trades,
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Backtest vectorisé haute fréquence')
    parser.add_argument('--pairs', '-p', type=str, nargs='+', default=['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'])
    parser.add_argument('--years', '-y', type=int, default=10)
    parser.add_argument('--timeframe', '-t', type=str, default='1h')
    parser.add_argument('--capital', '-c', type=float, default=50.0)
    parser.add_argument('--gap', type=float, default=0.001, help='Gap threshold')
    
    args = parser.parse_args()
    
    print("="*70)
    print("BACKTEST VECTORISÉ HAUTE FRÉQUENCE")
    print(f"Paires: {args.pairs} | Période: {args.years} ans | Timeframe: {args.timeframe}")
    print(f"Capital: ${args.capital} | Gap threshold: {args.gap}")
    print("="*70)
    
    all_results = []
    all_trades = []
    
    for pair in args.pairs:
        print(f"\n{'─'*50}")
        print(f"📊 {pair}")
        print(f"{'─'*50}")
        
        # Générer les données
        data = generate_forex_data(pair, args.years, args.timeframe)
        print(f"   Barres: {len(data):,}")
        
        # Backtest
        start_time = datetime.now()
        result = vectorized_backtest(
            data, pair,
            gap_threshold=args.gap,
            initial_capital=args.capital,
        )
        elapsed = (datetime.now() - start_time).total_seconds()
        
        all_results.append(result)
        all_trades.extend(result['trades'])
        
        print(f"   Trades: {result['total_trades']:,}")
        print(f"   Win Rate: {result['win_rate']:.1%}")
        print(f"   PnL Net: ${result['total_pnl']:.2f}")
        print(f"   Profit Factor: {result['profit_factor']:.2f}")
        print(f"   Max Drawdown: {result['max_drawdown']:.1%}")
        print(f"   Durée moyenne: {result['avg_duration_bars']:.0f} barres")
        print(f"   Temps: {elapsed:.1f}s")
    
    # === RÉSUMÉ GLOBAL ===
    print("\n" + "="*70)
    print("📈 RÉSUMÉ GLOBAL")
    print("="*70)
    
    total_trades = sum(r['total_trades'] for r in all_results)
    total_wins = sum(r['winning_trades'] for r in all_results)
    total_pnl = sum(r['total_pnl'] for r in all_results)
    total_fees = sum(r['total_fees'] for r in all_results)
    
    if total_trades > 0:
        print(f"\n   Total trades:      {total_trades:,}")
        print(f"   Trades gagnants:   {total_wins:,}")
        print(f"   Trades perdants:   {total_trades - total_wins:,}")
        print(f"   Win Rate global:   {total_wins/total_trades:.1%}")
        print(f"   PnL Net total:     ${total_pnl:.2f}")
        print(f"   Frais totaux:      ${total_fees:.2f}")
        print(f"   PnL moyen/trade:   ${total_pnl/total_trades:.4f}")
        
        # Distribution
        if all_trades:
            pnls = [t['pnl_dollar'] for t in all_trades]
            winners = [p for p in pnls if p > 0]
            losers = [p for p in pnls if p < 0]
            
            print(f"\n   Gain moyen:        ${np.mean(winners):.4f}" if winners else "\n   Aucun gain")
            print(f"   Perte moyenne:     ${np.mean(losers):.4f}" if losers else "   Aucune perte")
            print(f"   Meilleur trade:    ${max(pnls):.4f}")
            print(f"   Pire trade:        ${min(pnls):.4f}")
            
            if winners and losers:
                risk_reward = abs(np.mean(winners) / np.mean(losers))
                print(f"   Risk/Reward:       1:{risk_reward:.2f}")
        
        # Sauvegarder dans la DB
        print(f"\n{'─'*50}")
        print("📚 SAUVEGARDE DANS LA BASE DE RÉFLEXION")
        print(f"{'─'*50}")
        
        from forge_trading.reflection_db.database import ReflectionDatabase
        from forge_trading.strategies.base_strategy import Trade, TradeDirection, TradeStatus
        
        db = ReflectionDatabase()
        
        for t in all_trades:
            trade = Trade(
                pair=t['pair'],
                direction=TradeDirection.BUY if t['direction'] == 'BUY' else TradeDirection.SELL,
                entry_price=t['entry'],
                exit_price=t['exit'],
                pnl=t['pnl_dollar'],
                pnl_percent=t['pnl_pct'] * 100,
                fees=t['fees'],
                status=TradeStatus.CLOSED,
                strategy_name='micro_arb',
                market='forex',
                entry_time=datetime.now(),
                exit_time=datetime.now(),
            )
            db.save_trade(trade)
        
        summary = db.get_performance_summary('micro_arb')
        print(f"   Trades sauvegardés: {summary['total_trades']}")
        print(f"   Win rate DB:        {summary['win_rate']:.1%}")
        print(f"   Leçons apprises:    {summary['lessons_learned']}")
    
    else:
        print("\n❌ Aucun trade généré")


if __name__ == '__main__':
    main()
