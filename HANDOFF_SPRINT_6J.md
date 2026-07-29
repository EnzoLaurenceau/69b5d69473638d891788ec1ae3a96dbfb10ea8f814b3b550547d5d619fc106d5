# HANDOFF — Sprint 6j « Rendre réel + déployer »

> But : reprendre le sprint depuis une **nouvelle fenêtre Claude** sans recharger tout le contexte.
> Ordre de lecture : ce fichier → `09_TASKS/KANBAN_SPRINT_6J.md` (le board) →
> `PLAN_PLATEFORME_INFERENCE.md` (annexes A→E) si tu touches au contrat `/v1`.
> `HANDOFF_PLATEFORME_INFERENCE.md` reste valable pour l'architecture des phases 1→4 ;
> **ce fichier-ci le remplace pour l'état opérationnel courant.**
> Dernière mise à jour : **2026-07-25**.

---

## 0. Contexte en une phrase

Les phases 1→4 de la plateforme d'inférence sont finies mais **rien n'a jamais été exécuté**
(Docker jamais lancé, Herald jamais passé, branche jamais fusionnée) et le graphe Kuzu est vide.
Le sprint de 6 jours transforme « fait mais jamais exécuté » en « tourne et se mesure », sans
ajouter la moindre surface nouvelle.

---

## 1. Décisions verrouillées (ne pas re-litiger)

Reprises des phases précédentes :
1. **Exécution** : 1 process / tenant → repli fichier `forge_store` suffit ; PG+Redis primaire différé.
2. **Console** : 5 vues (Dashboard, Orchestrateur, Router, Budget/RTK, Neural map).
3. **Offre** : interne / démo d'abord → pas de gate légal ni Stripe. Herald + `security_audit` restent.
4. **Déploiement** : Coolify (`docker-compose.prod.yml` prêt).

Prises le **2026-07-25** :

5. **PLUS AUCUN TIER LLM GRATUIT.** Les offres gratuites et proxies se sont montrés trop instables.

   | Fournisseur | Statut |
   |---|---|
   | **Claude** | Abonnement Claude Code — raisonnement, orchestration, validation. Jamais d'API au token. |
   | **MiMo** | **Payant : 17 €/mois pour 11 Md tokens**, 4 Md consommés au 2026-07-25 → **~7 Md restants**. Moteur de volume, via Hermes. |
   | Gemini | Écarté — accès API **non inclus** dans l'abonnement AI Pro. |
   | Groq | Abandonné (instable). |
   | ds2api | Abandonné (proxy instable). |
   | Cerebras / OpenRouter | Retirés du code. |

6. **Tout retirer du routeur** (ds2api + Groq) — décision utilisateur.
7. **Politique de repli quand Claude échoue** : soit échec franc, soit bascule MiMo.
   **Contrainte d'ordre qui en découle** — voir §6, c'est le point le plus important de ce handoff.

8. **Docker** : Docker Desktop installable en local → on valide les builds ici, pas en prod.
9. **Herald** : sous-module rempli et compilé **en local**. Rien n'est envoyé à un service externe.
10. **Budget MiMo** : lu via l'API/dashboard MiMo (endpoint à confirmer dans la config).

**Cap au-delà du sprint** : compléter Hermes/MiMo avec d'autres **API payantes**, puis
éventuellement louer un **serveur GPU/VPS** hébergeant un modèle pour finir l'architecture.
Objectif final évoqué : construire un jeu AAA à 100 %. Hors périmètre du sprint, mais c'est la
direction que sert ce socle.

---

## 2. État d'avancement

Board machine : `05_STATE/kanban/board.json` · vue lisible : `09_TASKS/KANBAN_SPRINT_6J.md`
Reprendre par : `python 00_CORE/forge_dispatch/kanban.py status`

**Fait (4 / 24)** — **J1 est bouclé.**

| ID | Résultat |
|---|---|
| **S-01** | Les 4 portes re-passées et **vertes pour de vrai** (pas supposées) : `state_ownership` PORTE OK (73 écrivains / 285 sites, tenant migrés 32/32, 0 non classé) · `security_audit` PORTE OK (9 HIGH tous revus, 0 CRITICAL) · **86 passed** · console 0 warning / build vert |
| **S-02** | `/v1/router/tiers` ne ment plus. L'état est **lu** (clés réellement configurées) au lieu d'être déclaré. Contrat : `free_tier_available: false`, Claude=`subscription`, MiMo=`paid`, Gemini/Groq/ds2api/Cerebras=`removed`. Bandeau console « chaque token déchargé est facturé ». **87 passed** (+1), lint 0, build vert |

| **S-03** | Compteur budget **fournisseur** MiMo réel : `mimo_budget.py` (plan mensuel, ledger, `BudgetExceeded`), `mimo_call` **débite** le plan à chaque appel, `GET /v1/budget/mimo`, carte console. Le rapport dit **d'où sort son chiffre** (`source: remote\|local\|declared`) — aujourd'hui `declared`, et la vue l'affiche en toutes lettres. **100 passed** (+13), lint 0, build vert, **vue ouverte dans un navigateur et vérifiée** |

| **S-04** | Board branché : `/v1/orchestrator/board` renvoie des **colonnes** (`todo/doing/done/blocked`) au lieu d'une liste à plat, et `Orchestrator.tsx` les affiche — le run en direct reste une carte à part, dans la colonne de son état. Les deux chemins de board sont réconciliés **sans fuite** : repli GLOBAL uniquement si une seule identité existe, et **annoncé** (`scope`). Vérifié à l'écran : `à faire 20 / terminé 3 / bloqué 1`. **102 passed** (+2) |

**Prochaine tâche : S-05 → S-06 → S-07** (l'hémorragie MiMo). C'est le morceau le plus
rentable du sprint et il est entièrement débloqué : le compteur de S-03 rend le gain de
S-06 mesurable, et `mimo_budget.check()` est l'accroche toute prête de S-07.

> S-03 a aussi débloqué deux pannes réelles trouvées **en exécutant**, détaillées dans
> `09_TASKS/KANBAN_SPRINT_6J.md` §« Ce que S-03 a fait tomber au passage » :
> l'API renvoyait **401 sur tout** (BOM UTF-8 dans `tenants.json`), et les barres de quota
> de la vue Budget étaient **invisibles** (contrat serveur ≠ attente console).

---

## 3. Environnement (pièges déjà rencontrés — vérifiés)

- **Python PAS sur le PATH.** Le `python` de bash/PowerShell est le stub Microsoft Store et échoue.
  Utiliser le chemin complet :
  `C:\Users\Jack\AppData\Local\Programs\Python\Python311\python.exe` (3.11.9).
  Le **Bash tool n'a pas de python** → passer par **PowerShell**.
- **node/npm** : dispo (node v24.16.0, npm 11.13.0). `console/` a un `package-lock.json` commité.
- **Docker** : absent du shell à ce jour → S-12 doit l'installer avant J4.
- **Kuzu** : `ModuleNotFoundError: kuzu` → le graphe réel est **vide**. Toute vérif de la neural
  map passe encore par le bouton « voir un exemple » (2400 nœuds **synthétiques**). S-08 corrige.
- **GitNexus MCP/CLI** : absent → analyses d'impact faites **manuellement** (lecture ciblée).
- **`pytest.ini` : `testpaths` est une ALLOWLIST.** Un `test_*.py` non listé n'est jamais
  collecté — il ne casse rien et ne prouve rien. Vérifié : `test_mimo_budget.py` a tourné
  vert « à côté » de la CI jusqu'à son ajout. Tout nouveau fichier de test doit y figurer.
- **JSON écrit depuis PowerShell = BOM UTF-8.** C'est ce qui mettait `/v1` à **401 sur
  tout** (`forge_identity` lisait en `utf-8` strict). Corrigé en `utf-8-sig` à la lecture.
  Si un registre `05_STATE/*.json` provoque une panne inexplicable, vérifier ses 3 premiers
  octets (`EF BB BF`) avant toute autre hypothèse.
- **Un worktree git vit dans le dépôt** (`.claude/worktrees/<nom>/`) : c'est une copie
  complète. `state_ownership.py` la scannait et voyait 73 modules « non classés » —
  faux positifs sur des doublons. Ajouté aux `SKIP_DIRS`.
- **Monter la pile en local pour vérifier une vue** (ça marche, fait le 2026-07-25) :
  API `& $PY 09_WEB/server.py` (:7777, `PYTHONPATH=00_CORE;09_WEB`), console via
  `preview_start` sur la config `console` de `.claude/launch.json` (:5273, proxy `/v1`),
  puis coller le jeton de `05_STATE/identity/.local_token` dans l'écran de login (pattern
  du setter natif ci-dessous — `preview_fill` seul ne déclenche pas l'`onChange`).
- **`.env` et `05_STATE/` sont gitignorés.** Token local de test :
  `05_STATE/identity/.local_token` (généré par `scripts/seed_local.py`, jamais commité).
- **Deux chemins de board**, piège réel découvert en écrivant le kanban :
  `05_STATE/kanban/board.json` (GLOBAL, lu par le CLI sans tenant) et
  `05_STATE/tenants/<id>/kanban/board.json` (lu par l'API, qui a un tenant en contexte).
  Le board du sprint est au chemin GLOBAL. **Réconcilié en S-04** : l'API lit le board du
  tenant et ne retombe sur le GLOBAL que si une seule identité est enregistrée (ou opt-in
  `FORGE_BOARD_GLOBAL_FALLBACK=1`), en l'**annonçant** via `scope`. Le fichier n'a pas bougé.
- **`preview_fill` sur input contrôlé React** ne déclenche pas toujours l'`onChange`. Pattern qui marche :
  ```js
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  set.call(input, valeur);
  input.dispatchEvent(new Event('input', {bubbles:true}));
  ```
- **`preview_screenshot` peut timeout** sur une vue qui poll (neural map interroge `/v1/graph`
  toutes les 6 s) — le DOM/canvas reste inspectable via `preview_eval`.

---

## 4. Ce qui a été modifié cette session

### Session S-03 (2026-07-25, la plus récente)

| Fichier | Changement |
|---|---|
| `00_CORE/forge_agents/mimo_budget.py` *(nouveau)* | Plan d'abonnement MiMo : période = **mois calendaire** (pas la fenêtre glissante de `forge_quota`), ledger `05_STATE/identity/mimo_budget.json` **hors espace tenant** (le plan est commun), `record/used/remaining/check/report`, `BudgetExceeded` calqué sur `QuotaExceeded`. Garde le **réel à côté du facturé** → S-05 a déjà son chiffre. Verrou processus (le swarm appelle depuis 6 threads). |
| `00_CORE/forge_agents/forge_mimo.py` | `mimo_call` débite le plan via `_record_budget()` — **point de passage unique** (batcher, swarm, judge y aboutissent tous). Échec de comptabilité absorbé : un appel déjà payé ne se perd pas parce que le ledger coince. |
| `00_CORE/forge_agents/forge_identity.py` | `_load()` lit en **`utf-8-sig`**. Corrige le 401 généralisé (cf. §3). |
| `00_CORE/tools/state_ownership.py` | `mimo_budget.py` classé `platform` ; `test_mimo_budget.py` `exempt` ; `SKIP_DIRS` ignore les worktrees git. |
| `09_WEB/inference_api.py` | `GET /v1/budget/mimo`. Commentaire : passera `_require_admin` le jour où la plateforme sert de vrais clients externes. |
| `console/src/api/{types,client}.ts` | `MimoBudget` + `BudgetSource` + `getMimoBudget`. **`QuotaReport` corrigé** : `limits`/`usage` sont deux dicts parallèles, pas une liste de `{used, limit}`. |
| `console/src/views/Budget.tsx` | Carte « plan mimo » (solde, barre, badge de **provenance**, écart round-up) + appariement `limits`/`usage` qui **fait enfin apparaître** les barres de quota. |
| `test_mimo_budget.py` *(nouveau)* + `pytest.ini` | 11 tests, dont « un `mimo_call` débite réellement le plan ». Ajouté à `testpaths` — sans quoi il ne tourne pas. |
| `test_inference_api.py` | Contrat `/v1/budget/mimo` + refus sans jeton ; **S-04** : le board renvoie des colonnes, et chaque statut kanban tombe dans la bonne (statut inconnu → visible dans `todo`). |
| `09_WEB/inference_api.py` *(S-04)* | `/v1/orchestrator/board` traduit `{tasks}` → `{columns, counts, scope}`. Repli GLOBAL gardé par `_board_global_fallback_allowed()` : autorisé seulement s'il n'y a **personne à qui fuiter** (≤ 1 tenant) ou opt-in `FORGE_BOARD_GLOBAL_FALLBACK=1`. |
| `console/src/views/Orchestrator.tsx` *(S-04)* | 4 colonnes alimentées par le board ; le run en direct reste une carte distincte, placée dans la colonne de son état ; badge quand le board servi est celui de l'opérateur. |

**Vérifié pour de vrai** : API montée sur :7777, console sur :5273, authentification avec le
jeton local, vue « budget & rtk » **ouverte et lue dans le navigateur** — elle affiche
`7.00 Md restants sur 11.0 Md`, le badge « déclaré, pas encore mesuré », « clé absente », et
la ligne d'avertissement. 0 erreur console. La dette « vue jamais ouverte » du S-02 est levée
pour Budget ; **Router n'a toujours pas été regardé**.

### Session S-01/S-02 (précédente)

| Fichier | Changement |
|---|---|
| `09_WEB/inference_api.py` | `router_tiers()` réécrit : état lu, plus déclaré. Ajout de `_key_present()` qui réutilise `forge_mimo._env` (sait déjà lire `.env`/`.env.local`), repli sur `os.environ`. Commentaire expliquant **pourquoi** chaque tier est écarté. |
| `console/src/api/types.ts` | `RouterTierKind` = `subscription \| paid \| removed` (plus de `free`). `RouterTier` gagne `wired`, `available`, `detail`. `RouterTiers` gagne `free_tier_available`. |
| `console/src/views/Router.tsx` | Réécrit : badge par nature (payant en **ambre** — ce qui coûte doit sauter aux yeux), détail par tier, tiers retirés grisés mais **affichés**, bandeau « aucun tier gratuit », alerte `clé encore active` si une branche abandonnée a encore sa clé. |
| `test_inference_api.py` | `test_router_tiers_ne_declare_aucun_tier_gratuit` — un retour à une liste statique optimiste casse la CI. |
| `09_TASKS/KANBAN_SPRINT_6J.md` | Board créé, puis mis à jour (S-02 done, S-24 ajoutée, conséquence « plus de tier gratuit »). |
| `05_STATE/kanban/board.json` | Board machine au schéma `forge_dispatch/kanban.py`, **vérifié lu par `kanban.py status`**. |

**Non vérifié** : la vue Router **n'a pas été ouverte dans un navigateur**. Le contrat est
prouvé par le test API et par `tsc` — mais le visuel n'a pas été constaté. C'est désormais
peu coûteux : la recette de montage est en §3, et l'API répond (elle ne répondait pas).

---

## 5. Le sujet coût — le plus important du sprint

Il reste **~7 Md de tokens MiMo** et plus aucune destination gratuite. Chaque token déchargé est
désormais facturé.

**Où part l'argent.** `forge_mimo.py` documente que MiMo facture **arrondi au bloc de 1000
tokens**. Deux chemins, un seul correct :

- ✅ `forge_spine.batch_call()` (`forge_spine.py:233`) passe par `MimoBatcher` → round-up payé **une fois**.
- ❌ `forge_swarm.run_swarm()` (`forge_swarm.py:381`) appelle `mimo_call` **une fois par unité de
  code**, dans un pool de 6 workers. Une unité de 200 tokens réels est **facturée 1000**.
  Un fichier découpé en 40 unités = 40 000 tokens facturés minimum.

Le batcher existe déjà et n'est simplement pas branché là — c'est du **câblage, pas de
l'invention** (S-06). `forge_spine.py:233` montre le pattern d'usage exact, fallback séquentiel compris.

**Aucun compteur n'existe.** `00_CORE/mimo_token_tracker.py` porte mal son nom : il compte des
prospects, octets et latence, et dit lui-même « Pas de TokenUsage LLM ». `forge_quota.py` compte
bien `llm_tokens` mais en **fenêtre glissante par tenant** — c'est un quota *client*, pas le
plafond d'abonnement *fournisseur*. Ce sont deux axes distincts : ne pas les confondre en S-03.

---

## 6. ⚠️ Ordre d'exécution — la contrainte à ne pas violer

Décision 6 dit « tout retirer ». Décision 7 dit « soit on échoue, soit on bascule sur MiMo ».
**Ces deux-là ne peuvent pas être appliquées tout de suite.**

Retirer ds2api et Groq de `_call_paid_tier` supprime le dernier filet sous Claude. Si le repli
choisi est MiMo, alors un incident Claude route automatiquement du volume vers du **payant** —
et aujourd'hui, ni compteur ni garde-fou n'existent pour le voir ou l'arrêter. On remplacerait
un repli instable par une fuite budgétaire silencieuse.

**Donc l'ordre est : S-03 → S-07 → S-24.** Jamais S-24 en premier.
**S-03 est fait** : `mimo_budget.check(cost, enforce=True)` lève `BudgetExceeded` et
`report()` donne le solde. S-07 n'a plus qu'à **appeler** ce contrat depuis `run_swarm` /
`batch_call` ; il n'y a plus rien à inventer côté comptage.

**Recommandation pour S-24** (à confirmer, non appliquée) : ce n'est pas un choix binaire.
Basculer sur MiMo **sous condition de budget**, et échouer franchement quand le budget est
épuisé — la bascule étant toujours **journalisée et comptée**, jamais silencieuse. On garde la
robustesse quand on peut se le permettre, et l'échec franc devient le comportement uniquement
quand continuer coûterait plus que s'arrêter. Ça compose exactement avec S-03 (le compteur) et
S-07 (le seuil), déjà planifiés.

---

## 7. Vérifications qui tiennent (au 2026-07-25)

```powershell
$PY = "C:\Users\Jack\AppData\Local\Programs\Python\Python311\python.exe"
& $PY 00_CORE/tools/state_ownership.py --check   # PORTE OK (75 écrivains, 32/32 tenant)
& $PY 00_CORE/tools/security_audit.py  --check   # PORTE OK (10 HIGH, 10 revus)
& $PY -m pytest -q                               # 102 passed
cd console; npm run lint; npm run build          # 0 warning/erreur, build vert
& $PY 00_CORE/forge_dispatch/kanban.py status    # ✅4 ⬜19 🚫1
```

**Les 4 portes sont vertes** à la fin de cette session. Deux exceptions ont été **signées
par l'utilisateur** en cours de route, sur des fichiers untracked venus d'un travail hors
sprint (RPG) qui avaient rendu deux portes rouges :
- `world_kg.py:370` → `REVIEWED_INJECTION` (`security_audit.py`). Site relu : `label` validé
  par `_label(…, WORLD_NODE_TABLES)`, clés filtrées contre `allowed`, valeurs par `_literal`,
  id par `world_key` puis `_esc` — même motif que `graph_db.py:348`.
- `scripts/seed_rpg_backlog.py` → classé dans `state_ownership.DECISIONS`.

**Ne pas supposer qu'elles le sont encore** : un fichier ou un symbole cité ici est une
affirmation au moment de l'écriture, pas une garantie. Re-vérifier. En particulier, la clé
de `REVIEWED_INJECTION` est `fichier:ligne` — déplacer du code dans `world_kg.py` refera
échouer la porte, volontairement.

Avertissement attendu, pas une régression :
`ForgeStore: état écrit dans l'espace GLOBAL (aucun tenant en contexte) — mode de transition`.
C'est le repli documenté de `state_path()` ; `FORGE_TENANT_STRICT=1` le transforme en erreur —
c'est ce que la CI utilise.

---

## 8. État git

- **Branche** : `feat/inference-platform-p1-p3`, **pas encore fusionnée**. `master` est à `1060c60`.
- 5 commits sur la branche (phases 1→4 + neural map v2/v3). Le travail des sessions de
  sprint (S-01, S-02, S-03, kanban, handoff) **n'est pas commité** — aucun commit n'a été
  demandé.
- **Pas de remote configuré** — tout est local.
- **Sous-modules NON touchés et volontairement exclus** : `nexus`,
  `07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills` (apparaissent en `m`, ce n'est pas un oubli).

---

## 9. Règles Forge à garder actives

TOKEN ESTIMATE avant / ACTUAL après · `impact` avant édition de symbole (GitNexus absent → lecture
ciblée manuelle) · RTK + context-mode sur les sorties de commande · microservices par défaut ·
artefacts > 10 lignes → fichier · **jamais de commit sans demande explicite** · ne jamais commiter
les sous-modules non touchés.

⚠️ Toute nouvelle requête Cypher à labels en f-string dans `graph_db.py` doit être déclarée dans
`REVIEWED_INJECTION` (`00_CORE/tools/security_audit.py`), sinon la porte casse la CI.

⚠️ `CLAUDE.md` est **faux** sur les tiers LLM (il impose « offload au tier FREE », qui n'existe
plus, et écrit `LLMTier.FREE` alors que l'énumération n'a que `HAIKU`/`SONNET`/`OPUS`).
Correction planifiée en **S-21** — d'ici là, ne pas appliquer cette règle telle quelle.
