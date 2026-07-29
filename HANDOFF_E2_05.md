# HANDOFF — E2-05 : interroger le monde AVANT d'écrire

> Suite de [`HANDOFF_E2_02.md`](HANDOFF_E2_02.md) · [`HANDOFF_E2_04.md`](HANDOFF_E2_04.md) · [`HANDOFF_E2_06.md`](HANDOFF_E2_06.md) — branche `master`
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md) §3, epic E2

---

## 0. Ce qui a changé en une phrase

**Un agent peut désormais atteindre le monde sans en connaître les noms.** E2-01
livrait `context_pack(label, name)` — le voisinage d'une entité prêt à entrer dans
un prompt — mais il fallait déjà savoir de quelle entité on parlait. Or un agent
qui va écrire « un marchand de reliques dans la ville basse » ne connaît aucun
nom : c'est justement ce qu'il s'apprête à inventer. E2-05 est la porte
manquante : **langage naturel → entités du monde → le paquet.**

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/world_rag.py`](00_CORE/forge_agents/world_rag.py) | Recherche du monde (nouveau module) | 649 l. |
| [`test_world_rag.py`](test_world_rag.py) | **59 tests, tous verts** | 555 l. |
| [`00_CORE/forge_agents/world_kg.py`](00_CORE/forge_agents/world_kg.py) | `WorldKG.all_edges()` — lecture en masse | +28 l. |
| [`pytest.ini`](pytest.ini) · [`AGENTS.md`](00_CORE/forge_agents/AGENTS.md) | Inscription CI + contrat local | modifiés |

**Vérifications réellement passées** :
- `pytest` (suite complète) → **455 passed, 0 failed** ;
- **test de mutation** : 5 régressions injectées volontairement (hissage du nom
  retiré, exclusion des `cut` retirée, garde du score nul retirée, règles dures
  classées au lieu d'être hissées, `slugify` retiré de la tokenisation) —
  **5 tuées**, chacune par les tests censés l'attraper. Fichier restauré et vert.
  La suite mord ;
- `python -m py_compile` sur tous les fichiers touchés ;
- self-check : `python -m forge_agents.world_rag` (n'ouvre aucune base).

**Ticket** : `E2-05` → `done` dans le backlog, `actual_days` mesuré via
`task_run(..., started_at=claimed_start('E2-05'))` (protocole E6-01).

---

## 2. Comment on s'en sert

```python
from forge_agents.world_rag import get_world_rag

r = get_world_rag("urth")
r.search("bourreau de la guilde")            # → entités classées
r.world_context("relique qui guérit")        # → LE paquet à injecter dans le prompt
r.before_write("Character", "Severian le bourreau",
               summary="marchand de reliques")  # → avant d'écrire
```

`before_write()` est la forme courte de la promesse du ticket. Il rend, en un
appel : ce que le monde sait déjà du sujet (`entities`, chacune avec son
`context_pack`), ce qui ressemble à ce qu'on va écrire (`duplicates`, E2-02), ce
qui est interdit (`rules_in_scope`), et si `upsert()` lèverait (`would_raise`).

---

## 3. Les sept décisions (toutes mesurées, aucune déduite)

### 3.1 ⚠️ `forge_rag_optimized` NE S'IMPORTE PAS dans cette Forge

C'est **le** fait central du ticket, et il n'était pas prévisible depuis le plan.

```
import forge_rag_optimized  →  ModuleNotFoundError: No module named 'torch'
```

Le module fait `import torch` au niveau module. Conséquence : même son BM25 —
dont la dépendance `rank_bm25` **est** installée — est hors d'atteinte. Le
brancher en dur, comme le ticket le dit littéralement, aurait livré un E2-05 qui
lève à l'import : un monde interrogeable **nulle part**.

Il est donc chargé **paresseusement** (`load_reranker()`, qui ne lève jamais) et
sert à ce qu'il est seul à savoir faire : le **cross-encoder de re-classement** —
l'étape que le ticket nomme explicitement. Le reste dégrade en trois étages
**annoncés** dans `stats()["mode"]`, jamais en silence :

| mode | condition | ce qu'on perd |
|---|---|---|
| `rag_optimized` | torch + transformers | — |
| `bm25` | `rank_bm25` (état actuel) | le cross-encoder |
| `lexical` | rien | BM25, recouvrement de requête seul |

Une recherche qui s'éteint sans le dire est un monde que les agents
ré-inventeront à côté.

### 3.2 ⚠️ On n'appelle PAS `ForgeRAGOptimized.index()`

Deux raisons mesurées, pas une préférence :

1. `semantic_chunk()` coupe une fiche d'entité de 805 caractères en **2 morceaux,
   et le second n'a plus le nom** — un fragment (« il porte la Griffe et marche
   vers le nord ») remonterait attribué à personne ;
2. son `index()` ré-encode **tout** le corpus à chaque document ajouté (O(N²)).

D'où : **une entité = UN document, jamais découpé**, corpus tenu ici. C'est son
*reranker* qu'on branche, pas son indexeur.

### 3.3 ⚠️ Le tokenizer partagé mutile le français

```
_tokenize("épée dorée")  →  ['pée', 'dorée']      ← la lettre initiale est mangée
_tokens("épée dorée")    →  ['epee', 'doree']     ← corrigé
```

Le motif du tokenizer commence par `[a-zA-Z_]` : « é » n'ouvre aucun token.
« épée » et « epee » ne se rencontraient donc **jamais**, dans un monde qui
s'écrit en français. On tokenise le **slug** — et la recherche hérite au passage
exactement de la notion de « même chaîne » que l'identité (E2-01/E2-02).

### 3.4 ⚠️ Une entité NOMMÉE par la requête est hissée, pas classée

**La régression du ticket.** Le premier jet la classait comme les autres et
ratait le cas le plus élémentaire qui soit :

```
search("Severian")  →  [Agia, Griffe du Conciliateur, Épée Terminus Est]
                       ...mais PAS Severian.
```

Cause **structurelle**, non réglable par pondération, relevée contre le moteur :
le nom d'une entité figure dans le document de **chacun de ses voisins** (on y
rend les relations — et c'est voulu, « une rivale de Severian » doit trouver
Agia). Le terme apparaît donc dans la majorité des documents, son IDF s'effondre
au plancher d'epsilon de `rank_bm25`, et la normalisation par longueur classe
l'entité elle-même **dernière** :

| document | score BM25 pour « severian » | longueur |
|---|---|---|
| Agia | 0,0078 | 5 tokens |
| Griffe | 0,0078 | 5 tokens |
| Épée | 0,0078 | 5 tokens |
| **Sévérian** | **0,0059** | 9 tokens |

Un nom exact n'est pas un signal parmi d'autres : c'est une réponse. Il est donc
traité comme les règles dures — hors classement. La correspondance réutilise
`similarity()` d'E2-02 et se mesure sur **tout** le corpus : c'est précisément
quand la recherche rate l'entité qu'elle doit la rattraper.

### 3.5 Les règles `hard` ne sont jamais classées

Hissées entières à côté des résultats, et **retirées des `context_pack`
individuels** (E2-01 les rejoint à chaque appel : les garder ferait payer les
mêmes règles k fois dans le prompt). Un top-5 peut écarter la règle qui interdit
exactement ce que l'agent s'apprête à écrire — d'autant plus sûrement qu'elle est
formulée en termes généraux, donc lexicalement loin de la requête.

Verrouillé par test : **une requête sans aucun résultat rend quand même toutes
les règles dures.**

### 3.6 Score nul = aucun résultat

BM25 rend un vecteur entièrement nul hors vocabulaire, et `np.argsort` d'un
vecteur nul rend l'ordre des indices. `ForgeRAGOptimized.search_bm25()` renvoie
donc ses `top_k` premiers documents, à score 0, **comme s'ils répondaient**. Ici,
sous `MIN_SCORE`, liste vide — sauf pour une entité nommée.

*Corollaire à connaître* : les scores sont comparatifs **à l'intérieur** d'une
requête (min-max sur les seuls candidats), pas d'une requête à l'autre. Un unique
candidat parfait score donc bas. Un score absolu supposerait une échelle de
pertinence que ni BM25 ni un cross-encoder ne fournissent.

### 3.7 L'index n'est jamais périmé

Reconstruction complète **à chaque requête** (`fresh=True` par défaut). Un index
qui se rafraîchit sur signal a toujours un chemin par lequel il ment, et un agent
qui lit un monde périmé écrit contre un monde qui n'existe plus.

Rendu tenable par `all_edges()` — une requête par **table** d'arêtes au lieu de
deux par nœud :

| opération (300 nœuds) | avant | après |
|---|---|---|
| cartographier le voisinage | 2 087 ms | **27 ms** (×76) |

Le coût ne dépend plus que du nombre d'**arêtes**. Relevé sur 302 nœuds :

| | temps |
|---|---|
| `refresh()` complet | 91 ms |
| recherche, index tenu | 10 ms |
| recherche, `fresh=True` (défaut) | **74 ms** |
| `world_context()` | 122 ms |
| `before_write()` | 154 ms |

Bon arbitrage devant un agent qui s'apprête à écrire : l'appel LLM qui suit coûte
des **secondes**. `fresh=False` est la sortie explicite pour qui boucle sur un
monde figé — et le seul réglage à connaître si un monde grossit beaucoup.

---

## 4. Ce que le module ne fait PAS

**Ce n'est pas un juge de cohérence.** `before_write()` REMONTE les règles dures
et les quasi-doublons ; il ne décide pas si l'écriture les viole. Trancher « ce
PNJ contredit-il la règle ? » demande un LLM — c'est **E9 (LORE-GUARD)**. Un
module qui prétendrait le faire ici rendrait un verdict qu'il ne peut pas tenir,
et un garde-fou auquel on ne peut pas se fier est pire que pas de garde-fou.

La seule prédiction rendue, `would_raise`, est **vérifiable** : elle rejoue la
règle d'E2-02, et un test l'oppose au vrai `upsert()` **dans les deux sens** (elle
annonce le refus → `upsert` lève ; elle n'annonce rien → `upsert` passe). Une
prédiction jamais confrontée dérive en silence.

**Ce n'est pas une troisième ontologie** (même discipline qu'E2-04/E2-06) : zéro
label, zéro propriété, zéro arête. Un seul ajout à E2-01, `all_edges()`, et c'est
une **lecture**.

---

## 5. Pièges pour la suite

- ⚠️ **Ne jamais remettre `forge_rag_optimized` en import dur.** E2-05 lèverait à
  l'import et le monde ne serait plus interrogeable nulle part (§3.1). Si torch
  est installé un jour, le mode passe à `rag_optimized` **tout seul** — rien à
  changer.
- ⚠️ **Ne pas revenir à `_tokenize` nu** dans la recherche : le français y perd
  ses initiales accentuées (§3.3).
- ⚠️ **`RERANK_WEIGHTS` doit sommer à 1.0** (verrouillé par test) : une part
  ajoutée sans rééquilibrage rendrait les scores incomparables d'une version à
  l'autre, en silence.
- ⚠️ **`HIDDEN_STATUS` duplique volontairement la valeur de `world_gdd`** sans
  l'importer — la recherche n'a pas à dépendre du module qui rend un document.
  Un test verrouille l'accord des deux : une divergence doit se voir.
- ⚠️ **`forge_backlog.upsert()` est un REMPLACEMENT COMPLET, pas une fusion.**
  Un `upsert(id=…, notes=…)` partiel remet `state` à `pending` et efface
  `actual_days` — et la machine à états interdit ensuite `pending → done`, ce qui
  bloque la clôture du ticket. Toujours `rec = dict(bl.require(id)); rec.update(…);
  bl.upsert(**rec)`. Rencontré en clôturant E2-05.
- La branche cross-encoder est testée **par injection** (`WorldRAG(kg, engine=…)`).
  `forge_rag_optimized` étant inimportable ici, un `skip` aurait laissé croire
  qu'elle est vérifiée ailleurs.

---

## 6. Ce que ça débloque

- **E7 (procgen)** : `world_context()` est le paquet que la génération procédurale
  doit consommer avant de produire une entité — l'accroche prévue par E2-01 est
  maintenant atteignable sans connaître les noms.
- **E9 (LORE-GUARD)** : `before_write()` remonte déjà les règles dures en portée
  et les quasi-doublons. Il manque le **jugement** (le LLM qui tranche la
  violation), pas la matière.
- **E2-03 (canon source)** : le corpus ingéré devra passer par `entity_text()` /
  `upsert()` pour devenir cherchable — la recherche s'y branche sans modification.
- **Gain facile identifié** : `world_gdd.py` appelle encore `neighbors()` nœud par
  nœud pour bâtir le document (2 087 ms sur 300 nœuds). `all_edges()` le ramène à
  27 ms. Non fait ici : hors périmètre E2-05, et E2-04 était en cours dans une
  autre session pendant ce ticket.

---

## 7. État du dépôt à la remise

- Suite complète : **455 passed, 0 failed**.
- `E2-05` → `done`. Reste ouvert dans l'epic E2 : **E2-03** (ingestion du canon
  source, 3 j) — dernier ticket de l'epic.
- ⚠️ Une **autre session travaillait sur le même dépôt** pendant ce ticket : elle
  a clôturé E2-04 (`HANDOFF_E2_04.md`, `test_world_gdd.py` inscrit dans
  `pytest.ini`, porte `test_state_isolation` remise au vert) et produit
  `artifact_quality.py` / `test_artifact_quality.py`. Ces fichiers ne sont pas de
  ce ticket. Rien n'est en conflit — les périmètres ne se touchent pas.
