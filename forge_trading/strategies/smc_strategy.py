"""
Stratégie Smart Money Concepts (SMC) - Approche Institutionnelle
Utilise les Fair Value Gaps (FVG) et Order Blocks (OB) pour des entrées haute probabilité.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class FVG:
    """Fair Value Gap"""
    index: int
    direction: str  # 'bullish' or 'bearish'
    high: float     # Top of gap
    low: float      # Bottom of gap
    midpoint: float
    filled: bool = False
    fill_index: int = -1


@dataclass
class OrderBlock:
    """Order Block (zone institutionnelle)"""
    index: int
    direction: str  # 'bullish' or 'bearish'
    high: float
    low: float
    midpoint: float
    tested: bool = False
    test_count: int = 0


@dataclass 
class StructureBreak:
    """Break of Structure (BOS)"""
    index: int
    direction: str  # 'bullish_bos' or 'bearish_bos'
    level: float
    strength: float  # 0-1


def detect_fvg(data: pd.DataFrame, min_gap_pct: float = 0.0001) -> List[FVG]:
    """
    Détecte les Fair Value Gaps.
    
    FVG Bullish: candle[i-1].high < candle[i+1].low (gap haussier)
    FVG Bearish: candle[i-1].low > candle[i+1].high (gap baissier)
    """
    fvgs = []
    high = data['high'].values
    low = data['low'].values
    close = data['close'].values
    
    for i in range(1, len(data) - 1):
        # FVG Bullish
        if high[i-1] < low[i+1]:
            gap_size = (low[i+1] - high[i-1]) / close[i]
            if gap_size >= min_gap_pct:
                fvgs.append(FVG(
                    index=i,
                    direction='bullish',
                    high=low[i+1],
                    low=high[i-1],
                    midpoint=(low[i+1] + high[i-1]) / 2
                ))
        
        # FVG Bearish
        if low[i-1] > high[i+1]:
            gap_size = (low[i-1] - high[i+1]) / close[i]
            if gap_size >= min_gap_pct:
                fvgs.append(FVG(
                    index=i,
                    direction='bearish',
                    high=low[i-1],
                    low=high[i+1],
                    midpoint=(low[i-1] + high[i+1]) / 2
                ))
    
    return fvgs


def detect_order_blocks(data: pd.DataFrame, lookback: int = 50) -> List[OrderBlock]:
    """
    Détecte les Order Blocks.
    
    OB Bullish: Dernière bougie baissière avant un mouvement haussier fort
    OB Bearish: Dernière bougie haussière avant un mouvement baissier fort
    """
    obs = []
    close = data['close'].values
    open_p = data['open'].values
    high = data['high'].values
    low = data['low'].values
    
    # Calculer la volatilité pour le seuil
    atr = pd.Series(np.abs(np.diff(close, prepend=close[0]))).rolling(14).mean().values
    
    for i in range(lookback, len(data) - 3):
        # Mouvement fort = 2x ATR sur 3 bougies
        move_up = (high[i+3] - close[i]) / close[i]
        move_down = (close[i] - low[i+3]) / close[i]
        threshold = atr[i] / close[i] * 2
        
        # OB Bullish: bougie baissière avant un pump
        if move_up > threshold:
            if close[i] < open_p[i]:  # Bougie baissière
                obs.append(OrderBlock(
                    index=i,
                    direction='bullish',
                    high=high[i],
                    low=low[i],
                    midpoint=(high[i] + low[i]) / 2
                ))
        
        # OB Bearish: bougie haussière avant un dump
        if move_down > threshold:
            if close[i] > open_p[i]:  # Bougie haussière
                obs.append(OrderBlock(
                    index=i,
                    direction='bearish',
                    high=high[i],
                    low=low[i],
                    midpoint=(high[i] + low[i]) / 2
                ))
    
    return obs


def detect_structure_breaks(data: pd.DataFrame, swing_lookback: int = 10) -> List[StructureBreak]:
    """
    Détecte les Breaks of Structure (BOS).
    Indique le changement de tendance institutionnel.
    """
    breaks = []
    high = data['high'].values
    low = data['low'].values
    close = data['close'].values
    
    # Trouver les swing points
    swing_highs = []
    swing_lows = []
    
    for i in range(swing_lookback, len(data) - swing_lookback):
        # Swing High
        if high[i] == max(high[i-swing_lookback:i+swing_lookback+1]):
            swing_highs.append((i, high[i]))
        
        # Swing Low
        if low[i] == min(low[i-swing_lookback:i+swing_lookback+1]):
            swing_lows.append((i, low[i]))
    
    # Détecter les BOS
    for i in range(1, len(swing_highs)):
        if swing_highs[i][1] > swing_highs[i-1][1]:
            # Higher High = Bullish BOS
            strength = (swing_highs[i][1] - swing_highs[i-1][1]) / swing_highs[i-1][1]
            breaks.append(StructureBreak(
                index=swing_highs[i][0],
                direction='bullish_bos',
                level=swing_highs[i][1],
                strength=min(1.0, strength * 100)
            ))
    
    for i in range(1, len(swing_lows)):
        if swing_lows[i][1] < swing_lows[i-1][1]:
            # Lower Low = Bearish BOS
            strength = (swing_lows[i-1][1] - swing_lows[i][1]) / swing_lows[i-1][1]
            breaks.append(StructureBreak(
                index=swing_lows[i][0],
                direction='bearish_bos',
                level=swing_lows[i][1],
                strength=min(1.0, strength * 100)
            ))
    
    return breaks


def smc_backtest(
    data: pd.DataFrame,
    initial_capital: float = 50.0,
    risk_per_trade: float = 0.02,
    sl_atr_mult: float = 1.0,
    tp_rr_ratio: float = 2.5,  # 1:2.5 R:R
    max_spread: float = 0.00015,
    commission: float = 0.0001,
    require_bos: bool = True,       # Exiger un BOS avant l'entrée
    require_ob_confluence: bool = True,  # OB + FVG confluence
    min_fvg_quality: float = 0.0001,
) -> Dict:
    """
    Backtest Smart Money Concepts.
    
    Logique d'entrée:
    1. BOS confirme la direction (structure break)
    2. Prix revient vers un Order Block
    3. Un FVG se forme dans la zone OB
    4. Entrée à la confluence OB + FVG
    5. Stop loss sous l'OB, Take profit au prochain niveau
    """
    close = data['close'].values
    high = data['high'].values
    low = data['low'].values
    open_p = data['open'].values
    
    # Pré-détecter les structures
    fvgs = detect_fvg(data, min_fvg_quality)
    order_blocks = detect_order_blocks(data)
    structure_breaks = detect_structure_breaks(data)
    
    # Indexer les structures par position
    fvg_by_index = {}
    for fvg in fvgs:
        if fvg.index not in fvg_by_index:
            fvg_by_index[fvg.index] = []
        fvg_by_index[fvg.index].append(fvg)
    
    ob_by_index = {}
    for ob in order_blocks:
        if ob.index not in ob_by_index:
            ob_by_index[ob.index] = []
        ob_by_index[ob.index].append(ob)
    
    # ATR pour stops
    atr = pd.Series(np.abs(np.diff(close, prepend=close[0]))).rolling(14).mean().values
    
    # SMA pour tendance
    sma_20 = pd.Series(close).rolling(20).mean().values
    sma_50 = pd.Series(close).rolling(50).mean().values
    
    trades = []
    capital = initial_capital
    in_trade = False
    trade_entry = 0
    trade_sl = 0
    trade_tp = 0
    trade_dir = 0
    
    # Dernier BOS pour confirmer la direction
    last_bullish_bos = -100
    last_bearish_bos = -100
    
    for bos in structure_breaks:
        if bos.direction == 'bullish_bos':
            last_bullish_bos = bos.index
        else:
            last_bearish_bos = bos.index
    
    # Fenêtre de recherche active pour OB/FVG
    active_obs_bullish = []
    active_obs_bearish = []
    
    for i in range(60, len(data)):
        # Mettre à jour les OB actifs
        if i in ob_by_index:
            for ob in ob_by_index[i]:
                if ob.direction == 'bullish':
                    active_obs_bullish.append(ob)
                else:
                    active_obs_bearish.append(ob)
            
            # Garder seulement les 20 derniers OB
            active_obs_bullish = active_obs_bullish[-20:]
            active_obs_bearish = active_obs_bearish[-20:]
        
        # Mettre à jour les BOS
        if i in [bos.index for bos in structure_breaks]:
            for bos in structure_breaks:
                if bos.index == i:
                    if bos.direction == 'bullish_bos':
                        last_bullish_bos = i
                    else:
                        last_bearish_bos = i
        
        if in_trade:
            # Vérifier sortie
            exit_price = None
            
            if trade_dir == 1:  # Long
                if low[i] <= trade_sl:
                    exit_price = trade_sl
                elif high[i] >= trade_tp:
                    exit_price = trade_tp
            else:  # Short
                if high[i] >= trade_sl:
                    exit_price = trade_sl
                elif low[i] <= trade_tp:
                    exit_price = trade_tp
            
            if exit_price:
                pnl_pct = (exit_price - trade_entry) / trade_entry * trade_dir
                pnl = capital * risk_per_trade * (pnl_pct * trade_entry / (trade_entry - trade_sl)) if trade_dir == 1 else capital * risk_per_trade * (pnl_pct * trade_entry / (trade_sl - trade_entry))
                pnl -= capital * risk_per_trade * commission * 2  # fees
                
                capital += pnl
                capital = max(0.01, capital)
                
                trades.append({
                    'entry_idx': trade_entry_idx,
                    'exit_idx': i,
                    'direction': 'BUY' if trade_dir == 1 else 'SELL',
                    'entry': trade_entry,
                    'exit': exit_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'winner': pnl > 0,
                    'duration': i - trade_entry_idx,
                    'capital': capital,
                })
                
                in_trade = False
            continue
        
        # Chercher une entrée
        bullish_entry = False
        bearish_entry = False
        
        # === SIGNAL LONG ===
        # Condition 1: BOS haussier récent (dans les 50 dernières bougies)
        bos_bullish_ok = (i - last_bullish_bos) < 50 and require_bos
        if not require_bos:
            bos_bullish_ok = sma_20[i] > sma_50[i]  # Tendance haussière
        
        # Condition 2: Prix revient vers un OB haussier
        ob_bullish_zone = None
        for ob in active_obs_bullish:
            if ob.low <= close[i] <= ob.high * 1.002:  # Prix dans la zone OB
                ob_bullish_zone = ob
                break
        
        # Condition 3: FVG haussier dans la zone
        fvg_bullish_ok = False
        if i in fvg_by_index:
            for fvg in fvg_by_index[i]:
                if fvg.direction == 'bullish':
                    fvg_bullish_ok = True
                    break
        
        # Chercher FVG dans les 5 dernières bougies aussi
        if not fvg_bullish_ok:
            for j in range(max(0, i-5), i+1):
                if j in fvg_by_index:
                    for fvg in fvg_by_index[j]:
                        if fvg.direction == 'bullish':
                            fvg_bullish_ok = True
                            break
        
        # Confluence Long
        if bos_bullish_ok and ob_bullish_zone and fvg_bullish_ok:
            bullish_entry = True
        
        # === SIGNAL SHORT ===
        bos_bearish_ok = (i - last_bearish_bos) < 50 and require_bos
        if not require_bos:
            bos_bearish_ok = sma_20[i] < sma_50[i]
        
        ob_bearish_zone = None
        for ob in active_obs_bearish:
            if ob.low * 0.998 <= close[i] <= ob.high:
                ob_bearish_zone = ob
                break
        
        fvg_bearish_ok = False
        if i in fvg_by_index:
            for fvg in fvg_by_index[i]:
                if fvg.direction == 'bearish':
                    fvg_bearish_ok = True
                    break
        
        if not fvg_bearish_ok:
            for j in range(max(0, i-5), i+1):
                if j in fvg_by_index:
                    for fvg in fvg_by_index[j]:
                        if fvg.direction == 'bearish':
                            fvg_bearish_ok = True
                            break
        
        if bos_bearish_ok and ob_bearish_zone and fvg_bearish_ok:
            bearish_entry = True
        
        # Exécuter l'entrée
        if bullish_entry and not bearish_entry:
            trade_entry = close[i] * (1 + max_spread)
            trade_sl = ob_bullish_zone.low - atr[i] * sl_atr_mult
            risk = trade_entry - trade_sl
            trade_tp = trade_entry + risk * tp_rr_ratio
            trade_dir = 1
            trade_entry_idx = i
            in_trade = True
            
        elif bearish_entry and not bullish_entry:
            trade_entry = close[i] * (1 - max_spread)
            trade_sl = ob_bearish_zone.high + atr[i] * sl_atr_mult
            risk = trade_sl - trade_entry
            trade_tp = trade_entry - risk * tp_rr_ratio
            trade_dir = -1
            trade_entry_idx = i
            in_trade = True
    
    # Calculer les stats
    if not trades:
        return {'total_trades': 0, 'win_rate': 0, 'trades': []}
    
    df = pd.DataFrame(trades)
    wins = df[df['winner']]
    losses = df[~df['winner']]
    
    return {
        'total_trades': len(df),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': len(wins) / len(df),
        'total_pnl': df['pnl'].sum(),
        'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
        'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0,
        'profit_factor': abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 0,
        'max_drawdown': ((df['capital'].cumsum() - df['capital'].cumsum().expanding().max()) / df['capital'].cumsum().expanding().max()).min() if len(df) > 0 else 0,
        'final_capital': df['capital'].iloc[-1],
        'avg_duration': df['duration'].mean(),
        'trades': trades,
    }
