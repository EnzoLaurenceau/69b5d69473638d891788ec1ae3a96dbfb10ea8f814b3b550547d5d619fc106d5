#!/usr/bin/env python3
"""
Connexion WebSocket aux flux Crypto en temps réel.
Supporte Uniswap V3, Base, Arbitrum, et DEX aggregators.
"""

import asyncio
import websockets
import json
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Tuple
from dataclasses import dataclass, field
from web3 import Web3
import logging

logger = logging.getLogger(__name__)


@dataclass
class CryptoTick:
    """Tick de données Crypto."""
    pair: str
    chain: str
    price: float
    price_usd: float
    volume_24h: float
    timestamp: datetime
    reserve0: float = 0.0
    reserve1: float = 0.0
    liquidity: float = 0.0
    
    @property
    def pool_address(self) -> str:
        return self.pair.split('_')[0] if '_' in self.pair else ''


@dataclass
class PoolState:
    """État d'un pool DeFi."""
    address: str
    chain: str
    token0: str
    token1: str
    reserve0: int
    reserve1: int
    fee: int  # En basis points (500 = 0.05%)
    price: float
    liquidity: float
    last_update: datetime


class CryptoWebSocket:
    """
    Client WebSocket pour les flux Crypto DeFi.
    
    Supporte:
    - Uniswap V3 (Base, Arbitrum, Ethereum)
    - DEX aggregators (1inch, Paraswap)
    - Price feeds (Chainlink, Pyth)
    
    Usage:
        async with CryptoWebSocket(chain="base") as ws:
            async for tick in ws.stream_pools(pool_addresses):
                print(f"{tick.pair}: ${tick.price_usd:.2f}")
    """
    
    CHAIN_CONFIG = {
        'base': {
            'rpc': 'https://mainnet.base.org',
            'ws_rpc': 'wss://base-mainnet.g.alchemy.com/v2/{api_key}',
            'uniswap_v3_factory': '0x33128a8fC17869897dcE68Ed026d694621f6FDfD',
            'chain_id': 8453,
        },
        'arbitrum': {
            'rpc': 'https://arb1.arbitrum.io/rpc',
            'ws_rpc': 'wss://arb-mainnet.g.alchemy.com/v2/{api_key}',
            'uniswap_v3_factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
            'chain_id': 42161,
        },
        'ethereum': {
            'rpc': 'https://eth.llamarpc.com',
            'ws_rpc': 'wss://eth-mainnet.g.alchemy.com/v2/{api_key}',
            'uniswap_v3_factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
            'chain_id': 1,
        }
    }
    
    # ABI minimal pour Uniswap V3 Pool
    POOL_ABI = json.loads('''[
        {
            "inputs": [],
            "name": "slot0",
            "outputs": [
                {"name": "sqrtPriceX96", "type": "uint160"},
                {"name": "tick", "type": "int24"},
                {"name": "observationIndex", "type": "uint16"},
                {"name": "observationCardinality", "type": "uint16"},
                {"name": "observationCardinalityNext", "type": "uint16"},
                {"name": "feeProtocol", "type": "uint8"},
                {"name": "unlocked", "type": "bool"}
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "liquidity",
            "outputs": [{"name": "", "type": "uint128"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "token0",
            "outputs": [{"name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "token1",
            "outputs": [{"name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "fee",
            "outputs": [{"name": "", "type": "uint24"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]''')
    
    def __init__(
        self,
        chain: str = 'base',
        alchemy_api_key: Optional[str] = None,
        on_tick: Optional[Callable] = None,
    ):
        self.chain = chain
        self.alchemy_api_key = alchemy_api_key
        self.on_tick = on_tick
        
        self._config = self.CHAIN_CONFIG.get(chain)
        if not self._config:
            raise ValueError(f"Chaîne inconnue: {chain}. Disponibles: {list(self.CHAIN_CONFIG.keys())}")
        
        # Web3 connection
        rpc_url = self._config['rpc']
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        # WebSocket pour les événements
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._pools: Dict[str, PoolState] = {}
        self._callbacks: List[Callable] = []
    
    async def connect(self):
        """Établit la connexion WebSocket."""
        if not self.alchemy_api_key:
            logger.warning("Pas de clé Alchemy - utilisation du polling")
            return
        
        ws_url = self._config['ws_rpc'].format(api_key=self.alchemy_api_key)
        
        logger.info(f"Connexion WebSocket à {self.chain}...")
        try:
            self._ws = await websockets.connect(ws_url)
            self._running = True
            logger.info(f"Connecté à {self.chain}")
        except Exception as e:
            logger.error(f"Erreur connexion WebSocket: {e}")
            logger.info("Fallback en mode polling")
    
    async def disconnect(self):
        """Ferme la connexion."""
        self._running = False
        if self._ws:
            await self._ws.close()
    
    def get_pool_state(self, pool_address: str) -> Optional[PoolState]:
        """
        Récupère l'état actuel d'un pool via Multicall.
        """
        try:
            pool_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=self.POOL_ABI
            )
            
            # Appels batch pour optimiser
            slot0 = pool_contract.functions.slot0().call()
            liquidity = pool_contract.functions.liquidity().call()
            token0 = pool_contract.functions.token0().call()
            token1 = pool_contract.functions.token1().call()
            fee = pool_contract.functions.fee().call()
            
            # Calculer le prix depuis sqrtPriceX96
            sqrt_price_x96 = slot0[0]
            price = (sqrt_price_x96 / (2**96)) ** 2
            
            state = PoolState(
                address=pool_address,
                chain=self.chain,
                token0=token0,
                token1=token1,
                reserve0=0,  # Pas directement disponible dans V3
                reserve1=0,
                fee=fee,
                price=price,
                liquidity=liquidity,
                last_update=datetime.now()
            )
            
            self._pools[pool_address] = state
            return state
            
        except Exception as e:
            logger.error(f"Erreur lecture pool {pool_address}: {e}")
            return None
    
    async def stream_pools(self, pool_addresses: List[str], interval_ms: int = 100):
        """
        Générateur asynchrone qui yield les états des pools.
        
        Args:
            pool_addresses: Liste des adresses de pools
            interval_ms: Intervalle de polling en ms
        """
        self._running = True
        
        while self._running:
            for pool_addr in pool_addresses:
                state = self.get_pool_state(pool_addr)
                
                if state:
                    # Convertir en CryptoTick
                    tick = CryptoTick(
                        pair=f"{state.token0}_{state.token1}",
                        chain=self.chain,
                        price=state.price,
                        price_usd=state.price,  # À ajuster avec le prix USD
                        volume_24h=0,  # À récupérer via API
                        timestamp=state.last_update,
                        reserve0=state.reserve0,
                        reserve1=state.reserve1,
                        liquidity=state.liquidity
                    )
                    
                    # Callbacks
                    if self.on_tick:
                        self.on_tick(tick)
                    
                    for callback in self._callbacks:
                        await callback(tick)
                    
                    yield tick
            
            await asyncio.sleep(interval_ms / 1000)
    
    async def watch_pending_transactions(self, callback: Callable):
        """
        Écoute les transactions en attente (mempool).
        Utile pour détecter les gros swaps avant exécution.
        """
        if not self._ws:
            logger.warning("WebSocket non connecté")
            return
        
        # S'abonner aux transactions en attente
        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newPendingTransactions"]
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info("Écoute du mempool activée")
        
        while self._running:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=30)
                data = json.loads(msg)
                
                if 'params' in data:
                    tx_hash = data['params']['result']
                    
                    # Récupérer les détails de la tx
                    try:
                        tx = self.w3.eth.get_transaction(tx_hash)
                        
                        # Vérifier si c'est un swap DEX
                        if self._is_dex_swap(tx):
                            await callback(tx)
                    except:
                        pass  # Tx peut ne plus être disponible
                        
            except asyncio.TimeoutError:
                await self._ws.ping()
            except Exception as e:
                logger.debug(f"Erreur mempool: {e}")
    
    def _is_dex_swap(self, tx: dict) -> bool:
        """Vérifie si une transaction est un swap DEX."""
        # Vérifier le "to" address pour les routers connus
        known_routers = {
            '0x2626664c2603336E57B271c5C0b26F421741e481',  # Uniswap V3 Router (Base)
            '0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45',  # Uniswap Universal Router
            '0xE592427A0AEce92De3Edee1F18E0157C05861564',  # Uniswap V3 Router (Ethereum)
        }
        
        to_address = tx.get('to', '')
        return to_address in known_routers if to_address else False
    
    def add_callback(self, callback: Callable):
        """Ajoute un callback pour chaque tick."""
        self._callbacks.append(callback)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


# Exemple d'utilisation
async def example_base_pools():
    """Exemple: surveiller les pools sur Base."""
    
    # Pools populaires sur Base
    pools = [
        '0x4C36388bE6F416A29C9d6Ee709b18e82DE10b7Bf',  # WETH/USDC 0.05%
        '0x6c561B4473e7381B87dffb0B275558b7A5919789',  # WETH/USDbC 0.3%
    ]
    
    async def on_tick(tick: CryptoTick):
        print(f"[{tick.timestamp}] {tick.pair}: ${tick.price_usd:.4f} (Liquidity: {tick.liquidity:,.0f})")
    
    async with CryptoWebSocket(chain='base', on_tick=on_tick) as ws:
        async for tick in ws.stream_pools(pools, interval_ms=500):
            # Logique d'arbitrage ici
            if tick.liquidity > 1000000:  # Liquidity > $1M
                logger.info(f"Pool liquide: {tick.pair}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_base_pools())
