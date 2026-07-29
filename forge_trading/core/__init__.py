"""
00_CORE/trading — Super Orchestrateur Trading (Forge domain pack).

Conseiller only (pas d'exécution broker). Réutilise l'infra Forge :
forge_llm (FREE), mirofish (jury), forge_mcp_pruner (token éco), turbovec (RAG),
forge_experience_db (BigSet flywheel), token_tracker.

Cœur déterministe = smc_engine (OB/FVG/liquidity-sweep, 0 token LLM).
"""
from .config import TradingConfig, MODERATE

__all__ = ["TradingConfig", "MODERATE"]
