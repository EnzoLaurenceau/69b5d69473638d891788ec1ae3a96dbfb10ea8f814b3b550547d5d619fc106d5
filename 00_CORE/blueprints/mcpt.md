# Blueprint — MCPT : Minimum-Cost Program Transformation

> Statut : **implémenté (niveau 1-2)** — `00_CORE/forge_agents/semantic_edit_engine/`
> Entrée : `00_CORE/tools/see_edit.py` · Roadmap : `semantic_edit_engine/UPGRADE_ROADMAP.md`
> Créé : 2026-07-22 (WAVE 1 du board `forge_product`)

---

## 1. Le problème, formulé

Les assistants de code résolvent : *« quel est le meilleur code ? »*
La Forge résout : *« quelle est la transformation la moins coûteuse qui produit ce code ? »*

Formellement — étant donné un fichier `F`, un objectif `G`, et l'ensemble `P` des suites
d'opérations d'édition menant `F` à un état satisfaisant `G` :

```
MCPT(F, G) = argmin  cost(p)     sous contrainte   safe(p) ≥ θ
              p ∈ P
```

Ce n'est pas un « diff plus malin ». C'est un **déplacement de la sortie du LLM** : il
n'émet plus du code, il émet (ou permet de dériver) un **plan d'opérations**.

## 2. Fonction de coût

Implémentée dans `patch_optimizer.COST_WEIGHTS` :

| Terme | Poids | Ce qu'il capture |
|---|---|---|
| `emit` | 1.0 | caractères que le LLM doit produire pour exprimer le plan — **c'est lui qui paie les tokens** |
| `chars` | 0.5 | caractères réellement modifiés dans le fichier — proxy du risque |
| `lines` | 4.0 | lignes touchées — proxy des conflits Git et du coût de revue |
| `ops` | 8.0 | nombre d'opérations — un plan fragmenté est plus fragile |

Les poids sont des **hypothèses explicites**, pas des vérités. Ils sont ajustables et
devront l'être une fois assez de données dans `05_STATE/forge_metrics.jsonl`
(c'est la Phase 3 « patch learning » du roadmap SEE).

## 3. Contrainte de sûreté

Le coût minimal ne gagne **jamais** seul. `SAFETY_FLOOR = 0.55` sur le score `PatchScorer`
(6 critères : édition minimale, compilation, sûreté sémantique, formatage, taille du diff,
efficacité tokens). Un plan moins cher mais sous le plancher est écarté.

Second garde-fou, non négociable : **tout plan candidat qui ne reproduit pas exactement
la cible est supprimé** avant même le scoring (`derive_ops` → `_verifies`). Il n'existe pas
de plan « presque bon ».

Troisième : l'application passe par `auto_rollback.transactional_edit` — fichier qui ne
compile plus après écriture → restauration automatique.

## 4. Les 4 primitives (et pourquoi pas 13)

| Primitive | Coût d'émission | Usage |
|---|---|---|
| `InsertAfter(anchor, text)` | `len(anchor) + len(text)` | ajout pur — **ne détruit rien** |
| `Replace(anchor, replacement)` | `len(anchor) + len(replacement)` | substitution locale ancrée |
| `DeleteRange(start, end)` | ~10 (indices) | retrait — coût indépendant de la taille supprimée |
| `ReplaceSymbolBody(symbol, body)` | `len(body)` | **borne haute** — la réécriture, référence à battre |

La liste initiale en comptait 13 (`MoveFunction`, `ExtractMethod`, `RenameSymbol`…).
Écartées : ce sont des **refactorings**, pas des éditions. Ils opèrent sur plusieurs
fichiers, exigent un graphe d'appels, et relèvent d'un autre moteur (GitNexus `rename`).
Les mélanger dans le même espace de recherche rendait le coût incomparable.

Les ancres sont **minimisées et vérifiées uniques** (`_shrink_anchor`) : une ancre courte
coûte moins de tokens, une ancre ambiguë frapperait au mauvais endroit — donc toute ancre
apparaissant plusieurs fois est rejetée, jamais devinée.

## 5. Les stratégies (l'espace de recherche)

`derive_ops(original, modified, symbol)` produit **plusieurs expressions de la même
transformation**, puis le scoring tranche :

| Stratégie | Construction | Gagne quand |
|---|---|---|
| `character` | hunks purement insertion → `InsertAfter` · purement suppression → `DeleteRange` | ajout/retrait localisé |
| `token` | un `Replace` par hunk, ancre élargie jusqu'à l'unicité | substitution courte |
| `statement` | remplacement des lignes entières touchées | changements multi-lignes contigus |
| `semantic` | `ReplaceSymbolBody` — réécriture | fallback / borne haute |

Aucun cas n'est encodé en dur dans le moteur (c'était le défaut de la version stubbée).

## 6. Où le LLM intervient — et où il n'intervient pas

```
Objectif (langage naturel)
   ↓  ← SEUL appel LLM (forge_call, tier FREE, règle ANTI-DÉRIVE)
Code cible
   ↓  ← 0 token, déterministe
derive_ops → N plans candidats
   ↓  ← 0 token
scoring MCPT + plancher de sûreté
   ↓
plan gagnant → application transactionnelle → métriques
```

Le mode privilégié est celui où **le code cible est déjà connu** (produit par un agent en
amont, ou fourni) : la chaîne entière tourne alors à **0 token**.

## 7. Résultats mesurés (2026-07-22)

| Cas | Stratégie | Émission | Réécriture | Gain |
|---|---|---|---|---|
| ajout condition | character | 36 | 90 | −60 % |
| ajout import | character | 26 | 57 | −54 % |
| suppression ligne morte | character | 16 | 24 | −33 % |
| ajout paramètre | character | 63 | 72 | −13 % |
| renommage local | token | 72 | 82 | −12 % |

Vérification : `python 00_CORE/forge_agents/semantic_edit_engine/test_see.py`

## 8. Limites connues (à ne pas masquer)

- **Mono-fichier.** Le coût inter-fichiers est dans la formule conceptuelle, pas dans le code.
- **Compilation vérifiée en Python seulement.** Les autres langages passent le gate sans contrôle réel.
- **Résolution de symboles** : Python + fallback regex. L'universalité Tree-sitter annoncée n'est pas prouvée.
- **Poids non calibrés.** Choisis a priori ; aucune donnée ne les valide encore.
- **Gain faible sur les petits fichiers** : la baseline `len(original)/4` écrase le pourcentage d'économie affiché. La métrique est honnête mais peu lisible sous ~50 lignes.

## 9. Généralisation (hypothèse, non implémentée)

Le même schéma — dériver l'espace des transformations, scorer, choisir la moins chère —
s'applique en principe aux prompts, configs, documents et graphes de connaissances.
**C'est une hypothèse.** Elle ne sera pas codée avant que le cas « code » ait prouvé sa
valeur sur un usage réel.
