# POC HelixDB — évaluation comme store mémoire/vecteurs de la Forge

> Décision user (2026-06-16) : **POC d'abord**, pas de migration. Rien n'est supprimé
> de PG/Redis/turbovec. HelixDB ne remplace **pas** GitNexus (intelligence du code) —
> il est candidat uniquement pour la couche **mémoire/vecteurs** (`forge_db.py` + turbovec).

## Ce qu'est HelixDB
Base **graph-vector** en Rust (knowledge graphs + AI memory). Instance locale port
`6969`, REST `POST /v1/query`, SDK **Python** `helix-db` (import `helixdb`) qui émet
le même AST JSON que les SDK Rust/TS/Go. Storage **in-memory par défaut** → `--disk`
pour persister.

## Principe turbovec conservé
On **compresse/embed** le texte via turbovec AVANT de pousser dans Helix
(`prepare_docs()` → vecteur turbovec + texte compact). On ne pousse jamais de texte brut.

## Étapes
```bash
# 1. SDK + CLI
pip install helix-db                     # SDK Python (import helixdb)
# CLI Helix : docs.helix-db.com/cli/getting-started  (helix install)

# 2. Instance locale PERSISTANTE
helix init && helix start dev --disk

# 3. Schéma POC (à confirmer la syntaxe — voir helix_poc_schema.hx)
helix deploy

# 4. Pousser un échantillon turbovec compressé + interroger
python 00_CORE/db/helixdb_poc.py available        # SDK installé ?
python 00_CORE/db/helixdb_poc.py sample 30        # push 30 nœuds (compressés)
python 00_CORE/db/helixdb_poc.py search "openhands fleet"

# 5. Arrêter
helix stop dev
```

## Fichiers POC
| Fichier | Rôle |
|---|---|
| `helixdb_poc.py` | connecteur turbovec→Helix : `prepare_docs` (compress), `push_sample`, `is_available`. Self-check offline : `python helixdb_poc.py demo`. |
| `helix_poc_schema.hx` | schéma `ForgeDoc` (texte+agent+score+vector) — **sketch à confirmer** contre la doc. |

## À confirmer avant un vrai run (gating)
- Syntaxe HelixQL exacte du schéma + des queries `AddV`/`SearchV` (`helix_poc_schema.hx`).
- Builder Python d'insertion (`_build_insert` dans `helixdb_poc.py` est marqué CONFIRM).
- Dimension d'embedding turbovec compatible avec l'index vectoriel Helix.

## Critères de décision (comparer à PG+turbovec)
1. **Latence** insert + recherche vectorielle (k-NN) sur le même échantillon.
2. **Qualité de rappel** vs turbovec/pgvector sur des requêtes réelles de la Forge.
3. **Graph** : Helix fait graph+vector nativement — gain réel pour les relations findings/règles ?
4. **Friction** : SDK Python, persistance `--disk`, ops (1 process de plus).
5. **Réversibilité** : si on adopte → l'ajouter comme backend derrière `ForgeDB`
   (dual-write + WAL, comme le fallback actuel), pas de rip-and-replace.

## Verdict
À remplir après le run. Si positif → étape suivante = adapter `ForgeDB` (dual-write).
Si négatif → garder PG+Redis+turbovec, HelixDB reste documenté comme option.
