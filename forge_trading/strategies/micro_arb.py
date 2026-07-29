"""
Stratégie d'Arbitrage Micro-Gaps
Exploite les micro-différences de prix entre marchés.
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime

from .base_strategy import (
    BaseStrategy, Signal, Trade, 
    TradeDirection, TradeStatus
)


class MicroArbitrageStrategy(BaseStrategy):
    """
    Stratégie d'arbitrage sur les micro-gaps de prix.
    
    Logique:
    1. Détecte les écarts de prix anormaux (micro-gaps)
    2. Entre en position quand le spread dépasse le seuil
    3. Sort quand le prix revient à la moyenne (mean reversion)
    
    Paramètres optimisables:
    - gap_threshold: Seuil de détection du gap (en %)
    - lookback_period: Période de lookback pour la moyenne
    - exit_at_mean: Sortir quand le prix revient à la moyenne
    - min_volume: Volume minimum pour valider le signal
    """
    
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        default_params = {
            'gap_threshold': 0.002,      # 0.2% de gap minimum
            'lookback_period': 20,       # 20 périodes pour la moyenne
            'exit_at_mean': True,        # Sortir à la moyenne
            'stop_loss_atr_mult': 2.0,   # Stop loss = 2x ATR
            'take_profit_atr_mult': 3.0, # Take profit = 3x ATR
            'min_volume_percentile': 30, # Volume minimum (30ème percentile)
            'rsi_oversold': 30,          # RSI survendu
            'rsi_overbought': 70,        # RSI suracheté
            'require_confirmation': True, # Exiger confirmation
            'max_spread': 0.005,         # Spread maximum 0.5%
        }
        
        if params:
            default_params.update(params)
        
        super().__init__("micro_arb", default_params)
        
        # Historique pour calculs
        self._price_history: List[float] = []
        self._volume_history: List[float] = []
        self._gaps_detected: int = 0
        self._gaps_traded: int = 0
    
    def generate_signal(self, market_data: Dict[str, Any]) -> Optional[Signal]:
        """
        Génère un signal basé sur la détection de micro-gaps.
        """
        pair = market_data.get('pair', 'UNKNOWN')
        current_price = market_data.get('close', 0)
        current_volume = market_data.get('volume', 0)
        
        if current_price == 0:
            return None
        
        # Mettre à jour l'historique
        self._price_history.append(current_price)
        self._volume_history.append(current_volume)
        
        # Garder seulement les N dernières valeurs
        max_history = self.params['lookback_period'] * 3
        if len(self._price_history) > max_history:
            self._price_history = self._price_history[-max_history:]
            self._volume_history = self._volume_history[-max_history:]
        
        # Pas assez de données
        if len(self._price_history) < self.params['lookback_period']:
            return None
        
        # Calculer les indicateurs
        prices = np.array(self._price_history)
        volumes = np.array(self._volume_history)
        
        # Moyenne mobile
        sma = np.mean(prices[-self.params['lookback_period']:])
        
        # Écart par rapport à la moyenne
        gap = (current_price - sma) / sma
        
        # RSI
        rsi = market_data.get('rsi', 50)
        
        # ATR
        atr = market_data.get('atr', 0.001)
        
        # Volume
        volume_percentile = (current_volume - np.min(volumes)) / (np.max(volumes) - np.min(volumes)) * 100 if np.max(volumes) > np.min(volumes) else 50
        
        # Détection du gap
        self._gaps_detected += 1
        
        # Conditions d'achat (gap négatif = prix sous la moyenne)
        if gap < -self.params['gap_threshold']:
            # Vérifier les conditions de confirmation
            if self._check_buy_conditions(gap, rsi, volume_percentile, atr, market_data):
                self._gaps_traded += 1
                return self._create_buy_signal(pair, current_price, sma, atr, gap, market_data)
        
        # Conditions de vente (gap positif = prix au-dessus de la moyenne)
        elif gap > self.params['gap_threshold']:
            if self._check_sell_conditions(gap, rsi, volume_percentile, atr, market_data):
                self._gaps_traded += 1
                return self._create_sell_signal(pair, current_price, sma, atr, gap, market_data)
        
        return None
    
    def _check_buy_conditions(
        self, 
        gap: float, 
        rsi: float, 
        volume_pct: float,
        atr: float,
        market_data: Dict
    ) -> bool:
        """Vérifie les conditions pour un signal d'achat."""
        # Volume minimum
        if volume_pct < self.params['min_volume_percentile']:
            return False
        
        # RSI survendu (confirmation)
        if self.params['require_confirmation'] and rsi > self.params['rsi_oversold'] + 20:
            return False
        
        # Vérifier le spread (si disponible)
        spread = market_data.get('spread', 0)
        if spread > self.params['max_spread']:
            return False
        
        # Vérifier la volatilité (pas trop élevée)
        volatility = market_data.get('volatility', 0)
        if volatility > 0.5:  # >50% volatilité annualisée = trop risqué
            return False
        
        return True
    
    def _check_sell_conditions(
        self, 
        gap: float, 
        rsi: float, 
        volume_pct: float,
        atr: float,
        market_data: Dict
    ) -> bool:
        """Vérifie les conditions pour un signal de vente."""
        if volume_pct < self.params['min_volume_percentile']:
            return False
        
        if self.params['require_confirmation'] and rsi < self.params['rsi_overbought'] - 20:
            return False
        
        spread = market_data.get('spread', 0)
        if spread > self.params['max_spread']:
            return False
        
        return True
    
    def _create_buy_signal(
        self, 
        pair: str, 
        price: float, 
        sma: float, 
        atr: float,
        gap: float,
        market_data: Dict
    ) -> Signal:
        """Crée un signal d'achat."""
        # Stop loss sous le prix actuel
        stop_loss = price - (atr * self.params['stop_loss_atr_mult'])
        
        # Take profit à la moyenne ou au-delà
        if self.params['exit_at_mean']:
            take_profit = sma  # Objectif: retour à la moyenne
        else:
            take_profit = price + (atr * self.params['take_profit_atr_mult'])
        
        # Calculer la confiance basée sur la taille du gap et le RSI
        rsi = market_data.get('rsi', 50)
        confidence = min(0.9, abs(gap) * 100 + (self.params['rsi_oversold'] - rsi) / 100)
        confidence = max(0.3, confidence)  # Minimum 30%
        
        return Signal(
            pair=pair,
            direction=TradeDirection.BUY,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            strategy_name=self.name,
            metadata={
                'gap': gap,
                'sma': sma,
                'atr': atr,
                'rsi': rsi,
                'volume': market_data.get('volume', 0),
            }
        )
    
    def _create_sell_signal(
        self, 
        pair: str, 
        price: float, 
        sma: float, 
        atr: float,
        gap: float,
        market_data: Dict
    ) -> Signal:
        """Crée un signal de vente."""
        stop_loss = price + (atr * self.params['stop_loss_atr_mult'])
        
        if self.params['exit_at_mean']:
            take_profit = sma
        else:
            take_profit = price - (atr * self.params['take_profit_atr_mult'])
        
        rsi = market_data.get('rsi', 50)
        confidence = min(0.9, abs(gap) * 100 + (rsi - self.params['rsi_overbought']) / 100)
        confidence = max(0.3, confidence)
        
        return Signal(
            pair=pair,
            direction=TradeDirection.SELL,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            strategy_name=self.name,
            metadata={
                'gap': gap,
                'sma': sma,
                'atr': atr,
                'rsi': rsi,
            }
        )
    
    def should_exit(self, trade: Trade, current_price: float, market_data: Dict[str, Any]) -> bool:
        """
        Détermine si on doit sortir d'une position.
        
        Conditions de sortie:
        1. Stop loss atteint
        2. Take profit atteint
        3. Prix revenu à la moyenne (si exit_at_mean=True)
        4. Signal opposé détecté
        """
        # Stop loss
        if trade.direction == TradeDirection.BUY:
            if current_price <= trade.stop_loss:
                return True
        else:
            if current_price >= trade.stop_loss:
                return True
        
        # Take profit
        if trade.direction == TradeDirection.BUY:
            if current_price >= trade.take_profit:
                return True
        else:
            if current_price <= trade.take_profit:
                return True
        
        # Retour à la moyenne
        if self.params['exit_at_mean']:
            sma = market_data.get('sma_20', 0)
            if sma > 0:
                if trade.direction == TradeDirection.BUY and current_price >= sma:
                    return True
                elif trade.direction == TradeDirection.SELL and current_price <= sma:
                    return True
        
        # Trailing stop dynamique (après 50% du take profit atteint)
        if trade.direction == TradeDirection.BUY:
            progress = (current_price - trade.entry_price) / (trade.take_profit - trade.entry_price)
            if progress > 0.5:
                # Déplacer le stop loss au break-even
                new_stop = trade.entry_price + (current_price - trade.entry_price) * 0.3
                if new_stop > trade.stop_loss:
                    trade.stop_loss = new_stop
        else:
            progress = (trade.entry_price - current_price) / (trade.entry_price - trade.take_profit)
            if progress > 0.5:
                new_stop = trade.entry_price - (trade.entry_price - current_price) * 0.3
                if new_stop < trade.stop_loss:
                    trade.stop_loss = new_stop
        
        return False
    
    def optimize(self, trades: List[Trade]) -> Dict[str, Any]:
        """
        Optimise les paramètres basé sur l'historique des trades.
        Utilise le système de réflexion de la Forge.
        """
        if len(trades) < 20:
            return self.params
        
        # Analyser les trades gagnants et perdants
        winners = [t for t in trades if t.is_winner]
        losers = [t for t in trades if not t.is_winner]
        
        # Ajuster le seuil de gap
        if winners:
            avg_gap_winner = np.mean([abs(t.metadata.get('gap', 0)) for t in winners])
            self.params['gap_threshold'] = avg_gap_winner * 0.8  # 80% du gap moyen gagnant
        
        # Ajuster le stop loss
        if losers:
            avg_loss = np.mean([abs(t.pnl_percent) for t in losers])
            self.params['stop_loss_atr_mult'] = max(1.5, avg_loss / 2)
        
        # Ajuster le take profit
        if winners:
            avg_win = np.mean([t.pnl_percent for t in winners])
            self.params['take_profit_atr_mult'] = max(2.0, avg_win * 1.5)
        
        # Ajuster les seuils RSI
        if winners:
            rsi_values = [t.metadata.get('rsi', 50) for t in winners if t.direction == TradeDirection.BUY]
            if rsi_values:
                self.params['rsi_oversold'] = np.percentile(rsi_values, 25)
            
            rsi_values_sell = [t.metadata.get('rsi', 50) for t in winners if t.direction == TradeDirection.SELL]
            if rsi_values_sell:
                self.params['rsi_overbought'] = np.percentile(rsi_values_sell, 75)
        
        # Mettre à jour le win rate EMA
        super().optimize(trades)
        
        return self.params
    
    def get_stats(self) -> Dict[str, Any]:
        """Statistiques étendues de la stratégie."""
        base_stats = super().get_stats()
        base_stats.update({
            'gaps_detected': self._gaps_detected,
            'gaps_traded': self._gaps_traded,
            'gap_hit_rate': f"{self._gaps_traded/self._gaps_detected:.1%}" if self._gaps_detected > 0 else "N/A",
            'params': self.params
        })
        return base_stats
