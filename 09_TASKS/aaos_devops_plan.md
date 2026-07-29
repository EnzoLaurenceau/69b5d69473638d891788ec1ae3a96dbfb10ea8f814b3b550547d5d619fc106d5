# Plan Dev/DevOps — vague AAOS (items 59–102) — 2026-07-16

> **Statut : ✅ EXÉCUTÉ (2026-07-16).** Les 16 gaps TODO sont implémentés et vérifiés
> (6/6 checks `00_CORE/test_aaos_wave.py`, self-checks modules OK, endpoint testé 200) :
> - `forge_agents/forge_fingerprint.py` (NOUVEAU) → 63/64/65/78/79/87
> - `forge_llm.forge_call()` → gate zero-redundancy TOUS tiers + record empreinte
> - `token_tracker.py` → add_saving()/savings_summary() (84), inclus au rapport final
> - `dataset_rag.py` → health_check/policy (94/95/96), dataset_memory (100),
>   regression_guard+benchmark_retrieval (101), record_knowledge_gap (92/98)
> - `agent_nodes.dynamic_agent_node` → trigger score<5.0 → knowledge_gaps.json (92,
>   sans téléchargement auto — protocole DATASETS respecté)
> - `forge_system_registry.SystemNode` → budgets/provider/cache_policy (59)
> - `09_WEB/server.py` → GET /api/aaos_metrics (88/68 : cache, savings, CPU/RAM, gaps)
> Kill switch : env FORGE_FINGERPRINT_OFF=1. Reste ouvert : brancher neural_map.html
> sur /api/aaos_metrics (visuel), et les ⏭️ SKIP ci-dessous si un besoin concret apparaît.

> Objectif : faire évoluer la Forge vers un AI Agent Operating System (AAOS).
> Priorité #1 validée : cache intelligent + réutilisation des résultats (impact coûts/latence/scalabilité/UX).
> La map Three.js consomme ensuite les métriques produites — elle ne bloque rien.
> Règle : DO NOT INVENT — chaque item est d'abord mappé sur l'existant avant tout dev.

## Légende
- ✅ EXISTE — déjà couvert par un module, ne pas re-développer (au plus : câbler/exposer)
- 🔨 TODO — gap réel, à développer
- ⏭️ SKIP — YAGNI, réévaluer seulement si un besoin concret apparaît

## Phase 1 — Cache intelligent & zero-redundancy (PRIORITÉ)

| # | Tâche | Statut | Détail |
|---|---|---|---|
| 62 | Semantic result cache (>95% similarité → hit) | ✅ EXISTE | `semantic_cache.py`, `forge_cache_orchestrator.py`, `lmcache_integration.py`, câblé dans `forge_llm.py` (`optimized_check_cache/store_cache`) |
| 63 | Execution fingerprint (task_hash+input_hash+versions+result+cost+latency) | 🔨 TODO | Nouveau module léger persistant dans `forge_experience_db.py` ; consulté AVANT tout appel. Chaînon manquant cache→inter-sessions |
| 64 | Zero-redundancy execution (même tâche+contexte+version → 0 appel LLM) | 🔨 TODO | = fingerprint (63) branché en gate dans le cervelet, devant TOUS les tiers (pas seulement FREE) |
| 65 | Context deduplication (chunks/prompts/docs/embeddings identiques) | 🔨 TODO (partiel) | Hash exact via fingerprint ; dédup embeddings via turbovec existant |
| 79 | Task classifier (requires_reasoning / can_be_scripted / can_be_cached / can_run_locally) | 🔨 TODO | Score déterministe (regex+heuristiques, 0 token) dans `cervelet.py` avant `forge_call` |
| 87 | Cost comparison engine (LLM vs local vs OSS vs cache) | 🔨 TODO | Sortie du classifier (79) + coûts de `token_tracker.py` — même module |
| 84 | Token Efficiency compteurs (tokens_saved / money_saved / latency_saved) | 🔨 TODO | Champs additionnels dans `token_tracker.py`, exposés au dashboard |

**Ordre de build Phase 1 : 63 → 64 → 79/87 → 84 → 65.**

## Phase 2 — Token Last Architecture (76–90)

| # | Tâche | Statut | Détail |
|---|---|---|---|
| 76 | Token Last Principle (ordre : algo local → script → regex → DB → cache → règles → petit modèle → OSS → API free → LLM) | ✅ EXISTE (à formaliser) | Cervelet `route_request` réflexe + `forge_lazy.py` + hiérarchie RTK/free. TODO : encoder l'ordre explicite dans le cervelet via le classifier (79) |
| 77 | Automation Discovery Agent (ADA) | ✅ EXISTE (catalogues) | `osint_arsenal.pick()`, `public_apis.search()`, `oss_saas.py`, `registry.json`. Le scan "continu" est ⏭️ SKIP — pick() à la demande suffit |
| 78 | Automation Replacement Engine | 🔨 TODO | Détection tâche répétitive via fingerprint (63) : N hits similaires → proposer script/outil. Petit, dépend Phase 1 |
| 80 | Automation Catalog (Task → OSS → script → modèle local → LLM) | ✅ EXISTE | `00_CORE/tools/registry.json` + catalogues turbovec |
| 81 | Script Developer Agent | ✅ EXISTE | OpenHands (étape IMPLEMENT) + règle #5 wrappers micro-scripts. Rien à créer |
| 82/83 | Self-hosted first / local inference (ONNX, llama.cpp, petits modèles) | ⏭️ SKIP (pour l'instant) | RTK+free tiers couvrent le besoin coût. Réévaluer si quota free saturé — alors brancher llama.cpp dans `forge_llm.py` comme tier -1 |
| 85 | Open Source Scanner permanent (GitHub/HF/PyPI/npm/arXiv) | ⏭️ SKIP | Recherche à la demande (règle DO NOT INVENT) suffit ; un scanner permanent = coût sans demande |
| 86 | Automatic tool integration (benchmark→sandbox→validation→intégration) | ✅ EXISTE (process) | Process manuel actuel : wrapper + self-check + registry + gitnexus analyze. Pas d'automatisation supplémentaire |
| 88 | Local Compute Dashboard (CPU/RAM/GPU + tokens/dollars économisés) | 🔨 TODO | Étendre `09_WEB` dashboard avec compteurs de 84 + psutil. Après Phase 1 |
| 89/90 | Self-improving automation loop / transformer token cost en CPU cost | ✅ EXISTE (boucle) | `forge_meta.py` + `forge_experience_db.py` (boost post-exécution). L'objectif 90 = résultat des phases 1-2, pas une tâche |

## Phase 3 — Data Acquisition & Dataset Quality (91–102)

| # | Tâche | Statut | Détail |
|---|---|---|---|
| 92 | Quality threshold (quality/confidence < 0.5 → déclencher DAA) | 🔨 TODO | Brancher `forge_score` < 0.5 en sortie de `dynamic_agent_node` → trigger `dataset_rag.py`. Le pipeline existe, seul le trigger manque |
| 91/93 | Data Acquisition Agent + pipeline discovery | ✅ EXISTE | `dataset_rag.py` (nouveau), `kb_manager.py`, protocole DATASETS (CLAUDE.md : prévenir user avant download, ingérer via turbovec) |
| 94/95 | Dataset health check + quality score pondéré | 🔨 TODO | Fonction `health_check(dataset)` dans `dataset_rag.py` : completeness, dupes, missing, licence, freshness → score 0-100 |
| 96 | Acceptance policy (≥80 accepté / 60-80 quarantaine / <60 rejeté) | 🔨 TODO | 10 lignes dans le même module, seuils configurables |
| 97 | Dataset sandbox (scan, licence, dédup, format) avant ingestion | 🔨 TODO (partiel) | = health_check (94) + le protocole "prévenir user" existant. Scan antivirus ⏭️ SKIP (Defender fait le travail) |
| 98 | Knowledge gap detector | ✅ EXISTE (approx) | OpenViking retrieve + findings pending ; le trigger 92 le concrétise |
| 99/102 | Self-improvement loop échec→données→réévaluation | ✅ EXISTE (boucle) | experience_db + boost_node ; complété par 92 |
| 100 | Dataset memory (id, source, score, licence, perf_gain, usage) | 🔨 TODO | Table/JSON dans `07_KNOWLEDGE_BASE/datasets/` — schéma déjà amorcé par `dataset_rag.py`, ajouter quality_score + usage_count |
| 101 | Regression guard (nouveau dataset ne dégrade pas les benchmarks) | 🔨 TODO | Bench avant/après ingestion via `forge_score` sur un set de questions fixes ; rollback si régression |
| — | Dataset Curator Agent (second agent) | ⏭️ SKIP | Redondant : 94-96-100-101 couvrent la curation sans agent dédié |

## Phase 4 — Infra agents & observabilité (59–75)

| # | Tâche | Statut | Détail |
|---|---|---|---|
| 59 | Agent Registry industriel (YAML : provider/fallback/budgets/cache_policy) | 🔨 TODO (léger) | Étendre `forge_system_registry.py` avec les champs budget/latence/cache_policy par agent. Pas de nouveau système |
| 60 | Agent Lifecycle Manager (DISCOVER→…→DESTROY) | ⏭️ SKIP | Les agents = prompts générés à la volée, pas des process. Rien à warmup/hiberner |
| 61 | Agent Pools hot/warm/cold | ⏭️ SKIP | Même raison. Le boost/experience_db joue déjà le rôle de "warm" |
| 66 | Hippocampe mémoire partagée obligatoire | ✅ EXISTE | `forge_shared_brain.py` + `turbovec_brain.py` + `forge_db.py` (PG+Redis) |
| 67 | Event Bus (AgentCreated, TaskStarted, …) | ✅ EXISTE | `forge_event_bus.py` + `08_LOGS/events/live.jsonl` |
| 68 | Knowledge Map 3D nodes enrichis (latency/cost/tokens/health) | 🔨 TODO | `neural_map.html` consomme les métriques Phase 1 (fingerprint + token_tracker). APRÈS Phase 1 |
| 69 | Édition temps réel <500ms depuis la map | ⏭️ SKIP | Coût élevé, besoin non démontré. Édition = fichiers registry, pas la map |
| 70 | GitNexus dans la map 3D | 🔨 TODO (basse prio) | Le graph GitNexus existe ; l'exposer à neural_map = endpoint JSON |
| 71 | Time travel graph | ✅ EXISTE | `forge_checkpoint_engine.py` + `checkpoint_chain.jsonl` + checkpoints horodatés. Le replay visuel = extension de 68 |
| 72 | Performance Governor + 7 sous-agents | ✅ EXISTE (consolidé) | `forge_meta.py` + `forge_self_heal.py` + `token_tracker.py`. ⏭️ SKIP la décomposition en 7 agents — sur-ingénierie |
| 73 | Boucle horaire self-improving (collect→benchmark→apply→rollback) | ⏭️ SKIP | boost_node post-exécution fait déjà ce rôle par tâche ; une boucle horaire brûle du compute sans signal |
| 74 | Safety guardrails auto-optimisation | ✅ EXISTE | `forge_no_mistakes.py` + budgets `token_tracker` + HITL rule (CLAUDE.md) |
| 75 | Objectif AAOS | — | Vision cible, pas une tâche |

## Récap TODO (ordre d'exécution global)

1. **63/64** Execution fingerprint + gate zero-redundancy dans cervelet ← démarrer ici
2. **79/87** Task classifier + cost comparison (déterministe, 0 token)
3. **84** Compteurs tokens_saved dans token_tracker
4. **92** Trigger quality<0.5 → dataset_rag
5. **94/95/96** Dataset health check + score + policy
6. **100/101** Dataset memory + regression guard
7. **59** Champs budget/cache_policy dans system_registry
8. **65/78** Dédup contexte + replacement engine (dépend fingerprint)
9. **88/68/70** Dashboards + map 3D enrichie (consomme les métriques 1-3)
