# AGENTS.md — 00_CORE/forge_agents

## Purpose
Core Python package for the Forge's LangGraph meta-agent system: shared state schema, graph construction, dynamic agent generation, jury, checkpointing, batching, LLM routing, **quality harness**.

## Ownership
Owns: forge_state.py, forge_graph.py, agent_nodes.py, auto_complexification.py, mirofish.py, graphify_checkpointer.py, tool_batcher.py, forge_llm.py, kb_manager.py, openviking.py, token_tracker.py, prompt_architect.py, **ponytail.py**, **harness_engine.py**, **neural_markov_engine.py**, **legal_compliance.py**, **forge_spine.py**.

## Local Contracts
- `ForgeState` (forge_state.py) is the single shared TypedDict — any new cross-node field must be added here AND to `initial_state()`.
- All Graphify index side-effects go through `tool_batcher.get_batcher()` (batch_size=10 default) — never call `graphify_index()` per-item in a loop.
- Progress is persisted via `save_progress_checkpoint`/`load_progress_checkpoint`/`mark_step_done` (graphify_checkpointer.py) — every node that finishes a meaningful step must call `mark_step_done` and return `progress_done`/`progress_todo`/`progress_current_step`.
- LLM calls go through `forge_call()` (forge_llm.py), respecting the TIER 0-3 cost hierarchy in root CLAUDE.md — never call provider SDKs directly from a node.
- **Routing (forge_llm.py)** : moteur par défaut = **vrai Claude** (`_call_claude`, SDK anthropic, clé `ANTHROPIC_API_KEY`) ; FREE tier → Claude Haiku 4.5, tiers payants → Claude du tier. Kill switch `FORGE_CLAUDE_DEFAULT=0`. Sans clé → dégradation gracieuse vers le cascade gratuit (MiMo→Gemini→ds2api→Groq). **RTK n'est PAS dans la cascade LLM** — c'est le Rust Token Killer (compression de sorties de commandes) : cf. `00_CORE/tools/rtk.py` (`rtk_run`) + hook global `rtk init -g`.
- **Zero-redundancy gate (AAOS)** : `forge_call()` consulte `forge_fingerprint.get_fingerprint_store()` avant TOUT appel (tous tiers) — même tâche+contexte+version dans le TTL 7j → résultat rejoué, 0 token. Économies comptées dans `token_tracker.get_tracker().savings_summary()`. Kill switch : `FORGE_FINGERPRINT_OFF=1`. Classifier déterministe : `forge_fingerprint.classify_task()` / `compare_costs()` (Token Last Principle).
- **Un expert par micro-task (forge_team.py)** : `orchestrator_node` appelle `assemble_team(task, lead_name)` qui DÉCOMPOSE la task en micro-tasks (décomposition SÉMANTIQUE LLM `_semantic_decompose` FREE tier ; fallback split regex phrases/connecteurs si LLM échoue ou <2 ; max `MAX_MICRO_TASKS=6`) → `state["team"]` = {lead, specialists:[{name,mission}]} (chaque `specialist` = l'expert d'UNE micro-task ; {} si mono-micro-task). `dynamic_agent_node` (= le LEAD/synthétiseur) exécute via `run_team()` : pipeline où UN expert dédié exécute CHAQUE micro-task en voyant les résultats des précédentes (contexte partagé), puis le lead synthétise. Expert rappelé du roster (`kb_manager.lookup` @0.60) ou conçu JIT (`forge_prompt_architect`) ; conçu + score ≥ `PERSIST_SCORE_MIN=7.0` → auto-promu au roster (`kb_manager.add_skill_from_finding`). Self-check : `python -m forge_agents.forge_team`.
- **Quality→Data Acquisition (AAOS 92)** : `dynamic_agent_node` score < 5.0/10 → `dataset_rag.record_knowledge_gap()` (07_KNOWLEDGE_BASE/datasets/knowledge_gaps.json, pas de téléchargement auto). Qualité datasets : `dataset_rag.health_check()` (accept ≥80 / quarantaine 60-80 / reject <60) + `regression_guard()` avant ingestion. Self-check global : `python 00_CORE/test_aaos_wave.py`.
- **SPINE (forge_spine.py)** — colonne vertébrale du refacto (blueprint `00_CORE/blueprints/refacto_spine.md`). Unifie 3 choses, ne réécrit rien :
  1. **Honnêteté + HITL** : `should_escalate(state)` → escalade humaine si aveu d'ignorance (`is_unknown`/sentinelle `UNKNOWN:`), hallucination persistante (`revision_attempts >= MAX_REVISION_ATTEMPTS=2`), ou confiance < `CONFIDENCE_MIN=0.35` sur tâche à risque. Le graph route `anti_hallucination → escalate_human` (au lieu de boucler jusqu'au recursion_limit) ; `escalate_human_node` écrit dans `05_STATE/human_queue.json` via `escalate_to_human()` et stoppe le run (`human_pending=True`). La Forge DIT qu'elle ne sait pas au lieu d'inventer. `pending_human()` liste les demandes ouvertes.
  2. **Deliver gate** : `deliver_gate(target_dir, product_type)` = `legal_check` (bloquant) + herald (advisory). Appelé dans `dynamic_agent_node` juste après `_write_deliverables` — livrable non conforme → `NMP|DELIVER|BLOCKED` + escalade + score plafonné à 4.0. Fichiers écrits mais signalés non livrés.
     - **Herald (agent_nodes.py::herald_audit)** : audit sécurité déterministe (0 token LLM). Charge `00_CORE/tools/security_audit.py` et retourne `{grade: A-F, score: 0-100, http, injection, deps, issues, summary}`. Grading : HTTP surface (-40 max), injection HIGH (-30 max), deps vulnérables (-20 max). Grade ≥ B = passant, < C = advisory. Intégré dans `forge_spine.deliver_gate(with_herald=True)`. Le sous-module AsyncHerald (GitHub) a été supprimé — repo 404.
  3. **Cache/batch facade** : `cache_get/cache_set` (dédupe fingerprint+semantic, ne cache jamais un `UNKNOWN:`) ; `batch_call(prompts)` coalesce N micro-appels en 1 (MimoBatcher, fallback séquentiel) — à utiliser dans les nœuds qui bouclent. Le cache réponse est DÉJÀ universel via `forge_call`.
  Champs state ajoutés : `revision_attempts`, `confidence`, `needs_revision`, `revision_reason`, `human_pending`, `human_queue_id`, `deliver_blocked`, `deliver_reason`. Self-check : `python -m forge_agents.forge_spine`.
- **Legal gate (legal_compliance.py)** : `legal_check(path, product_type)` scanne le livrable (heuristiques mots-clés ; source de vérité : `00_CORE/blueprints/legal_compliance.md`) → `{grade, missing, violations, deliver_ready}`. `deliver_ready=False` = DELIVER BLOQUÉ (critique manquante, TODO-LEGAL, localStorage). S6.5 de la séquence MVP, avant MiroFish ; injecter `state['legal_grade']` au jury (persona Legal_Officer, grade < B → -2.0 pts). Types combinables (`"saas,chatbot"`). Self-check : `python 00_CORE/forge_agents/legal_compliance.py`.
- **World-KG (world_kg.py)** — ontologie du MONDE (E2-01, cf. `07_REPORTS/AUDIT_APTITUDE_RPG.md`). **N'est PAS une extension de `graph_db.py`** : `graph_db` indexe la Forge (Agent/Project/Concept/Repository) et est lu en prod par la neural map (`09_WEB/inference_api.py::_GRAPH_LABELS`) — y ajouter `Character`/`Quest` ferait remonter des PNJ dans la carte du code. Seconde ontologie, **seconde base Kùzu** (`04_GRAPHIFY/kuzu_world`, override `FORGE_WORLD_KG_PATH`), zéro octet touché dans `graph_db.py`. `_esc`/`_label`/`_num` sont en revanche IMPORTÉS de `graph_db` : une seule implémentation d'échappement, verrouillée par `test_graph_db_escaping.py` — ne jamais la dupliquer.
  - 10 nœuds (`Character, Faction, Location, Quest, Item, Ability, Event, LoreRule, DialogueNode, DesignDecision`) × 6 arêtes (`KNOWS, OWNS, LOCATED_IN, REQUIRES, CONTRADICTS, DERIVED_FROM`). Le DDL est **dérivé** de `_TYPE_PROPS` / `WORLD_EDGE_PAIRS` (`node_ddl`/`edge_ddl`, fonctions pures) : ajouter une propriété ou un couple se fait LÀ, jamais en DDL écrit à la main.
  - Identité déterministe `world_key(world_id, label, name)` = `{world}:{Label}:{slug}` (accents/casse/ponctuation neutralisés). Le cloisonnement multi-jeux est DANS la clé — Kùzu n'accepte qu'une colonne en PK. La connexion Kùzu est partagée **par chemin** (`_CONNECTIONS`) : Kùzu verrouille une base par processus, deux `WorldKG` sur le même fichier sans ce partage lèvent « Could not set lock on file ».
  - Garde-fous qui LÈVENT (jamais d'écriture avalée) : propriété hors whitelist, `canon` hors `CANON_KINDS`, `status` hors `STATUS_KINDS`, couple d'arête non déclaré. `_rows()` dépréfixe les alias Cypher (`n.hard` → `hard`) — les appelants ne connaissent pas l'alias de la requête.
  - `context_pack(label, name)` = le paquet que tout agent doit consommer AVANT d'écrire (entité + voisinage + règles de lore dures). Point d'accroche **branché par E2-05** (`world_rag.py` : langage naturel → entités → ce paquet) et prévu pour E7 (procgen). `contradictions()` / `chronology()` sont la matière première d'E9.
  - `all_edges()` (ajout E2-05) = TOUTES les arêtes du monde, **une requête par TABLE** et non deux par nœud : 2 087 ms → 27 ms sur 300 nœuds (×76), coût fonction des arêtes et non des nœuds. À préférer dès qu'on cartographie le monde entier — `world_gdd` appelle encore `neighbors()` nœud par nœud, c'est le prochain gain facile.
  - Dépendance : `kuzu` (0.11.3 vérifié, mode `rel_table` multi-couples ; repli `REL TABLE GROUP` pour < 0.7). **`kuzu` n'est déclaré dans AUCUN requirements/Dockerfile** — le graphe dégrade en silence là où il manque. Self-check : `python -m forge_agents.world_kg` · tests : `pytest test_world_kg.py` (33).

- **Backlog persistant (forge_backlog.py)** — E1-01. **Ne remplace pas `00_CORE/forge_dispatch/kanban.py`, il le précède** : le kanban JSON porte le WIP (qui tient quoi maintenant, verrou par fichiers) ; le backlog porte le *plan* (epic, dépendances, estimé vs réel, retries) et survit aux sessions. `to_kanban_board()` projette l'un vers l'autre — l'état `ready` du backlog devient `pending`, vocabulaire que `kanban.py` sait compter.
  - Stockage : table `tasks` du store unifié `forge_db`. **Aucune base ouverte en propre** — tout passe par `deep_insert`/`deep_query`, donc Postgres quand il est up (vraies colonnes + index `epic`/`state`) et secours SQLite `04_GRAPHIFY/forge_fallback.db` sinon, avec le dual-write et le WAL gratuits. Ajouter `"tasks"` à `_DEEP_TABLES` (forge_db_fallback.py) est **obligatoire** : sans ça `deep_insert` ignore les écritures SILENCIEUSEMENT (verrouillé par un test).
  - Le DDL Postgres est **dérivé** de `_TASK_PROPS` (`table_ddl()`, fonction pure) et injecté dans `forge_db._ensure_schema` par un import TARDIF (`forge_backlog` appelle `get_db()` — un import au chargement ferait un cycle). Ajouter une propriété se fait dans `_TASK_PROPS`, jamais en colonnes recopiées.
  - Garde-fous qui LÈVENT (même doctrine que `world_kg`) : propriété hors whitelist, `state` hors `TASK_STATES`, `complexity` hors `COMPLEXITIES`, **transition d'état illégale** (`_TRANSITIONS`), auto-dépendance, dépendance dupliquée, effort négatif, booléen sur champ numérique (`True == 1` en Python passerait sans garde explicite). `upsert_many` valide TOUT le lot avant d'écrire quoi que ce soit : un lot à moitié écrit est pire qu'un lot refusé.
  - **Asymétrie assumée sur les dépendances** : une dépendance vers une tâche encore inexistante est tolérée à l'écriture (injecter un plan impose des références avant-coureuses, sinon l'ordre du lot devient signifiant) mais **`claim()` LÈVE** si elle n'est pas satisfaite. Une dépendance inconnue n'est *jamais* considérée satisfaite. La rigueur se paie au moment où se tromper coûte quelque chose.
  - `_coerce_row` normalise la relecture : Postgres peut rendre `depends_on` en JSONB déjà décodé **ou en chaîne** selon le driver. Sans ça `ready()` comparerait une liste à une chaîne et déclarerait tout prenable — échec silencieux. `find_cycles()` est une DFS **itérative** (un backlog est déclaratif ; une récursion exploserait sur un plan mal saisi au lieu de le signaler).
  - `Backlog.SCAN_LIMIT` : on lit large et on filtre en Python. Le secours SQLite ne filtre que sur les `limit * 4` lignes les plus récentes (`forge_db_fallback.deep_query`) — déléguer le filtre au store tronquerait le backlog en silence.
  - Accroches : `ready`/`dependents_of`/`find_cycles` → **E1-02** (chemin critique) · `effort_days` vs `actual_days`, `est_tokens` vs `actual_tokens` → **E1-03** et **E6-01** · `retries`/`bump_retry`/`blocked` → **E1-05** · `to_kanban_board` → **E1-06**/**E1-07**. Self-check : `python -m forge_agents.forge_backlog` · tests : `pytest test_forge_backlog.py` (51).
  - Peuplement : `python scripts/seed_rpg_backlog.py` **parse** `07_REPORTS/AUDIT_APTITUDE_RPG.md` (49 tickets, 11 epics, 151 j dont un jalon E11 de 12 j) — il ne retranscrit pas. Ré-exécuter préserve la progression (l'audit possède le plan, la Forge possède l'avancement) ; `--force` remet à plat. La vue va dans `05_STATE/kanban/board_rpg.json` — **pas** `board.json`, occupé par le Sprint 6j — et n'est donc lue ni par `kanban.py` ni par `/v1/orchestrator/board` : la source de vérité interrogeable est la table `tasks` ; brancher la vue est E1-06.

- **Unicité sémantique du monde (world_kg.py)** — E2-02. La contrainte est DANS `upsert()`, pas dans une fonction d'aide à côté : un garde qu'on contourne en appelant `upsert` directement ne garde rien. Les 10 types en bénéficient, pas seulement `Character`.
  - **Pas construit sur `forge_fingerprint`**, malgré l'intitulé du ticket : ce module est un cache d'appels LLM (`make_fingerprint(prompt, system, tier)` → sha d'un prompt) et répond à « ai-je déjà payé cette requête ? ». Un sha n'a pas de voisinage — deux noms proches donnent deux hash étrangers. L'y brancher aurait donné une fausse garantie.
  - Trois étages, du plus sûr au plus flou : **clé exacte** (`world_key`, acquis E2-01) → **alias déclaré** (`resolve()`) → **proximité** (`find_similar()`). `resolve()` ne résout JAMAIS sur une ressemblance : fusionner deux entités que personne n'a décidé de fusionner est pire que le doublon. La ressemblance alerte, elle n'arbitre pas.
  - `similarity()` = Jaccard sur tokens **relevé par l'inclusion** (`max` des deux). Jaccard seul donne 0,33 à « Severian » vs « Severian le bourreau » et laisse passer le doublon. Mots vides retirés (`_NAME_STOPWORDS`), sinon « le Bourreau » et « la Sorcière » partagent un token. Seuil `SIMILARITY_THRESHOLD` (0.62, `FORGE_WORLD_SIMILARITY`).
  - Deux sorties **explicites** au refus : `allow_similar=True` (« ce sont bien deux entités ») ou `aliases=[…]` (« c'est la même » → met à jour l'existante). Un alias déjà porté par une autre entité **lève** : un nom ne peut pas désigner deux entités, sinon `resolve()` renvoie l'une ou l'autre selon l'ordre de parcours. Les alias **fusionnent**, jamais n'écrasent.
  - **Ordre dans `upsert` : validation des propriétés AVANT unicité.** La validation est déterministe et sans I/O, l'unicité interroge la base — et la fixture `_kg()` de `test_world_kg.py` repose sur le fait que la validation tourne SANS Kùzu. Inverser casse 4 tests d'E2-01.
  - **`_migrate_schema()`** réconcilie les colonnes manquantes (`ALTER TABLE … ADD`) : `CREATE NODE TABLE IF NOT EXISTS` ne touche pas une table existante, donc sans lui « pour étendre, ajouter dans `_TYPE_PROPS` » serait faux dès la 2ᵉ ouverture.
  - ⚠️ **`_CONNECTIONS` n'évince jamais.** Chaque chemin ouvert reste ouvert pour la vie du processus ; au ~16ᵉ, Kùzu refuse d'ouvrir et l'échec remonte en `UnicodeDecodeError` (message natif cp1252 décodé en utf-8 par le binding) — symptôme illisible, cause banale. Tout test qui ouvre plusieurs bases DOIT appeler `reset_world_kg()` en teardown. Tests : `pytest test_world_kg_identity.py` (30).

- **Journal des décisions (world_decisions.py)** — E2-06. Le World-KG sait CE QU'EST le monde ; ce module dit POURQUOI. Chaque choix devient un nœud `DesignDecision`, chaque entité qui en découle porte un `DERIVED_FROM` vers lui — « pourquoi ce PNJ est-il mortel ? » devient une requête, pas une question à l'auteur. Sert l'objectif **S2** (reprendre un projet entre deux sessions sans perte).
  - **Zéro octet d'ontologie touché** : `DesignDecision` et `DERIVED_FROM` existent depuis E2-01, ce module ne fait que les câbler. S'il avait fallu créer un label, c'est qu'il débordait de son ticket.
  - **Module à côté, PAS dans `upsert()`** — l'inverse d'E2-02, et pour une raison précise : E2-02 protégeait un invariant, donc devait être incontournable. Ici il n'y a aucun invariant — `kg.add_decision()` en direct reste légitime (une décision qui n'affecte encore rien). Le raisonnement d'E2-02 ne se transpose pas mécaniquement.
  - ⚠️ **`WorldKG.link()` renvoie `True` quand la cible n'existe pas** (vérifié contre le moteur) : le `MATCH` ne trouve rien, le `CREATE` ne fait rien, Kùzu ne lève pas. Et **il duplique** si on l'appelle deux fois. Un journal qui hérite de ces deux comportements revendique une traçabilité qu'il n'a pas. D'où : `affects` est résolu AVANT toute écriture (tout ou rien, `UntraceableDecisionError`), et `_link_once()` déduplique.
  - **Fusion, jamais remplacement** (même doctrine que les alias d'E2-02) : re-`decide()` en ne précisant que le `choice` n'efface pas rationale/alternatives/auteur. Le premier jet les écrasait — pour un journal dont le produit EST le « pourquoi », c'était la pire perte possible. Vaut aussi pour `status` : une décision `validated` ne retombe pas en `draft`.
  - **« Remplacée par » se LIT, ne se stocke pas** : arête `DERIVED_FROM` portant `context="supersedes"`, plutôt qu'un `"superseded"` ajouté à `STATUS_KINDS` — constante partagée par les 10 types, où un `Character` « superseded » ne veut rien dire.
  - Une révision hérite de l'unicité d'E2-02 : « perma-mort v2 » ressemble assez à « perma-mort » pour être refusée. C'est voulu — `allow_similar=True` rend l'acte délibéré.
  - `render()` = **vue markdown, jamais source de vérité** (même doctrine que le GDD vivant, E2-04) : on régénère, on n'édite pas. `orphans()` expose les décisions sans conséquence — soit non appliquées, soit un `affects` oublié. Tests : `pytest test_world_decisions.py` (27).

- **GDD vivant (world_gdd.py)** — E2-04. Le World-KG sait CE QU'EST le monde, E2-06 dit POURQUOI ; ce module les lit ensemble sous la forme qu'attend un projet de jeu. **Le document est une VUE** : `_SECTIONS` ne fait que donner un ORDRE de lecture aux 10 types d'E2-01 — zéro label, zéro propriété, zéro arête ajoutés (un GDD qui aurait eu besoin d'un type « Pitch » débordait de son ticket).
  - ⚠️ **Invariant verrouillé par test : chaque label de `WORLD_NODE_TABLES` est rangé dans exactement une section.** Un 11ᵉ type ajouté à E2-01 et oublié ici disparaîtrait du GDD **en silence** — et un document ne dit pas ce qu'il ne contient pas, donc personne ne le verrait. Ajouter un type au monde impose de le ranger dans `_SECTIONS`.
  - **`status` pilote enfin le document**, comme E2-01 l'annonçait : `cut` n'est PAS listé (sinon le statut ne veut rien dire) mais reste COMPTÉ dans l'en-tête — omettre en silence serait mentir par soustraction. C'est **`validated` qu'on signale, pas `draft`** : mesuré sur un monde de sonde, marquer les brouillons posait un badge sur 11 entités sur 13, `draft` étant la valeur par défaut d'`upsert()` que personne n'a choisie. Un marqueur universel apprend à être ignoré.
  - **Document DÉTERMINISTE : aucun horodatage dans le corps.** `created`/`updated` reviennent en `datetime` (sondé) ; les rendre ferait diverger deux générations d'un monde inchangé, et le diff — seul moyen de voir ce qui a bougé entre deux sessions — deviendrait du bruit. Git sait déjà quand.
  - ⚠️ **`write()` REFUSE d'écraser un fichier retouché à la main** (`HandEditedGDDError`, sortie explicite `force=True`). Le fichier porte un `<!-- gdd-lock sha256:… -->` = hash de son propre corps, sur fins de ligne normalisées (sans quoi un aller-retour `core.autocrlf` crierait « édité à la main »). Un fichier SANS verrou est traité pareil : on ne présume jamais qu'un fichier qu'on n'a pas écrit est jetable. Raison : perdre une fois le travail d'un humain suffit à ce que plus personne ne régénère, donc à tuer le GDD vivant.
  - **Trois pièges sondés contre le moteur** : une propriété non fournie revient à `None` (pas `""`) — tout le rendu passe par `_text()` sinon « None » finit dans un document livré ; `chrono` absent ferait lever `sorted([10, None])` et emporterait le document entier pour un seul événement mal saisi (`_chrono_key` les range en fin ET les signale) ; `all_nodes(limit)` **tronque en silence** — un label qui rend autant de lignes que la limite est déclaré tronqué, sinon le GDD devient le « document d'apparence complète » qu'on refuse.
  - `gaps()` = les trous DANS le document, nommément. La table `_SUBSTANCE` évite les faux positifs (la substance d'une `DesignDecision` est son `rationale`, celle d'une `LoreRule` son `statement` — pas un `summary` que personne ne remplit) : **une liste de trous à faux positifs est une liste qu'on cesse de lire**. Les clés internes (`monde:Label:slug`) rendues par `contradictions()` sont traduites en noms — un game designer n'a pas à voir la plomberie.
  - Le « pourquoi » par entité relit le voisinage DÉJÀ tenu plutôt que d'appeler `DecisionJournal.why()` (qui ré-interrogerait le graphe 2× par entité) : on réutilise le vocabulaire exporté d'E2-06 (`DECISION_LABEL`, `label_of`), **et un test verrouille l'accord des deux lectures**. Le GDD **cite** les décisions, il ne recopie pas l'ADR — deux documents à tenir d'accord sur le même sujet divergent toujours.
  - `LivingGDD` construit son journal SUR son `kg` (jamais `get_journal(world_id)`, qui s'adosse au singleton `get_world_kg` et ouvrirait la base PAR DÉFAUT : sur un `kg` de test le journal serait vide sans que rien ne le signale).
  - Régime d'état : **`tenant`** (`state_ownership.py`) — un GDD est intégralement dérivé du monde d'un client, `default_path()` passe donc par `forge_store.state_path()`, importé **en tête et gardé** (`try/except ImportError`, convention W5-03a). Un import paresseux dans la méthode avait été écrit puis retiré : `test_state_isolation.py` l'interdit pour tout module doté d'un bloc `__main__`, et `pytest test_world_gdd.py` seul ne le voyait pas — **la suite complète fait partie du ticket**. Self-check : `python -m forge_agents.world_gdd` · tests : `pytest test_world_gdd.py` (53).

- **Recherche du monde (world_rag.py)** — E2-05. E2-01 livrait `context_pack(label, name)` : le voisinage d'une entité prêt à entrer dans un prompt, **mais il fallait déjà connaître son nom**. Or un agent qui va écrire « un marchand de reliques dans la ville basse » ne connaît aucun nom — c'est ce qu'il s'apprête à inventer. Ce module est la porte manquante : **langage naturel → entités du monde → `context_pack`**. `before_write()` en est la forme courte, et c'est là que « tout agent interroge le monde avant d'écrire » devient exécutable.
  - **Zéro octet d'ontologie touché** (même discipline qu'E2-04/E2-06). Un seul ajout à E2-01, `WorldKG.all_edges()`, et c'est une LECTURE.
  - ⚠️ **`forge_rag_optimized` NE S'IMPORTE PAS dans cette Forge** : `import torch` au niveau module → `ModuleNotFoundError`, donc même son BM25 (dont la dépendance *est* installée) est hors d'atteinte. Il est chargé **paresseusement** (`load_reranker()`, qui ne lève jamais) et sert à ce qu'il est seul à savoir faire : le **cross-encoder de re-classement**. Trois modes annoncés dans `stats()["mode"]`, jamais silencieux : `rag_optimized` → `bm25` → `lexical`. Ne jamais le remettre en import dur — E2-05 lèverait à l'import et le monde ne serait plus interrogeable nulle part.
  - ⚠️ **On n'appelle PAS `ForgeRAGOptimized.index()`** : (a) `semantic_chunk` coupe une fiche d'entité de 805 caractères en 2 morceaux et **le second n'a plus le nom** (mesuré) — un fragment attribué à personne ; (b) son `index()` ré-encode TOUT le corpus à chaque document ajouté (O(N²)). **Une entité = UN document, jamais découpé.** C'est son *reranker* qu'on branche, pas son indexeur.
  - ⚠️ **Le tokenizer partagé mutile le français** : `_tokenize("épée dorée")` → `['pée', 'dorée']`, la lettre accentuée INITIALE est mangée (motif en `[a-zA-Z_]`). « épée » et « epee » ne se rencontraient jamais. `_tokens()` tokenise donc le **slug** — et la recherche hérite exactement de la notion de « même chaîne » que l'identité (E2-01/E2-02). Ne pas revenir à `_tokenize` nu.
  - ⚠️ **Une entité NOMMÉE par la requête est hissée, pas classée.** Le premier jet la classait comme les autres et ratait le cas le plus élémentaire : chercher « Severian » rendait Agia, la Griffe et l'Épée — **pas Severian**. Cause structurelle, non réglable par pondération : le nom d'une entité figure dans le document de CHACUN de ses voisins (les relations y sont rendues, et c'est voulu — « une rivale de Severian » doit trouver Agia), donc son IDF s'effondre au plancher d'epsilon de `rank_bm25` et la normalisation par longueur classe l'entité **dernière** (0,0059 contre 0,0078 relevé). Un nom exact est une réponse, pas un signal. Le hissage réutilise `similarity()` d'E2-02 et se mesure sur tout le corpus.
  - **Les règles `hard` ne sont jamais classées** : hissées entières à côté des résultats, et **retirées des `context_pack` individuels** (E2-01 les rejoint à chaque appel — les garder ferait payer les mêmes règles k fois dans le prompt). Un top-5 peut écarter la règle qui interdit exactement ce que l'agent va écrire, d'autant plus sûrement qu'elle est formulée en termes généraux.
  - **Score nul = aucun résultat.** BM25 rend un vecteur nul hors vocabulaire, et `argsort` d'un vecteur nul rend l'ordre des indices : `ForgeRAGOptimized.search_bm25()` renvoie donc ses `top_k` premiers documents à score 0 **comme s'ils répondaient**. Ici, `MIN_SCORE` — sauf pour une entité nommée. Corollaire à connaître : les scores sont comparatifs **à l'intérieur** d'une requête (min-max sur les seuls candidats), pas d'une requête à l'autre.
  - **Pas de juge de cohérence** : `before_write()` remonte règles dures et quasi-doublons, il ne dit pas si l'écriture les viole (c'est E9). Sa seule prédiction, `would_raise`, rejoue la règle d'E2-02 — **et un test l'oppose au vrai `upsert()` dans les deux sens**, sans quoi elle dériverait en silence.
  - **L'index n'est jamais périmé** : reconstruction complète à chaque requête (`fresh=True` par défaut). Rendu tenable par `all_edges()` — une requête par TABLE d'arêtes au lieu de deux par nœud : **2 087 ms → 27 ms (×76)** sur 300 nœuds, coût fonction des ARÊTES et non des nœuds. Relevé sur 302 nœuds : refresh **91 ms**, soit **74 ms/requête** contre 10 ms sur index tenu — bon arbitrage devant un appel LLM qui coûte des secondes. `fresh=False` est la sortie explicite pour une boucle sur monde figé, et le seul réglage à connaître si un monde grossit beaucoup.
  - `HIDDEN_STATUS` (`cut`) duplique volontairement la valeur de `world_gdd` **sans l'importer** (la recherche n'a pas à dépendre du module qui rend un document) — **un test verrouille l'accord des deux**. `RERANK_WEIGHTS` somme à 1.0, verrouillé aussi : une part ajoutée sans rééquilibrage rendrait les scores incomparables d'une version à l'autre.
  - La branche cross-encoder est testée **par injection** (`WorldRAG(kg, engine=…)`) : `forge_rag_optimized` étant inimportable ici, un `skip` aurait laissé croire qu'elle est vérifiée ailleurs. Self-check : `python -m forge_agents.world_rag` · tests : `pytest test_world_rag.py` (59).

- **Mesure par tâche (forge_task_ledger.py)** — E6-01. **N'est PAS un nouveau système de métriques** : `forge_metrics` enregistre déjà l'événement (provider, modèle, tokens, coût, latence, ok/erreur) et `agent_tracker` l'invocation d'agent. Ce module ajoute la seule couche qui manquait — **l'agrégation par ticket du backlog et le retour vers `actual_days`/`actual_tokens`**, que E1-01 avait livrés vides. Un troisième compteur parallèle aurait produit un troisième chiffre divergent.
  - Le lien est le champ **`MetricRecord.task_id`** (ajouté à `forge_metrics`, additif : les 8 appelants passent des kwargs explicites, les lignes antérieures n'ont pas le champ et ne sont jamais comptées à tort).
  - `task_run(task_id)` = context manager : `claim()` à l'entrée (donc **LÈVE si une dépendance est ouverte** — on ne mesure pas un travail qui n'aurait pas dû commencer), et à la sortie agrégation + report + `complete()`. **Sur exception : `block()` + `bump_retry()`, mais la mesure est CONSERVÉE** — un échec a coûté du temps et des tokens, et c'est justement la donnée dont E1-03 a besoin pour apprendre qu'un type de tâche dérape. L'exception n'est jamais masquée.
  - `sync_backlog` **AFFECTE, n'additionne pas** : l'agrégat porte déjà tous les événements du ticket. Un `+=` sur fenêtre temporelle a été écrit puis retiré — les fenêtres se chevauchaient et le second passage comptait double ; un test l'a attrapé (`test_deux_passages_cumulent`).
  - `HOURS_PER_DAY` (défaut 8, `FORGE_HOURS_PER_DAY`) : un « jour-Forge » de l'audit n'est pas 24 h. Le facteur est explicite, pas caché dans une division — sans lui, comparer `actual_days` à `effort_days` ne veut rien dire.
  - **`quality` est PORTÉ, pas CALCULÉ ICI** : la normalisation 0-100 par type d'artefact est **E6-02** (`artifact_quality.py`), branchée en OPTION — `task_run(..., autoscore=True, world_id=…)` note les artefacts déclarés et remplit `meta["quality"]` + `meta["quality_detail"]`. Sans ce drapeau et sans `quality=` explicite, le champ reste `None` : un trou visible plutôt qu'un chiffre inventé. Un scoreur en panne rend `None`, **jamais 0** — un zéro inventé condamnerait un livrable qu'on n'a pas su mesurer.
  - ⚠️ **`perf_counter()` seul ne mesure PAS un ticket.** Un ticket réel s'étale sur des heures, des dizaines d'appels et plusieurs processus : le `with` ne couvre que le dernier bloc, d'où une durée juste mais sans rapport avec le ticket. **C'est la cause mécanique du `coverage()` à 0 % sur cinq tickets** — pas un oubli de discipline. Correctif E2-06 : `claimed_start(task_id)` relit le `started_at` que `claim()` écrit en base depuis E1-01 et que personne ne lisait, et `task_run(..., started_at=…)` mesure alors le temps d'horloge depuis la PRISE. Sans `started_at`, comportement d'origine inchangé.
  - **Le bon usage est donc en deux temps** : `bl.claim(id, session)` à la PREMIÈRE action du ticket, puis à la fin `with task_run(id, claim=False, started_at=claimed_start(id))`. Ouvrir le `with` à la fin sans `started_at` produit un chiffre plausible-mais-faux — exactement ce qui a été refusé à l'inscription d'E6-01 et d'E2-02.
  - `coverage()` est le chiffre qui dit si le module sert : il liste nommément les tâches faites **non mesurées**. Ne pas « améliorer » ce chiffre en mesurant l'acte de cocher la case (essayé, retiré : ça mesurait 30 s pour un ticket de 3 j).
  - `variance()` → **E1-03** · `epic_costs()` → **E6-03** · `aggregate()["failures"]` → **E1-05**. Self-check : `python -m forge_agents.forge_task_ledger` · tests : `pytest test_forge_task_ledger.py` (28).

- **Score par artefact (artifact_quality.py)** — E6-02. Remplit le `quality` qu'E6-01 laissait vide : 0-100 par artefact, quatre types (`code` · `asset` · `audio` · `narrative`), **déterministe et gratuit** (aucun appel LLM — une note payante ne serait ni reproductible ni comparable d'une exécution à l'autre). Une extension inconnue ressort `unknown` SANS score : deviner le type, c'est fabriquer la note qui suit.
  - **Règle centrale : un critère non mesuré n'est jamais un critère réussi.** Il vaut `None`, sort du dénominateur, et fait baisser `confidence`. `score = 100 × Σ(poids × valeur) / Σ(poids)` sur les seuls critères MESURÉS ; `confidence = Σ(poids mesurés) / Σ(poids déclarés)`. Aucun critère mesuré → `score is None` (jamais 0, jamais 100) et `grade == "?"` — **`?` dit « pas mesuré », `F` dit « mauvais »**, les confondre fait jeter un livrable correct qu'on n'a pas su ausculter.
  - ⚠️ **Ce que le Harness renvoyait vraiment** (sondé avant d'écrire, pas déduit) : `validate(CODE, …)` = **100/100 pour à peu près n'importe quoi**, PNG compris. Trois causes : (1) les gates déclarent `check="check_no_secrets"` et `_run_gate` cherchait le seul `_check_{check}` → 8 gates sur 10, dont 3 `critical`, « passées par défaut » ; (2) `flake8` absent → sortie vide lue comme « 0 erreur » → « flake8 clean » ; (3) une gate qui ne filtre que les `.py` « réussit » sur un lot sans `.py`. **(1) et (2) sont corrigés** dans `harness_engine`, **(3) reste ouvert** et un test le dit explicitement — ce qu'E6-02 garantit sur ce cas, c'est le CLASSEMENT (un PNG est un `asset`), pas le Harness.
  - Les détecteurs du Harness (`_check_no_secrets`, `_check_no_ai_slop`, `_check_error_handling`, `_check_no_print`) sont appelés **par leur nom réel**, jamais via `_run_gate` : le module ne dépend pas d'un correctif situé dans un autre fichier. Leurs réponses muettes sont reconnues par **égalité exacte** (`_MUTE_EXACT`), jamais par sous-chaîne : le détail d'un échec cite le texte trouvé DANS le fichier, et « placeholder » est lui-même un motif anti-slop — un `in detail` transformait une vraie détection en « sonde indisponible », donc en meilleure note.
  - **`CAP_BLOCKED = 49`** : un critère `BLOCKING` (`syntax`, `readable`, `not_blank`, `not_silent`, `container`, `no_placeholder`) mesuré à 0 plafonne le score juste sous le plancher du C. Sans lui, un WAV **entièrement silencieux** sortait à **76,9/100 (B)** — lisible, durée saine, 44,1 kHz, sans saturation : toutes ses sondes sauf une disent « bon ». Certains défauts ne se compensent pas. `no_secrets`/`no_slop` n'en sont PAS : fautes graves (les poids les sanctionnent), pas artefacts hors service.
  - Deux critères sont mesurés par AST plutôt que délégués, parce qu'une bascule à seuil fixe (le Harness : « >10 manquants ») ne normalise rien — sur un gros fichier le seuil est franchi d'office, sur un petit jamais : **`docstrings` et `type_hints` sont des PROPORTIONS**. Idem `tests_exist`, qui cherche `test_<stem>.py` jusqu'à la racine du dépôt (les tests de cette Forge y vivent ; ne regarder que le dossier du fichier répondait « absent » à tous les coups). Sur un `test_*.py`, `type_hints` sort NON mesuré — personne n'annote `def test_x(tmp_path)`.
  - `narrative` : l'ancrage (`grounded`, poids `critical`) résout les noms propres du texte contre le **World-KG d'E2-01** — le seul critère qui distingue un texte de jeu d'un texte bien écrit, un PNJ inventé en cours de rédaction étant indétectable au style. **Non mesuré tant qu'aucun `world_id` n'est fourni** : sans monde de référence, sanctionner un nom propre revient à noter au hasard.
  - Un artefact **déclaré mais absent** rend `None`, pas 0 : ce n'est pas un livrable médiocre, c'est un trou. `score_artifacts()` ne pondère PAS la moyenne par la confiance — ça ferait taire les artefacts les moins auscultés, exactement ceux qu'il faut regarder — et rend `unscored` à côté du chiffre.
  - Sert **E6-03** (artefacts les plus chers × qualité) et **E1-05** (réaffectation sur échec). Self-check : `python -m forge_agents.artifact_quality <chemins…>` · tests : `pytest test_artifact_quality.py` (37).

- **Budget fournisseur MiMo (mimo_budget.py)** — S-03. À ne PAS confondre avec `forge_quota` : celui-ci compte ce que *le client* consomme sur une fenêtre glissante d'une heure, dans l'espace du tenant ; `mimo_budget` compte ce qu'il reste sur *notre abonnement* (11 Md/mois) sur le mois calendaire, dans un ledger **GLOBAL** (`05_STATE/identity/mimo_budget.json`, régime `platform` — le plan est commun, le cloisonner donnerait à chaque tenant son propre « 11 Md restants »).
  - `mimo_call` (forge_mimo.py) débite le plan via `_record_budget()` : **point de passage unique**, toutes les branches (MimoBatcher, forge_swarm, hallucination_judge) y aboutissent. Comptabiliser ailleurs = double comptage. L'échec du ledger est absorbé (un appel déjà payé ne se perd pas parce que le disque coince) — le solde sous-estime alors, et le log le dit.
  - Le ledger garde le **réel à côté du facturé** (`real_tokens` / `billed_tokens`) : l'écart EST le coût du round-up au bloc de 1000. C'est la mesure dont S-05/S-06 ont besoin, déjà en place.
  - `check(cost, enforce=True)` **lève** `BudgetExceeded` (même contrat que `forge_quota.QuotaExceeded`) et vérifie AVANT de dépenser. C'est l'accroche de S-07 : `run_swarm`/`batch_call` n'ont qu'à l'appeler.
  - `report()["source"]` = `remote|local|declared` : le champ le plus important. Il n'existe pas d'endpoint fournisseur confirmé — tant que `MIMO_USAGE_URL` n'est pas posée, le solde vient d'un **point de départ déclaré** (`MIMO_BASELINE_TOKENS`, valable pour son seul mois) plus le ledger mesuré. Ne jamais afficher ce chiffre sans sa provenance. Exposé par `GET /v1/budget/mimo`. Self-check : `python -m forge_agents.mimo_budget` · tests : `pytest test_mimo_budget.py` (11).
- **Registres JSON de `05_STATE` : lire en `utf-8-sig`, écrire en `utf-8`.** Sur cette plateforme, tout JSON écrit depuis PowerShell porte un BOM. `forge_identity._load()` lisait en `utf-8` strict : `json.loads` échouait sur le premier octet, `_load` levait, et **toute** résolution de jeton retournait 401 — l'API `/v1` entière inaccessible pour un octet invisible.

## ✂️ SEMANTIC EDIT ENGINE — MCPT (édition de coût minimal)

`semantic_edit_engine/` — le LLM ne produit pas le patch, il produit l'INTENTION (le code
cible) ; le moteur dérive ensuite **sans token** toutes les façons d'exprimer la
transformation, les score, et retient la moins coûteuse qui reste sûre.

```python
from tools.see_edit import apply_minimal_edit
res = apply_minimal_edit("path/file.py", target_name="guard", modified_code=code_cible,
                         dry_run=False, test_cmd="python -m pytest -q")
# res["status"] / res["ops"] / res["token_savings_pct"] / res["impact"] / res["review"]
```

**Boucle complète (`edit_pipeline.run_edit`)** — seul appelant légitime des 4 briques :

```
plan (MCPT) → gate impact → revue statique → application → tests → diff
                   ↓ CRITICAL     ↓ régression      ↓ ne compile plus / tests KO
                 ABORT           ABORT             ROLLBACK
```

Statuts : `no_plan` · `blocked_impact` · `blocked_review` · `planned` (dry-run) ·
`apply_failed` · `tests_failed` (rollback effectué) · `applied`.
`force=True` passe outre les gates bloquants — le forçage est tracé dans le résultat.

- **Primitives** (`edit_primitives.py`) : `Replace`, `InsertAfter`, `DeleteRange`,
  `ReplaceSymbolBody`. 4 seulement — les refactos (MoveFunction, ExtractMethod…) sont
  un AUTRE problème (ponytail/YAGNI).
- **`derive_ops(original, modified, symbol)`** : produit l'espace des plans
  (character / token / statement / semantic) et **écarte tout plan qui ne reproduit pas
  exactement la cible**. Déterministe, 0 appel LLM.
- **Coût MCPT** (`patch_optimizer.COST_WEIGHTS`) : `emit` (caractères à émettre, domine)
  + `chars` + `lines` + `ops`. Plancher de sûreté `SAFETY_FLOOR=0.55` sur le PatchScorer :
  un plan moins cher mais non sûr est écarté.
- **Sûreté sémantique** (`semantic_safety.py`, 0 dépendance) : suppression d'API publique,
  référence pendante, import retiré encore utilisé, syntaxe cassée → **BLOCK** ;
  changement de signature publique → **WARN**. AST stdlib en Python, heuristiques ailleurs.
- **Revue statique** (`patch_review.py`) : ruff / semgrep / eslint, **tous optionnels**.
  Règle : seuls les diagnostics **introduits** par le patch bloquent (avant/après, on
  soustrait) — la dette préexistante n'est pas le problème du patch. Outil absent →
  `tools_skipped`, jamais un échec.
- **Gate impact** (`impact_gate.py`) : blast radius GitNexus en code, plus en consigne.
  `CRITICAL` → BLOCK, `HIGH` → WARN. Index/node absent → non bloquant.
- **Application** : `auto_rollback` — si le fichier ne compile plus, OU si `test_cmd`
  échoue, restauration automatique (`rolled_back=True`).
- **Observabilité** : `edit_metrics.record_edit(candidate)` relaie vers
  `05_STATE/forge_metrics.jsonl` (kind=`tool`, workflow=`semantic_edit_engine`).
- Vérification : `python 00_CORE/forge_agents/semantic_edit_engine/test_see.py`
  (5 cas réels ; exige que le plan gagnant batte la réécriture). Roadmap :
  `semantic_edit_engine/UPGRADE_ROADMAP.md`.

## 🐝 FORGE SWARM — agents natifs MiMo (le travail HORS session Claude)

`forge_swarm.py` — quand il faut auditer/traiter N fichiers, **ne pas** spawner N
sous-agents Claude (≈120K tokens CHACUN, dans la session facturée). Chaque « agent » =
un `mimo_call` (backend interne MiMo 2.5-pro, facturé au bloc round-up, hors session).
Orchestration déterministe en Python = 0 token Claude. Claude ne fait que lancer et lire
la synthèse. Aligne la RÈGLE ANTI-DÉRIVE (Claude raisonne/valide, MiMo exécute).

```bash
python 00_CORE/forge_agents/forge_swarm.py --chunks 05_STATE/tech_debt.json --workers 8
python 00_CORE/forge_agents/forge_swarm.py --files a.py b.py --workers 6
```

- **Récursion** : un fichier > `MAX_FILE_CHARS` est découpé par symbole (AST) → un
  `mimo_call` par unité, puis fusion. Un agent MiMo engendre ses propres sous-agents MiMo.
- **Piège MiMo** : c'est un modèle de RAISONNEMENT — `reasoning_content` consomme le
  budget AVANT la réponse. `max_tokens < ~5000` → `content` vide mais bloc facturé.
  `audit_unit` utilise `max_tokens=6000`.
- **Garde-fou anti-hallucination (déterministe, 0 token)** : `_ground_finding` vérifie que
  le code cité en preuve EXISTE dans le fichier (comparaison espaces retirés) et
  **relocalise** la vraie ligne (MiMo invente les numéros). Preuve introuvable →
  `quarantine_hallucinated`, jamais mélangée aux findings retenus. Cas réel attrapé : un
  finding CRITICAL citant `self.tag_file(...dry_run=...)` à une ligne qui était en fait un
  dict littéral.
- **Sortie** : `05_STATE/swarm_audit.json` — findings groundés + quarantaine + coût
  (`mimo_billed_tokens`, `claude_session_tokens: 0`).
- **Isolation** : l'audit est read-only → en place. Un swarm d'ÉCRITURE (fixes parallèles)
  doit tourner en `git worktree` par agent (répertoires disjoints).

## 📊 SANTÉ DU DÉPÔT — rendu DYNAMIQUE (jamais statique)

`forge_health.py` + routes `/health` et `/api/health` dans `09_WEB/server.py`.

**Règle : aucun site statique.** La page est fabriquée par `render_html()` à CHAQUE requête
depuis les sources vivantes — rien n'est pré-généré sur disque, donc toute mise à jour d'un
scan est visible au rafraîchissement suivant, sans build ni HTML à maintenir.

Sources relues à chaud (toutes optionnelles, dégradation gracieuse) :
`05_STATE/tech_debt.json` · `swarm_audit.json` · `debt_priority.json` · `forge_metrics.jsonl`.

- **Santé dépôt** : fichiers, SLOC, score de dette /kSLOC, échecs silencieux, zones.
- **Vue par tâche** : agrégats `forge_metrics.summary()["groups"]` — workflow × agent,
  appels, tokens in/out, latence p50, erreurs.
- **Notes** : décroissance exponentielle (`100·exp(-x/k)`), jamais écrêtée à 0 — une note
  linéaire saturait dès ~8 CRITICAL et n'informait plus. Poids = hypothèses explicites en
  tête de `collect()`.
- Vérification : `python -m forge_agents.forge_health` (résumé) / `--json`.

## 🎯 PRIORISATION DE LA DETTE

`debt_priority.py` — `priorité = poids(sévérité) × poids(catégorie) × (1 + log2(1 + dépendants))`.
Blast radius calculé par **graphe d'imports inverse déterministe** (< 5 s, 0 token) : `gitnexus
impact` est la source d'autorité mais mesuré à **89 s/appel** sur ce dépôt (index 885 Mo), soit
> 2 h à cette échelle. Arêtes par import UNIQUEMENT — un repli « identifiant partagé » avait été
tenté et attribuait 222 dépendants à un outil feuille (noms courants type `configure`/`run`).
Sortie : `05_STATE/debt_priority.json` + `07_REPORTS/DEBT_PRIORITY.md`.

## 🛡️ HARNESS ENGINE — Quality Gates (MANDATORY)

**Every artifact MUST pass through the Harness before delivery.**

```python
from .harness_engine import HarnessEngine, ArtifactType, format_harness_report

engine = HarnessEngine(auto_fix=True)
result = engine.validate(ArtifactType.CODE, files)
if not result.passed:
    # Fix or regenerate — NEVER deliver with critical failures
    pass
```

### Artifact Types
- `ArtifactType.CODE` — Python, JS, etc. (10 gates)
- `ArtifactType.WEBSITE` — Landing pages, webapps (11 gates)
- `ArtifactType.VIDEO` — YouTube, TikTok (8 gates)
- `ArtifactType.BOT` — Telegram, Discord (9 gates)
- `ArtifactType.EMAIL` — HTML emails (9 gates)
- `ArtifactType.API` — REST, GraphQL (8 gates)

### Anti-Slop Rules (CRITICAL)
- NO "Certainly!", "Great question!", "I'd be happy to"
- NO "# TODO: implement", "placeholder", "lorem ipsum"
- NO hardcoded secrets (API keys, passwords, tokens)
- NO print() in production code (use logging)

### ⚠️ État réel des gates (sondé en E6-02, pas déduit)
Jusqu'au correctif E6-02, `validate(CODE, …)` renvoyait **100/100 pour à peu près
n'importe quoi** — un PNG compris. `_run_gate` ne cherchait que `_check_{gate.check}`
alors que les gates déclarent `check="check_no_secrets"` : **8 gates sur 10, dont les 3
`critical`, étaient « passées par défaut »**. Corrigé (les deux formes sont tentées), ainsi
que `flake8 clean` annoncé sans flake8 installé. **Restent faux** : les gates WEBSITE /
VIDEO / BOT / EMAIL / API sont des `placeholder` qui réussissent toujours, un type sans
gate (`DOCUMENT`, `DATABASE`…) renvoie 100 avec **zéro gate exécutée**, et un lot sans
aucun `.py` passe toutes les gates CODE sans que rien n'ait été regardé. Pour une note
qui distingue « mesuré » de « réussi », utiliser **`artifact_quality` (E6-02)**.

### Quality Thresholds
- CRITICAL: 100% (blocks delivery)
- HIGH: ≥80% (warning)
- MEDIUM: ≥60% (recommendation)
- Overall: ≥70% AND zero critical failures = PASSED

### Integration
The Harness is called in `dynamic_agent_node()` and `post_mortem_node()`:
- Before storing findings → validate code artifacts
- Before generating brief → validate all outputs
- If critical failures → regenerate with stricter prompt

## 🧠 NEURAL-MARKOV ENGINE — Interpretable Forecasting

```python
from .neural_markov_engine import get_engine, forecast_all

engine = get_engine()
engine.initialize()  # Load financial + BBRIL data
result = engine.forecast_all(n_ahead=7)
print(result.explanation)  # Human-readable explanation
```

### Data Sources
- Financial: SPY, QQQ, GLD, TLT, BTC-USD (460-690 days)
- BBRIL: 11,758 vulnerability reports (24 types)

### Architecture
1. Neural Encoder → 8 interpretable dimensions (economic concepts)
2. Markov Model → 5 regimes (BULL/BEAR/SIDEWAYS/CRISIS/RECOVERY)
3. Economic Theory → CRRA utility, Prospect Theory, behavioral biases
4. Individual Preferences → hierarchical Bayesian

### Integration
- Cervelet: reflexes for prediction (0 LLM tokens)
- Brain-Node: external data enrichment
- NMP: inter-agent communication
- Dynamic Agents: regime-specific specialists

## 🎯 PONYTAIL — YAGNI Layer

```python
from .ponytail import yagni_suffix

# Injected into system prompt for code tasks
suffix = yagni_suffix(task)  # Returns YAGNI rules if code task
```

### YAGNI Ladder
1. Does it need to exist? → No: skip
2. Does stdlib do it? → Use stdlib
3. Native platform feature? → Use it
4. Already installed dependency? → Use it
5. One line sufficient? → One line
6. Only then: minimum that works

## 📊 DATA SCIENTIST — analytics déterministe (`forge_data_scientist.py`)

Bounded context ANALYTICS. **0 token LLM** : tout est statistique stdlib, donc
rien à halluciner. Livré 2026-07-22 (gap analysis :
`09_TASKS/analysis/GAP_DATA_SCIENTIST_2026-07-22.md`).

### Chaîne interne (sous-agents data, matérialisés en classes)
```
DataLake (engineer)  → joint forge_metrics.jsonl + experience_db.json
                        + tool_call_ledger.jsonl + agent_tracker/history.json
                        en un schéma unique `Observation`
AnomalyDetector      → z-score robuste (MAD), 5 métriques × 4 dimensions
AgentProfiler        → scorecard 0-100 (efficacité/fiabilité/coût/vitesse)
Forecaster           → OLS + EWMA, J+7/J+30, « budget épuisé dans N jours »
ABTester             → Welch + Cohen's d, auto_smart() = 1re métrique instrumentée
Policy               → bandit ε-greedy sur qualité−coût−temps (exploration
                        DÉTERMINISTE via explore_seed → décision rejouable)
OptimizationEngine   → règles explicites → Recommendation(P0/P1/P2)
```

### Contrats (à ne pas casser)
- `get_data_scientist().analyze(budget_usd=None, persist=True) -> dict`
  → persiste `05_STATE/data_scientist_report.json`
- `advisory(task, domain) -> str` : **borné à 6 lignes**, injecté par
  `agent_nodes._ds_advisory()`. C'est un réflexe, pas un rapport.
- `post_task_card()` : contrat figé
  `{what_worked, what_failed, cost, time_ms, recommendation, confidence}`
- `choose_agent(dimension, exclude, explore_seed) -> dict|None`

### Règles d'honnêteté (verrouillées par tests — NE PAS assouplir)
1. **Un jour sans mesure est absent de la série**, jamais compté `0`. Sinon un
   trou d'instrumentation produit une fausse anomalie « +100 % ».
2. **Baseline nulle ⇒ pas d'anomalie.** Pas de division par zéro déguisée.
3. **Métrique non instrumentée ⇒ pas de verdict A/B.** « 0 vs 0 » n'est pas une
   comparaison.
4. **Le score de santé est plafonné par la couverture d'instrumentation**
   (`coverage()`). On ne déclare pas la Forge saine sur ce qu'on ne mesure pas.
5. Lake vide ⇒ `None` et `confidence=0.0`, jamais une valeur inventée.

### Dépendance amont (le vrai gap restant)
Couverture d'instrumentation ≈ 27,6 % : `cost_usd` 0 %, `quality` 0 %,
`latency_ms` 2,6 %, `tokens_total` 4,2 %. Toute amélioration passe par des
appels `forge_metrics.observe()` dans `forge_llm`, `harness_engine` et les nœuds
LangGraph — **pas** par du code côté Data Scientist.

### API HTTP (09_WEB/server.py)
`/api/datascience/{report,anomalies,forecast,scorecards,abtest,recommendations,choose}`
+ `POST /api/datascience/card`. 16 nœuds `datascience` sur la carte neuronale.

## Work Guidance
- Run `python3 -m py_compile <file>.py` on every edited module before considering a change done.
- Run `gitnexus_impact` before modifying any exported function/class (root AGENTS.md / CLAUDE.md GitNexus section).
- **Run Harness validation on ALL generated code before delivery.**
- **Run Neural-Markov engine for forecasting tasks.**

## Verification
- `python3 -m py_compile *.py` must pass on all touched files.
- `python run_forge.py --status` should run without raising after structural changes to ForgeState or the graph.
- `python harness_engine.py code <files>` must pass for all code artifacts.
- `python neural_markov_engine.py` must run without errors.
- `python -m forge_agents.test_forge_data_scientist` must stay green (24 tests) —
  il verrouille les 5 règles d'honnêteté du Data Scientist.
- `pytest test_world_kg.py` doit rester vert (33 tests) — il verrouille l'ontologie du
  monde (E2-01) : les 10 types + 6 arêtes du ticket, le DDL dérivé du schéma, l'identité
  déterministe, le cloisonnement multi-mondes et les 4 garde-fous qui LÈVENT. Les tests
  d'écriture se sautent proprement si `kuzu` manque — un skip est visible, une absence non.
- `pytest test_forge_backlog.py` doit rester vert (51 tests) — il verrouille le backlog
  (E1-01) : le DDL dérivé, les garde-fous qui LÈVENT, la machine à états, la détection de
  cycles, et surtout **un aller-retour contre le VRAI SQLite du secours** sur fichier
  temporaire (les listes `depends_on` traversent une sérialisation JSON — c'est là que ça
  casse en silence). Aucun test ne touche `04_GRAPHIFY/forge_fallback.db`.
- `pytest test_forge_task_ledger.py` doit rester vert (28 tests) — il verrouille E6-01 :
  l'agrégation par `task_id`, la conservation de la mesure sur échec, l'idempotence de
  `sync_backlog`, le fait que `quality` reste `None` tant qu'E6-02 n'existe pas, et
  (E2-06) que `started_at` mesure depuis la PRISE de la tâche et non depuis le `with`.
- `pytest test_artifact_quality.py` doit rester vert (37 tests) — il verrouille E6-02 :
  la normalisation sur les seuls critères mesurés, `None` (ni 0 ni 100) quand rien n'est
  mesurable, le plafond `CAP_BLOCKED` (né d'un WAV silencieux noté **B**), le fait que le
  CONTENU d'un fichier ne puisse pas se faire passer pour une sonde muette, et les trois
  régressions Harness (gates injoignables, `flake8 clean` sans flake8, `HarnessResult.grade`
  inexistant que `agent_nodes` lisait déjà dans un `except Exception`). **Vérifié par
  mutation** : 3 régressions injectées, 3 tuées (2, 6 et 1 test), fichiers restaurés verts.
  Un test y assume explicitement un trou NON corrigé (PNG noté 100 comme du CODE) — il
  tombera le jour où `validate()` refusera un lot étranger à son type, et c'est voulu.
- `pytest test_world_decisions.py` doit rester vert (27 tests) — il verrouille E2-06 :
  le refus tout-ou-rien d'une cible inconnue, la non-duplication des arêtes, le fait
  qu'une re-déclaration partielle n'efface pas le « pourquoi », et qu'une décision qui en
  remplace une autre ne soit pas comptée comme une conséquence de design. Les deux
  premiers existent parce que `link()` renvoie `True` sur une cible absente et duplique
  sur appel répété — comportements observés contre le moteur, pas supposés.
- `pytest test_world_gdd.py` doit rester vert (53 tests) — il verrouille E2-04 : l'exhaustivité
  des sections (aucun type du monde ne peut disparaître du document), le fait qu'une entité
  `cut` soit absente MAIS comptée, le déterminisme octet à octet de deux générations d'un
  monde inchangé, la déclaration de troncature, l'absence de faux positif dans `gaps()`, et
  le refus d'écraser un fichier retouché à la main. Le skip Kùzu est dans la FIXTURE, pas en
  tête de module : l'invariant d'exhaustivité est une propriété pure et doit rester vérifié
  même sans moteur. **Vérifié par mutation** (injections en mémoire, aucun fichier touché) —
  5 régressions injectées, 5 tuées.
- `pytest test_world_rag.py` doit rester vert (59 tests) — il verrouille E2-05 : le fait
  qu'une entité cherchée par son NOM revienne en premier (la régression du ticket : BM25 la
  classait dernière, son nom étant dans le document de tous ses voisins), que les règles
  `hard` accompagnent le paquet **même quand la recherche ne rend rien**, qu'une requête hors
  du monde rende une liste vide au lieu du top-5 d'un vecteur nul, qu'une entité `cut` ne soit
  jamais proposée, que l'index ne soit jamais périmé, et que `would_raise` soit **d'accord
  avec le vrai `upsert()` dans les deux sens**. La branche cross-encoder est couverte par
  INJECTION (`WorldRAG(kg, engine=…)`) : `forge_rag_optimized` est inimportable ici (torch
  absent), un `skip` aurait laissé croire qu'elle est vérifiée ailleurs. **Vérifié par
  mutation** (copie du fichier, restaurée) — 5 régressions injectées, 5 tuées.
- **`testpaths` de `pytest.ini` n'est PAS exhaustif** : un fichier de test absent de cette
  liste ne tourne jamais en CI, même vert en local. `test_world_kg.py` (33 tests d'E2-01) y
  a manqué. Ajouter tout nouveau fichier de test à `testpaths` fait partie du ticket.
- `python 00_CORE/tools/security_audit.py --check` : la porte indexe les sites revus par
  **`fichier:ligne`** (`REVIEWED_INJECTION`). Insérer une ligne au-dessus d'un site revu
  décale la clé et rouvre la porte sans que le code ait changé — vérifier après toute
  édition de `graph_db.py`, `world_kg.py` ou `forge_db_fallback.py`.

## Child DOX Index
(none — leaf package)
