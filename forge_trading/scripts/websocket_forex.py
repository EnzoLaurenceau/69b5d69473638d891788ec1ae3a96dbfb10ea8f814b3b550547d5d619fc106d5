#!/usr/bin/env python3
"""
Connexion WebSocket aux flux Forex en temps réel.
Supporte OANDA, FXCM, et autres brokers ECN.
"""

import asyncio
import websockets
import json
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ForexTick:
    """Tick de données Forex."""
    pair: str
    bid: float
    ask: float
    spread: float
    timestamp: datetime
    volume: float = 0.0
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class ForexWebSocket:
    """
    Client WebSocket pour les flux Forex.
    
    Supporte:
    - OANDA Streaming API
    - FXCM WebSocket
    - Custom WebSocket feeds
    
    Usage:
        async with ForexWebSocket(provider="oanda") as ws:
            async for tick in ws.stream(["EURUSD", "GBPUSD"]):
                print(f"{tick.pair}: {tick.bid}/{tick.ask}")
    """
    
    PROVIDERS = {
        'oanda': {
            'url': 'wss://stream-fxpractice.oanda.com/v3/accounts/{account}/pricing/stream',
            'auth_header': 'Authorization',
            'auth_prefix': 'Bearer ',
        },
        'fxcm': {
            'url': 'wss://api-demo.fxcm.com:443/candle',
            'auth_header': 'Authorization',
            'auth_prefix': '',
        },
    }
    
    def __init__(
        self,
        provider: str = 'oanda',
        api_key: Optional[str] = None,
        account_id: Optional[str] = None,
        on_tick: Optional[Callable] = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.account_id = account_id
        self.on_tick = on_tick
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._ticks_buffer: List[ForexTick] = []
        self._callbacks: List[Callable] = []
    
    async def connect(self):
        """Établit la connexion WebSocket."""
        provider_config = self.PROVIDERS.get(self.provider)
        if not provider_config:
            raise ValueError(f"Provider inconnu: {self.provider}")
        
        url = provider_config['url'].format(account=self.account_id)
        
        headers = {}
        if self.api_key:
            headers[provider_config['auth_header']] = f"{provider_config['auth_prefix']}{self.api_key}"
        
        logger.info(f"Connexion à {self.provider} WebSocket...")
        
        try:
            self._ws = await websockets.connect(url, extra_headers=headers)
            self._running = True
            logger.info(f"Connecté à {self.provider}")
        except Exception as e:
            logger.error(f"Erreur de connexion: {e}")
            raise
    
    async def disconnect(self):
        """Ferme la connexion WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
            logger.info("Déconnecté")
    
    async def subscribe(self, pairs: List[str]):
        """S'abonne aux flux de données pour les paires spécifiées."""
        if not self._ws:
            raise RuntimeError("Non connecté. Appelez connect() d'abord.")
        
        if self.provider == 'oanda':
            # OANDA: souscription via JSON
            msg = {
                "type": "PRICE",
                "instruments": pairs
            }
            await self._ws.send(json.dumps(msg))
            logger.info(f"Abonné à {pairs}")
        
        elif self.provider == 'fxcm':
            # FXCM: souscription par paire
            for pair in pairs:
                msg = {"message": "subscribe", "instruments": [pair]}
                await self._ws.send(json.dumps(msg))
    
    async def stream(self, pairs: List[str]):
        """
        Générateur asynchrone qui yield les ticks.
        
        Usage:
            async for tick in ws.stream(["EURUSD"]):
                process_tick(tick)
        """
        await self.subscribe(pairs)
        
        while self._running:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=30)
                tick = self._parse_message(msg)
                
                if tick:
                    self._ticks_buffer.append(tick)
                    
                    # Appeler les callbacks
                    if self.on_tick:
                        self.on_tick(tick)
                    
                    for callback in self._callbacks:
                        await callback(tick)
                    
                    yield tick
                    
            except asyncio.TimeoutError:
                logger.warning("Timeout - envoi ping")
                await self._ws.ping()
            except websockets.ConnectionClosed:
                logger.warning("Connexion fermée, reconnexion...")
                await self.connect()
                await self.subscribe(pairs)
    
    def _parse_message(self, msg: str) -> Optional[ForexTick]:
        """Parse le message WebSocket en ForexTick."""
        try:
            data = json.loads(msg)
            
            if self.provider == 'oanda':
                if data.get('type') == 'PRICE':
                    return ForexTick(
                        pair=data['instrument'],
                        bid=float(data['bids'][0]['price']),
                        ask=float(data['asks'][0]['price']),
                        spread=float(data['asks'][0]['price']) - float(data['bids'][0]['price']),
                        timestamp=datetime.fromisoformat(data['time'].replace('Z', '+00:00')),
                    )
            
            elif self.provider == 'fxcm':
                if 'Rates' in data:
                    pair = data.get('Symbol', 'UNKNOWN')
                    rates = data['Rates']
                    return ForexTick(
                        pair=pair,
                        bid=rates[0],
                        ask=rates[1],
                        spread=rates[1] - rates[0],
                        timestamp=datetime.now(),
                        volume=rates[2] if len(rates) > 2 else 0,
                    )
            
        except Exception as e:
            logger.debug(f"Erreur parsing: {e}")
        
        return None
    
    def add_callback(self, callback: Callable):
        """Ajoute un callback appelé à chaque tick."""
        self._callbacks.append(callback)
    
    def get_recent_ticks(self, pair: str, count: int = 100) -> List[ForexTick]:
        """Récupère les ticks récents pour une paire."""
        return [t for t in self._ticks_buffer[-count:] if t.pair == pair]
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


# Exemple d'utilisation
async def example_usage():
    """Exemple d'utilisation du WebSocket Forex."""
    
    # Callback pour traiter les ticks
    async def on_tick(tick: ForexTick):
        print(f"[{tick.timestamp}] {tick.pair}: Bid={tick.bid:.5f} Ask={tick.ask:.5f} Spread={tick.spread:.5f}")
    
    # Connexion et streaming
    async with ForexWebSocket(provider='oanda', on_tick=on_tick) as ws:
        pairs = ["EURUSD", "GBPUSD", "USDJPY"]
        
        async for tick in ws.stream(pairs):
            # Logique de trading ici
            if tick.spread < 0.0002:  # Spread < 2 pips
                logger.info(f"Opportunité détectée: {tick.pair} spread={tick.spread:.5f}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())
