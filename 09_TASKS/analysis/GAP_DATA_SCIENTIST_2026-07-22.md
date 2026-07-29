# Gap RÉEL vs ATTENDU — Agent Data Scientist (2026-07-22)

> Source de l'attendu : `09_TASKS/queue/Créer agent Data Scientist (2026-07-22).md`
> Méthode : chaque capacité annoncée confrontée au code lu, puis comblée.
> Verdicts : ✅ LIVRÉ · 🟡 PARTIEL · ⛔ ÉCARTÉ (avec justification)

---

## 0. Constat d'entrée (avant cette session)

Ce qui portait le nom de « Data Scientist » dans la Forge était **une fonction de
23 lignes** : `agent_nodes.py:_ds_advisory()`. Elle lisait trois getters de
`forge_experience_db` (meilleur workflow, composants morts, sources
d'hallucination) et les collait dans le prompt de l'orchestrateur.

| Attendu (tâche) | Réel avant |
|---|---|
| Data lake unifié | ❌ 4 stores disjoints, jamais joints (`forge_metrics.jsonl`, `experience_db.json`, `tool_call_ledger.jsonl`, `agent_tracker/history.json`) |
| Détection d'anomalies | ❌ 0 occurrence de « anomal » hors `zsl_cyber.py` (sécurité, sans rapport) |
| Prévisions | ❌ 0 (le seul moteur de forecast, `neural_markov_engine.py`, est dans `09_ARCHIVE/`) |
| A/B testing | ❌ 0 occurrence de `ab_test` dans tout le dépôt |
| Optimisation auto | 🟡 routage `forge_llm` par tiers, mais aucune boucle pilotée par la mesure |
| Profilage d'agents | 🟡 `WorkflowScore` existait, mais pas de scorecard normalisée 0-100 |
| ML / RL | ❌ 0 |
| Carte post-tâche | ❌ 0 occurrence de `what_worked` |
| DuckDB / Parquet | ❌ 0 |

**Écart réel : ~85 % de la capacité demandée n'existait pas.** Le nom existait,
pas la fonction.

---

## 1. Ce qui est livré maintenant

Module : **`00_CORE/forge_agents/forge_data_scientist.py`** (~900 lignes,
stdlib uniquement, **0 token LLM** — c'est de la statistique, donc rien à
halluciner).

| # | Capacité attendue | Verdict | Implémentation |
|---|---|---|---|
| 1 | Event bus → Data lake | ✅ | `DataLake` joint les 4 stores en un schéma unique `Observation` (22 champs). 1 124 observations réelles sur 27,6 j. |
| 2 | Postgres / DuckDB / Parquet | ✅ | `export_warehouse()` : JSONL toujours, DuckDB + Parquet si la lib est présente, dégradation propre sinon (pas de dépendance dure) |
| 3 | Détection d'anomalies | ✅ | `AnomalyDetector` — z-score robuste (MAD, Iglewicz-Hoaglin), 5 métriques × 4 dimensions (global/model/agent/workflow), 4 niveaux de sévérité |
| 4 | Prévisions | ✅ | `Forecaster` — OLS + EWMA sur séries journalières, J+7 / J+30, et résolution quadratique de « budget épuisé dans N jours » |
| 5 | A/B testing | ✅ | `ABTester` — test de Welch + Cohen's d, `auto_smart()` choisit la première métrique réellement instrumentée |
| 6 | Profilage d'agents | ✅ | `AgentProfiler` — scorecard efficacité / fiabilité / coût / vitesse + composite, verdict `preferred\|ok\|watch\|avoid`. 43 sujets profilés sur données réelles |
| 7 | Optimisation automatique | ✅ | `OptimizationEngine` — règles explicites et auditables → `Recommendation(priority, category, action, rationale, expected_gain, confidence)` |
| 8 | Reinforcement Learning | ✅ (cadré) | `Policy` — bandit ε-greedy sur la récompense `qualité − coût − temps`, avec priorité cold-start et exploration **déterministe** (rejouable). Voir §3. |
| 9 | Carte post-tâche | ✅ | `post_task_card()` → contrat exact `{what_worked, what_failed, cost, time, recommendation, confidence}` + `tokens`, `success_rate`, `samples` |
| 10 | Dashboard | ✅ | 7 endpoints sur `09_WEB/server.py` + 16 nœuds `datascience` sur la carte neuronale |
| 11 | Chaîne de sous-agents data | ✅ | Matérialisée en classes : `DataLake` (engineer) → `AnomalyDetector`/`AgentProfiler` (analyst) → `Forecaster`/`ABTester` (scientist) → `Policy` (ML) → `OptimizationEngine` (optim) |
| 12 | Branchement décisionnel | ✅ | `agent_nodes._ds_advisory()` appelle désormais `DataScientist.advisory()` — l'analyse retourne dans l'orchestrateur, bornée à 6 lignes |

### Infrastructure volontairement écartée

| Attendu | Verdict | Raison |
|---|---|---|
| Kafka / NATS | ⛔ | `forge_event_bus.py` existe déjà et suffit au volume actuel (~40 exécutions/j). Ajouter un broker serait de l'infrastructure sans charge. YAGNI/ponytail. |
| Neo4j (relations entre agents) | ⛔ | GitNexus (83 150 symboles / 111 561 relations) et Graphify couvrent déjà le graphe. Redondance pure. |
| pgvector | ⛔ | Déjà présent côté `forge_db` — rien à ajouter pour l'analytique. |
| Deep learning / réseaux de prédiction | ⛔ | Voir §3 : avec 3 à 106 exécutions par agent, un réseau apprendrait du bruit. |

---

## 2. Deux bugs de vérité corrigés en cours de route

Le premier jet du module produisait **4 anomalies CRITICAL** et un A/B test
concluant. Les deux étaient faux :

1. **Fausse anomalie sur baseline nulle.** Les jours sans mesure étaient comptés
   comme `0`, donc toute première mesure devenait `+100 % vs baseline`.
   → Correction : un jour sans mesure est désormais **absent** de la série, et
   une baseline nulle interdit le calcul de delta (pas de division par zéro
   déguisée en anomalie).
2. **A/B test sur métrique non mesurée.** Le coût est nul partout (abonnement
   Claude + tiers gratuits), donc « 0 vs 0 » sortait comme comparaison.
   → Correction : si toutes les valeurs sont nulles des deux côtés, le test
   renvoie explicitement « métrique non instrumentée — test impossible ».

Ces deux corrections sont verrouillées par des tests de régression dédiés.

**Conséquence directe** : le score de santé est passé de **A (100/100)** — faux —
à **C (57/100)** — vrai. Il est maintenant **plafonné par la couverture
d'instrumentation** : on ne déclare pas la Forge saine sur des métriques qu'on ne
mesure pas.

---

## 3. Le gap qui reste, et pourquoi il ne se comble pas par du code

Le Data Scientist est complet. **Ses entrées ne le sont pas.**

```
Couverture d'instrumentation mesurée : 27,6 %
  cost_usd            0,0 %      ← aucune ligne ne porte de coût
  quality             0,0 %      ← aucun score qualité émis
  hallucination_score 0,1 %
  tokens_total        4,2 %
  latency_ms          2,6 %
  agent              ~100 %
  model              ~100 %
```

Sur 1 124 observations, **1 000 viennent du `tool_call_ledger`** — qui n'écrit ni
coût, ni latence, ni tokens. Le vrai ledger analytique
(`forge_metrics.jsonl`) ne compte que **53 lignes**.

Aucun algorithme ne compense une métrique absente. C'est pour cela que le module
**refuse de conclure** plutôt que d'inventer, et remonte lui-même la
recommandation P0 : *« Compléter l'instrumentation des champs : cost_usd,
latency_ms, tokens_total, hallucination_score, quality »*.

**Action restante (hors périmètre de ce module)** : appeler
`forge_metrics.observe()` dans `forge_llm`, `harness_engine` et les nœuds
LangGraph. C'est ~10 points d'instrumentation. Une fois faits, prévisions,
anomalies et A/B s'allument **sans une ligne de code supplémentaire** côté Data
Scientist.

De la même façon, le RL est livré au bon niveau : un bandit ε-greedy converge
avec quelques dizaines d'essais et reste auditable. Passer à un modèle appris
n'aura de sens qu'après plusieurs milliers d'exécutions **instrumentées** — pas
avant.

---

## 4. Vérification

```
python -m forge_agents.test_forge_data_scientist     → 24 tests, OK
python -m forge_agents.forge_data_scientist report   → santé C (57/100)
```

Les tests couvrent explicitement les modes d'échec dangereux : fausse anomalie
sur baseline nulle, verdict A/B sur métrique vide, santé A sans instrumentation,
carte post-tâche inventée sur lake vide.

## 5. Surface exposée

| Endpoint | Rôle |
|---|---|
| `GET /api/datascience/report` | rapport complet (+ persistance `05_STATE/data_scientist_report.json`) |
| `GET /api/datascience/anomalies` | anomalies filtrées par sévérité |
| `GET /api/datascience/forecast` | prévisions coût/tokens/latence/échec |
| `GET /api/datascience/scorecards` | scorecards agent ou modèle |
| `GET /api/datascience/abtest` | A/B auto ou comparaison explicite |
| `GET /api/datascience/recommendations` | recommandations priorisées P0/P1/P2 |
| `GET /api/datascience/choose` | routage appris (bandit) |
| `POST /api/datascience/card` | carte post-tâche |

CLI : `python -m forge_agents.forge_data_scientist {report,anomalies,forecast,profile,abtest,card,choose,export,advisory}`
