# Blueprint — Frontières de services (W5-03d)

> Dérivé du **graphe d'imports réel**, pas d'une intuition d'architecture.
> Outil ré-exécutable : `python -m forge_agents.service_map`
> Mesuré le 2026-07-22 · `cohésion = liens internes / (internes + sortants)`

---

## 1. Le critère

Un contexte n'est extractible en service que si **peu d'arêtes le traversent**. Extraire un
module qui appelle 62 fois l'extérieur ne crée pas un microservice mais un **monolithe
distribué** : mêmes couplages, plus la latence réseau et les pannes partielles.

## 2. Deux corrections de méthode avant de conclure

La première mesure était fausse deux fois. Les deux erreurs allaient dans le sens du
pessimisme — elles auraient fait renoncer à un découpage pourtant possible.

**a) Un produit tiers polluait l'analyse.** 149 modules (~40 %) tombaient dans « divers ».
En les inspectant : ~50 venaient de `tg-bot-workflow/`, une **application cliente complète**
(bot Telegram, réservation d'hôtel) hébergée dans le dépôt de la Forge. Isolée comme telle,
« non classé » est tombé de **149 à 11**.

**b) Le graphe contenait des arêtes fantômes.** L'appariement se faisait sur le nom de
fichier : `__init__` désignait **49 fichiers**, `config`/`database`/`app` plusieurs chacun.
D'où 43 liens « bot Telegram → trading », qui n'existent pas. En ne gardant que les clés
identifiant **un seul** module, la cohésion réelle apparaît :

| Contexte | avec fantômes | corrigé |
|---|---:|---:|
| trading | 62 % | **90 %** |
| tg-bot-workflow | 46 % | **93 %** |

## 3. Mesure

| Bounded context | Modules | Internes | Sortants | Cohésion | Extractible |
|---|---:|---:|---:|---:|:--:|
| **trading** | 46 | 46 | 5 | **90 %** | ✅ |
| **édition (MCPT)** | 17 | 29 | 5 | **85 %** | ✅ |
| **socle multi-tenant** | 4 | 4 | 1 | **80 %** | ✅ |
| outils externes | 43 | 10 | 11 | 48 % | |
| observabilité | 16 | 6 | 7 | 46 % | |
| mémoire / connaissance | 25 | 18 | 24 | 43 % | |
| qualité / garde-fous | 14 | 3 | 4 | 43 % | |
| routage LLM | 15 | 8 | 11 | 42 % | |
| persistance | 8 | 2 | 5 | 29 % | |
| orchestration | 22 | 15 | **62** | **20 %** | ❌ |
| opérations / CLI | 20 | 2 | 18 | 10 % | ❌ |
| passerelle HTTP | 4 | 2 | **29** | **6 %** | ❌ |
| non classé | 11 | 0 | 21 | — | |

*Produits tiers hébergés dans le dépôt (hors périmètre Forge) : `tg-bot-workflow` (39 modules,
93 %), `tg-bot-workflow-v2` (31, 86 %), `demo_partna`, `mvp_output`.*

## 4. Ce que ça dit

**Trois contextes Forge sont extractibles aujourd'hui :**
- **trading (90 %)** — 46 modules, 5 liens sortants. Le plus mûr, et le plus autonome
  métier. Candidat n°1.
- **édition MCPT (85 %)** — le différenciateur produit est aussi la brique la mieux isolée.
  Cohérent : construit avec des frontières explicites.
- **socle multi-tenant (80 %)** — neuf, conçu comme point de passage.

**Deux produits tiers devraient quitter le dépôt** plutôt que devenir des services :
`tg-bot-workflow` et sa v2 sont des logiciels clients, pas des contextes de la Forge. Ils
cohabitent avec le noyau sans raison technique.

**Non extractibles, et pourquoi :**
- **orchestration (20 %, 62 liens sortants)** — c'est le cœur qui appelle tout. L'extraire
  transformerait chaque appel interne en appel réseau.
- **passerelle HTTP (6 %, 29 sortants)** — `server.py` dépend de tout et n'est dépendance de
  personne. C'est un point d'entrée : il doit **maigrir**, pas être extrait.
- **routage LLM (42 %)**, **mémoire (43 %)** — à mi-chemin. Il faut inverser leurs
  dépendances (injection plutôt qu'import direct) pour les faire passer le seuil.

## 5. Ordre recommandé

1. **Sortir les produits tiers** du dépôt (`tg-bot-workflow*`) — gain immédiat en clarté,
   aucun risque pour le noyau.
2. **Extraire `trading`** (90 %) — le plus mûr, périmètre métier net.
3. **Extraire `édition MCPT`** (85 %) — le différenciateur, en service utilisable par d'autres agents.
4. **Finir la migration d'état** (W5-03a) : un service sans état isolé n'est pas déployable
   indépendamment, donc n'est pas un service.
5. **Faire maigrir `server.py`**, puis inverser les dépendances de `routage LLM` et `mémoire`.
6. **Ne pas toucher à `orchestration`** tant que 4 et 5 ne sont pas faits.

## 6. Portée honnête de ce document

C'est une **mesure**, pas un découpage. Elle dit ce qui est extractible aujourd'hui (3
contextes), ce qui ne l'est pas (orchestration, HTTP), et dans quel ordre lever les
obstacles. La règle « microservices par défaut » de CLAUDE.md vaut pour le **code neuf** ;
l'appliquer rétroactivement à un noyau à 20 % de cohésion produirait exactement ce qu'elle
cherche à éviter.
