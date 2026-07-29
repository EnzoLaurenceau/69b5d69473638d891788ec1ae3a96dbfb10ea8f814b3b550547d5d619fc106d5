"""
forge_execution_logger.py — V6 Execution Logger
Persiste les traces d'exécution en JSON pour analyse, debugging, et visualisation.

Chaque run produit un fichier dans 05_STATE/logs/executions/ :
  trace-{timestamp}-{session_id}.json

Contenu :
  task, path (nodes traversés), cost, latency, tokens, confidence,
  events, kernel_id, domain
"""

from __future__ import annotations
import json
import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path


FORGE_ROOT = Path(__file__).parent.parent.parent


def LOGS_DIR() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("logs/executions")


@dataclass
class ExecutionLog:
    """Trace complète d'une exécution."""
    trace_id: str = ""
    session_id: str = ""
    task: str = ""
    kernel_id: str = ""
    domain: str = ""
    graph: str = "main_v6"
    path: list[str] = field(default_factory=list)
    node_metrics: list[dict] = field(default_factory=list)
    total_cost: float = 0.0
    total_latency: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    effective_tokens: int = 0  # ET = input + output*4 + cache*0.1
    final_confidence: float = 0.0
    outcome: str = "unknown"  # success | failure | partial
    events: list[dict] = field(default_factory=list)
    started_at: str = ""
    ended_at: str = ""
    duration_sec: float = 0.0

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.datetime.now().isoformat()
        if not self.trace_id:
            self.trace_id = f"trace-{int(datetime.datetime.now().timestamp())}"

    def add_step(self, node: str, cost: float = 0, latency: float = 0,
                 tokens: int = 0, confidence: float = 0) -> None:
        """Ajoute un step à la trace."""
        self.path.append(node)
        self.node_metrics.append({
            "node": node,
            "cost": cost,
            "latency": latency,
            "tokens": tokens,
            "confidence": confidence,
            "timestamp": datetime.datetime.now().isoformat(),
        })
        self.total_cost += cost
        self.total_latency += latency
        self.total_tokens += tokens
        self.final_confidence = confidence

    def compute_et(self, model_multiplier: float = 1.0) -> int:
        """
        Calcule les Effective Tokens selon la formule GitHub.
        ET = input + (output × 4) + (cache_read × 0.1)
        Multiplié par le model multiplier.
        """
        raw = self.input_tokens + (self.output_tokens * 4) + (self.cache_read * 0.1)
        self.effective_tokens = int(raw * model_multiplier)
        return self.effective_tokens

    def finish(self, outcome: str = "success") -> None:
        """Termine la trace."""
        self.outcome = outcome
        self.ended_at = datetime.datetime.now().isoformat()
        try:
            start = datetime.datetime.fromisoformat(self.started_at)
            self.duration_sec = (datetime.datetime.now() - start).total_seconds()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionLogger:
    """Logger d'exécutions. Persiste chaque trace en JSON."""

    def __init__(self, logs_dir: Optional[Path] = None):
        self._dir = logs_dir or LOGS_DIR()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._current: Optional[ExecutionLog] = None

    def start(self, task: str, session_id: str = "",
              kernel_id: str = "", domain: str = "") -> ExecutionLog:
        """Démarre une nouvelle trace."""
        log = ExecutionLog(
            task=task,
            session_id=session_id,
            kernel_id=kernel_id,
            domain=domain,
        )
        self._current = log
        return log

    def get_current(self) -> Optional[ExecutionLog]:
        return self._current

    def finish(self, outcome: str = "success") -> Optional[dict]:
        """Termine et persiste la trace courante."""
        if not self._current:
            return None
        self._current.finish(outcome)
        trace_dict = self._current.to_dict()

        # Persister
        filename = f"{self._current.trace_id}.json"
        filepath = self._dir / filename
        filepath.write_text(
            json.dumps(trace_dict, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        result = trace_dict
        self._current = None
        return result

    def list_traces(self, limit: int = 20) -> list[dict]:
        """Liste les traces persistées."""
        traces = []
        for f in sorted(self._dir.glob("trace-*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                traces.append({
                    "trace_id": data.get("trace_id", f.stem),
                    "task": data.get("task", "")[:80],
                    "path": data.get("path", []),
                    "total_cost": data.get("total_cost", 0),
                    "total_tokens": data.get("total_tokens", 0),
                    "effective_tokens": data.get("effective_tokens", 0),
                    "outcome": data.get("outcome", "?"),
                    "duration_sec": data.get("duration_sec", 0),
                    "started_at": data.get("started_at", ""),
                })
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return traces

    def get_trace(self, trace_id: str) -> Optional[dict]:
        """Récupère une trace par ID."""
        filepath = self._dir / f"{trace_id}.json"
        if filepath.exists():
            return json.loads(filepath.read_text(encoding="utf-8"))
        return None

    def get_stats(self) -> dict:
        """Stats globales sur les exécutions."""
        traces = self.list_traces(limit=1000)
        if not traces:
            return {"total": 0}
        total_tokens = sum(t.get("total_tokens", 0) for t in traces)
        total_et = sum(t.get("effective_tokens", 0) for t in traces)
        total_cost = sum(t.get("total_cost", 0) for t in traces)
        successes = sum(1 for t in traces if t.get("outcome") == "success")
        return {
            "total": len(traces),
            "successes": successes,
            "success_rate": successes / len(traces),
            "total_tokens": total_tokens,
            "total_et": total_et,
            "total_cost": total_cost,
            "avg_duration": sum(t.get("duration_sec", 0) for t in traces) / len(traces),
        }


# Singleton
_logger: Optional[ExecutionLogger] = None


def get_logger() -> ExecutionLogger:
    global _logger
    if _logger is None:
        _logger = ExecutionLogger()
    return _logger


if __name__ == "__main__":
    logger = get_logger()
    log = logger.start("Build hotel bot", session_id="test-001", domain="bot")
    log.add_step("v6_init", 0.01, 0.5, 500, 0.85)
    log.add_step("orchestrator", 0.12, 2.5, 3000, 0.9)
    log.add_step("dynamic_agent", 0.25, 5.0, 8000, 0.85)
    log.input_tokens = 5000
    log.output_tokens = 3000
    log.cache_read = 2000
    et = log.compute_et(model_multiplier=0.3)  # MiMo
    print(f"ET (MiMo): {et}")
    result = logger.finish("success")
    print(f"Saved: {result['trace_id']}")
    print(f"Stats: {json.dumps(logger.get_stats(), indent=2)}")
