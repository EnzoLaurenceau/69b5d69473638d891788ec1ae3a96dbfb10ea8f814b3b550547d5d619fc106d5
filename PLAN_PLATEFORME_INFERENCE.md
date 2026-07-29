# Plan — Plateforme d'inférence pour agents IA (La Forge) → produit shippable

> Objectif : transformer le socle existant en **produit livrable**. On teste **d'abord
> en local mono-tenant** (prouver la boucle de bout en bout), **puis on active le
> multi-tenant** déjà conçu (option C, blueprint `00_CORE/blueprints/multi_tenant.md`).
> Rédigé le 2026-07-24.

---

## 0. État des lieux mesuré (point de départ réel)

| Brique | Fichier(s) | État |
|---|---|---|
| Moteur d'inférence (orchestrateur + experts) | `run_forge.py`, LangGraph | ✅ fonctionnel, Claude-first |
| API web + streaming | `09_WEB/server.py` (:7777, WS, `X-Forge-Token`) | ✅ mais monolithique (129 Ko) |
| Gateway microservice LLM/RAG | `00_CORE/n8n/forge_gateway.py` (:7788, Prometheus) | ✅ mais **double emploi** avec server.py |
| Identité tenant | `forge_tenant.py` (contextvars, fermé par défaut) | ✅ testé (18 checks) |
| Store isolé PG+Redis / repli fichier | `forge_store.py` | ✅ testé (200 écritures // , 0 perte) |
| Quotas (stockage/req/tokens) | `forge_quota.py` | ✅ fait (W5-03c) |
| Migration des 32 modules `tenant` | `state_ownership.py`, `migrate_state_writers.py` | ⚠️ **24/32**, 8 restants |
| PG+Redis comme primaire | `00_CORE/db/docker-compose.yml` | ⚠️ en **miroir chaud**, pas primaire |
| Design system | kit fourni (tokens, React, UI kit console) | ✅ mais **non câblé** à une console live |
| Build front | — | ❌ aucun `package.json` |
| Déploiement de l'app | compose DB/n8n/observabilité seulement | ❌ pas de manifeste app (Coolify) |

**Diagnostic** : le socle est à ~70 %. Ce qui manque n'est pas de la R&D, c'est de la
**consolidation, du câblage et du durcissement**. Les 3 écarts bloquants pour « shippable » :
1. **Deux API** qui se chevauchent → choisir **une** surface d'inférence contractuelle.
2. **Aucune console** reliant le design system au moteur en temps réel.
3. Multi-tenant **conçu mais pas actif** (8 modules, PG+Redis primaire, quotas non câblés au chemin requête).

---

## 1. Architecture cible

```
                         ┌────────────────────────────────────────┐
   Console (React + DS)  │  Inference API  (FastAPI, une seule)    │
   ───────────────────►  │  POST /v1/agents/run    (sync)          │
   WS /v1/stream         │  WS   /v1/stream        (SSE/WS live)   │
                         │  GET  /v1/agents /runs /metrics /quota  │
                         │  Auth: Bearer <token>  → middleware      │
                         │         → forge_tenant.set(tenant)       │
                         └───────────────┬────────────────────────┘
                                         │ (chaque appel scope tenant)
                    ┌────────────────────┼─────────────────────┐
                    ▼                    ▼                     ▼
             run_forge (moteur)   forge_store (PG+Redis)   forge_quota
             LangGraph            clés préfixées tenant     (enforce/refuse)
```

- **Une** API (`inference_api`) = fusion des rôles de `server.py` + `forge_gateway.py`.
- Contrat versionné `/v1/*`, auth Bearer → middleware résout le tenant (`forge_tenant`).
- Le moteur ne change pas ; on l'expose proprement et on le scope par tenant.
- Console = app React qui consomme **exactement** ce contrat, habillée par le design system.

---

## PHASE 1 — Plateforme locale mono-tenant testable (prouver la boucle)

> But : `un client, une machine`. On lance, on envoie une tâche, un agent tourne, on
> voit le stream et les métriques. `FORGE_SINGLE_TENANT=local` (opt-in explicite d'insécurité).

### Étapes
1. **Choisir la surface API unique.** Garder `09_WEB/server.py` comme base (il a déjà WS +
   auth + index) ; y intégrer les endpoints utiles de `forge_gateway.py` (`/llm`, `/metrics`
   Prometheus). Marquer `forge_gateway.py` comme *déprécié → interne n8n only* pour éviter la
   confusion. **Impact analysis obligatoire** (GitNexus `impact`) avant de toucher server.py.
2. **Définir le contrat `/v1`** (Pydantic) : `POST /v1/agents/run {task, agent?, budget?}`,
   `WS /v1/stream`, `GET /v1/runs/{id}`, `GET /v1/metrics`, `GET /v1/quota`. OpenAPI auto (FastAPI).
3. **Câbler le tenant même en mono** : middleware qui lit `Authorization: Bearer` ou, à défaut,
   `FORGE_SINGLE_TENANT`. Tout passe déjà par `forge_store` → isolation gratuite plus tard.
4. **Bring-up une commande.** `docker-compose.local.yml` : PG + Redis (`00_CORE/db`) + API.
   Cible : `make dev` (ou `start_forge_local.bat`) démarre tout.
5. **Seed + smoke test scriptés** : `scripts/seed_local.py` (crée tenant `local`, un token),
   puis `scripts/smoke_run.py` (envoie une tâche, attend le run terminé, vérifie le stream).

### Critères d'acceptation Phase 1 (Definition of Done)
- [ ] `docker compose -f docker-compose.local.yml up` démarre PG+Redis+API sans erreur.
- [ ] `POST /v1/agents/run` lance un agent réel et renvoie un `run_id`.
- [ ] `WS /v1/stream` diffuse les étapes en direct (pas de refresh manuel).
- [ ] `GET /v1/metrics` expose tokens in/out + coût (déjà tracé par `forge_metrics`).
- [ ] `pytest` : `test_final.py` + un nouveau `test_inference_api.py` verts.
- [ ] TOKEN ESTIMATE affiché avant / TOKEN ACTUAL après chaque run (règle budget CORE).

---

## PHASE 2 — Console (design system → live)

> But : rendre la plateforme **utilisable et vendable**. Le kit design existe ; il faut une
> vraie app qui parle au contrat `/v1`.

### Étapes
1. **Scaffold front** `console/` (Vite + React + TS). Importer le kit fourni : `tokens/*.css`,
   `components/core/*` (Button, Card, MetricCard, StatusBadge, ProgressBar, Input).
2. **Brancher l'adhérence design** : intégrer `_adherence.oxlintrc.json` en CI front (garantit
   le respect du design system — poids 400/500, pas de dégradé, coral avec retenue, etc.).
3. **5 vues déjà validées** (cf. design-system.md §8), consommant `/v1` :
   - Dashboard (MetricCards : agents actifs, tokens économisés, coût).
   - Orchestrateur (Kanban des micro-tasks).
   - Router LLM (tiers FREE→Claude).
   - Token budget & RTK (ProgressBar quota).
   - Neural map 2D (WS temps réel).
4. **Temps réel** : la console s'abonne à `WS /v1/stream` ; statuts d'agents + neural map en
   direct (jamais de rafraîchissement manuel — règle DS §6).

### Critères d'acceptation Phase 2
- [ ] `console/` build sans erreur ; oxlint adhérence design vert.
- [ ] Les 5 vues affichent des **chiffres réels** issus de l'API (pas de mock).
- [ ] Vérification navigateur (preview_* / screenshot) : dark-first, tokens respectés.
- [ ] Un run lancé depuis la console apparaît en live dans l'orchestrateur.

---

## PHASE 3 — Activation multi-tenant (socle → ON)

> But : passer de « socle posé et testé » à « multi-tenant actif ». La conception est faite
> (option C) ; il reste à **terminer, activer et prouver l'isolation sous charge réelle**.

### Étapes
1. **Finir les 8 modules `tenant` restants** (`PENDING_ALLOWLIST` dans `state_ownership.py`) :
   chemins dynamiques / portés par instance / SQLite LangGraph. But : `state_ownership.py --check`
   passe **sans allowlist**. Outillé (`migrate_state_writers.py`, dry-run + restauration).
2. **Basculer PG+Redis en primaire** (aujourd'hui miroir chaud). Le repli fichier reste pour le
   dev/local ; en prod, `forge_store` écrit d'abord PG+Redis → autorise le **multi-worker**
   (le repli fichier est intra-process only, cf. blueprint §6 — ne pas vendre l'inverse).
3. **Câbler l'auth réelle au chemin requête** : middleware Bearer → compte → tenant (identité
   déjà faite W5-03b : comptes + jetons hachés). Retirer `FORGE_SINGLE_TENANT` en prod.
4. **Enforcer les quotas par requête** : `forge_quota` vérifié **avant** exécution ;
   `QuotaExceeded` → HTTP 429 propre côté API + bandeau console (amber, règle DS statut budget).
5. **Provisioning tenant** : endpoint/CLI admin `POST /v1/admin/tenants` (crée espace + token +
   limites `Limits`). Isolation physique `05_STATE/tenants/<tenant>/` déjà en place.

### Critères d'acceptation Phase 3
- [ ] `state_ownership.py --check` vert **sans** allowlist (0 module tenant non migré).
- [ ] `test_state_isolation.py` étendu : 2 tenants concurrents **multi-process** (uvicorn 2+
      workers), aucune fuite d'état, prouvé.
- [ ] Un tenant qui dépasse son quota est bloqué (429) **sans dégrader** l'autre.
- [ ] Deux tokens = deux espaces ; A ne lit jamais rien de B (test automatisé).
- [ ] La console affiche le bon tenant partout (aucune donnée cross-tenant à l'écran).

---

## PHASE 4 — Durcissement & ship (gates Forge)

> But : franchir les **gates bloquants** de la doctrine et déployer.

### Étapes
1. **Sécurité** : `python 00_CORE/tools/security_audit.py` → 0 CRITICAL. Secrets hors repo
   (`.env` déjà présent — vérifier qu'aucune clé n'est commitée), CORS restreint, rate-limit.
2. **Herald** (gate MVP) : grade **≥ B**, 0 CRITICAL, score sécu ≥ 70. Grade < C = bloqué.
3. **Légal** (si offre commerciale/landing) : `legal_check(...)["deliver_ready"] == True`
   (SIRET / hébergeur / médiateur — **demander, jamais inventer**, sinon blocage).
4. **Déploiement Coolify** (doctrine microservices) : Dockerfile API + Dockerfile console +
   `docker-compose.prod.yml` (API, console, PG, Redis, observabilité). Chaque service
   dockerisable + déployable indépendamment + observable (Prometheus déjà là).
5. **Observabilité prod** : brancher `09_WEB/observability/` (Prometheus) + LangSmith (déjà en
   deps) → traces LLM par tenant.
6. **CI 2 repos** (cf. `PLAN_2REPOS_CI.md`) : tests + adhérence design + `detect_changes()` +
   `state_ownership --check` en portes bloquantes.

### Critères d'acceptation Phase 4 (= « 1000% shippable »)
- [ ] `security_audit.py` : 0 CRITICAL.
- [ ] Herald grade ≥ B.
- [ ] `legal_check` deliver_ready (si commercial).
- [ ] Déploiement Coolify reproductible depuis zéro (`git clone` → up).
- [ ] Runbook : démarrer, créer un tenant, révoquer un token, lire les métriques.
- [ ] Rollback documenté (image précédente + migration réversible).

---

## Ordre d'exécution & dépendances

```
Phase 1 (local mono-tenant)  ──►  Phase 2 (console)  ──►  Phase 3 (multi-tenant)  ──►  Phase 4 (ship)
     API unique + contrat            DS câblé au /v1        socle activé + prouvé        gates + deploy
```

- **1 avant tout** : sans API unique testable en local, le reste flotte.
- **2 peut démarrer en // de la fin de 1** (dès que le contrat `/v1` est figé).
- **3 exige 1** (le middleware tenant est le même point d'entrée).
- **4 exige 1→3** (on ne durcit que ce qui est complet).

## Règles Forge appliquées en continu
- **Chaque tâche** : TOKEN ESTIMATE avant / ACTUAL + post-mortem après (`token_tracker`).
- **Avant toute édition de symbole** : GitNexus `impact` (blast radius) ; `detect_changes()` avant commit.
- **Génération de volume** (code long, docs) : offload FREE tier / MiMo, pas le contexte Claude.
- **RTK + context-mode** sur toute sortie de commande nourrissant le LLM.
- **Microservices par défaut** : API et console = services découplés, contrats explicites.

## Décisions verrouillées (2026-07-24)
1. **Modèle d'exécution** : **1 process par tenant.** → Phase 3 allégée : le repli fichier
   (isolation par répertoire) suffit ; PG+Redis primaire devient *optionnel / plus tard*,
   pas un bloquant. On ne vend pas de multi-worker partagé pour l'instant (cf. blueprint §6).
2. **Console v1** : **les 5 vues d'un coup** (Dashboard, Orchestrateur, Router, Budget/RTK,
   Neural map). Phase 2 plus longue mais console complète en une passe.
3. **Offre** : **interne / démo d'abord.** → **pas** de gate légal ni Stripe en Phase 4.
   Herald + security_audit restent obligatoires ; légal/paiement = itération ultérieure.
4. **Déploiement** : **Coolify** (doctrine microservices, self-hosted).

### Impacts sur les phases
- **Phase 3** : garder `FORGE_SINGLE_TENANT` retiré au profit de l'auth Bearer, mais **repli
  fichier conservé** comme store (1 process/tenant → intra-process lock suffit). Bascule
  PG+Redis primaire = tâche différée, non bloquante pour ship.
- **Phase 4** : retirer l'étape `legal_check`/Stripe ; garder `security_audit` 0 CRITICAL +
  Herald ≥ B + Coolify comme gates de livraison.

---

# ANNEXE A — Contrat `/v1` (façade d'inférence versionnée)

> Principe : `/v1` n'est **pas** une réécriture des 60 routes de `server.py`. C'est une
> **façade mince, stable, versionnée** par-dessus le moteur existant (`run_forge`,
> `_run_forge_stream`, canal Redis `forge_events`, `forge_metrics`, `forge_quota`).
> Les 60 routes `/api/*` actuelles **restent** comme endpoints internes du dashboard
> (consommés par les vues avancées de la console). `forge_gateway.py` (`/llm /rag /judge`)
> reste **interne n8n**, non exposé au produit.

## A.0 Conventions transverses
- **Auth** : `Authorization: Bearer <token>`. Middleware unique → hash → compte → tenant
  (`forge_tenant.set`). En local : repli `FORGE_SINGLE_TENANT=local` (opt-in insécurité).
- **Absence/echec de token** → `401`. **Hors scope** (`TenantError`) → `403`.
- **Quota dépassé** (`QuotaExceeded`) → `429` + corps `{error, resource, used, limit}`.
- **Tout est scopé tenant** : chaque handler passe par `forge_store`/`forge_quota`, jamais
  d'accès global. Un handler qui oublie le scope échoue bruyamment (fermé par défaut).
- **Versionnage** : `/v1` figé ; toute rupture → `/v2`. OpenAPI auto (FastAPI `/v1/openapi.json`).

## A.1 Cœur inférence

| Méthode | Chemin | Corps / params | Réponse | Enrobe |
|---|---|---|---|---|
| `POST` | `/v1/agents/run` | `{task, agent?, budget_tokens?, mode?}` | `202 {run_id, status:"queued"}` | logique de `_run_forge_stream`, mais **asynchrone** : enfile + rend le `run_id` |
| `WS` | `/v1/stream?run_id=` | — (upgrade WS) | flux `{type, content, ts}` | pub/sub Redis `forge_events`, **filtré tenant + run_id** |
| `GET` | `/v1/runs/{run_id}` | — | `{run_id, status, result?, tokens_in, tokens_out, cost, started, ended}` | checkpoint + `forge_metrics` |
| `GET` | `/v1/runs` | `?limit&status` | `[{run_id, task, status, cost, ts}]` | `/history` (scopé tenant) |
| `POST` | `/v1/runs/{run_id}/cancel` | — | `{run_id, status:"cancelled"}` | arrêt du run |

**Cycle de vie d'un run** : `queued → running → (streaming) → done | error | cancelled`.
Le `budget_tokens` optionnel plafonne le run (TOKEN ESTIMATE avant / ACTUAL après — règle CORE).

## A.2 Catalogue & introspection (lecture)

| Méthode | Chemin | Réponse | Enrobe |
|---|---|---|---|
| `GET` | `/v1/agents` | `[{name, role, status, model_tier}]` | `/api/agents` |
| `GET` | `/v1/agents/{name}` | détail agent + historique récent | `/api/agents/{name}` |
| `GET` | `/v1/metrics` | `{tokens_in, tokens_out, cost, savings_pct, agents_active}` | `forge_metrics` summary + `/metrics` |
| `GET` | `/v1/quota` | `{storage, requests, llm_tokens : {used, limit, window}}` | `forge_quota` |

## A.3 Vues produit (lecture, alimentent la console)

| Méthode | Chemin | Réponse | Enrobe |
|---|---|---|---|
| `GET` | `/v1/orchestrator/board` | colonnes Kanban + micro-tasks | `forge_dispatch/kanban.py`, `forge_product_board.json` |
| `GET` | `/v1/router/tiers` | tiers LLM + routage courant (FREE→Claude) | `MODEL_ROUTING.md` / router |
| `GET` | `/v1/graph` | `{nodes, edges}` neural map | `/api/graph` |

## A.4 Admin (Phase 3 — provisioning tenant)

| Méthode | Chemin | Corps | Réponse | Note |
|---|---|---|---|---|
| `POST` | `/v1/admin/tenants` | `{tenant_id, limits?}` | `{tenant_id, token}` | crée espace + jeton haché + `Limits` |
| `POST` | `/v1/admin/tenants/{id}/tokens` | `{action:"issue"|"revoke"}` | `{token?}` | rotation jeton |
| `GET` | `/v1/admin/tenants` | — | `[{tenant_id, quota, created}]` | vue opérateur |

> Admin protégé par un rôle séparé (jeton opérateur ≠ jeton tenant). Non exposé en démo publique.

---

# ANNEXE B — Console : 5 vues → endpoints (Phase 2, livrées d'un coup)

> Chaque vue réutilise le vocabulaire du design system (dark-first, tokens, composants du kit).
> Aucune donnée mockée : tout vient de `/v1`. Temps réel = abonnement `WS /v1/stream`.

| Vue | Composants DS | Endpoints consommés | Temps réel |
|---|---|---|---|
| **Dashboard** | `MetricCard` (agents actifs, tokens économisés, coût), `StatusBadge` | `GET /v1/metrics`, `GET /v1/quota`, `GET /v1/agents` | rafraîchi via WS |
| **Orchestrateur (Kanban)** | `Card` colonnes, `StatusBadge` (en cours/attente/bloqué) | `GET /v1/orchestrator/board`, `POST /v1/agents/run` | `WS /v1/stream` (déplacement des cartes en direct) |
| **Router LLM** | `Card`, `StatusBadge` (tier), `Icon ti-network` | `GET /v1/router/tiers`, `GET /v1/metrics` | poll léger |
| **Token budget & RTK** | `ProgressBar` (quota), `MetricCard`, couleur **amber** si seuil | `GET /v1/quota`, `GET /v1/metrics` (savings_pct) | WS |
| **Neural map 2D** | canvas + `Icon ti-cpu`, micro-pulsation lien actif | `GET /v1/graph`, `WS /v1/stream` (arêtes live) | `WS /v1/stream` |

**Garde-fous design (CI front, `_adherence.oxlintrc.json`)** : poids 400/500 uniquement, aucun
dégradé/glow, coral avec retenue, casse phrase, bordures ≤ 1px, états vides actionnables,
squelettes plats (pas de spinner isolé), animations sous `prefers-reduced-motion`.

**Écran d'auth** : saisie du token → stocké **en mémoire** (jamais `localStorage`/`sessionStorage`
— interdit règle Fable 5 §4). Un run lancé depuis l'Orchestrateur doit apparaître **live** dans
la même vue (preuve de bout en bout de Phase 2).

---

# ANNEXE C — Découpage Phase 1 en tâches livrables (chemin critique)

1. `impact` GitNexus sur les symboles de `server.py` touchés (websocket_chat, `_run_forge_stream`,
   auth) → rapport blast radius **avant** toute modif.
2. Nouveau routeur `inference_api/v1.py` (FastAPI `APIRouter`, préfixe `/v1`) monté dans
   `server.py` — **ajout, pas réécriture** (risque minimal).
3. Middleware auth Bearer → tenant (réutilise l'identité W5-03b) + repli `FORGE_SINGLE_TENANT`.
4. Endpoints A.1 (`run`, `stream`, `runs`) branchés sur le moteur existant.
5. Endpoints A.2/A.3 (lecture) en façade des routes `/api/*` déjà là.
6. `docker-compose.local.yml` (PG+Redis `00_CORE/db` + API) + `scripts/seed_local.py` +
   `scripts/smoke_run.py`.
7. `test_inference_api.py` : run → stream → done, métriques présentes, 429 si quota (vert = DoD).

> `detect_changes()` avant tout commit ; chaque édition de symbole précédée d'`impact`.

---

# ANNEXE D — Schéma des events `WS /v1/stream`

> C'est le contrat temps réel qui alimente l'Orchestrateur (Kanban), la Neural map et la
> barre de budget. Aujourd'hui le WS envoie `{type, content}` non typé ; on le **normalise**
> en enveloppe versionnée, filtrée par tenant + run_id, adossée au canal Redis `forge_events`.

## D.0 Enveloppe commune (serveur → client)
```json
{ "v": 1, "run_id": "run_abc123", "seq": 42, "ts": 1721800000.12, "type": "...", "data": { } }
```
- `seq` : entier monotone **par run** → le client détecte un trou et se resynchronise.
- Filtrage strict : un client abonné au tenant A ne reçoit **jamais** un event du tenant B
  (vérifié : le middleware pose le tenant, le broadcast le compare).

## D.1 Taxonomie des events

| `type` | `data` | Vue(s) impactée(s) |
|---|---|---|
| `run.queued` | `{task, agent?}` | Dashboard, Orchestrateur |
| `run.started` | `{agent, task, estimate_tokens}` | Orchestrateur, Budget |
| `task.decomposed` | `{micro_tasks:[{id, title}]}` | Orchestrateur (crée les cartes) |
| `agent.assigned` | `{micro_task_id, agent, model_tier}` | Orchestrateur, Router LLM |
| `agent.thinking` | `{agent, delta}` (chunk streaming) | Orchestrateur (log live) |
| `agent.output` | `{micro_task_id, agent, content}` | Orchestrateur |
| `tool.call` | `{agent, tool, args_preview}` | Orchestrateur, Neural map |
| `tool.result` | `{agent, tool, summary}` | Orchestrateur |
| `board.update` | `{micro_task_id, column}` (`todo`→`doing`→`done`) | Orchestrateur (déplace la carte) |
| `graph.update` | `{nodes:[...], edges:[...]}` | Neural map (arêtes live) |
| `budget.update` | `{tokens_in, tokens_out, cost, savings_pct}` | Budget/RTK, Dashboard |
| `quota.warning` | `{resource, used, limit}` | Budget (bandeau **amber**) |
| `run.done` | `{result_ref, tokens_in, tokens_out, cost, duration}` | toutes |
| `run.error` | `{phase, error}` | Orchestrateur (carte **coral**) |
| `heartbeat` | `{}` (toutes ~15 s) | maintien de connexion |

## D.2 Client → serveur
- Abonnement : à l'upgrade, query `?run_id=` (+ `&since_seq=` pour rejouer après reconnexion).
- Message toléré : `{"type":"cancel"}` → équivaut à `POST /v1/runs/{id}/cancel`.
- Aucune autre commande acceptée (surface minimale = surface d'attaque minimale).

## D.3 Robustesse
- **Reconnexion** : le client renvoie `since_seq` ; le serveur rejoue depuis un buffer Redis
  (fenêtre courte). Trou non rejouable → event `resync` + le client refait `GET /v1/runs/{id}`.
- **Ordre** : garanti par run via `seq`. Pas de garantie inter-runs (inutile).
- **Backpressure** : si le client est lent, on coalesce `agent.thinking` (garde le dernier delta).

---

# ANNEXE E — Wireframes des 5 vues (composition, pas pixel-perfect)

> Grille : sidebar gauche fixe (nav, `Icon` outline) + zone principale. Dark-first,
> `--forge-bg-dark` fond, `--forge-surface-dark` cartes. Réutilise le UI kit console fourni.

## E.1 Dashboard
```
┌───────────┬──────────────────────────────────────────────────────┐
│ ◈ forge   │  tableau de bord                                       │
│ ▸ agents  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│ ▸ orch.   │  │ agents  │ │ tokens  │ │  coût   │ │ économie│  ← MetricCard
│ ▸ router  │  │  actifs │ │  in/out │ │  session│ │  23 %   │       │
│ ▸ budget  │  │    6    │ │ 12k/8k  │ │ 0,04 $  │ │ (RTK)   │       │
│ ▸ map     │  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│           │  runs récents (StatusBadge : en cours / done / bloqué) │
│           │  ┌──────────────────────────────────────────────────┐ │
│           │  │ run_ab12  résumé produit X    ● en cours   0,01 $ │ │
│           │  │ run_9f01  audit sécurité      ✓ done       0,03 $ │ │
│           │  └──────────────────────────────────────────────────┘ │
└───────────┴──────────────────────────────────────────────────────┘
Endpoints : GET /v1/metrics · /v1/quota · /v1/agents · /v1/runs ; live via WS budget.update
```

## E.2 Orchestrateur (Kanban)
```
│  orchestrateur          [ + lancer un agent ]  ← Button coral
│  ┌── à faire ──┐  ┌── en cours ──┐  ┌── terminé ──┐
│  │ ▸ micro #3  │  │ ▸ micro #1 ● │  │ ▸ micro #0 ✓ │   cartes = Card
│  │   scrape    │  │   analyse    │  │   plan       │   badge = StatusBadge
│  │ ▸ micro #4  │  │   (agent A)  │  │              │   micro-pulsation ● teal
│  └─────────────┘  └──────────────┘  └──────────────┘
Endpoints : GET /v1/orchestrator/board ; POST /v1/agents/run
Live : WS board.update (déplace la carte) · task.decomposed (crée) · run.error (carte coral)
```

## E.3 Router LLM
```
│  router llm — tier par défaut : FREE → Claude (validation)
│  ┌─ MiMo    ● prêt   0,00 $ ─┐  ┌─ Gemini  ● prêt ─┐
│  ┌─ Groq    ● prêt          ─┐  ┌─ Claude  ◐ abon. ─┐  ← StatusBadge tier
│  requêtes routées : 142  ·  répartition par tier (barre horizontale)
Endpoints : GET /v1/router/tiers · /v1/metrics
```

## E.4 Token budget & RTK
```
│  budget & rtk
│  quota tokens   [██████████░░░░░░]  62 %   ← ProgressBar (amber si > 80 %)
│  quota requêtes [████░░░░░░░░░░░░]  24 %
│  stockage       [██░░░░░░░░░░░░░░]  11 %
│  économie RTK : 23 %   (MetricCard)      bandeau amber si quota.warning
Endpoints : GET /v1/quota · /v1/metrics ; live via WS quota.warning
```

## E.5 Neural map 2D
```
│  neural map                                (canvas plein)
│        (orchestrateur)
│         /    |    \        nœuds = Icon ti-cpu / ti-network
│      A ●    B ●    C ●     arêtes actives = micro-pulsation teal
│       \     |     /        (prefers-reduced-motion respecté)
│        (store PG+Redis)
Endpoints : GET /v1/graph ; live via WS graph.update
```

> Ces wireframes fixent la **composition et le vocabulaire** ; le rendu pixel suit le kit
> design et passe la CI d'adhérence (`_adherence.oxlintrc.json`).
