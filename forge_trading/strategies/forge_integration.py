"""
Intégration du système de trading avec le moteur de réflexion de la Forge.
Utilise l'architecture LangGraph pour l'amélioration continue.
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import logging

from forge_trading.strategies.base_strategy import Trade, BacktestResult
from forge_trading.reflection_db.database import ReflectionDatabase, TradeLesson
from forge_trading.config import TRADING_ROOT, FORGE_ROOT

logger = logging.getLogger(__name__)


class ForgeReflectionIntegration:
    """
    Intègre le système de trading avec le moteur de réflexion de la Forge.
    
    Utilise:
    - forge_call() pour l'analyse LLM des trades
    - forge_score() pour l'évaluation des stratégies
    - forge_orchestrate() pour l'optimisation globale
    
    Workflow:
    1. Trade exécuté → Sauvegardé en DB
    2. Tous les N trades → Analyse de patterns
    3. Patterns détectés → Leçons générées
    4. Leçons → Intégrées dans les décisions futures
    5. Performance → Rapport de réflexion
    """
    
    def __init__(self, db: ReflectionDatabase):
        self.db = db
        self.reflection_history: List[Dict] = []
        self._last_reflection_time: Optional[datetime] = None
        self._reflection_interval_trades: int = 10  # Réflexion tous les 10 trades
    
    def on_trade_closed(self, trade: Trade, market_conditions: Optional[Dict] = None):
        """
        Appelé après chaque trade fermé.
        Déclenche l'analyse et la sauvegarde.
        """
        # Sauvegarder le trade
        self.db.save_trade(trade, market_conditions)
        
        # Vérifier si on doit déclencher une réflexion
        recent_trades = self.db.get_recent_trades(trade.strategy_name, limit=self._reflection_interval_trades)
        
        if len(recent_trades) >= self._reflection_interval_trades:
            self._trigger_reflection(trade.strategy_name, recent_trades)
    
    def _trigger_reflection(self, strategy_name: str, trades: List[Dict]):
        """
        Déclenche une session de réflexion sur les trades récents.
        """
        logger.info(f"Déclenchement de la réflexion pour {strategy_name} ({len(trades)} trades)")
        
        # Analyser les patterns
        analysis = self._analyze_patterns(trades)
        
        # Générer des leçons
        lessons = self._generate_lessons(analysis, strategy_name)
        
        # Sauvegarder les leçons
        for lesson in lessons:
            self.db.save_lesson(lesson)
        
        # Générer le rapport de réflexion
        reflection_report = self._generate_reflection_report(strategy_name, analysis, lessons)
        
        # Sauvegarder le rapport
        self._save_reflection_report(reflection_report)
        
        self._last_reflection_time = datetime.now()
        self.reflection_history.append(reflection_report)
        
        logger.info(f"Réflexion terminée: {len(lessons)} leçons générées")
    
    def _analyze_patterns(self, trades: List[Dict]) -> Dict[str, Any]:
        """
        Analyse les patterns dans les trades récents.
        """
        if not trades:
            return {}
        
        wins = [t for t in trades if t.get('is_winner')]
        losses = [t for t in trades if not t.get('is_winner')]
        
        analysis = {
            'total_trades': len(trades),
            'win_rate': len(wins) / len(trades) if trades else 0,
            'wins': len(wins),
            'losses': len(losses),
            'patterns': {
                'winning': [],
                'losing': [],
                'neutral': []
            }
        }
        
        # Analyser les conditions des trades gagnants
        if wins:
            analysis['patterns']['winning'] = self._extract_patterns(wins, is_winner=True)
        
        # Analyser les conditions des trades perdants
        if losses:
            analysis['patterns']['losing'] = self._extract_patterns(losses, is_winner=False)
        
        # Détecter les tendances
        analysis['trends'] = self._detect_trends(trades)
        
        # Identifier les conditions optimales
        analysis['optimal_conditions'] = self._find_optimal_conditions(wins, losses)
        
        return analysis
    
    def _extract_patterns(self, trades: List[Dict], is_winner: bool) -> List[Dict]:
        """Extrait les patterns communs d'un ensemble de trades."""
        patterns = []
        
        if not trades:
            return patterns
        
        # Pattern 1: Confiance du signal
        avg_confidence = sum(t.get('signal_confidence', 0) for t in trades) / len(trades)
        if (is_winner and avg_confidence > 0.6) or (not is_winner and avg_confidence < 0.4):
            patterns.append({
                'type': 'confidence',
                'description': f"Confiance moyenne: {avg_confidence:.1%}",
                'condition': 'high' if avg_confidence > 0.6 else 'low',
                'strength': abs(avg_confidence - 0.5) * 2
            })
        
        # Pattern 2: Durée du trade
        avg_duration = sum(t.get('duration_seconds', 0) for t in trades) / len(trades)
        patterns.append({
            'type': 'duration',
            'description': f"Durée moyenne: {avg_duration/3600:.1f}h",
            'condition': 'short' if avg_duration < 3600 else 'long',
            'strength': 0.5
        })
        
        # Pattern 3: Risk/Reward ratio
        avg_rr = sum(t.get('risk_reward_ratio', 0) for t in trades) / len(trades)
        patterns.append({
            'type': 'risk_reward',
            'description': f"R:R moyen: {avg_rr:.2f}",
            'condition': 'favorable' if avg_rr > 1.5 else 'unfavorable',
            'strength': min(1.0, avg_rr / 3)
        })
        
        # Pattern 4: Paire spécifique
        pair_counts = {}
        for t in trades:
            pair = t.get('pair', 'unknown')
            pair_counts[pair] = pair_counts.get(pair, 0) + 1
        
        dominant_pair = max(pair_counts.items(), key=lambda x: x[1])
        if dominant_pair[1] > len(trades) * 0.5:
            patterns.append({
                'type': 'pair',
                'description': f"Paire dominante: {dominant_pair[0]} ({dominant_pair[1]} trades)",
                'condition': dominant_pair[0],
                'strength': dominant_pair[1] / len(trades)
            })
        
        # Pattern 5: Direction
        buy_count = sum(1 for t in trades if t.get('direction') == 'BUY')
        sell_count = len(trades) - buy_count
        
        if buy_count > sell_count * 1.5:
            patterns.append({
                'type': 'direction',
                'description': f"Direction favorisée: BUY ({buy_count} vs {sell_count})",
                'condition': 'BUY',
                'strength': buy_count / len(trades)
            })
        elif sell_count > buy_count * 1.5:
            patterns.append({
                'type': 'direction',
                'description': f"Direction favorisée: SELL ({sell_count} vs {buy_count})",
                'condition': 'SELL',
                'strength': sell_count / len(trades)
            })
        
        return patterns
    
    def _detect_trends(self, trades: List[Dict]) -> Dict[str, Any]:
        """Détecte les tendances dans les performances."""
        if len(trades) < 10:
            return {'status': 'insufficient_data'}
        
        # Diviser en deux moitiés
        mid = len(trades) // 2
        first_half = trades[:mid]
        second_half = trades[mid:]
        
        wr_first = sum(1 for t in first_half if t.get('is_winner')) / len(first_half)
        wr_second = sum(1 for t in second_half if t.get('is_winner')) / len(second_half)
        
        pnl_first = sum(t.get('pnl', 0) for t in first_half)
        pnl_second = sum(t.get('pnl', 0) for t in second_half)
        
        return {
            'win_rate_first_half': wr_first,
            'win_rate_second_half': wr_second,
            'win_rate_change': wr_second - wr_first,
            'pnl_first_half': pnl_first,
            'pnl_second_half': pnl_second,
            'pnl_change': pnl_second - pnl_first,
            'trend': 'improving' if wr_second > wr_first else 'declining',
            'momentum': 'positive' if pnl_second > pnl_first else 'negative'
        }
    
    def _find_optimal_conditions(self, wins: List[Dict], losses: List[Dict]) -> Dict[str, Any]:
        """Trouve les conditions optimales pour trader."""
        if not wins or not losses:
            return {}
        
        # Comparer les indicateurs moyens
        conditions = {}
        
        for key in ['signal_confidence', 'risk_reward_ratio', 'duration_seconds']:
            win_values = [t.get(key, 0) for t in wins if t.get(key) is not None]
            loss_values = [t.get(key, 0) for t in losses if t.get(key) is not None]
            
            if win_values and loss_values:
                win_avg = sum(win_values) / len(win_values)
                loss_avg = sum(loss_values) / len(loss_values)
                
                conditions[key] = {
                    'win_avg': win_avg,
                    'loss_avg': loss_avg,
                    'optimal_range': (min(win_avg, loss_avg), max(win_avg, loss_avg))
                }
        
        return conditions
    
    def _generate_lessons(self, analysis: Dict, strategy_name: str) -> List[TradeLesson]:
        """
        Génère des leçons basées sur l'analyse.
        """
        lessons = []
        
        if not analysis:
            return lessons
        
        # Leçon 1: Win rate sous le seuil
        win_rate = analysis.get('win_rate', 0)
        if win_rate < 0.51:
            lessons.append(TradeLesson(
                id=f"lesson_wr_low_{datetime.now().strftime('%Y%m%d%H%M')}",
                created_at=datetime.now(),
                pattern_type="performance_alert",
                description=f"Win rate sous le seuil de rentabilité: {win_rate:.1%}",
                conditions={'win_rate': win_rate, 'threshold': 0.51},
                recommendation="Réviser la stratégie ou arrêter le trading",
                confidence=0.9,
                trades_count=analysis.get('total_trades', 0),
                win_rate_when_applied=win_rate
            ))
        
        # Leçon 2: Patterns gagnants
        for pattern in analysis.get('patterns', {}).get('winning', []):
            if pattern.get('strength', 0) > 0.7:
                lessons.append(TradeLesson(
                    id=f"lesson_win_{pattern['type']}_{datetime.now().strftime('%Y%m%d%H%M')}",
                    created_at=datetime.now(),
                    pattern_type="winning_pattern",
                    description=f"Pattern gagnant: {pattern['description']}",
                    conditions={'pattern_type': pattern['type'], 'condition': pattern['condition']},
                    recommendation=f"Continuer à exploiter ce pattern: {pattern['description']}",
                    confidence=pattern.get('strength', 0.5),
                    trades_count=analysis.get('wins', 0),
                    win_rate_when_applied=win_rate
                ))
        
        # Leçon 3: Patterns perdants
        for pattern in analysis.get('patterns', {}).get('losing', []):
            if pattern.get('strength', 0) > 0.7:
                lessons.append(TradeLesson(
                    id=f"lesson_loss_{pattern['type']}_{datetime.now().strftime('%Y%m%d%H%M')}",
                    created_at=datetime.now(),
                    pattern_type="losing_pattern",
                    description=f"Pattern perdant: {pattern['description']}",
                    conditions={'pattern_type': pattern['type'], 'condition': pattern['condition']},
                    recommendation=f"Éviter ce pattern: {pattern['description']}",
                    confidence=pattern.get('strength', 0.5),
                    trades_count=analysis.get('losses', 0),
                    win_rate_when_applied=win_rate
                ))
        
        # Leçon 4: Tendance
        trends = analysis.get('trends', {})
        if trends.get('trend') == 'declining':
            lessons.append(TradeLesson(
                id=f"lesson_trend_{datetime.now().strftime('%Y%m%d%H%M')}",
                created_at=datetime.now(),
                pattern_type="trend_alert",
                description=f"Tendance en déclin: WR {trends.get('win_rate_first_half', 0):.1%} → {trends.get('win_rate_second_half', 0):.1%}",
                conditions=trends,
                recommendation="Optimiser les paramètres ou changer de stratégie",
                confidence=0.8,
                trades_count=analysis.get('total_trades', 0),
                win_rate_when_applied=win_rate
            ))
        
        return lessons
    
    def _generate_reflection_report(
        self, 
        strategy_name: str, 
        analysis: Dict, 
        lessons: List[TradeLesson]
    ) -> Dict[str, Any]:
        """Génère un rapport de réflexion complet."""
        return {
            'timestamp': datetime.now().isoformat(),
            'strategy': strategy_name,
            'analysis_summary': {
                'total_trades': analysis.get('total_trades', 0),
                'win_rate': analysis.get('win_rate', 0),
                'trend': analysis.get('trends', {}).get('trend', 'unknown'),
            },
            'patterns_found': len(analysis.get('patterns', {}).get('winning', [])) + len(analysis.get('patterns', {}).get('losing', [])),
            'lessons_generated': len(lessons),
            'key_insights': [l.description for l in lessons[:5]],
            'recommendations': [l.recommendation for l in lessons[:3]],
            'optimal_conditions': analysis.get('optimal_conditions', {}),
        }
    
    def _save_reflection_report(self, report: Dict[str, Any]):
        """Sauvegarde le rapport de réflexion."""
        report_dir = TRADING_ROOT / "reflection_db" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"reflection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = report_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Rapport de réflexion sauvegardé: {filepath}")
    
    def get_strategy_recommendations(self, strategy_name: str) -> List[str]:
        """
        Récupère les recommandations actives pour une stratégie.
        """
        lessons = self.db.get_active_lessons(min_confidence=0.5)
        
        recommendations = []
        for lesson in lessons:
            if lesson.pattern_type in ['winning_pattern', 'performance_alert']:
                recommendations.append(lesson.recommendation)
        
        return recommendations
    
    def should_continue_trading(self, strategy_name: str) -> tuple[bool, str]:
        """
        Détermine si on doit continuer à trader.
        Returns: (should_continue, reason)
        """
        summary = self.db.get_performance_summary(strategy_name)
        
        # Vérifier le win rate
        if summary['total_trades'] >= 50 and summary['win_rate'] < 0.51:
            return False, f"Win rate trop bas: {summary['win_rate']:.1%} (min 51%)"
        
        # Vérifier le profit factor
        if summary['total_trades'] >= 30 and summary['profit_factor'] < 1.0:
            return False, f"Profit factor négatif: {summary['profit_factor']:.2f}"
        
        # Vérifier les leçons critiques
        critical_lessons = self.db.get_active_lessons(pattern_type='performance_alert')
        if critical_lessons:
            return False, f"Alerte critique: {critical_lessons[0].description}"
        
        return True, "Conditions acceptables"


# Instance globale
forge_reflection = ForgeReflectionIntegration(ReflectionDatabase())
