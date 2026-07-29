"""
Moteur de backtesting pour stratégies de trading.
Supporte 10+ ans de données historiques.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Type
from pathlib import Path
import logging

import sys
# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))
from forge_trading.strategies.base_strategy import (
    BaseStrategy, Signal, Trade, BacktestResult, 
    TradeDirection, TradeStatus
)
from forge_trading.config import config

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Moteur de backtesting principal.
    
    Exécute des stratégies sur des données historiques et calcule
    les métriques de performance.
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = None,
        commission_percent: float = 0.001,  # 0.1%
        slippage_percent: float = 0.0005,   # 0.05%
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital or config.backtest_initial_capital
        self.commission_percent = commission_percent
        self.slippage_percent = slippage_percent
        
        self.capital = self.initial_capital
        self.trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        self.equity_curve: List[float] = [self.initial_capital]
        self.signals_generated: int = 0
        self.signals_executed: int = 0
    
    def run(
        self,
        data: pd.DataFrame,
        pair: str = "EURUSD",
        market: str = "forex",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        verbose: bool = False
    ) -> BacktestResult:
        """
        Exécute le backtest sur les données fournies.
        
        Args:
            data: DataFrame avec colonnes ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            pair: Paire de trading
            market: "forex" ou "crypto"
            start_date: Date de début (optionnel)
            end_date: Date de début (optionnel)
            verbose: Afficher les logs détaillés
            
        Returns:
            BacktestResult avec toutes les métriques
        """
        logger.info(f"Démarrage backtest {self.strategy.name} sur {pair} ({len(data)} barres)")
        
        # Filtrer par dates
        if start_date:
            data = data[data['timestamp'] >= start_date]
        if end_date:
            data = data[data['timestamp'] <= end_date]
        
        if len(data) < 100:
            raise ValueError(f"Pas assez de données ({len(data)} barres). Minimum 100 requis.")
        
        # Réinitialiser l'état
        self.capital = self.initial_capital
        self.trades = []
        self.open_trades = []
        self.equity_curve = [self.initial_capital]
        
        # Fenêtre glissante pour les indicateurs
        window_size = 100
        
        for i in range(window_size, len(data)):
            # Données actuelles (fenêtre)
            window = data.iloc[i-window_size:i+1]
            current_bar = data.iloc[i]
            current_price = current_bar['close']
            current_time = current_bar['timestamp']
            
            # Préparer les données de marché pour la stratégie
            market_data = self._prepare_market_data(window, current_bar, pair, market)
            
            # 1. Vérifier les sorties sur les trades ouverts
            trades_to_close = []
            for trade in self.open_trades:
                if self.strategy.should_exit(trade, current_price, market_data):
                    trades_to_close.append(trade)
            
            for trade in trades_to_close:
                self._close_trade(trade, current_price, current_time)
            
            # 2. Générer de nouveaux signaux
            signal = self.strategy.generate_signal(market_data)
            
            if signal:
                self.signals_generated += 1
                
                # Vérifier si on peut trader
                if self._can_trade(signal):
                    trade = self._execute_signal(signal, current_price, current_time, pair, market)
                    if trade:
                        self.signals_executed += 1
                        self.open_trades.append(trade)
                        
                        if verbose:
                            logger.info(f"[{current_time}] {signal.direction.value} {pair} @ {current_price:.5f}")
            
            # 3. Mettre à jour l'equity curve
            unrealized_pnl = sum(
                self._calculate_pnl(t, current_price) for t in self.open_trades
            )
            self.equity_curve.append(self.capital + unrealized_pnl)
        
        # Fermer tous les trades restants
        final_price = data.iloc[-1]['close']
        final_time = data.iloc[-1]['timestamp']
        
        for trade in self.open_trades[:]:
            self._close_trade(trade, final_price, final_time)
        
        # Créer le résultat
        result = BacktestResult(
            strategy_name=self.strategy.name,
            start_date=data.iloc[0]['timestamp'],
            end_date=data.iloc[-1]['timestamp'],
            initial_capital=self.initial_capital,
            final_capital=self.capital,
            trades=self.trades
        )
        
        logger.info(f"Backtest terminé: {result.total_trades} trades, WR={result.win_rate:.1%}, Return={result.total_return_percent:.1f}%")
        
        return result
    
    def _prepare_market_data(
        self, 
        window: pd.DataFrame, 
        current_bar: pd.Series,
        pair: str,
        market: str
    ) -> Dict[str, Any]:
        """Prépare les données de marché pour la stratégie."""
        return {
            'pair': pair,
            'market': market,
            'timestamp': current_bar['timestamp'],
            'open': current_bar['open'],
            'high': current_bar['high'],
            'low': current_bar['low'],
            'close': current_bar['close'],
            'volume': current_bar.get('volume', 0),
            'window': window,
            'prices': window['close'].values,
            'highs': window['high'].values,
            'lows': window['low'].values,
            'volumes': window['volume'].values if 'volume' in window.columns else np.zeros(len(window)),
            
            # Indicateurs techniques calculés
            'sma_20': window['close'].rolling(20).mean().iloc[-1],
            'sma_50': window['close'].rolling(50).mean().iloc[-1] if len(window) >= 50 else None,
            'ema_12': window['close'].ewm(span=12).mean().iloc[-1],
            'ema_26': window['close'].ewm(span=26).mean().iloc[-1],
            'rsi': self._calculate_rsi(window['close'], 14),
            'atr': self._calculate_atr(window, 14),
            'volatility': window['close'].pct_change().std() * np.sqrt(252),
        }
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calcule le RSI."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
    
    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> float:
        """Calcule l'ATR (Average True Range)."""
        high = data['high']
        low = data['low']
        close = data['close'].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0.001
    
    def _can_trade(self, signal: Signal) -> bool:
        """Vérifie si on peut exécuter un trade."""
        # Vérifier le capital disponible
        required_margin = self.capital * config.max_risk_per_trade
        if required_margin < 1.0:  # Minimum $1
            return False
        
        # Vérifier le nombre max de trades simultanés
        if len(self.open_trades) >= config.max_concurrent_trades:
            return False
        
        # Vérifier le drawdown actuel
        current_drawdown = (max(self.equity_curve) - self.equity_curve[-1]) / max(self.equity_curve)
        if current_drawdown > config.max_drawdown:
            logger.warning(f"Drawdown maximum atteint: {current_drawdown:.1%}")
            return False
        
        # Vérifier la perte quotidienne (approximative)
        daily_loss = self.capital - self.initial_capital
        if daily_loss < -(self.initial_capital * config.max_daily_loss):
            return False
        
        return True
    
    def _execute_signal(
        self, 
        signal: Signal, 
        current_price: float,
        current_time: datetime,
        pair: str,
        market: str
    ) -> Optional[Trade]:
        """Exécute un signal et crée un trade."""
        # Appliquer le slippage
        if signal.direction == TradeDirection.BUY:
            entry_price = current_price * (1 + self.slippage_percent)
        else:
            entry_price = current_price * (1 - self.slippage_percent)
        
        # Calculer la taille de position (risque 2% du capital)
        risk_amount = self.capital * config.max_risk_per_trade
        
        if signal.stop_loss > 0:
            stop_distance = abs(entry_price - signal.stop_loss)
            position_size = risk_amount / stop_distance if stop_distance > 0 else 0
        else:
            # Stop par défaut: 1% du prix
            position_size = risk_amount / (entry_price * 0.01)
        
        # Limiter la taille de position
        max_position = self.capital * 0.95 / entry_price  # Max 95% du capital
        position_size = min(position_size, max_position)
        
        if position_size <= 0:
            return None
        
        # Calculer les frais
        fees = position_size * entry_price * self.commission_percent
        
        # Créer le trade
        trade = Trade(
            signal=signal,
            pair=pair,
            direction=signal.direction,
            entry_price=entry_price,
            quantity=position_size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_time=current_time,
            status=TradeStatus.OPEN,
            strategy_name=self.strategy.name,
            market=market,
            fees=fees,
            metadata={
                'signal_confidence': signal.confidence,
                'risk_reward': signal.risk_reward_ratio,
            }
        )
        
        # Déduire les frais du capital
        self.capital -= fees
        
        return trade
    
    def _close_trade(self, trade: Trade, current_price: float, current_time: datetime):
        """Ferme un trade."""
        # Appliquer le slippage à la sortie
        if trade.direction == TradeDirection.BUY:
            exit_price = current_price * (1 - self.slippage_percent)
        else:
            exit_price = current_price * (1 + self.slippage_percent)
        
        # Calculer le PnL
        pnl = self._calculate_pnl(trade, exit_price)
        
        # Frais de sortie
        exit_fees = trade.quantity * exit_price * self.commission_percent
        
        # Mettre à jour le trade
        trade.exit_price = exit_price
        trade.exit_time = current_time
        trade.pnl = pnl - exit_fees
        trade.fees += exit_fees
        trade.pnl_percent = (trade.pnl / (trade.entry_price * trade.quantity)) * 100
        trade.status = TradeStatus.CLOSED
        
        # Mettre à jour le capital
        self.capital += pnl - exit_fees
        
        # Déplacer des trades ouverts vers l'historique
        self.open_trades.remove(trade)
        self.trades.append(trade)
        
        # Appeler le hook de la stratégie
        self.strategy.on_trade_closed(trade)
        
        logger.debug(f"Trade fermé: {trade.pair} PnL={trade.pnl:.2f} WR={self.strategy.current_win_rate:.1%}")
    
    def _calculate_pnl(self, trade: Trade, current_price: float) -> float:
        """Calcule le PnL d'un trade."""
        if trade.direction == TradeDirection.BUY:
            return (current_price - trade.entry_price) * trade.quantity
        else:
            return (trade.entry_price - current_price) * trade.quantity
    
    def get_optimization_suggestions(self) -> Dict[str, Any]:
        """Génère des suggestions d'optimisation basées sur les résultats."""
        if not self.trades:
            return {}
        
        winners = [t for t in self.trades if t.is_winner]
        losers = [t for t in self.trades if not t.is_winner]
        
        suggestions = {
            'current_win_rate': f"{len(winners)/len(self.trades):.1%}",
            'total_trades': len(self.trades),
            'avg_win_duration': np.mean([t.duration_seconds for t in winners]) if winners else 0,
            'avg_loss_duration': np.mean([t.duration_seconds for t in losers]) if losers else 0,
        }
        
        # Analyser les patterns
        if winners:
            avg_win_pnl = np.mean([t.pnl for t in winners])
            suggestions['avg_win_pnl'] = round(avg_win_pnl, 2)
        
        if losers:
            avg_loss_pnl = np.mean([t.pnl for t in losers])
            suggestions['avg_loss_pnl'] = round(avg_loss_pnl, 2)
            
            # Suggérer un meilleur stop loss
            if avg_loss_pnl < 0:
                suggestions['suggested_stop_loss'] = f"Réduire le stop loss à {abs(avg_loss_pnl)*0.8:.2f}"
        
        # Vérifier si le win rate s'améliore
        if len(self.trades) >= 40:
            first_half = self.trades[:len(self.trades)//2]
            second_half = self.trades[len(self.trades)//2:]
            
            wr_first = len([t for t in first_half if t.is_winner]) / len(first_half)
            wr_second = len([t for t in second_half if t.is_winner]) / len(second_half)
            
            suggestions['win_rate_trend'] = 'improving' if wr_second > wr_first else 'declining'
            suggestions['win_rate_first_half'] = f"{wr_first:.1%}"
            suggestions['win_rate_second_half'] = f"{wr_second:.1%}"
        
        return suggestions
