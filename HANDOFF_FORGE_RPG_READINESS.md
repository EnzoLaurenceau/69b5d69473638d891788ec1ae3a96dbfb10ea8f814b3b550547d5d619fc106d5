# HANDOFF — Aptitude de la Forge à produire un RPG (reprise session)
> Créé le 2026-07-25 · Branche `feat/inference-platform-p1-p3` · Artefact principal :
> [`07_REPORTS/AUDIT_APTITUDE_RPG.md`](07_REPORTS/AUDIT_APTITUDE_RPG.md)
> **Lis d'abord l'audit, ce handoff n'en est que le mode d'emploi.**

---

## 0. Contexte en une phrase

L'utilisateur veut produire un RPG narratif AAA (inspiré du *Livre du Nouveau Soleil*)
**avec** la Forge, et a décidé — à raison — de **ne pas écrire une ligne du jeu** avant que
la Forge soit capable de le produire de façon fiable. Un audit d'aptitude a été demandé,
puis un plan Kanban pour combler l'écart. Les deux sont faits. Rien n'a été implémenté.

---

## 1. Décisions verrouillées (ne pas re-litiger)

1. **On construit la Forge avant le jeu.** Décision de l'utilisateur, confirmée par l'audit.
2. **Verdict = NO-GO** pour le développement du jeu. Maturité globale **5.9/10**.
3. **On étend l'existant, on ne réécrit rien.** ~60 % de l'infra est déjà là et bonne.
4. **Pas de subagents Claude Code.** L'utilisateur a explicitement constaté qu'ils coûtent
   ~60 k tokens pour 30 tool calls. L'audit entier a été fait en **9 tool calls** avec
   Bash+RTK, Grep, Glob. Reproduis cette méthode : `ls`/`grep -nE "^(class|def )"` sur les
   modules ciblés, jamais de `Read` de fichier entier, jamais de fan-out d'agents.
5. **Claude = jugement et validation.** Toute génération de volume passe par `forge_call`
   tier FREE (MiMo → Gemini → Groq → Cerebras). Cf. `CLAUDE.md` règle ANTI-DÉRIVE.

---

## 2. Ce que l'audit a établi (résumé exécutable)

**Les 4 constats qui décident de tout :**

| # | Constat | Preuve dans le code |
|---|---|---|
| 1 | Le KG existe mais **indexe le code, pas le monde** | `00_CORE/forge_agents/graph_db.py` — ontologie = `Agent/Project/Concept/Repository/Memory/Decision`. Aucun `Character/Quest/Item/LoreRule`. |
| 2 | La Forge **exécute des tâches, ne conduit pas un projet** | `00_CORE/forge_dispatch/kanban.py` = claim/complete/block ; `check_conflicts` collisionne au niveau *fichier*. Pas de DAG. `token_sprint_tracker.py` = budget tokens, pas vélocité agile. |
| 3 | **Pas de pipeline d'assets** | `design_assets.py` = palettes UI + doodles SVG + footers web. Seul générateur réel : `00_CORE/tools/product_bricks/generative_media/open_gen_ai.py` → `generate_image/generate_video`, sans style-lock. |
| 4 | **Audio = 0** | Aucune occurrence de musicgen / audiocraft / elevenlabs / tts / suno dans les ~100 modules de `00_CORE/forge_agents/`. |

**Points forts à ne surtout pas toucher :** RTK + `forge_fingerprint` + `semantic_cache` +
`forge_cache_orchestrator` + `tool_batcher` + `forge_quota` (9/10) · `forge_rag_optimized` /
`adaptive_rag` / `dataset_rag` (8/10) · `forge_observability` + `token_tracker` +
`agent_tracker` (8/10) · `harness_engine.py` (framework de gates — **à étendre, pas réécrire**) ·
`03_JURY/` · `forge_checkpoint_engine` + `forge_self_heal` · console React + neural map canvas v3.

---

## 3. Le plan — 11 epics, ~139 jours-Forge, 10 sprints

Détail complet (tickets, efforts, dépendances, DoD) dans l'audit §3. Vue courte :

| Epic | Titre | Effort | Niveau | Statut |
|---|---|---|---|---|
| **E1** | PROJECT-OS — backlog persistant, DAG, sprints, réaffectation | 18 j | 1 (bloquant) | ⬜ |
| **E2** | WORLD-KG — ontologie du monde dans Kuzu | 15 j | 1 (bloquant) | ⬜ |
| **E3** | ASSET-PIPE — concept → sprite → 3D → anim → Unity | 21 j | 1 | ⬜ |
| **E4** | AUDIO-PIPE — musique + SFX, from scratch | 15 j | 1 | ⬜ |
| **E5** | QA-GAME — build moteur, playtest, benchmark, screenshot | 16 j | 1 | ⬜ |
| **E6** | OBS-TASK — coût/tokens/modèle/score qualité par artefact | 10 j | 1 | ⬜ |
| **E7** | PROCGEN — quêtes, villages, donjons, dialogues, PNJ | 16 j | 2 | ⬜ |
| **E8** | SIM — quête terminable, détection d'incohérences | 10 j | 2 | ⬜ |
| **E9** | LORE-GUARD — cohérence lore/chronologie/relations | 8 j | 2 | ⬜ |
| **E10** | BALANCE — dégâts, économie, difficulté, progression | 10 j | 2 | ⬜ |
| **E11** | SHIP — trailer, Steam, succès, patch notes, i18n, doublage | ~12 j | 3 (plus tard) | ⬜ |

**Ordre imposé par les dépendances :** E1 + E2 en parallèle d'abord (E2 débloque E3, E7, E8, E9),
puis E6 (mesure), puis E3/E4 en parallèle, puis E5. E7→E10 ensuite. E11 après le vertical slice.

---

## 4. Prochaine action — 2 options proposées, aucune tranchée

L'utilisateur a été laissé sur ce choix. **Demande-lui laquelle avant de démarrer.**

**Option A — Injecter les ~60 tickets dans `05_STATE/kanban/`** au format lu par
`00_CORE/forge_dispatch/kanban.py`, pour que le board soit réel et claimable par la Forge.
Peu de risque, débloque le suivi. *Attention* : `kanban.py` n'a pas encore le schéma
étendu (epic, dépendances, effort) — soit tu injectes en dégradé, soit tu fais E1-01 d'abord.

**Option B — Attaquer E2-01 directement** (ontologie du monde dans Kuzu). C'est le ticket
qui débloque 5 epics sur 11. Fichier cible : `00_CORE/forge_agents/graph_db.py`.
⚠️ **Lance `impact({target: "ForgeGraphDB", direction: "upstream"})` avant d'éditer** —
c'est une classe centrale, le blast radius est probablement HIGH. La bonne approche est
**une seconde ontologie à côté**, pas une mutation du schéma existant (le KG code/agents
est en production et alimente la neural map de la console).

Ma recommandation si l'utilisateur ne tranche pas : **E1-01 puis Option A** — avoir un board
réel avant de produire 139 jours de travail est cohérent avec l'esprit même de sa demande.

---

## 5. Pièges connus / à savoir avant de coder

- **`graph_db.py` est en production.** La neural map de la console (commits `d41f2c0`,
  `e43eeec`) lit ce graphe. Ne casse pas le schéma existant — ajoute.
- **`harness_engine.py` (41,8 Ko)** : `ArtifactType` est un Enum ; l'étendre (E3-01) est
  un ticket S, mais chaque nouveau type demande ses gates dans `QualityGate`/`GateResult`.
- **`forge_dispatch/decomposer.py`** a déjà `estimate_task_tokens()` — E1-03 consiste à le
  brancher sur `forge_experience_db.py` pour qu'il apprenne, pas à réécrire l'estimateur.
- **RTK ne couvre que Bash**, pas les tools natifs Grep/Read (cf. mémoire
  `feedback_forge_subagent_rtk`). Explore via `Bash` pour bénéficier de la compression.
- **Gate copyright (E3-07)** : non négociable si le jeu est commercial. Aucun gate licence
  n'existe aujourd'hui sur les assets générés — c'est un risque juridique identifié §2 de l'audit.

---

## 6. État git au moment du handoff

Branche `feat/inference-platform-p1-p3`, **non commité** :
- ajouté : `07_REPORTS/AUDIT_APTITUDE_RPG.md` (l'audit), `HANDOFF_FORGE_RPG_READINESS.md` (ce fichier)
- déjà en cours avant cette session (chantier neural map, cf. `HANDOFF_PLATEFORME_INFERENCE.md`) :
  `09_WEB/inference_api.py`, `console/src/api/types.ts`, `console/src/views/NeuralMap.tsx`,
  `ANALYSE_SCREENSHOTS_NEURAL_MAP.md`, `CARTO_CONTENEURS_RAG_KAG.md`

**Aucun code de la Forge n'a été modifié par cette session** — uniquement de l'analyse et deux documents.

---

## 7. Le gate GO/NO-GO à ne jamais contourner

Le développement du RPG reste interdit tant que les **10 critères** de l'audit §5 ne sont pas
verts. Le plus discriminant : *« créer un marchand » produit concept → sprite → 3D → anim →
**fichier importé dans Unity**, sans intervention humaine*. Tant que celui-là est rouge,
tout développement de jeu produit de la dette qu'il faudra jeter.

---

## 8. Règles Forge à garder actives

TOKEN ESTIMATE avant / TOKEN ACTUAL après · RTK sur toute sortie de commande ·
pas d'`ANTHROPIC_API_KEY` (abonnement uniquement) · génération de volume → tier FREE ·
archi microservices par défaut · DOX : lire puis mettre à jour l'`AGENTS.md` le plus proche ·
`detect_changes()` avant tout commit · `impact()` avant d'éditer un symbole.
