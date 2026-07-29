# HANDOFF — E2-01 World-KG livré, suite du plan RPG
> Session du 2026-07-25 · Branche `feat/inference-platform-p1-p3` · **non commité**
> Handoff amont : [`HANDOFF_FORGE_RPG_READINESS.md`](HANDOFF_FORGE_RPG_READINESS.md)
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)
>
> **Ce fichier remplace les §4 et §6 du handoff amont** (l'option a été tranchée,
> l'état git a changé). Tout le reste du handoff amont — le plan, les 11 epics,
> les pièges, le gate GO/NO-GO — reste valide et fait toujours autorité.

---

## 0. Ce qui a changé en une phrase

**E2-01 est fait, testé contre le vrai moteur Kùzu, et n'a rien cassé.** Le premier
ticket qui débloque 5 epics sur 11 est livré ; il reste 10 epics et ~135 jours-Forge.

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/world_kg.py`](00_CORE/forge_agents/world_kg.py) | Ontologie du MONDE — 10 nœuds × 6 arêtes, base Kùzu séparée | 571 l. |
| [`test_world_kg.py`](test_world_kg.py) | **33 tests, tous verts, 0 skip** | 321 l. |
| [`00_CORE/forge_agents/AGENTS.md`](00_CORE/forge_agents/AGENTS.md) | Contrat local + ligne de vérification (DOX) | modifié |

**Vérifications réellement passées** (pas déclaratif) :
- `pytest test_world_kg.py` → **33 passed** ;
- `pytest test_graph_db_escaping.py test_inference_api.py` → **16 passed**, aucune régression ;
- `py -m py_compile 00_CORE/forge_agents/world_kg.py` → OK ;
- `py -m forge_agents.world_kg` → self-check du schéma OK ;
- schéma ouvert sur le chemin de prod → `rel_mode=rel_table`, 10 tables à 0 nœud.

**`graph_db.py` : zéro octet modifié.** Confirmé par `git status` — il n'apparaît pas
dans les fichiers modifiés.

---

## 2. Les trois décisions d'archi à ne pas re-litiger

1. **Base Kùzu SÉPARÉE** (`04_GRAPHIFY/kuzu_world`, override `FORGE_WORLD_KG_PATH`), pas
   des tables ajoutées au graphe existant. Raison mesurée : `09_WEB/inference_api.py:403`
   (`_GRAPH_LABELS`) code ses labels en dur ; ajouter `Character`/`Quest` à `NODE_TABLES`
   aurait fait remonter des PNJ dans la neural map du code, qui est en production.
2. **`_esc` / `_label` / `_num` sont IMPORTÉS de `graph_db`, jamais recopiés.** Cette
   fonction d'échappement a déjà été cassée en silence une fois (W6-01) ; une seule
   implémentation, un seul test qui la garde (`test_graph_db_escaping.py`).
3. **Les garde-fous LÈVENT, ils n'avertissent pas.** Propriété hors whitelist, `canon`
   ou `status` hors vocabulaire, couple d'arête non déclaré (`Item KNOWS Character`)
   → `ValueError`. Un LLM qui écrit à côté doit être bloqué, pas se croire enregistré.

---

## 3. Surface d'API utile aux tickets suivants

```python
from forge_agents.world_kg import get_world_kg
kg = get_world_kg(world_id="urth")

kg.add_character("Sévérian", role="protagoniste", canon="canon", alive=True)
kg.add_location("Nessus", kind="city")
kg.link("LOCATED_IN", "Character", "Severian", "Location", "Nessus")

kg.context_pack("Character", "Severian")   # entité + voisinage + règles de lore dures
kg.contradictions()                        # matière première d'E9
kg.chronology()                            # événements ordonnés par `chrono`
```

**Points d'accroche déjà posés pour la suite** :
- `world_key()` (identité déterministe `{monde}:{Label}:{slug}`) → **E2-02** y branche
  l'unicité sémantique via `forge_fingerprint`, sans toucher au schéma ;
- `context_pack()` → **E2-05** (RAG + re-ranking) et **E7** (procgen). C'est LE point de
  passage : aucun agent ne doit inventer un PNJ sans avoir consommé ce paquet ;
- `DesignDecision` + arête `DERIVED_FROM` → **E2-06**, tables déjà créées, c'est du câblage ;
- `contradictions()` / `chronology()` (champ `Event.chrono`) → **E9** ;
- `canon` ∈ {canon, derived, generated, human} → gate copyright **E3-07** ;
- `provenance` sur chaque nœud et chaque arête → **E6** (coût/traçabilité par artefact).

**Pour étendre le schéma** : ajouter dans `_TYPE_PROPS` (propriétés) ou `WORLD_EDGE_PAIRS`
(couples). Le DDL en est **dérivé** (`node_ddl`/`edge_ddl` sont des fonctions pures, testées).
Ne jamais écrire de DDL à la main ailleurs.

---

## 4. Ce que l'installation de Kùzu a révélé — à retenir comme méthode

`kuzu` n'était pas installé ; j'ai d'abord écrit des tests purs, puis **installé
`kuzu 0.11.3`** pour prouver le schéma contre le vrai moteur. Ça a sorti **3 bugs réels
qu'aucun test pur n'aurait vus** :

1. `context_pack()` ne remontait **jamais** les règles de lore dures — Kùzu nomme les
   colonnes `n.hard`, le filtre lisait `hard`. La fonction censée défendre le lore
   renvoyait une liste vide, silencieusement. → `_rows()` dépréfixe désormais les alias.
2. Deux mondes = deux `kuzu.Database` sur le même fichier = *« Could not set lock on
   file »*. `get_world_kg("urth")` puis `get_world_kg("autre")` aurait planté.
   → connexion partagée **par chemin** (`_CONNECTIONS`).
3. Un test encodait « Kùzu est absent » comme hypothèse — il serait devenu faux le jour
   de l'installation.

**Leçon transposable au reste du plan** : un schéma qui se rend joliment n'est pas un
schéma qui s'ouvre. Pour E3/E4/E5, installer/lancer le vrai outil avant de déclarer un
ticket fait.

---

## 5. Deux points ouverts — décisions qui vous appartiennent

### 5.1 `kuzu` n'est déclaré dans AUCUN fichier de dépendances
Ni `requirements.txt`, ni Dockerfile, ni pyproject (vérifié par grep). Or `graph_db.py`
l'importe en prod et `/graph` l'attrape en `except` → **votre neural map est peut-être
vide en ligne pour cette seule raison**. Je n'ai rien corrigé : ça touche l'image
déployée. Une tâche séparée est posée (`task_c5ac6d3a`), non démarrée.

### 5.2 `04_GRAPHIFY/kuzu_world` est untracked (84 Ko, schéma vide, 0 nœud)
Créé pendant la mise au point des tests. Je l'ai laissé : il prouve que le schéma s'ouvre
sur le chemin de prod (`rel_mode=rel_table`). **Convention du dépôt : `04_GRAPHIFY/kuzu_graph`
est COMMITÉ** (13,4 Mo de binaire dans git). Donc, à trancher :
- soit le World-KG suit la même convention et sera commité — cohérent avec E2-04
  (« le GDD est une vue, le graphe est la source de vérité ») ;
- soit il va dans `.gitignore` et il faut prévoir une autre persistance du canon.
Ne pas laisser ce choix par défaut : c'est la question « où vit la vérité du jeu ».

---

## 6. Prochaine action — recommandation

**Ne pas enchaîner sur E2-02.** Le ticket le plus rentable maintenant est **E1-01, puis
l'injection des ~60 tickets dans `05_STATE/kanban/`** (l'« option A » du handoff amont) :
cette session vient de produire un module dont l'avancement n'est tracé nulle part, et il
en reste ~135 jours. Avoir un board réel avant de produire ce volume est exactement
l'esprit de la demande initiale.

**Si vous préférez rester dans E2** : prendre **E2-06** (journal de décisions, 1 j, S)
avant E2-02 — la table `DesignDecision` et l'arête `DERIVED_FROM` existent déjà, c'est du
câblage, et ça commence à tracer *pourquoi* vous décidez ce que vous décidez pendant que
vous construisez la Forge.

**Ordre du plan rappelé** : E1 + E2 d'abord (E2 débloque E3, E7, E8, E9) → E6 (mesure) →
E3/E4 en parallèle → E5 → E7→E10 → E11 après le vertical slice.

---

## 7. État git au moment du handoff

Branche `feat/inference-platform-p1-p3`, **rien de commité cette session**.

Ajouté par cette session :
`00_CORE/forge_agents/world_kg.py` · `test_world_kg.py` · `04_GRAPHIFY/kuzu_world` (cf. §5.2) ·
ce fichier — et `00_CORE/forge_agents/AGENTS.md` modifié.

Déjà en cours **avant** cette session (ne pas m'attribuer) : chantier neural map
(`09_WEB/inference_api.py`, `console/src/*`, `ANALYSE_SCREENSHOTS_NEURAL_MAP.md`,
`CARTO_CONTENEURS_RAG_KAG.md`), `07_REPORTS/AUDIT_APTITUDE_RPG.md`,
`HANDOFF_FORGE_RPG_READINESS.md`, `09_TASKS/KANBAN_SPRINT_6J.md`, `HANDOFF_SPRINT_6J.md`,
`00_CORE/forge_agents/mimo_budget.py`.

⚠️ Aucun `detect_changes()` n'a pu être lancé : **le MCP GitNexus n'est pas connecté dans
cette session**. L'analyse d'impact sur `ForgeGraphDB` a été faite à la main (grep des
consommateurs) — elle est documentée en §2.1 et vérifiée par les 16 tests de non-régression.
Relancer `detect_changes()` avant de commiter si le MCP est disponible.

---

## 8. Méthode de travail (elle a tenu, la reconduire)

Audit initial : 9 tool calls. Cette session : ~20, dont l'implémentation, l'installation
de Kùzu et 3 cycles de correction. **Pas un seul subagent.** `Bash`+RTK / `Grep` / `Glob`
sur les modules ciblés, jamais de `Read` de fichier entier, jamais de fan-out.
Règles Forge actives : pas d'`ANTHROPIC_API_KEY` · DOX (AGENTS.md lu puis mis à jour) ·
`impact()` avant d'éditer un symbole.

⚠️ **Ne pas appliquer la règle ANTI-DÉRIVE « offload au tier FREE » de `CLAUDE.md`** : la
décision du 2026-07-25 a écarté TOUS les tiers gratuits (Groq/ds2api/Gemini/Cerebras). Il
reste Claude (abonnement) et MiMo, qui est **payant** (17 €/mois). `CLAUDE.md` n'est pas
encore à jour sur ce point — offloader « pour économiser » coûte désormais de l'argent.
Sur ce ticket, aucun appel LLM automatisé n'a été fait : tout est du code écrit et testé.
