"""
SMC v3 - Méthode Institutionnelle Complète
Liquidity Sweep → Displacement → FVG Entry

C'est la vraie méthode que les institutions utilisent.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class LiquidityLevel:
    """Niveau de liquidité (high/low significatif)"""
    index: int
    price: float
    type: str  # 'high' or 'low'
    swept: bool = False
    sweep_index: int = -1


@dataclass
class Displacement:
    """Bougie de displacement (momentum institutionnel)"""
    index: int
    direction: str  # 'bullish' or 'bearish'
    body_pct: float  # % du body par rapport à la range
    strength: float  # 0-1


@dataclass
class SetupSMC:
    """Setup SMC complet"""
    index: int
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    confluence_score: int
    liquidity_level: LiquidityLevel
    displacement: Displacement
    fvg_midpoint: float


def find_swing_points(data: pd.DataFrame, lookback: int = 20) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Trouve les swing highs et swing lows significatifs."""
    high = data['high'].values
    low = data['low'].values
    
    swing_highs = []
    swing_lows = []
    
    for i in range(lookback, len(data) - lookback):
        # Swing High: plus haut dans la fenêtre
        window_high = max(high[i-lookback:i+lookback+1])
        if high[i] == window_high:
            swing_highs.append((i, high[i]))
        
        # Swing Low: plus bas dans la fenêtre
        window_low = min(low[i-lookback:i+lookback+1])
        if low[i] == window_low:
            swing_lows.append((i, low[i]))
    
    return swing_highs, swing_lows


def detect_liquidity_sweep(
    data: pd.DataFrame,
    swing_highs: List[Tuple[int, float]],
    swing_lows: List[Tuple[int, float]],
    sweep_threshold: float = 0.001  # 0.1% au-delà du niveau
) -> Tuple[List[LiquidityLevel], List[Tuple[int, str, LiquidityLevel]]]:
    """
    Détecte les sweeps de liquidité.
    
    Un sweep se produit quand:
    - Le prix dépasse un swing high/low
    - Puis revient immédiatement de l'autre côté
    - C'est un "stop hunt" institutionnel
    """
    high = data['high'].values
    low = data['low'].values
    close = data['close'].values
    
    levels = []
    sweeps = []
    
    # Créer les niveaux de liquidité
    for idx, price in swing_highs:
        levels.append(LiquidityLevel(index=idx, price=price, type='high'))
    
    for idx, price in swing_lows:
        levels.append(LiquidityLevel(index=idx, price=price, type='low'))
    
    # Détecter les sweeps
    for level in levels:
        for i in range(level.index + 5, min(level.index + 200, len(data))):
            if level.type == 'high':
                # Sweep haussier: prix dépasse le high puis revient
                if high[i] > level.price * (1 + sweep_threshold):
                    # Vérifier que le close est en dessous (rejet)
                    if close[i] < level.price:
                        level.swept = True
                        level.sweep_index = i
                        sweeps.append((i, 'bullish_sweep', level))
                        break
                    # Ou que la bougie suivante rejette
                    if i + 1 < len(data) and close[i+1] < level.price:
                        level.swept = True
                        level.sweep_index = i
                        sweeps.append((i, 'bullish_sweep', level))
                        break
            
            elif level.type == 'low':
                # Sweep baissier: prix passe sous le low puis revient
                if low[i] < level.price * (1 - sweep_threshold):
                    if close[i] > level.price:
                        level.swept = True
                        level.sweep_index = i
                        sweeps.append((i, 'bearish_sweep', level))
                        break
                    if i + 1 < len(data) and close[i+1] > level.price:
                        level.swept = True
                        level.sweep_index = i
                        sweeps.append((i, 'bearish_sweep', level))
                        break
    
    return levels, sweeps


def detect_displacement(data: pd.DataFrame, min_body_pct: float = 0.6) -> List[Displacement]:
    """
    Détecte les bougies de displacement.
    
    Une bougie de displacement a:
    - Un grand body (>60% de la range)
    - Peu de mèches
    - Volume élevé (si disponible)
    """
    open_p = data['open'].values
    high = data['high'].values
    low = data['low'].values
    close = data['close'].values
    
    displacements = []
    
    for i in range(1, len(data)):
        body = abs(close[i] - open_p[i])
        range_ = high[i] - low[i]
        
        if range_ == 0:
            continue
        
        body_pct = body / range_
        
        if body_pct >= min_body_pct:
            # Direction
            if close[i] > open_p[i]:
                direction = 'bullish'
            else:
                direction = 'bearish'
            
            # Strength basé sur la taille relative
            avg_range = np.mean(high[max(0,i-20):i] - low[max(0,i-20):i])
            strength = min(1.0, range_ / avg_range) if avg_range > 0 else 0.5
            
            if strength > 1.2:  # Au moins 20% plus grand que la moyenne
                displacements.append(Displacement(
                    index=i,
                    direction=direction,
                    body_pct=body_pct,
                    strength=strength
                ))
    
    return displacements


def detect_fvg_after_displacement(
    data: pd.DataFrame,
    displacements: List[Displacement],
    max_gap_bars: int = 3
) -> List[Tuple[Displacement, float, float, float]]:
    """
    Détecte les FVG créés par les displacements.
    
    Le FVG doit être créé dans les 3 bougies après le displacement.
    Retourne (displacement, fvg_high, fvg_low, fvg_midpoint)
    """
    high = data['high'].values
    low = data['low'].values
    
    fvg_list = []
    
    for disp in displacements:
        i = disp.index
        
        for j in range(i, min(i + max_gap_bars, len(data) - 1)):
            if disp.direction == 'bullish':
                # FVG haussier: high[j-1] < low[j+1]
                if j >= 1 and j + 1 < len(data):
                    if high[j-1] < low[j+1]:
                        fvg_high = low[j+1]
                        fvg_low = high[j-1]
                        fvg_mid = (fvg_high + fvg_low) / 2
                        fvg_list.append((disp, fvg_high, fvg_low, fvg_mid))
                        break
            
            elif disp.direction == 'bearish':
                # FVG baissier: low[j-1] > high[j+1]
                if j >= 1 and j + 1 < len(data):
                    if low[j-1] > high[j+1]:
                        fvg_high = low[j-1]
                        fvg_low = high[j+1]
                        fvg_mid = (fvg_high + fvg_low) / 2
                        fvg_list.append((disp, fvg_high, fvg_low, fvg_mid))
                        break
    
    return fvg_list


def find_order_block(data: pd.DataFrame, displacement: Displacement) -> Optional[Tuple[float, float]]:
    """
    Trouve l'Order Block associé à un displacement.
    
    OB haussier: dernière bougie baissière AVANT le displacement
    OB baissier: dernière bougie haussière AVANT le displacement
    """
    open_p = data['open'].values
    close = data['close'].values
    high = data['high'].values
    low = data['low'].values
    
    i = displacement.index
    
    if displacement.direction == 'bullish':
        # Chercher la dernière bougie baissière avant
        for j in range(i-1, max(0, i-10), -1):
            if close[j] < open_p[j]:
                return (high[j], low[j])
    
    elif displacement.direction == 'bearish':
        # Chercher la dernière bougie haussière avant
        for j in range(i-1, max(0, i-10), -1):
            if close[j] > open_p[j]:
                return (high[j], low[j])
    
    return None


def smc_v3_backtest(
    data: pd.DataFrame,
    htf_data: Optional[pd.DataFrame] = None,
    initial_capital: float = 50.0,
    risk_per_trade: float = 0.02,
    rr_target: float = 2.5,
    spread: float = 0.00012,
    commission: float = 0.0001,
    min_confluence: int = 5,
) -> Dict:
    """
    Backtest SMC v3 - Méthode Institutionnelle
    
    CONFLUENCES:
    1. HTF Trend (SMA50 > SMA200)
    2. Liquidity Sweep confirmé
    3. Displacement candle (fort momentum)
    4. FVG dans la zone de displacement
    5. Order Block identifié
    6. Prix revient dans le FVG/OB
    7. RSI pas en extrême opposé
    """
    close = data['close'].values
    high = data['high'].values
    low = data['low'].values
    open_p = data['open'].values
    n = len(data)
    
    # Indicateurs
    sma50 = pd.Series(close).rolling(50).mean().values
    sma200 = pd.Series(close).rolling(200).mean().values
    
    delta = np.diff(close, prepend=close[0])
    g = pd.Series(np.where(delta > 0, delta, 0)).rolling(14).mean().values
    lo = pd.Series(np.where(delta < 0, -delta, 0)).rolling(14).mean().values
    lo = np.where(lo == 0, 1e-10, lo)
    rsi = 100 - 100 / (1 + g / lo)
    atr = pd.Series(np.abs(delta)).rolling(14).mean().values
    
    # Pré-détecter les structures
    swing_highs, swing_lows = find_swing_points(data, lookback=15)
    levels, sweeps = detect_liquidity_sweep(data, swing_highs, swing_lows)
    displacements = detect_displacement(data, min_body_pct=0.65)
    fvg_list = detect_fvg_after_displacement(data, displacements)
    
    # Indexer les sweeps par position
    sweep_by_index = {}
    for i, sweep_type, level in sweeps:
        if i not in sweep_by_index:
            sweep_by_index[i] = []
        sweep_by_index[i].append((sweep_type, level))
    
    # Indexer les FVG par position du displacement
    fvg_by_disp_index = {}
    for disp, fvg_h, fvg_l, fvg_m in fvg_list:
        fvg_by_disp_index[disp.index] = (fvg_h, fvg_l, fvg_m, disp)
    
    # Indexer les displacements
    disp_by_index = {d.index: d for d in displacements}
    
    # Backtest
    trades = []
    capital = initial_capital
    in_trade = False
    
    for i in range(250, n):
        if in_trade:
            # Vérifier sortie
            ep = None
            if trade_dir == 1:
                if low[i] <= trade_sl:
                    ep = trade_sl
                elif high[i] >= trade_tp:
                    ep = trade_tp
            else:
                if high[i] >= trade_sl:
                    ep = trade_sl
                elif low[i] <= trade_tp:
                    ep = trade_tp
            
            if ep:
                pnl_pct = (ep - trade_entry) / trade_entry * trade_dir
                risk_amount = capital * risk_per_trade
                pnl = risk_amount * (pnl_pct * trade_entry / abs(trade_entry - trade_sl))
                pnl -= risk_amount * (spread + commission) * 2
                pnl = np.clip(pnl, -capital * 0.05, capital * 0.05)
                capital = max(0.01, capital + pnl)
                
                trades.append({
                    'pnl': pnl,
                    'w': pnl > 0,
                    'dur': i - trade_entry_idx,
                    'cap': capital,
                    'conf': trade_conf,
                })
                in_trade = False
            continue
        
        # === CHERCHER UN SETUP ===
        
        # Vérifier si un sweep récent (dans les 20 dernières bougies)
        recent_sweep = None
        for j in range(max(0, i - 20), i + 1):
            if j in sweep_by_index:
                for sweep_type, level in sweep_by_index[j]:
                    recent_sweep = (j, sweep_type, level)
                    break
            if recent_sweep:
                break
        
        if not recent_sweep:
            continue
        
        sweep_idx, sweep_type, sweep_level = recent_sweep
        
        # Vérifier si un displacement suit le sweep
        recent_disp = None
        for j in range(sweep_idx, min(sweep_idx + 10, i + 1)):
            if j in disp_by_index:
                recent_disp = (j, disp_by_index[j])
                break
        
        if not recent_disp:
            continue
        
        disp_idx, displacement = recent_disp
        
        # Vérifier si un FVG accompagne le displacement
        fvg_data = fvg_by_disp_index.get(disp_idx)
        if not fvg_data:
            continue
        
        fvg_high, fvg_low, fvg_mid, fvg_disp = fvg_data
        
        # Vérifier si le prix est dans la zone FVG/OB maintenant
        ob = find_order_block(data, displacement)
        
        in_fvg_zone = False
        in_ob_zone = False
        
        if displacement.direction == 'bullish':
            in_fvg_zone = fvg_low <= close[i] <= fvg_high * 1.002
            if ob:
                in_ob_zone = ob[1] <= close[i] <= ob[0] * 1.002
        else:
            in_fvg_zone = fvg_low * 0.998 <= close[i] <= fvg_high
            if ob:
                in_ob_zone = ob[1] * 0.998 <= close[i] <= ob[0]
        
        if not (in_fvg_zone or in_ob_zone):
            continue
        
        # === CALCULER LE SCORE DE CONFLUENCE ===
        conf = 0
        
        # 1. HTF Trend
        if displacement.direction == 'bullish' and sma50[i] > sma200[i]:
            conf += 1
        elif displacement.direction == 'bearish' and sma50[i] < sma200[i]:
            conf += 1
        
        # 2. Liquidity Sweep
        conf += 1  # Déjà filtré
        
        # 3. Displacement fort
        if displacement.strength > 1.5:
            conf += 1
        elif displacement.strength > 1.2:
            conf += 0.5
        
        # 4. FVG présent
        conf += 1  # Déjà filtré
        
        # 5. Order Block
        if ob:
            conf += 1
        
        # 6. Prix dans la zone (FVG ou OB)
        if in_fvg_zone and in_ob_zone:
            conf += 1  # Double confluence
        elif in_fvg_zone or in_ob_zone:
            conf += 0.5
        
        # 7. RSI confirmation
        if displacement.direction == 'bullish' and 25 < rsi[i] < 60:
            conf += 1
        elif displacement.direction == 'bearish' and 40 < rsi[i] < 75:
            conf += 1
        
        # 8. Bougie de confirmation
        if displacement.direction == 'bullish' and close[i] > open_p[i]:
            conf += 0.5
        elif displacement.direction == 'bearish' and close[i] < open_p[i]:
            conf += 0.5
        
        conf = int(conf)
        
        if conf < min_confluence:
            continue
        
        # === ENTRER EN POSITION ===
        if displacement.direction == 'bullish':
            trade_entry = close[i] * (1 + spread)
            trade_sl = (fvg_low if in_fvg_zone else ob[1]) - atr[i] * 0.3
            risk = trade_entry - trade_sl
            trade_tp = trade_entry + risk * rr_target
            trade_dir = 1
        else:
            trade_entry = close[i] * (1 - spread)
            trade_sl = (fvg_high if in_fvg_zone else ob[0]) + atr[i] * 0.3
            risk = trade_sl - trade_entry
            trade_tp = trade_entry - risk * rr_target
            trade_dir = -1
        
        trade_entry_idx = i
        trade_conf = conf
        in_trade = True
    
    # Stats
    if not trades:
        return {'trades': 0, 'wr': 0, 'total_pnl': 0}
    
    df = pd.DataFrame(trades)
    wins = df[df['w']]
    losses = df[~df['w']]
    
    return {
        'trades': len(df),
        'winners': len(wins),
        'losers': len(losses),
        'wr': len(wins) / len(df),
        'total_pnl': df['pnl'].sum(),
        'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
        'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0,
        'pf': abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 0,
        'rr_actual': abs(wins['pnl'].mean() / losses['pnl'].mean()) if len(losses) > 0 and losses['pnl'].mean() != 0 else 0,
        'final_capital': df['cap'].iloc[-1],
        'avg_duration': df['dur'].mean(),
        'avg_conf': df['conf'].mean(),
        'trades_list': trades,
    }
