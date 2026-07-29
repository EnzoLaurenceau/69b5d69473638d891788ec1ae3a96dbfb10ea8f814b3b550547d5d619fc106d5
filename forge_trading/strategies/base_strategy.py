"""
Classe abstraite de base pour toutes les stratégies de trading.
Toute nouvelle stratégie DOIT hériter de cette classe.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum
import uuid


class TradeDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


@dataclass
class Signal:
    """Signal de trading généré par une stratégie."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    pair: str = ""
    direction: TradeDirection = TradeDirection.BUY
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.0  # 0.0 à 1.0
    strategy_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def risk_reward_ratio(self) -> float:
        """Calcule le ratio risque/récompense."""
        if self.entry_price == 0 or self.stop_loss == 0:
            return 0.0
        
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        
        return reward / risk if risk > 0 else 0.0


@dataclass
class Trade:
    """Représente un trade exécuté."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    signal: Optional[Signal] = None
    pair: str = ""
    direction: TradeDirection = TradeDirection.BUY
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    status: TradeStatus = TradeStatus.PENDING
    pnl: float = 0.0
    pnl_percent: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    strategy_name: str = ""
    market: str = "forex"  # "forex" ou "crypto"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_winner(self) -> bool:
        return self.pnl > 0
    
    @property
    def duration_seconds(self) -> float:
        if self.exit_time is None:
            return 0.0
        return (self.exit_time - self.entry_time).total_seconds()
    
    @property
    def net_pnl(self) -> float:
        return self.pnl - self.fees


@dataclass
class BacktestResult:
    """Résultat d'un backtest."""
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    trades: List[Trade] = field(default_factory=list)
    
    @property
    def total_trades(self) -> int:
        return len(self.trades)
    
    @property
    def winning_trades(self) -> int:
        return len([t for t in self.trades if t.is_winner])
    
    @property
    def losing_trades(self) -> int:
        return len([t for t in self.trades if not t.is_winner])
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    @property
    def total_pnl(self) -> float:
        return sum(t.net_pnl for t in self.trades)
    
    @property
    def total_return_percent(self) -> float:
        return (self.final_capital - self.initial_capital) / self.initial_capital * 100
    
    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    @property
    def max_drawdown(self) -> float:
        """Calcule le drawdown maximum."""
        if not self.trades:
            return 0.0
        
        equity_curve = [self.initial_capital]
        for trade in sorted(self.trades, key=lambda t: t.exit_time or t.entry_time):
            equity_curve.append(equity_curve[-1] + trade.net_pnl)
        
        peak = equity_curve[0]
        max_dd = 0.0
        
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
    
    @property
    def sharpe_ratio(self) -> float:
        """Calcule le ratio de Sharpe (simplifié)."""
        if not self.trades:
            return 0.0
        
        returns = [t.pnl_percent for t in self.trades]
        avg_return = sum(returns) / len(returns)
        
        if len(returns) < 2:
            return 0.0
        
        variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = variance ** 0.5
        
        return avg_return / std_dev if std_dev > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy_name,
            "period": f"{self.start_date.date()} to {self.end_date.date()}",
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": f"{self.win_rate:.1%}",
            "total_pnl": round(self.total_pnl, 2),
            "total_return": f"{self.total_return_percent:.1f}%",
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": f"{self.max_drawdown:.1%}",
            "sharpe_ratio": round(self.sharpe_ratio, 2)
        }


class BaseStrategy(ABC):
    """
    Classe abstraite pour toutes les stratégies de trading.
    
    Chaque stratégie DOIT implémenter:
    - name: Nom de la stratégie
    - generate_signal(): Génère un signal de trading
    - should_exit(): Détermine si on doit sortir d'une position
    
    Optionnel:
    - on_trade_closed(): Hook appelé après chaque trade (pour apprentissage)
    - optimize(): Optimise les paramètres basé sur l'historique
    """
    
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}
        self.trades_history: List[Trade] = []
        self.is_active: bool = True
        self._win_rate_ema: float = 0.5  # EMA du win rate pour suivi adaptatif
        self._ema_alpha: float = 0.1     # Facteur de lissage
    
    @abstractmethod
    def generate_signal(self, market_data: Dict[str, Any]) -> Optional[Signal]:
        """
        Génère un signal de trading basé sur les données de marché.
        
        Args:
            market_data: Dict contenant les données OHLCV, orderbook, etc.
            
        Returns:
            Signal si opportunité détectée, None sinon
        """
        pass
    
    @abstractmethod
    def should_exit(self, trade: Trade, current_price: float, market_data: Dict[str, Any]) -> bool:
        """
        Détermine si on doit sortir d'une position.
        
        Args:
            trade: Le trade en cours
            current_price: Prix actuel
            market_data: Données de marché actuelles
            
        Returns:
            True si on doit sortir
        """
        pass
    
    def on_trade_closed(self, trade: Trade):
        """
        Hook appelé après chaque trade fermé.
        Utilisé pour l'apprentissage et l'adaptation.
        """
        self.trades_history.append(trade)
        
        # Mettre à jour le win rate EMA
        if trade.is_winner:
            self._win_rate_ema = self._ema_alpha * 1.0 + (1 - self._ema_alpha) * self._win_rate_ema
        else:
            self._win_rate_ema = self._ema_alpha * 0.0 + (1 - self._ema_alpha) * self._win_rate_ema
    
    def optimize(self, trades: List[Trade]) -> Dict[str, Any]:
        """
        Optimise les paramètres de la stratégie basé sur l'historique.
        
        Args:
            trades: Liste des trades passés
            
        Returns:
            Nouveaux paramètres optimisés
        """
        # Implémentation par défaut: ajuster le stop/take profit
        if not trades:
            return self.params
        
        winners = [t for t in trades if t.is_winner]
        losers = [t for t in trades if not t.is_winner]
        
        if winners and losers:
            avg_win = sum(t.pnl_percent for t in winners) / len(winners)
            avg_loss = abs(sum(t.pnl_percent for t in losers) / len(losers))
            
            # Ajuster le ratio risk/reward
            if avg_loss > 0:
                self.params['risk_reward_target'] = avg_win / avg_loss
        
        return self.params
    
    @property
    def current_win_rate(self) -> float:
        """Retourne le win rate actuel (EMA)."""
        return self._win_rate_ema
    
    @property
    def is_improving(self) -> bool:
        """Vérifie si le win rate s'améliore."""
        if len(self.trades_history) < 20:
            return True  # Pas assez de données
        
        recent = self.trades_history[-20:]
        older = self.trades_history[-40:-20] if len(self.trades_history) >= 40 else []
        
        if not older:
            return True
        
        recent_wr = len([t for t in recent if t.is_winner]) / len(recent)
        older_wr = len([t for t in older if t.is_winner]) / len(older)
        
        return recent_wr >= older_wr
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de la stratégie."""
        if not self.trades_history:
            return {"name": self.name, "trades": 0, "win_rate": 0.0}
        
        return {
            "name": self.name,
            "trades": len(self.trades_history),
            "win_rate": f"{self.current_win_rate:.1%}",
            "is_improving": self.is_improving,
            "params": self.params
        }
