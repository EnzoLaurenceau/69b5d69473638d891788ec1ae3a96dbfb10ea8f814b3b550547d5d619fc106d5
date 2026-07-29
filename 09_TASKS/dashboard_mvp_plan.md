# Plan MVP — Forge Dashboard Multi-Agent (Jarvis Mode)
> Brief d'implémentation pour Claude Code CLI (modèle **Fable 5** — `claude --model claude-fable-5`). Pas de code ici, uniquement le plan.
> Base : le prompt maître du .md fourni (14 sections). Ce document reprend **chaque section 1-14 telle quelle** et tranche : ce qui est déjà construit dans la Forge, ce qui rentre dans le MVP, ce qui est repoussé en V2 — et pourquoi.
> **Emplacement cible : `C:\Users\Enzo\Documents\DASHBOARD`** — projet séparé du Forge (`.claude`), actuellement vide. Voir section 0 ci-dessous pour ce qui doit y être copié et pourquoi.

## 0. Séparation physique — DASHBOARD devient un projet standalone

Le dashboard ne vit plus dans `.claude/00_CORE/forge_agents/`. Il devient son propre dossier/repo (`DASHBOARD/`), mais garde **la même intelligence** : même format d'events (NMP), même accès mémoire (Postgres+Redis), même harness, même LLM router. Le principe qui rend ça possible sans dupliquer les données : Postgres et Redis tournent déjà en localhost sur des ports réseau (`docker-compose.yml` : Postgres `:5433`, Redis `:6380`) — donc **le cerveau reste partagé via le réseau, seul le code applicatif est dupliqué**.

### 0.1 Fichiers à copier tels quels dans `DASHBOARD/backend/` (l'intelligence)
| Fichier source (`.claude/00_CORE/forge_agents/`) | Rôle | Pourquoi il doit être copié |
|---|---|---|
| `forge_db.py` | Accès Postgres+Redis (L0/L2/L3), fallback+WAL | Sans lui, DASHBOARD n'a plus de mémoire |
| `semantic_cache.py` | `_tokenize`/`_simhash`, dépendance directe de `forge_db.py` | Import obligatoire, sinon `forge_db.py` casse |
| `forge_state.py` | `ForgeState`, `Finding`, `NMPPacket` (types stricts) | Pour parser les events/checkpoints dans le même format que le Forge |
| `forge_event_bus.py` | Format `ForgeEvent`, types d'events | Pour afficher les events sans réinventer le schéma |
| `forge_llm.py` | Routing RTK→Gemini→Groq→Cerebras→Claude | Utilisé par `/api/chat` existant + futur classifieur `role_tag` |
| `harness_engine.py` | Grades qualité (Lint/Tests/Security/Perf) | Pour afficher les badges harness dans le dashboard |
| `dashboard_server.py` | Le serveur FastAPI lui-même | Devient le point d'entrée de `DASHBOARD/backend/` |
| `forge_dashboard.html` | Le front | Devient `DASHBOARD/frontend/forge_dashboard.html` |

**Ne PAS copier** : `agent_nodes.py`, `forge_graph.py`, `prompt_architect.py`, `mirofish.py`, `auto_complexification.py` — c'est le moteur d'exécution des agents, il continue de tourner **uniquement** depuis `.claude/run_forge.py`. DASHBOARD observe et déclenche via API, il ne réimporte jamais le graphe LangGraph. C'est ce qui garde les deux systèmes vraiment séparés (pas un fork du Forge).

### 0.2 Configuration à dupliquer (sous-ensemble de `.env`, pas tout)
Copier dans `DASHBOARD/.env` uniquement : `DATABASE_URL`, `REDIS_URL`, `GOOGLE_AI_STUDIO_KEY`, `GROQ_API_KEY` (tiers FREE de `forge_llm.py`), et la clé Claude utilisée par `/api/chat`. **Ne pas copier** : `DS2API_*`, `FIRECRAWL_API_KEY`, `WEB_SECRET` — inutilisés par le dashboard, aucune raison de dupliquer une clé sensible non nécessaire.

### 0.3 Point ouvert à trancher : dépendance à `checkpoint.json`
`dashboard_server.py` lit aujourd'hui `checkpoint.json` en fichier local (`FORGE_ROOT / "05_STATE" / "checkpoint.json"`). Une fois DASHBOARD séparé, deux options :
- **Option MVP (retenue)** : `DASHBOARD/.env` ajoute `FORGE_CHECKPOINT_PATH=C:\Users\Enzo\Documents\MODELS\.claude\05_STATE\checkpoint.json` — chemin en dur, fonctionne tant que les deux dossiers restent sur la même machine (c'est le cas ici).
- **Option V2** : migrer complètement la lecture vers `forge_db.hot_get()`/Postgres (le Forge écrirait son état dans Redis/Postgres au lieu d'un fichier local) — plus propre, découplage total, mais du dev réel, pas un simple copier-coller.

### 0.4 Tickets de migration (à exécuter EN PREMIER, avant les tickets 1-10 de la section Exécution)
1. Créer `DASHBOARD/backend/` et `DASHBOARD/frontend/`.
2. Copier les 8 fichiers de la table 0.1. Adapter les imports : dans `.claude` ce sont des imports de package (`from .forge_llm import ...`, `from forge_agents.forge_db import ...`) ; dans `DASHBOARD/backend/` (dossier plat, pas un sous-package du Forge) ils deviennent des imports locaux (`from forge_llm import ...`). Réécriture d'imports uniquement, **zéro changement de logique**.
3. Créer `DASHBOARD/.env` (sous-ensemble section 0.2) + `DASHBOARD/requirements.txt` (sous-ensemble : `fastapi`, `uvicorn[standard]`, `redis`, `psycopg[binary]`, `langchain-anthropic` — pas besoin de `langgraph`/`langgraph-checkpoint-postgres`, DASHBOARD n'exécute pas de graphe).
4. Ajouter `FORGE_CHECKPOINT_PATH` (section 0.3) dans `DASHBOARD/.env`.
5. Vérifier `uvicorn dashboard_server:app --port 7420` démarre depuis `DASHBOARD/backend/` sans erreur d'import, et que `/api/health` répond avec Postgres+Redis connectés (mêmes instances que le Forge, données déjà présentes visibles immédiatement).
6. `npx gitnexus analyze` sur `DASHBOARD` une fois peuplé — nouveau projet, index séparé de celui de `.claude`.
7. Dans `.claude` : supprimer `dashboard_server.py`/`forge_dashboard.html`/`forge_visualizer.py` de `00_CORE/forge_agents/` (ou les déplacer vers `09_ARCHIVE/`) une fois DASHBOARD confirmé fonctionnel — évite d'avoir deux dashboards qui tournent en parallèle (même piège que le doublon `forge_visualizer.py` déjà identifié).

**Après cette migration**, tous les tickets 1-10 de la section "Exécution" plus bas s'appliquent sur les fichiers copiés dans `DASHBOARD/backend/` / `DASHBOARD/frontend/` — plus jamais sur `.claude/00_CORE/forge_agents/`. Le Forge (`.claude`) redevient uniquement le moteur d'exécution des agents ; DASHBOARD devient le cortex visuel, séparé, qui lit le même cerveau (Postgres/Redis) par le réseau.

## Correction par rapport à l'échange précédent

Le plan précédent sous-estimait ce qui existe déjà. Après relecture du code réel (`agent_nodes.py`, `forge_state.py`, `harness_engine.py`, `semantic_cache.py`, `prompt_architect.py`), la Forge n'est pas juste "un dashboard à patcher" — **le système nerveux du prompt maître existe déjà à 60-70% côté backend**, il n'est juste pas visible (pas de cortex visuel). Le MVP n'est donc pas "construire le multi-agent" mais **rendre visible et connecté ce qui tourne déjà**, plus combler 3-4 trous précis. C'est plus fidèle à ta vision que le lot précédent, qui traitait ça comme de simples ajouts de features.

## Table de correspondance section par section (prompt maître → réalité code)

### 1. Système global (Supervisor + Workers, event-driven, state typé, event sourcing)
- **Déjà là** : `agent_nodes.py` = `orchestrator_node` (supervisor) + `dynamic_agent_node` (worker) sur un `StateGraph` LangGraph. `forge_state.py` = `ForgeState` (TypedDict strict, zéro dict libre). Chaque node émet un `NMPPacket` via `_nmp_emit()` (ligne 118-125 `agent_nodes.py`), append-only dans `state["nmp_log"]`.
- **MVP** : rien à construire ici — vérifier juste que `_nmp_emit` est appelé sur **tous** les nodes du graphe (`forge_graph.py`, 8 nodes), pas seulement `orchestrator_node`. Audit, pas dev.
- **V2** : event store véritablement immuable (actuellement `nmp_log` vit dans `checkpoint.json`, donc écrasable) — migrer vers `forge_db.deep_insert()` en table append-only.

### 2. Mémoire multi-layer (L0-L4)
- **Déjà là** : L0 Redis = `forge_db.hot_get/hot_set`. L2 Postgres = `forge_db.deep_insert/deep_query`. L3 sémantique = `forge_db.deep_semantic()` + `semantic_cache.py` (simhash, pas d'API payante). L4 Knowledge Graph = GitNexus (19072 symboles déjà indexés sur ce projet).
- **MVP** : exposer ces 4 couches en lecture dans le Memory Explorer (Vue 4). Aucune nouvelle couche à écrire.
- **V2** : L1 "Session Memory" comme store dédié (pour le MVP, `ForgeState` + `checkpoint.json` en mémoire fait déjà ce rôle, pas besoin d'une 5e table).

### 3. Cache system
- **Déjà là** : `semantic_cache.py` (cache sémantique), `forge_kernel.py` = extraction de Kernel (core_intent/entities/constraints) qui joue déjà le rôle de "context router obligatoire avant agent call".
- **MVP** : afficher le cache-hit-rate (déjà calculable depuis les events `MCP_CACHE_HIT`/`MCP_CACHE_MISS` prévus dans `forge_event_bus.py`) dans un badge dashboard.
- **V2** : invalidation par event plutôt que TTL/staleness (actuellement pas de véritable invalidation event-driven).

### 4. Snapshot Engine
- **Déjà là** : `checkpoint.json` (snapshot complet, pas différentiel) + `forge_experience_db.py` (proche d'un BigSet d'expériences).
- **MVP (volontairement minimal)** : append `checkpoint.json` complet dans `08_LOGS/snapshots/YYYYMMDD_HHmm.json` toutes les 2 interactions user↔IA (ta règle). **Pas de diff compressé** — ton propre échange avec ChatGPT signale que "snapshot tout toutes les 2 réponses sans filtre" coûte cher ; on le fait quand même en MVP mais on l'écrit noir sur blanc comme dette assumée, pas cachée.
- **V2** : la vraie version ("checkpoint incrémental, delta uniquement, state critique + memory delta + graph changes + metrics delta") — c'est un morceau de dev à part entière (diff engine), pas un MVP.

### 5. Multi-Agent System — **le point de friction, tranché explicitement**
- Ton prompt maître veut 9 agents **nommés fixes** (Orchestrator, Architecture, Backend, Frontend, DevOps, Security, Token Optimization, Validator, Memory).
- La Forge actuelle fait l'inverse par design : **un seul** `dynamic_agent_node` qui fait générer son prompt-système à la volée par `prompt_architect.py` (10 sections, sur mesure par tâche) — zéro rôle statique.
- **Ces deux approches ne sont pas incompatibles si on les relie correctement** : on ajoute un champ `role_tag` (une des 9 catégories) au Kernel/ForgeState, rempli automatiquement par un classifieur cheap (`forge_call(tier=FREE)`, une ligne : "classe cette tâche dans une des 9 catégories"). L'agent reste dynamique (nom + prompt uniques par tâche), mais **le dashboard l'affiche sous son rôle canonique** dans la Neural Map (couleur/cluster = `role_tag`). Tu obtiens visuellement "9 rôles multi-agent" sans perdre l'efficacité de la factory dynamique (pas de 9 agents qui tournent à vide en permanence, pas de 9x coût token).
- **MVP** : ajouter `role_tag` (9 valeurs enum) au state, peuplé par le classifieur FREE tier, affiché en couleur dans le graphe.
- **V2** : agents persistants dédiés par rôle avec leur propre mémoire/config si un rôle devient un vrai goulot (ex : si Security devient assez sollicité pour justifier un agent permanent plutôt que spawné).

### 6. File Lock System
- **Déjà là** : rien de câblé (recherche confirmée, aucun lock file trouvé dans le code).
- **MVP minimal** : une clé Redis `lock:<filepath>` via `forge_db.hot_set(key, agent_id, ttl=300)` posée avant tout `Write`/`Edit` d'un agent, vérifiée avant écriture, libérée après. Pas de rollback automatique (dépend du Snapshot Engine V2).
- **V2** : lock + validation Validator Agent + tests obligatoires avant unlock + rollback par snapshot diff.

### 7. Loop Engineering (Observe→Compress→Route→Diagnose→Consensus→RCA→Plan→Patch→Harness→Validate→Snapshot→Iterate)
- **Déjà là** : le graphe LangGraph (`forge_graph.py`, 8 nodes) couvre déjà Observe/Route/Diagnose/Patch. `mirofish.py` (jury) couvre Consensus Validate.
- **MVP** : dans la Neural Map, labelliser chaque node existant avec son stage de la loop (visuel seulement, pas de nouveau moteur).
- **V2** : Root Cause Analysis et Plan Repair comme nodes distincts (actuellement fusionnés dans `dynamic_agent_node`).

### 8. Harnesses de validation
- **Déjà là** : `harness_engine.py` existe déjà et couvre Code (Lint+Tests+Security+Performance), Website (Lighthouse+A11y+SEO), Bot, Email — par `ArtifactType`. `mimo_token_tracker.py` couvre le token cost analysis.
- **MVP** : brancher `HarnessEngine().validate()` sur le résultat de chaque tâche et afficher le grade dans le dashboard (badge, comme le `herald_grade` déjà prévu dans CLAUDE.md). Pas de nouveau check à écrire.
- **V2** : le check "architecture validation" + "UX/UI consistency" (pas encore dans `harness_engine.py`, à ajouter si besoin réel apparaît).

### 9. Dashboard Jarvis — les 4 vues (**c'est le vrai livrable visuel du MVP**)

| Vue | MVP | V2 |
|---|---|---|
| **Neural Map** | Graphe `vis-network` (CDN, zéro build) sur `_NODES`/`_EDGES` existants + agents dynamiques colorés par `role_tag` (section 5) + pulse en direct sur le node actif via SSE réel (pas poll 2s, cf section 1) | Clustering multi-dimension fichiers/services/mémoire, drag-and-drop |
| **Pipeline Analyzer** | Lecture seule : clic sur un node → dernières métriques réelles (`/api/live`) | Steps éditables + replay d'exécution |
| **Event Stream** | Flux `OP_CODE\|SOURCE\|PAYLOAD` — **déjà généré** par `_nmp_emit()`, juste mal exposé (actuellement lu depuis `checkpoint.json` au lieu d'un flux poussé) → MVP = pousser chaque `_nmp_emit` directement en SSE au lieu d'attendre le prochain write de checkpoint | Filtrage/recherche dans l'historique complet |
| **Memory Explorer** | Recherche sémantique (`forge_db.deep_semantic`) sur L2/L3, statut L0/L4 (`forge_db.health()`) | Diff historique de snapshots (dépend du Snapshot Engine V2) |

### 10. Communication rules (zéro langage naturel entre agents)
- **Déjà là** : le format NMP (`ACTION|SOURCE|TARGET|PAYLOAD`) est déjà strict et déjà utilisé par tous les `_nmp_emit()`. C'est la partie la plus mûre du prompt maître dans le code actuel.
- **MVP** : rien à construire, juste s'assurer que l'Event Stream (section 9) n'affiche QUE des NMP packets, jamais de prose brute de checkpoint.

### 11. Token Optimization Rules
- **Déjà là** : `forge_llm.py` (routing RTK→Gemini→Groq→Cerebras→Claude), `mimo_token_tracker.py`.
- **MVP** : afficher le tracker existant dans le dashboard (déjà quasi prêt via `/api/live` → `token_estimate`/`token_actual`).
- **V2** : "reuse agent si ≥80% match" — nécessite une similarité contre `forge_experience_db.py`, logique réelle à écrire, pas juste un affichage.

### 12. Sécurité & CVE
- **Déjà là** : `pentest_datasets.py`, `cvelistV5-main/` (base CVE déjà présente).
- **MVP** : badge lecture seule (nombre de CVE connues pertinentes) dans le header dashboard.
- **V2** : gate bloquant avant commit (nécessite d'être branché dans le harness de la section 8).

### 13-14. Objectif final / résultat attendu
Le MVP est une **coupe verticale fine à travers toutes les couches** (mémoire, agents, events, harness, sécurité) plutôt qu'une profondeur complète sur une seule. C'est exactement la mise en garde que ton propre échange avec ChatGPT formule à la fin ("si tu ne réduis pas le scope, système lent et cher") — le tableau ci-dessus applique cette réduction pilier par pilier, pas en coupant des piliers entiers.

## Ce qu'on ne construit PAS dans ce MVP (backlog V2 explicite)
- Diff/replay de snapshots, rollback automatique par snapshot.
- File lock avec validation + unlock automatique.
- Pipeline steps éditables + replay d'exécution.
- 9 agents persistants dédiés (on garde la factory dynamique + `role_tag`, cf. section 5).
- Harnesses "architecture validation" et "UX/UI consistency".
- Gate CVE bloquant.
- Cache invalidation event-driven complète.

## Exécution — ordre des tickets pour Fable 5 / Claude Code CLI

> Prérequis : tickets de migration 0.4 (section 0) exécutés en premier. Tout ce qui suit se fait dans `DASHBOARD/backend/` et `DASHBOARD/frontend/`, pas dans `.claude`.

1. **Audit NMP** : vérifier que les 8 nodes de `forge_graph.py` émettent tous du NMP (section 1). Zéro nouveau fichier.
2. **`role_tag`** : ajouter le champ à `ForgeState`/`Finding`, classifieur FREE tier dans `prompt_architect.py` ou `forge_kernel.py` (section 5).
3. **SSE réel** : modifier `dashboard_server.py` pour pousser chaque `_nmp_emit` en direct (hook sur le logger `NMP` ou petit writer JSONL `08_LOGS/events/live.jsonl` lu en tail) au lieu du poll 2s sur `checkpoint.json` (section 1 + section 9 Event Stream).
4. **Neural Map** : intégrer `vis-network` (CDN) dans `forge_dashboard.html`, consommer `/api/workflows`, coloration par `role_tag`, pulse sur `active_node` via le flux SSE réel du ticket 3.
5. **Memory Explorer** : nouvel endpoint `GET /api/memory/search?q=` → `forge_db.deep_semantic()`, panel HTML recherche.
6. **Pipeline Analyzer (lecture seule)** : clic node → panneau `/api/live`.
7. **Harness badge** : brancher `harness_engine.py` sur le résultat de tâche, afficher le grade.
8. **File lock minimal** : `hot_set`/`hot_get` Redis sur les chemins de fichiers en cours d'écriture par un agent.
9. **Snapshot naïf** : writer JSONL toutes les 2 interactions (assumé non compressé, documenté comme dette V2).
10. **Consolidation** : archiver `forge_visualizer.py` (doublon de `dashboard_server.py`, ports 8420 vs 7420) dans `09_ARCHIVE/`.

Avant chaque ticket touchant un symbole existant : `impact({target, direction:"upstream"})`. Après chaque ticket : `detect_changes()` + `npx gitnexus analyze`. Tickets 2, 5, 7, 8 sont indépendants entre eux et peuvent être parallélisés via `openhands.run_fleet()` ; 1→3→4 et 1→9 sont séquentiels (dépendances directes).

## Définition de "MVP terminé"
`DASHBOARD/` est un projet autonome (son propre `.env`, son propre `requirements.txt`, aucun import depuis `.claude`), lancé indépendamment (`uvicorn dashboard_server:app --port 7420` depuis `DASHBOARD/backend/`), qui lit le même Postgres/Redis que le Forge. Sur `localhost:7420`, en un seul écran : Neural Map animée en temps réel avec agents colorés par rôle canonique (5 + 9), Event Stream 100% NMP structuré poussé en direct (pas de poll), Memory Explorer avec recherche sémantique réelle, Pipeline Analyzer en lecture avec métriques réelles, badge harness + badge CVE + tracker tokens visibles. Aucun doublon de serveur. Le reste (diff snapshots, file lock complet, agents persistants, replay, gate CVE bloquant) est backlog V2 écrit noir sur blanc, pas oublié.
