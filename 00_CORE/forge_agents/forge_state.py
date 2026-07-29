"""
forge_state.py — ForgeState : état partagé entre tous les agents LangGraph
Chaque node lit ET écrit dans ce dict typé. LangGraph le checkpointe automatiquement.
"""

from __future__ import annotations
from typing import Annotated, Any, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
import operator

# ──────────────────────────────────────────────
# TYPE ALIASES
# ──────────────────────────────────────────────

AgentName = Literal[
    "orchestrator",
    "dynamic_agent",
    "mirofish",
    "auto_complexification",
    "memory_pruner",
    "curator",
    "post_mortem",
    "estimate_budget",
    "__end__",
]

Level = Literal["L1", "L2", "L3", "L4"]


# ──────────────────────────────────────────────
# FINDING — unité atomique de connaissance
# ──────────────────────────────────────────────

class Finding(TypedDict):
    id: str                    # ex: "F-HUNTER-001"
    agent: str
    cycle: int
    content: str
    score: float               # 0.0 → 10.0
    jury_consensus: float      # 0.0 → 1.0
    status: Literal["pending", "confirmed", "killed"]
    graphify_indexed: bool


# ──────────────────────────────────────────────
# NMP PACKET — protocole inter-agents (optiforge)
# Format strict : ACTION|SOURCE|TARGET|PAYLOAD
# Remplace CavemanMsg. Tout inter-agent = NMP pur.
# Seul agent_output reste human-readable (goal user).
# ──────────────────────────────────────────────

# NMPPacket = str pipe-formattée validée par nanomachine.parse_and_route
NMPPacket = str

# Alias rétrocompat : CavemanMsg = NMPPacket (str)
CavemanMsg = NMPPacket


# ──────────────────────────────────────────────
# MIROFISH JURY STATE
# ──────────────────────────────────────────────

class JuryPersonaScore(TypedDict):
    persona_id: str
    score: float               # 0.0 → 1.0
    feedback: str
    vote: Literal["APPROVE", "REJECT", "ABSTAIN"]


class JuryVerdict(TypedDict):
    consensus: float           # weighted average
    decision: Literal["APPROVED", "REJECTED", "REVISE"]
    suggestions: list[str]
    kill_flag: bool            # True si score < kill_below threshold


# ──────────────────────────────────────────────
# FORGE STATE — état global du graphe
# ──────────────────────────────────────────────

def _prune_caveman(left: list, right: list) -> list:
    return (left + right)[-50:]
        
def _prune_findings(left: list, right: list) -> list:
    return (left + right)[-20:]

class ForgeState(TypedDict):
    # ── ORCHESTRATION ──────────────────────────
    current_task: str           # slug de la tâche en cours
    current_task_desc: str      # description courte
    cycle: int                  # numéro de cycle global
    level: Level                # niveau actuel : L1 → L4
    next_agent: AgentName       # agent à invoquer après le routeur
    task_complete: bool         # True = cycle terminé, retour ORCH

    # ── AGENTS DYNAMIQUES ──────────────────────
    dynamic_agent_name: str     # Nom de l'agent généré à la volée (= le LEAD)
    dynamic_agent_prompt: str   # Prompt système généré à la volée
    team: dict                  # Équipe hybride recrutée par l'orchestrateur pour
                                # la micro-task : {lead, specialists:[{name,mission}]}
                                # Le lead peut appeler ses membres OU le roster KB
                                # à la demande (cf. forge_team.run_lead_with_team). {} = lead seul.
    role_tag: str               # Rôle canonique (9 valeurs) pour la Neural Map :
                                # orchestrator|architecture|backend|frontend|devops|
                                # security|token_optimization|validator|memory
    harness_grade: str          # Grade HarnessEngine (A+..F), badge dashboard
    artifact_files: list        # Fichiers produits par l'agent (input du harness)

    # ── MESSAGES (LangGraph native) ─────────────
    messages: Annotated[list[BaseMessage], add_messages]

    nmp_log: Annotated[list[NMPPacket], _prune_caveman]   # NMP packets inter-agents (max 50)

    # ── CONTEXT GRAPHIFY ────────────────────────
    graphify_context: str       # résultat de graphify_query() au INIT
    graphify_nodes_added: int   # compteur de nodes indexés cette session

    # ── OUTPUTS AGENTS ──────────────────────────
    findings: Annotated[list[Finding], _prune_findings]
    agent_output: str           # output brut du dernier agent
    agent_output_tokens: int    # tokens utilisés

    # ── MIROFISH JURY ───────────────────────────
    jury_seed: str              # seed envoyée au jury (≤500 tokens)
    jury_persona_scores: list[JuryPersonaScore]
    jury_verdict: Optional[JuryVerdict]

    # ── AUTO-COMPLEXIFICATION ───────────────────
    quality_history: list[float]        # scores par cycle
    quality_delta: float                # cycle N - cycle N-1
    token_ratio_history: list[float]    # ratio tokens économisés
    should_level_up: bool
    should_rollback: bool
    rollback_reason: str

    # ── SHOPIFY / ECOM CONTEXT ──────────────────
    shopify_products: list[dict]        # produits créés/modifiés
    shopify_collections: list[dict]

    # ── TOKEN BUDGET / TRACKING ─────────────────
    token_estimate: dict             # devis initial : {model_value: {input, output, cost}}
    token_actual: dict               # consommation reelle agregee par modele
    token_analysis: dict             # rapport post-mortem (recos, score)
    sprint_id: str                   # ex: "sprint_2026_07_B"
    task_id: str                     # ex: "task_452"
    token_variance_pct: float        # variance estimation vs réel (%)
    auto_refinement: dict            # recommandations auto si variance > 25%

    # ── PROGRESS CHECKPOINT (DONE/TODO, résumable) ───
    progress_done: list[str]    # étapes terminées (session courante)
    progress_todo: list[str]    # étapes restantes connues (plan)
    progress_current_step: str  # dernière étape exécutée

    # ── BLUEPRINT (DevilDev spec-first) ──────────────────
    blueprint: str                  # spécification architecturale générée
    blueprint_approved: bool        # validé par le jury/critic
    blueprint_feedback: str         # feedback du critic si rejeté
    blueprint_attempts: int         # nombre de tentatives (max 3)

    # ── V6 : SHARED BRAIN ──────────────────────────
    kernel_id: str                  # ID du kernel partagé (forge_kernel.py)
    kernel_domain: str              # domaine détecté (web_dev, security, etc.)
    kernel_confidence: float        # confiance extraction kernel
    shared_context: str             # contexte partagé injecté dans les agents

    # ── V6 : MCP CACHE ──────────────────────────────
    mcp_cache_hits: int             # nombre de hits MCP cache
    mcp_cache_misses: int           # nombre de misses MCP cache

    # ── V6 : META LAYER (émotions simulées) ──────────
    meta_confidence: float          # 0.0 → 1.0
    meta_uncertainty: float         # 0.0 → 1.0
    meta_risk: float                # 0.0 → 1.0
    meta_reward: float              # 0.0 → 1.0
    meta_curiosity: float           # 0.0 → 1.0
    meta_recommendation: str        # recommandation de l'alter stratégique

    # ── V6 : LAZY EXECUTION ──────────────────────────
    lazy_strategy: str              # "reuse", "adapt", "full_execution"
    lazy_reason: str                # pourquoi ce strategy

    # ── V6 : EXPERIENCE DB ───────────────────────────
    experience_recorded: bool       # expérience enregistrée dans la DB

    # ── V6 : SELF-HEALING ────────────────────────────
    heal_actions: list[str]         # actions de guérison proposées
    heal_executed: list[str]        # actions exécutées

    # ── V6 : EVENT BUS ───────────────────────────────
    events_emitted: int             # compteur d'événements émis cette session

    # ── V7 : SEMANTIC EDIT ENGINE ─────────────────────
    see_active: bool                    # SEE activé pour cette tâche
    see_patches_applied: int            # nombre de patches appliqués
    see_patches_rolled_back: int        # nombre de rollbacks
    see_avg_patch_score: float          # score moyen des patches
    see_token_savings_pct: float        # % tokens économisés via context window
    see_last_strategy: str              # dernière stratégie utilisée
    see_metrics: dict                   # métriques agrégées du cycle

    # ── V8 : REWARD ENGINE ────────────────────────────
    reward_total: float                 # reward cumulé du cycle (-1.0 → +1.0)
    reward_signals: list[dict]          # signaux bruts collectés ce cycle
    reward_agent_elo: dict              # ELO par agent {name: rating}
    reward_kl_divergence: float         # divergence comportementale vs baseline
    reward_gaming_detected: bool        # True si proxy↑ mais true↓

    # ── SPINE : HONNÊTETÉ + ESCALADE HUMAINE (HITL) ──
    revision_attempts: int              # retries hallucination (route_after_hallucination_check)
    confidence: float                   # confiance de la dernière réponse (0.0→1.0)
    needs_revision: bool                # réponse jugée non fiable → retry ou escalade
    revision_reason: str                # pourquoi la révision est demandée
    human_pending: bool                 # True = run stoppé, en attente d'un humain
    human_queue_id: str                 # id de la demande dans 05_STATE/human_queue.json

    # ── SPINE : DELIVER GATE ─────────────────────
    deliver_blocked: bool               # livrable bloqué (legal/herald KO)
    deliver_reason: str                 # raison du blocage

    # ── META ─────────────────────────────────────
    error: Optional[str]
    error_agent: Optional[str]
    session_id: str


# ──────────────────────────────────────────────
# INITIAL STATE FACTORY
# ──────────────────────────────────────────────

def initial_state(task: str, task_desc: str = "", session_id: str = "default") -> ForgeState:
    """Crée un état initial propre pour un nouveau cycle."""
    import uuid
    return ForgeState(
        current_task=task,
        current_task_desc=task_desc,
        cycle=0,
        level="L1",
        next_agent="orchestrator",
        task_complete=False,
        dynamic_agent_name="",
        dynamic_agent_prompt="",
        team={},
        role_tag="",
        harness_grade="",
        artifact_files=[],
        messages=[],
        nmp_log=[],
        graphify_context="",
        graphify_nodes_added=0,
        findings=[],
        agent_output="",
        agent_output_tokens=0,
        jury_seed="",
        jury_persona_scores=[],
        jury_verdict=None,
        quality_history=[],
        quality_delta=0.0,
        token_ratio_history=[],
        should_level_up=False,
        should_rollback=False,
        rollback_reason="",
        shopify_products=[],
        shopify_collections=[],
        token_estimate={},
        token_actual={},
        token_analysis={},
        sprint_id="",
        task_id="",
        token_variance_pct=0.0,
        auto_refinement={},
        progress_done=[],
        progress_todo=[],
        progress_current_step="",
        # Blueprint (DevilDev)
        blueprint="",
        blueprint_approved=False,
        blueprint_feedback="",
        blueprint_attempts=0,
        # V6: Shared Brain
        kernel_id="",
        kernel_domain="",
        kernel_confidence=0.0,
        shared_context="",
        # V6: MCP Cache
        mcp_cache_hits=0,
        mcp_cache_misses=0,
        # V6: Meta Layer
        meta_confidence=0.5,
        meta_uncertainty=0.5,
        meta_risk=0.0,
        meta_reward=0.0,
        meta_curiosity=0.3,
        meta_recommendation="",
        # V6: Lazy Execution
        lazy_strategy="full_execution",
        lazy_reason="",
        # V6: Experience DB
        experience_recorded=False,
        # V6: Self-Healing
        heal_actions=[],
        heal_executed=[],
        # V6: Event Bus
        events_emitted=0,
        # V7: Semantic Edit Engine
        see_active=False,
        see_patches_applied=0,
        see_patches_rolled_back=0,
        see_avg_patch_score=0.0,
        see_token_savings_pct=0.0,
        see_last_strategy="",
        see_metrics={},
        # V8: Reward Engine
        reward_total=0.0,
        reward_signals=[],
        reward_agent_elo={},
        reward_kl_divergence=0.0,
        reward_gaming_detected=False,
        # SPINE: honnêteté + HITL
        revision_attempts=0,
        confidence=1.0,
        needs_revision=False,
        revision_reason="",
        human_pending=False,
        human_queue_id="",
        # SPINE: deliver gate
        deliver_blocked=False,
        deliver_reason="",

        error=None,
        error_agent=None,
        session_id=session_id or str(uuid.uuid4())[:8],
    )
