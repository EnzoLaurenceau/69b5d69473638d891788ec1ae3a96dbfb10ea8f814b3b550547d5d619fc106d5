"""
Super Agent Forge — LangGraph Package
======================================
Entry points:
  from forge.langgraph.forge_graph import ForgeRunner, build_forge_graph
  from forge.langgraph.forge_state import ForgeState, initial_state
  from forge.langgraph.mirofish_subgraph import run_jury
  from forge.langgraph.graphify_checkpointer import graphify_query, graphify_index
"""

# ── Encodage UTF-8 universel ──────────────────────────────────────────────────
# Windows console = cp1252 par défaut → crash sur les box-drawing/emoji (╔ 🧠 →)
# imprimés par token_tracker, agent_nodes, cervelet… Forcé ici, à l'import du
# package : couvre TOUS les points d'entrée (run_forge, modules, toute IA).
import sys as _sys
for _stream in ("stdout", "stderr"):
    try:
        getattr(_sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

from .forge_state import (
    ForgeState,
    Finding,
    CavemanMsg,
    JuryVerdict,
    initial_state,
)
from .forge_graph import ForgeRunner, build_forge_graph
from .openviking import get_viking, VikingContext
from .cervelet import (
    get_cervelet,
    cervelet_intercept,
    route_request,
    ESCALATE,
    CerveletArtificiel,
    SystèmeHoméostatique,
    LayerMémoirePostgresRedis,
)
from .forge_db import get_db, ForgeDB, light_embedding
from .graphify_checkpointer import (
    graphify_query,
    graphify_index,
    sync_findings_to_graphify,
    checkpoint_state_to_json,
    load_last_checkpoint,
)

# ── V6 Imports ────────────────────────────────────────────────────────────────
from .forge_kernel import Kernel, extract_kernel_fast, get_or_extract_kernel
from .forge_shared_brain import ForgeBrain, get_brain, get_kernel_store, get_mcp_cache, get_shared_reasoning
from .forge_experience_db import ExperienceDB, Experience, get_experience_db
from .forge_meta import ForgeMetaLayer, EmotionalState, get_meta
from .forge_lazy import LazyExecutionEngine, get_lazy_engine
from .forge_event_bus import ForgeEventBus, ForgeEvent, get_event_bus, get_tracer
from .forge_self_heal import SelfHealingEngine, get_healer, CheckpointManager
from .forge_system_registry import SystemRegistry, get_registry, refresh_registry
from .forge_execution_logger import ExecutionLogger, ExecutionLog, get_logger
from .forge_mcp_pruner import MCPPruningEngine, get_pruner, refresh_pruner
from .forge_no_mistakes import NoMistakesGate, ForgeQualityGate, get_quality_gate
# ── V7 Imports ────────────────────────────────────────────────────────────────
from .semantic_edit_engine import (
    SymbolResolver, resolve_symbol,
    SemanticPatchOptimizer, optimize_patch,
    PatchScorer, PatchCandidate, PatchScore,
    AutoRollback, transactional_edit,
    EditMetrics, get_metrics_aggregator as get_edit_metrics,
    PatchMemory, get_patch_memory,
    IntelligentContextWindow, build_context
)
import logging

logger = logging.getLogger(__name__)


__all__ = [
    "ForgeState",
    "Finding",
    "CavemanMsg",
    "JuryVerdict",
    "initial_state",
    "ForgeRunner",
    "build_forge_graph",
    "graphify_query",
    "graphify_index",
    "sync_findings_to_graphify",
    "checkpoint_state_to_json",
    "load_last_checkpoint",
    "get_viking",
    "VikingContext",
    "get_cervelet",
    "cervelet_intercept",
    "route_request",
    "ESCALATE",
    "CerveletArtificiel",
    "SystèmeHoméostatique",
    "LayerMémoirePostgresRedis",
    "get_db",
    "ForgeDB",
    "light_embedding",
    # V6
    "Kernel",
    "extract_kernel_fast",
    "get_or_extract_kernel",
    "ForgeBrain",
    "get_brain",
    "get_kernel_store",
    "get_mcp_cache",
    "get_shared_reasoning",
    "ExperienceDB",
    "Experience",
    "get_experience_db",
    "ForgeMetaLayer",
    "EmotionalState",
    "get_meta",
    "LazyExecutionEngine",
    "get_lazy_engine",
    "ForgeEventBus",
    "ForgeEvent",
    "get_event_bus",
    "get_tracer",
    "SelfHealingEngine",
    "get_healer",
    "CheckpointManager",
    "SystemRegistry",
    "get_registry",
    "refresh_registry",
    "ExecutionLogger",
    "ExecutionLog",
    "get_logger",
    "MCPPruningEngine",
    "get_pruner",
    "refresh_pruner",
    "NoMistakesGate",
    "ForgeQualityGate",
    "get_quality_gate",
]
