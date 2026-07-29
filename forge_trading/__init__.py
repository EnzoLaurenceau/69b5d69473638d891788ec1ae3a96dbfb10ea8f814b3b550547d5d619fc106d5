"""forge_trading — service de trading de la Forge (SMC + jury, conseiller only).

Package unique et importable. Remplace la double racine precedente :
  00_CORE/trading/  (importable) + 10_TRADING/  (NON importable : le nom commence
  par un chiffre, donc `import 10_TRADING` est une SyntaxError).

Contrat avec le noyau : forge_trading/core/ports.py (7 dependances, degradation gracieuse).
"""
