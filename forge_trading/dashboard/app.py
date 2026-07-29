#!/usr/bin/env python3
"""
Dashboard de monitoring pour le système de trading.
Affiche les métriques en temps réel.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import sys

# [consolidation] sys.path retiré : forge_trading est un package
# sys.path.insert(0, str(Path(__file__).parent.parent))

from forge_trading.reflection_db.database import ReflectionDatabase
from forge_trading.config import config, TRADING_ROOT


class TradingDashboard:
    """
    Dashboard simple en terminal pour le monitoring.
    Affiche:
    - Win rate actuel
    - PnL quotidien
    - Trades récents
    - Leçons apprises
    - Tendances
    """
    
    def __init__(self):
        self.db = ReflectionDatabase()
    
    def show_summary(self, strategy_name: str = None):
        """Affiche le résumé de performance."""
        summary = self.db.get_performance_summary(strategy_name)
        
        print("\n" + "="*60)
        print("📊 TRADING DASHBOARD - FORGE SYSTEM")
        print("="*60)
        
        # Win Rate
        wr = summary.get('win_rate', 0)
        wr_emoji = "✅" if wr >= 0.51 else "⚠️" if wr >= 0.45 else "❌"
        print(f"\n{wr_emoji} Win Rate: {wr:.1%} (objectif: {config.target_win_rate:.0%})")
        
        # Barre de progression
        progress = min(1.0, wr / config.target_win_rate)
        bar = "█" * int(progress * 20) + "░" * (20 - int(progress * 20))
        print(f"   [{bar}] {progress:.0%}")
        
        # Trades
        print(f"\n📈 Trades:")
        print(f"   Total: {summary.get('total_trades', 0)}")
        print(f"   Gagnants: {summary.get('winning_trades', 0)}")
        print(f"   Perdants: {summary.get('losing_trades', 0)}")
        
        # PnL
        total_pnl = summary.get('total_pnl', 0)
        pnl_emoji = "💰" if total_pnl > 0 else "💸"
        print(f"\n{pnl_emoji} PnL Total: ${total_pnl:.2f}")
        print(f"   Moyenne gain: ${summary.get('avg_win_pnl', 0):.2f}")
        print(f"   Moyenne perte: ${summary.get('avg_loss_pnl', 0):.2f}")
        
        # Profit Factor
        pf = summary.get('profit_factor', 0)
        pf_emoji = "✅" if pf >= 1.5 else "⚠️"
        print(f"\n{pf_emoji} Profit Factor: {pf:.2f}")
        
        # Leçons
        lessons_count = summary.get('lessons_learned', 0)
        print(f"\n📚 Leçons apprises: {lessons_count}")
        
        # Tendance
        trend = summary.get('win_rate_trend', [])
        if trend:
            print(f"\n📈 Tendance Win Rate:")
            for t in trend[-3:]:
                print(f"   Période {t['period']}: {t['win_rate']:.1%} ({t['trades']} trades)")
        
        print("\n" + "="*60)
    
    def show_recent_trades(self, strategy_name: str = None, count: int = 10):
        """Affiche les trades récents."""
        trades = self.db.get_recent_trades(strategy_name, limit=count)
        
        if not trades:
            print("\nAucun trade récent.")
            return
        
        print(f"\n📋 {len(trades)} Trades Récents:")
        print("-"*60)
        print(f"{'ID':<10} {'Pair':<10} {'Dir':<5} {'PnL':<10} {'Status':<8}")
        print("-"*60)
        
        for trade in trades[:count]:
            pnl = trade.get('pnl', 0)
            pnl_str = f"${pnl:.2f}"
            pnl_emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
            
            print(f"{trade['id'][:8]:<10} {trade['pair']:<10} {trade['direction']:<5} {pnl_emoji}{pnl_str:<9} {trade['status']:<8}")
    
    def show_lessons(self):
        """Affiche les leçons apprises."""
        lessons = self.db.get_active_lessons()
        
        if not lessons:
            print("\nAucune leçon apprise pour le moment.")
            return
        
        print(f"\n📚 {len(lessons)} Leçons Apprises:")
        print("-"*60)
        
        for i, lesson in enumerate(lessons[:10], 1):
            confidence = lesson.confidence * 100
            print(f"\n{i}. [{lesson.pattern_type}] Confiance: {confidence:.0f}%")
            print(f"   {lesson.description}")
            print(f"   → {lesson.recommendation}")
    
    def show_recommendations(self, strategy_name: str = None):
        """Affiche les recommandations."""
        summary = self.db.get_performance_summary(strategy_name)
        
        if summary.get('total_trades', 0) < 10:
            print("\nPas assez de données pour des recommandations.")
            return
        
        print("\n💡 Recommandations:")
        print("-"*60)
        
        wr = summary.get('win_rate', 0)
        if wr < 0.51:
            print("⚠️  Win rate sous le seuil de rentabilité!")
            print("   → Réviser les paramètres de la stratégie")
            print("   → Analyser les trades perdants pour identifier les patterns")
        elif wr < 0.60:
            print("📊 Win rate acceptable mais optimisable")
            print("   → Ajuster les stop loss et take profit")
            print("   → Filtrer les trades à faible confiance")
        elif wr >= 0.70:
            print("🎯 Excellent win rate!")
            print("   → Maintenir la stratégie actuelle")
            print("   → Considérer une augmentation progressive de la taille des positions")
        
        pf = summary.get('profit_factor', 0)
        if pf < 1.5:
            print("\n⚠️  Profit factor faible")
            print("   → Augmenter les take profits ou réduire les stop loss")
    
    def export_report(self, strategy_name: str = None) -> str:
        """Exporte un rapport JSON."""
        summary = self.db.get_performance_summary(strategy_name)
        recommendations = self.db.export_for_reflection(strategy_name)
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'strategy': strategy_name,
            'performance': summary,
            'recommendations': recommendations,
            'config': {
                'initial_capital': config.initial_capital,
                'target_win_rate': config.target_win_rate,
                'min_win_rate': config.min_win_rate,
            }
        }
        
        report_path = TRADING_ROOT / "logs" / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        return str(report_path)
    
    def interactive_mode(self):
        """Mode interactif du dashboard."""
        while True:
            print("\n" + "="*60)
            print("🎮 FORGE TRADING DASHBOARD")
            print("="*60)
            print("\n1. Voir le résumé")
            print("2. Voir les trades récents")
            print("3. Voir les leçons")
            print("4. Voir les recommandations")
            print("5. Exporter un rapport")
            print("6. Quitter")
            
            choice = input("\nChoix: ").strip()
            
            if choice == '1':
                self.show_summary()
            elif choice == '2':
                self.show_recent_trades()
            elif choice == '3':
                self.show_lessons()
            elif choice == '4':
                self.show_recommendations()
            elif choice == '5':
                path = self.export_report()
                print(f"\nRapport exporté: {path}")
            elif choice == '6':
                print("\nAu revoir! 🚀")
                break
            else:
                print("\nChoix invalide.")


def main():
    """Point d'entrée principal."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Dashboard de monitoring trading')
    parser.add_argument('--strategy', '-s', type=str, help='Nom de la stratégie')
    parser.add_argument('--interactive', '-i', action='store_true', help='Mode interactif')
    parser.add_argument('--export', '-e', action='store_true', help='Exporter un rapport')
    
    args = parser.parse_args()
    
    dashboard = TradingDashboard()
    
    if args.interactive:
        dashboard.interactive_mode()
    elif args.export:
        path = dashboard.export_report(args.strategy)
        print(f"Rapport exporté: {path}")
    else:
        dashboard.show_summary(args.strategy)
        dashboard.show_recent_trades(args.strategy)
        dashboard.show_lessons()
        dashboard.show_recommendations(args.strategy)


if __name__ == '__main__':
    main()
