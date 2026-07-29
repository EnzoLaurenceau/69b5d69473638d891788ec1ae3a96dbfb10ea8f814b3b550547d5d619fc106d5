# Triage — Session GPT « Forge cognitive et produits » (2026-07-22)

> Source : `09_TASKS/queue/Forge cognitive et produits (2026-07-22).md`
> Méthode : chaque proposition GPT confrontée à l'état RÉEL du dépôt (code lu, pas déclaratif).
> Verdicts : ✅ DÉJÀ LÀ · 🟡 PARTIEL · 🔴 GAP RÉEL · ⛔ REJET

---

## 0. Constat majeur (à lire en premier)

GPT recommande, comme différenciateur n°1, l'**édition minimale / Edit Planner / MCPT**.
**La Forge a déjà ce module** : `00_CORE/forge_agents/semantic_edit_engine/` (8 modules, 728 lignes, Phase 1 déclarée livrée le 2026-07-18).

Sauf que la lecture du code donne trois faits durs :

| Fait | Preuve |
|---|---|
| Le module est **orphelin** | `semantic_edit_engine` n'est importé que par `test_see.py` et `forge_agents/__init__.py`. Zéro nœud du graph, zéro agent, zéro hook l'utilise. |
| Le cœur est un **stub** | `patch_optimizer.py:50-51` — la seule "stratégie" est `if "timeout" in instruction: re.sub(r"process_request\(.*?\)", ...)`. Il n'y a **aucune génération multi-stratégie**, donc aucun choix de coût minimal. |
| Le `UPGRADE_ROADMAP.md` **sur-déclare** | Il annonce « SemanticPatchOptimizer multi-stratégie » et « EditMetrics 18 métriques » ; le fichier fait 65 lignes et l'optimizer en produit une seule, hardcodée. |

Ce qui EST réel dans SEE : `patch_scorer.py` (6 critères pondérés, fonctionnel), `symbol_resolver.py`, `auto_rollback.py`, `patch_memory.py`, `context_window.py`.

➡️ **Conclusion** : la bonne action n'est pas « implémenter l'idée de GPT », c'est **finir et câbler ce qui existe déjà**. Le différenciateur est à 80 % écrit et à 0 % utilisé.

---

## 1. Triage des 10 propositions

| # | Proposition GPT | Verdict | État réel dans la Forge | Action |
|---|---|---|---|---|
| 1 | Compréhension instantanée d'un dépôt Git | ✅ DÉJÀ LÀ | GitNexus (83 150 symboles / 111 561 relations / 300 flux) + `query`/`context`/`explain` + graphify + `forge_search_engine.py` | Rien à coder. **Produitiser** (exposer en service, pas en MCP local) |
| 2 | Modification de code sûre (diff + tests + PR) | 🟡 PARTIEL | `auto_rollback.transactional_edit` OK, harness_engine OK ; **pas** de boucle patch→tests→PR | ✅ GO — WAVE 2 |
| 3 | Détection auto de dette technique | 🟡 PARTIEL | `ponytail-audit`, `code-modernization:*`, `security-review` existent en skills manuels ; pas de scan périodique ni de priorisation | ✅ GO — WAVE 3 (daemon + score) |
| 4 | Mémoire persistante du projet | ✅ DÉJÀ LÀ | `forge_experience_db.py`, `patch_memory.py`, `shared_context.json`, graphify, mémoire fichier `~/.claude/.../memory/` | Rien à coder |
| 5 | Observabilité IA (temps/LLM/coût/tokens/latence/qualité) | ✅ DÉJÀ LÀ | `forge_metrics.py` → `05_STATE/forge_metrics.jsonl` (tokens in/out/inference, latence, coût, score hallucination), `forge_observability.py` (LangSmith), `token_tracker`, dashboard :7777 | Rien à coder. Manque juste la **vue "par tâche"** (WAVE 3) |
| 6 | Analyse d'impact avant modification | ✅ DÉJÀ LÀ | GitNexus `impact()` + règle CLAUDE.md bloquante | Rien à coder |
| 7 | Optimisation auto des coûts IA | ✅ DÉJÀ LÀ | `forge_llm` (tiers), `forge_fingerprint` (zero-redundancy gate), `semantic_cache`, MimoBatcher, RTK | Rien à coder |
| 8 | **Édition incrémentale / patch minimal** | 🔴 **GAP RÉEL** | Scaffolding présent, cœur stubbé, non câblé (cf. §0) | ✅ **GO — WAVE 1, priorité absolue** |
| 9 | Dashboard santé du dépôt | 🟡 PARTIEL | Dashboard :7777 montre la santé de la *Forge*, pas celle d'un *dépôt client* | ✅ GO — WAVE 3 |
| 10 | Agent de revue de code sur PR | 🟡 PARTIEL | `/code-review`, Herald, `security-review` en local ; pas de bot PR | ⏸ DIFFÉRÉ — dépend d'un vrai produit hébergé |

### Idées transverses

| Idée | Verdict | Justification |
|---|---|---|
| **Edit Planner** (lister stratégies → scorer → choisir) | ✅ GO | C'est exactement le trou de `patch_optimizer.optimize()`. `PatchScorer` est déjà là pour scorer. |
| **MCPT** (Minimum-Cost Program Transformation) comme principe fondateur | ✅ GO (cadrage) | À formaliser dans un blueprint + à généraliser plus tard (prompts, configs, KG). Le code d'abord, la théorie ensuite. |
| Bibliothèque de 13 primitives d'édition | ⛔ RÉDUIT | YAGNI/ponytail. 4 primitives couvrent >90 % des cas : `Replace(anchor)`, `InsertAfter`, `DeleteRange`, `ReplaceSymbolBody`. Les 9 autres (MoveFunction, ExtractMethod…) sont des refactos, pas des éditions. |
| Niveau 3 « moteur sémantique » complet | ⏸ DIFFÉRÉ | Phase 3+ du roadmap SEE. Sans Niveau 1/2 fonctionnels c'est du vide. |
| Reconstruire une observabilité type LangSmith | ⛔ REJET | Déjà branché sur LangSmith + métriques maison. Redondance pure. |
| Concurrencer Cursor / Windsurf sur la génération de code | ⛔ REJET | GPT le dit lui-même : objectif très coûteux, hors thèse. |
| Positionnement / analyse concurrentielle | ✅ GO (doc, pas code) | Livrable `POSITIONING.md` — utile pour trancher le périmètre produit |

---

## 2. Ce que ce triage change dans la stratégie

GPT conclut : « viser la meilleure *transformation*, pas le meilleur *code* ».
C'est cohérent avec l'architecture existante — et c'est déjà la brique la plus avancée **sur le papier** et la plus creuse **dans le code**.

Le risque identifié par GPT (« 10 briques excellentes, aucune indispensable ») se vérifie ici sous une forme précise :
**la Forge a 10 briques déclarées, dont au moins une est déclarée livrée sans l'être.** Le premier travail est un travail de vérité, pas d'ajout.

---

## 3. Sortie

→ Kanban d'exécution : `09_TASKS/KANBAN_FORGE_PRODUCT.md` + `05_STATE/kanban/forge_product_board.json`
