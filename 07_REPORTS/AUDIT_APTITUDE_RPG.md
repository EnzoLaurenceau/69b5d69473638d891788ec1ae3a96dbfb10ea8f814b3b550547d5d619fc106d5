# AUDIT D'APTITUDE — La Forge → RPG narratif AAA
> Date : 2026-07-25 · Scope : capacité de la Forge à produire un RPG de façon autonome.
> Méthode : lecture du code réel (`00_CORE/forge_agents/` 100 modules, `00_CORE/forge_dispatch/`,
> `03_JURY/`, `04_GRAPHIFY/`, `05_STATE/`, `.github/workflows/`). Aucun subagent.

## ⛔ VERDICT : **NO-GO** pour le développement du jeu

Score global de maturité : **5.9 / 10**. La Forge est excellente sur ce qui est *invisible*
(orchestration, tokens, mémoire, RAG, QA code) et **quasi nulle sur ce qui fait un jeu**
(assets, audio, moteur, gestion de projet longue durée, ontologie narrative).

Le risque n°1 n'est pas technique, il est structurel : **la Forge sait exécuter une tâche,
elle ne sait pas conduire un projet de 18 mois.** Sans E1 et E2 ci-dessous, tout le contenu
généré dérivera (incohérences de lore, doublons, quêtes non terminables) et il faudra tout jeter.

---

## 1. MATRICE DE MATURITÉ

| # | Domaine | Note | Ce qui existe (fichiers réels) | Lacune bloquante pour un RPG |
|---|---|---|---|---|
| 1 | **Orchestration** | 7/10 | `run_forge.py`, `forge_graph.py` (LangGraph), `forge_dispatch/decomposer.py`, `forge_swarm.py`, `forge_team.py`, `forge_router_agent.py` | Orienté *one-shot task*. Aucun état projet persistant multi-sessions. Pas de DAG de dépendances. |
| 2 | **Agents** | 5/10 | 9 personas `02_AGENTS/` (senior_dev, critic, research, scraper, legal…) + `AGENT_UNIVERSAL_TEMPLATE.md` | **Zéro persona game-dev** : pas de game designer, level designer, narrative designer, concept artist, sound designer, technical artist, balance designer. |
| 3 | **Skills** | 4/10 | `skills/` = 3 entrées (hexstrike, firecrawl, antigravity) + `agent_skills_patterns.py` | Aucun SKILL.md métier jeu. La règle "skills avant l'action" tourne à vide sur ce domaine. |
| 4 | **Outils** | 8/10 | `00_CORE/tools/` (rtk, security_audit, state_ownership, see_edit, mcpify, openhands), `auto_tool_generator.py` | Pas de wrapper Unity/Godot/Blender/ffmpeg/aseprite. |
| 5 | **Observabilité** | 8/10 | `forge_observability.py` (LangSmith), `token_tracker.py`, `agent_tracker.py`, `forge_metrics.py`, `tool_call_ledger.jsonl` (645 Ko live) | Traque *tokens & agents*, pas *artefacts*. Impossible de dire "le sprite du marchand a coûté X, score qualité Y, 3 retries". |
| 6 | **Pipelines** | 5/10 | `harness_engine.py` (`validate_code/website/bot/email/api`), `bbril_pipeline.py`, `forge_pxpipe.py` | `ArtifactType` ne connaît que code/web/email/API. Aucun type `SPRITE`, `MODEL_3D`, `ANIM`, `MUSIC`, `SFX`, `QUEST`, `DIALOGUE`. |
| 7 | **Mémoire** | 7/10 infra · 1/10 domaine | `graph_db.py` (Kuzu), `kb_manager.py`, `knowledge_curator.py`, `forge_shared_brain.py`, `forge_experience_db.py`, `memory_pruner.py` | **Ontologie = Agent/Project/Concept/Repository/Memory/Decision.** Pas de `Character`, `Quest`, `Item`, `Location`, `Faction`, `LoreRule`, `Event`, `DesignDecision`. C'est LE trou n°1. |
| 8 | **Génération d'assets** | 2/10 | `design_assets.py` = palettes UI, SVG doodles, footers web · `product_bricks/generative_media/open_gen_ai.py` = `generate_image()` / `generate_video()` sur service déployé | Rien du pipeline demandé : pas de concept art → validation → sprite/texture → 3D → rig → anim → export Unity. Pas de cohérence de style entre assets. |
| 9 | **Génération audio** | 0/10 | *(aucune occurrence de musicgen / audiocraft / elevenlabs / tts / suno dans le code)* | Pipeline entièrement à construire. |
| 10 | **Génération de code** | 6/10 | `agent_nodes.py` (71 Ko), `semantic_edit_engine/`, `harness_engine.py`, `gen_games.py` (mini-jeux HTML one-shot) | Python/JS/web only. Aucun C#/Unity, aucun GDScript, aucune notion de scène/prefab/ScriptableObject. |
| 11 | **QA** | 7/10 code · 0/10 jeu | `harness_engine.py` (quality gates), `03_JURY/` (personas + critic), `forge_no_mistakes.py`, `anti_hallucination.py`, `hallucination_judge.py`, `neuro_symbolic_guard.py` | Pas de build moteur, pas de playtest headless, pas de benchmark FPS/mémoire, pas de capture d'écran de validation. |
| 12 | **CI/CD** | 6/10 | `.github/workflows/ci.yml` (unique), `docker/`, Coolify (P4 fait) | Pas de runner GPU, pas de cache d'assets binaires (LFS/S3), pas de pipeline de build jeu. |
| 13 | **Validation** | 6/10 | `03_JURY/personas.json`, Herald (grade ≥ B), `legal_compliance.py` | Aucun critère de validation *artistique* ou *ludique*. Un jury qui note du code ne note pas une musique. |
| 14 | **Optimisation** | 9/10 | RTK, `forge_fingerprint.py`, `semantic_cache.py`, `forge_cache_orchestrator.py`, `lmcache_integration.py`, `tool_batcher.py`, `forge_quota.py`, `nmp_encoder.py` | **Point fort majeur.** Rien de bloquant. À étendre au cache d'assets (ne pas régénérer 2× le même sprite). |
| 15 | **Gestion documentaire** | 7/10 | Hiérarchie DOX `AGENTS.md` (11 fichiers), `CLAUDE.md`/`FORGE_REFERENCE.md` chargement à la demande | Pas de GDD (Game Design Document) vivant, versionné, requêtable. |
| 16 | **Base de connaissances** | 7/10 | `07_KNOWLEDGE_BASE/`, `kb_manager.py`, `knowledge_curator.py`, `multi_source_brain.py` | Rien sur le corpus source (Livre du Nouveau Soleil) : pas d'ingestion, pas de canon indexé. |
| 17 | **Knowledge Graph** | 7/10 infra | Kuzu 13 Mo `05_STATE/kuzu_graph`, GitNexus (83 k symboles), `04_GRAPHIFY/`, neural map console v3 | Même problème que #7 : le graphe indexe *le code*, pas *le monde*. |
| 18 | **RAG** | 8/10 | `adaptive_rag.py`, `forge_rag_optimized.py`, `rag_anything.py`, `dataset_rag.py`, `turbovec_brain.py`, re-ranking + guards | Prêt à l'emploi. Il lui manque juste un corpus jeu à indexer. |
| 19 | **Dépendances de tâches** | 4/10 | `decomposer.py` (`decompose_task`, `estimate_task_tokens`), `kanban.py` (`check_conflicts` par fichier) | Conflits détectés au niveau *fichier*, pas de graphe de dépendances, pas de chemin critique, pas d'ordonnancement. |
| 20 | **Sprints** | 3/10 | `token_sprint_tracker.py` = sprints de **budget tokens**, pas de sprints agiles | Pas de vélocité, pas de burndown, pas de replanification. |
| 21 | **Microservices** | 6/10 | `09_WEB/inference_api.py` (façade /v1), `nexus/`, `docker/`, console React | Aucun service dédié asset/audio/build. Tout serait monolithique par défaut. |
| 22 | **Sécurité** | 7/10 | `security_audit.py`, `state_ownership.py`, gates CI, Herald, CORS durci (P4) | Pas de gate licence/copyright sur les assets générés — **risque juridique réel** sur un jeu commercial. |
| 23 | **Reprise après erreur** | 7/10 | `forge_checkpoint_engine.py`, `forge_self_heal.py`, `fallow_guard.py`, `graphify_checkpointer.py`, `forge_db_fallback.py` | Reprise *intra-tâche*. Pas de reprise *projet* ("le sprint 12 a échoué → réaffecter"). |

**Moyenne : 5.9/10** — *écart-type énorme* : 9/10 sur l'optimisation, 0/10 sur l'audio.

---

## 2. LES 5 RISQUES QUI TUENT LE PROJET

1. **Dérive du lore** (proba haute, impact fatal) — sans KG narratif, l'agent #400 contredira l'agent #12. Détecté trop tard = milliers d'assets à refaire.
2. **Amnésie inter-sessions** — la Forge repart de zéro à chaque session ; sur 18 mois c'est du travail redondant permanent.
3. **Incohérence visuelle** — `generate_image()` sans style-lock produit 500 assets qui ne vont pas ensemble.
4. **Quêtes non terminables** — aucun simulateur : les bugs de design sont découverts par le joueur.
5. **Copyright asset/audio** — aucun gate. Un modèle entraîné sur du contenu protégé dans un jeu vendu = blocage commercial.

---

## 3. KANBAN — COMBLER LE GAP

Format : `[ID] Titre — effort(jours-Forge) · dépend de · complexité`
Colonnes : **BACKLOG → READY → WIP → REVIEW → DONE** (WIP limit = 3)

### 🟥 EPIC E1 — PROJECT-OS · *gestionnaire de projet autonome* (Niveau 1)
> Base : étendre `00_CORE/forge_dispatch/kanban.py` + `decomposer.py`, ne PAS repartir de zéro.

| ID | Ticket | Effort | Dép. | Complexité |
|---|---|---|---|---|
| E1-01 | Schéma `Task` persistant (id, epic, état, estimé, réel, assignee, artefacts, retries) en SQLite via `forge_db.py` | 2 j | — | M |
| E1-02 | **DAG de dépendances** + calcul du chemin critique + détection de cycles (remplace `check_conflicts` fichier-only) | 3 j | E1-01 | H |
| E1-03 | Estimation auto : brancher `decomposer.estimate_task_tokens` + historique réel (`forge_experience_db.py`) → estimation apprenante | 2 j | E1-01 | M |
| E1-04 | Moteur de sprints agiles (vélocité, burndown, replanification) — distinct de `token_sprint_tracker` | 3 j | E1-02 | M |
| E1-05 | **Réaffectation sur échec** : politique retry → agent alternatif → escalade humaine, adossée à `forge_self_heal.py` | 3 j | E1-01, E6-01 | H |
| E1-06 | Vue Kanban dans la console React (réutiliser le rendu canvas de la neural map v3) | 3 j | E1-01 | M |
| E1-07 | Reprise projet multi-sessions : `resume_project()` qui rehydrate backlog + WIP + contexte | 2 j | E1-01 | M |
| | **Total E1** | **18 j** | | |

### 🟥 EPIC E2 — WORLD-KG · *mémoire globale du monde* (Niveau 1)
> Base : `graph_db.py` (Kuzu) est solide — il faut **une seconde ontologie**, pas un second moteur.

| ID | Ticket | Effort | Dép. | Complexité |
|---|---|---|---|---|
| E2-01 | Ontologie jeu dans Kuzu : `Character, Faction, Location, Quest, Item, Ability, Event, LoreRule, DialogueNode, DesignDecision` + arêtes (`KNOWS, OWNS, LOCATED_IN, REQUIRES, CONTRADICTS, DERIVED_FROM`) | 4 j | — | H |
| E2-02 | API d'écriture typée + **contrainte d'unicité sémantique** (empêche 2 PNJ identiques) via `forge_fingerprint.py` | 3 j | E2-01 | M |
| E2-03 | Ingestion du canon source (Livre du Nouveau Soleil) → `dataset_rag.py` + index de citations *(gate copyright : inspiration, jamais copie)* | 3 j | E2-01 | M |
| E2-04 | **GDD vivant** généré depuis le graphe (le doc est une *vue*, jamais la source de vérité) | 2 j | E2-01 | M |
| E2-05 | Brancher `forge_rag_optimized` + re-ranking sur le World-KG → tout agent interroge le monde avant d'écrire | 2 j | E2-01 | M |
| E2-06 | Journal des décisions de design (ADR jeu) + traçabilité "pourquoi ce choix" | 1 j | E2-01 | S |
| | **Total E2** | **15 j** | | |

### 🟧 EPIC E3 — ASSET-PIPE (Niveau 1)

| ID | Ticket | Effort | Dép. | Complexité |
|---|---|---|---|---|
| E3-01 | `ArtifactType` étendu (`CONCEPT, SPRITE, TEXTURE, MODEL_3D, RIG, ANIM, VFX`) dans `harness_engine.py` | 1 j | — | S |
| E3-02 | **Style-lock** : bible visuelle (palette + prompt-suffix + refs) stockée dans le World-KG, injectée dans chaque génération | 3 j | E2-01 | H |
| E3-03 | Wrappers outils : ComfyUI/SDXL (`open_gen_ai.py` à étendre), Blender headless, aseprite CLI → micro-scripts réutilisables | 5 j | — | H |
| E3-04 | Pipeline `concept → gate validation → sprite/texture → 3D → rig → anim → export Unity` en machine à états reprenable | 5 j | E3-01, E3-03 | H |
| E3-05 | Gate de validation d'asset (jury visuel : cohérence style, lisibilité, budget polygones/résolution) | 3 j | E3-04 | H |
| E3-06 | Cache d'assets par fingerprint sémantique (jamais régénérer 2× le même marchand) | 2 j | E3-04 | M |
| E3-07 | **Gate copyright/licence** sur tout asset généré (bloquant avant intégration) | 2 j | E3-04 | M |
| | **Total E3** | **21 j** | | |

### 🟧 EPIC E4 — AUDIO-PIPE (Niveau 1 — *from scratch*)

| ID | Ticket | Effort | Dép. | Complexité |
|---|---|---|---|---|
| E4-01 | Wrappers : MusicGen/AudioCraft (musique), TTS open-source (voix), ffmpeg (mix/loop/normalisation LUFS) | 4 j | — | H |
| E4-02 | Pipeline musique `description → génération → validation → bouclage sans couture → mixage → export` | 4 j | E4-01 | H |
| E4-03 | Pipeline SFX (banque catégorisée, variations, layering) | 3 j | E4-01 | M |
| E4-04 | Gate audio automatique (LUFS, clipping, qualité de boucle, durée) | 2 j | E4-02 | M |
| E4-05 | Liaison audio ↔ World-KG (chaque lieu/faction a son thème, chaque item son SFX) | 2 j | E2-01, E4-02 | M |
| | **Total E4** | **15 j** | | |

### 🟧 EPIC E5 — QA-GAME (Niveau 1)

| ID | Ticket | Effort | Dép. | Complexité |
|---|---|---|---|---|
| E5-01 | Runner build moteur headless (Unity batchmode ou Godot `--headless`) + parsing des erreurs de compilation | 4 j | — | H |
| E5-02 | Gates jeu dans `harness_engine` : compile → tests → lint C# → benchmark FPS/mémoire → screenshot | 3 j | E5-01, E3-01 | H |
| E5-03 | Capture d'écran automatique + comparaison visuelle de régression | 2 j | E5-01 | M |
| E5-04 | Playtest headless scripté (un bot joue la quête du début à la fin) | 4 j | E5-01, E8-01 | H |
| E5-05 | CI : job GPU + cache d'assets binaires (LFS/S3) dans `.github/workflows/` | 3 j | E5-01 | M |
| | **Total E5** | **16 j** | | |

### 🟨 EPIC E6 — OBS-TASK · *observabilité par tâche* (Niveau 1)

| ID | Ticket | Effort | Dép. | Complexité |
|---|---|---|---|---|
| E6-01 | Enregistrement unifié par tâche : durée, coût, modèle, tokens, succès/échec, score qualité, artefacts → étend `agent_tracker.py` + `tool_call_ledger.jsonl` | 3 j | E1-01 | M |
| E6-02 | Score qualité normalisé 0-100 par type d'artefact (code / asset / audio / narratif) | 3 j | E6-01 | H |
| E6-03 | Dashboard console : coût par epic, taux d'échec par agent, artefacts les plus chers | 3 j | E6-01, E1-06 | M |
| E6-04 | Alerte de dérive budget (seuil par sprint, coupe-circuit) | 1 j | E6-01 | S |
| | **Total E6** | **10 j** | | |

### 🟩 EPIC E7 — PROCGEN (Niveau 2)
`E7-01` générateur de quêtes (grammaire + contraintes KG) 4 j · `E7-02` villages/donjons 4 j · `E7-03` objets & loot tables 2 j ·
`E7-04` arbres de dialogues typés 3 j · `E7-05` PNJ (fiche complète liée au KG) 3 j — **16 j**, dépend de E2.

### 🟩 EPIC E8 — SIM (Niveau 2)
`E8-01` solveur d'atteignabilité de quête (la quête est-elle terminable ?) 4 j · `E8-02` détection d'incohérences (item requis inexistant, PNJ mort qui parle) 3 j ·
`E8-03` simulation de parcours joueur (N runs, stats) 3 j — **10 j**, dépend de E2 + E7.

### 🟩 EPIC E9 — LORE-GUARD (Niveau 2)
`E9-01` agent cohérence narrative (lore, chronologie, relations, continuité) 4 j · `E9-02` gate `CONTRADICTS` bloquant sur le KG 2 j ·
`E9-03` réutilisation de `neuro_symbolic_guard.py` + `hallucination_judge.py` sur le domaine narratif 2 j — **8 j**, dépend de E2.

### 🟩 EPIC E10 — BALANCE (Niveau 2)
`E10-01` modèle de combat (dégâts, courbes de stats) 3 j · `E10-02` économie (prix, drop rates, inflation) 3 j ·
`E10-03` courbe de difficulté & progression + auto-tuning par simulation 4 j — **10 j**, dépend de E8.

### ⬜ EPIC E11 — SHIP (Niveau 3 — *après le vertical slice, pas avant*)
Bandes-annonces · captures Steam · succès · patch notes · i18n · doublage IA — **~12 j**, à ne pas planifier maintenant.

---

## 4. ROADMAP EN SPRINTS (2 semaines / sprint)

| Sprint | Contenu | Livrable vérifiable |
|---|---|---|
| **S1** | E1-01→E1-03, E2-01 | Backlog persistant + DAG + ontologie monde en place |
| **S2** | E1-04→E1-07, E2-02, E2-06 | La Forge reprend un projet entre 2 sessions sans perte |
| **S3** | E2-03→E2-05, E6-01, E6-02 | Tout agent interroge le World-KG ; chaque tâche est mesurée |
| **S4** | E3-01→E3-03, E4-01 | Wrappers image/3D/audio opérationnels, style-lock défini |
| **S5** | E3-04→E3-07, E4-02 | **Pipeline asset complet : "créer un marchand" → export Unity** |
| **S6** | E4-03→E4-05, E5-01, E5-02 | Pipeline audio complet + build moteur automatisé |
| **S7** | E5-03→E5-05, E6-03, E6-04, E1-06 | QA jeu + dashboard complet |
| **S8** | E7 (procgen) | Quêtes/villages/PNJ générés et stockés dans le KG |
| **S9** | E8 + E9 | Quêtes simulées, terminables, cohérentes avec le lore |
| **S10** | E10 + **VERTICAL SLICE** | 1 zone jouable, 3 quêtes, 10 PNJ, musique, 100 % pipeline Forge |

**~20 semaines / ~139 jours-Forge** avant la première ligne de code du jeu à proprement parler.
Les Epics E1/E2/E6 sont parallélisables (`forge_swarm`) ; E3/E4 aussi. Chemin critique réel ≈ S1→S7.

---

## 5. CRITÈRES DE VALIDATION — GATE GO/NO-GO

Le développement du RPG n'est autorisé que si **les 10 critères** sont verts :

1. ☐ Un projet survit à 3 sessions Claude distinctes sans perte de contexte (`resume_project`).
2. ☐ Le DAG de dépendances ordonne ≥ 200 tâches sans cycle et calcule le chemin critique.
3. ☐ Une tâche échouée est réaffectée automatiquement et aboutit (test injecté).
4. ☐ Le World-KG contient ≥ 50 entités liées et répond à "quels PNJ connaissent X et vivent à Y".
5. ☐ Le gate `CONTRADICTS` bloque une contradiction de lore injectée volontairement.
6. ☐ « Créer un marchand » produit concept → sprite → 3D → anim → **fichier importé dans Unity**, sans intervention.
7. ☐ « Musique de taverne » produit une boucle sans couture, mixée, exportée, gate LUFS OK.
8. ☐ Le build du jeu compile, tourne, passe les tests et rend une capture d'écran en CI.
9. ☐ Une quête générée est prouvée terminable par le simulateur (10/10 runs).
10. ☐ Le dashboard donne coût + tokens + modèle + score qualité pour **chaque** artefact produit.

**Herald grade ≥ B, 0 issue CRITICAL, score sécu ≥ 70** sur les nouveaux services (gate Forge standard).

---

## 6. CE QUI EST DÉJÀ ACQUIS (ne pas reconstruire)

`RTK` + `forge_fingerprint` + `semantic_cache` + `tool_batcher` + `forge_quota` (coût maîtrisé) ·
`graph_db.py`/Kuzu (moteur KG) · `forge_rag_optimized`/`adaptive_rag` (RAG avec re-ranking) ·
`harness_engine` (framework de gates, à étendre pas à réécrire) · `03_JURY` (validation multi-personas) ·
`forge_checkpoint_engine`/`forge_self_heal` (reprise) · console React + neural map canvas (UI réutilisable) ·
`forge_swarm`/`forge_team` (parallélisation gratuite) · DOX `AGENTS.md` (discipline documentaire).

**~60 % de l'infrastructure est là.** Ce qui manque est le *domaine jeu* et la *conduite de projet*.
