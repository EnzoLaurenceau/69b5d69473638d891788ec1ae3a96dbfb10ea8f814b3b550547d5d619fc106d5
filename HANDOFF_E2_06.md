# HANDOFF — E2-06 journal des décisions de design (ADR jeu)

> Suite de [`HANDOFF_E2_02.md`](HANDOFF_E2_02.md) · branche `master`
> Plan de référence : [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)

---

## 0. Ce qui a changé en une phrase

**Le monde sait désormais POURQUOI il est ainsi.** Chaque choix de design est un nœud
`DesignDecision`, chaque entité qui en découle porte un `DERIVED_FROM` vers lui — et
`E6-01 a produit sa première mesure réelle` (couverture 0 % → 16,7 %).

---

## 1. Livré

| Fichier | Rôle | Taille |
|---|---|---|
| [`00_CORE/forge_agents/world_decisions.py`](00_CORE/forge_agents/world_decisions.py) | Journal des décisions (nouveau module) | 437 l. |
| [`test_world_decisions.py`](test_world_decisions.py) | **27 tests, tous verts** | 286 l. |
| [`00_CORE/forge_agents/forge_task_ledger.py`](00_CORE/forge_agents/forge_task_ledger.py) | Correctif E6-01 : `claimed_start()` + `started_at` | +31 l. |
| [`test_forge_task_ledger.py`](test_forge_task_ledger.py) | 24 → **28 tests** | +4 tests |
| [`pytest.ini`](pytest.ini) · [`AGENTS.md`](00_CORE/forge_agents/AGENTS.md) | Enregistrement CI + contrat local | modifiés |

**Vérifications réellement passées** :
- `pytest` (suite complète) → **306 passed** (275 avant), aucune régression ;
- **test de mutation** : deux régressions injectées volontairement (retrait de la fusion,
  retrait de la déduplication d'arêtes) tuent **exactement** les tests censés les
  attraper (2 puis 1 échec), fichier restauré et vert. La suite mord ;
- sonde manuelle contre le vrai moteur Kùzu : 12 comportements observés, pas déduits ;
- `security_audit.py --check` → **PORTE OK** (14 HIGH, 14 revus) ;
- `state_ownership.py --check` → **PORTE ÉCHEC**, 2 fichiers, cf. §4.2.

---

## 2. Les trois décisions d'archi à ne pas re-litiger

1. **Module à côté, PAS dans `upsert()` — l'inverse d'E2-02, délibérément.** E2-02
   protégeait un invariant, donc devait être incontournable. Ici il n'y a aucun invariant :
   `kg.add_decision()` en direct reste légitime (une décision qui n'affecte encore rien).
   Le raisonnement d'E2-02 ne se transpose pas mécaniquement, et `world_kg.py` reste sur
   son seul sujet.
2. **Zéro octet d'ontologie touché.** `DesignDecision` et `DERIVED_FROM` existaient depuis
   E2-01. En particulier, « remplacée par » est une **arête** portant `context="supersedes"`
   et non un `"superseded"` ajouté à `STATUS_KINDS` — cette constante est partagée par les
   10 types, et un `Character` « superseded » ne veut rien dire.
3. **`affects` est tout-ou-rien, vérifié avant la moindre écriture.** Raison en §4.1.

---

## 3. Surface d'API

```python
from forge_agents.world_decisions import get_journal, UntraceableDecisionError
j = get_journal("urth")

j.decide("perma-mort",
         question="Le joueur peut-il mourir définitivement ?",
         choice="Oui, hors sanctuaire",
         rationale="La tension retombe sinon",
         alternatives=["mort douce", "checkpoints"],
         decided_by="game-design",
         affects=[("Character", "Severian"), ("Quest", "La Griffe")])

j.why("Character", "Severian")     # → les décisions dont ce PNJ découle
j.affected_by("perma-mort")        # → ce que cette décision a produit
j.supersede_chain("perma-mort v2") # → ["perma-mort v2", "perma-mort"]
j.orphans()                        # → décisions sans conséquence (trou visible)
print(j.render())                  # → le journal en ADR markdown (une VUE)
```

Réviser une décision : nouvelle décision + `supersedes="<ancien nom>"`. Elle héritera de
l'unicité d'E2-02 (« perma-mort v2 » ressemble trop à « perma-mort ») — `allow_similar=True`
rend l'acte délibéré, ce qui est le comportement voulu.

---

## 4. Ce que la vérification a révélé

### 4.1 `WorldKG.link()` ment deux fois — c'est ce qui a dicté l'archi
Sondé contre le moteur, pas supposé :
- **cible inexistante → renvoie `True` et ne crée rien.** Le `MATCH` ne trouve rien, le
  `CREATE` ne fait rien, Kùzu ne lève pas. Un journal bâti naïvement dessus enregistrerait
  une décision en revendiquant une traçabilité qu'il n'a pas — le pire résultat possible
  pour un outil dont l'unique raison d'être EST la traçabilité ;
- **appelé deux fois → crée deux arêtes.** `why()` afficherait deux fois la même décision.

D'où : `affects` est résolu **avant** toute écriture (`UntraceableDecisionError`, rien
n'est écrit), et `_link_once()` déduplique. Les deux comportements sont verrouillés par
un test chacun.

### 4.2 Le premier jet effaçait le « pourquoi »
Re-`decide()` en ne précisant que le `choice` écrasait rationale, alternatives et auteur
avec des chaînes vides — visible au `render()` de la sonde. Pour un journal dont le produit
EST le « pourquoi », c'est la pire perte possible. Corrigé par une fusion (même doctrine
que les alias d'E2-02) : un champ non fourni n'efface jamais ce qui est écrit. Vaut aussi
pour `status` — une décision `validated` ne retombe pas en `draft`.

### 4.3 `perf_counter()` ne pouvait PAS mesurer un ticket — la cause du 0 %
Le handoff précédent traitait le `coverage()` à 0 % comme un manque de discipline. C'est
une cause **mécanique** : `task_run` mesurait `time.perf_counter()` autour d'un bloc `with`,
or un ticket réel s'étale sur des heures, des dizaines d'appels et plusieurs processus.
Preuve chiffrée : l'unique événement enregistré pour E6-01 dure **10,4 secondes** — la
durée du bloc, pas celle d'un ticket de 3 jours.

Correctif minimal : `claim()` écrivait déjà `started_at` en base depuis E1-01, personne ne
le relisait. `claimed_start(task_id)` le relit, `task_run(..., started_at=…)` mesure alors
le temps d'horloge depuis la PRISE. Sans `started_at`, comportement d'origine strictement
inchangé (test de non-régression dédié).

**Le bon usage est en deux temps** — et c'est celui qui a été suivi pour ce ticket :
```python
bl.claim("E2-07", "ma-session")                    # PREMIÈRE action du ticket
...                                                 # le travail
with task_run("E2-07", claim=False,
              started_at=claimed_start("E2-07")) as run:
    run.artifact(...)
```

### 4.4 L'interpréteur du PATH n'est pas celui du projet
`python` résout vers un venv `hermes-agent` dépourvu de `langgraph` : tout import de
`forge_agents` y échoue, et `pytest` y collecte **zéro test**. L'interpréteur du projet est
`C:/Users/Jack/AppData/Local/Programs/Python/Python311/python.exe`. Un `pytest` lancé sans
y prendre garde renvoie « no tests collected » — un vert apparent qui ne vérifie rien.

---

## 5. Points ouverts

### 5.1 La première mesure révèle que `variance()` compare deux unités
E2-06 : **0,0321 j mesuré (0,257 h) contre 1,0 j estimé, soit −96,8 %**. Le chiffre est
honnête — l'horodatage de prise est réel et couvre tout le ticket. Mais il mesure une
**session d'agent**, tandis que le `effort_days` de l'audit est une **estimation
humaine**. Les deux ne sont pas commensurables. **E1-03 (estimation apprenante) ne doit pas
être entraîné là-dessus sans trancher d'abord ce que `effort_days` signifie** — sinon il
apprendra qu'un ticket d'un jour prend un quart d'heure.

### 5.2 `actual_tokens` reste à 0, et c'est structurel
Le raisonnement de cette session tourne sur l'abonnement Claude et ne passe jamais par
`forge_metrics.record()` : aucun événement ne porte de tokens pour ce `task_id`. La durée
est mesurée, le coût ne l'est pas. `epic_costs()` affichera donc 0 tok / 0 $ pour tout
ticket fait en session d'agent — un trou visible, pas un zéro trompeur, mais à connaître
avant de bâtir E6-03 (dashboard) dessus.

### 5.3 Porte état : ne PAS appliquer le précédent évident
`full_graph_connect.py` et `living_graph_sync.py` restent non classés. Le précédent du
fichier classe tout `00_CORE/tools/*` en `exempt` (« outillage dev, lancé à la main »).
**Ce serait faux pour `living_graph_sync.py`** : c'est un cron quotidien qui lit cinq
sources depuis le `05_STATE` GLOBAL — `experience_db.json` (l. 175), `forge_metrics.jsonl`
(l. 230), `tool_call_ledger.jsonl` (l. 271), `agent_tracker/history.json` (l. 301),
`hallucination_events.json` (l. 143) — dont les modules propriétaires sont tous classés
**`tenant`**, et les projette dans un graphe Kùzu global, sans passer par
`forge_store.state_path()`. Or `exempt` signifie littéralement « pas de risque
inter-clients ». Tamponner `exempt` pour verdir la porte blanchirait une fuite potentielle
en coche verte : **la porte rouge est plus honnête**. Ticket séparé ouvert.

### 5.4 Toujours ouverts depuis E2-01/E2-02
- `_CONNECTIONS` n'évince toujours jamais (production ; les tests s'en protègent) ;
- le sort de `04_GRAPHIFY/kuzu_world` — « où vit la vérité du jeu » — non tranché.

---

## 6. Prochaine action

**E2-04 (GDD vivant, 2 j)** — ne dépend que d'E2-01, et le terrain est prêt : `render()`
d'E2-06 pose déjà la doctrine « le document est une VUE, jamais la source de vérité ».
Le GDD est la même idée à l'échelle du monde entier.

**À faire dès la première action** : `bl.claim("<id>", "<session>")`, puis clôture sous
`task_run(..., claim=False, started_at=claimed_start("<id>"))` — cf. §4.3. C'est ce qui a
fait passer la couverture de 0 % à 16,7 %.

**Toujours à ne pas enchaîner** : E1-03 (estimation apprenante) — non pas faute de mesure
désormais, mais à cause de §5.1 : il apprendrait sur deux unités incommensurables.
