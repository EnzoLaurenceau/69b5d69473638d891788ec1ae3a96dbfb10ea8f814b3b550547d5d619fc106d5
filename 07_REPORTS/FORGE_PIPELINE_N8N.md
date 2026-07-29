# FORGE — Pipeline complet (reproduction n8n)

> Reconstruit depuis le **code réel**, pas seulement les docs.
> Source de vérité : `00_CORE/forge_agents/forge_graph.py` (le DAG LangGraph), `run_forge.py` (CLI), `agent_nodes.py`, `mirofish.py`, `forge_llm.py`, `cervelet.py`, `adaptive_rag.py`, `forge_db.py`.
> Règle appliquée : **aucune tâche décorative**. Chaque node ci-dessous map vers une fonction réelle. Colonne `Nécessité` = CORE (indispensable) / OPT (supprimable).

---

## 0. L'objet d'état (le "item" qui circule entre les nodes n8n)

Tout passe par `ForgeState` (`forge_state.py`, TypedDict). En n8n = le JSON de l'item qui traverse le workflow. Champs clés :

```
task            # tâche courante
subtasks[]      # décomposées par l'orchestrateur
session_id      # id de session (checkpoint)
cycle / level   # cycle courant, niveau L1→L4
budget_estimate # tokens estimés (estimate_budget)
budget_actual   # tokens réels (post_mortem)
findings[]      # résultats → confirmed / pending / killed
mirofish_verdict, mirofish_score
context         # injecté par graphify + openviking (adaptive_rag)
```

---

## 1. WORKFLOW A — Boucle cœur (le moteur)

DAG réel (`forge_graph.py`, entry = `estimate_budget`) :

```
        ┌─────────────────────────────────────────────────────────┐
        │                                                         (loop)
[START] → estimate_budget → orchestrator → dynamic_agent → auto_complexification
                                ↑                                   │
                                │                          route_after_complexification
                          memory_pruner ←── "encore un cycle" ──────┤
                                                                    │
                                                  "fini" ──→ post_mortem → [END]
```

Routage conditionnel exact (extrait du code) :
- `orchestrator` → `route_from_orchestrator` → `{ dynamic_agent | END }`
- `dynamic_agent` → `route_after_agent` → `{ auto_complexification | END }`
- `auto_complexification` → `route_after_complexification` → `{ orchestrator→memory_pruner | __end__→post_mortem }`

### Pré-filtre (avant le graph) — Cervelet
`cervelet.route_request` (`cervelet.py`) : réflexe Token-ID. Si la requête est triviale il répond SANS lancer le graph, sinon `ESCALATE` vers `estimate_budget`. En n8n = **node IF en tête** : `reflex hit ? → réponse directe : → entre dans le graph`.

### Table des nodes (Workflow A)

| # | Node n8n | Map → code | Input | Output | Nécessité | Pourquoi |
|---|----------|-----------|-------|--------|-----------|----------|
| 0 | **Cervelet (IF/Switch)** | `cervelet.route_request` | `task` | hit→sortie / miss→#1 | OPT | Économise le graph sur requêtes triviales. Supprimable (tout passe au graph). |
| 1 | **Estimate Budget** | `estimate_budget_node` + `token_tracker.estimate_budget` | `task` | `budget_estimate` + table | CORE | Règle TOKEN BUDGET : estimation avant toute exécution. |
| 2 | **Orchestrator** | `orchestrator_node` | `task`, `context` | `subtasks[]` | CORE | Décompose la tâche, KB intake gate + plan selection gate. Appelle le **Router LLM** (Workflow B). |
| 3 | **Dynamic Agent** | `dynamic_agent_node` | `subtask` | `finding` brut | CORE | Génère l'expert parfait (prompt+nom) à la volée et exécute. Appelle Router LLM. |
| 4 | **MiroFish Jury** | `mirofish.mirofish_gate` | `finding` | `verdict`, `score` | CORE | Jury multi-persona, score de consensus → tri confirmed/pending/killed. (appelé depuis #3) |
| 5 | **Auto-Complexification** | `auto_complexification_node` | `score`, `cycle` | décision loop, `level` | CORE | Leveling L1→L4 + décide : reboucler ou finir. C'est le contrôleur de boucle. |
| 6 | **Memory Pruner** | `memory_pruner_node` | state | state élagué | CORE* | Élague la mémoire entre cycles puis reboucle vers #2. *CORE si runs longs, OPT si 1 seul cycle. |
| 7 | **Post-Mortem** | `post_mortem_node` + `token_tracker` | `budget_actual` | rapport + efficiency score | CORE | Règle TOKEN BUDGET : actual + recommandations + score. Écrit `08_LOGS/tokens/`. |

---

## 2. WORKFLOW B — Router LLM (sous-workflow réutilisé)

`forge_llm.forge_call` — appelé par Orchestrator, Dynamic Agent, MiroFish. **Le node le plus réutilisé.** En n8n = sous-workflow appelé via *Execute Workflow*.

```
forge_call(prompt, tier|task_type)
  → tier_for_task()                      # choisit le tier
  → _enrich_with_openviking()            # injecte top-5 noeuds pertinents
  → _check_ceiling() / _check_subtask_budget()   # garde-fous budget
  → cascade :
      TIER 0 FREE  : OpenRouter/RTK → Gemini Flash → Groq → Cerebras
      TIER 1 Haiku : emails, posts, templates
      TIER 2 Sonnet: market scan, research, build
      TIER 3 Opus  : orchestration, jury, audit
  → _log_to_tracker()                    # token_tracker
```

| Node n8n | Map → code | Nécessité | Pourquoi |
|----------|-----------|-----------|----------|
| Tier Selector (Switch) | `tier_for_task` | CORE | Route coût (gratuit d'abord). |
| OpenViking enrich | `_enrich_with_openviking` | OPT | Améliore le prompt ; supprimable au prix de pertinence. |
| Budget guard (IF) | `_check_ceiling`,`_check_subtask_budget` | CORE | Stoppe si plafond dépassé. |
| FREE cascade (HTTP) | `_call_free` | CORE | Appels gratuits + fallback en chaîne. |
| Anthropic fallback (HTTP) | `_call_anthropic` | CORE | Dernier recours payant. |
| Token log | `_log_to_tracker` | CORE | Alimente estimate/post-mortem. |

> En n8n : 1 node HTTP Request par fournisseur + un node "Error Trigger / continueOnFail" pour enchaîner la cascade (provider down → suivant).

---

## 3. Mémoire & checkpoint (couche transversale)

| Node n8n | Map → code | Nécessité | Pourquoi |
|----------|-----------|-----------|----------|
| Postgres (pgvector) | `forge_db.get_db` | CORE | Store primaire (findings, vecteurs). |
| Redis | `forge_db` | CORE | Cache chaud / état réflexe. |
| SQLite fallback + WAL | `forge_db_fallback` | OPT | Secours si PG/Redis down (dual-write). |
| Checkpoint write | `graphify_checkpointer` | CORE | Écrit `05_STATE/checkpoint.json` après chaque node → permet `--resume`. |
| Adaptive context | `adaptive_rag.get_adaptive_context` | OPT | Classe la stratégie de récupération (graphify+openviking) avant prompt. |

En n8n : après **chaque** node A, un petit node "Set checkpoint" (écrit l'état) → reproduit `--resume`.

---

## 4. WORKFLOW C — Track ECOM / MVP Factory (au-dessus du moteur)

Layer documenté dans `01_ORCHESTRATOR/` (prompts) — réutilise le moteur A.

**ECOM** (`ECOM_ORCHESTRATOR.md`) : `BOOT CHECK → MARKET SCAN → PRODUCT HUNT → BUILD → LAUNCH`
Agents : MARKET / HUNTER / BUILDER / CRITIC. MCPs : Shopify, mcp-omnisearch (remplace Semrush).

**MVP Factory** (séquence projet) :
```
ESTIMATE → AUDIT HERALD → PLAN → ⏸WAIT(humain) → IMPLEMENT → RE-AUDIT HERALD → MIROFISH → DELIVER → ACTUAL
```

| Node n8n | Map | Nécessité | Pourquoi |
|----------|-----|-----------|----------|
| Estimate | token_tracker | CORE | budget avant projet. |
| Audit Herald | HTTP `localhost:3001/analyze/local` ou cloud | CORE (track MVP) | grade sécurité initial. **Blocage : grade < C → stop.** |
| Plan | orchestrator | CORE | inclut les fixes Herald. |
| ⏸ Wait | n8n Wait node (approbation) | CORE | gate humain avant implémentation. |
| Implement | dynamic_agent (+ BUILDER) | CORE | fixe issues Herald en priorité. |
| Re-Audit Herald | HTTP Herald | CORE | grade final ≥ B requis. |
| MiroFish | `mirofish_gate` (reçoit `herald_grade`) | CORE | verdict final, pénalité si grade < B. |
| Deliver | écrit `LIVRABLE.md` | CORE | livrable + rapport Herald. |
| Actual | token_tracker | CORE | post-mortem tokens. |

> **Herald n'est PAS câblé dans le moteur A** (vérifié : 0 référence herald dans `agent_nodes/forge_graph`). Il vit seulement dans ce track C, en appel HTTP externe. Ne pas l'ajouter au cœur.

---

## 5. Où s'attachent les 3 nouveaux outils

| Outil | Point d'attache n8n | Type | Note |
|-------|--------------------|------|------|
| **ponytail** | system-prompt injecté dans #3 Dynamic Agent + BUILDER (toute génération de code) | couche prompt (pas un node) | Échelle YAGNI → moins de code. Aucune suppression requise. |
| **evomap / evolver** | node **"Evolve"** après #7 Post-Mortem (Execute Command : `evolver solidify` / `distill`) | node additif | Capture la session en Genes/Capsules locales → réinjecté dans #2 Orchestrator au run suivant. Parallèle au loop Graphify existant. **Mode local-only obligatoire** (voir note). |

> **⚠️ evomap — mode local-only obligatoire.** `evolver` n'est pas qu'un outil d'auto-amélioration : c'est un **marché décentralisé à crédits** (ATP : `buy`/`orders`/`recipe --price --publish`, routing `auction|swarm`) avec un **rôle validateur ACTIF PAR DÉFAUT** (work réseau pour crédits) et un **hub qui pousse des feature-flags à distance** (mailbox). `sync`/`publish` **uploadent vos stratégies** sur leur Hub. Pour n'avoir QUE l'auto-amélioration locale :
> - Sous-process uniquement (jamais `import` → GPLv3 reste à distance).
> - `EVOLVER_VALIDATOR_ENABLED=0` (désactive le validateur réseau).
> - N'utiliser QUE `solidify` / `review` / `distill`. **Jamais** `login`, `sync`, `recipe --publish`, `buy` dans le pipeline auto.
> - Pas de `setup-hooks` (sinon il injecte ses hooks dans Claude Code).
>
> **Implémenté (mode local-only)** : `00_CORE/forge_agents/evomap_evolve.py` (wrapper sous-process : validateur OFF, subcommands `solidify`/`review`/`distill` only, no-op propre si absent). Activation : `python run_forge.py --evolve` (standalone) ou `FORGE_EVOLVE=1` (hook auto dans `post_mortem_node`). Pré-requis pour activer réellement : `npm i -g @evomap/evolver` (ou `EVOLVER_BIN=<index.js>`) **+ racine en dépôt git**.
| **kickbacks** | ❌ aucun (hors pipeline) | — | Ads dans le spinner Claude Code = UI humaine. Un pipeline n8n headless n'a pas de spinner ni d'humain → 0 impression légitime. Réserver à l'IDE perso, pas à la Forge. |

---

## 6. Notes d'implémentation n8n

- **Boucle** : n8n ne boucle pas nativement → utiliser *Loop Over Items* ou un *Execute Workflow* récursif gardé par un compteur `cycle < cycles_max` (= l'arg `--cycles`).
- **Sous-workflows** : Workflow B (Router) = 1 sous-workflow appelé partout. Évite la duplication.
- **Cascade fournisseurs** : HTTP node `onError: continueRegularOutput` → branche vers le fournisseur suivant.
- **Secrets** : clés en n8n Credentials, jamais en clair (équivaut au nopeek de la Forge).
- **Resume** : node "Set checkpoint" après chaque étape = équivalent `run_forge.py --resume`.
- **Entrée** : Webhook/Manual trigger portant `{task, session_id, cycles}` = les args `--task --session --cycles`.

---

## 7. Audit "zéro décoration" — ce qui est supprimable

| Supprimable (OPT) | Conséquence si retiré |
|-------------------|----------------------|
| Cervelet (#0) | Tout passe par le graph (plus de tokens sur trivial). |
| Memory Pruner (#6) si 1 cycle | OK pour runs courts. |
| OpenViking enrich (B) | Prompts moins ciblés. |
| SQLite fallback | Pas de secours si PG/Redis tombe. |
| Adaptive RAG | Récupération de contexte plus naïve. |

**Indispensables (ne pas retirer)** : estimate_budget, orchestrator, dynamic_agent, mirofish, auto_complexification, post_mortem, Router LLM (cascade + budget guard + log), Postgres, Redis, checkpoint.

---

## 8. Outils projet — CRM + catalogue d'apps (bibliothèque `00_CORE/tools/`)

Branchés sur le track C (BUILD / IMPLEMENT). Manifeste : `00_CORE/tools/registry.json` · doc : `00_CORE/tools/TOOLS.md`.

| Outil | Node n8n | Map → code | Usage |
|-------|----------|-----------|-------|
| **Twenty CRM** | Execute Command (docker) + HTTP (GraphQL) | `tools/twenty_crm.py` (`prepare`/`up`/`graphql`/`down`) | Provisionne un CRM isolé par projet qui en a besoin. **AGPL-3.0** → contrainte revente (voir TOOLS.md). |
| **App catalog** | HTTP (GitHub) + cache JSON | `tools/app_catalog.py` (`search`/`fetch_app_readme`) | MVP Factory : trouver/combiner/adapter un template vendable. Query on-demand (règle #1), jamais de dump. |

Flux : `app_catalog.search(besoin)` → shortlist → `fetch_app_readme` → choisir/combiner/adapter → si CRM requis `twenty_crm.prepare()+up()` + schéma GraphQL → **vérifier licences (AGPL Twenty + deps des sous-apps) avant vente**.
