# HANDOFF — Plateforme d'inférence La Forge (reprise session)

> But de ce fichier : reprendre le travail depuis une **nouvelle fenêtre Claude** sans
> recharger tout le contexte. Lis d'abord `PLAN_PLATEFORME_INFERENCE.md` (le plan complet
> avec annexes A→E), puis ce fichier pour l'état d'avancement.
> Dernière mise à jour : 2026-07-24. **Phases 1→4 du plan sont TERMINÉES.** Le travail en
> cours dépasse le plan initial (amélioration de la neural map, cf. §6).

---

## 0. Contexte en une phrase
Le socle Forge est devenu un **produit shippable** : une plateforme d'inférence pour agents
IA, façade `/v1` + console React, multi-tenant actif et prouvé, durcie et prête à déployer
sur Coolify. Les 4 phases du plan sont closes ; le travail actuel est de l'**itération**
(neural map) au-delà du plan, à la demande de l'utilisateur.

## 1. Décisions verrouillées (ne pas re-litiger)
1. **Exécution** : 1 process / tenant → repli fichier `forge_store` suffit, PG+Redis primaire
   volontairement différé (non bloquant pour le ship).
2. **Console** : les 5 vues d'un coup (Dashboard, Orchestrateur, Router, Budget/RTK, Neural map).
3. **Offre** : interne / démo d'abord → PAS de gate légal ni Stripe. Herald + security_audit restent.
4. **Déploiement** : Coolify (docker-compose.prod.yml prêt).

## 2. Architecture retenue
- `/v1` = **façade mince versionnée** montée dans `09_WEB/server.py` via `include_router` (additif).
- `forge_gateway.py` (`/llm /rag /judge`) reste **interne n8n**, non exposé au produit.
- Console React consomme **exactement** le contrat `/v1`. Design system fourni réutilisé verbatim.
- Multi-tenant réel : `tenant_middleware` (server.py) lit `Authorization: Bearer` → pose le
  contexte tenant pour toute la requête ; `forge_store` refuse d'écrire sans tenant résolu.
- Contrat `/v1` détaillé (annexe A) et wireframes (annexe D/E) → `PLAN_PLATEFORME_INFERENCE.md`.

## 3. Environnement (pièges déjà rencontrés)
- **Python** : PAS sur le PATH. Le `python` de bash/PowerShell = stub Microsoft Store (échoue).
  Utiliser le chemin complet : `C:\Users\Jack\AppData\Local\Programs\Python\Python311\python.exe` (3.11.9).
- **Bash tool** : pas de python. Faire tourner python/pytest via **PowerShell** avec `$PY` = chemin ci-dessus.
- **node/npm** : dispo (node v24.16.0, npm 11.13.0). `console/` a un `package-lock.json` commité.
- **Docker** : absent du shell → impossible de faire `docker compose up`/`docker build` ici.
  Tous les Dockerfiles/composes sont écrits et YAML-validés, mais **jamais exécutés** dans cet
  environnement — à faire sur la machine de déploiement.
- **Kuzu** (backend du graphe `graph_db.py`) : **non installé** ici (`ModuleNotFoundError: kuzu`).
  Le graphe réel est donc toujours vide en dev local ; toute vérif de la neural map passe par
  le bouton "voir un exemple" (données synthétiques, cf. §6).
- **GitNexus MCP/CLI** : absent → analyses d'impact faites **manuellement** (lecture ciblée).
- **preview_fill sur input contrôlé React** : ne déclenche pas toujours l'`onChange` React (le
  setter DOM natif seul ne suffit pas). Pattern qui marche, utilisé partout dans cette session :
  ```js
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  set.call(input, valeur);
  input.dispatchEvent(new Event('input', {bubbles:true}));
  ```
- **preview_screenshot** peut timeout sur une vue qui poll (ex. neural map poll `/v1/graph` toutes
  les 6s) — le DOM/canvas reste inspectable via `preview_eval` même quand le screenshot bloque.
- `.env` et `05_STATE/` sont gitignorés. Token local de test : `05_STATE/identity/.local_token`
  (généré par `scripts/seed_local.py`, jamais commité).

## 4. État git — IMPORTANT
- **Branche courante** : `feat/inference-platform-p1-p3` (créée depuis `master`, **PAS encore
  fusionnée**). `master` est resté à `1060c60`.
- **5 commits** sur la branche, tous vérifiés (build/lint/tests/gates verts avant chaque commit) :
  1. `13aed5c` — Phase 1→3 : façade `/v1`, console React (5 vues), multi-tenant actif.
  2. `2da953b` — Phase 4 : durcissement sécurité (CORS restreint, `/metrics` public_by_design)
     + déploiement Coolify (Dockerfiles prod, compose prod, CI étendue, runbook).
  3. `d41f2c0` — Neural map v2 : graphe typé (vraies relations), pivot au clic (SVG).
  4. `e43eeec` — Neural map v3 : **rendu canvas** (le SVG ne tenait pas l'échelle), query
     builder serveur (`type`/`q`/`focus`/`limit` sur `/v1/graph`), testé à ≈2400 nœuds.
- **Pas de remote configuré** (`git remote -v` vide, cf. `PLAN_2REPOS_CI.md`) — tout est local.
- **Sous-modules NON touchés** et volontairement exclus de tous les commits : `nexus`,
  `07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills` (apparaissent en `m` dans `git status`,
  ce n'est pas un oubli).
- Prochaine étape naturelle : `git checkout master && git merge --ff-only feat/inference-platform-p1-p3`
  (fast-forward propre), ou ouvrir une revue avant fusion.

## 5. Vérifications qui tiennent (à re-tester si tu doutes de l'état)
```powershell
$PY = "C:\Users\Jack\AppData\Local\Programs\Python\Python311\python.exe"
& $PY 00_CORE/tools/state_ownership.py --check   # attendu: PORTE OK
& $PY 00_CORE/tools/security_audit.py  --check   # attendu: PORTE OK (9 HIGH tous revus)
& $PY -m pytest -q                               # attendu: 86 passed
cd console; npm run lint; npm run build          # attendu: 0 warning/error, build vert
```
Toutes ces commandes étaient vertes à la fin de la session précédente. Si l'une échoue,
quelque chose a changé depuis — ne pas supposer que l'état décrit ici est encore vrai sans
re-vérifier (règle mémoire standard : un fichier/symbole cité est une affirmation au moment
de l'écriture, pas une garantie actuelle).

## 6. EN COURS — Neural map (au-delà du plan initial, demande utilisateur)

### Pourquoi ce chantier existe
L'utilisateur a partagé des captures Instagram sur des moteurs de graph intelligence
(LemonGraph/NSA, XKeyscore/NSA, DataWave, Apache NiFi/Accumulo — 5 outils "From Ghidra to
XKeyscore" par hexsecteam) et a demandé d'en extraire les idées utiles à la coordination et
à l'affichage de la neural map, **sans** adopter leur infra lourde (JVM/Hadoop, contre la
décision #1 "léger"). Puis a précisé : **la Forge a plusieurs milliers de nœuds, ils
devraient tous pouvoir s'afficher** — d'où le passage SVG→canvas.

### Ce qui est fait (v2 puis v3, commits d41f2c0 + e43eeec)
- **Backend `/v1/graph`** (`09_WEB/inference_api.py`) :
  - Nœuds réellement typés (avant : labels bidons "Task"/"Node" qui n'existent pas dans
    `graph_db.NODE_TABLES` — bug corrigé).
  - Vraies arêtes via `graph_db.get_edges()` (nouvelle méthode, additive, même façon sûre
    de construire les requêtes Cypher que `export_to_mermaid` déjà en place — labels tirés
    de la constante `EDGE_TABLES`, jamais de l'input utilisateur brut).
  - **Query builder serveur** : `?type=Agent`, `?q=sous-chaîne`, `?focus=entité` (voisinage),
    `?limit=` (plafond dur `_GRAPH_MAX=20000`, avant 200). `truncated:true` si un type atteint
    le plafond — jamais de coupe silencieuse.
- **Console `NeuralMap.tsx`** : réécrite en `<canvas>` (plus de SVG par nœud, qui ne scale pas) :
  - Layout déterministe **clustered par type** (packing phyllotaxique par cluster), pan/zoom
    souris (drag + molette), culling hors-écran, labels affichés seulement si peu de nœuds
    visibles ou zoom suffisant.
  - Query builder client : champ recherche (filtre sur la clé), chips filtre par **type**
    (6 types) et par **relation** (9 types `EDGE_TABLES`), compteur nœuds/relations live.
  - **Pivot** : clic sur un nœud → panneau détail (type, liste des relations, voisins
    cliquables pour re-pivoter), arêtes du nœud sélectionné mises en évidence, reste atténué.
  - État vide actionnable : bouton "voir un exemple (≈2400 nœuds)" génère un graphe
    synthétique (six types × 400, relations plausibles) — **c'est la seule façon de vérifier
    le rendu ici** puisque Kuzu (le backend réel du graphe) n'est pas installé dans cet
    environnement de dev.
- **Vérifié en navigateur** (preview tools, cf. pattern §3 pour le login) :
  - Chargement de l'exemple → header exact `2400 / 2400 nœuds · 800 relations`, légende
    `agent·400 / project·400 / concept·400 / memorynode·400 / decision·400 / repository·400`.
  - Canvas contient des pixels réellement dessinés (vérifié via `getImageData`).
  - Recherche `agent-3` → `19 / 2400 nœuds` (substring match correct : agent-3, agent-30..39,
    agent-300..399).
  - Pivot : clic précis sur un pixel opaque détecté par balayage `getImageData` → nœud
    `agent-2226` sélectionné, panneau affiche `1 relation(s) · deviation_from → repository-1187`.
  - `security_audit` : le nouveau site SQL f-string de `get_edges` (même pattern non-injectable
    que les 3 sites déjà revus dans `graph_db.py`) déclaré dans `REVIEWED_INJECTION` → porte OK.
  - Nouveau test de contrat `test_graph_nodes_typEs_et_aretes` dans `test_inference_api.py`.

### Ce qui N'EST PAS fait (idées notées, pas commencées)
Ce sont les items que j'avais explicitement mis de côté avant que l'utilisateur ne relance
sur "lemongraph et query builder" — le query builder ET l'échelle sont maintenant faits, mais
ces trois-là restent ouverts si l'utilisateur veut continuer :
1. **NiFi — provenance/lineage** : une vue "flux d'un run" tracée depuis `forge_events` /
   `tool_call_ledger` (étapes horodatées d'une exécution). Pas commencé.
2. **LemonGraph — community detection / clustering par rôle** : les agents ont déjà un
   `role_tag` calculé (9 valeurs, cf. `agent_nodes.py` — heuristique keyword + FREE tier
   fallback) qui pourrait remplacer/compléter le clustering par `type` actuel dans le layout
   canvas (regrouper visuellement par rôle fonctionnel plutôt que par label de nœud). Pas
   commencé — c'est l'idée la plus rapide à greffer si on continue ce chantier.
3. **XKeyscore/DataWave — recherche par attribut arbitraire** (au-delà de la clé) : le query
   builder actuel filtre sur `type`/`q`(clé)/`focus`. Filtrer sur des propriétés arbitraires
   du nœud (ex. `raw["status"]`, `raw["cost"]`) n'est pas exposé. Mineur, à la demande.

### Si tu dois continuer ce chantier
- Le fichier central est `console/src/views/NeuralMap.tsx` (canvas, ~300 lignes, commenté).
- Le backend est `09_WEB/inference_api.py` fonctions `graph()` et `_type_of()` (~ligne 400-480).
- La méthode `get_edges()` est dans `00_CORE/forge_agents/graph_db.py` (juste avant `close()`).
- Schéma du graphe (à connaître avant de toucher au typage) :
  `NODE_TABLES = ["Agent","Project","Concept","MemoryNode","Decision","Repository"]`,
  `EDGE_TABLES` = 9 relations typées (`EXECUTES`, `RECALLS`, `LINKS_TO`, `DEVIATION_FROM`,
  `PRODUCED_BY`, `DEPENDS_ON`, `CITES`, `REFERENCES`, `HOSTS_TOOL`).
- **Toute nouvelle requête Cypher dans `graph_db.py` avec des labels/types en f-string** doit
  être ajoutée à `REVIEWED_INJECTION` dans `00_CORE/tools/security_audit.py` (même justification
  que les sites existants : labels issus de constantes du module, jamais de l'appelant) — sinon
  `security_audit.py --check` casse la CI.

## 7. Ce qui reste vraiment ouvert (hors neural map)
- **Herald (gate MVP ≥ B)** : service Rust externe (`AsyncHerald/`, sous-module vide ici) ou
  API cloud `app.itsasync.fr/herald`. **Jamais exécuté** dans cet environnement (pas de Docker,
  et on n'envoie pas le code à un service externe sans accord explicite). C'est le seul gate
  de la doctrine Forge non validé pour ce travail — à lancer sur la machine de déploiement
  avant tout ship réel. Câblé dans `RUNBOOK_PLATEFORME_INFERENCE.md` §5.
- **`docker compose -f docker-compose.prod.yml up -d --build`** : jamais lancé (Docker absent
  du shell de dev). YAML validé, Dockerfiles relus, mais la première exécution réelle reste
  à faire par l'utilisateur.
- **Fusion de la branche** vers `master` (cf. §4).
- Bascule PG+Redis primaire (décision verrouillée #1 : différée, non bloquante).

## 8. Règles Forge à garder actives
TOKEN ESTIMATE avant / ACTUAL après ; `impact` avant édition de symbole ; offload volume au
tier FREE ; RTK + context-mode sur sorties de commande ; microservices par défaut ; artefacts
>10 lignes → fichier ; jamais de commit sans que l'utilisateur l'ait demandé explicitement ;
ne jamais commiter les sous-modules non touchés.
