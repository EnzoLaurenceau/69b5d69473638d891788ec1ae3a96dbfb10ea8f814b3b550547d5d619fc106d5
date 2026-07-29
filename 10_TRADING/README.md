# 10_TRADING - Système d'Arbitrage Hybride Forex/Crypto
## Forge Trading Bots Collection

Ce dossier contient tous les bots de trading et algorithmes créés dans la Forge.

## Architecture

```
10_TRADING/
├── strategies/          # Stratégies de trading (modulaires)
│   ├── base_strategy.py # Classe abstraite
│   ├── micro_arb.py     # Arbitrage micro-gaps
│   ├── momentum.py      # Suivi de momentum
│   └── mean_reversion.py# Retour à la moyenne
├── backtesting/         # Moteur de backtesting (10+ ans)
│   ├── engine.py        # Moteur principal
│   ├── data_loader.py   # Chargement données historiques
│   ├── metrics.py       # Calcul métriques performance
│   └── visualizer.py    # Graphiques résultats
├── data/                # Données de marché
│   ├── forex/           # Paires Forex (EURUSD, GBPUSD, etc.)
│   ├── crypto/          # Cryptos (BTC, ETH, etc.)
│   └── historical/      # Données historiques 10+ ans
├── smart-contracts/     # Contrats Solidity (Flash Loans)
├── config/              # Configuration
│   ├── settings.yaml    # Paramètres globaux
│   └── secrets.yaml     # Clés API (gitignored)
├── logs/                # Logs d'exécution
├── reflection_db/       # Base de données d'apprentissage
│   ├── trades.db        # SQLite - historique trades
│   ├── lessons.json     # Leçons tirées
│   └── patterns.json    # Patterns identifiés
├── scripts/             # Scripts utilitaires
│   ├── websocket_forex.py
│   ├── websocket_crypto.py
│   └── run_backtest.py
├── dashboard/           # Interface monitoring
└── tests/               # Tests unitaires
```

## Objectifs de Performance

- **Win Rate Minimum**: 51% (seuil de rentabilité)
- **Win Rate Cible**: 70%+ (objectif initial)
- **Amélioration Continue**: Le win rate DOIT s'améliorer trade après trade
- **Backtesting**: 10+ ans de données historiques obligatoire
- **Capital Initial**: $50 minimum

## Système de Réflexion (Forge Integration)

Le système utilise le moteur de réflexion de la Forge pour:
1. Analyser chaque trade (gagnant/perdant)
2. Identifier les patterns de succès/échec
3. Ajuster les paramètres de stratégie automatiquement
4. Générer des "leçons" stockées en base
5. Améliorer les décisions futures via apprentissage

## Utilisation Rapide

```bash
# Backtesting
cd 10_TRADING
python scripts/run_backtest.py --strategy micro_arb --years 10

# Live trading (après validation backtest)
python scripts/run_live.py --strategy micro_arb --capital 50

# Voir les métriques
python dashboard/app.py
```
