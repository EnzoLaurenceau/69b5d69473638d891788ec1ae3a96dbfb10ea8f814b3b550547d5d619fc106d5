# Diagnostic — Carte neuronale : nœuds figés & sous-représentation

**Date :** 2026-07-22
**Fichiers :** `09_WEB/static/neural_map.html`, `09_WEB/server.py` (`/api/graph`)

---

## Question 1 — « Pourquoi les nœuds ne s'updatent pas réellement ? »

### Cause racine : la détection de changement ne regardait que le *nombre* de nœuds

`neural_map.html`, poll de 8 s, version d'origine :

```js
const sig = `${filtered.nodes.length}:${filtered.links.length}`;
if (sig !== _lastCounts) { graph3D.graphData(filtered); }
```

Conséquences, toutes observables :

| Symptôme | Mécanisme |
|---|---|
| Un nœud qui passe en `running` reste affiché `active` | le compte n'a pas bougé → aucun re-rendu |
| Score, nombre d'appels, latence d'un lien : jamais rafraîchis | idem — seul l'effectif était surveillé |
| Un ajout **et** une suppression au même tick = update perdu | signature identique, changement réel invisible |
| Le panneau de détail affichait des valeurs périmées | il lisait `graph3D.graphData()`, jamais patché |

Autrement dit la carte ne se mettait à jour **que** quand la Forge gagnait ou
perdait un nœud — c'est-à-dire presque jamais. Tout le reste (l'état vivant)
était gelé au premier chargement.

### Cause secondaire : deux chargements concurrents

`initGraph()` faisait `.jsonUrl(getGraphUrl())` **et** `DOMContentLoaded` faisait
son propre `fetch('/api/graph')`. Deux requêtes, deux résultats, celui qui
arrivait en dernier gagnait — dont le graphe **non filtré**. L'état affiché
dépendait donc de l'ordre réseau.

### Corrections appliquées

1. **`/api/graph` renvoie `version`** — un sha1 du contenu complet (nœuds +
   liens), pas de l'effectif. Le moindre changement de statut, de score ou de
   latence change la version.
2. **Patch en place** (`patchInPlace`) — quand la topologie est inchangée, les
   propriétés `label / score / status / details / size` sont écrites directement
   sur les objets nœuds existants. La simulation physique n'est pas relancée,
   donc **les positions sont conservées** : plus de graphe qui « explose » à
   chaque tick.
3. **Rebuild uniquement si la topologie change** — comparaison de la signature
   des ids et des paires source→cible, pas du compte.
4. **Suppression de `.jsonUrl()`** — une seule source de vérité pour le
   chargement initial.

---

## Question 2 — « Pourquoi si peu de nœuds vs la taille réelle de la Forge ? »

Trois causes cumulées. La plus grosse est côté **affichage**, pas côté données.

### Cause n°1 — 233 nœuds fichiers étaient masqués par défaut (la principale)

```html
<input type="checkbox" id="f-file" onchange="applyFilters()">   <!-- pas de `checked` -->
<input type="checkbox" id="f-finding" onchange="applyFilters()"> <!-- idem -->
```

Le filtre était **fail-closed** :

```js
const visibleNodes = data.nodes.filter(n => visibleTypes.has(n.type));
```

Un type sans case cochée — ou **sans case du tout** — disparaissait
silencieusement. Tout nouveau type de nœud renvoyé par l'API était donc
invisible sans que rien ne le signale.

**Corrigé** : filtre **fail-open** (un type inconnu du panneau est visible), cases
ajoutées pour `module` et `datascience`, et le compteur affiche désormais
`Nodes: affichés / total` plus la ventilation par type et le nombre de masqués.
On ne peut plus confondre « la Forge est petite » et « le filtre cache 60 % ».

### Cause n°2 — le scan de code ne voyait qu'un seul dossier, non récursivement

```python
agents_core = FORGE_ROOT / "00_CORE" / "forge_agents"
for f in sorted(agents_core.glob("*.py")):      # non récursif
    if f.name.startswith("_"): continue
```

Étaient ignorés : `00_CORE/forge_agents/semantic_edit_engine/`, `tools/`,
`ai_agent_kit/`, et **la totalité** de `01_ORCHESTRATOR`, `03_JURY`,
`04_GRAPHIFY`, `09_WEB`, `10_TRADING`.

**Corrigé** : `_scan_code_tree()` parcourt récursivement les 7 racines de code
propriétaire, crée un nœud `module` par dossier (hiérarchie parent→enfant), et
**agrège** les dépôts vendorés (`skills/`, `07_KNOWLEDGE_BASE/`, `nexus/`, …) en
un nœud par racine — sinon 6 400 fichiers tiers noieraient la Forge elle-même.
Case « Inclure dépôts vendorés » (`?scope=full`) pour les développer.
Cache disque de 30 s pour que le poll de 8 s ne rescanne pas le FS.

### Cause n°3 — sources vides ou plafonnées

| Source | Problème | Correction |
|---|---|---|
| `05_STATE/tool_index.json` | fichier **vide** (`[]`) → 0 nœud outil | repli sur le scan réel de `00_CORE/tools/` → 30 outils |
| expériences | plafond `[-100:]` | porté à `[-400:]` |
| Data Scientist | inexistant sur la carte | 16 nœuds `datascience` (santé, anomalies, recos, scorecards) |

### Résultat mesuré

| | Avant | Après |
|---|---|---|
| Nœuds servis (`scope=core`) | ~200 | **416** |
| Nœuds réellement **affichés** | ~180 (fichiers masqués) | **416** |
| Nœuds en `scope=full` | — | **5 359** |
| Types | 8 | 10 (+ `module`, `datascience`) |
| Outils | 0 | 30 |

---

## Ce qui n'est *pas* corrigé, et pourquoi

**GitNexus (83 150 symboles / 111 561 relations) reste non branché sur la carte.**
C'est la vraie masse de la Forge, mais un graphe 3D force-dirigé ne rend pas
83 000 nœuds de façon utilisable. La bonne réponse est un rendu par niveau de
zoom (module → fichier → symbole, chargé à la demande), pas un dump. Les nœuds
`module` ajoutés ici sont le premier palier de cette hiérarchie ; le palier
symbole reste à faire.
