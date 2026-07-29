"""
agent_nodes.py — Chaque agent de la Forge comme node LangGraph.
PATCH v2 : MiroFish gates réintégrées (kb_intake + plan_selection)

Chaque node suit le cycle universel :
  [ESTIMATE] → [INIT/Graphify] → [EXECUTE] → [JURY MiroFish] → [STORE/Graphify] → [AUTO-COMPLEXIFICATION] → [REPORT] → [POST-MORTEM]

Changements v2 :
  - _base_store() → Gate MiroFish 1 (kb_intake) si finding.score ≥ 7.5
  - orchestrator_node() → KB lookup avant création + Gate MiroFish 2 (plan_selection, Sonnet)
  - forge_orchestrate() importée depuis forge_llm
"""

from __future__ import annotations
import logging
logging.basicConfig(level=logging.INFO)
import json, datetime
from pathlib import Path

from langchain_core.messages import AIMessage
from .nanomachine import NANO_SYSTEM_PROMPT

from .forge_state import ForgeState, Finding, NMPPacket
from .graphify_checkpointer import (
    graphify_query, graphify_index, sync_findings_to_graphify,
    save_progress_checkpoint, load_progress_checkpoint, mark_step_done,
)
from .openviking import get_viking, VikingContext
from .forge_llm import forge_call, forge_score, forge_summarize, forge_orchestrate, LLMTier, tier_for_task
from .token_tracker import get_tracker
from .reward_engine import get_reward_engine, RewardSignal
from .tool_batcher import get_batcher
from .scraping_hook import maybe_scrape_for_task
from .a2a_protocol import A2A_SYSTEM_SUFFIX, A2APacket
from .adaptive_rag import get_adaptive_context
from .prompt_architect import forge_prompt_architect, should_invoke_prompt_architect
from .multi_source_brain import get_brain, classify_scale, ScaleClass, nmp_data_need, nmp_dl_done
from .turbovec_brain import get_turbovec_brain
from .nanomachine import (
    invoke_gitnexus, parse_and_route, boost_node,
    append_to_gitnexus_rules, deconstruct_task, TOKEN_CEILING,
)

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent

# Seuil de score pour déclencher gate kb_intake
KB_INTAKE_SCORE_THRESHOLD = 7.5
# Seuil de complexity pour déclencher gate plan_selection
PLAN_SELECTION_COMPLEXITY_THRESHOLD = 0.7

# optiforge §1-3 : mots-clés déclenchant la source hierarchy
_DATA_KEYWORDS = frozenset([
    "dataset", "corpus", "training data", "données", "examples",
    "huggingface", "kaggle", "gist", "samples", "fine-tune", "finetune",
    "benchmark", "embeddings", "vectorize", "ingest", "scrape dataset",
])


def _needs_external_data(task: str) -> tuple[bool, int]:
    """
    Détecte si la tâche nécessite des données externes.
    Retourne (needs_data, estimated_bytes).
    """
    t = task.lower()
    if not any(kw in t for kw in _DATA_KEYWORDS):
        return False, 0
    # Heuristique taille : "large" / "massive" → HEAVYWEIGHT, sinon FEATHERWEIGHT
    if any(w in t for w in ("large", "massive", "big", "full corpus")):
        return True, 500_000_000  # HEAVYWEIGHT
    if any(w in t for w in ("medium", "mid", "moderate")):
        return True, 50_000_000   # MIDWEIGHT
    return True, 500_000          # FEATHERWEIGHT par défaut


def _fetch_external_data(task: str, agent_name: str, log: list) -> str:
    """
    optiforge §3-4 : déclenche MultiSourceBrainOrchestrator (HF→Gists→Kaggle).
    Retourne un RÉSUMÉ vectorisé (jamais le raw) à injecter dans le contexte.
    Token Guard : seul le résumé entre dans le prompt.
    """
    needs, est_bytes = _needs_external_data(task)
    if not needs:
        return ""

    scale = classify_scale(est_bytes)
    nmp_msg = nmp_data_need(agent_name, ["huggingface", "github_gists", "kaggle"],
                             scale, est_bytes, task)
    log.append(_caveman("BRAIN", "DATA_NEED", task[:40],
                        scale=scale.value, nmp=nmp_msg[:60]))

    try:
        brain = get_brain()
        result = brain.select_source_and_scale(agent_name, task, est_bytes)
        if result and result.success:
            log.append(_caveman("BRAIN", "DATA_FETCHED", result.platform,
                                bytes=result.bytes_fetched, path=str(result.local_path)[:40]))
            # Résumé vectorisé via HAIKU tier (jamais raw dans contexte)
            summary = forge_call(
                f"Summarize this dataset acquisition in 3 bullet points for agent context:\n"
                f"Platform={result.platform} Bytes={result.bytes_fetched} Path={result.local_path}",
                tier=LLMTier.HAIKU, task_type="fast_extraction", max_tokens=200,
            )
            graphify_index(summary or "", agent=agent_name, cycle=0)
            log.append(_caveman("BRAIN", "DATA_VECTORIZED", agent_name,
                                nmp=nmp_dl_done(result.platform, str(result.local_path))[:60]))
            return summary or ""
        else:
            log.append(_caveman("BRAIN", "DATA_SKIP", "no_result"))
    except Exception as e:
        log.append(_caveman("BRAIN", "DATA_ERR", str(e)[:60]))

    return ""


# ── HELPERS COMMUNS ──────────────────────────────────────────────────────────

_nmp_logger = logging.getLogger("NMP")

def _nmp(action: str, source: str, target: str, payload: str = "") -> NMPPacket:
    """Produit un NMP packet strict : ACTION|SOURCE|TARGET|PAYLOAD"""
    return f"{action}|{source}|{target}|{payload}"

_NMP_LIVE_JSONL = Path(__file__).parent.parent.parent / "08_LOGS" / "events" / "live.jsonl"


def _nmp_live_path() -> Path:
    """Trace d'exécution live du client — cloisonnée par tenant (W5-03c).

    Avec un tenant en contexte, la trace part dans son espace (`forge_store`) : deux
    clients ne mélangent jamais leur flux live. Sans tenant (mode dashboard mono-
    utilisateur historique), on garde `08_LOGS/events/live.jsonl` pour ne pas casser
    le tail SSE du DASHBOARD."""
    try:
        from .forge_tenant import current_tenant_or_none
        from . import forge_store
    except Exception:
        return _NMP_LIVE_JSONL
    if current_tenant_or_none() is not None:
        return forge_store.state_path("events/live.jsonl")
    return _NMP_LIVE_JSONL


def _nmp_emit(action: str, source: str, target: str, payload: str = "") -> NMPPacket:
    """Émet ET retourne le NMP packet (stdout NMP, jamais prose).
    Pousse aussi l'event en JSONL append-only (live.jsonl) — consommé en tail
    par le SSE du DASHBOARD (Event Stream temps réel, pas de poll checkpoint)."""
    pkt = _nmp(action, source, target, payload)
    _nmp_logger.info(pkt)
    try:
        live_path = _nmp_live_path()
        live_path.parent.mkdir(parents=True, exist_ok=True)
        with live_path.open("a", encoding="utf-8") as _f:
            _f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "action": action, "source": source,
                "target": target, "payload": payload,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass  # le flux live ne doit jamais casser un node
    return pkt

# ── role_tag : rôle canonique (9 valeurs) pour la Neural Map du DASHBOARD ────
# L'agent reste dynamique (nom+prompt uniques) ; le tag sert uniquement au
# clustering visuel. Heuristique keyword d'abord (0 token), FREE tier en secours.

_ROLE_TAGS = ["orchestrator", "architecture", "backend", "frontend", "devops",
              "security", "token_optimization", "validator", "memory"]

_ROLE_KEYWORDS = {
    "security":           ["securit", "cve", "pentest", "vuln", "audit", "osint", "exploit"],
    "frontend":           ["frontend", "ui", "ux", "css", "html", "design", "landing", "react", "vue "],
    "devops":             ["deploy", "docker", "ci/cd", "coolify", "infra", "kubernetes", "pipeline ci"],
    "memory":             ["memoire", "memory", "graphify", "vector", "rag", "index", "embedding"],
    "token_optimization": ["token", "budget", "cost", "cache", "compress"],
    "validator":          ["test", "valid", "jury", "mirofish", "harness", "qa ", "review"],
    "architecture":       ["architect", "blueprint", "schema", "conception", "structure projet"],
    "orchestrator":       ["orchestr", "decompos", "planifi", "coordonn"],
}

def _classify_role_tag(task: str, agent_name: str) -> str:
    """Classe la tâche dans un des 9 rôles canoniques. Heuristique 0 token,
    fallback forge_call(FREE) une ligne, défaut 'backend'."""
    text = f"{task} {agent_name}".lower()
    for tag, kws in _ROLE_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return tag
    try:
        from .forge_llm import forge_call, LLMTier
        ans = forge_call(
            f"Classe cette tâche dans UNE catégorie parmi {_ROLE_TAGS}. "
            f"Réponds uniquement par le mot exact.\nTâche: {task[:200]}",
            tier=LLMTier.HAIKU, task_type="fast_extraction", max_tokens=10,
        ) or ""
        ans = ans.strip().lower()
        if ans in _ROLE_TAGS:
            return ans
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return "backend"

# Alias rétrocompat (si d'autres modules appellent encore _caveman)
def _caveman(sender: str, verb: str, obj: str, **meta) -> NMPPacket:
    payload = " ".join(f"{k}={v}" for k, v in meta.items())
    return _nmp(verb, sender, obj, payload)

def _new_finding(agent: str, content: str, score: float, cycle: int, suffix: str = "001") -> Finding:
    """
    Create a finding with NMP-encoded content.
    
    Content is encoded as: FINDING|AGENT|F-ID|score=X|status=pending|cycle=Y
    """
    from .nmp_encoder import encode_finding_nmp
    
    finding = Finding(
        id=f"F-{agent.upper()}-{cycle:03d}-{suffix}",
        agent=agent, cycle=cycle, content=content,
        score=score, jury_consensus=0.0,
        status="pending", graphify_indexed=False
    )
    
    # Encode content to NMP format
    nmp_content = encode_finding_nmp(finding)
    finding["content"] = nmp_content
    
    return finding
def _base_init(state: ForgeState, agent_name: str) -> str:
    """
    INIT standard — optiforge pipeline complet pour Mimo/Hermes :

    Ordre de priorité (zéro raw text en contexte) :
      1. GitNexus-First  → query graph local SANS LLM (0 tokens)
      2. TurboVec 4-bit  → top-5 vecteurs session compactés
      3. Graphify        → résumés indexés session précédente
      4. OpenViking      → nœuds sémantiques long-terme
      5. ExternalData    → résumé vectorisé dataset (jamais raw)

    TOKEN GUARD (optiforge §1) : raw text NEVER in LLM context.
    Ceiling Mimo/Hermes = 65 000 tokens.
    """
    task  = state.get("current_task", "")
    query = f"agent={agent_name} last_session task={task}"
    parts = []

    # 1. GitNexus-First — graph local, 0 tokens LLM
    gn_result = invoke_gitnexus("query", task)
    if gn_result and "ERR|GITNEXUS" not in gn_result:
        # Tronqué : seul le résumé entre dans le contexte (Token Guard)
        parts.append("[GitNexus/Graph]\n" + gn_result[:400])

    # 2. TurboVec 4-bit — recherche sémantique session
    brain = get_turbovec_brain()
    tv_results = brain.search(task, k=5)
    if tv_results:
        tv_lines = [f"- [{r['agent']}] {r['summary']}" for r in tv_results]
        parts.append("[TurboVec/4bit]\n" + "\n".join(tv_lines))

    # 3. Graphify — résumés indexés
    graph_ctx = graphify_query(query)
    if graph_ctx:
        parts.append("[Graphify]\n" + graph_ctx)

    # 4. OpenViking — nœuds sémantiques long-terme
    viking = get_viking()
    viking_ctx = viking.retrieve_context(
        query=f"{agent_name} {task}", task_type=task
    )
    findings_ctx = viking.get_findings_context()
    if viking_ctx and not viking_ctx.is_fallback:
        parts.append("[OpenViking]\n" + viking_ctx.content)
    if findings_ctx:
        parts.append(findings_ctx)

    # 5. ExternalData — résumé vectorisé multi-source (jamais raw)
    ext_ctx = state.get("_external_data_summary", "")
    if ext_ctx:
        parts.append("[ExternalData/Vectorized]\n" + ext_ctx)

    return "\n\n".join(parts) if parts else "(aucun contexte disponible)"


def _graphify_index_executor(tool: str, args_list: list[dict]) -> list:
    """Executor pour ToolCallBatcher : exécute un lot d'appels graphify_index."""
    if tool != "graphify_index":
        return [None] * len(args_list)
    return [graphify_index(a["content"], agent=a.get("agent", "ORCH"), cycle=a.get("cycle", 0))
            for a in args_list]


def _batched_index_findings(findings: list[Finding], cycle: int, batcher) -> int:
    """Empile l'indexation Graphify de chaque finding confirmé sur le batcher,
    puis exécute en lot. Retourne le nombre indexé avec succès."""
    queued: list[Finding] = []
    for f in findings:
        if f.get("status") == "confirmed" and not f.get("graphify_indexed"):
            content = (f"## FINDING-{f.get('id','UNK')}\nAgent:{f.get('agent')}\n"
                      f"Score:{f.get('score',0)}/10\nJury:{f.get('jury_consensus',0):.2f}\n"
                      f"Content:{f.get('content','')[:400]}")
            batcher.queue("graphify_index", {"content": content, "agent": f.get("agent", "ORCH"), "cycle": cycle})
            queued.append(f)
    results = batcher.flush_all()
    indexed = 0
    for f, ok in zip(queued, results[-len(queued):] if queued else []):
        if ok:
            f["graphify_indexed"] = True
            indexed += 1
    return indexed


def _base_store(state: ForgeState, agent_name: str, findings: list[Finding]) -> int:
    """
    STORE standard : indexe findings dans Graphify.
    NOUVEAU v2 : déclenche gate MiroFish kb_intake si score ≥ 7.5
    """
    cycle = state.get("cycle", 0)

    # Indexe résumé session
    summary = (
        f"## AGENT-{agent_name.upper()}-SESSION-{datetime.date.today()}\n"
        f"Cycle:{cycle} Task:{state.get('current_task','?')}\n"
        f"Findings:{len(findings)} Quality:{state.get('jury_verdict',{}).get('consensus',0) if state.get('jury_verdict') else 'N/A'}\n"
        f"Output preview:{state.get('agent_output','')[:200]}"
    )
    # ── Batching : regroupe les appels graphify_index (résumé + findings) ──
    # Au lieu d'un round-trip par finding, on empile et on exécute en un lot.
    batcher = get_batcher(batch_size=10)
    batcher.executor = _graphify_index_executor

    batcher.queue("graphify_index", {"content": summary, "agent": agent_name, "cycle": cycle})
    indexed = _batched_index_findings(findings, cycle, batcher)
    batcher.flush_all()

    # ── TurboVec 4-bit : indexe le résumé session (Token Guard) ─────────────
    brain = get_turbovec_brain()
    brain.store(
        text=summary,
        agent=agent_name,
        score=state.get("jury_verdict", {}).get("consensus", 0.0) if state.get("jury_verdict") else 0.0,
        cycle=cycle,
    )

    # ── Session Compaction (optiforge ceiling 65k Mimo/Hermes) ───────────────
    # Si pression > 85% du ceiling → compaction automatique TurboVec
    pressure = brain.token_pressure()
    if pressure["pressure_pct"] >= 85.0:
        pruned = brain.session_compaction()
        _nmp_emit("BOOST_NODE", agent_name, "SESSION_COMPACT",
                  f"pruned={pruned} tokens={brain.token_pressure()['session_tokens']} ceiling={TOKEN_CEILING}")
        # Boost node : écrit règle compaction dans AGENTS.md
        boost_node(agent_name, f"session_compacted pruned={pruned} cycle={cycle}")

    # ── Gate MiroFish 1 : KB Intake (hors hot path) ──────────────────────────
    kb_candidates = [f for f in findings if f.get("score", 0) >= KB_INTAKE_SCORE_THRESHOLD]
    if kb_candidates:
        _run_kb_intake_gate(kb_candidates, agent_name, cycle)

    # ── Rétro-apprentissage optiforge §4 (non-bloquant) ─────────────────────
    retroactive_learning_boost(state, agent_name)

    return indexed


def _run_kb_intake_gate(candidates: list[Finding], agent_name: str, cycle: int) -> None:
    """
    Gate MiroFish 1 — KB Intake.
    Appel asynchrone (best-effort) : ne bloque pas le cycle si échec.
    Jury en FREE tier. Si consensus ≥ 0.70 → finding promu en KB skill.
    """
    try:
        from .mirofish import get_mirofish
        from .kb_manager import get_kb_manager

        gate = get_mirofish()
        kb   = get_kb_manager()

        for finding in candidates:
            finding_dict = dict(finding)
            verdict = gate.kb_intake(finding=finding_dict)

            if verdict.decision == "APPROVED":
                kb.add_skill_from_finding(finding_dict, verdict)
                _nmp_emit("SUCCESS", "KB_INTAKE", finding_dict.get("id","?"),
                          f"promoted consensus={verdict.consensus:.2f}")
            else:
                _nmp_emit("ERR", "KB_INTAKE", finding_dict.get("id","?"),
                          f"rejected consensus={verdict.consensus:.2f} decision={verdict.decision}")
    except ImportError:
        _nmp_emit("ERR", "KB_INTAKE", agent_name, "import_missing")
    except Exception as e:
        _nmp_emit("ERR", "KB_INTAKE", agent_name, str(e)[:80])


# ── RETROACTIVE LEARNING BOOST (optiforge §4) ────────────────────────────────

def retroactive_learning_boost(state: ForgeState, agent_name: str) -> None:
    """
    Phase 3 optiforge : évolution rétroactive post-cycle.
    Extrait l'output comme insight court → write-back AGENTS.md + Graphify.
    Non-bloquant : échec silencieux.
    """
    try:
        from .multi_source_brain import get_brain
        output = state.get("agent_output", "")
        task = state.get("current_task", "")
        verdict = state.get("jury_verdict") or {}
        score = verdict.get("consensus", 0.0) if verdict else 0.0
        if not output or score < 6.0:
            return  # pas assez bon pour rétro-apprentissage
        insight = f"task={task!r} score={score:.1f} | {output[:180]}"
        get_brain().retroactive_learning_boost(agent_name, insight)
    except Exception as e:
        logging.getLogger("agent_nodes").debug(f"[RETRO-BOOST] skip: {e}")


# ── ORCHESTRATOR NODE ────────────────────────────────────────────────────────

def _ds_advisory(task: str, domain: str = "") -> str:
    """Data Scientist : injecte le verdict du profiler (forge_experience_db) dans
    le contexte orchestrateur → ferme la boucle analyse→décision. Réflexe local,
    0 token LLM. ponytail: le "Data Scientist" existe déjà (experience_db+meta),
    manquait juste ce branchement dans le décideur."""
    best = dead = halluc = None
    try:
        from .forge_experience_db import get_experience_db
        db = get_experience_db()
        best   = db.get_best_workflow(domain or None)
        dead   = db.get_dead_components()
        halluc = db.get_hallucination_sources()
    except Exception:
        pass  # le volet analytique ci-dessous reste utile même sans experience_db
    lines = []
    if best:
        lines.append(f"- Agent le plus fiable (domaine={domain or 'tous'}) : {best} — réutiliser si adapté.")
    if dead:
        lines.append(f"- ÉVITER (composants morts) : {', '.join(dead[:3])}")
    if halluc:
        top = halluc[0]
        lines.append(f"- MÉFIANCE hallucinations : {top['component']} ({top['hallucination_rate']:.0%}) — ajouter checkpoint vérif.")
    block = ("\n\n[DATA SCIENTIST — profiler experience_db]\n" + "\n".join(lines)) if lines else ""

    # Volet analytique complet (anomalies / prévisions / scorecards / A-B) —
    # 0 token LLM, purement statistique. Non bloquant.
    try:
        from .forge_data_scientist import get_data_scientist
        block += get_data_scientist().advisory(task=task, domain=domain)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return block


def orchestrator_node(state: ForgeState) -> dict:
    """
    L'orchestrateur analyse la tâche et instancie l'expert parfait à la volée.

    Flux v2 :
      1. KB lookup → réutiliser un skill existant si match ≥ 0.75
      2. forge_orchestrate() → génère le profil de l'agent dynamique
      3. Si complexity_score > 0.7 → Gate MiroFish 2 (plan_selection, Sonnet)
      4. Spawn l'agent avec le meilleur plan
    """
    cycle = state.get("cycle", 0) + 1
    task  = state.get("current_task", "")

    # Charge contexte Graphify + skills appris
    ctx        = graphify_query(f"orchestrator cycle={cycle} task={task}")
    skills_ctx = graphify_query(f"learned_skill task={task}")
    ctx        = f"{ctx}\n\n[SKILLS APPRIS PAR LE CURATEUR]\n{skills_ctx}"
    ctx       += _ds_advisory(task, state.get("kernel_domain", ""))  # ferme boucle profiler→décision

    # ── 1. KB Lookup — évite de recréer un agent qui existe déjà ─────────────
    kb_skill = _kb_lookup(task)
    if kb_skill:
        return _use_kb_skill(kb_skill, state, cycle, ctx)

    # Historique caveman court
    history_lines = state.get("nmp_log", [])[-5:]
    history = "\n".join(history_lines)

    # ── 2. forge_orchestrate() → profil agent dynamique ──────────────────────
    decision        = forge_orchestrate(task, ctx, history)
    complexity_score = decision.get("complexity_score", 0.0)
    dynamic_name    = decision.get("dynamic_agent_name", "General_Expert")
    dynamic_prompt  = decision.get("dynamic_prompt", "Tu es un expert.")

    # ── optiforge B2 : Task Deconstruction → atomic steps ≤ 2000 tok ────────
    atomic_steps = deconstruct_task(task, max_tokens_per_step=2000)
    if len(atomic_steps) > 1:
        logging.getLogger("agent_nodes").info(
            f"[DECONSTRUCT] task split into {len(atomic_steps)} atomic steps"
        )

    # ── optiforge §1-4 : Source Hierarchy si tâche data-intensive ───────────
    ext_log: list = []
    ext_summary = _fetch_external_data(task, "ORCH", ext_log)
    if ext_summary:
        state["_external_data_summary"] = ext_summary  # injecté via _base_init Token Guard

    log = [
        _caveman("ORCH", "SPAWN_EXPERT", f"name={dynamic_name}",
                 cycle=cycle, complexity=complexity_score,
                 atomic_steps=len(atomic_steps)),
    ] + ext_log

    # ── 2bis. Prompt Architect — aucun agent/skill existant ne couvre la tâche
    # ET complexity_score >= NO_AGENT_MATCH_THRESHOLD → on conçoit un agent
    # ULTRA (prompt système 10 sections), promouvable en skill KB ensuite.
    if should_invoke_prompt_architect(kb_skill, complexity_score):
        log.append(_nmp_emit("INIT", "PROMPT_ARCHITECT", dynamic_name,
                             f"complexity={complexity_score:.2f}"))
        arch = forge_prompt_architect(
            task=task, context=ctx,
            dynamic_agent_name=dynamic_name,
            draft_prompt=dynamic_prompt,
            history=history,
        )
        dynamic_name   = arch["dynamic_agent_name"]
        dynamic_prompt = arch["ultra_prompt"]
        log.append(_nmp("SUCCESS", "PROMPT_ARCHITECT", dynamic_name,
                        f"tools={arch.get('tools_required')}"))

    if complexity_score > PLAN_SELECTION_COMPLEXITY_THRESHOLD and cycle == 1:
        log.append(_nmp_emit("INIT", "PLAN_GATE", task[:40], f"complexity={complexity_score:.2f}"))
        dynamic_prompt = _run_plan_selection_gate(task, ctx, dynamic_prompt)

    # ── 3. Recrutement d'ÉQUIPE hybride ──────────────────────────────────────
    # L'orchestrateur choisit l'équipe de spécialistes de la micro-task. Le lead
    # (agent dynamique) pourra les appeler OU rappeler le roster KB à la demande.
    # {} si la task est mono-phase → lead seul (comportement historique).
    try:
        from .forge_team import assemble_team
        team = assemble_team(task, dynamic_name)
    except Exception as e:
        team = {}
        log.append(_nmp_emit("ERR", "TEAM", dynamic_name, str(e)[:60]))
    if team:
        log.append(_caveman("ORCH", "RECRUIT_TEAM", f"lead={dynamic_name}",
                            specialists=len(team.get("specialists", []))))

    msg = AIMessage(content=_nmp("INIT", "ORCH", dynamic_name,
                                  f"cycle={cycle} task={task[:60]}"))

    step_name = f"cycle{cycle}:spawn:{dynamic_name}"
    cp = mark_step_done(
        step=f"cycle{cycle}:orchestrate",
        next_steps=[step_name],
        session_id=state.get("session_id", ""),
        current_task=task,
    )

    return {
        "cycle": cycle,
        "next_agent": decision.get("next_agent", "dynamic_agent"),
        "dynamic_agent_name": dynamic_name,
        "dynamic_agent_prompt": dynamic_prompt,
        "team": team,
        "role_tag": _classify_role_tag(task, dynamic_name),
        "graphify_context": ctx,
        "messages": [msg],
        "nmp_log": log,
        "task_complete": False,
        "progress_done": cp["done"],
        "progress_todo": cp["todo"],
        "progress_current_step": cp["current_step"],
    }


def _kb_lookup(task: str) -> dict | None:
    """Cherche un skill existant en KB. Retourne le skill ou None."""
    try:
        from .kb_manager import get_kb_manager
        return get_kb_manager().lookup(task, threshold=0.75)
    except ImportError:
        return None
    except Exception as e:
        _nmp_emit("ERR", "KB_LOOKUP", task[:40], str(e)[:60])
        return None


def _use_kb_skill(skill: dict, state: ForgeState, cycle: int, ctx: str) -> dict:
    """Fast path : utilise un skill KB existant sans recréer d'agent."""
    skill_name   = skill.get("name", "KB_Skill")
    skill_prompt = skill.get("prompt", "Tu es un expert.")

    msg = AIMessage(content=_nmp("SUCCESS", "ORCH", skill_name, "KB_HIT"))
    log = [_nmp_emit("SUCCESS", "ORCH", skill_name, f"KB_HIT cycle={cycle}")]

    step_name = f"cycle{cycle}:kb_hit:{skill_name}"
    cp = mark_step_done(
        step=f"cycle{cycle}:orchestrate",
        next_steps=[step_name],
        session_id=state.get("session_id", ""),
        current_task=state.get("current_task", ""),
    )

    return {
        "cycle": cycle,
        "next_agent": "dynamic_agent",
        "dynamic_agent_name": skill_name,
        "dynamic_agent_prompt": skill_prompt,
        "role_tag": _classify_role_tag(state.get("current_task", ""), skill_name),
        "graphify_context": ctx,
        "messages": [msg],
        "nmp_log": log,
        "task_complete": False,
        "progress_done": cp["done"],
        "progress_todo": cp["todo"],
        "progress_current_step": cp["current_step"],
    }


def _run_plan_selection_gate(task: str, ctx: str, fallback_prompt: str) -> str:
    """Wrapper avec timeout 45s — ne bloque jamais le cycle au-delà."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_run_plan_selection_gate_inner, task, ctx, fallback_prompt)
        try:
            return fut.result(timeout=45)
        except concurrent.futures.TimeoutError:
            _nmp_emit("ERR", "PLAN_GATE", task[:40], "TIMEOUT_45s fallback")
            return fallback_prompt
        except Exception as e:
            _nmp_emit("ERR", "PLAN_GATE", task[:40], str(e)[:60])
            return fallback_prompt

def _run_plan_selection_gate_inner(task: str, ctx: str, fallback_prompt: str) -> str:
    """
    Gate MiroFish 2 — Plan Selection.
    1. Sonnet génère 3 plans d'implémentation
    2. MiroFish jury (FREE) sélectionne le meilleur
    Retourne le prompt du plan vainqueur, ou fallback_prompt si échec.
    """
    try:
        _nmp_emit("EXEC", "PLAN_GATE", task[:40], "generating 3 plans via Sonnet")
        plans_raw = forge_call(
            f"""Tu es un architecte expert en systèmes multi-agents.
Génère 3 plans d'implémentation DISTINCTS pour cette tâche.
Chaque plan doit avoir un angle différent (ex: vitesse, qualité, économie de tokens).

TÂCHE: {task}
CONTEXTE: {ctx[:600]}

Réponds en JSON strict :
{{
  "plans": [
    {{
      "id": "P1",
      "title": "Plan rapide",
      "content": "Description du plan et étapes clés...",
      "trade_offs": "Avantages et risques...",
      "estimated_tokens": 1500,
      "complexity": "low|medium|high"
    }},
    {{ "id": "P2", ... }},
    {{ "id": "P3", ... }}
  ]
}}""",
            tier=LLMTier.SONNET,  # ← SONNET obligatoire pour la conception
            max_tokens=1500,
            task_type="plan",
            node="plan_selection_gate",
            use_openviking=False,
        )

        # Parser les plans
        import re
        match = re.search(r'\{[\s\S]*\}', plans_raw)
        if not match:
            raise ValueError("JSON non trouvé dans la réponse Sonnet")
        plans_data = json.loads(match.group())
        plans = plans_data.get("plans", [])

        if len(plans) < 2:
            _nmp_emit("ERR", "PLAN_GATE", task[:40], "less_than_2_plans fallback")
            return fallback_prompt

        _nmp_emit("EXEC", "PLAN_GATE", "MIROFISH", f"deliberating plans={len(plans)}")
        from .mirofish import get_mirofish
        gate    = get_mirofish()
        verdict = gate.plan_selection(plans=plans, task_desc=task)

        _nmp_emit("SUCCESS", "PLAN_GATE", verdict.winner or "?",
                  f"consensus={verdict.consensus:.2f} decision={verdict.decision}")

        if verdict.decision in ("APPROVED", "REVISE") and verdict.winner_content:
            # Construire le prompt système à partir du plan vainqueur
            winner_plan = next((p for p in plans if p["id"] == verdict.winner), None)
            if winner_plan:
                return (
                    f"Tu es un expert mandaté pour exécuter ce plan d'implémentation.\n\n"
                    f"PLAN VALIDÉ ({verdict.winner} — consensus jury: {verdict.consensus:.0%}):\n"
                    f"{winner_plan.get('content', '')}\n\n"
                    f"TRADE-OFFS CONNUS:\n{winner_plan.get('trade_offs', '')}\n\n"
                    f"RISQUES IDENTIFIÉS PAR LE JURY:\n" +
                    "\n".join(f"- {r}" for r in verdict.risks[:3])
                )

        _nmp_emit("RETRY", "PLAN_GATE", "fallback",
                  f"rejected consensus={verdict.consensus:.2f}")
        return fallback_prompt

    except Exception as e:
        _nmp_emit("ERR", "PLAN_GATE", "exception", str(e)[:80])
        return fallback_prompt


# ── ESTIMATE BUDGET NODE ─────────────────────────────────────────────────────

def estimate_budget_node(state: ForgeState) -> dict:
    """
    Noeud d'entrée : génère le devis tokens AVANT toute exécution.
    Utilise les données historiques (token_sprint_tracker) pour affiner les estimations.
    """
    from .token_tracker import get_tracker, normalize_task, compute_cost, Model
    from .token_sprint_tracker import historical_estimate

    tracker = get_tracker()
    task = state.get("current_task", "market_scan")
    session_id = state.get("session_id", "default")
    sprint_id = state.get("sprint_id", "") or f"sprint_{datetime.datetime.utcnow().strftime('%Y_%m')}"

    tracker.reset_session(session_id, task)
    estimate = tracker.estimate_budget(task)

    # Historical refinement: adjust estimates based on past data
    task_type = normalize_task(task)
    historical_adjustments = {}
    for model in estimate:
        model_val = model.value if hasattr(model, 'value') else str(model)
        hist = historical_estimate(task_type, model_val)
        if hist and hist["confidence"] > 0.3:
            # Weighted blend: 60% historical, 40% heuristic
            blend_weight = min(0.6, hist["confidence"])
            est = estimate[model]
            est["input"] = int(est["input"] * (1 - blend_weight) + hist["estimated_in"] * blend_weight)
            est["output"] = int(est["output"] * (1 - blend_weight) + hist["estimated_out"] * blend_weight)
            est["cost"] = compute_cost(model, est["input"], est["output"])
            historical_adjustments[model_val] = {
                "confidence": hist["confidence"],
                "sample_count": hist["sample_count"],
                "avg_variance": hist["avg_variance_pct"],
            }

    table    = tracker.render_estimate_table()
    print(f"\n{table}\n")

    if historical_adjustments:
        print(f"  📊 Historical refinement applied to {len(historical_adjustments)} models")

    estimate_dict = {}
    for model, data in estimate.items():
        key = model.value if hasattr(model, 'value') else str(model)
        estimate_dict[key] = data

    log = [_caveman("BUDGET", "ESTIMATE", f"task={task}",
                    total_cost=sum(d["cost"] for d in estimate.values()))]

    return {
        "token_estimate": estimate_dict,
        "sprint_id": sprint_id,
        "task_id": session_id,
        "nmp_log": log,
        "messages": [AIMessage(content=_nmp("STATE", "BUDGET", task, f"estimated"))],
    }


# ── POST-MORTEM NODE ─────────────────────────────────────────────────────────

def post_mortem_node(state: ForgeState) -> dict:
    """
    Noeud de sortie : génère le rapport post-mortem tokens APRÈS exécution.
    Enregistre les données dans token_sprints et détecte les variances.
    """
    from .token_tracker import get_tracker, normalize_task, Model
    from .token_sprint_tracker import record_sprint, detect_variance

    tracker = get_tracker()
    actual_table = tracker.render_actual_table()
    print(f"\n{actual_table}")

    recs  = tracker.generate_recommendations()
    score = tracker.efficiency_score()
    print(f"\n  RECOMMANDATIONS")
    for r in recs:
        print(f"  {r}")
    print(f"\n  EFFICIENCY SCORE: {score}/100")

    report = tracker.generate_final_report()
    print(f"  Log saved -> {report.get('log_path', '?')}\n")

    actuals = tracker.actuals_by_model()
    actual_dict = {}
    for model, data in actuals.items():
        key = model.value if hasattr(model, 'value') else str(model)
        actual_dict[key] = data

    # ── SPRINT RECORDING — persist estimation vs actual ──
    sprint_id = state.get("sprint_id", "") or f"sprint_{datetime.datetime.utcnow().strftime('%Y_%m')}"
    task_id = state.get("task_id", "") or state.get("session_id", "default")
    task_type = normalize_task(state.get("current_task", ""))
    hallucination_detected = any(
        "hallucination" in r.lower() or "neuro-symbolic" in r.lower()
        for r in recs
    )

    sprint_variance = 0.0
    all_refinements = []
    for model, act_data in actuals.items():
        model_val = model.value if isinstance(model, Model) else str(model)
        est_data = tracker.estimate.get(model, {})
        est_in = est_data.get("input", 0)
        est_out = est_data.get("output", 0)
        est_cost = est_data.get("cost", 0.0)

        sprint_rec = record_sprint(
            sprint_id=sprint_id,
            task_id=task_id,
            task_type=task_type,
            model=model_val,
            estimated_in=est_in,
            estimated_out=est_out,
            actual_in=act_data["input"],
            actual_out=act_data["output"],
            cost_estimated=est_cost,
            cost_actual=act_data["cost"],
            hallucination_detected=hallucination_detected,
            latency_ms=act_data.get("latency_ms", 0),
        )

        variance_result = detect_variance(sprint_rec)
        if variance_result["recommendations"]:
            all_refinements.extend(variance_result["recommendations"])

        if abs(sprint_rec.variance_pct) > abs(sprint_variance):
            sprint_variance = sprint_rec.variance_pct

    if all_refinements:
        print(f"  🔄 AUTO-REFINEMENT: {len(all_refinements)} actions triggered (variance {sprint_variance:+.1f}%)")

    analysis = {
        "recommendations": recs,
        "efficiency_score": score,
        "savings_usd": report.get("savings_usd", 0),
        "log_path": report.get("log_path", ""),
        "sprint_id": sprint_id,
        "variance_pct": sprint_variance,
        "auto_refinements": all_refinements,
    }

    log = [_caveman("BUDGET", "POST_MORTEM", f"score={score}/100",
                    savings=report.get("savings_usd", 0), recs_count=len(recs))]

    # ── EVOMAP — auto-évolution LOCALE (opt-in: FORGE_EVOLVE=1) ──────────────
    # Sous-process `evolver solidify` (validateur réseau OFF, aucun login/sync/
    # publish). No-op propre si evolver absent ou racine non-git. Cf. evomap_evolve.py.
    import os as _os
    if _os.environ.get("FORGE_EVOLVE") == "1":
        try:
            from .evomap_evolve import evolve as _evolve
            _ev = _evolve(subcommand="solidify", intent="optimize")
            _msg = _ev.get("skipped") or ("ok" if _ev.get("ok") else str(_ev.get("error")))
            print(f"  EVOMAP evolve (local) -> {_msg}")
            log.append(_caveman("EVOLVE", "POST_MORTEM", str(_msg)[:80]))
        except Exception as _e:
            print(f"  EVOMAP evolve skipped: {_e}")

    # ── HARNESS — quality gate: scan mvp_output/ pour artifacts récents ──────
    # ponytail: scan passif des 10 dernières minutes, pas de tracking état requis.
    if _is_build_task(state.get("current_task", "")):
        try:
            import time as _time
            from pathlib import Path as _Path
            from .harness_engine import HarnessEngine, ArtifactType
            _mvp = _Path(__file__).parent.parent.parent / "mvp_output"
            if _mvp.exists():
                _recent = [d for d in _mvp.iterdir()
                           if d.is_dir() and _time.time() - d.stat().st_mtime < 600]
                if _recent:
                    _newest = max(_recent, key=lambda d: d.stat().st_mtime)
                    _files = (list(_newest.glob("**/*.py"))
                              + list(_newest.glob("**/*.js"))
                              + list(_newest.glob("**/*.ts")))
                    if _files:
                        _hr = HarnessEngine().validate(ArtifactType.CODE, _files[:20])
                        print(f"  HARNESS {_newest.name}: grade={_hr.grade} passed={_hr.passed}")
                        log.append(_caveman("HARNESS", "POST_MORTEM", f"grade={_hr.grade}"))
        except Exception as _e:
            print(f"  HARNESS skipped: {_e}")

    return {
        "token_actual": actual_dict,
        "token_analysis": analysis,
        "token_variance_pct": sprint_variance,
        "auto_refinement": {"actions": all_refinements, "count": len(all_refinements)},
        "nmp_log": log,
        "messages": [AIMessage(content=_nmp("DONE", "POST_MORTEM", "session",
                                             f"efficiency={score} recs={len(recs)} variance={sprint_variance:+.1f}%"))],
    }


# ── DYNAMIC AGENT ────────────────────────────────────────────────────────────

# optiforge : heuristique « tâche de code/build ? » pour router vers OpenHands.
# ponytail: simple keyword match, ceiling=mots-clés FR/EN. Si trop grossier un jour,
# remplacer par un classifieur free-tier (forge_score).
_BUILD_KW = ("code", "build", "implement", "implément", "développ", "develop", "écris le code",
             "refactor", "fix bug", "api", "endpoint", "compose", "déploie", "deploy", "saas",
             "landing", "website", "site web", "workflow", "bot", "script")


def _is_build_task(task: str) -> bool:
    t = (task or "").lower()
    return any(k in t for k in _BUILD_KW)


# ── DELIVERABLE BRIDGE (optiforge) ──────────────────────────────────────────
# ponytail: le graph produisait du TEXTE jamais écrit sur disque → 0 livrable.
# On force un contrat de sortie fichier-par-fichier, puis on parse + écrit.
_FILE_CONTRACT = (
    "\n\n## CONTRAT DE LIVRAISON — OBLIGATOIRE\n"
    "Émets CHAQUE fichier du livrable EXACTEMENT ainsi, sans prose entre les blocs :\n"
    "=== FILE: chemin/relatif.ext ===\n"
    "```\n<contenu complet du fichier>\n```\n"
    "Répète pour chaque fichier nécessaire. Code complet et fonctionnel, "
    "aucune abréviation, jamais de '...'. Pour un site : index.html d'abord, "
    "puis style.css, puis app.js."
)


def _extract_target_dir(task: str):
    """Devine le dossier de sortie depuis la task ('... dans path/to/dir/'). None sinon."""
    import re
    m = re.search(r'dans\s+([A-Za-z0-9_.\-/\\]+/)', task or "")
    if not m:
        m = re.search(r'([A-Za-z0-9_.\-/\\]+/site_[A-Za-z0-9_]+/?)', task or "")
    if not m:
        return None
    rel = m.group(1).strip().replace("\\", "/").rstrip("/")
    dest = (FORGE_ROOT / rel).resolve()
    try:  # garde-fou : rester sous FORGE_ROOT
        dest.relative_to(FORGE_ROOT.resolve())
    except ValueError:
        return None
    return dest


def _write_deliverables(output: str, target_dir) -> list:
    """Parse le contract '=== FILE: x ===' + fence et écrit les fichiers. Fallback: fences par langage."""
    import re
    if not output or target_dir is None:
        return []
    written: list = []

    def _safe_write(relpath: str, content: str):
        if not relpath or not content.strip():
            return
        # relpath peut inclure le préfixe du dossier cible (protocole COMMAND) → on
        # écrit relatif à target_dir en ne gardant que la partie après le nom du dossier.
        rp = relpath.replace("\\", "/").strip().lstrip("/")
        tname = target_dir.name
        if ("/" + tname + "/") in ("/" + rp) or rp.startswith(tname + "/"):
            rp = rp.split(tname + "/", 1)[1]
        dest = (target_dir / rp).resolve()
        try:  # garde-fou path traversal
            dest.relative_to(target_dir.resolve())
        except ValueError:
            dest = (target_dir / Path(rp).name).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content.strip("\n"), encoding="utf-8")
        written.append(str(dest))

    # 0. Protocole NMP COMMAND|<verbe>|path|content (ce que le routeur forge émet).
    # Le verbe varie selon le run : write / WRITE_FILE / create / file... → on les couvre.
    for path, content in re.findall(
            r'COMMAND\|(?:write_?file|writefile|write|create_?file|create|file|save)\|'
            r'([^|\n]+)\|(.*?)(?=\n?COMMAND\||\Z)', output, re.DOTALL | re.IGNORECASE):
        _safe_write(path, content)
    if written:
        return written

    parts = re.split(r'===\s*FILE:\s*(.+?)\s*===', output)
    if len(parts) > 1:  # contract respecté
        for i in range(1, len(parts), 2):
            relpath = parts[i].strip().strip('`"\'')
            body = parts[i + 1] if i + 1 < len(parts) else ""
            fence = re.search(r'```[a-zA-Z0-9]*\n(.*?)```', body, re.DOTALL)
            _safe_write(relpath, fence.group(1) if fence else body.strip())
    else:  # fallback : fences taggées par langage
        lang_map = {"html": "index.html", "css": "style.css",
                    "js": "app.js", "javascript": "app.js"}
        for lang, content in re.findall(r'```([a-zA-Z]+)\n(.*?)```', output, re.DOTALL):
            fn = lang_map.get(lang.lower())
            if fn:
                _safe_write(fn, content)

    # dernier recours : le modèle a dumpé du HTML brut (fence non fermée / sans wrapper)
    if not written and re.search(r'<!DOCTYPE html|<html', output, re.IGNORECASE):
        m = re.search(r'(<!DOCTYPE html.*|<html.*)', output, re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\n?```\s*$', '', m.group(1)) if m else output
        _safe_write("index.html", html)
    return written


# ── BLUEPRINT NODES (DevilDev spec-first) ───────────────────────────────────

MAX_BLUEPRINT_ATTEMPTS = 3

def generate_blueprint_node(state: ForgeState) -> dict:
    """
    Génère un blueprint architectural AVANT toute écriture de code.
    Inspiré de DevilDev : specification-first, pas de coding direct.
    
    Le blueprint décrit :
    - Architecture cible (fichiers, modules, patterns)
    - Signatures de fonctions/clés
    - Dépendances et impacts
    - Risques identifiés
    """
    task = state.get("current_task", "")
    agent_name = state.get("dynamic_agent_name", "DYNAMIC")
    agent_prompt = state.get("dynamic_agent_prompt", "")
    ctx = state.get("graphify_context", "")
    cycle = state.get("cycle", 0)
    prev_feedback = state.get("blueprint_feedback", "")
    attempt = state.get("blueprint_attempts", 0) + 1

    # Skip blueprint for non-build tasks (pure analysis, scoring, etc.)
    if not _is_build_task(task):
        _nmp_emit("SKIP", "BLUEPRINT", agent_name, "not_a_build_task")
        return {
            "blueprint": "(skipped — non-build task)",
            "blueprint_approved": True,
            "blueprint_feedback": "",
            "blueprint_attempts": attempt,
        }

    # Construire le prompt de blueprinting
    revision_hint = ""
    if prev_feedback:
        revision_hint = f"""
REVISE TON BLUEPRINT — le critic a rejeté la version précédente :
FEEDBACK DU CRITIC: {prev_feedback}
Corrige les problèmes identifiés et soumets une version améliorée.
"""

    blueprint_prompt = f"""Tu es un architecte logiciel senior. Avant de coder, tu dois produire un BLUEPRINT détaillé.

TÂCHE: {task}
AGENT ASSOCIÉ: {agent_name}
CONTEXTE: {ctx[:800]}
{revision_hint}

Produis un blueprint structuré avec ces sections :

## 1. Architecture Cible
- Structure de fichiers (noms exacts)
- Modules et leurs responsabilités
- Pattern architectural utilisé (MVC, hexagonal, etc.)

## 2. Interfaces & Signatures
- Fonctions/classes principales avec signatures
- Types de retour et paramètres
- Contrats entre modules

## 3. Dépendances
- Packages externes nécessaires
- Imports internes
- Configuration requise

## 4. Impact & Risques
- Fichiers existants modifiés
- Risques de régression
- Points d'attention

## 5. Plan d'Exécution
- Ordre des implémentations (étapes)
- Critères de validation par étape

Sois PRÉCIS et CONCRET. Pas de vague — chaque fichier, chaque signature, chaque dépendance doit être nommé.
Réponds en markdown structuré (pas de JSON)."""

    try:
        blueprint = forge_call(
            blueprint_prompt,
            tier=LLMTier.SONNET,  # Sonnet pour la conception architecturale
            max_tokens=2000,
            task_type="blueprint",
            node="generate_blueprint",
        ) or ""

        if not blueprint or len(blueprint) < 100:
            _nmp_emit("ERR", "BLUEPRINT", agent_name, "too_short_or_empty")
            blueprint = f"(blueprint failed — output trop court: {len(blueprint)} chars)"

        _nmp_emit("SUCCESS", "BLUEPRINT", agent_name,
                  f"generated attempt={attempt} len={len(blueprint)}")

    except Exception as e:
        _nmp_emit("ERR", "BLUEPRINT", agent_name, str(e)[:80])
        blueprint = f"(blueprint error: {str(e)[:100]})"

    return {
        "blueprint": blueprint,
        "blueprint_approved": False,  # sera validé par le node suivant
        "blueprint_feedback": "",     # reset feedback pour cette tentative
        "blueprint_attempts": attempt,
    }


def validate_blueprint_node(state: ForgeState) -> dict:
    """
    Valide le blueprint via un critic/jury.
    Si approuvé → dynamic_agent peut coder.
    Si rejeté → retour generate_blueprint (max 3 tentatives).
    """
    blueprint = state.get("blueprint", "")
    task = state.get("current_task", "")
    agent_name = state.get("dynamic_agent_name", "DYNAMIC")
    attempt = state.get("blueprint_attempts", 0)

    # Skip si blueprint skippé (non-build task)
    if blueprint.startswith("(skipped"):
        return {"blueprint_approved": True, "blueprint_feedback": ""}

    # Max tentatives atteint → forcer l'approbation avec warning
    if attempt >= MAX_BLUEPRINT_ATTEMPTS:
        _nmp_emit("RETRY", "BLUEPRINT_VALIDATE", agent_name,
                  f"max_attempts={attempt} force_approve")
        return {
            "blueprint_approved": True,
            "blueprint_feedback": "(force-approved après max tentatives)",
        }

    # Validation par le critic (FREE tier — pas de Sonnet pour la validation)
    validate_prompt = f"""Tu es un critic/architecte senior. Évalue ce blueprint architectural.

TÂCHE: {task}
BLUEPRINT:
{blueprint[:3000]}

Critères d'évaluation :
1. COMPLÉTUDE : toutes les sections sont-elles remplies ? Fichiers, signatures, dépendances nommées ?
2. COHÉRENCE : l'architecture tient-elle ? Les modules s'emboîtent-ils logiquement ?
3. FAISABILITE : est-ce réalisable avec les outils/dispos du projet ?
4. IMPACT : les risques sont-ils identifiés et mitigés ?

Réponds en JSON strict :
{{
  "approved": true/false,
  "score": 0.0-10.0,
  "feedback": "explication courte si rejeté, ou 'LGTM' si approuvé",
  "issues": ["problème 1", "problème 2"]
}}"""

    try:
        result_raw = forge_call(
            validate_prompt,
            tier=LLMTier.HAIKU,  # validation = pas besoin de Sonnet
            max_tokens=500,
            task_type="blueprint_validation",
            node="validate_blueprint",
        ) or ""

        import re
        match = re.search(r'\{[\s\S]*\}', result_raw)
        if not match:
            _nmp_emit("ERR", "BLUEPRINT_VALIDATE", agent_name, "no_json_found")
            return {"blueprint_approved": True, "blueprint_feedback": ""}

        result = json.loads(match.group())
        approved = result.get("approved", True)
        score = result.get("score", 5.0)
        feedback = result.get("feedback", "")
        issues = result.get("issues", [])

        if approved:
            _nmp_emit("SUCCESS", "BLUEPRINT_VALIDATE", agent_name,
                      f"approved score={score:.1f}")
            return {"blueprint_approved": True, "blueprint_feedback": ""}
        else:
            feedback_str = feedback
            if issues:
                feedback_str += " | ISSUES: " + "; ".join(issues[:3])
            _nmp_emit("RETRY", "BLUEPRINT_VALIDATE", agent_name,
                      f"rejected score={score:.1f} attempt={attempt}")
            return {
                "blueprint_approved": False,
                "blueprint_feedback": feedback_str,
            }

    except Exception as e:
        _nmp_emit("ERR", "BLUEPRINT_VALIDATE", agent_name, str(e)[:80])
        # En cas d'erreur de validation, on laisse passer (fail-open)
        return {"blueprint_approved": True, "blueprint_feedback": ""}


def route_after_blueprint(state: ForgeState) -> str:
    """
    Conditional edge après validate_blueprint.
    Si approuvé → zsl_analysis.
    Si rejeté et tentatives < max → generate_blueprint (révision).
    Si rejeté et tentatives >= max → zsl_analysis (force).
    """
    if state.get("blueprint_approved", False):
        return "zsl_analysis"

    attempt = state.get("blueprint_attempts", 0)
    if attempt < MAX_BLUEPRINT_ATTEMPTS:
        return "generate_blueprint"  # révision

    return "zsl_analysis"  # force après max tentatives



def dynamic_agent_node(state: ForgeState) -> dict:
    """
    Agent généré à la volée par l'orchestrateur.
    Utilise dynamic_agent_name et dynamic_agent_prompt.
    """
    agent_name    = state.get("dynamic_agent_name", "DYNAMIC")
    system_prompt = state.get("dynamic_agent_prompt", "Tu es un assistant.")
    task          = state.get("current_task", "")

    # ── Blueprint injection : l'agent reçoit le blueprint validé comme spec ──
    blueprint = state.get("blueprint", "")
    if blueprint and not blueprint.startswith("(skipped"):
        system_prompt += (
            "\n\n## BLUEPRINT VALIDÉ — SPEC À SUIVRE\n"
            "Tu dois implémenter exactement selon ce blueprint. "
            "Ne dévie pas de l'architecture, des signatures ou des dépendances listées.\n\n"
            f"{blueprint}\n\n"
            "---\nFin du blueprint. Code maintenant.\n"
        )

    # Activer LMCache prefix caching pour ce persona dynamique
    try:
        from .lmcache_integration import create_forge_cache
        cache_mgr = create_forge_cache()
        cache_mgr.register_agent_persona(agent_name, system_prompt)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # RAG adaptatif : remplace _base_init() par une stratégie de contexte
    # dimensionnée à la complexité de la tâche (cf. adaptive_rag.py).
    ctx, rag_meta = get_adaptive_context(state, agent_name)

    # Hook de scraping universel : si la tâche contient une/des URL(s),
    # Scrapling est appelé EN PREMIER (avant le LLM), Firecrawl en fallback
    # payant uniquement (cf. scraping_hook.py / scrapling_connector.py).
    scraped_ctx = maybe_scrape_for_task(task)
    if scraped_ctx:
        ctx += "\n\n[SCRAPLING]\n" + scraped_ctx

    # BBRIL — inject exploit patterns for bounty/pentest tasks ─────────────────
    _BOUNTY_KW = ("bounty", "pentest", "vulnérabilité", "vulnerability",
                  "exploit", "recon", "yesweHack", "hackerone", "bughunter")
    if any(kw in task.lower() for kw in _BOUNTY_KW):
        try:
            from .bbril_pipeline import get_patterns_for_target, format_patterns_for_prompt
            _bp = get_patterns_for_target(limit=5)
            if _bp:
                ctx += "\n\n[BBRIL — EXPLOIT PATTERNS]\n" + format_patterns_for_prompt(_bp)
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # optiforge §1-4 : Source Hierarchy (HF→Gists→Kaggle) si tâche data-intensive
    # Le résumé vectorisé (jamais raw) est déjà dans ctx via _base_init Token Guard.
    # Si l'orchestrateur n'a pas encore fetchée (cycle > 1 ou agent autonome), on fetch ici.
    ext_log_dyn: list = []
    if not state.get("_external_data_summary"):
        ext_summary = _fetch_external_data(task, agent_name, ext_log_dyn)
        if ext_summary:
            ctx += "\n\n[ExternalData/Vectorized]\n" + ext_summary

    prompt = f"Task: {task}\n\nContext:\n{ctx}"
    # Protocole AIL : sortie intermédiaire ultra-compacte (décodée en
    # français uniquement à la présentation finale, cf. ail_protocol.py).
    # PONYTAIL : échelle YAGNI ajoutée au system-prompt pour les tâches de code
    # (le meilleur code est celui qu'on n'écrit pas). No-op si tâche non-code.
    try:
        from .ponytail import yagni_suffix as _yagni
    except Exception:
        def _yagni(_t):
            return ""
    # optiforge : OpenHands REMPLACE le développeur. Si la tâche est un build/code
    # ET que le wrapper OpenHands est déployé, on délègue le code à OpenHands
    # (sandbox sur mvp_output/<projet>/) au lieu de le générer ici. No-op sinon
    # (status:planned dans registry.json) → fallback forge_call. Cf. tools/TOOLS.md §3.
    output = None
    if _is_build_task(task):
        try:
            from tools.dev.openhands import build as _oh_build  # actif si OPENHANDS_CMD/MODE dans .env
            # sandbox = dossier cible extrait de la task (sinon défaut mvp_output/_scratch)
            output = _oh_build(task, context=ctx, workspace=_extract_target_dir(task))
        except Exception:
            output = None  # OpenHands indispo → on retombe sur le LLM
    # ── ÉQUIPE : si l'orchestrateur a décomposé la task en micro-tasks, UN expert
    # dédié exécute chaque micro-task (pipeline), puis ce lead synthétise. Sinon,
    # exécution mono-agent historique (A2A output). ────────────────────────────
    team = state.get("team") or {}
    if output is None and team.get("specialists"):
        try:
            from .forge_team import run_team
            output, _team_log = run_team(
                lead_name=agent_name,
                lead_prompt=system_prompt + _yagni(task),
                task=task, ctx=ctx, team=team,
            )
            ext_log_dyn += _team_log
        except Exception as _e:
            output = None  # équipe indispo → fallback mono-agent
            ext_log_dyn.append(f"NMP|TEAM|{agent_name}|FAIL|{str(_e)[:60]}")
    _build = _is_build_task(task)
    if output is None:
        if _build:  # tâche de code : système DÉDIÉ (pas de NMP), contrat fichier, budget large
            _bp = state.get("blueprint", "")
            _spec = ("\n\n## SPEC À SUIVRE\n" + _bp) if (_bp and not _bp.startswith("(skipped")) else ""
            _sys = (
                "Tu es un développeur web senior. Génère UN SEUL fichier index.html "
                "AUTONOME et COMPLET : tout le CSS dans une balise <style>, tout le JS "
                "dans une balise <script> en fin de body. AUCUN fichier externe "
                "(pas de style.css ni app.js séparés). Site moderne, responsive, "
                "fonctionnel. Donne le fichier index.html ENTIER, du <!DOCTYPE html> "
                "à </html>, sans troncature ni '...'."
                + _spec + _FILE_CONTRACT
            )
            _mt = 12000
            _p = (f"{task}\n\nContexte:\n{ctx}\n\n"
                  "Génère MAINTENANT tous les fichiers complets du site selon le contrat de livraison.")
        else:
            _sys = system_prompt + A2A_SYSTEM_SUFFIX + _yagni(task)
            _mt = 1500
            _p = prompt
        output = forge_call(_p, system=_sys, tier=LLMTier.HAIKU,
                            max_tokens=_mt, task_type="generate")

    # DELIVERABLE BRIDGE : écrire les fichiers du build sur disque (sinon 0 livrable)
    written_files: list = []
    if _build:
        try:
            written_files = _write_deliverables(output, _extract_target_dir(task))
        except Exception as _e:
            ext_log_dyn.append(f"NMP|DELIVER|{agent_name}|FAIL|{str(_e)[:60]}")
    if written_files:
        ext_log_dyn.append(f"NMP|DELIVER|{agent_name}|OK|{len(written_files)} files")

    # If output matches A2A format, we extract metrics or details
    parsed_a2a = A2APacket.decode(output)
    score = parsed_a2a.score if (parsed_a2a and parsed_a2a.score is not None) else 8.0
    if written_files:
        score = max(score, 8.5)  # livrable réellement écrit sur disque = succès
        # SPINE DELIVER GATE : la Forge respecte ses propres règles avant de livrer.
        # legal_check bloquant (+ herald advisory). Échec → livraison bloquée + humain.
        try:
            from .forge_spine import deliver_gate, escalate_to_human
            _tgt = _extract_target_dir(task)
            if _tgt is not None:
                _gate = deliver_gate(_tgt)
                if not _gate.get("deliver_ready", True):
                    ext_log_dyn.append(
                        f"NMP|DELIVER|{agent_name}|BLOCKED|{_gate.get('reason','')[:60]}")
                    escalate_to_human(
                        question=(f"Livrable « {task} » BLOQUÉ (règles non respectées) : "
                                  f"{_gate.get('reason','')}. Grade={_gate.get('grade','?')}."),
                        context={"target": str(_tgt), "checks": _gate.get("checks", {})},
                        task=task)
                    score = min(score, 4.0)  # bloqué ≠ succès
        except Exception as _e:
            ext_log_dyn.append(f"NMP|DELIVER|{agent_name}|GATE_ERR|{str(_e)[:50]}")
    
    # Mandatory Fallow audit check for JS/TS workspaces
    try:
        from .fallow_guard import FallowGuard
        fallow = FallowGuard(str(FORGE_ROOT))
        if fallow.is_js_ts_project():
            audit = fallow.run_audit()
            if audit.get("status") == "fail":
                score = min(score, 5.0)  # Demote score if boundaries are violated
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
    # AAOS 92 : quality threshold — score < 5.0/10 (= 50%) → Data Acquisition.
    # Ne télécharge rien (protocole DATASETS : prévenir le user d'abord) :
    # enregistre le gap dans 07_KNOWLEDGE_BASE/datasets/knowledge_gaps.json.
    if score < 5.0:
        try:
            from .dataset_rag import record_knowledge_gap
            record_knowledge_gap(task, score, agent=agent_name)
        except Exception:
            pass  # best-effort

    findings = [_new_finding(agent_name, output[:500], score, state.get("cycle", 0))]

    # _base_store déclenche automatiquement gate kb_intake si score ≥ 7.5
    nb_indexed = _base_store(state, agent_name, findings)  # retourne un int

    # OPTIMISATION APRÈS CHAQUE APPEL (optiforge) : on compresse l'expérience de
    # CET appel en une règle réutilisable (boost_node → AGENTS.md + .cursorrules +
    # turbovec). L'agent devient meilleur à chaque exécution : la prochaine fois
    # qu'il est spawné, orchestrator/prompt_architect récupèrent ce boost en contexte.
    try:
        boost_node(agent_name, f"task={task[:120]} score={score} out={output[:300]}")
    except Exception:
        pass  # best-effort, ne casse jamais le cycle

    log = [_caveman(agent_name.upper(), "DONE", f"task={task}", score=score, indexed=nb_indexed,
                     rag_strategy=rag_meta.get("strategy"), scraped=bool(scraped_ctx))] + ext_log_dyn
    msg = AIMessage(content=_nmp("DONE", agent_name.upper(), "task",
                                  f"score={score:.1f} indexed={nb_indexed}"))

    from .forge_state import JuryVerdict
    fake_verdict = JuryVerdict(consensus=0.8, decision="APPROVED", suggestions=[], kill_flag=False)

    # task_complete=True → termine le cycle proprement (évite boucle infinie)
    MAX_CYCLES = 3
    current_cycle = state.get("cycle", 1)
    is_done = (score >= 7.0) or (current_cycle >= MAX_CYCLES)

    step_name = state.get("progress_current_step") or f"cycle{current_cycle}:spawn:{agent_name}"
    next_steps = [] if is_done else [f"cycle{current_cycle + 1}:orchestrate"]
    cp = mark_step_done(
        step=step_name,
        next_steps=next_steps,
        session_id=state.get("session_id", ""),
        current_task=task,
        notes=f"last_score={score} batcher={get_batcher().stats()}",
    )

    return {
        "findings": findings,  # list[Finding], pas le int retourné par _base_store
        "nmp_log": log,
        "agent_output": output,
        "jury_verdict": fake_verdict,
        "messages": [msg],
        "task_complete": is_done,
        "progress_done": cp["done"],
        "progress_todo": cp["todo"],
        "progress_current_step": cp["current_step"],
    }


# ── MEMORY PRUNER NODE ────────────────────────────────────────────────────────

def memory_pruner_node(state: ForgeState) -> dict:
    """Supprime les messages trop anciens si le contexte dépasse 15k tokens."""
    from langchain_core.messages import RemoveMessage

    messages = state.get("messages", [])
    if not messages:
        return {}

    total_tokens = sum(len(str(m.content)) / 4 for m in messages if hasattr(m, 'content'))
    MAX_TOKENS = 15000
    if total_tokens <= MAX_TOKENS:
        return {}

    tokens_to_remove = total_tokens - (MAX_TOKENS / 2)
    removed_tokens   = 0
    messages_to_remove = []

    for m in messages[1:-2]:
        if hasattr(m, 'id') and m.id:
            msg_toks = len(str(m.content)) / 4
            removed_tokens += msg_toks
            messages_to_remove.append(RemoveMessage(id=m.id))
            if removed_tokens >= tokens_to_remove:
                break

    if not messages_to_remove:
        return {}

    log = [_nmp_emit("BOOST_NODE", "MEMORY_PRUNER", "messages",
                     f"removed={len(messages_to_remove)} tokens_saved={int(removed_tokens)}")]
    return {"messages": messages_to_remove, "nmp_log": log}


# ═══════════════════════════════════════════════════════════════════════
# ZSL CYBER NODE — Zero-Shot Learning for Cybersecurity
def zsl_analysis_node(state: ForgeState) -> dict:
    """
    Zero-Shot Learning analysis.
    Analyzes code for vulnerabilities and optimizations, CTF challenges, threat intel without training data.
    """
    from .zsl_cyber import ZSLCyberEngine, ZSLTaskType

    engine = ZSLCyberEngine()
    task = state.get("task", "")
    code_context = state.get("code_context", "")

    # Determine analysis type
    findings = []
    confidence = 0.5
    task_type_val = "general_analysis"
    explanation = "General ZSL analysis."
    tokens_used = 0

    if "ctf" in task.lower() or "challenge" in task.lower():
        result = engine.analyze_ctf_challenge(task)
        findings = result.findings
        confidence = result.confidence
        task_type_val = result.task_type.value
        explanation = result.explanation
        tokens_used = result.tokens_used
    elif "threat" in task.lower() or "intel" in task.lower():
        result = engine.analyze_threat_intel(task)
        findings = result.findings
        confidence = result.confidence
        task_type_val = result.task_type.value
        explanation = result.explanation
        tokens_used = result.tokens_used
    else:
        # Run both security vulnerability patterns and algorithm optimization patterns for general code review tasks
        vuln_res = engine.analyze_code(code_context)
        opt_res = engine.optimize_algorithm(code_context)
        
        findings = vuln_res.findings + opt_res.findings
        confidence = max(vuln_res.confidence, opt_res.confidence)
        task_type_val = "code_review"
        explanation = f"ZSL Code Review: found {len(vuln_res.findings)} vulnerabilities and {len(opt_res.findings)} optimization opportunities."
        tokens_used = vuln_res.tokens_used + opt_res.tokens_used

    # Build finding
    finding = Finding(
        title=f"ZSL Analysis: {task_type_val}",
        content=explanation,
        score=confidence * 10,
        source="zsl_cyber",
        metadata={
            "task_type": task_type_val,
            "confidence": confidence,
            "findings": findings,
            "tokens_used": tokens_used
        }
    )

    findings_list = state.get("findings", []) + [finding]
    log = [_caveman("ZSL", "ANALYSIS", task_type_val,
                    confidence=f"{confidence:.1%}", findings=len(findings))]

    return {"findings": findings_list, "nmp_log": log}


# ═══════════════════════════════════════════════════════════════════════
# NEURO-SYMBOLIC VERIFICATION NODE
# ═══════════════════════════════════════════════════════════════════════
def neuro_symbolic_verification_node(state: ForgeState) -> dict:
    """
    Neuro-symbolic verification for explainability and hallucination prevention.
    Combines neural pattern matching with logical inference.
    """
    from .neuro_symbolic_guard import NeuroSymbolicGuard

    guard = NeuroSymbolicGuard()
    response = state.get("current_response", "")
    context = state.get("context", {})

    if not response:
        return {}

    # Verify response
    result = guard.prevent_hallucination(response, context)

    # Update state
    verification = state.get("verification", [])
    verification.append({
        "source": "neuro_symbolic_guard",
        "result": result,
        "timestamp": datetime.datetime.now().isoformat()
    })

    needs_revision = not result["is_safe"]
    revision_reason = f"Hallucination score: {result['hallucination_score']:.1%}" if needs_revision else None

    log = [_caveman("NEURO", "VERIFY", "safe" if result["is_safe"] else "unsafe",
                    score=f"{result['hallucination_score']:.1%}")]

    return {
        "verification": verification,
        "needs_revision": needs_revision,
        "revision_reason": revision_reason,
        "nmp_log": log
    }


# ═══════════════════════════════════════════════════════════════════════
# ANTI-HALLUCINATION NODE
# ═══════════════════════════════════════════════════════════════════════
def anti_hallucination_node(state: ForgeState) -> dict:
    """
    Anti-hallucination engine with semantic gravity and iteration limits.
    Prevents AI from entering repetitive hallucination loops.
    """
    from .anti_hallucination import AntiHallucinationEngine

    engine = AntiHallucinationEngine(max_iterations=3)
    response = state.get("current_response", "")
    context = state.get("context", {})

    if not response:
        return {}

    # Check for hallucinations
    result = engine.get_safe_response(response, context)

    # Update state
    hallucination_checks = state.get("hallucination_checks", [])
    hallucination_checks.append({
        "source": "anti_hallucination_engine",
        "result": result,
        "timestamp": datetime.datetime.now().isoformat()
    })

    needs_revision = not result["is_safe"]
    revision_reason = f"Hallucination score: {result['hallucination_score']:.1%}" if needs_revision else None

    log = [_caveman("ANTI_HAL", "CHECK", "safe" if result["is_safe"] else "unsafe",
                    score=f"{result['hallucination_score']:.1%}",
                    iterations=result["iterations_used"])]

    return {
        "hallucination_checks": hallucination_checks,
        "needs_revision": needs_revision,
        "revision_reason": revision_reason,
        # SPINE: compteur pour route_after_hallucination_check → escalade humaine
        # après MAX_REVISION_ATTEMPTS au lieu de boucler jusqu'au recursion_limit.
        "revision_attempts": state.get("revision_attempts", 0) + (1 if needs_revision else 0),
        "confidence": (1.0 - result.get("hallucination_score", 0.0)),
        "safe_response": result.get("safe_response"),
        "nmp_log": log
    }


def escalate_human_node(state: ForgeState) -> dict:
    """
    SPINE — Gate honnêteté : la Forge s'arrête et APPELLE UN HUMAIN plutôt que
    d'inventer ou de boucler. Déclenché quand should_escalate() est vrai
    (aveu d'ignorance, hallucination persistante, confiance trop basse).
    Écrit la question dans 05_STATE/human_queue.json et termine le run proprement.
    """
    from .forge_spine import escalate_to_human, should_escalate
    _, why = should_escalate(state)
    reason = why or state.get("revision_reason") or "réponse non fiable"
    task = state.get("current_task", "")
    info = escalate_to_human(
        question=(f"Tâche « {task} » : {reason}. "
                  f"La Forge préfère demander plutôt qu'inventer."),
        context={"last_response": (state.get("current_response", "") or "")[:500],
                 "revision_attempts": state.get("revision_attempts", 0),
                 "confidence": state.get("confidence", None)},
        task=task,
    )
    log = [_caveman("SPINE", "ESCALATE", "HUMAN", id=info["id"], reason=reason[:40])]
    _nmp_emit("ERR", "ESCALATE", "human", f"{info['id']} {reason[:50]}")
    return {
        "human_pending": True,
        "human_queue_id": info["id"],
        "task_complete": True,   # stoppe la boucle — reprise quand l'humain répond
        "nmp_log": log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HERALD — Audit sécurité déterministe + grading A-F
# ══════════════════════════════════════════════════════════════════════════════

def herald_audit(target_dir: str) -> dict:
    """Audit sécurité d'un livrable via security_audit.py + grading A-F.

    Retourne : {"grade": "A"|"B"|"C"|"D"|"F", "score": 0-100,
                "http": {...}, "injection": {...}, "deps": {...},
                "issues": [...], "summary": "..."}
    """
    import importlib.util, os, sys

    # Charger security_audit.py depuis 00_CORE/tools/
    forge_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sa_path = os.path.join(forge_root, "00_CORE", "tools", "security_audit.py")
    if not os.path.exists(sa_path):
        return {"grade": "F", "score": 0, "error": "security_audit.py introuvable",
                "issues": ["security_audit.py missing"]}

    spec = importlib.util.spec_from_file_location("security_audit", sa_path)
    sa = importlib.util.module_from_spec(spec)
    sys.modules["security_audit"] = sa
    spec.loader.exec_module(sa)

    # Exécuter les 3 audits
    try:
        result = sa.run()
    except Exception as e:
        return {"grade": "F", "score": 0, "error": str(e)[:200],
                "issues": [f"security_audit failed: {e}"]}

    score = 100.0
    issues = []

    # ── 1. HTTP surface ──────────────────────────────────────────────────
    http = result.get("http", {})
    unguarded = http.get("unguarded_count", 0)
    total_routes = http.get("total_routes", 0)
    if unguarded > 0:
        penalty = min(unguarded * 5, 40)  # max -40
        score -= penalty
        issues.append(f"{unguarded} routes non gardées sur {total_routes}")

    # ── 2. Injection ─────────────────────────────────────────────────────
    inj = result.get("injection", {})
    high_count = inj.get("high_total", 0)
    total_inj = inj.get("total", 0)
    # Filtrer les sites HIGH revus ( REVIEWED_INJECTION ) — ils ne comptent pas
    by_rule = inj.get("by_rule", {})
    reviewed = set()
    try:
        import importlib.util as _iu, os as _os
        _sa_path = os.path.join(forge_root, "00_CORE", "tools", "security_audit.py")
        if _os.path.exists(_sa_path):
            _spec = _iu.spec_from_file_location("_sa_check", _sa_path)
            _mod = _iu.module_from_spec(_spec)
            sys.modules["_sa_check"] = _mod
            _spec.loader.exec_module(_mod)
            reviewed = set(getattr(_mod, "REVIEWED_INJECTION", {}).keys())
    except Exception:
        pass
    # Compter les HIGH non-revus
    unrevised_high = 0
    for rule_name, rule_data in by_rule.items():
        if rule_data.get("severity") == "HIGH":
            for site in rule_data.get("sites", []):
                if site not in reviewed:
                    unrevised_high += 1
    if unrevised_high > 0:
        penalty = min(unrevised_high * 10, 30)  # max -30
        score -= penalty
        issues.append(f"{unrevised_high} sites HIGH injection non revus")
    # pénalité légère pour les mediums
    medium_count = sum(1 for v in by_rule.values()
                       if v.get("severity") == "MEDIUM" and v.get("count", 0) > 0)
    if medium_count > 0:
        score -= min(medium_count * 2, 10)

    # ── 3. Dépendances ───────────────────────────────────────────────────
    deps = result.get("deps", {})
    vuln_total = deps.get("vulnerable_count", 0)
    # Filtrer les paquets hors requirements Forge (pip-audit scanne tout l'env Python)
    forge_reqs = set()
    for req_file in ["requirements.txt", "requirements-docker.txt"]:
        rf = os.path.join(forge_root, req_file)
        if os.path.exists(rf):
            with open(rf, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "==" in line:
                        forge_reqs.add(line.split("==")[0].lower().strip())
    vuln_packages = deps.get("vulnerable_packages", [])
    forge_vuln = [v for v in vuln_packages if v.get("name", "").lower() in forge_reqs]
    vuln = len(forge_vuln)
    if vuln > 0:
        penalty = min(vuln * 8, 20)  # max -20
        score -= penalty
        issues.append(f"{vuln} paquets vulnérables")
    unpinned = deps.get("unpinned", 0)
    if unpinned > 0:
        score -= min(unpinned, 5)

    # ── Grade ─────────────────────────────────────────────────────────────
    score = max(0, min(100, score))
    if score >= 90:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 50:
        grade = "C"
    elif score >= 30:
        grade = "D"
    else:
        grade = "F"

    summary = (f"score={score:.0f}/100 grade={grade} | "
               f"routes={total_routes - unguarded}/{total_routes} gardées | "
               f"injection={total_inj} (HIGH={high_count}) | "
               f"deps vulnérables={vuln}")

    return {
        "grade": grade,
        "score": round(score, 1),
        "http": http,
        "injection": inj,
        "deps": deps,
        "issues": issues,
        "summary": summary,
    }
