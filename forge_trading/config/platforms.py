"""
Configuration multi-plateforme avec données réelles.
Chaque plateforme a ses propres spreads, frais, slippage et latence.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class PlatformType(Enum):
    FOREX_ECN = "forex_ecn"
    FOREX_STANDARD = "forex_standard"
    DEX_V2 = "dex_v2"
    DEX_V3 = "dex_v3"
    CEX = "cex"


@dataclass
class PlatformConfig:
    """Configuration d'une plateforme de trading."""
    name: str
    platform_type: PlatformType
    
    # Frais
    commission_percent: float  # Commission par trade
    spread_pips: float         # Spread typique en pips (Forex) ou basis points (Crypto)
    spread_variable: bool      # Spread fixe ou variable
    
    # Slippage
    slippage_percent: float    # Slippage moyen
    slippage_max: float        # Slippage maximum
    
    # Exécution
    latency_ms: int            # Latence moyenne en ms
    fill_rate: float           # Taux de remplissage (0-1)
    
    # Capital
    min_lot_size: float        # Taille minimum de position
    max_leverage: int          # Levier maximum
    
    # Frais spécifiques
    overnight_fee: float = 0  # Frais overnight (swap)
    gas_fee_usd: float = 0   # Frais de gaz (crypto)
    withdrawal_fee: float = 0 # Frais de retrait
    
    # Limites
    max_slippage_before_reject: float = 0.01  # Rejeter si slippage > 1%
    min_profit_after_all_fees: float = 0.001  # Profit minimum après TOUS les frais


# ============================================================
# PLATEFORMES FOREX RÉELLES
# ============================================================

FOREX_PLATFORMS = {
    "ic_markets_ecn": PlatformConfig(
        name="IC Markets ECN",
        platform_type=PlatformType.FOREX_ECN,
        commission_percent=0.0007,  # $7 par lot standard (0.0007%)
        spread_pips=0.1,            # 0.1 pip EURUSD en moyenne ECN
        spread_variable=True,
        slippage_percent=0.0001,    # 0.01%
        slippage_max=0.0005,        # 0.05% max
        latency_ms=50,              # 50ms
        fill_rate=0.98,             # 98% de remplissage
        min_lot_size=0.01,          # Micro lot
        max_leverage=500,
        overnight_fee=0.0001,       # Swap quotidien
    ),
    
    "pepperstone_ecn": PlatformConfig(
        name="Pepperstone ECN",
        platform_type=PlatformType.FOREX_ECN,
        commission_percent=0.0007,
        spread_pips=0.15,
        spread_variable=True,
        slippage_percent=0.00015,
        slippage_max=0.0006,
        latency_ms=60,
        fill_rate=0.97,
        min_lot_size=0.01,
        max_leverage=500,
        overnight_fee=0.00012,
    ),
    
    "oanda": PlatformConfig(
        name="OANDA",
        platform_type=PlatformType.FOREX_STANDARD,
        commission_percent=0,       # Pas de commission (spread inclus)
        spread_pips=1.2,            # 1.2 pip EURUSD (standard)
        spread_variable=True,
        slippage_percent=0.0002,
        slippage_max=0.001,
        latency_ms=80,
        fill_rate=0.95,
        min_lot_size=1,             # 1 unité (pas de lot minimum!)
        max_leverage=50,
        overnight_fee=0.00015,
    ),
    
    "fxcm": PlatformConfig(
        name="FXCM",
        platform_type=PlatformType.FOREX_STANDARD,
        commission_percent=0,
        spread_pips=1.4,
        spread_variable=True,
        slippage_percent=0.00025,
        slippage_max=0.0012,
        latency_ms=100,
        fill_rate=0.93,
        min_lot_size=1,
        max_leverage=400,
        overnight_fee=0.0002,
    ),
    
    "xm_standard": PlatformConfig(
        name="XM Standard",
        platform_type=PlatformType.FOREX_STANDARD,
        commission_percent=0,
        spread_pips=1.7,
        spread_variable=True,
        slippage_percent=0.0003,
        slippage_max=0.0015,
        latency_ms=120,
        fill_rate=0.90,
        min_lot_size=0.01,
        max_leverage=1000,  # Levier élevé!
        overnight_fee=0.0003,
    ),
}


# ============================================================
# PLATEFORMES CRYPTO RÉELLES
# ============================================================

CRYPTO_PLATFORMS = {
    # DEX - Uniswap V3
    "uniswap_v3_base": PlatformConfig(
        name="Uniswap V3 (Base)",
        platform_type=PlatformType.DEX_V3,
        commission_percent=0.0005,  # 0.05% fee tier (Uniswap V3)
        spread_pips=0,              # Pas de spread classique
        spread_variable=False,
        slippage_percent=0.001,     # 0.1% slippage moyen
        slippage_max=0.005,         # 0.5% max
        latency_ms=2000,            # 2s (temps de bloc)
        fill_rate=0.99,             # Toujours rempli si gaz OK
        min_lot_size=0.001,
        max_leverage=1,             # Pas de levier sur DEX
        gas_fee_usd=0.01,           # Base L2 = ~$0.01
        withdrawal_fee=0,
    ),
    
    "uniswap_v3_arbitrum": PlatformConfig(
        name="Uniswap V3 (Arbitrum)",
        platform_type=PlatformType.DEX_V3,
        commission_percent=0.0005,
        spread_pips=0,
        spread_variable=False,
        slippage_percent=0.0008,
        slippage_max=0.004,
        latency_ms=1000,            # 1s (plus rapide que Base)
        fill_rate=0.99,
        min_lot_size=0.001,
        max_leverage=1,
        gas_fee_usd=0.05,           # Arbitrum ~$0.05
    ),
    
    "uniswap_v3_ethereum": PlatformConfig(
        name="Uniswap V3 (Ethereum)",
        platform_type=PlatformType.DEX_V3,
        commission_percent=0.0005,
        spread_pips=0,
        spread_variable=False,
        slippage_percent=0.001,
        slippage_max=0.008,
        latency_ms=12000,           # 12s (1 bloc ETH)
        fill_rate=0.99,
        min_lot_size=0.01,
        max_leverage=1,
        gas_fee_usd=5.0,            # ETH mainnet ~$5-20
    ),
    
    # DEX - Aerodrome (Base native)
    "aerodrome_base": PlatformConfig(
        name="Aerodrome (Base)",
        platform_type=PlatformType.DEX_V2,
        commission_percent=0.003,   # 0.3% fee (V2 style)
        spread_pips=0,
        spread_variable=False,
        slippage_percent=0.002,
        slippage_max=0.01,
        latency_ms=2000,
        fill_rate=0.98,
        min_lot_size=0.001,
        max_leverage=1,
        gas_fee_usd=0.01,
    ),
    
    # CEX - Binance
    "binance": PlatformConfig(
        name="Binance",
        platform_type=PlatformType.CEX,
        commission_percent=0.001,    # 0.1% maker/taker
        spread_pips=0.1,            # Très serré sur BTC
        spread_variable=True,
        slippage_percent=0.0005,
        slippage_max=0.002,
        latency_ms=50,              # API rapide
        fill_rate=0.99,
        min_lot_size=10,            # $10 minimum
        max_leverage=125,
        withdrawal_fee=0.0005,      # 0.0005 BTC par retrait
    ),
    
    # CEX - Bybit
    "bybit": PlatformConfig(
        name="Bybit",
        platform_type=PlatformType.CEX,
        commission_percent=0.001,
        spread_pips=0.15,
        spread_variable=True,
        slippage_percent=0.0006,
        slippage_max=0.003,
        latency_ms=60,
        fill_rate=0.98,
        min_lot_size=10,
        max_leverage=100,
        withdrawal_fee=0.0006,
    ),
    
    # DEX - Gains Network (Forex on-chain)
    "gtrade_base": PlatformConfig(
        name="gTrade (Base)",
        platform_type=PlatformType.DEX_V3,
        commission_percent=0.0008,  # 0.08% opening fee
        spread_pips=0.5,            # Spread simulé
        spread_variable=True,
        slippage_percent=0.002,
        slippage_max=0.01,
        latency_ms=2000,
        fill_rate=0.97,
        min_lot_size=1,
        max_leverage=150,           # Levier gTrade
        gas_fee_usd=0.02,
        overnight_fee=0.0005,       # Funding rate
    ),
}


# ============================================================
# PAIRES DISPONIBLES PAR PLATEFORME
# ============================================================

PAIRS_BY_PLATFORM = {
    # Forex
    "ic_markets_ecn": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"],
    "pepperstone_ecn": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
    "oanda": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF", "EURGBP"],
    "fxcm": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"],
    "xm_standard": ["EURUSD", "GBPUSD", "USDJPY"],
    
    # Crypto
    "uniswap_v3_base": ["WETH/USDC", "WETH/USDbC", "WBTC/USDC"],
    "uniswap_v3_arbitrum": ["WETH/USDC", "WETH/USDT", "WBTC/USDC"],
    "uniswap_v3_ethereum": ["WETH/USDC", "WETH/USDT", "WBTC/USDC", "UNI/USDC"],
    "aerodrome_base": ["WETH/USDC", "AERO/USDC"],
    "binance": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT"],
    "bybit": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "gtrade_base": ["EURUSD", "GBPUSD", "USDJPX", "BTC/USD", "ETH/USD"],
}


def get_all_platforms() -> Dict[str, PlatformConfig]:
    """Retourne toutes les plateformes."""
    all_platforms = {}
    all_platforms.update(FOREX_PLATFORMS)
    all_platforms.update(CRYPTO_PLATFORMS)
    return all_platforms


def get_platform(name: str) -> PlatformConfig:
    """Récupère la config d'une plateforme."""
    all_platforms = get_all_platforms()
    if name not in all_platforms:
        raise ValueError(f"Plateforme inconnue: {name}. Disponibles: {list(all_platforms.keys())}")
    return all_platforms[name]


def get_forex_platforms() -> Dict[str, PlatformConfig]:
    """Retourne uniquement les plateformes Forex."""
    return FOREX_PLATFORMS.copy()


def get_crypto_platforms() -> Dict[str, PlatformConfig]:
    """Retourne uniquement les plateformes Crypto."""
    return CRYPTO_PLATFORMS.copy()
