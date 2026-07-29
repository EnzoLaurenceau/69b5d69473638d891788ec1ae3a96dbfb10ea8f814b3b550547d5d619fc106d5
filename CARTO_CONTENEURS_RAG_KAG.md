# Cartographie conteneurs RAG / KAG — qui stocke quoi, et ce qui va (ou non) sur la neural map
> Généré 2026-07-24. Vérifié via lecture ciblée (`rtk smart` + grep), source d'autorité :
> docstring `00_CORE/forge_agents/forge_db.py` (topologie) + `knowledge_curator.py` (gardien du graphe).
> But : trancher « ne pas tout foutre dans la neural map ». Réponse courte : **l'archi le fait
> déjà** — les datasets ne peuvent structurellement PAS gonfler la map, ils sont dans un autre
> conteneur. Le seul levier manquant = un seuil de curation (voir §Levier).

## Les 6 conteneurs distincts

| Conteneur | Backend | Contenu | Rôle | Sur la neural map ? |
|---|---|---|---|---|
| **Graphe Kuzu** | `graph_db.py` → `04_GRAPHIFY/kuzu_curator_test` | 6 types de nodes (Agent/Project/Concept/MemoryNode/Decision/Repository), 9 relations | **KAG** = couche sens/relations | **OUI — c'est CE que la map affiche** |
| **Postgres + pgvector** (primaire) | `forge_db.py` | findings, episodes, checkpoints, `graphify_nodes`, `gitnexus_symbols` + embeddings | RAG profond + checkpoints | Non (contenu, pas relations) |
| **Redis (chaud)** | `forge_db.py` | réflexes Cervelet, compteurs, état session, findings chauds | Éphémère/vitesse | Non |
| **rag_anything** | pgvector (`working_dir`) | docs multimodaux ingérés (PDF/Word/Excel/PPT/images…) | RAG documentaire | Non |
| **dataset_rag** | **index léger, PAS de vecteurs** | datasets 1.1M+ rows, index par catégorie + keyword TF-IDF-like + sampling | Récupération dataset à l'échelle | **Non — explicitement hors graphe** |
| **Secours** | `forge_db_fallback.py` | SQLite LangGraph + `graph.json` + gitnexus + WAL `04_GRAPHIFY/wal.jsonl` | Warm standby (dual-write) | Non |

## Pourquoi les datasets ne peuvent PAS gonfler la neural map
`dataset_rag.py` dit texto : *« 1.1M+ rows → index léger, pas de vectorisation (trop cher),
index par catégorie + sampling représentatif, keyword matching TF-IDF-like »*. Ces lignes ne
touchent JAMAIS le graphe Kuzu. La map ne lit que Kuzu. Donc dumper un dataset = 0 node ajouté
à la map, par construction. Ta crainte (« gonfler de centaines de milliers de lignes ») est
déjà écartée par la séparation des conteneurs — sauf si un jour on écrivait explicitement des
rows de dataset via `add_*` du curator, ce que rien ne fait aujourd'hui.

## Qui écrit dans le graphe (le seul chemin vers la map)
3 modules seulement appellent les méthodes d'écriture de `graph_db.py` :
- **`knowledge_curator.py`** `curate()` (après chaque cycle Forge) → agents, projets, mémoire, concepts.
- **`knowledge_blender.py`** → `add_memory` (findings promus en KAG).
- **`forge_shared_brain.py`** → `add_decision`.

## Le gardien actuel = `knowledge_curator.curate()` (00_CORE/forge_agents/knowledge_curator.py:112)
Ce qui entre dans le graphe à chaque cycle :
- **Agent** : si `state["dynamic_agent_name"]` — toujours.
- **Project** : si `state["current_task"]` — toujours.
- **Memory** : `for finding in state["findings"]` **SEULEMENT si `finding["status"] == "confirmed"`** (l:145). ← unique filtre.
- **Concept** : `_extract_concepts(state)` → **tous syncés, aucun filtre** (l:150).
- **Decision** : via forge_shared_brain.

## Levier « afficher seulement les nodes utiles » (ta demande exacte)
Le champ **`score` existe déjà** : `add_memory(..., score=score)` le stocke, `_sync_memory`
le lit (`finding.get("score", 0.0)`), la note affiche `Score X/10` — **mais il n'est JAMAIS
utilisé comme seuil**. Deux greffes cheap, sans nouveau conteneur :
1. **Seuil de score** dans `_sync_memory` / sync concept : ne promouvoir en node que si
   `score >= seuil` (ex. 6/10). Transforme le graphe en « ce qui a fait ses preuves », pas
   « tout ce qui a été confirmé ». C'est le filtre le plus direct pour ta contrainte.
2. **Pruning des orphelins** : `db.get_orphan_nodes()` existe déjà et est appelé dans `curate()`
   (l:161) — mais il ne fait que **générer une note**, il ne supprime rien. Le brancher sur une
   vraie suppression (ou un flag `visible=false`) nettoie la map des nodes sans relation.

## Lien avec les zones / la map « jeu vidéo »
Une « zone » = un regroupement de nodes déjà présents dans Kuzu. Le clustering actuel (v3) est
par **type de node** (6). Passer à `role_tag` (9 valeurs, déjà calculé côté agents) OU au
`category` des Concepts (`_sync_concept` prend `category`, défaut "technical") donnerait des
zones plus « métier ». Aucune de ces deux données n'exige de toucher aux conteneurs — c'est du
layout côté `NeuralMap.tsx` + un champ déjà stocké. Décision produit à trancher (cf. HANDOFF §6).
