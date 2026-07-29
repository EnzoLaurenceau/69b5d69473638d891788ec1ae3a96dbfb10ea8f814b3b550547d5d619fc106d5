# AGENTS.md — 00_CORE/trading

## Purpose
Super-orchestrateur trading **conseiller-only** (aucune exécution broker). Analyse une
paire FOREX → setup SMC déterministe (OB/FVG/liquidity-sweep) → jury d'avis comparés →
money-management profil MODÉRÉ "petits gains" → rapport fichier → flywheel BigSet.

## Ownership
Pack autonome. Dépend de `forge_agents/` (forge_llm FREE, mirofish, forge_mcp_pruner,
turbovec_brain, forge_experience_db, token_tracker) en best-effort : tout dégrade
proprement si un module/clé manque.

## Local Contracts
- **CONSEILLER ONLY.** Pas d'ordre, pas d'argent. Exécution réelle = Phase 4 (HITL gate, OFF).
- **Token economy.** SMC = pandas déterministe (0 token). LLM = `forge_call(tier=FREE)`
  uniquement, et SEULEMENT si un setup existe. MCP/TA via lib directe + tracking pruner.
- **Output = fichiers** (`05_STATE/trading/*.md`), jamais de blob inline.
- Sorties analystes = ligne stricte `VOTE= SCORE= REASON=` (parsable, courte).

## Modules
| Fichier | Rôle |
|---|---|
| `config.py` | profil MODÉRÉ + MM petits-gains + params SMC (1 dataclass) |
| `data_feed.py` | OHLCV yfinance (1h/4h/1d) + fallback synthétique + cache parquet |
| `smc_engine.py` | ★ confirmation model déterministe → `Setup` (self-check `_demo`) |
| `money_manager.py` | sizing risque %, échelle TP, caps jour/semaine (self-check) |
| `mcp_tradingview.py` | TA distillée (lib `tradingview_ta` directe, tracké pruner) |
| `analysts.py` | 5 lentilles d'avis (Technique/Institutionnel/Sentiment/Macro/Risk) FREE |
| `jury.py` | consensus pondéré + VETO risk + gate MiroFish (self-check `_demo`) |
| `rag.py` | retrieve/index turbovec + calibration BigSet (flywheel) |
| `report.py` | rapport conseil markdown |
| `orchestrator.py` | pipeline complet `analyze(pair)` |
| `../../run_trading.py` | CLI : `--analyze PAIR` / `--selfcheck` / `--factory` (Phase 3 stub) |

## Work Guidance
- Ajouter une confluence SMC → `smc_engine.detect_setup` + étendre `_demo`.
- Ajouter un analyste → entrée dans `analysts.ROLES` (poids + brief). Le jury s'adapte.
- Biais HTF **découplé** du LTF (calculé sur la HTF df, passé à `detect_setup(bias=...)`).

## Verification
```
python run_trading.py --selfcheck            # smc_engine + money_manager (offline, 0 dép)
python run_trading.py --analyze EURUSD        # pipeline complet → rapport
```

## TODO (phases suivantes)
- Phase 3 : `alpha_factory.py` (vectorbt/optuna/quantstats, rapport HTML style MT5) + `pine_export.py`.
- Phase 4 : traduction MQL5 + exécution compte réel (HITL obligatoire).
- Sentiment réel (news/Reddit) + datasets RAG SMC (validation user avant download).
