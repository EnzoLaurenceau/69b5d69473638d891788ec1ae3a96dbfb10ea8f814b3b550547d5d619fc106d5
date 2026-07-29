# HANDOFF — E2-03 : ingestion du canon source

> Suite de [`HANDOFF_E2_05.md`](HANDOFF_E2_05.md) · branche `master`
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md) §3, epic E2

---

## 0. Ce qui a changé en une phrase

**Le pipeline narratif dispose désormais d'un gate copyright** qui prouve que l'index
de citations ne contient aucun mot de l'œuvre source — et qu'un texte qui copie est
bloqué avant intégration.

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/world_canon.py`](00_CORE/forge_agents/world_canon.py) | Canon source, index de citations, gate copyright | 403 l. |
| [`test_world_canon.py`](test_world_canon.py) | **51 tests, tous verts** | 565 l. |
| [`pytest.ini`](pytest.ini) | Inscription CI | modifié |

**Vérifications réellement passées** :
- `pytest test_world_canon.py` → **51 passed, 0 failed** ;
- Suite complète → **339 passed, 42 skipped, 1 failed** (échec pré-existant :
  `test_core_modules_import` dans forge_trading — pandas manquant — hors périmètre) ;
- **Test de mutation** : 5 régressions injectées volontairement — **5 tuées** :

| Mutation | Test(s) tueur(s) |
|---|---|
| Gate `blocked` désactivé (`bool(reasons)` → `False`) | test_copie_franche_bloquee, test_guard_leve_sur_copie, test_workflow_complet |
| `refuse_repo_source` désactivé | test_chemin_dans_le_depot, test_ingest_file_dans_le_depot_leve |
| `forget()` ne nettoie plus les shingles | test_forget_nettoie_les_shingles |
| `SHINGLE_WORDS` réduit de 8 à 1 | 6 tests (texte innové bloqué, fenêtres, etc.) |
| `forget()` retiré de `ingest_text` (accumulation) | test_remplacement_jamais_accumulation |

- `python -m py_compile 00_CORE/forge_agents/world_canon.py` → OK.

---

## 2. Comment on s'en sert

```python
from forge_agents.world_canon import get_canon, CopyrightViolation

c = get_canon()
c.ingest_file("D:/hors-depot/nouveau-soleil.txt",   # RESTE hors du dépôt
              work="Le Livre du Nouveau Soleil",
              license="tous droits réservés")

c.attribute(texte)   # → d'où ça vient (repères, jamais de texte)
c.check(texte)       # → verdict chiffré (ok / warn / blocked)
c.guard(texte)       → lève CopyrightViolation si ça recopie
```

**La décision qui commande tout** : l'index ne contient **aucun mot de l'œuvre**.
Seules des empreintes sha1 tronquées (16 hexa) et des repères de passage sont
stockés. On ne peut pas reconstruire la source depuis l'index — c'est vérifié
par 3 tests dédiés (TestInvariantNoSourceText).

**Pourquoi PAS `dataset_rag`** (malgré l'intitulé du ticket) : `dataset_rag` est
un corpus de RECHERCHE — il rend des extraits pour les injecter dans un prompt.
Y verser le canon reviendrait à mettre le texte de l'œuvre dans le contexte d'un
modèle qui doit produire du contenu original. Le chemin le plus court vers la
copie, pas vers l'inspiration.

---

## 3. Les décisions

### 3.1 ⚠️ On n'indexe pas le texte — on indexe des empreintes

L'index ne contient que des sha1 de fenêtres glissantes de 8 mots, tronqués à
16 hexa (64 bits). Sur un million de fenêtres, la probabilité de collision
fortuite reste négligeable. Le texte source n'est jamais conservé.

### 3.2 ⚠️ `refuse_repo_source()` est un GARDIEN, pas un raffinement

Indexer un fichier du dépôt suppose que l'œuvre y a été copiée — ce que ce
module existe précisément pour empêcher. On refuse le geste plutôt que de
l'accepter en produisant un index propre par-dessus une infraction déjà commise.

### 3.3 ⚠️ Ré-ingérer remplace, jamais n'accumule

Deux passes sur un fichier corrigé doubleraient les empreintes sans rien
apporter. `ingest_text()` appelle `forget(work, save=False)` avant d'indexer.

### 3.4 Les seuils de CLAUDE.md §3 sont encodés en dur

`MAX_QUOTE_WORDS=15`, `MAX_QUOTES=1`. Changer ces valeurs ici serait changer
la doctrine en douce. Trois tests verrouillent ces constantes.

### 3.5 Deux mesures attrapent deux fautes différentes

- La **plus longue reprise continue** attrape le copier-coller franc.
- Le **nombre de reprises distinctes** attrape le patchwork — dix fragments
  de douze mots, chacun sous la limite, forment ensemble une copie que le seul
  critère de longueur laisserait passer.

---

## 4. Ce que le module ne fait PAS

- **Ce n'est pas une source d'inspiration pour les agents.** Le texte de l'œuvre
  n'est jamais mis dans un prompt. Ce que les agents lisent pour s'inspirer,
  c'est le World-KG (E2-01) — des entités, pas de la prose.
- **Ce n'est pas un détecteur de plagiat universel.** Il détecte la recopie
  d'œuvres INDEXÉES. Un texte qui copie une source non indexée passe — c'est
  le rôle de l'humain de décider quoi indexer.
- **Le point d'accroche E3-07** (gate bloquant avant intégration d'asset) est
  `guard()`. Ce ticket fournit le détecteur ; le poser dans le chemin de
  livraison des assets est l'autre ticket.

---

## 5. Pièges pour la suite

- ⚠️ **Ne jamais mettre le texte source dans le dépôt.** `refuse_repo_source()`
  le bloque, mais un fichier `.txt` commité avant l'existence de ce module
  resterait dans l'historique git. Utiliser `.gitignore` ou un repo séparé.
- ⚠️ **`SHINGLE_WORDS` ne doit pas dépasser `MAX_QUOTE_WORDS`.** Verrouillé par
  test : une fenêtre plus longue que la limite doctrinale rendrait le seuil de
  CLAUDE.md invérifiable.
- ⚠️ **L'index est cloisonné par tenant** (via `state_path`). Deux jeux qui
  s'inspirent d'œuvres différentes ne doivent pas se contaminer leurs verdicts.
- ⚠️ **Le chargement du module bypass `__init__.py`** dans les tests (langgraph
  absent). Les tests utilisent `importlib.util.spec_from_file_location` avec
  `__file__` injecté manuellement. Si `__init__.py` change, les tests ne le
  voient pas — c'est voulu (isolation), mais c'est à connaître.

---

## 6. Ce que ça débloque

- **E3-07 (gate copyright/licence)** : `guard()` est le détecteur ; E3-07 le
  pose dans le chemin de livraison des assets. La combinaison bloque un asset
  qui copie avant qu'il n'entre dans le build.
- **E9 (LORE-GUARD)** : l'attribution (`attribute()`) permet de savoir si une
  affirmation du monde vient du canon ou de la génération — le poids d'une
  contradiction dépend de cette provenance.
- **Epic E2 COMPLET** : E2-01 (ontologie) → E2-02 (unicité) → E2-03 (canon) →
  E2-04 (GDD) → E2-05 (RAG) → E2-06 (journal). Le World-KG est opérationnel.

---

## 7. État du dépôt à la remise

- Suite complète : **339 passed, 42 skipped, 1 failed** (pré-existant).
- `E2-03` → `done`. **Epic E2 complet** (6/6 tickets done).
- **3 autres sessions Hermes actives** : mutation testing, CI tools classification,
  LangChain research — aucun conflit de périmètre.
- Prochain sprint selon la roadmap : **S4** (E3-01→E3-03, E4-01).
