"""
Configuration du système de trading Forge.
Tous les paramètres centralisés ici.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import yaml

# Chemins
TRADING_ROOT = Path(__file__).parent.parent
FORGE_ROOT = TRADING_ROOT.parent

@dataclass
class TradingConfig:
    """Configuration principale du système de trading."""
    
    # Capital et risque
    initial_capital: float = 50.0
    max_risk_per_trade: float = 0.02  # 2% du capital par trade
    max_daily_loss: float = 0.10      # 10% max perte quotidienne
    max_drawdown: float = 0.20        # 20% max drawdown total
    
    # Objectifs de performance
    min_win_rate: float = 0.51        # 51% minimum (seuil rentabilité)
    target_win_rate: float = 0.70     # 70% objectif initial
    min_profit_factor: float = 1.5    # Ratio gains/pertes minimum
    
    # Paramètres de stratégie
    default_strategy: str = "micro_arb"
    max_concurrent_trades: int = 3
    trade_cooldown_seconds: int = 60
    
    # Backtesting
    backtest_years: int = 10
    backtest_data_source: str = "yfinance"  # ou "csv", "api"
    backtest_initial_capital: float = 50.0
    
    # Forex
    forex_pairs: list = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"
    ])
    forex_leverage: int = 500
    forex_max_spread_pips: float = 2.0
    
    # Crypto
    crypto_pairs: list = field(default_factory=lambda: [
        "WETH/USDC", "WBTC/USDC", "WETH/USDbC"
    ])
    crypto_chains: list = field(default_factory=lambda: ["base", "arbitrum"])
    crypto_max_gas_gwei: float = 50.0
    
    # Smart Contracts
    flash_loan_provider: str = "aave_v3"  # ou "dydx"
    min_profit_after_fees_bps: int = 5    # 0.05% minimum
    
    # Réflexion et apprentissage
    reflection_enabled: bool = True
    reflection_after_each_trade: bool = True
    lesson_generation_threshold: int = 10  # Générer leçon après 10 trades similaires
    pattern_detection_enabled: bool = True
    
    # RPC Configuration
    base_rpc: str = "https://mainnet.base.org"
    arbitrum_rpc: str = "https://arb1.arbitrum.io/rpc"
    flashbots_rpc: str = "https://rpc.flashbots.net"
    
    # Logs
    log_level: str = "INFO"
    log_to_file: bool = True
    log_to_console: bool = True
    
    @classmethod
    def from_yaml(cls, path: Optional[str] = None) -> 'TradingConfig':
        """Charger la configuration depuis un fichier YAML."""
        if path is None:
            path = TRADING_ROOT / "config" / "settings.yaml"
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def to_yaml(self, path: Optional[str] = None):
        """Sauvegarder la configuration en YAML."""
        if path is None:
            path = TRADING_ROOT / "config" / "settings.yaml"
        
        import dataclasses
        with open(path, 'w') as f:
            yaml.dump(dataclasses.asdict(self), f, default_flow_style=False)

# Instance globale
config = TradingConfig()
