"""
tool_batcher.py — Batching des tool calls pour les agents dynamiques de la Forge.

PROBLÈME : un agent dynamique (ou Claude piloté via Agent SDK) peut accumuler
des dizaines/centaines d'appels d'outils individuels (Read, Grep, graphify_index,
web_fetch, ...) sur une session longue. Chaque appel = 1 round-trip
→ coût + latence + bruit dans les logs/checkpoints (objectif CLAUDE.md :
éviter de finir une tâche avec ~250 tool calls non groupés).

SOLUTION : ToolCallBatcher accumule les intentions d'appel dans une file et
les regroupe en paquets (batch_size) exécutés via un executor unique. Les
appels du même outil sont groupés ensemble (group_by_tool=True) pour permettre
à un executor natif en lot (ex: browser_batch, computer_batch, ou un wrapper
maison) de traiter N appels en 1 seule invocation.

Intégration actuelle :
  - agent_nodes._base_store() : regroupe les indexations Graphify des findings
    d'un même cycle en un seul batch (au lieu d'un subprocess par finding).

Intégration future (Agent SDK / Ruflo) :
  - tout agent dynamique qui produit une liste d'actions outils
    (`tool_calls` dans sa sortie JSON) doit les empiler via batcher.queue()
    au lieu de les exécuter une à une, puis appeler flush_all() une fois.
  - batcher.stats() est injecté dans le rapport post-mortem (token_tracker)
    pour mesurer les round-trips économisés.
"""

from __future__ import annotations
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("tool_batcher")

DEFAULT_BATCH_SIZE = 10


@dataclass
class QueuedCall:
    tool: str
    args: dict
    meta: dict = field(default_factory=dict)


class ToolCallBatcher:
    """
    File d'attente de tool calls + exécution groupée.

    executor(tool_name, args_list) -> list[Any]
        Reçoit le nom de l'outil et la liste des args accumulés pour cet
        outil (taille <= batch_size), retourne une liste de résultats
        de même longueur. Si aucun executor n'est fourni, un executor
        de secours "stub" est utilisé (ne casse jamais le flux).
    """

    def __init__(self, executor: Callable[[str, list[dict]], list[Any]] | None = None,
                 batch_size: int = DEFAULT_BATCH_SIZE, group_by_tool: bool = True):
        self.executor = executor or self._default_executor
        self.batch_size = max(1, batch_size)
        self.group_by_tool = group_by_tool
        self._queue: deque[QueuedCall] = deque()
        self._total_queued = 0
        self._total_batches = 0
        self._total_executed = 0

    # ── API publique ──────────────────────────────────────────────────────

    def queue(self, tool: str, args: dict, **meta) -> None:
        """Empile un appel d'outil. Auto-flush si la file atteint batch_size."""
        self._queue.append(QueuedCall(tool=tool, args=args, meta=meta))
        self._total_queued += 1
        if len(self._queue) >= self.batch_size:
            self.flush()

    def pending_count(self) -> int:
        return len(self._queue)

    def flush(self) -> list[Any]:
        """Exécute un batch (regroupé par outil) et vide la file courante."""
        if not self._queue:
            return []
        results: list[Any] = []
        grouped: dict[str, list[QueuedCall]] = defaultdict(list)
        for call in self._queue:
            key = call.tool if self.group_by_tool else "_mixed_"
            grouped[key].append(call)
        for tool, calls in grouped.items():
            results.extend(self._run_batch(tool if self.group_by_tool else calls[0].tool, calls))
        self._queue.clear()
        return results

    def flush_all(self) -> list[Any]:
        """Vide complètement la file, en plusieurs batches si nécessaire."""
        all_results: list[Any] = []
        while self._queue:
            all_results.extend(self.flush())
        return all_results

    def stats(self) -> dict:
        raw = self._total_executed
        batches = self._total_batches
        saved = max(0, raw - batches)
        ratio = (saved / raw * 100) if raw else 0.0
        return {
            "total_calls_queued": self._total_queued,
            "total_calls_executed": raw,
            "total_batches": batches,
            "round_trips_saved": saved,
            "saved_pct": round(ratio, 1),
            "pending": len(self._queue),
        }

    def reset_stats(self) -> None:
        self._total_queued = 0
        self._total_batches = 0
        self._total_executed = 0

    # ── internes ──────────────────────────────────────────────────────────

    def _run_batch(self, tool: str, calls: list[QueuedCall]) -> list[Any]:
        out: list[Any] = []
        for i in range(0, len(calls), self.batch_size):
            chunk = calls[i:i + self.batch_size]
            args_list = [c.args for c in chunk]
            try:
                batch_result = self.executor(tool, args_list)
                if not isinstance(batch_result, list) or len(batch_result) != len(chunk):
                    raise ValueError("executor doit retourner une liste de meme taille que args_list")
            except Exception as e:
                logger.warning(f"[BATCH] {tool} batch de {len(chunk)} a échoué: {e}")
                batch_result = [None] * len(chunk)
            self._total_batches += 1
            self._total_executed += len(chunk)
            out.extend(batch_result)
        return out

    @staticmethod
    def _default_executor(tool: str, args_list: list[dict]) -> list[Any]:
        logger.debug(f"[BATCH] executor par défaut (stub): {tool} x{len(args_list)}")
        return [{"tool": tool, "args": a, "status": "stub"} for a in args_list]


# ── Singleton global (réutilisable entre nodes du graph) ────────────────────

_GLOBAL_BATCHER: ToolCallBatcher | None = None


def get_batcher(**kwargs) -> ToolCallBatcher:
    """Retourne le batcher global, en le créant au besoin."""
    global _GLOBAL_BATCHER
    if _GLOBAL_BATCHER is None:
        _GLOBAL_BATCHER = ToolCallBatcher(**kwargs)
    return _GLOBAL_BATCHER


def reset_batcher() -> None:
    global _GLOBAL_BATCHER
    _GLOBAL_BATCHER = None
