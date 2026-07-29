"""
SMC Paper Trading System - Live Real-Time
Sweep → Displacement → FVG Pullback Entry

Connecte aux flux WebSocket et détecte les setups en temps réel.
"""

import asyncio
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

TRADE_LOG = Path(__file__).parent.parent / "logs" / "paper_trades.json"


@dataclass
class MarketState:
    """État du marché en temps réel pour une paire."""
    pair: str
    timeframe: str
    candles: List[Dict]  # OHLCV récents
    swing_highs: List[Tuple[int, float]] = field(default_factory=list)
    swing_lows: List[Tuple[int, float]] = field(default_factory=list)
    recent_sweeps: List[Dict] = field(default_factory=list)
    recent_displacements: List[Dict] = field(default_factory=list)
    active_fvg_zones: List[Dict] = field(default_factory=list)
    active_ob_zones: List[Dict] = field(default_factory=list)
    htf_bias: str = "neutral"  # bullish, bearish, neutral
    
    def as_arrays(self) -> Dict[str, np.ndarray]:
        """Convertit les candles en arrays numpy."""
        if not self.candles:
            return {}
        c = np.array([x['close'] for x in self.candles])
        h = np.array([x['high'] for x in self.candles])
        l = np.array([x['low'] for x in self.candles])
        o = np.array([x['open'] for x in self.candles])
        v = np.array([x.get('volume', 0) for x in self.candles])
        return {'close': c, 'high': h, 'low': l, 'open': o, 'volume': v}


@dataclass
class PaperTrade:
    """Trade paper trading."""
    id: str
    pair: str
    direction: str  # BUY or SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN, CLOSED, CANCELLED
    confluence_score: int = 0
    setup_type: str = ""  # "sweep_displacement_fvg"
    notes: str = ""


class SMCDetector:
    """
    Détecteur SMC en temps réel.
    
    Workflow:
    1. Surveille les swings (liquidité)
    2. Détecte les sweeps de liquidité
    3. Attend le displacement
    4. Marque les zones FVG/OB
    5. Attend le pullback dans la zone
    6. Génère le signal d'entrée
    """
    
    def __init__(self, pair: str, timeframe: str = "1h"):
        self.pair = pair
        self.timeframe = timeframe
        self.state = MarketState(pair=pair, timeframe=timeframe, candles=[])
        
        # Paramètres
        self.swing_lookback = 15
        self.sweep_threshold_pct = 0.001  # 0.1%
        self.displacement_body_pct = 0.65
        self.displacement_strength_mult = 1.1
        self.fvg_max_age_bars = 50
        self.ob_max_age_bars = 100
    
    def update(self, candle: Dict) -> Optional[Dict]:
        """
        Met à jour le détecteur avec une nouvelle bougie.
        Retourne un signal si un setup est détecté.
        """
        self.state.candles.append(candle)
        
        # Garder les 500 dernières bougies
        if len(self.state.candles) > 500:
            self.state.candles = self.state.candles[-500:]
        
        if len(self.state.candles) < 250:
            return None
        
        # Mettre à jour les structures
        self._update_swings()
        self._update_sweeps()
        self._update_displacements()
        self._update_fvg_zones()
        self._update_ob_zones()
        self._update_htf_bias()
        
        # Chercher un setup
        return self._check_for_setup()
    
    def _update_swings(self):
        """Met à jour les swing points."""
        data = self.state.as_arrays()
        if not data:
            return
        
        h = data['high']
        l = data['low']
        n = len(h)
        lb = self.swing_lookback
        
        # Nouveaux swing highs
        self.state.swing_highs = []
        for i in range(lb, n - 1):  # Pas le dernier (en cours)
            if h[i] == max(h[max(0, i-lb):i+lb+1]):
                self.state.swing_highs.append((i, float(h[i])))
        
        # Nouveaux swing lows
        self.state.swing_lows = []
        for i in range(lb, n - 1):
            if l[i] == min(l[max(0, i-lb):i+lb+1]):
                self.state.swing_lows.append((i, float(l[i])))
    
    def _update_sweeps(self):
        """Détecte les sweeps de liquidité récents."""
        data = self.state.as_arrays()
        if not data:
            return
        
        h = data['high']
        l = data['low']
        c = data['close']
        n = len(c)
        
        self.state.recent_sweeps = []
        
        # Vérifier les sweeps sur les 30 dernières bougies
        check_from = max(0, n - 30)
        
        for idx, price in self.state.swing_highs:
            if idx < check_from:
                continue
            # Le prix a-t-il dépassé le high puis rejeté?
            for i in range(idx + 1, min(idx + 20, n)):
                if h[i] > price * (1 + self.sweep_threshold_pct):
                    if c[i] < price or (i + 1 < n and c[i + 1] < price):
                        self.state.recent_sweeps.append({
                            'index': i,
                            'type': 'bullish_sweep',
                            'level': price,
                            'sweep_high': float(h[i]),
                        })
                        break
        
        for idx, price in self.state.swing_lows:
            if idx < check_from:
                continue
            for i in range(idx + 1, min(idx + 20, n)):
                if l[i] < price * (1 - self.sweep_threshold_pct):
                    if c[i] > price or (i + 1 < n and c[i + 1] > price):
                        self.state.recent_sweeps.append({
                            'index': i,
                            'type': 'bearish_sweep',
                            'level': price,
                            'sweep_low': float(l[i]),
                        })
                        break
    
    def _update_displacements(self):
        """Détecte les bougies de displacement."""
        data = self.state.as_arrays()
        if not data:
            return
        
        o = data['open']
        h = data['high']
        l = data['low']
        c = data['close']
        n = len(c)
        
        self.state.recent_displacements = []
        
        # Calculer l'ATR pour la force
        ranges = h - l
        avg_range = pd.Series(ranges).rolling(20).mean().values
        
        for i in range(max(0, n - 30), n):
            body = abs(c[i] - o[i])
            range_ = ranges[i]
            
            if range_ == 0:
                continue
            
            body_pct = body / range_
            
            if body_pct >= self.displacement_body_pct:
                strength = range_ / avg_range[i] if avg_range[i] > 0 else 1
                if strength >= self.displacement_strength_mult:
                    direction = 'bullish' if c[i] > o[i] else 'bearish'
                    self.state.recent_displacements.append({
                        'index': i,
                        'direction': direction,
                        'body_pct': float(body_pct),
                        'strength': float(strength),
                        'high': float(h[i]),
                        'low': float(l[i]),
                    })
    
    def _update_fvg_zones(self):
        """Met à jour les zones FVG actives."""
        data = self.state.as_arrays()
        if not data:
            return
        
        h = data['high']
        l = data['low']
        c = data['close']
        n = len(c)
        
        self.state.active_fvg_zones = []
        
        # Chercher les FVG récents
        for i in range(max(0, n - self.fvg_max_age_bars), n - 1):
            # FVG haussier
            if i >= 1 and i + 1 < n:
                if h[i-1] < l[i+1]:
                    # Vérifier si le FVG n'est pas encore rempli
                    filled = False
                    for j in range(i + 2, n):
                        if c[j] <= h[i-1]:
                            filled = True
                            break
                    
                    if not filled:
                        self.state.active_fvg_zones.append({
                            'index': i,
                            'direction': 'bullish',
                            'high': float(l[i+1]),
                            'low': float(h[i-1]),
                            'midpoint': float((l[i+1] + h[i-1]) / 2),
                        })
                
                # FVG baissier
                if l[i-1] > h[i+1]:
                    filled = False
                    for j in range(i + 2, n):
                        if c[j] >= l[i-1]:
                            filled = True
                            break
                    
                    if not filled:
                        self.state.active_fvg_zones.append({
                            'index': i,
                            'direction': 'bearish',
                            'high': float(l[i-1]),
                            'low': float(h[i+1]),
                            'midpoint': float((l[i-1] + h[i+1]) / 2),
                        })
    
    def _update_ob_zones(self):
        """Met à jour les zones Order Block actives."""
        data = self.state.as_arrays()
        if not data:
            return
        
        o = data['open']
        h = data['high']
        l = data['low']
        c = data['close']
        n = len(c)
        
        ranges = h - l
        avg_range = pd.Series(ranges).rolling(20).mean().values
        
        self.state.active_ob_zones = []
        
        for i in range(max(0, n - self.ob_max_age_bars), n - 3):
            # Mouvement fort après
            if i + 3 < n:
                move_up = (c[i+3] - c[i]) / c[i] if c[i] != 0 else 0
                move_down = (c[i] - c[i+3]) / c[i] if c[i] != 0 else 0
                threshold = avg_range[i] / c[i] * 2 if c[i] != 0 else 0
                
                # OB Bullish: dernière bougie baissière avant un pump
                if move_up > threshold and c[i] < o[i]:
                    self.state.active_ob_zones.append({
                        'index': i,
                        'direction': 'bullish',
                        'high': float(h[i]),
                        'low': float(l[i]),
                        'midpoint': float((h[i] + l[i]) / 2),
                    })
                
                # OB Bearish: dernière bougie haussière avant un dump
                if move_down > threshold and c[i] > o[i]:
                    self.state.active_ob_zones.append({
                        'index': i,
                        'direction': 'bearish',
                        'high': float(h[i]),
                        'low': float(l[i]),
                        'midpoint': float((h[i] + l[i]) / 2),
                    })
    
    def _update_htf_bias(self):
        """Détermine le bias HTF."""
        data = self.state.as_arrays()
        if not data:
            return
        
        c = data['close']
        
        if len(c) < 200:
            return
        
        sma50 = np.mean(c[-50:])
        sma200 = np.mean(c[-200:])
        
        if sma50 > sma200:
            self.state.htf_bias = "bullish"
        elif sma50 < sma200:
            self.state.htf_bias = "bearish"
        else:
            self.state.htf_bias = "neutral"
    
    def _check_for_setup(self) -> Optional[Dict]:
        """
        Vérifie si un setup complet est présent.
        
        CONFLUENCES:
        1. Liquidity Sweep récent (< 20 bougies)
        2. Displacement après le sweep
        3. FVG dans la zone de displacement
        4. Prix actuel dans la zone FVG (pullback)
        5. HTF bias aligné
        6. RSI confirmation
        """
        data = self.state.as_arrays()
        if not data:
            return None
        
        c = data['close']
        o = data['open']
        h = data['high']
        l = data['low']
        n = len(c)
        
        if n < 20:
            return None
        
        current_price = c[-1]
        current_idx = n - 1
        
        # RSI
        delta = np.diff(c, prepend=c[0])
        g = pd.Series(np.where(delta > 0, delta, 0)).rolling(14).mean().values
        lo = pd.Series(np.where(delta < 0, -delta, 0)).rolling(14).mean().values
        lo = np.where(lo == 0, 1e-10, lo)
        rsi = 100 - 100 / (1 + g / lo)
        current_rsi = rsi[-1] if len(rsi) > 0 else 50
        
        # ATR pour le stop
        atr = np.mean(np.abs(np.diff(c[-20:]))) if len(c) > 20 else 0.001
        
        best_setup = None
        best_score = 0
        
        # === CHERCHER SETUP LONG ===
        for sweep in self.state.recent_sweeps:
            if sweep['type'] != 'bullish_sweep':
                continue
            
            sweep_idx = sweep['index']
            
            # Vérifier displacement après le sweep
            for disp in self.state.recent_displacements:
                if disp['direction'] != 'bullish':
                    continue
                if disp['index'] <= sweep_idx or disp['index'] > sweep_idx + 15:
                    continue
                
                # Vérifier FVG dans la zone
                for fvg in self.state.active_fvg_zones:
                    if fvg['direction'] != 'bullish':
                        continue
                    if abs(fvg['index'] - disp['index']) > 5:
                        continue
                    
                    # LE MOMENT CLÉ: Le prix est-il dans la zone FVG?
                    in_fvg = fvg['low'] <= current_price <= fvg['high'] * 1.002
                    
                    if not in_fvg:
                        continue
                    
                    # Calculer le score de confluence
                    score = 0
                    score += 1  # Sweep
                    score += 1  # Displacement
                    score += 1  # FVG
                    
                    # HTF bias
                    if self.state.htf_bias == 'bullish':
                        score += 1
                    
                    # OB en confluence
                    for ob in self.state.active_ob_zones:
                        if ob['direction'] == 'bullish':
                            if ob['low'] <= current_price <= ob['high'] * 1.002:
                                score += 1
                                break
                    
                    # RSI
                    if 30 < current_rsi < 65:
                        score += 1
                    
                    # Bougie actuelle
                    if c[-1] > o[-1]:
                        score += 0.5
                    
                    if score > best_score:
                        best_score = score
                        best_setup = {
                            'direction': 'BUY',
                            'entry': current_price,
                            'stop_loss': fvg['low'] - atr * 0.3,
                            'take_profit': current_price + (current_price - (fvg['low'] - atr * 0.3)) * 2.5,
                            'confluence': int(score),
                            'fvg_zone': fvg,
                            'sweep': sweep,
                            'displacement': disp,
                        }
        
        # === CHERCHER SETUP SHORT ===
        for sweep in self.state.recent_sweeps:
            if sweep['type'] != 'bearish_sweep':
                continue
            
            sweep_idx = sweep['index']
            
            for disp in self.state.recent_displacements:
                if disp['direction'] != 'bearish':
                    continue
                if disp['index'] <= sweep_idx or disp['index'] > sweep_idx + 15:
                    continue
                
                for fvg in self.state.active_fvg_zones:
                    if fvg['direction'] != 'bearish':
                        continue
                    if abs(fvg['index'] - disp['index']) > 5:
                        continue
                    
                    in_fvg = fvg['low'] * 0.998 <= current_price <= fvg['high']
                    
                    if not in_fvg:
                        continue
                    
                    score = 0
                    score += 1
                    score += 1
                    score += 1
                    
                    if self.state.htf_bias == 'bearish':
                        score += 1
                    
                    for ob in self.state.active_ob_zones:
                        if ob['direction'] == 'bearish':
                            if ob['low'] * 0.998 <= current_price <= ob['high']:
                                score += 1
                                break
                    
                    if 35 < current_rsi < 70:
                        score += 1
                    
                    if c[-1] < o[-1]:
                        score += 0.5
                    
                    if score > best_score:
                        best_score = score
                        best_setup = {
                            'direction': 'SELL',
                            'entry': current_price,
                            'stop_loss': fvg['high'] + atr * 0.3,
                            'take_profit': current_price - ((fvg['high'] + atr * 0.3) - current_price) * 2.5,
                            'confluence': int(score),
                            'fvg_zone': fvg,
                            'sweep': sweep,
                            'displacement': disp,
                        }
        
        # Retourner le meilleur setup si confluence suffisante
        if best_setup and best_score >= 4:
            return best_setup
        
        return None


class PaperTradingEngine:
    """
    Moteur de paper trading.
    Gère les entrées/sorties et le suivi de performance.
    """
    
    def __init__(self, initial_capital: float = 50.0, risk_per_trade: float = 0.02):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.trades: List[PaperTrade] = []
        self.open_trades: List[PaperTrade] = []
        self.trade_counter = 0
    
    def open_trade(self, setup: Dict) -> PaperTrade:
        """Ouvre un nouveau trade paper."""
        self.trade_counter += 1
        trade = PaperTrade(
            id=f"PT-{self.trade_counter:04d}",
            pair=setup.get('pair', 'UNKNOWN'),
            direction=setup['direction'],
            entry_price=setup['entry'],
            stop_loss=setup['stop_loss'],
            take_profit=setup['take_profit'],
            entry_time=datetime.now(),
            confluence_score=setup['confluence'],
            setup_type='sweep_displacement_fvg',
        )
        
        self.open_trades.append(trade)
        self.trades.append(trade)
        
        logger.info(f"📈 TRADE OUVERT: {trade.id} {trade.direction} {trade.pair} @ {trade.entry_price:.5f} | SL={trade.stop_loss:.5f} TP={trade.take_profit:.5f} | Conf={trade.confluence_score}")
        
        return trade
    
    def update(self, pair: str, current_price: float):
        """Met à jour les trades ouverts avec le prix actuel."""
        for trade in self.open_trades[:]:
            if trade.pair != pair:
                continue
            
            # Vérifier stop loss
            if trade.direction == 'BUY' and current_price <= trade.stop_loss:
                self._close_trade(trade, trade.stop_loss, 'STOP_LOSS')
            elif trade.direction == 'SELL' and current_price >= trade.stop_loss:
                self._close_trade(trade, trade.stop_loss, 'STOP_LOSS')
            
            # Vérifier take profit
            elif trade.direction == 'BUY' and current_price >= trade.take_profit:
                self._close_trade(trade, trade.take_profit, 'TAKE_PROFIT')
            elif trade.direction == 'SELL' and current_price <= trade.take_profit:
                self._close_trade(trade, trade.take_profit, 'TAKE_PROFIT')
    
    def _close_trade(self, trade: PaperTrade, exit_price: float, reason: str):
        """Ferme un trade."""
        trade.exit_price = exit_price
        trade.exit_time = datetime.now()
        trade.status = "CLOSED"
        
        # Calculer PnL
        if trade.direction == 'BUY':
            pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - exit_price) / trade.entry_price
        
        risk_amount = self.capital * self.risk_per_trade
        trade.pnl = risk_amount * pnl_pct * (trade.entry_price / abs(trade.entry_price - trade.stop_loss))
        
        self.capital += trade.pnl
        self.open_trades.remove(trade)
        
        emoji = "✅" if trade.pnl > 0 else "❌"
        logger.info(f"{emoji} TRADE FERMÉ: {trade.id} {reason} @ {exit_price:.5f} | PnL=${trade.pnl:.2f} | Capital=${self.capital:.2f}")
        
        # Sauvegarder
        self._save_trade(trade)
    
    def _save_trade(self, trade: PaperTrade):
        """Sauvegarde un trade dans le log."""
        TRADE_LOG.parent.mkdir(parents=True, exist_ok=True)
        
        trades_data = []
        if TRADE_LOG.exists():
            with open(TRADE_LOG, 'r') as f:
                trades_data = json.load(f)
        
        trades_data.append(asdict(trade))
        
        with open(TRADE_LOG, 'w') as f:
            json.dump(trades_data, f, indent=2, default=str)
    
    def get_stats(self) -> Dict:
        """Retourne les statistiques de performance."""
        closed = [t for t in self.trades if t.status == 'CLOSED']
        if not closed:
            return {'trades': 0, 'wr': 0}
        
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        
        return {
            'total_trades': len(closed),
            'open_trades': len(self.open_trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins) / len(closed),
            'total_pnl': sum(t.pnl for t in closed),
            'current_capital': self.capital,
            'avg_win': np.mean([t.pnl for t in wins]) if wins else 0,
            'avg_loss': np.mean([t.pnl for t in losses]) if losses else 0,
            'profit_factor': abs(sum(t.pnl for t in wins) / sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses) != 0 else 0,
        }


class SMCPaperTrader:
    """
    Système complet de paper trading SMC.
    Combine le détecteur et le moteur de trading.
    """
    
    def __init__(self, pairs: List[str], timeframe: str = "1h", capital: float = 50.0):
        self.pairs = pairs
        self.timeframe = timeframe
        self.detectors = {pair: SMCDetector(pair, timeframe) for pair in pairs}
        self.engine = PaperTradingEngine(capital)
        self.running = False
    
    def on_candle(self, pair: str, candle: Dict):
        """Appelé à chaque nouvelle bougie."""
        if pair not in self.detectors:
            return
        
        detector = self.detectors[pair]
        setup = detector.update(candle)
        
        # Mettre à jour les trades ouverts
        self.engine.update(pair, candle['close'])
        
        # Si un setup est détecté
        if setup:
            setup['pair'] = pair
            
            # Vérifier qu'on n'a pas déjà un trade ouvert sur cette paire
            open_pairs = [t.pair for t in self.engine.open_trades]
            if pair in open_pairs:
                logger.debug(f"Setup ignoré: trade déjà ouvert sur {pair}")
                return
            
            self.engine.open_trade(setup)
    
    def get_status(self) -> Dict:
        """Retourne le statut complet."""
        stats = self.engine.get_stats()
        return {
            'pairs': self.pairs,
            'timeframe': self.timeframe,
            'performance': stats,
            'open_trades': [
                {
                    'id': t.id,
                    'pair': t.pair,
                    'direction': t.direction,
                    'entry': t.entry_price,
                    'sl': t.stop_loss,
                    'tp': t.take_profit,
                    'conf': t.confluence_score,
                }
                for t in self.engine.open_trades
            ],
        }
