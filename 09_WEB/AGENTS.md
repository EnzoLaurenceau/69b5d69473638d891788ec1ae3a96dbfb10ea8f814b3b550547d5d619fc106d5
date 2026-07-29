# AGENTS.md — 09_WEB

## Purpose
Couche de présentation et d'observabilité de la Forge : serveur FastAPI
(`server.py`, port 7777) + interfaces statiques (`static/`), dont la carte
neuronale 3D. Sert l'état de la Forge — il ne le produit pas.

## Ownership
- `server.py` — API HTTP/WebSocket, agrégation des stores `05_STATE/`
- `static/neural_map.html` — carte neuronale 3D (ForceGraph3D)
- `observability/` — Prometheus / Grafana provisioning

## Local Contracts

### `GET /api/graph?scope={core|full}&q=`
Contrat de sortie :
```json
{ "nodes": [...], "links": [...], "version": "<sha1[:16] du contenu>",
  "scope": "core", "counts": {"nodes": N, "links": M, "by_type": {...}} }
```

- **`version` est obligatoire.** C'est l'empreinte du CONTENU complet, pas de
  l'effectif. Le frontend s'en sert pour détecter un changement d'état, de score
  ou de latence à effectif constant. Le supprimer regèle le graphe (bug historique
  documenté : `09_TASKS/analysis/NEURAL_MAP_DIAGNOSTIC_2026-07-22.md`).
- Types de nœuds : `graph`, `memory`, `agent`, `tool`, `experience`, `skill`,
  `finding`, `module`, `file`, `datascience`.
  **Tout nouveau type doit avoir sa case dans `neural_map.html`** (le filtre est
  fail-open, donc il s'affichera quand même — mais il sera non décochable).
- `scope=core` (défaut) : les 7 racines de code propriétaire, fichier par fichier,
  + dépôts vendorés **agrégés** en un nœud par racine. ≈ 416 nœuds.
  `scope=full` : vendorés développés. ≈ 5 359 nœuds — pour l'inspection, pas pour
  l'usage courant.
- `_scan_code_tree()` est **caché 30 s** (`_TREE_TTL`). Le poll frontend est à 8 s :
  sans ce cache on rescanne le disque 7 fois par minute.

### Frontend `neural_map.html`
- Une seule source de chargement : le `fetch` de `DOMContentLoaded`.
  **Ne pas réintroduire `.jsonUrl()`** sur `ForceGraph3D` — deux chargements
  concurrents, le dernier arrivé écrase le filtrage.
- Mise à jour : `patchInPlace()` écrit les propriétés sur les nœuds existants
  (positions physiques préservées) ; rebuild complet **uniquement** si la
  signature de topologie (ids + paires source→cible) change.
- Le filtre par type est **fail-open** : un type absent du panneau est visible.

### Tracker d'hallucinations
Chaîne : `tool_call_ledger.build_ledger()` → `hallucination_compare.scan_ledger()`
→ `save_findings()` → `05_STATE/hallucination_events.json`.

- **Le producteur est `ForgeTelemetryDaemon._update_hallucinations()`**
  (throttlé à 60 s), pas `hermes_session_tracker.py` — ce dernier n'est appelé
  par personne. Ne pas rebrancher le tracker dessus.
- **Le producteur écrit le fichier, il ne diffuse pas.** Le temps réel vient de
  `_hallucination_watcher()` (asyncio, 2 s) qui surveille le `mtime` et diffuse
  les ids inédits. Ce découplage est délibéré : n'importe quel écrivain du
  fichier déclenche le push, sans connaître le WebSocket.
- **Ids : toujours `max(ids)+1`** (`_next_halluc_id`). `len(events)+1` recyclait
  les ids une fois le plafond atteint et `/resolve` marquait le mauvais
  événement (109 doublons mesurés). Réparation : `POST /api/hallucinations/repair-ids`.
- **`timestamp` = instant de l'appel d'outil fautif**, jamais l'instant du scan
  (celui-ci va dans `detected_at`). Sinon le KPI « 24h » compte des scans.
- `MAX_HALLUC_EVENTS = 2000` doit rester égal à
  `hallucination_compare.MAX_EVENTS` — les deux écrivent le même fichier.
- `GET /api/hallucinations/health` est le seul moyen de distinguer « rien à
  signaler » de « producteur mort ». Le frontend l'affiche en badge
  LIVE/STALE/DEAD. Ne pas le retirer.

Diagnostic complet : `09_TASKS/analysis/HALLUCINATION_TRACKER_DIAGNOSTIC_2026-07-22.md`

### `/api/datascience/*`
Proxy vers `forge_agents.forge_data_scientist` (cf.
`00_CORE/forge_agents/AGENTS.md`). Le serveur ne calcule rien lui-même : il
expose. `503` si le module n'est pas importable — le reste de l'API continue de
servir.

### `GET /v1/orchestrator/board`
Renvoie `{columns:{todo,doing,done,blocked}, counts, scope, parent_task, updated}`.
`kanban.py` range ses tâches **à plat** avec un `status` ; la traduction en
colonnes se fait ici, une fois, pas dans chaque vue. Un statut inconnu tombe
dans `todo` — **visible**, jamais escamoté.

`scope` dit à qui est le board. Le CLI `kanban.py` tourne sans tenant et écrit
au chemin GLOBAL ; l'API a toujours un tenant et lit `05_STATE/tenants/<id>/`.
Servir le board GLOBAL à un tenant serait une fuite dès qu'il y a plusieurs
clients : le repli n'est autorisé que s'il n'y a **personne à qui fuiter** (une
seule identité enregistrée) ou sur opt-in `FORGE_BOARD_GLOBAL_FALLBACK=1`, et il
est toujours **annoncé** (`scope: "global"`). La garde se referme d'elle-même
quand un second tenant est créé.

### `/v1/quota` et `/v1/budget/mimo` — deux axes, jamais à confondre
`/v1/quota` (`forge_quota.report()`) répond « combien **ce tenant** a consommé sur
la fenêtre glissante d'une heure ». Sa forme est `{tenant, limits:{…},
usage:{…}, window_seconds}` — **deux dictionnaires parallèles**, pas une liste de
`{used, limit}` ; la console doit les apparier (`Budget.tsx::pairResources`).
Se tromper là ne lève rien : la vue reste simplement vide.

`/v1/budget/mimo` (`forge_agents.mimo_budget.report()`) répond « combien il reste
sur **notre abonnement** fournisseur ce mois-ci ». Le champ décisif est `source`
(`remote|local|declared`) : tant qu'aucun endpoint MiMo n'est confirmé, le solde
est en partie **déclaré**, et l'API doit l'avouer plutôt que de le présenter comme
une lecture. Ouvert au jeton tenant comme `/v1/metrics` ; à basculer sous
`_require_admin` le jour où la plateforme sert de vrais clients externes.

## Work Guidance
- Le serveur **agrège**, il ne produit pas de métrique. Toute nouvelle donnée
  doit d'abord exister dans `05_STATE/` via son producteur.
- Un chiffre affiché doit porter sa **provenance** quand elle n'est pas évidente.
  Même règle que « pas de valeur par défaut plausible » : un solde déclaré rendu
  comme un solde mesuré est un mensonge silencieux, pas une approximation.
- Ne jamais fabriquer de valeur par défaut plausible (score, coût) pour combler
  un champ absent : `None` se rend comme « pas de donnée », un `7.0` inventé se
  rend comme une certitude fausse.
- Une source vide (`tool_index.json == []`) doit avoir un repli explicite sur la
  réalité disque, pas afficher 0.

## Verification
- `python -m py_compile server.py`
- Tracker d'hallucinations : `GET /api/hallucinations/health` doit renvoyer
  `status: "live"` et `duplicate_ids: 0` quand le serveur tourne. `status: "dead"`
  = le producteur ne tourne plus, ce n'est jamais « rien à signaler ».
- Chargement hors serveur :
  `python -c "import asyncio,importlib.util,sys; spec=importlib.util.spec_from_file_location('s','server.py'); m=importlib.util.module_from_spec(spec); sys.modules['s']=m; spec.loader.exec_module(m); print(asyncio.run(m.api_graph())['counts'])"`
  → doit renvoyer ≥ 400 nœuds en `scope=core`.
- Carte neuronale : le compteur affiche `Nodes: affichés / total` + ventilation
  par type. Si `affichés < total`, la ligne « N masqués par les filtres » doit
  l'expliquer.

## Child DOX Index
(none — leaf)
