# Analyse des 25 screenshots — inspiration neural map / cartographie "jeu vidéo"
> Généré 2026-07-24 depuis les 25 images uploadées le même jour (12h54-13h02) dans une
> **autre session** que celle-ci (dossier `~/.claude/uploads/06ce9d6d-.../`), lues via agent
> dédié pour ne pas saturer le contexte. Croisé avec `HANDOFF_PLATEFORME_INFERENCE.md` §6
> (état réel du code au commit `e43eeec`).

## Constat qui contredit la prémisse de la demande
**Il n'y a pas de design system Claude.ai dans ce lot.** Les 25 images (3 sont des doublons
exacts → 22 uniques) sont **toutes des captures Instagram** (posts éducatifs sauvegardés, UI
Instagram visible sur chaque image) : aucune couleur hex, police ou composant Anthropic
officiel n'en est extractible. Répartition réelle :
- 5 images : patterns d'architecture agents (série "techwith.ram" — Diamond Pattern, Stop
  Rule, Human Gate, Four Rules, 3 graphes d'exemple)
- 8 images : dashboards ML génériques (série "pythonlifetelugu" — Resume Screening, RAG PDF
  Chatbot, Churn/House Price, Fake News/Sentiment, Object Detection/Face Recognition, Voice
  Assistant/Fraud Detection, **AI Code Reviewer / Multi-Agent Research Assistant**, MLOps)
- 5 fiches outils NSA (série "hexsecteam" "From Ghidra to XKeyscore") : Accumulo, NiFi,
  **DataWave**, **LemonGraph**, XKeyscore — celles déjà citées au commit `d41f2c0` comme
  inspiration de la neural map v2
- 2 images : stratégies de retrieval RAG (Dense/Sparse/Hybrid/.../**Graph Retrieval**)
- 2 images hors sujet : schémas algo linked-list, repo GitHub "career-ops"

## Modèle minimal pour continuer ce chantier
**Sonnet (le modèle de cette session) suffit** — c'est lui qui a livré v2 et v3 (typage réel,
query builder serveur, passage SVG→canvas à 2400 nœuds). C'est du code itératif standard
(React/canvas, requêtes Cypher, layout), pas un problème de raisonnement profond.
Réserver **Opus** uniquement si le design de l'algorithme de partitionnement spatial pour la
"carte façon jeu vidéo à l'échelle de toute la Forge" bloque réellement (vrai problème
combinatoire/design ci-dessous), pas pour la suite mécanique du chantier actuel.
Rappel doctrine `CLAUDE.md` : Claude reste sur **abonnement** (jamais d'API au token) ; toute
génération automatisée hors session interactive passe par le **tier FREE** du routeur
(MiMo→Gemini→Groq→Cerebras), jamais par Claude.

## ✅ Retenu — déjà implémenté (commits `d41f2c0`, `e43eeec`)
| Fonctionnalité | Inspiration | Preuve |
|---|---|---|
| Nœuds typés réels + arêtes réelles (`get_edges()`) | LemonGraph "Graph Analysis" | test contrat `test_graph_nodes_typEs_et_aretes` |
| Query builder serveur `type`/`q`/`focus`/`limit` | DataWave query builder SQL-like | `_GRAPH_MAX=20000`, `truncated:true` explicite |
| Rendu canvas à l'échelle (2400+ nœuds, clustering par type, pan/zoom, culling) | passage forcé par le volume réel de la Forge | vérifié navigateur : `2400/2400 nœuds` |
| Pivot au clic → panneau détail + voisins cliquables | LemonGraph "Entity Details" | vérifié navigateur : `agent-2226` → 1 relation |

## ❌ Rejeté
| Idée | Pourquoi |
|---|---|
| Infra lourde façon Accumulo (JVM/Hadoop) | contredit la décision verrouillée #1 (Forge reste légère ; PG+Redis même pas encore primaire) |
| Schémas linked-list (img 22), repo career-ops (img 23) | hors sujet, sauvegardes Instagram sans lien avec la Forge |

## ⏳ Reporté — idée retenue en principe, pas commencée
| Idée | Pourquoi reporté | Échéance |
|---|---|---|
| Lineage/provenance façon NiFi (tracer un run via `forge_events`/`tool_call_ledger`) | secondaire à l'échelle/query builder qui viennent d'être livrés en priorité | si tu relances ce chantier |
| Clustering par `role_tag` (community detection façon LemonGraph) | la donnée existe déjà (`agent_nodes.py`), mais pas validé que le clustering par type actuel pose problème | **le plus rapide à greffer** si tu continues — item déjà noté HANDOFF §6 |
| Recherche par attribut arbitraire (XKeyscore/DataWave, au-delà de la clé) | mineur, le query builder actuel (`type`/`q`/`focus`) couvre le besoin immédiat | à la demande |
| **Carte/zones façon jeu vidéo** (monde interactif DataWave + ton objectif final "cartographier par zone sélectionnable") | **aucun code commencé** — bloqué sur une décision produit, pas une limite technique (cf. question ouverte ci-dessous) | dès que la définition de "zone" est tranchée |
| Gabarit dashboard admin (images 7-13 : cards KPI + charts + pipeline) | réutilisable pour la console (quotas/tenants) mais pas demandé explicitement ; console a déjà ses 5 vues figées (décision #2) | si nouvelle vue admin demandée |
| Diamond Pattern / Stop Rule (split→explore→evaluate→merge) | le "Human Gate" est déjà en doctrine (HITL, `CLAUDE.md`) ; le reste n'a pas de demande concrète liée à un agent Forge existant | si un futur agent multi-branches le justifie |
| Graph Retrieval (RAG sur la neural map) | pas de besoin RAG exprimé sur le graphe pour l'instant | si recherche sémantique sur nœuds demandée |

## Question ouverte avant de coder la carte "façon jeu vidéo"
Il faut trancher **avant** d'écrire du code : qu'est-ce qu'une "zone" dans le schéma Forge ?
- `role_tag` de l'agent (9 valeurs, donnée déjà calculée) — le plus rapide à essayer
- Dossier physique Forge (`00_CORE`/`04_GRAPHIFY`/`09_WEB`/...)
- Type de nœud (6 valeurs, `NODE_TABLES`) — déjà utilisé pour le clustering canvas actuel

Le clustering actuel (v3) est déjà par **type**. Passer à des zones par **role_tag** est le
changement le moins coûteux (donnée déjà là) pour se rapprocher de l'effet "carte de jeu
vidéo avec régions sélectionnables" — mais reste une décision produit à valider avant code.
