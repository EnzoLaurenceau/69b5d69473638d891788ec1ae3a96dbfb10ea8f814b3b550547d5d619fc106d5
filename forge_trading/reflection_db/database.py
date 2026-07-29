"""
Base de données de réflexion et d'apprentissage des trades.
Système central d'amélioration continue du win rate.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
import logging

import sys
# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))
from forge_trading.strategies.base_strategy import Trade, TradeStatus, TradeDirection
from forge_trading.config import TRADING_ROOT

logger = logging.getLogger(__name__)

DB_PATH = TRADING_ROOT / "reflection_db" / "trades.db"


@dataclass
class TradeLesson:
    """Leçon tirée d'un ou plusieurs trades."""
    id: str
    created_at: datetime
    pattern_type: str  # "winning_pattern", "losing_pattern", "market_condition"
    description: str
    conditions: Dict[str, Any]
    recommendation: str
    confidence: float  # 0.0 à 1.0
    trades_count: int  # Nombre de trades ayant confirmé cette leçon
    win_rate_when_applied: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat(),
            'pattern_type': self.pattern_type,
            'description': self.description,
            'conditions': json.dumps(self.conditions),
            'recommendation': self.recommendation,
            'confidence': self.confidence,
            'trades_count': self.trades_count,
            'win_rate_when_applied': self.win_rate_when_applied
        }


class ReflectionDatabase:
    """
    Base de données SQLite pour l'apprentissage des trades.
    
    Fonctionnalités:
    - Stockage de tous les trades (backtest + live)
    - Analyse des patterns gagnants/perdants
    - Génération de leçons automatiques
    - Suivi de l'amélioration du win rate
    - Intégration avec le système de réflexion de la Forge
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialise la base de données avec le schéma."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pair TEXT NOT NULL,
                    market TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    quantity REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    entry_time DATETIME,
                    exit_time DATETIME,
                    pnl REAL DEFAULT 0,
                    pnl_percent REAL DEFAULT 0,
                    fees REAL DEFAULT 0,
                    status TEXT DEFAULT 'PENDING',
                    strategy_name TEXT,
                    is_winner BOOLEAN,
                    duration_seconds REAL,
                    signal_confidence REAL,
                    risk_reward_ratio REAL,
                    metadata TEXT,
                    -- Conditions de marché au moment du trade
                    market_conditions TEXT,
                    indicators TEXT,
                    -- Apprentissage
                    lesson_id TEXT,
                    applied_lesson BOOLEAN DEFAULT FALSE
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pattern_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    conditions TEXT,
                    recommendation TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    trades_count INTEGER DEFAULT 1,
                    win_rate_when_applied REAL DEFAULT 0,
                    times_applied INTEGER DEFAULT 0,
                    times_successful INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS win_rate_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    strategy_name TEXT NOT NULL,
                    window_size INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    period_start DATETIME,
                    period_end DATETIME
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pattern_name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    conditions TEXT NOT NULL,
                    outcome TEXT,
                    confidence REAL DEFAULT 0.5,
                    occurrences INTEGER DEFAULT 1
                )
            """)
            
            # Index pour performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_winner ON trades(is_winner)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lessons_type ON lessons(pattern_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lessons_active ON lessons(is_active)")
            
            conn.commit()
    
    def save_trade(self, trade: Trade, market_conditions: Optional[Dict] = None, indicators: Optional[Dict] = None):
        """Sauvegarde un trade dans la base de données."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trades (
                    id, pair, market, direction, entry_price, exit_price,
                    quantity, stop_loss, take_profit, entry_time, exit_time,
                    pnl, pnl_percent, fees, status, strategy_name, is_winner,
                    duration_seconds, signal_confidence, risk_reward_ratio,
                    metadata, market_conditions, indicators
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.id,
                trade.pair,
                trade.market,
                trade.direction.value,
                trade.entry_price,
                trade.exit_price,
                trade.quantity,
                trade.stop_loss,
                trade.take_profit,
                trade.entry_time.isoformat() if trade.entry_time else None,
                trade.exit_time.isoformat() if trade.exit_time else None,
                trade.pnl,
                trade.pnl_percent,
                trade.fees,
                trade.status.value,
                trade.strategy_name,
                trade.is_winner,
                trade.duration_seconds,
                trade.metadata.get('signal_confidence', 0),
                trade.metadata.get('risk_reward', 0),
                json.dumps(trade.metadata),
                json.dumps(market_conditions) if market_conditions else None,
                json.dumps(indicators) if indicators else None
            ))
            conn.commit()
        
        logger.debug(f"Trade sauvegardé: {trade.id} ({trade.pair})")
        
        # Déclencher l'analyse de pattern après sauvegarde
        self._analyze_patterns_after_trade(trade)
    
    def get_win_rate(
        self, 
        strategy_name: Optional[str] = None,
        pair: Optional[str] = None,
        window_size: int = 100,
        market: Optional[str] = None
    ) -> Tuple[float, int]:
        """
        Calcule le win rate actuel.
        
        Returns:
            Tuple (win_rate, total_trades)
        """
        query = "SELECT is_winner FROM trades WHERE status = 'CLOSED'"
        params = []
        
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        
        if pair:
            query += " AND pair = ?"
            params.append(pair)
        
        if market:
            query += " AND market = ?"
            params.append(market)
        
        query += f" ORDER BY exit_time DESC LIMIT {window_size}"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            results = cursor.fetchall()
        
        if not results:
            return 0.0, 0
        
        wins = sum(1 for r in results if r[0])
        return wins / len(results), len(results)
    
    def get_win_rate_trend(self, strategy_name: str, periods: int = 5) -> List[Dict]:
        """
        Analyse la tendance du win rate sur plusieurs périodes.
        """
        trades = self.get_recent_trades(strategy_name, limit=periods * 100)
        
        if len(trades) < 20:
            return []
        
        trends = []
        chunk_size = len(trades) // periods
        
        for i in range(periods):
            chunk = trades[i*chunk_size:(i+1)*chunk_size]
            if chunk:
                wins = sum(1 for t in chunk if t.get('is_winner'))
                trends.append({
                    'period': i + 1,
                    'win_rate': wins / len(chunk),
                    'trades': len(chunk),
                    'timestamp': chunk[0].get('timestamp')
                })
        
        return trends
    
    def save_lesson(self, lesson: TradeLesson):
        """Sauvegarde une leçon apprise."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO lessons (
                    id, pattern_type, description, conditions, recommendation,
                    confidence, trades_count, win_rate_when_applied, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lesson.id,
                lesson.pattern_type,
                lesson.description,
                json.dumps(lesson.conditions),
                lesson.recommendation,
                lesson.confidence,
                lesson.trades_count,
                lesson.win_rate_when_applied,
                True
            ))
            conn.commit()
        
        logger.info(f"Leçon sauvegardée: {lesson.id} - {lesson.description[:50]}...")
    
    def get_active_lessons(
        self, 
        pattern_type: Optional[str] = None,
        min_confidence: float = 0.3
    ) -> List[TradeLesson]:
        """Récupère les leçons actives."""
        query = "SELECT * FROM lessons WHERE is_active = TRUE AND confidence >= ?"
        params = [min_confidence]
        
        if pattern_type:
            query += " AND pattern_type = ?"
            params.append(pattern_type)
        
        query += " ORDER BY confidence DESC, trades_count DESC"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        
        lessons = []
        for row in rows:
            lessons.append(TradeLesson(
                id=row['id'],
                created_at=datetime.fromisoformat(row['created_at']),
                pattern_type=row['pattern_type'],
                description=row['description'],
                conditions=json.loads(row['conditions']) if row['conditions'] else {},
                recommendation=row['recommendation'],
                confidence=row['confidence'],
                trades_count=row['trades_count'],
                win_rate_when_applied=row['win_rate_when_applied']
            ))
        
        return lessons
    
    def get_recent_trades(self, strategy_name: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Récupère les trades récents."""
        query = "SELECT * FROM trades WHERE status = 'CLOSED'"
        params = []
        
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        
        query += f" ORDER BY exit_time DESC LIMIT {limit}"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def _analyze_patterns_after_trade(self, trade: Trade):
        """
        Analyse les patterns après un trade.
        Génère des leçons si nécessaire.
        """
        # Récupérer les trades similaires
        similar_trades = self._find_similar_trades(trade)
        
        if len(similar_trades) < 5:
            return
        
        # Analyser le pattern
        wins = [t for t in similar_trades if t.get('is_winner')]
        losses = [t for t in similar_trades if not t.get('is_winner')]
        
        win_rate = len(wins) / len(similar_trades)
        
        # Si le win rate est significativement bon ou mauvais, créer une leçon
        if win_rate > 0.75 and len(wins) >= 5:
            self._create_winning_pattern_lesson(trade, wins, win_rate)
        elif win_rate < 0.35 and len(losses) >= 5:
            self._create_losing_pattern_lesson(trade, losses, win_rate)
    
    def _find_similar_trades(self, trade: Trade) -> List[Dict]:
        """Trouve des trades similaires basés sur les conditions de marché."""
        # Chercher sur la même paire avec des conditions similaires
        query = """
            SELECT * FROM trades 
            WHERE pair = ? 
            AND direction = ? 
            AND status = 'CLOSED'
            AND ABS(signal_confidence - ?) < 0.2
            ORDER BY exit_time DESC 
            LIMIT 50
        """
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, (
                trade.pair,
                trade.direction.value,
                trade.metadata.get('signal_confidence', 0.5)
            ))
            return [dict(row) for row in cursor.fetchall()]
    
    def _create_winning_pattern_lesson(self, trade: Trade, wins: List[Dict], win_rate: float):
        """Crée une leçon basée sur un pattern gagnant."""
        lesson_id = f"win_{trade.pair}_{trade.direction.value}_{datetime.now().strftime('%Y%m%d%H%M')}"
        
        # Analyser les conditions communes des trades gagnants
        common_conditions = self._extract_common_conditions(wins)
        
        lesson = TradeLesson(
            id=lesson_id,
            created_at=datetime.now(),
            pattern_type="winning_pattern",
            description=f"Pattern gagnant identifié sur {trade.pair} ({trade.direction.value})",
            conditions=common_conditions,
            recommendation=f"Continuer à trader {trade.pair} dans cette direction avec ces conditions",
            confidence=min(0.9, win_rate),
            trades_count=len(wins),
            win_rate_when_applied=win_rate
        )
        
        self.save_lesson(lesson)
        logger.info(f"Leçon gagnante créée: {lesson_id} (WR={win_rate:.1%})")
    
    def _create_losing_pattern_lesson(self, trade: Trade, losses: List[Dict], win_rate: float):
        """Crée une leçon basée sur un pattern perdant."""
        lesson_id = f"loss_{trade.pair}_{trade.direction.value}_{datetime.now().strftime('%Y%m%d%H%M')}"
        
        common_conditions = self._extract_common_conditions(losses)
        
        lesson = TradeLesson(
            id=lesson_id,
            created_at=datetime.now(),
            pattern_type="losing_pattern",
            description=f"Pattern perdant identifié sur {trade.pair} ({trade.direction.value})",
            conditions=common_conditions,
            recommendation=f"Éviter de trader {trade.pair} dans cette direction avec ces conditions",
            confidence=min(0.9, 1 - win_rate),
            trades_count=len(losses),
            win_rate_when_applied=win_rate
        )
        
        self.save_lesson(lesson)
        logger.warning(f"Leçon perdante créée: {lesson_id} (WR={win_rate:.1%})")
    
    def _extract_common_conditions(self, trades: List[Dict]) -> Dict[str, Any]:
        """Extrait les conditions communes d'un ensemble de trades."""
        conditions = {
            'avg_confidence': sum(t.get('signal_confidence', 0) for t in trades) / len(trades),
            'avg_duration': sum(t.get('duration_seconds', 0) for t in trades) / len(trades),
            'avg_risk_reward': sum(t.get('risk_reward_ratio', 0) for t in trades) / len(trades),
        }
        
        # Analyser les indicateurs si disponibles
        indicators_list = [json.loads(t['indicators']) for t in trades if t.get('indicators')]
        if indicators_list:
            for key in indicators_list[0].keys():
                values = [ind.get(key) for ind in indicators_list if ind.get(key) is not None]
                if values:
                    conditions[f'avg_{key}'] = sum(values) / len(values)
        
        return conditions
    
    def get_performance_summary(self, strategy_name: Optional[str] = None) -> Dict[str, Any]:
        """Génère un résumé de performance global."""
        query = "SELECT * FROM trades WHERE status = 'CLOSED'"
        params = []
        
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            trades = [dict(row) for row in cursor.fetchall()]
        
        if not trades:
            return {'total_trades': 0, 'win_rate': 0.0}
        
        wins = [t for t in trades if t['is_winner']]
        losses = [t for t in trades if not t['is_winner']]
        
        return {
            'total_trades': len(trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins) / len(trades),
            'total_pnl': sum(t['pnl'] for t in trades),
            'avg_win_pnl': sum(t['pnl'] for t in wins) / len(wins) if wins else 0,
            'avg_loss_pnl': sum(t['pnl'] for t in losses) / len(losses) if losses else 0,
            'profit_factor': abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses and sum(t['pnl'] for t in losses) != 0 else float('inf'),
            'avg_trade_duration': sum(t['duration_seconds'] for t in trades) / len(trades),
            'best_trade': max(t['pnl'] for t in trades),
            'worst_trade': min(t['pnl'] for t in trades),
            'lessons_learned': len(self.get_active_lessons()),
            'win_rate_trend': self.get_win_rate_trend(strategy_name) if strategy_name else []
        }
    
    def export_for_reflection(self, strategy_name: str) -> Dict[str, Any]:
        """
        Exporte les données pour le système de réflexion de la Forge.
        Format compatible avec le moteur de réflexion.
        """
        summary = self.get_performance_summary(strategy_name)
        lessons = self.get_active_lessons()
        recent_trades = self.get_recent_trades(strategy_name, limit=50)
        
        return {
            'strategy': strategy_name,
            'performance': summary,
            'lessons': [l.to_dict() for l in lessons],
            'recent_trades': recent_trades,
            'recommendations': self._generate_recommendations(summary, lessons),
            'exported_at': datetime.now().isoformat()
        }
    
    def _generate_recommendations(self, summary: Dict, lessons: List[TradeLesson]) -> List[str]:
        """Génère des recommandations basées sur l'analyse."""
        recommendations = []
        
        if summary['total_trades'] < 100:
            recommendations.append("Collecter plus de données avant d'optimiser (min 100 trades)")
        
        if summary['win_rate'] < 0.51:
            recommendations.append("WIN RATE SOUS LE SEUIL DE RENTABILITÉ - Réviser la stratégie")
        elif summary['win_rate'] < 0.60:
            recommendations.append("Win rate acceptable mais peut être amélioré")
        elif summary['win_rate'] >= 0.70:
            recommendations.append("Excellent win rate - Maintenir la stratégie")
        
        if summary['profit_factor'] < 1.5:
            recommendations.append("Profit factor faible - Augmenter les take profits ou réduire les stop loss")
        
        # Recommandations basées sur les leçons
        losing_lessons = [l for l in lessons if l.pattern_type == "losing_pattern"]
        if losing_lessons:
            recommendations.append(f"Éviter {len(losing_lessons)} patterns perdants identifiés")
        
        winning_lessons = [l for l in lessons if l.pattern_type == "winning_pattern"]
        if winning_lessons:
            recommendations.append(f"Exploiter {len(winning_lessons)} patterns gagnants identifiés")
        
        return recommendations


# Instance globale
db = ReflectionDatabase()
