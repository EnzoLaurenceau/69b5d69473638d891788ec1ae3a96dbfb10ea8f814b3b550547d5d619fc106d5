# Forge — Carte des capacités réelles + Contest du plan "conscience"
> Audit 2026-06-24 · 9 inventaires fan-out (multi-agent) + synthèse Claude · source brute: tasks/w175iv13w.output
> Règle directrice (la tienne): toute couche nouvelle doit prouver un gain mesurable (qualité/vitesse/fiabilité/coût), sinon NON intégrée. Le danger = accumulation de complexité.

## TL;DR
La Forge **a déjà** une couche Conscient solide (LangGraph 11 nœuds + vérif + anti-halluc, réelle et câblée).
Le Subconscient "always-on" est **ABSENT** — mais l'apprentissage utile existe déjà (task-bound). L'Alter stratégique n'existe qu'en graine (et CET audit EN est l'exécution on-demand).
Le vrai problème n'est pas un manque de couches — c'est **~70 modules orphelins + 6 clusters de doublons + des daemons morts**, et des **subagents isolés qui crament les tokens** (cet audit: ~1.6M tokens). Priorité = **couper + mutualiser**, pas ajouter.

---

## 1. Couche CONSCIENT — RÉELLE & câblée (garder)
`run_forge.py` → `cervelet.route_request` (réflexe Token-ID étroit: ne déclenche que si signal contient `#` et `:`; sinon ESCALATE) → `ForgeRunner` (`forge_agents/forge_graph.py`) = vrai `StateGraph(ForgeState)`, **11 nœuds**:
```
v6_init → estimate_budget → orchestrator(planner/CEO) → dynamic_agent(worker, expert spawné par prompt_architect)
        → v6_post_execution → auto_complexification(L1-L4) → neuro_symbolic_verification → anti_hallucination
        → memory_pruner → (loop orchestrator)        post_mortem → END
```
- Persistance: SqliteSaver (`04_GRAPHIFY`) + `graphify_checkpointer` JSON (`05_STATE`).
- Le pipeline "generator → verifier → anti-hallucination" que tu décris **existe déjà**.
- Meta-agent-factory dynamique = `prompt_architect.py` (système 10 sections par tâche), confirmé réel.

**Risque #1 (structurel):** DEUX moteurs d'orchestration qui ne partagent PAS de code —
le LangGraph (`run_forge→forge_graph`, via `forge_llm`) **et** `forge_dispatcher.py`+`forge_daemon_service.py` (subprocess `hermes chat`, hors graph). → choisir UN seul.

## 2. Couche SUBCONSCIENT — apprentissage task-bound OUI, always-on NON
**VERDICT: pas de processus de fond.** Aucun apprentissage/consolidation/scoring qui tourne sans tâche active.
MAIS la boucle d'apprentissage **existe**, à l'intérieur d'un run:
- `v6_post_execution_node` → met à jour `forge_meta` + `forge_experience_db` (BigSet, workflow_scores) + `boost_node`.
- `post_mortem_node` → déclenche optionnellement `evomap`.
→ La valeur ("mesurer→apprendre→réutiliser") est **déjà capturée après chaque run**.

## 3. Couche ALTER STRATÉGIQUE — graine seulement
`forge_meta` (état émotionnel/scoring) + `forge_experience_db` + `boost_node` = les primitives, mais **task-bound**, pas d'observateur permanent. **Cet audit multi-agent EST la fonction alter-stratégique** exécutée à la demande.

---

## 4. Contest des 3 couches (mesurable ou rien)
| Couche | Réalité | Verdict mesurable |
|---|---|---|
| Conscient | Existe, robuste | **Garder.** Seul fix: supprimer le 2e moteur (dispatcher/Hermes-subprocess) → 1 orchestrateur. |
| Subconscient *always-on* | Absent; learning task-bound présent | **NE PAS construire un daemon résident.** Gain marginal vs coût/complexité. Si consolidation périodique voulue → **1 cron** qui rejoue le learning post-run sur `experience_db` accumulé. Pas d'archi nouvelle. |
| Alter stratégique *résident* | Graine + audit on-demand | **NE PAS résidentialiser.** Planifier CET audit en cron (hebdo) = même valeur, coût borné. |

> Les 3 daemons "background" déjà écrits (`autonomous_monitor`, `forge_session_daemon`, `forge_daemon_service`) sont la tentative ratée d'always-on: **tous orphelins, même CEILING=65000 hardcodé 3×.** → preuve que la résidence n'apporte rien ici. **À supprimer.**

---

## 5. Réalité vs docs (ne pas faire confiance au CLAUDE.md)
- `00_CORE/langgraph/` **n'existe pas** (modules dans `forge_agents/`). *(corrigé dans CLAUDE.md ce jour)*
- Mémoire "PRIMARY PG+Redis+pgvector": **Postgres DOWN** (timeout), Redis UP (6380), Nexus boote sans kernel → **tout tombe en fallback SQLite/JSON** (`forge_fallback.db`, `.nexus/forge_state.json`). `nexus-data/` vide.
- Router: CLAUDE.md annonce cascade DIRECT Nebius/Gemini/Groq/Cerebras; le code appelle surtout **ds2api/RTK/Groq + jailbreak**. Nebius orphelin.
- `__init__.py` importe `forge.langgraph.mirofish_subgraph.run_jury` = **import mort** (module inexistant).

## 6. Code mort / orphelin (couper = anti-complexité)
~70 modules sans importeur. Gros blocs sûrs à supprimer/archiver:
- **Vérif/inférence**: `harness_engine.py` (1040 l, orphelin) · `inference_optimizer.py` · `neural_markov_engine.py` (45 KB).
- **Daemons fond**: `autonomous_monitor` · `forge_session_daemon` · `forge_daemon_service` · `token_ceiling_monitor` · `cleanup_agent` · `ratchet_optimizer`.
- **Specialty (18/33 orphelins)**: `decepticon_adapter` · `reverse_engineering` · `bbril_pipeline` (seul importeur = `tmp_bbril_compare.py` jetable) · `pentest_datasets` · `agency_personas` · `agent_topology` · `agent_skills_patterns` · `research_enrichment` · `snapchat_marketing` · `geo_seo` · `infographic_builder` · `algorithm_helper` · `semantic_compressor` · `caveman_logger` · `crafty_slug` · `mimo_token_tracker`.
- **Dispatcher dupliqué**: `00_CORE/forge_dispatch/forge_dispatcher.py` (stale, 101 l).
- **Registry mort**: `registry.json` + `parse_registry()/find_tool()` = zéro consommateur.
- Junk repo: `tmp_*.py` ×7, `nul`.

## 7. Clusters de doublons (fusionner → 1)
- **3 "brain"**: `turbovec_brain`(actif) · `openviking`(shim) · `multi_source_brain`(≠ job, mal nommé).
- **3 RAG**: `adaptive_rag`(câblé) · `rag_anything`(orphelin) · `multi_source_brain`.
- **Checkpoint écrit 3×**: SqliteSaver + nexus_bridge + graphify_checkpointer (même état).
- **2 token trackers**: `token_tracker`(13 importeurs) vs `mimo_token_tracker`(orphelin).
- **3 protocoles inter-agent**: `a2a_protocol` · `nmp_encoder` · `ail_protocol` (même messaging pipe-delimited).
- **2 caches**: `lmcache_integration` vs `semantic_cache`.
- **Deploy orphelins**: `coolify`/`dify`/`langflow`/`twenty_crm` (docker/HTTP, aucun appelant).
- **MCP**: dépôt ne configure **aucun** serveur MCP (pas de `.mcp.json`); `metorial`/`mcpify`/`repowise` orphelins; `open_osint.py` duplique le MCP openosint live.

---

## 8. NORTH STAR — moins de tokens, plusieurs subagents (action prioritaire)
Cet audit a brûlé ~1.6M tokens car **les subagents sont isolés** (pas de cerveau partagé) — exactement ton diagnostic optiforge.md (800k/5min). Levier 10–50×, et **le code existe déjà (batch V6) mais n'est pas câblé**:

1. **Câbler le shared-brain V6** (déjà écrit, dormant) dans le spawn des subagents:
   - `forge_kernel.py` → 1 kernel unique partagé (objectif/entités/contraintes) lu par tous.
   - `forge_shared_brain.MCPProxyCache` → 1 appel MCP/outil mis en cache, rediffusé (÷5–20).
   - `forge_lazy.py` → reuse solution cachée / pattern similaire avant full execution.
   → Agents = workers légers (kernel + shared_state in, contribution out).
2. **Adopter headroom** (`github.com/headroomlabs-ai/headroom`, pip `headroom-ai`) = couche compression contexte pour agents: **60–95% tokens en moins**, library/proxy/MCP, local-first, **réversible**. Compresse tool-outputs + logs + RAG + messages inter-agent **avant** le LLM. → DO NOT INVENT: **remplace** les tentatives maison orphelines (`semantic_compressor`, `inference_optimizer`) par une lib maintenue. Branchement le + simple: `headroom proxy` devant les appels LLM des subagents.
3. **Mesurer** (mimo/token_tracker) avant/après sur une tâche fixe → ne garder que si gain prouvé.

---

## 9. Plan d'action ordonné par impact
1. **Mutualiser** (gros gain tokens): câbler `forge_kernel`+`forge_shared_brain.MCPProxyCache`+`forge_lazy` dans le spawn subagent + brancher **headroom** proxy. Mesurer.
2. **Unifier l'orchestration**: garder LangGraph, retirer le moteur `forge_dispatcher`/Hermes-subprocess (ou l'inverse) — 1 seul.
3. **Supprimer le code mort** (§6) + junk (`tmp_*`, `nul`, dispatcher dupliqué, registry mort).
4. **Fusionner les doublons** (§7): 1 brain, 1 RAG, 1 protocole inter-agent, 1 cache, 1 token tracker, 1 chemin checkpoint.
5. **Décider la mémoire**: soit lever PG+Redis pour de vrai (docker up), soit assumer SQLite/JSON et supprimer la couche PG fantôme. Pas les deux à moitié.
6. **Apprentissage/meta = on-demand**, pas daemon: cron hebdo qui (a) rejoue le learning sur `experience_db`, (b) relance cet audit. Supprimer les 3 daemons ceiling orphelins.
7. **Embedded repos** (G0DM0D3/L1B3RT4S/AsyncHerald/nexus/hexstrike-ai): pas de `.gitmodules` → vrais submodules OU vendor en fichiers OU gitignore. (séparé)
