# HANDOFF — E1-01 + E1-02 + E6-01 + option A (board réel), suite du plan RPG
> Session du 2026-07-25 (reprise programmée) · Branche `feat/inference-platform-p1-p3` · **non commité**
> Handoff amont : [`HANDOFF_E2_WORLD_KG.md`](HANDOFF_E2_WORLD_KG.md)
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)
>
> **Ce fichier remplace le §6 du handoff amont** (la recommandation a été exécutée).
> Les §5.1 et §5.2 du handoff amont — les deux décisions ouvertes sur `kuzu` — restent
> **ouvertes et non traitées**. Tout le reste du plan fait toujours autorité.

---

## 0. Ce qui a changé en une phrase

**Le plan n'est plus un document, c'est un board interrogeable et mesurable** : 49 tickets en
base, 4 faits (E2-01, E1-01, E1-02, E6-01), et la Forge répond désormais à « qu'est-ce qui est
prenable », « qu'est-ce qui est sur le chemin critique » et « qu'est-ce que ça a réellement
coûté » sans qu'on relise l'audit.

**Découverte qui change la lecture du plan** : le chemin critique du DAG ne fait que **16 jours**,
pas 139. Les 139 jours sont une contrainte de *capacité* (un seul exécutant), pas d'*ordre*.
À nuancer, cf. §4.6.

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/forge_backlog.py`](00_CORE/forge_agents/forge_backlog.py) | Backlog typé, persistant, DAG + CPM — tickets E1-01 et E1-02 | 650 l. |
| [`test_forge_backlog.py`](test_forge_backlog.py) | **66 tests, tous verts, 0 skip** | 620 l. |
| [`scripts/seed_rpg_backlog.py`](scripts/seed_rpg_backlog.py) | Injection option A : **parse** l'audit, ne le retranscrit pas | 223 l. |
| `05_STATE/kanban/board_rpg.json` | Vue kanban projetée — 49 tickets, 151 j (⚠️ non branchée, cf. §5.1) | généré |
| [`00_CORE/forge_agents/forge_db.py`](00_CORE/forge_agents/forge_db.py) | DDL `tasks` dérivé, injecté par import tardif | +9 l. |
| [`00_CORE/forge_agents/forge_db_fallback.py`](00_CORE/forge_agents/forge_db_fallback.py) | `"tasks"` ajouté à `_DEEP_TABLES` | +0 l. (cf. §4.1) |
| [`00_CORE/tools/security_audit.py`](00_CORE/tools/security_audit.py) | Site `world_kg.py:370` revu et justifié (cf. §4.2) | +5 l. |
| [`00_CORE/tools/state_ownership.py`](00_CORE/tools/state_ownership.py) | Régime du seeder | +1 l. |
| [`00_CORE/forge_agents/forge_task_ledger.py`](00_CORE/forge_agents/forge_task_ledger.py) | **E6-01** — agrégation par ticket, retour vers `actual_*` | 302 l. |
| [`test_forge_task_ledger.py`](test_forge_task_ledger.py) | **24 tests, tous verts** | 249 l. |
| [`00_CORE/forge_agents/forge_metrics.py`](00_CORE/forge_agents/forge_metrics.py) | Champ `task_id` sur `MetricRecord` (additif) | +4 l. |
| [`requirements.txt`](requirements.txt) | **`kuzu==0.11.3` déclaré** — §5.1 du handoff amont réglé | +7 l. |
| [`pytest.ini`](pytest.ini) | `test_world_kg` + les 2 nouveaux ajoutés aux `testpaths` | +3 l. |
| [`00_CORE/forge_agents/AGENTS.md`](00_CORE/forge_agents/AGENTS.md) | Contrat local + 4 lignes de vérification (DOX) | modifié |

**E1-02** n'a pas de fichier propre : la détection de cycles était déjà livrée avec E1-01, ce
ticket ajoute `critical_path()` (CPM : marges, ordonnancement) et `conflicts()` dans
[`forge_backlog.py`](00_CORE/forge_agents/forge_backlog.py) — d'où 66 tests au lieu de 51.

**Vérifications réellement passées** (pas déclaratif) :
- `pytest test_forge_backlog.py` → **66 passed** · `pytest test_forge_task_ledger.py` → **24 passed** ;
- `pytest` (suite complète, comme la CI) → **225 passed**, aucune régression ;
- `py_compile` sur les 5 modules touchés → OK ;
- `python -m forge_agents.forge_backlog` → auto-test du schéma OK ;
- `state_ownership.py --check` → **PORTE OK** ;
- `security_audit.py --check` → **PORTE OK (10/10 revus)** — elle était **ROUGE** en arrivant, cf. §4.2.

---

## 2. Les trois décisions d'archi à ne pas re-litiger

1. **Le backlog ne remplace pas `forge_dispatch/kanban.py`, il le précède.** Le kanban JSON
   porte le WIP (qui tient quoi, verrou par fichiers, claim inter-sessions) ; le backlog porte
   le *plan* (epic, dépendances, estimé vs réel, retries) et survit aux sessions.
   `to_kanban_board()` projette l'un vers l'autre. Ne pas fusionner les deux : ils ont des
   durées de vie et des propriétaires différents.
2. **Aucune base ouverte en propre.** Tout passe par `forge_db.deep_insert/deep_query`, table
   `tasks` → Postgres quand il est up (vraies colonnes + index), secours SQLite sinon, avec le
   dual-write et le WAL gratuits. Le DDL est **dérivé** de `_TASK_PROPS` (`table_ddl()`,
   fonction pure) et injecté dans `_ensure_schema` par import **tardif** — un import au
   chargement ferait un cycle (`forge_backlog` appelle `get_db()`).
3. **Asymétrie assumée sur les dépendances.** Une dépendance vers une tâche encore inexistante
   est **tolérée à l'écriture** (injecter un plan de 49 tickets impose des références
   avant-coureuses ; refuser rendrait l'ordre du lot signifiant) mais **`claim()` LÈVE** si
   elle n'est pas satisfaite. Une dépendance inconnue n'est *jamais* réputée satisfaite. La
   rigueur se paie au moment où se tromper coûte quelque chose : prendre la tâche.

---

## 3. Surface d'API utile aux tickets suivants

```python
from forge_agents.forge_backlog import get_backlog
bl = get_backlog()

bl.ready()                    # ce qui est réellement prenable (deps satisfaites)
bl.claim("E1-02", "sess-1")   # LÈVE si une dépendance est ouverte
bl.complete("E1-02", actual_days=3.5, actual_tokens=120_000, artifacts=[...])
bl.dependents_of("E2-01")     # ce que ce ticket débloque
bl.find_cycles()              # DFS itérative — [] = DAG sain
bl.validate()                 # rapport : cycles, deps orphelines, compte par état
bl.epic_summary()             # avancement + jours estimés/réels par epic
bl.render()                   # rendu texte compact, ~1 ligne par epic

# E1-02
bl.critical_path()            # {duration_days, path, critical, schedule{…slack}}
bl.critical_path(remaining=True)   # idem, les tâches faites pesant 0
bl.topological_order()        # ordre de réalisation possible ; LÈVE sur cycle
bl.conflicts("E3-04")         # conflits d'ÉCRITURE (fichiers) + d'ORDRE (deps)
```

```python
# E6-01 — la façon normale de travailler un ticket désormais
from forge_agents.forge_task_ledger import task_run, variance, coverage, epic_costs

with task_run("E2-02", session="ma-session") as run:
    ...                                   # le travail
    run.artifact("00_CORE/forge_agents/world_kg.py")
# → durée, tokens, coût agrégés ; actual_* remplis ; complete() ou block()+retry

variance("E2-02")   # estimé vs réel — matière première d'E1-03
coverage()          # quelle part du backlog est RÉELLEMENT mesurée (0 % aujourd'hui)
epic_costs()        # coût/tokens/échecs par epic — base du dashboard E6-03
```

**Points d'accroche déjà posés** :
- `critical_path()["schedule"][id]["slack"]` → **E1-04** (vélocité, burndown, replanification) ;
- `variance()` → **E1-03**, mais **pas avant d'avoir des tickets mesurés** (cf. §5.2) ;
- `retries` / `bump_retry()` / `aggregate()["failures"]` → **E1-05** ;
- `epic_costs()` → **E6-03** · `meta["quality"]` → **E6-02** (le champ est porté, pas calculé) ;
- `to_kanban_board()` → **E1-06** (vue console) et **E1-07** (`resume_project()`).

**Pour étendre le schéma** : ajouter dans `_TASK_PROPS`. Le DDL en est dérivé. Ne jamais
écrire de colonnes à la main ailleurs. `TASK_STATES` et `COMPLEXITIES` sont un **contrat**
(un test les gèle) : les changer invalide les boards déjà écrits.

---

## 4. Ce que la vérification a révélé — à retenir comme méthode

### 4.1 La porte sécurité est indexée par `fichier:ligne` — et c'est fragile
`security_audit.REVIEWED_INJECTION` est un dict dont les clés sont `chemin:ligne`. Insérer
**une seule ligne** au-dessus d'un site revu décale la clé et rouvre la porte alors que le
code n'a pas changé. C'est pour ça que `"tasks"` a été ajouté à `_DEEP_TABLES` **sans ajouter
de ligne** (la clé `forge_db_fallback.py:128` devait rester valide). À savoir avant toute
édition de `graph_db.py`, `world_kg.py` ou `forge_db_fallback.py`. Consigné dans AGENTS.md.

### 4.2 La porte sécurité était ROUGE en arrivant — laissée par E2-01
`world_kg.py:370` était signalé `NOUVEAU SITE HIGH` non revu. **La session E2-01 n'avait
lancé que `pytest`**, pas les portes CI ; elle a donc déclaré le ticket fait sur une CI
cassée. Le site a été **vérifié ligne à ligne, pas tamponné** : `label` passe par
`_label(label, WORLD_NODE_TABLES)`, toute propriété hors whitelist lève avant, et chaque
valeur passe par `_literal` — `sets` n'interpole que des clés whitelistées et des littéraux
encodés. C'est le même motif que les 4 entrées `graph_db.py` déjà revues, donc la
justification est légitime. **Leçon : « les tests passent » ≠ « la CI passe ».** Les 4 portes
(`pytest`, `state_ownership`, `security_audit`, compilation) sont à lancer avant de dire fait.

### 4.3 Le parseur est vérifié contre l'arithmétique de l'audit lui-même
`seed_rpg_backlog.py` **parse** l'audit au lieu de le retranscrire — 49 tickets extraits, et
les totaux par epic tombent exactement sur les totaux que le document déclare (E1 18 j,
E2 15 j, E3 21 j, E4 15 j, E5 16 j, E6 10 j, E7 16 j, E8 10 j, E9 8 j, E10 10 j). Total
parsé 151 j − 12 j (jalon E11) = **139 j**, le chiffre annoncé par l'audit. Une retranscription
manuelle de 49 lignes n'aurait offert aucune preuve de ce genre.

### 4.4 Deux chiffres du handoff amont étaient des estimations
Le plan compte **48 tickets réels**, pas « ~60 » (+ 1 jalon E11-01 posé parce que l'audit
refuse explicitement de décomposer E11 — on ne devine pas 6 tickets qui n'existent pas).

### 4.5 Ce que le DAG confirme par la mesure
`dependents_of("E2-01")` → **18 tickets** débloqués sur 5 epics ; `dependents_of("E1-01")` →
6. L'audit l'affirmait, c'est maintenant calculé. Les tâches prenables sont passées de 7 à
**24** une fois E2-01 et E1-01 marqués faits.

---

### 4.6 Le chemin critique fait 16 jours, pas 139 — et ce que ça ne veut PAS dire
`critical_path()` sur le DAG réel donne **16 j** (chaîne `E2-01 → E7-01 → E8-01 → E5-04`),
contre 139 j d'effort cumulé. Les 139 jours sont donc une contrainte de **capacité** (un seul
exécutant), pas d'**ordre** : avec de la parallélisation, la limite dure est bien plus basse.
Les plus grandes marges sont E1-07 et E1-03 (12 j chacune).
**La nuance qui compte** : les epics E7→E10 n'ont dans l'audit que des dépendances au niveau
*epic*, pas au ticket (§ « prose » du document). Le graphe est donc plus creux que la réalité
et 16 j est un **plancher**, pas une prévision. Affiner ces dépendances vaut plus que
n'importe quel outil de planification supplémentaire.

### 4.7 `pytest.ini` ne collectait pas les tests d'E2-01
`testpaths` est une liste explicite : un fichier de test absent ne tourne **jamais** en CI,
même vert en local. `test_world_kg.py` (33 tests) y manquait — les tests d'E2-01 n'avaient
donc jamais protégé quoi que ce soit en intégration. Ajouté, avec les deux nouveaux fichiers.
La suite CI passe de **100 à 225 tests**. Consigné dans AGENTS.md.

### 4.8 Mesurer l'acte de cocher la case n'est pas mesurer le travail
E6-01 a d'abord été marqué fait *via son propre* `task_run` — qui a enregistré **0,0004 jour**
pour un ticket estimé à 3 j : la durée de la cérémonie, pas du travail. C'est précisément le
chiffre plausible-mais-faux contre lequel le module est censé prémunir. Annulé ; `coverage()`
affiche **0 %** et nomme les 4 tâches faites non mesurées. C'est exact : toutes ont été
construites avant que l'instrumentation existe. Ne pas « améliorer » ce chiffre.

---

## 5. Points ouverts — décisions qui vous appartiennent

### 5.1 `board_rpg.json` n'est lu par personne aujourd'hui — c'est délibéré
`05_STATE/kanban/board.json` était **déjà occupé** par le board du Sprint 6j ouvert le
2026-07-25 (10,3 Ko). L'écraser aurait détruit un sprint en cours pour installer un plan à
139 jours. Le board RPG est donc écrit à côté, en `board_rpg.json` — et `kanban.py` comme
`/v1/orchestrator/board` ne lisent que `board.json`. **La source de vérité interrogeable est
la table `tasks`**, pas ce JSON. Trancher la cohabitation des deux boards (deux fichiers ? un
champ `boards` ? le sprint devient un filtre du backlog ?) est le cœur d'**E1-06**.
S'ajoute le piège déjà consigné dans `board.json` : le chemin GLOBAL diverge de ce que lit
l'API (`state_path()` AVEC tenant → `05_STATE/tenants/<id>/kanban/`). Non réintroduit en
silence, mais non résolu.

### 5.2 `actual_days` / `actual_tokens` : l'outil existe désormais, la donnée non
**E6-01 est livré** — `task_run()` remplit ces colonnes automatiquement. Mais les 4 tickets
déjà faits ne peuvent pas être mesurés rétroactivement : `coverage()` vaut **0 %** et les
nomme. La première mesure réelle sera celle du prochain ticket. **E1-03 (estimation
apprenante) reste donc inutilisable tant qu'aucun ticket n'a été fait sous instrumentation** —
c'est la seule raison de ne pas l'enchaîner tout de suite.

### 5.3 ⚠️ Postgres est DOWN — le backlog vit dans le secours SQLite
Mesuré pendant la session : `Redis indisponible (TimeoutError)`, `Postgres indisponible
(ConnectionTimeout)`. Les 49 tickets sont donc dans `04_GRAPHIFY/forge_fallback.db`.
**Conséquence à connaître : le jour où Postgres remonte, `deep_query` interrogera PG en
priorité et le backlog paraîtra VIDE**, la table `tasks` y étant neuve. Ce n'est pas une
perte (le secours garde tout) mais ça se corrige, pas ça se découvre : `scripts/migrate_to_pg.py`
existe pour ce transfert — **je ne l'ai pas lancé** (PG est injoignable, et ça touche la base
de prod). À faire avant de compter sur le board en environnement connecté.

### 5.4 `kuzu` : réglé. `kuzu_world` : toujours à trancher
**Réglé** — `kuzu==0.11.3` est déclaré dans `requirements.txt`, et il est **vérifié** (pas
supposé) que `docker/api.prod.Dockerfile:25` et `docker/api.Dockerfile:15` installent depuis
ce fichier : la correction atteint donc l'image déployée. Si la neural map était vide en
ligne pour cette raison, elle ne le sera plus au prochain build.
**Toujours ouvert** — le sort de `04_GRAPHIFY/kuzu_world` (commité comme `kuzu_graph`, ou
ignoré) n'est pas tranché : c'est la question « où vit la vérité du jeu », elle vous revient.
Non commité par défaut pour ne pas la trancher à votre place.

---

## 6. Prochaine action — recommandation

**E2-02** (3 j, M — unicité sémantique des entités du monde) ou **E3-01** (1 j, S — extension
d'`ArtifactType`). Raison commune : ce sont les premiers tickets qui seront faits **sous
instrumentation**, donc les premiers à produire une vraie mesure `actual_*`. Faites-les avec
`task_run("E2-02")` — c'est là que le board commence à apprendre.

**À NE PAS enchaîner** : **E1-03** (estimation apprenante). Il n'a rien à apprendre :
`coverage()` vaut 0 %, aucun ticket n'a encore été fait sous mesure. Le construire maintenant
produirait un estimateur entraîné sur zéro donnée. Le refaire après 3-4 tickets mesurés.

**À ne pas faire tout de suite non plus** : E1-06 (vue console). Il demande de trancher §5.1,
et une décision d'ergonomie prise pour se débarrasser d'un conflit de fichiers est une
mauvaise décision.

**Avant tout ticket E7→E10** : affiner leurs dépendances au niveau du ticket dans l'audit
(cf. §4.6). Le chemin critique est aujourd'hui un plancher optimiste à cause de ça.

**Ordre du plan rappelé** : E1 + E2 d'abord → E6 (mesure) → E3/E4 en parallèle → E5 →
E7→E10 → E11 après le vertical slice.

---

## 7. État git au moment du handoff

Branche `feat/inference-platform-p1-p3`, **rien de commité** (ni cette session, ni la précédente).

Ajouté par cette session : `forge_backlog.py` · `test_forge_backlog.py` ·
`forge_task_ledger.py` · `test_forge_task_ledger.py` · `scripts/seed_rpg_backlog.py` ·
`05_STATE/kanban/board_rpg.json` · ce fichier.
Modifié par cette session : `forge_db.py` · `forge_db_fallback.py` · `forge_metrics.py` ·
`security_audit.py` · `state_ownership.py` · `requirements.txt` · `pytest.ini` ·
`00_CORE/forge_agents/AGENTS.md`.
Modifié hors dépôt : `04_GRAPHIFY/forge_fallback.db` (49 lignes dans `tasks`).

**Ne pas m'attribuer** : `forge_identity.py`, `pytest.ini`, `09_WEB/AGENTS.md`, `forge_mimo.py`,
`mimo_budget.py` (lignée S-03 / budget MiMo) ; le chantier neural map (`09_WEB/inference_api.py`,
`console/src/*`) ; `AUDIT_APTITUDE_RPG.md`, `HANDOFF_FORGE_RPG_READINESS.md`,
`KANBAN_SPRINT_6J.md` ; `world_kg.py`, `test_world_kg.py`, `04_GRAPHIFY/kuzu_world` (E2-01).

⚠️ `detect_changes()` n'a **pas** pu être lancé : **le MCP GitNexus n'est pas connecté** et
`.gitnexus/run.cjs` est absent. L'analyse d'impact a été faite à la main (grep des
consommateurs de `_ensure_schema` → 1 site interne ; `_DEEP_TABLES` → 4 sites internes + 1
référence dans `security_audit.py`) et vérifiée par les 100 tests. Relancer avant de commiter
si le MCP redevient disponible.

---

## 8. Méthode de travail

~25 tool calls. **Pas un seul subagent, aucun appel LLM automatisé** — tout est du code écrit
et testé directement. `Bash`+RTK / `Grep` ciblés ; `Read` partiel uniquement (jamais un fichier
entier, y compris sur l'`AGENTS.md` de 23 Ko).
Règles Forge actives : pas d'`ANTHROPIC_API_KEY` · DOX (AGENTS.md lu puis mis à jour) ·
analyse d'impact avant d'éditer un symbole existant.

⚠️ **Ne pas appliquer la règle ANTI-DÉRIVE « offload au tier FREE » de `CLAUDE.md`** : la
décision du 2026-07-25 a écarté TOUS les tiers gratuits. Il reste Claude (abonnement) et MiMo
(**payant**, 17 €/mois). Offloader « pour économiser » coûte désormais de l'argent.
