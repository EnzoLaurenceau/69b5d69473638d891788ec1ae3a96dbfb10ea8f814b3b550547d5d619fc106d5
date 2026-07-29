# Dette technique — priorisée par impact

> Source : `swarm_audit.json` · 220 findings
> Méthode : graphe de dépendances inverse déterministe (proxy du blast radius ; gitnexus impact mesuré à 89 s/appel, inutilisable à cette échelle)

`priorité = poids(sévérité) × poids(catégorie) × (1 + log2(1 + dépendants))`

## Fichiers les plus rentables à corriger

| # | Fichier | Priorité | Findings | Dépendants |
|---|---|---|---|---|
| 1 | `09_WEB/server.py` | 127 | 28 | 0 |
| 2 | `00_CORE/forge_agents/hallucination_compare.py` | 114 | 4 | 5 |
| 3 | `00_CORE/forge_agents/token_tracker.py` | 109 | 3 | 9 |
| 4 | `00_CORE/forge_agents/agent_nodes.py` | 88 | 6 | 4 |
| 5 | `00_CORE/forge_agents/nanomachine.py` | 82 | 7 | 3 |
| 6 | `00_CORE/forge_agents/n8n_bridge.py` | 81 | 5 | 1 |
| 7 | `00_CORE/forge_agents/token_sprint_tracker.py` | 72 | 4 | 2 |
| 8 | `00_CORE/forge_agents/auto_tool_generator.py` | 60 | 6 | 1 |
| 9 | `00_CORE/forge_agents/knowledge_blender.py` | 59 | 4 | 1 |
| 10 | `scripts/recursive_optimizer.py` | 57 | 6 | 1 |
| 11 | `scripts/gitnexus_to_vault.py` | 56 | 9 | 0 |
| 12 | `00_CORE/tools/automation/browser_use.py` | 55 | 5 | 1 |
| 13 | `00_CORE/forge_agents/forge_lazy.py` | 48 | 4 | 3 |
| 14 | `00_CORE/forge_agents/memory_pruner.py` | 45 | 5 | 1 |
| 15 | `00_CORE/forge_agents/sync_history.py` | 42 | 4 | 1 |

## Top 20 findings individuels

| # | Prio | Sév. | Cat. | Emplacement | Défaut |
|---|---|---|---|---|---|
| 1 | 56.2 | CRITICAL | bug | `00_CORE/forge_agents/token_tracker.py:201` | Double comptage potentiel des économies de la session courante |
| 2 | 46.6 | CRITICAL | bug | `00_CORE/forge_agents/hallucination_compare.py:209` | Success tokens check breaks French accented characters |
| 3 | 36.3 | HIGH | silent-failure | `00_CORE/forge_agents/token_tracker.py:208` | Exception masquée dans la lecture des logs historiques |
| 4 | 36.2 | CRITICAL | silent-failure | `00_CORE/forge_agents/token_sprint_tracker.py:57` | _load_sprints silencie toute erreur JSON et renvoie [], effaçant les données historiques |
| 5 | 32.0 | HIGH | silent-failure | `00_CORE/forge_agents/forge_experience_db.py:156` | Silent exception handling in _load |
| 6 | 28.0 | CRITICAL | silent-failure | `00_CORE/forge_agents/sync_history.py:28` | Corruption de history.json silencieusement remplacé par un historique vide |
| 7 | 28.0 | HIGH | bug | `00_CORE/forge_agents/hallucination_compare.py:112` | Numeric regex misses numbers with separators or decimals |
| 8 | 27.9 | HIGH | silent-failure | `00_CORE/forge_agents/agent_nodes.py:138` | Silence l'erreur LLM et impose un rôle par défaut |
| 9 | 26.0 | CRITICAL | bug | `00_CORE/forge_agents/inference_patch.py:189` | Compression removes docstring content |
| 10 | 26.0 | CRITICAL | bug | `00_CORE/forge_agents/n8n_bridge.py:146` | export_dir ne récupère que les 4 clés premières : les autres champs (id, active, tags, e |
| 11 | 25.9 | HIGH | bug | `00_CORE/forge_agents/dataset_rag.py:168` | Missing DATASETS_ROOT existence check |
| 12 | 25.8 | HIGH | correctness-risk | `00_CORE/forge_agents/hallucination_compare.py:128` | Missing number detection skips decimal numbers in tool results |
| 13 | 25.2 | HIGH | silent-failure | `00_CORE/forge_agents/nanomachine.py:105` | File operations errors are silently ignored |
| 14 | 23.4 | HIGH | bug | `00_CORE/forge_agents/forge_lazy.py:171` | plan() ignore l'étape 2 pattern matching documentée |
| 15 | 20.2 | HIGH | bug | `00_CORE/forge_agents/forge_self_heal.py:209` | Actions contradictoires générées pour le même composant |
| 16 | 20.2 | HIGH | bug | `00_CORE/forge_agents/harness_engine.py:104` | Literal redefined as str, breaks type hint evaluation |
| 17 | 20.2 | HIGH | bug | `00_CORE/forge_agents/opt_out_manager.py:75` | Cache Redis invalidé même en cas d'échec DB |
| 18 | 20.2 | HIGH | bug | `00_CORE/trading/data_feed.py:35` | _synthetic ignores tf, always generates hourly bars |
| 19 | 19.6 | MEDIUM | correctness-risk | `00_CORE/forge_agents/forge_llm.py:78` | TOKEN_CEILING = 65 000 alors que la doc module annonce 50 000 |
| 20 | 19.2 | HIGH | security | `00_CORE/tools/automation/browser_use.py:51` | Injection de prompt via URL |

## Limites assumées

- Le blast radius est un **proxy** (imports + références de symboles), pas le graphe
  d'appels exact de GitNexus — écarté ici pour cause de latence (89 s/appel).
- Les findings viennent de MiMo : groundés (le code cité existe) et filtrés des
  artefacts de découpage, mais **non vérifiés un par un**. Priorité haute = à
  regarder en premier, pas « défaut prouvé ».
- Les poids sont des hypothèses explicites, ajustables en tête de `debt_priority.py`.