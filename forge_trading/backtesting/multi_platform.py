"""
Moteur de backtesting multi-plateforme.
Simule les conditions réelles de chaque plateforme.
"""

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import logging
import sys

# Add parent directories to path
# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))
# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent))

from engine import BacktestEngine, BacktestResult
from forge_trading.strategies.base_strategy import BaseStrategy, Signal, Trade, TradeDirection, TradeStatus
from forge_trading.config.platforms import PlatformConfig, get_platform, get_all_platforms, PAIRS_BY_PLATFORM

logger = logging.getLogger(__name__)


@dataclass
class PlatformBacktestResult:
    """Résultat d'un backtest sur une plateforme spécifique."""
    platform_name: str
    platform_config: PlatformConfig
    result: BacktestResult
    total_fees_paid: float
    total_slippage_cost: float
    avg_execution_time_ms: float
    rejected_trades: int  # Trades rejetés (slippage trop élevé)
    
    @property
    def effective_win_rate(self) -> float:
        return self.result.win_rate
    
    @property
    def net_after_fees(self) -> float:
        return self.result.total_pnl - self.total_fees_paid - self.total_slippage_cost
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'platform': self.platform_name,
            'type': self.platform_config.platform_type.value,
            'win_rate': f"{self.effective_win_rate:.1%}",
            'total_trades': self.result.total_trades,
            'rejected_trades': self.rejected_trades,
            'gross_pnl': f"${self.result.total_pnl:.2f}",
            'total_fees': f"${self.total_fees_paid:.2f}",
            'total_slippage': f"${self.total_slippage_cost:.2f}",
            'net_pnl': f"${self.net_after_fees:.2f}",
            'commission': f"{self.platform_config.commission_percent:.4%}",
            'spread': f"{self.platform_config.spread_pips} pips",
            'avg_execution': f"{self.avg_execution_time_ms:.0f}ms",
            'profit_factor': f"{self.result.profit_factor:.2f}",
            'max_drawdown': f"{self.result.max_drawdown:.1%}",
        }


class MultiPlatformBacktester:
    """
    Backtesteur multi-plateforme.
    Teste la même stratégie sur plusieurs plateformes avec leurs conditions réelles.
    """
    
    def __init__(self, strategy: BaseStrategy, initial_capital: float = 50.0):
        self.strategy = strategy
        self.initial_capital = initial_capital
    
    def backtest_platform(
        self,
        platform_name: str,
        data: pd.DataFrame,
        pair: str,
        verbose: bool = False
    ) -> PlatformBacktestResult:
        """
        Backtest sur une plateforme spécifique.
        """
        platform = get_platform(platform_name)
        
        logger.info(f"Backtest sur {platform.name} ({platform.platform_type.value})")
        
        # Créer le moteur avec les paramètres de la plateforme
        engine = BacktestEngine(
            strategy=self.strategy,
            initial_capital=self.initial_capital,
            commission_percent=platform.commission_percent,
            slippage_percent=platform.slippage_percent,
        )
        
        # Variables de tracking
        total_fees = 0.0
        total_slippage_cost = 0.0
        rejected_trades = 0
        execution_times = []
        
        # Exécuter le backtest
        result = engine.run(
            data=data,
            pair=pair,
            market="forex" if platform.platform_type.value.startswith("forex") else "crypto",
            verbose=verbose
        )
        
        # Calculer les coûts réels
        for trade in result.trades:
            # Frais totaux
            total_fees += trade.fees
            
            # Coût du slippage
            if trade.direction == TradeDirection.BUY:
                ideal_entry = trade.entry_price / (1 + platform.slippage_percent)
                slippage_cost = (trade.entry_price - ideal_entry) * trade.quantity
            else:
                ideal_entry = trade.entry_price / (1 - platform.slippage_percent)
                slippage_cost = (ideal_entry - trade.entry_price) * trade.quantity
            
            total_slippage_cost += abs(slippage_cost)
            
            # Simuler le slippage variable
            if platform.spread_variable:
                # Ajouter du bruit au spread
                noise = np.random.normal(0, platform.spread_pips * 0.3)
                extra_spread_cost = abs(noise) * 0.0001 * trade.quantity
                total_slippage_cost += extra_spread_cost
            
            # Simuler la latence
            execution_times.append(platform.latency_ms + np.random.normal(0, platform.latency_ms * 0.2))
            
            # Vérifier si le trade aurait été rejeté
            actual_slippage = abs(trade.entry_price * platform.slippage_percent)
            if actual_slippage > platform.max_slippage_before_reject * trade.entry_price:
                rejected_trades += 1
        
        # Simuler les frais overnight (swap)
        for trade in result.trades:
            if trade.duration_seconds > 86400:  # > 24h
                days = trade.duration_seconds / 86400
                overnight_cost = trade.entry_price * trade.quantity * platform.overnight_fee * days
                total_fees += overnight_cost
        
        # Frais de gaz pour les DEX
        if platform.gas_fee_usd > 0:
            total_fees += platform.gas_fee_usd * len(result.trades)
        
        return PlatformBacktestResult(
            platform_name=platform.name,
            platform_config=platform,
            result=result,
            total_fees_paid=total_fees,
            total_slippage_cost=total_slippage_cost,
            avg_execution_time_ms=np.mean(execution_times) if execution_times else 0,
            rejected_trades=rejected_trades,
        )
    
    def backtest_all_platforms(
        self,
        data: pd.DataFrame,
        pair: str,
        platform_type: Optional[str] = None,  # "forex", "crypto", ou None (tous)
        verbose: bool = False
    ) -> List[PlatformBacktestResult]:
        """
        Backtest sur toutes les plateformes compatibles.
        """
        results = []
        
        # Filtrer les plateformes compatibles
        if platform_type == "forex":
            platforms = {k: v for k, v in get_all_platforms().items() 
                        if v.platform_type.value.startswith("forex")}
        elif platform_type == "crypto":
            platforms = {k: v for k, v in get_all_platforms().items() 
                        if not v.platform_type.value.startswith("forex")}
        else:
            platforms = get_all_platforms()
        
        for platform_name, platform_config in platforms.items():
            # Vérifier si la paire est disponible
            available_pairs = PAIRS_BY_PLATFORM.get(platform_name, [])
            if pair not in available_pairs and pair.replace("/", "") not in [p.replace("/", "") for p in available_pairs]:
                logger.debug(f"Skipping {platform_name}: {pair} not available")
                continue
            
            try:
                result = self.backtest_platform(platform_name, data, pair, verbose)
                results.append(result)
                logger.info(f"  {platform_config.name}: WR={result.effective_win_rate:.1%} Net=${result.net_after_fees:.2f}")
            except Exception as e:
                logger.warning(f"  Error on {platform_name}: {e}")
        
        # Trier par PnL net
        results.sort(key=lambda x: x.net_after_fees, reverse=True)
        
        return results
    
    def compare_platforms(
        self,
        data: pd.DataFrame,
        pair: str,
        verbose: bool = False
    ) -> pd.DataFrame:
        """
        Compare les performances sur toutes les plateformes.
        Retourne un DataFrame comparatif.
        """
        results = self.backtest_all_platforms(data, pair, verbose=verbose)
        
        comparison = []
        for r in results:
            comparison.append({
                'Platform': r.platform_name,
                'Type': r.platform_config.platform_type.value,
                'Win Rate': f"{r.effective_win_rate:.1%}",
                'Trades': r.result.total_trades,
                'Rejected': r.rejected_trades,
                'Gross PnL': f"${r.result.total_pnl:.2f}",
                'Fees': f"${r.total_fees_paid:.2f}",
                'Slippage': f"${r.total_slippage_cost:.2f}",
                'Net PnL': f"${r.net_after_fees:.2f}",
                'Profit Factor': f"{r.result.profit_factor:.2f}",
                'Max DD': f"{r.result.max_drawdown:.1%}",
                'Spread': f"{r.platform_config.spread_pips} pips",
                'Commission': f"{r.platform_config.commission_percent:.4%}",
            })
        
        return pd.DataFrame(comparison)
    
    def find_best_platform(
        self,
        data: pd.DataFrame,
        pair: str,
        min_win_rate: float = 0.51,
        min_profit_factor: float = 1.0,
    ) -> Optional[PlatformBacktestResult]:
        """
        Trouve la meilleure plateforme pour une paire donnée.
        """
        results = self.backtest_all_platforms(data, pair)
        
        for result in results:
            if (result.effective_win_rate >= min_win_rate and 
                result.result.profit_factor >= min_profit_factor and
                result.net_after_fees > 0):
                return result
        
        return None


def run_multi_platform_backtest(
    strategy: BaseStrategy,
    data: pd.DataFrame,
    pair: str,
    initial_capital: float = 50.0,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour exécuter un backtest multi-plateforme.
    """
    backtester = MultiPlatformBacktester(strategy, initial_capital)
    
    # Comparer toutes les plateformes
    comparison_df = backtester.compare_platforms(data, pair, verbose)
    
    # Trouver la meilleure plateforme
    best = backtester.find_best_platform(data, pair)
    
    return {
        'comparison': comparison_df,
        'best_platform': best,
        'summary': {
            'platforms_tested': len(comparison_df),
            'profitable_platforms': len(comparison_df[comparison_df['Net PnL'].str.replace('$', '').astype(float) > 0]),
            'best_win_rate': comparison_df['Win Rate'].max(),
            'best_net_pnl': comparison_df['Net PnL'].max(),
        }
    }
