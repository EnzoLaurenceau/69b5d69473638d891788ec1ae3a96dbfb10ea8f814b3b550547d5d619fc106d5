"""
forge_graph.py — Graph LangGraph principal de la Forge.

Architecture :
                    ┌─────────────────────────────┐
                    │       ORCHESTRATOR           │
                    │  (décide → route → cycle++)  │
                    └────────────┬────────────────-┘
                  ┌──────────────┼──────────────────┐
                  ▼              ▼                   ▼
            [HUNTER]       [BUILDER]          [MARKET]
            [CRITIC]       [CLOSER]           [MARKETING]
            [AUDIT]
                  │              │                   │
                  └──────────────┴────────────────── ┘
                                 ▼
                    ┌────────────────────────┐
                    │   AUTO_COMPLEXIFICATION │
                    │  (delta, level_up,      │
                    │   rollback, kill)       │
                    └────────────┬───────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  task_complete? → END    │
                    │  else → ORCHESTRATOR     │
                    └─────────────────────────-┘

Persistence : SqliteSaver → .claude/04_GRAPHIFY/forge_checkpoints.db
              + sync JSON → .claude/05_STATE/checkpoint.json (lisible Claude)
"""

from __future__ import annotations
import os
import threading
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from .forge_state import ForgeState, initial_state
from .agent_nodes import (
    orchestrator_node,
    estimate_budget_node, post_mortem_node, dynamic_agent_node, memory_pruner_node,
    zsl_analysis_node, neuro_symbolic_verification_node, anti_hallucination_node,
    generate_blueprint_node, validate_blueprint_node, route_after_blueprint,
    escalate_human_node,
    _nmp_emit,
)
from .auto_complexification import (
    auto_complexification_node,
    route_after_complexification,
    route_from_orchestrator,
    route_after_agent,
    route_after_verification,
    route_after_hallucination_check,
)
from .graphify_checkpointer import checkpoint_state_to_json, load_last_checkpoint, load_progress_checkpoint

# ── V6 Imports ────────────────────────────────────────────────────────────────
from .forge_kernel import get_or_extract_kernel
from .forge_shared_brain import get_brain
from .forge_meta import get_meta
from .forge_lazy import get_lazy_engine
from .forge_experience_db import get_experience_db, Experience
from .forge_event_bus import get_event_bus, get_tracer, ForgeEvent
from .forge_self_heal import get_healer

# ── V6.1 Imports — Cache Orchestrator + Turn Checkpointer (session design 2026-07) ──
from .forge_cache_orchestrator import get_cache_orchestrator
from .forge_checkpoint_engine import get_turn_checkpointer
import logging

logger = logging.getLogger(__name__)

# ── Chemin SQLite pour le checkpointing ──────────────────────────────────────

FORGE_ROOT = Path(__file__).parent.parent.parent
# Chemin historique (mode opérateur mono-utilisateur / secours global).
DB_PATH = str(FORGE_ROOT / "04_GRAPHIFY" / "forge_checkpoints.db")
(FORGE_ROOT / "04_GRAPHIFY").mkdir(parents=True, exist_ok=True)


def _db_path() -> str:
    """Chemin de la base de checkpoints SQLite LangGraph, cloisonné par tenant (W5-03c) :
    l'état de run d'un client ne partage jamais la même base qu'un autre. Résolu à l'appel
    (tenant en contexte au moment de la requête) via forge_store ; sans tenant → base
    historique globale `04_GRAPHIFY/forge_checkpoints.db`."""
    try:
        from .forge_tenant import current_tenant_or_none
        from . import forge_store
    except Exception:
        return DB_PATH
    if current_tenant_or_none() is not None:
        return str(forge_store.tenant_dir() / "forge_checkpoints.db")
    return DB_PATH


# ── V6 Nodes ──────────────────────────────────────────────────────────────────

def v6_init_node(state: ForgeState) -> dict:
    """
    V6 Initialization Node.
    Extrait le kernel, initialise le shared brain, démarre le lazy engine.
    C'est LA porte d'entrée V6 — remplace le simple estimate_budget comme premier node.
    """
    task = state.get("current_task", "")
    bus = get_event_bus()
    tracer = get_tracer()

    # 1. Kernel extraction
    brain = get_brain()
    kernel = brain.initialize_for_task(task)

    # 2. Lazy engine plan
    lazy = get_lazy_engine()
    lazy.reset_loops()
    plan = lazy.plan(task, domain=kernel.domain)

    # 3. Start execution trace
    tracer.start_trace(task)

    # 3b. Cache Orchestrator — cascade exact -> semantic -> recompute -> compute
    #     (session de design 2026-07 : "cache = mémoire calculée", décision unique
    #     avant tout recalcul, cf. forge_cache_orchestrator.py). Observation seule
    #     à ce stade : ne court-circuite pas encore l'exécution de l'agent, mais
    #     rend la décision visible dans le state pour les nodes suivants/dashboard.
    cache_decision = None
    try:
        cache_orch = get_cache_orchestrator()
        cache_decision = cache_orch.decide(task, domain=kernel.domain)
    except Exception as e:
        bus.emit(ForgeEvent(type="CACHE_ORCH_ERROR", source="v6_init", data={"error": str(e)}))

    # 4. Emit events
    bus.emit_kernel_extracted(kernel.kernel_id, kernel.domain, kernel.confidence)
    bus.emit(ForgeEvent(
        type="V6_INIT",
        source="v6_init",
        data={
            "kernel_id": kernel.kernel_id,
            "domain": kernel.domain,
            "complexity": kernel.complexity_estimate,
            "lazy_strategy": plan.strategy,
            "cache_strategy": cache_decision.strategy if cache_decision else "unavailable",
        },
    ))

    # 5. Meta layer init
    meta = get_meta()

    # NMP → Event Stream dashboard (audit ticket 1)
    _nmp_emit("INIT", "V6_INIT", kernel.domain,
              f"kernel={kernel.kernel_id} complexity={kernel.complexity_estimate}")

    return {
        "kernel_id": kernel.kernel_id,
        "kernel_domain": kernel.domain,
        "kernel_confidence": kernel.confidence,
        "shared_context": brain.get_agent_context(task, "init"),
        "lazy_strategy": plan.strategy,
        "lazy_reason": plan.reason,
        "cache_strategy": cache_decision.strategy if cache_decision else "unavailable",
        "cache_reason": cache_decision.reason if cache_decision else "",
        "meta_confidence": meta.emotional.confidence,
        "meta_uncertainty": meta.emotional.uncertainty,
        "meta_risk": meta.emotional.risk,
        "meta_reward": meta.emotional.reward,
        "meta_curiosity": meta.emotional.curiosity,
        "events_emitted": 2,
    }


def v6_post_execution_node(state: ForgeState) -> dict:
    """
    V6 Post-Execution Node.
    Après chaque agent, met à jour : meta layer, experience DB, event bus, self-heal.
    """
    bus = get_event_bus()
    meta = get_meta()
    exp_db = get_experience_db()
    healer = get_healer()
    tracer = get_tracer()

    # 1. Get execution metrics
    tokens = state.get("agent_output_tokens", 0)
    agent_name = state.get("dynamic_agent_name", "unknown")
    verdict = state.get("jury_verdict") or {}
    quality = verdict.get("consensus", 5.0)
    success = verdict.get("decision") == "APPROVED"

    # 2. Update meta layer
    meta.observe_execution(
        node=agent_name,
        success=success,
        cost=tokens * 0.00003,
        latency=0,
        tokens=tokens,
        hallucinations=0,
        quality=quality,
    )

    # 2b. Alimente meta.health depuis le profiler → réveille la règle heal_system
    #     de suggest_optimization (broken_nodes était toujours vide = code mort).
    meta.health.broken_nodes   = exp_db.get_dead_components()
    meta.health.underused_nodes = exp_db.get_degraded_components()

    # 3. Get meta recommendation
    recommendation = meta.suggest_optimization()
    rec_str = ""
    if recommendation:
        rec_str = f"{recommendation['type']}: {recommendation['action']}"
        bus.emit_optimization(recommendation["type"], recommendation["action"], recommendation["reason"])

    # 4. Record experience
    kernel_id = state.get("kernel_id", "")
    domain = state.get("kernel_domain", "")
    exp = Experience(
        kernel_id=kernel_id,
        task=state.get("current_task", "")[:100],
        used_nodes=[agent_name],
        outcome="success" if success else "failure",
        reason=verdict.get("decision", "unknown"),
        tokens_used=tokens,
        quality_score=quality,
        domain=domain,
    )
    exp_db.record(exp)

    # NMP → Event Stream dashboard (audit ticket 1)
    _nmp_emit("SUCCESS" if success else "ERR", "V6_POST", agent_name,
              f"quality={quality} tokens={tokens}")

    # 5. Self-heal check
    heal_actions = []
    comp_health = exp_db._component_health
    actions = healer.diagnose(comp_health)
    for a in actions[:3]:
        healer.execute_action(a)
        heal_actions.append(f"{a.action_type}:{a.target}")

    # 5b. Cache Orchestrator — écrit le résultat (traçable, versionné) seulement
    #     si le calcul a réellement eu lieu (pas de ré-écriture d'un hit de cache).
    if success and state.get("cache_strategy") == "compute":
        try:
            get_cache_orchestrator().record(
                query=state.get("current_task", ""),
                result=verdict.get("summary", verdict) if isinstance(verdict, dict) else str(verdict),
                quality=quality,
                agent=agent_name,
                domain=domain,
            )
        except Exception:
            pass  # non bloquant — l'exécution a réussi, le cache est un bonus

    # 6. Trace
    tracer.add_step(agent_name, tokens * 0.00003, 0, tokens, quality)

    # 7. Emit event
    bus.emit_node_executed(agent_name, tokens * 0.00003, 0, quality, tokens)

    # 8. Harness badge (MVP ticket 7) : grade qualité si des fichiers artefacts
    #    ont été produits par l'agent (state["artifact_files"]). Skip sinon —
    #    on n'invente pas un grade sans artefact réel.
    harness_grade = state.get("harness_grade", "")
    artifact_files = state.get("artifact_files") or []
    if artifact_files:
        try:
            from .harness_engine import validate_code
            hr = validate_code(artifact_files)
            s = hr.score
            harness_grade = ("A+" if s >= 95 else "A" if s >= 90 else "B" if s >= 80
                             else "C" if s >= 70 else "D" if s >= 60 else "F")
            _nmp_emit("SUCCESS" if hr.passed else "ERR", "HARNESS", agent_name,
                      f"grade={harness_grade} score={s:.0f}")
        except Exception as e:
            _nmp_emit("ERR", "HARNESS", agent_name, str(e)[:60])

    # 8. Auto-indexing post-task (non-blocking)
    try:
        from .forge_versioning import get_versioning
        versioning = get_versioning()
        # Detect if files were written during this execution
        files_written = any(
            kw in state.get("current_task", "").lower()
            for kw in ("write", "create", "modify", "edit", "build", "implement", "fix")
        )
        versioning.maybe_auto_index(files_written=files_written or success)
    except Exception as e:
        logger.debug(f"[V6_POST] Auto-index skip: {e}")

    # 8b. GitNexus re-index (non-blocking background thread)
    def _run_gitnexus_bg():
        try:
            import subprocess
            gitnexus = FORGE_ROOT / ".gitnexus" / "run.cjs"
            if gitnexus.exists():
                subprocess.run(
                    ["node", str(gitnexus), "analyze"],
                    cwd=str(FORGE_ROOT), capture_output=True, timeout=60,
                )
            else:
                subprocess.run(
                    ["npx", "gitnexus", "analyze"],
                    cwd=str(FORGE_ROOT), capture_output=True, timeout=60,
                )
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    threading.Thread(target=_run_gitnexus_bg, daemon=True).start()

    # 8c. GitHub repo indexing hook (non-blocking)
    task_text = state.get("current_task", "")
    if "github.com" in task_text.lower():
        def _index_github_bg():
            try:
                import sys
                sys.path.insert(0, str(FORGE_ROOT / "scripts"))
                from github_indexer import index_from_chat_message
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(index_from_chat_message(task_text))
                loop.close()
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        threading.Thread(target=_index_github_bg, daemon=True).start()

    return {
        "harness_grade": harness_grade,
        "meta_confidence": meta.emotional.confidence,
        "meta_uncertainty": meta.emotional.uncertainty,
        "meta_risk": meta.emotional.risk,
        "meta_reward": meta.emotional.reward,
        "meta_curiosity": meta.emotional.curiosity,
        "meta_recommendation": rec_str,
        "experience_recorded": True,
        "heal_actions": heal_actions,
        "events_emitted": state.get("events_emitted", 0) + 2,
    }


def knowledge_curator_node(state: ForgeState) -> dict:
    """
    Knowledge Curator — sync asynchrone Kuzu → Obsidian vault.
    Exécuté après post_mortem, avant END. Non-bloquant : échec silencieux.
    """
    try:
        from .knowledge_curator import get_curator
        curator = get_curator()
        results = curator.curate(state)

        _nmp_emit("SUCCESS", "CURATOR", state.get("dynamic_agent_name", "?"),
                  f"agents={results.get('agents_synced', 0)} "
                  f"projects={results.get('projects_synced', 0)} "
                  f"concepts={results.get('concepts_synced', 0)} "
                  f"notes={sum(results.values())}")

        return {"curator_results": results}
    except Exception as e:
        _nmp_emit("ERR", "CURATOR", "curator", str(e)[:80])
        return {"curator_results": {"error": str(e)}}


# ── Construction du graph ────────────────────────────────────────────────────

def build_forge_graph(use_sqlite: bool = True):
    """
    Construit et compile le graph LangGraph de la Forge.
    use_sqlite=True  → persistence SQLite (recommandé en prod)
    use_sqlite=False → MemorySaver (tests, sessions courtes)
    """
    graph = StateGraph(ForgeState)

    # ── Nodes ────────────────────────────────────────────────────────────────
    graph.add_node("v6_init",               v6_init_node)
    graph.add_node("estimate_budget",       estimate_budget_node)
    graph.add_node("orchestrator",         orchestrator_node)
    graph.add_node("generate_blueprint",   generate_blueprint_node)
    graph.add_node("validate_blueprint",   validate_blueprint_node)
    graph.add_node("dynamic_agent",        dynamic_agent_node)
    graph.add_node("v6_post_execution",    v6_post_execution_node)
    graph.add_node("auto_complexification", auto_complexification_node)
    graph.add_node("post_mortem",           post_mortem_node)
    graph.add_node("memory_pruner",         memory_pruner_node)
    graph.add_node("zsl_analysis",          zsl_analysis_node)
    graph.add_node("neuro_symbolic_verification", neuro_symbolic_verification_node)
    graph.add_node("anti_hallucination",    anti_hallucination_node)
    graph.add_node("escalate_human",        escalate_human_node)

    # ── V6 Entry point : v6_init → estimate_budget → orchestrator ─────────────
    graph.set_entry_point("v6_init")
    graph.add_edge("v6_init", "estimate_budget")
    graph.add_edge("estimate_budget", "orchestrator")

    # ── Edges : orchestrator → generate_blueprint (conditional) ─────────────
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "generate_blueprint": "generate_blueprint",
            "zsl_analysis": "zsl_analysis",
            "__end__": END,
        }
    )

    # ── Edges : generate_blueprint → validate_blueprint ─────────────────────
    graph.add_edge("generate_blueprint", "validate_blueprint")

    # ── Edges : validate_blueprint → zsl_analysis | generate_blueprint ─────
    graph.add_conditional_edges(
        "validate_blueprint",
        route_after_blueprint,
        {
            "zsl_analysis": "zsl_analysis",
            "generate_blueprint": "generate_blueprint",  # révision si rejeté
        }
    )

    # ── Edges : chaque agent → v6_post_execution → auto_complexification ─────
    graph.add_conditional_edges(
        "dynamic_agent",
        route_after_agent,
        {
            "auto_complexification": "v6_post_execution",
            "neuro_symbolic_verification": "neuro_symbolic_verification",
            "__end__": END,
        }
    )

    # V6: post_execution → auto_complexification
    graph.add_edge("v6_post_execution", "auto_complexification")
    
    # ── Edges : zsl_analysis → dynamic_agent ─────────────────────────────────
    graph.add_edge("zsl_analysis", "dynamic_agent")
    
    # ── Edges : neuro_symbolic_verification → anti_hallucination ─────────────
    graph.add_conditional_edges(
        "neuro_symbolic_verification",
        route_after_verification,
        {
            "anti_hallucination": "anti_hallucination",
        }
    )
    
    # ── Edges : anti_hallucination → auto_complexification or back to agent ──
    graph.add_conditional_edges(
        "anti_hallucination",
        route_after_hallucination_check,
        {
            "auto_complexification": "auto_complexification",
            "dynamic_agent": "dynamic_agent",
            "escalate_human": "escalate_human",   # SPINE: honnêteté → humain
        }
    )

    # ── SPINE : escalate_human → END (run stoppé, en attente humaine) ────────
    graph.add_edge("escalate_human", END)

    # ── Edges : auto_complexification → orchestrator | post_mortem ────────────
    graph.add_conditional_edges(
        "auto_complexification",
        route_after_complexification,
        {
            "orchestrator": "memory_pruner",
            "__end__": "post_mortem",
        }
    )

    # ── Edges : post_mortem → knowledge_curator → END ────────────────────
    graph.add_edge("memory_pruner", "orchestrator")
    graph.add_node("knowledge_curator", knowledge_curator_node)
    graph.add_edge("post_mortem", "knowledge_curator")
    graph.add_edge("knowledge_curator", END)

    # ── Compile avec checkpointer ─────────────────────────────────────────────
    # Hiérarchie optiforge two-tier :
    #   PRIMAIRE = PostgresSaver (PG up)  →  SECOURS = SqliteSaver (forge_checkpoints.db)
    #   --no-sqlite (use_sqlite=False)    →  MemorySaver (tests, stateless)
    if not use_sqlite:
        from langgraph.checkpoint.memory import MemorySaver
        return graph.compile(checkpointer=MemorySaver())

    checkpointer = _make_checkpointer()
    return graph.compile(checkpointer=checkpointer)


def _make_checkpointer():
    """PostgresSaver si la DB est joignable, sinon repli SqliteSaver (secours chaud)."""
    # 1. Tenter Postgres (primaire) — seulement si forge_db voit la DB up
    try:
        from .forge_db import get_db, DATABASE_URL
        if get_db().pg_ok:
            from langgraph.checkpoint.postgres import PostgresSaver
            saver_cm = PostgresSaver.from_conn_string(DATABASE_URL)
            saver = saver_cm.__enter__()
            saver.setup()
            globals()["_pg_saver_cm"] = saver_cm  # garde le contexte ouvert
            print("[forge_graph] Checkpointer = PostgresSaver (primaire)")
            return saver
    except Exception as e:
        print(f"[forge_graph] PostgresSaver indisponible → secours SQLite ({e.__class__.__name__})")

    # 2. Secours : SqliteSaver existant
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    db_path = _db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    globals()["conn"] = conn  # référencé par run_forge.py au cleanup
    return SqliteSaver(conn)


# ── Runner principal ─────────────────────────────────────────────────────────

class ForgeRunner:
    """
    Interface haut niveau pour lancer des cycles de la Forge.
    Gère la persistance SQLite + sync JSON + logs.
    """

    def __init__(self, session_id: str = "default", use_sqlite: bool = True):
        self.session_id = session_id
        self.graph = build_forge_graph(use_sqlite=use_sqlite)
        self.config = {"configurable": {"thread_id": session_id}}

    def run_task(self, task: str, task_desc: str = "", max_cycles: int = 5, quiet: bool = False) -> dict:
        """
        Lance un cycle complet pour une tâche donnée.
        Retourne l'état final.
        """
        # Bootstrap depuis checkpoint JSON si disponible
        last_cp = load_last_checkpoint()
        cycle_start = last_cp.get("cycle_count", 0)
        level_start = last_cp.get("current_level", "L1")

        state = initial_state(task, task_desc, self.session_id)
        state["cycle"] = cycle_start
        state["level"] = level_start

        progress_cp = load_progress_checkpoint()
        if progress_cp.get("todo") or progress_cp.get("done"):
            state["progress_done"] = progress_cp.get("done", [])
            state["progress_todo"] = progress_cp.get("todo", [])
            state["progress_current_step"] = progress_cp.get("current_step", "")

        if not quiet:
            print(f"\n{'='*60}")
            print(f"FORGE RUN — task={task} session={self.session_id}")
            print(f"Level: {level_start} | Cycle start: {cycle_start}")
            if progress_cp.get("todo") or progress_cp.get("done"):
                print(f"Progress: {len(progress_cp.get('done', []))} done | "
                      f"{len(progress_cp.get('todo', []))} todo | "
                      f"last_step={progress_cp.get('current_step', '?')}")
                for t in progress_cp.get("todo", [])[:5]:
                    print(f"  TODO -> {t}")
            print(f"{'='*60}\n")

        result = None
        for step in self.graph.stream(state, config=self.config):
            node_name = list(step.keys())[0]
            node_state = step[node_name]

            if not node_state:
                continue

            # Print caveman log
            if not quiet:
                for msg in node_state.get("caveman_log", []):
                    if isinstance(msg, dict):
                        print(f"  [{msg.get('sender','?')}] {msg.get('verb','?')} {msg.get('object','')}")

                # Jury verdict
                verdict = node_state.get("jury_verdict")
                if verdict and isinstance(verdict, dict):
                    print(f"  → JURY: {verdict.get('decision','?')} consensus={verdict.get('consensus',0):.2f}")

                # Progress checkpoint (DONE/TODO)
                if node_state.get("progress_current_step"):
                    todo_n = len(node_state.get("progress_todo", []))
                    print(f"  → PROGRESS: step={node_state['progress_current_step']} | {todo_n} remaining")

            result = node_state

            # Checkpoint intelligent (session de design 2026-07) : snapshot toutes les
            # 2 interactions OU immédiatement si événement critique (jury REJETÉ, action
            # de self-heal déclenchée). Remplace le dump complet à CHAQUE step (coûteux,
            # non filtré) par forge_checkpoint_engine.TurnCheckpointer. Le fichier maître
            # 05_STATE/checkpoint.json (_update_master_checkpoint, lu par CLAUDE.md au
            # boot) reste, lui, toujours écrit intégralement en fin de run — inchangé.
            verdict = node_state.get("jury_verdict") or {}
            is_critical = (
                verdict.get("decision") == "REJECTED"
                or bool(node_state.get("heal_actions"))
                or bool(node_state.get("error"))
            )
            get_turn_checkpointer().record_turn(node_state, critical=is_critical)

        # Sync final
        if result:
            checkpoint_state_to_json(result, label="forge_last_complete")
            self._update_master_checkpoint(result)

        if not quiet:
            print(f"\n{'='*60}")
            print(f"FORGE COMPLETE — findings={len(result.get('findings',[]) if result else [])}")
            print(f"Level: {result.get('level','?') if result else '?'}")
            print(f"{'='*60}\n")

        return result or {}

    def _update_master_checkpoint(self, state: dict) -> None:
        """Met à jour checkpoint.json maître (lu par CLAUDE.md au INIT)."""
        import json, datetime
        # Cloisonné par tenant (W5-03c) : le checkpoint maître d'un client lui appartient.
        # Sans tenant → repli GLOBAL 05_STATE/checkpoint.json (identique à l'historique, lu
        # par CLAUDE.md au INIT), assuré par state_path lui-même.
        try:
            from .forge_store import state_path
        except ImportError:
            from forge_agents.forge_store import state_path
        cp_path = state_path("checkpoint.json")
        try:
            cp = json.load(open(cp_path, encoding="utf-8")) if cp_path.exists() else {}
        except Exception:
            cp = {}

        cp.update({
            "current_level": state.get("level", cp.get("current_level", "L1")),
            "cycle_count": state.get("cycle", cp.get("cycle_count", 0)),
            "last_task": state.get("current_task", ""),
            "last_task_slug": state.get("current_task", "").replace(" ", "_").lower(),
            "total_findings_confirmed": len([f for f in state.get("findings", [])
                                             if isinstance(f, dict) and f.get("status") == "confirmed"]),
            "graphify_nodes_added_session": state.get("graphify_nodes_added", 0),
            "progress": {
                "current_step": state.get("progress_current_step", ""),
                "done_count": len(state.get("progress_done", [])),
                "todo_count": len(state.get("progress_todo", [])),
                "todo_next": state.get("progress_todo", [])[:3],
            },
            "_meta": {**cp.get("_meta", {}), "last_updated": datetime.date.today().isoformat()},
        })
        with open(cp_path, "w", encoding="utf-8") as f:
            json.dump(cp, f, indent=2, ensure_ascii=False)

    def get_history(self) -> list[dict]:
        """Récupère l'historique des states depuis SQLite."""
        history = []
        for state in self.graph.get_state_history(self.config):
            history.append({
                "step": state.config.get("configurable", {}).get("checkpoint_id", "?"),
                "cycle": state.values.get("cycle", 0),
                "level": state.values.get("level", "L1"),
                "last_agent": state.values.get("next_agent", "?"),
                "findings": len(state.values.get("findings", [])),
            })
        return history
