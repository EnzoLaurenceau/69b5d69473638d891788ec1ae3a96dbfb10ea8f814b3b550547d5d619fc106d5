from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class EditMetrics:
    minimal_edit_score: float = 0.0
    ast_nodes_changed: int = 0
    characters_changed: int = 0
    tokens_changed: int = 0
    lines_changed: int = 0
    semantic_distance: float = 0.0
    tree_edit_distance: int = 0
    git_diff_size: int = 0
    patch_complexity: float = 0.0
    context_size_tokens: int = 0
    token_savings: float = 0.0
    compilation_time_ms: float = 0.0
    test_time_ms: float = 0.0
    rollback_rate: float = 0.0
    patch_success_rate: float = 0.0
    average_patch_size: float = 0.0
    hallucination_rate: float = 0.0
    patch_confidence: float = 0.0

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def to_nmp(self) -> str:
        pairs = ",".join(f"{k}={v}" for k, v in self.to_dict().items())
        return f"METRICS|SEE|DASHBOARD|{pairs}"

    def summary(self) -> str:
        return f"SEE metrics: score={self.minimal_edit_score:.2f}, AST nodes={self.ast_nodes_changed}, lines={self.lines_changed}, savings={self.token_savings:.1f}%"

    @staticmethod
    def zero() -> EditMetrics:
        return EditMetrics()

class EditMetricsAggregator:
    def __init__(self):
        self.history: list[EditMetrics] = []

    def record(self, metrics: EditMetrics):
        self.history.append(metrics)

    def aggregate(self) -> EditMetrics:
        if not self.history:
            return EditMetrics.zero()
        n = len(self.history)
        res = EditMetrics()
        for m in self.history:
            for k in res.__dict__:
                setattr(res, k, getattr(res, k) + getattr(m, k))
        for k in res.__dict__:
            setattr(res, k, getattr(res, k) / n)
        return res

_aggregator = EditMetricsAggregator()

def get_metrics_aggregator() -> EditMetricsAggregator:
    return _aggregator


def from_candidate(candidate) -> EditMetrics:
    """Construit les métriques d'un PatchCandidate (patch_optimizer)."""
    baseline = max(len(candidate.original) // 4, 1)   # coût d'une réécriture complète
    emitted = max(candidate.emit_cost // 4, 0)
    return EditMetrics(
        minimal_edit_score=candidate.score,
        characters_changed=candidate.char_changes,
        tokens_changed=emitted,
        lines_changed=candidate.line_changes,
        git_diff_size=len(candidate.diff),
        patch_complexity=float(len(candidate.plan.ops)) if candidate.plan else 0.0,
        context_size_tokens=baseline,
        token_savings=round(100.0 * (1.0 - emitted / baseline), 2),
        patch_confidence=candidate.score,
    )


def record_edit(candidate, workflow: str = "semantic_edit_engine",
                agent: str = "patch_optimizer", latency_ms: int = 0) -> EditMetrics:
    """Agrège + relaie vers `forge_metrics.jsonl` (sink unique d'observabilité).

    Dégradation gracieuse : si forge_metrics est indisponible, l'agrégat local
    reste alimenté et rien ne casse.
    """
    metrics = from_candidate(candidate)
    _aggregator.record(metrics)
    try:
        from ..forge_metrics import record as _record
        _record(
            kind="tool",
            workflow=workflow,
            agent=agent,
            node=candidate.strategy.value,
            tokens_out=metrics.tokens_changed,
            latency_ms=latency_ms,
            meta={
                "file": candidate.file_path,
                "target": candidate.target_name,
                "strategy": candidate.strategy.value,
                "emit_cost": candidate.emit_cost,
                "mcpt_cost": round(candidate.mcpt_cost, 2),
                "chars_changed": metrics.characters_changed,
                "lines_changed": metrics.lines_changed,
                "token_savings_pct": metrics.token_savings,
                "patch_score": round(candidate.score, 4),
            },
        )
    except Exception as exc:  # sink optionnel — jamais bloquant
        logger.debug("forge_metrics indisponible: %s", exc)
    return metrics
