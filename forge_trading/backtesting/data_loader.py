"""
Chargeur de données historiques pour backtesting.
Supporte 10+ ans de données via yfinance ou fichiers CSV.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import logging

import sys
# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))
from forge_trading.config import TRADING_ROOT

logger = logging.getLogger(__name__)

DATA_DIR = TRADING_ROOT / "data"


class HistoricalDataLoader:
    """
    Chargeur de données historiques multi-sources.
    
    Sources supportées:
    - yfinance (Yahoo Finance) - Gratuit, 10+ ans
    - Fichiers CSV locaux
    - API Forex (OANDA, etc.)
    - API Crypto (Binance, etc.)
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or DATA_DIR / "historical"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, pd.DataFrame] = {}
    
    def load_forex(
        self,
        pair: str = "EURUSD",
        years: int = 10,
        timeframe: str = "1d",  # 1d, 1h, 5m
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Charge les données historiques Forex.
        
        Args:
            pair: Paire de devises (ex: "EURUSD", "GBPUSD")
            years: Nombre d'années d'historique
            timeframe: Temporalité (1d, 1h, 5m)
            use_cache: Utiliser le cache local
            
        Returns:
            DataFrame avec colonnes ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        cache_key = f"forex_{pair}_{years}y_{timeframe}"
        
        # Vérifier le cache
        if use_cache and cache_key in self._cache:
            logger.info(f"Utilisation du cache pour {cache_key}")
            return self._cache[cache_key]
        
        # Vérifier le fichier cache local
        cache_file = self.cache_dir / f"{cache_key}.parquet"
        if use_cache and cache_file.exists():
            logger.info(f"Chargement depuis le fichier cache: {cache_file}")
            df = pd.read_parquet(cache_file)
            self._cache[cache_key] = df
            return df
        
        # Télécharger via yfinance
        logger.info(f"Téléchargement des données {pair} ({years} ans, {timeframe})")
        df = self._download_forex_yfinance(pair, years, timeframe)
        
        # Sauvegarder en cache
        if use_cache:
            df.to_parquet(cache_file)
            self._cache[cache_key] = df
        
        return df
    
    def _download_forex_yfinance(
        self, 
        pair: str, 
        years: int, 
        timeframe: str
    ) -> pd.DataFrame:
        """Télécharge les données Forex via yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("yfinance non installé. pip install yfinance")
        
        # Formater le ticker pour yfinance
        # EURUSD -> EURUSD=X
        ticker = f"{pair}=X"
        
        # Calculer les dates
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years * 365)
        
        # Télécharger les données
        data = yf.download(
            ticker,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval=timeframe,
            progress=False
        )
        
        if data.empty:
            raise ValueError(f"Aucune donnée récupérée pour {pair}")
        
        # Formater le DataFrame
        df = pd.DataFrame({
            'timestamp': data.index,
            'open': data['Open'].values.flatten(),
            'high': data['High'].values.flatten(),
            'low': data['Low'].values.flatten(),
            'close': data['Close'].values.flatten(),
            'volume': data['Volume'].values.flatten() if 'Volume' in data.columns else 0
        })
        
        df = df.reset_index(drop=True)
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        logger.info(f"Données chargées: {len(df)} barres pour {pair}")
        return df
    
    def load_crypto(
        self,
        pair: str = "BTC-USD",
        years: int = 10,
        timeframe: str = "1d",
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Charge les données historiques Crypto.
        
        Args:
            pair: Paire crypto (ex: "BTC-USD", "ETH-USD")
            years: Nombre d'années
            timeframe: Temporalité
            use_cache: Utiliser le cache
        """
        cache_key = f"crypto_{pair}_{years}y_{timeframe}"
        
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        cache_file = self.cache_dir / f"{cache_key}.parquet"
        if use_cache and cache_file.exists():
            df = pd.read_parquet(cache_file)
            self._cache[cache_key] = df
            return df
        
        logger.info(f"Téléchargement des données crypto {pair} ({years} ans)")
        df = self._download_crypto_yfinance(pair, years, timeframe)
        
        if use_cache:
            df.to_parquet(cache_file)
            self._cache[cache_key] = df
        
        return df
    
    def _download_crypto_yfinance(
        self, 
        pair: str, 
        years: int, 
        timeframe: str
    ) -> pd.DataFrame:
        """Télécharge les données crypto via yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("yfinance non installé. pip install yfinance")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years * 365)
        
        data = yf.download(
            pair,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval=timeframe,
            progress=False
        )
        
        if data.empty:
            raise ValueError(f"Aucune donnée récupérée pour {pair}")
        
        df = pd.DataFrame({
            'timestamp': data.index,
            'open': data['Open'].values.flatten(),
            'high': data['High'].values.flatten(),
            'low': data['Low'].values.flatten(),
            'close': data['Close'].values.flatten(),
            'volume': data['Volume'].values.flatten()
        })
        
        df = df.reset_index(drop=True)
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        logger.info(f"Données crypto chargées: {len(df)} barres pour {pair}")
        return df
    
    def load_from_csv(
        self, 
        file_path: str, 
        timestamp_col: str = 'timestamp',
        parse_dates: bool = True
    ) -> pd.DataFrame:
        """Charge les données depuis un fichier CSV."""
        df = pd.read_csv(file_path, parse_dates=[timestamp_col] if parse_dates else False)
        
        # Normaliser les noms de colonnes
        column_mapping = {
            'Date': 'timestamp', 'Datetime': 'timestamp', 'Time': 'timestamp',
            'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
            'Volume': 'volume', 'Vol': 'volume'
        }
        
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        
        required_cols = ['timestamp', 'open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Colonne manquante: {col}")
        
        return df
    
    def generate_synthetic_data(
        self,
        years: int = 10,
        volatility: float = 0.001,
        trend: float = 0.0001,
        noise: float = 0.0005,
        start_price: float = 1.1000  # EURUSD typique
    ) -> pd.DataFrame:
        """
        Génère des données synthétiques pour les tests.
        Utile quand les données réelles ne sont pas disponibles.
        """
        np.random.seed(42)
        
        # Générer les timestamps (1 barre par jour)
        days = years * 365
        timestamps = pd.date_range(end=datetime.now(), periods=days, freq='D')
        
        # Générer les prix avec marche aléatoire + trend
        returns = np.random.normal(trend, volatility, days)
        prices = start_price * np.exp(np.cumsum(returns))
        
        # Créer les OHLCV
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'close': prices * (1 + np.random.normal(0, noise, days)),
            'high': prices * (1 + abs(np.random.normal(0, volatility, days))),
            'low': prices * (1 - abs(np.random.normal(0, volatility, days))),
            'volume': np.random.randint(1000, 100000, days)
        })
        
        # S'assurer que high >= open, close et low <= open, close
        df['high'] = df[['open', 'close', 'high']].max(axis=1)
        df['low'] = df[['open', 'close', 'low']].min(axis=1)
        
        logger.info(f"Données synthétiques générées: {len(df)} barres ({years} ans)")
        return df
    
    def get_available_pairs(self, market: str = "forex") -> List[str]:
        """Retourne les paires disponibles pour le backtesting."""
        if market == "forex":
            return [
                "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                "NZDUSD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY"
            ]
        elif market == "crypto":
            return [
                "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "MATIC-USD",
                "LINK-USD", "UNI-USD", "AAVE-USD"
            ]
        return []
    
    def clear_cache(self):
        """Vide le cache en mémoire."""
        self._cache.clear()
        logger.info("Cache vidé")


# Instance globale
loader = HistoricalDataLoader()
