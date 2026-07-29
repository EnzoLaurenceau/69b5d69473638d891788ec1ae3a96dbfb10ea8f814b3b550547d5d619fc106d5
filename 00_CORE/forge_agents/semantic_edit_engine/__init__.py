from __future__ import annotations

from .edit_metrics import EditMetrics, get_metrics_aggregator
from .patch_scorer import PatchScorer, PatchScore, ScoringWeights
from .auto_rollback import AutoRollback, get_rollback_manager, transactional_edit
from .symbol_resolver import SymbolResolver, SymbolTarget, SymbolKind, Language, get_symbol_resolver, resolve_symbol
from .patch_memory import PatchMemory, PatchRecord, get_patch_memory
from .context_window import IntelligentContextWindow, SmartContext, get_context_window, build_context
from .patch_optimizer import SemanticPatchOptimizer, PatchCandidate, PatchStrategy, get_patch_optimizer, optimize_patch
from .edit_primitives import EditOp, EditPlan, EditError, Replace, InsertAfter, DeleteRange, ReplaceSymbolBody, derive_ops

__all__ = [
    "EditMetrics",
    "get_metrics_aggregator",
    "PatchScorer",
    "PatchScore",
    "ScoringWeights",
    "AutoRollback",
    "get_rollback_manager",
    "transactional_edit",
    "SymbolResolver",
    "SymbolTarget",
    "SymbolKind",
    "Language",
    "get_symbol_resolver",
    "resolve_symbol",
    "PatchMemory",
    "PatchRecord",
    "get_patch_memory",
    "IntelligentContextWindow",
    "SmartContext",
    "get_context_window",
    "build_context",
    "SemanticPatchOptimizer",
    "PatchCandidate",
    "PatchStrategy",
    "get_patch_optimizer",
    "optimize_patch",
    "EditOp",
    "EditPlan",
    "EditError",
    "Replace",
    "InsertAfter",
    "DeleteRange",
    "ReplaceSymbolBody",
    "derive_ops",
]
