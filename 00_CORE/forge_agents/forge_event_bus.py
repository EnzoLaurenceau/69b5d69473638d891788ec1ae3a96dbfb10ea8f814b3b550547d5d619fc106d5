"""
forge_event_bus.py — V6 Event Bus (Observabilité)
Chaque node Forge émet des événements → le bus les distribue.
Permet la visualisation temps réel, le debugging, et le méta-monitoring.

Événements typiques :
  NODE_EXECUTED, NODE_FAILED, KERNEL_EXTRACTED,
  MCP_CACHE_HIT, MCP_CACHE_MISS, VERDICT_RENDERED,
  HALLUCINATION_DETECTED, OPTIMIZATION_SUGGESTED
"""

from __future__ import annotations
import json
import time
import datetime
import threading
from typing import Any, Callable, Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT TYPE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ForgeEvent:
    """Un événement Forge."""
    type: str                       # NODE_EXECUTED, etc.
    source: str                     # node/agent source
    data: dict = field(default_factory=dict)
    timestamp: str = ""
    session_id: str = ""
    cycle: int = 0
    event_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now().isoformat()
        if not self.event_id:
            self.event_id = f"{self.type}-{int(time.time()*1000) % 1000000}"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_nmp(self) -> str:
        """Format NMP compact."""
        data_str = json.dumps(self.data, separators=(',', ':'))[:200]
        return f"EVENT|{self.source}|BUS|{self.type}|{data_str}"


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT BUS
# ═══════════════════════════════════════════════════════════════════════════════

# Type de callback : reçoit un ForgeEvent
EventCallback = Callable[[ForgeEvent], None]


class ForgeEventBus:
    """
    Bus d'événements Forge.
    Thread-safe. Supporte les subscribers par type ou globaux.
    Redis Pub/Sub pour IPC temps réel + fallback HTTP.
    """

    def __init__(self, max_history: int = 500):
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)
        self._global_subscribers: list[EventCallback] = []
        self._history: list[dict] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._event_count = 0
        self._redis = None
        self._redis_ok = False
        self._http_fallback_url = "http://127.0.0.1:7777/api/broadcast/event"
        self._init_redis()

    def _init_redis(self) -> None:
        """Try to connect to Redis for Pub/Sub."""
        try:
            import redis
            import os
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            self._redis = redis.from_url(redis_url, socket_timeout=2)
            self._redis.ping()
            self._redis_ok = True
        except Exception:
            self._redis_ok = False

    def _publish_redis(self, event_dict: dict) -> None:
        """Publish event to Redis channel forge_events (non-blocking)."""
        if not self._redis_ok or not self._redis:
            return
        try:
            self._redis.publish("forge_events", json.dumps(event_dict, default=str))
        except Exception:
            self._redis_ok = False  # disable on failure

    def _publish_http_fallback(self, event_dict: dict) -> None:
        """HTTP POST fallback if Redis is down (fire-and-forget thread)."""
        def _post():
            try:
                import urllib.request
                data = json.dumps(event_dict, default=str).encode("utf-8")
                req = urllib.request.Request(
                    self._http_fallback_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=3)
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        threading.Thread(target=_post, daemon=True).start()

    def subscribe(self, callback: EventCallback, event_type: str = None) -> None:
        """S'abonne à un type d'événement ou à tous."""
        with self._lock:
            if event_type:
                self._subscribers[event_type].append(callback)
            else:
                self._global_subscribers.append(callback)

    def unsubscribe(self, callback: EventCallback, event_type: str = None) -> None:
        """Se désabonne."""
        with self._lock:
            if event_type:
                if callback in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(callback)
            else:
                if callback in self._global_subscribers:
                    self._global_subscribers.remove(callback)

    def emit(self, event: ForgeEvent) -> None:
        """Émet un événement. Distribue à tous les subscribers + Redis/HTTP."""
        with self._lock:
            self._event_count += 1
            self._history.append(event.to_dict())
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        event_dict = event.to_dict()

        # Distribution locale (hors lock pour éviter deadlock)
        for cb in self._subscribers.get(event.type, []):
            try:
                cb(event)
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        for cb in self._global_subscribers:
            try:
                cb(event)
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # IPC: Redis Pub/Sub → dashboard temps réel
        self._publish_redis(event_dict)

        # Fallback HTTP si Redis down
        if not self._redis_ok:
            self._publish_http_fallback(event_dict)

    def emit_node_executed(self, node: str, cost: float, latency: float,
                           confidence: float, tokens: int = 0) -> None:
        """Helper: émet un événement NODE_EXECUTED."""
        self.emit(ForgeEvent(
            type="NODE_EXECUTED",
            source=node,
            data={"cost": cost, "latency": latency, "confidence": confidence, "tokens": tokens},
        ))

    def emit_node_failed(self, node: str, error: str) -> None:
        """Helper: émet un événement NODE_FAILED."""
        self.emit(ForgeEvent(
            type="NODE_FAILED",
            source=node,
            data={"error": error},
        ))

    def emit_kernel_extracted(self, kernel_id: str, domain: str, confidence: float) -> None:
        """Helper: émet un événement KERNEL_EXTRACTED."""
        self.emit(ForgeEvent(
            type="KERNEL_EXTRACTED",
            source="kernel_engine",
            data={"kernel_id": kernel_id, "domain": domain, "confidence": confidence},
        ))

    def emit_mcp_cache_hit(self, tool: str, tokens_saved: int) -> None:
        self.emit(ForgeEvent(
            type="MCP_CACHE_HIT",
            source="mcp_proxy",
            data={"tool": tool, "tokens_saved": tokens_saved},
        ))

    def emit_mcp_cache_miss(self, tool: str) -> None:
        self.emit(ForgeEvent(
            type="MCP_CACHE_MISS",
            source="mcp_proxy",
            data={"tool": tool},
        ))

    def emit_hallucination(self, node: str, severity: float, details: str) -> None:
        self.emit(ForgeEvent(
            type="HALLUCINATION_DETECTED",
            source=node,
            data={"severity": severity, "details": details},
        ))

    def emit_optimization(self, opt_type: str, action: str, reason: str) -> None:
        self.emit(ForgeEvent(
            type="OPTIMIZATION_SUGGESTED",
            source="meta_layer",
            data={"opt_type": opt_type, "action": action, "reason": reason},
        ))

    def get_history(self, event_type: str = None, limit: int = 50) -> list[dict]:
        """Récupère l'historique des événements."""
        with self._lock:
            if event_type:
                filtered = [e for e in self._history if e.get("type") == event_type]
                return filtered[-limit:]
            return self._history[-limit:]

    def stats(self) -> dict:
        with self._lock:
            type_counts: dict[str, int] = {}
            for e in self._history:
                t = e.get("type", "unknown")
                type_counts[t] = type_counts.get(t, 0) + 1
            return {
                "total_events": self._event_count,
                "history_size": len(self._history),
                "event_types": type_counts,
                "subscribers": {
                    "global": len(self._global_subscribers),
                    "by_type": {k: len(v) for k, v in self._subscribers.items()},
                },
            }

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._event_count = 0


# Singleton
_bus: Optional[ForgeEventBus] = None


def get_event_bus() -> ForgeEventBus:
    global _bus
    if _bus is None:
        _bus = ForgeEventBus()
    return _bus


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION LOGGER — trace complète d'une requête
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecutionTrace:
    """Trace complète d'une exécution (pour visualisation)."""
    trace_id: str = ""
    task: str = ""
    graph: str = "main"
    path: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    total_latency: float = 0.0
    total_tokens: int = 0
    final_confidence: float = 0.0
    events: list[dict] = field(default_factory=list)
    started_at: str = ""
    ended_at: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.datetime.now().isoformat()


class ExecutionTracer:
    """Enregistre les traces d'exécution."""

    def __init__(self):
        self._traces: list[dict] = []
        self._current: Optional[ExecutionTrace] = None

    def start_trace(self, task: str, trace_id: str = "") -> ExecutionTrace:
        """Démarre une nouvelle trace."""
        self._current = ExecutionTrace(
            trace_id=trace_id or f"trace-{int(time.time())}",
            task=task,
        )
        return self._current

    def add_step(self, node: str, cost: float = 0, latency: float = 0,
                 tokens: int = 0, confidence: float = 0) -> None:
        """Ajoute un step à la trace courante."""
        if self._current:
            self._current.path.append(node)
            self._current.total_cost += cost
            self._current.total_latency += latency
            self._current.total_tokens += tokens
            self._current.final_confidence = confidence

    def end_trace(self) -> Optional[dict]:
        """Termine et persiste la trace."""
        if self._current:
            self._current.ended_at = datetime.datetime.now().isoformat()
            trace_dict = asdict(self._current)
            self._traces.append(trace_dict)
            result = trace_dict
            self._current = None
            return result
        return None

    def get_traces(self, limit: int = 20) -> list[dict]:
        return self._traces[-limit:]


# Singleton
_tracer: Optional[ExecutionTracer] = None


def get_tracer() -> ExecutionTracer:
    global _tracer
    if _tracer is None:
        _tracer = ExecutionTracer()
    return _tracer


if __name__ == "__main__":
    bus = get_event_bus()
    tracer = get_tracer()

    # Simulate execution
    trace = tracer.start_trace("Build hotel bot")
    bus.emit_kernel_extracted("k-001", "bot", 0.85)
    tracer.add_step("kernel_extraction", 0.01, 0.5, 500, 0.85)

    bus.emit_node_executed("orchestrator", 0.12, 2.5, 0.9, 3000)
    tracer.add_step("orchestrator", 0.12, 2.5, 3000, 0.9)

    bus.emit_mcp_cache_hit("web_search", 2000)
    bus.emit_node_executed("dynamic_agent", 0.25, 5.0, 0.85, 8000)
    tracer.add_step("dynamic_agent", 0.25, 5.0, 8000, 0.85)

    final = tracer.end_trace()

    print(f"Events: {json.dumps(bus.stats(), indent=2)}")
    print(f"\nTrace: {json.dumps(final, indent=2)}")
