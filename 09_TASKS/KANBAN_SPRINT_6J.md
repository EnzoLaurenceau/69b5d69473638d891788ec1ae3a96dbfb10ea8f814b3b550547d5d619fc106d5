# Kanban — Sprint 6 jours « Rendre réel + déployer »

> Ouvert 2026-07-25 · Branche `feat/inference-platform-p1-p3`
> Board machine : `05_STATE/kanban/board.json` (schéma `00_CORE/forge_dispatch/kanban.py`)
> Colonnes : `backlog` → `todo` → `doing` → `review` → `done` · `blocked`
> Estimations : XS (<30 min) · S (~1 h) · M (~½ j) · L (~1 j)
> Mode : **solo séquentiel** (Jack + session Claude), une tâche à la fois.

---

## Pourquoi ce sprint, et pas l'arsenal du briefing

Le méga-briefing (91 captures) demande OSINT, DataWave, career-ops, evals. Confronté au
dépôt, le constat s'inverse : **la Forge n'a pas un problème de surface manquante, elle a un
problème de réalité.**

| Ce qu'on croit | Ce que dit le code |
|---|---|
| Phases 1→4 livrées | Livrées mais **jamais exécutées** : `docker compose` jamais lancé, 2 Dockerfiles jamais buildés, Herald jamais passé, branche jamais fusionnée (`HANDOFF` §7) |
| Neural map à 2400 nœuds | Kuzu **non installé** → graphe réel vide. Les 2400 nœuds sont **synthétiques** (bouton « voir un exemple ») |
| Tiers LLM gratuits | **Il n'en reste aucun** (décision 2026-07-25). MiMo est facturé 17 €/mois ; Gemini n'a pas d'accès API sur l'abonnement AI Pro ; Groq et ds2api sont abandonnés (instables) ; Cerebras retiré. `inference_api.py` annonçait les quatre premiers en `free` |
| Budget MiMo suivi | `mimo_token_tracker.py` compte des **prospects et des octets**, pas des tokens (« Pas de TokenUsage LLM »). **4 Md / 11 Md consommés, suivis nulle part** |

### Conséquence majeure — il n'y a plus de tier gratuit

`CLAUDE.md` construit toute sa politique de coût sur « offload volume au tier FREE ».
**Cette destination n'existe plus.** Chaque token déchargé est désormais facturé, et la seule
soupape restante est MiMo — précisément celui qui facture par bloc de 1000 et dont le batcher
n'est pas branché sur le swarm.

Cela change le poids de trois tâches : **S-06 cesse d'être une optimisation** pour devenir le
principal levier de coût du dépôt ; **S-07** (garde-fou) devient une protection réelle et non un
confort ; **S-21** ne corrige plus une imprécision mais une règle qui coûte de l'argent.

> À noter pour S-21 : `CLAUDE.md` écrit `forge_call(prompt, tier=LLMTier.FREE)`, or l'énumération
> `LLMTier` ne contient que `HAIKU`, `SONNET`, `OPUS`. Suivre la doctrine à la lettre lève un
> `AttributeError`.

Cap annoncé par ailleurs : compléter Hermes/MiMo avec d'autres API payantes, puis éventuellement
un serveur GPU/VPS loué hébergeant un modèle — hors périmètre de ce sprint, mais c'est la
direction que sert le socle.

**Piste sur les 4 Md** : `forge_mimo.py` documente que MiMo facture **arrondi au bloc de 1000
tokens**. `forge_spine.batch_call():233` passe par `MimoBatcher` (round-up payé une fois), mais
`forge_swarm.run_swarm():381` appelle `mimo_call` **une fois par unité de code** dans un pool de
6 workers. Une unité de 200 tokens réels est facturée 1000. Le batcher existe déjà et n'est
simplement pas branché là.

**Ordonnancement** : J1→J3 n'ont aucune dépendance externe. J4→J5 (Docker, Herald, Coolify)
concentrent tout le risque et viennent après, délibérément. Si la queue glisse, le sprint a
quand même livré.

---

## Baseline vérifiée — 2026-07-25

Le `HANDOFF` §5 déclarait ces portes vertes « à la fin de la session précédente ». C'était une
affirmation datée, pas une garantie. Re-passées avant d'écrire une ligne :

| Porte | Résultat réel |
|---|---|
| `state_ownership.py --check` | **PORTE OK** — 73 écrivains / 285 sites, tenant migrés **32/32**, 0 non classé |
| `security_audit.py --check` | **PORTE OK** — 9 HIGH, **9 revus**, 0 CRITICAL |
| `pytest -q` | **86 passed** en 44 s (1 warning : `starlette.testclient` déprécié) |
| `console` lint + build | **0 warning / 0 erreur** (oxlint, 30 fichiers) · build vert (178 kB, 57 kB gzip) |

> Avertissement observé et attendu : `ForgeStore: état écrit dans l'espace GLOBAL (aucun tenant
> en contexte) — mode de transition`. C'est le repli documenté de `state_path()`, pas une
> régression. `FORGE_TENANT_STRICT=1` le transforme en erreur — c'est ce que la CI utilise.

---

## J1 — Vérité mesurable

> Aucune dépendance externe. On arrête de mentir avant d'ajouter quoi que ce soit.

| ID | Tâche | Fichiers cibles | Est. | Statut |
|---|---|---|---|---|
| S-01 | Re-passer les 4 portes déterministes avant tout — tout le sprint repose dessus | — (lecture seule) | XS | ✅ done |
| S-02 | `/v1/router/tiers` dit la vérité : état **lu** (clés réellement configurées) au lieu d'une liste statique. Claude → `subscription`, MiMo → `paid`, Gemini/Groq/ds2api/Cerebras → `removed`, `free_tier_available: false`. Bandeau console « chaque token déchargé est facturé » | `09_WEB/inference_api.py`, `console/src/api/types.ts`, `console/src/views/Router.tsx`, `test_inference_api.py` | S | ✅ done |
| S-03 | Compteur budget **fournisseur** MiMo (11 Md/mois, 4 Md consommés). Axe distinct de `forge_quota` qui compte par **tenant** en fenêtre glissante — ici c'est un plafond d'abonnement mensuel | `00_CORE/forge_agents/mimo_budget.py` *(nouveau)*, `forge_mimo.py`, `09_WEB/inference_api.py`, `console/src/views/Budget.tsx` | M | ✅ done |
| S-04 | Brancher le board orphelin : `/v1/orchestrator/board` renvoyait `{tasks:[]}` quand `BoardData` attend `{columns:{}}`, et `Orchestrator.tsx` construisait ses colonnes depuis les **runs**. Aligné + affiché, **4 colonnes** (`blocked` incluse), repli GLOBAL signalé | `09_WEB/inference_api.py`, `console/src/api/types.ts`, `console/src/views/Orchestrator.tsx` | S | ✅ done |

**DoD J1 — ATTEINT (2026-07-25)**. Le solde MiMo est lisible à l'écran *avec sa provenance*,
et **ce kanban s'affiche dans la console** : constaté dans un navigateur, colonnes
`à faire 20 / en cours 0 / terminé 3 / bloqué 1`, S-24 visible dans `bloqué` avec sa raison.
La Forge pilote son propre sprint depuis sa console.

**Comment les deux chemins de board ont été réconciliés (S-04)** — pas en déplaçant le
fichier, mais en assumant les deux régimes. Le CLI tourne sans tenant et écrit au chemin
GLOBAL ; l'API a toujours un tenant et lit `05_STATE/tenants/<id>/kanban/`. `/v1/orchestrator/board`
lit donc le board du tenant, et ne retombe sur le board GLOBAL que s'il n'y a **personne à
qui fuiter** (une seule identité enregistrée) ou sur opt-in `FORGE_BOARD_GLOBAL_FALLBACK=1`.
Le repli est **annoncé** dans la réponse (`scope: "global"`) et badgé dans la console. La
garde se referme d'elle-même le jour où un second tenant est créé — c'est voulu.

### Ce que S-03 a fait tomber au passage (2026-07-25)

Deux défauts trouvés en **exécutant** au lieu de relire. Aucun n'était visible en lecture :

1. **L'API `/v1` renvoyait 401 sur TOUT.** `05_STATE/identity/tenants.json` porte un BOM
   UTF-8 (écrit depuis PowerShell) ; `forge_identity._load()` lisait en `utf-8` strict,
   `json.loads` échouait sur le premier octet, `_load` levait, et **aucun jeton ne se
   résolvait plus**. La console n'a jamais pu s'authentifier sur cette instance. Corrigé
   par `utf-8-sig` en lecture (l'écriture reste en `utf-8` nu). Sur une plateforme
   Windows, tout ce qui écrit du JSON depuis PowerShell est concerné — à vérifier sur les
   autres registres si un 401/500 inexplicable réapparaît.
2. **Les barres de quota de la vue Budget étaient invisibles.** `forge_quota.report()`
   renvoie `limits` et `usage` comme deux dictionnaires parallèles ; `Budget.tsx`
   cherchait des objets `{used, limit}` — le filtre ne trouvait **jamais** rien et la
   carte restait vide sans erreur. Même famille que S-04 (board orphelin) : contrat
   serveur et attente console divergents, sans personne pour crier.

Deux autres points constatés, **non corrigés** (hors S-03, cf. §Vérification) :
`security_audit` est rouge sur `world_kg.py:370` (fichier untracked, pas de ce sprint), et
`test_mimo_budget.py` a dû être ajouté à `pytest.ini` — `testpaths` est une **allowlist** :
un fichier de test non listé ne tourne jamais, sans le moindre avertissement.

---

## J2 — Arrêter l'hémorragie MiMo

> Le sujet le plus rentable : chaque jour sans correctif coûte des tokens facturés.

| ID | Tâche | Fichiers cibles | Est. | Statut |
|---|---|---|---|---|
| S-05 | Instrumenter le round-up **avant** de corriger : facturé (`ceil(tok/1000)*1000` par appel) vs réel, sur un run swarm témoin. Sans chiffre avant, le gain après n'est pas démontrable | `00_CORE/forge_agents/forge_mimo.py`, `forge_metrics.py` | S | ✅ done |
| S-06 | Router `run_swarm()` via `MimoBatcher` au lieu de `mimo_call` par unité. **Ne rien inventer** : le batcher existe et `forge_spine.batch_call():233` montre le pattern exact, fallback séquentiel compris | `00_CORE/forge_agents/forge_swarm.py` | M | ✅ done |
| S-07 | Garde-fou budget : sous un seuil de solde mensuel, `run_swarm`/`batch_call` alertent puis bloquent. Même politique que `forge_quota.consume()` : **lever plutôt que tronquer en silence** | `00_CORE/forge_agents/mimo_budget.py`, `forge_swarm.py`, `forge_spine.py` | S | ✅ done |
| S-24 | Retirer ds2api + Groq de `_call_paid_tier` et câbler le repli. Décision utilisateur : **tout retirer**, repli = échec franc ou bascule MiMo. ⛔ **Bloquée par S-03 + S-07** — cf. encadré ci-dessous | `00_CORE/forge_agents/forge_llm.py` | M | ✅ done |

> **⚠️ Ordre obligatoire : S-03 → S-07 → S-24.**
> Retirer ds2api et Groq supprime le dernier filet sous Claude. Si le repli choisi est MiMo, un
> incident Claude route automatiquement du volume vers du **payant** — et aujourd'hui ni compteur
> (S-03) ni garde-fou (S-07) n'existent pour le voir ou l'arrêter. On remplacerait un repli
> instable par une **fuite budgétaire silencieuse**.
>
> **Recommandation** : ce n'est pas un choix binaire. Basculer sur MiMo **sous condition de
> budget**, échouer franchement quand le budget est épuisé, la bascule étant toujours journalisée
> et comptée — jamais silencieuse. On garde la robustesse quand on peut se le permettre, et
> l'échec franc devient le comportement uniquement quand continuer coûterait plus que s'arrêter.

**DoD J2** — Gain chiffré sur le même corpus, écrit dans ce fichier : X tokens facturés avant
→ Y après. Un dépassement de budget lève au lieu de brûler.

---

## J3 — Kuzu réel : le KAG cesse d'être synthétique

| ID | Tâche | Fichiers cibles | Est. | Statut |
|---|---|---|---|---|
| S-08 | `pip install kuzu` avec le Python complet (`…\Python311\python.exe` — le `python` du PATH est le stub Store, `HANDOFF` §3). Vérifier que `graph_db.py` ouvre la base | `requirements.txt` | S | todo |
| S-09 | Peupler le graphe réel : backfill de l'existant (findings confirmés, `graph.json` du fallback, `05_STATE`) **et** N cycles Forge réels → `knowledge_curator.curate()` écrit les 6 types de nœuds | `00_CORE/forge_agents/knowledge_curator.py`, script de backfill | M | todo |
| S-10 | `/v1/graph` sur données **réelles** : compteur, légende par type, pivot au clic sur un vrai nœud. L'exemple synthétique n'est plus la seule preuve | `console/src/views/NeuralMap.tsx`, `09_WEB/inference_api.py` | S | todo |
| S-11 | Curation — les 2 leviers de `CARTO_CONTENEURS_RAG_KAG.md` §Levier : (a) seuil de `score` dans `_sync_memory` (champ stocké et lu, **jamais utilisé comme seuil**) ; (b) `get_orphan_nodes()` est appelé (`curate():161`) mais **ne fait que générer une note** — le brancher sur une vraie suppression ou un flag `visible=false` | `00_CORE/forge_agents/knowledge_curator.py` | M | todo |

**DoD J3** — La map affiche des nœuds issus de vraies exécutions. Le graphe contient ce qui a
fait ses preuves, pas tout ce qui a été confirmé.

---

## J4 — Docker : du YAML jamais exécuté au conteneur qui tourne

> Premier jour à risque. Les Dockerfiles n'ont **jamais** été buildés — supposer qu'ils passent
> du premier coup serait naïf. C'est ici que le temps part.

| ID | Tâche | Fichiers cibles | Est. | Statut |
|---|---|---|---|---|
| S-12 | Docker Desktop installé et démarré : `docker version` + `docker compose version` répondent dans ce shell | — | S | todo |
| S-13 | `docker compose -f docker-compose.local.yml up` : PG + Redis + API démarrent. Première exécution réelle du socle | `docker-compose.local.yml` | M | todo |
| S-14 | `docker build` des 2 Dockerfiles prod (api, console). Corriger ce qui casse | `Dockerfile.api`, `Dockerfile.console` | L | todo |
| S-15 | `docker-compose.prod.yml` en local + smoke `/v1` bout-en-bout **dans le conteneur**. Les 3 endpoints admin deviennent enfin testables (`FORGE_ADMIN_TOKEN`) — jamais exécutés à ce jour | `docker-compose.prod.yml` | M | todo |

**DoD J4** — La plateforme tourne en conteneur ici. `/v1/admin/tenants` exécuté pour de vrai,
plus seulement relu.

---

## J5 — Herald + Coolify

| ID | Tâche | Fichiers cibles | Est. | Statut |
|---|---|---|---|---|
| S-16 | Remplir le sous-module `AsyncHerald/` (vide ici) et compiler en local. Décision prise : **rien ne sort de la machine**, pas d'envoi à l'API cloud | `AsyncHerald/`, `.gitmodules` | M | todo |
| S-17 | Passer le gate : grade ≥ **B**, 0 CRITICAL, sécu ≥ 70 (`CLAUDE.md` GATES BLOQUANTS). Dernier gate de doctrine non validé | selon retour Herald | M | todo |
| S-18 | Déployer sur Coolify : env, secrets, volumes persistants, images taguées. Créer un tenant réel via `/v1/admin/tenants` | `RUNBOOK_PLATEFORME_INFERENCE.md` | L | todo |
| S-19 | Smoke prod : agent lancé, `WS /v1/stream` en direct, métriques, quota 429, neural map sur le vrai graphe. Puis **tester le rollback** (image précédente, données survivent) | — | M | todo |

**DoD J5** — Un run lancé depuis la console déployée streame en direct. Le rollback est
**prouvé**, pas documenté.

---

## J6 — Fusion, doctrine, doc

| ID | Tâche | Fichiers cibles | Est. | Statut |
|---|---|---|---|---|
| S-20 | `git merge --ff-only` vers `master`. **Ne pas commiter les sous-modules non touchés** (`nexus`, `07_KNOWLEDGE_BASE/…` en `m` — volontaire, `HANDOFF` §4) | — | S | todo |
| S-21 | Corriger la doctrine `CLAUDE.md` : elle impose « tier FREE uniquement : MiMo → Gemini → Groq → Cerebras » alors que MiMo est **payant** et que Gemini/MiMo/OpenRouter sont **retirés du code**. Tant que ce texte est faux, chaque nouvelle session repart sur une prémisse fausse et re-crée le bug | `CLAUDE.md`, `FORGE_REFERENCE.md` | S | todo |
| S-22 | Actualiser `HANDOFF` (§3 : Docker et Kuzu ne sont plus absents ; §7 : reste ouvert) et `RUNBOOK` post-déploiement réel | 2 `.md` | S | todo |
| S-23 | DOX : `AGENTS.md` le plus proche de chaque dossier touché (`00_CORE/forge_agents/`, `09_WEB/`, `05_STATE/`) | `AGENTS.md` concernés | XS | todo |
| — | **Buffer** — absorbe le débordement de J4/J5 | — | — | — |

---

## Hors sprint (décidé, ne pas y revenir sans arbitrage)

| Élément | Raison |
|---|---|
| Arsenal OSINT (Shodan/Censys/SpiderFoot/recon-ng/Maltego) | **Aucun connecteur n'existe.** Surface net-new sur une base non shippée et à budget aveugle. Après le déploiement. |
| Lineage NiFi · clustering `role_tag` · recherche par attribut | Idées neural map notées (`HANDOFF` §6), non commencées. `role_tag` (9 valeurs, déjà calculé) est le plus rapide à greffer → 1ᵉʳ candidat du sprint suivant |
| Carte « zones jeu vidéo » | Bloquée sur une **décision produit** : qu'est-ce qu'une zone (`role_tag` / dossier / type) ? À trancher avant tout code |
| MCP control layer · LLM-as-a-judge · réveil MiroFish | Durcit le cerveau, invisible tant que rien ne tourne |
| Career-ops · Taipy · Youwee · Gmail Creator | Hors thèse plateforme d'inférence |
| Bascule PG+Redis primaire | Décision verrouillée #1 : différée, non bloquante |

---

## Vérification

```powershell
$PY = "C:\Users\Jack\AppData\Local\Programs\Python\Python311\python.exe"
& $PY 00_CORE/tools/state_ownership.py --check   # PORTE OK
& $PY 00_CORE/tools/security_audit.py  --check   # PORTE OK
& $PY -m pytest -q                               # 102 passed (+ nouveaux tests S-06)
cd console; npm run lint; npm run build
```

> ⚠️ `pytest.ini` a un `testpaths` qui est une **allowlist explicite**. Un `test_*.py`
> nouveau mais non listé n'est jamais collecté — il ne casse rien, il ne prouve rien non
> plus. Tout test ajouté par ce sprint doit y figurer.

**Tests à ajouter — sinon le sprint n'est pas vérifiable :**
- ✅ `test_inference_api.py` : `/v1/router/tiers` ne renvoie plus `kind:"free"` pour MiMo (S-02) ;
  `/v1/budget/mimo` expose le plan fournisseur **et sa provenance** (S-03) ;
  `/v1/orchestrator/board` renvoie des **colonnes** (`blocked` comprise) et traduit chaque
  statut kanban, statut inconnu inclus — visible dans `todo`, jamais escamoté (S-04).
- ✅ `test_mimo_budget.py` (11 tests) : le dépassement **lève** (même contrat que
  `forge_quota.QuotaExceeded`), le point de départ déclaré ne se re-compte pas chaque mois,
  un ledger corrompu ne redevient pas un solde vierge, `report()["source"]` ne prétend
  jamais « mesuré » quand rien ne l'est, et **un `mimo_call` débite réellement le plan**
  (client HTTP doublé — aucun token dépensé pour prouver qu'on sait les compter).
- `forge_swarm` : N unités → **1** appel batché, pas N.

**Preuve de bout en bout (J5)** : depuis la console déployée → lancer un agent → événements en
direct via `WS /v1/stream` → run visible dans le board → nœuds ajoutés au graphe Kuzu visibles
dans la neural map → coût reflété dans Budget avec le solde MiMo à jour.

> ⚠️ Toute nouvelle requête Cypher à labels en f-string dans `graph_db.py` doit être déclarée
> dans `REVIEWED_INJECTION` (`00_CORE/tools/security_audit.py`), sinon la porte casse la CI.

**Règles Forge actives** : TOKEN ESTIMATE avant / ACTUAL après · `impact` avant édition de
symbole · RTK sur les sorties de commande · artefacts > 10 lignes → fichier ·
**jamais de commit sans demande explicite**.
