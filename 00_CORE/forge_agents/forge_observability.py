"""
forge_observability.py — LangSmith tracing central pour TOUS les LLM de la Forge
================================================================================
https://smith.langchain.com — suivi & observabilité irréprochable.

Point unique : `traced()` décore `forge_call()` (choke point de tout appel LLM,
tous providers/tiers). LangGraph s'auto-trace en plus dès que LANGSMITH_TRACING=true.

Dégradation gracieuse : si langsmith absent OU pas de clé → décorateur no-op,
zéro impact. Aucun secret dans le code — clé lue depuis .env (LANGSMITH_API_KEY).

Activation (.env) :
  LANGSMITH_TRACING=true
  LANGSMITH_API_KEY=lsv2_...
  LANGSMITH_PROJECT=super-agent-forge   # optionnel (défaut ci-dessous)

Kill switch : LANGSMITH_TRACING absent/false → tout est no-op.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("ForgeObservability")

FORGE_ROOT = Path(__file__).parent.parent.parent
DEFAULT_PROJECT = "super-agent-forge"

_INITIALIZED = False
_ENABLED = False


def _hydrate_env_from_dotenv() -> None:
    """Charge les clés LANGSMITH depuis .env dans os.environ (le SDK les lit là)."""
    for env_path in [FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"]:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.startswith(("LANGSMITH_", "LANGCHAIN_")):
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def init_observability() -> bool:
    """Idempotent. True si LangSmith est actif (tracing on + clé + SDK présent)."""
    global _INITIALIZED, _ENABLED
    if _INITIALIZED:
        return _ENABLED
    _INITIALIZED = True

    _hydrate_env_from_dotenv()

    tracing = os.environ.get("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes")
    if not tracing:
        logger.debug("[LangSmith] tracing désactivé (LANGSMITH_TRACING≠true)")
        return False
    if not os.environ.get("LANGSMITH_API_KEY"):
        logger.warning("[LangSmith] LANGSMITH_TRACING=true mais LANGSMITH_API_KEY absente → no-op")
        return False
    try:
        import langsmith  # noqa: F401
    except ImportError:
        logger.warning("[LangSmith] paquet langsmith non installé → no-op (pip install langsmith)")
        return False

    # LangChain/LangGraph lisent LANGCHAIN_* ; on miroir pour l'auto-trace du graph.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])
    project = os.environ.get("LANGSMITH_PROJECT", DEFAULT_PROJECT)
    os.environ.setdefault("LANGSMITH_PROJECT", project)
    os.environ.setdefault("LANGCHAIN_PROJECT", project)

    _ENABLED = True
    logger.info(f"[LangSmith] observabilité ACTIVE — projet '{project}'")
    return True


def is_enabled() -> bool:
    return init_observability()


def traced(name: str | None = None, run_type: str = "llm") -> Callable:
    """
    Décorateur : trace un appel dans LangSmith s'il est actif, sinon no-op.
    Applique @traceable du SDK à la volée (import paresseux → 0 coût si off).
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not init_observability():
                return fn(*args, **kwargs)
            try:
                from langsmith import traceable
                meta = {k: kwargs[k] for k in ("task_type", "node", "tier")
                        if k in kwargs and kwargs[k] is not None}
                traced_fn = traceable(
                    run_type=run_type,
                    name=name or fn.__name__,
                    metadata=meta or None,
                )(fn)
                return traced_fn(*args, **kwargs)
            except Exception as e:  # jamais casser un appel LLM à cause du tracing
                logger.debug(f"[LangSmith] trace skip ({fn.__name__}): {e}")
                return fn(*args, **kwargs)
        return wrapper
    return decorator


# ─── Audit Monitors ─────────────────────────────────────────────────────────

class ForgeAuditMonitor:
    """
    Moniteurs d'évaluation LangSmith pour le routeur et les nodes.
    Configure des évaluations automatiques pour tracker :
    - Taux de réussite des décisions du routeur
    - Ratio de rebonds (même node visité 2x+ consécutives)
    - Boucles infinies de correction
    - Latence moyenne des décisions
    """

    def __init__(self):
        self._client = None
        self._enabled = False

    def _get_client(self):
        if self._client is None:
            if not init_observability():
                return None
            try:
                from langsmith import Client
                self._client = Client()
                self._enabled = True
            except Exception:
                return None
        return self._client

    def log_router_decision(self, decision: dict) -> None:
        """Log une décision de routeur dans LangSmith comme run d'évaluation."""
        client = self._get_client()
        if not client:
            return

        try:
            client.create_run(
                name=f"router_decision_{decision.get('method', 'unknown')}",
                run_type="tool",
                inputs={
                    "node": decision.get("node", ""),
                    "cycle": decision.get("cycle", 0),
                    "state_summary": decision.get("state_summary", ""),
                },
                outputs={
                    "chosen_node": decision.get("node", ""),
                    "reason": decision.get("reason", ""),
                    "confidence": decision.get("confidence", 0.0),
                    "latency_ms": decision.get("latency_ms", 0),
                },
                metadata={
                    "component": "forge_router",
                    "method": decision.get("method", "unknown"),
                    "confidence": decision.get("confidence", 0.0),
                    "evaluation_type": "router_decision",
                },
                project_name=os.environ.get("LANGSMITH_PROJECT", DEFAULT_PROJECT),
            )
        except Exception as e:
            logger.debug(f"[Audit] router_decision log skip: {e}")

    def log_loop_detection(self, node: str, count: int, forced_target: str) -> None:
        """Log une détection de boucle infinie."""
        client = self._get_client()
        if not client:
            return

        try:
            client.create_run(
                name="loop_detection",
                run_type="tool",
                inputs={"stuck_node": node, "consecutive_count": count},
                outputs={"forced_target": forced_target, "intervention": True},
                metadata={
                    "component": "forge_router",
                    "evaluation_type": "loop_detection",
                    "severity": "high" if count >= 5 else "medium",
                },
                project_name=os.environ.get("LANGSMITH_PROJECT", DEFAULT_PROJECT),
            )
        except Exception as e:
            logger.debug(f"[Audit] loop_detection log skip: {e}")

    def log_bounce(self, from_node: str, to_node: str, cycle: int) -> None:
        """Log un rebond (retour rapide au même node)."""
        client = self._get_client()
        if not client:
            return

        try:
            client.create_run(
                name="bounce_detected",
                run_type="tool",
                inputs={"from": from_node, "to": to_node, "cycle": cycle},
                outputs={"is_bounce": from_node == to_node},
                metadata={
                    "component": "forge_router",
                    "evaluation_type": "bounce",
                },
                project_name=os.environ.get("LANGSMITH_PROJECT", DEFAULT_PROJECT),
            )
        except Exception as e:
            logger.debug(f"[Audit] bounce log skip: {e}")

    def log_node_execution(self, node: str, tokens: int, quality: float,
                           success: bool, cycle: int) -> None:
        """Log l'exécution d'un node pour suivi de performance."""
        client = self._get_client()
        if not client:
            return

        try:
            client.create_run(
                name=f"node_exec_{node}",
                run_type="chain",
                inputs={"node": node, "cycle": cycle},
                outputs={
                    "tokens": tokens,
                    "quality": quality,
                    "success": success,
                },
                metadata={
                    "component": "forge_node",
                    "evaluation_type": "node_execution",
                    "quality_score": quality,
                    "success": success,
                },
                project_name=os.environ.get("LANGSMITH_PROJECT", DEFAULT_PROJECT),
            )
        except Exception as e:
            logger.debug(f"[Audit] node_exec log skip: {e}")

    def get_evaluation_summary(self) -> dict:
        """Récupère le résumé des évaluations depuis LangSmith."""
        client = self._get_client()
        if not client:
            return {"enabled": False, "reason": "LangSmith not available"}

        try:
            project = os.environ.get("LANGSMITH_PROJECT", DEFAULT_PROJECT)
            runs = list(client.list_runs(
                project_name=project,
                execution_order=1,
                limit=100,
            ))

            total = len(runs)
            router_runs = [r for r in runs if r.metadata.get("component") == "forge_router"]
            loop_runs = [r for r in runs if r.metadata.get("evaluation_type") == "loop_detection"]
            node_runs = [r for r in runs if r.metadata.get("component") == "forge_node"]

            # Calculer les métriques
            success_nodes = [r for r in node_runs if r.metadata.get("success")]
            avg_quality = (
                sum(r.metadata.get("quality_score", 0) for r in node_runs) / len(node_runs)
                if node_runs else 0
            )

            return {
                "enabled": True,
                "total_runs": total,
                "router_decisions": len(router_runs),
                "loop_detections": len(loop_runs),
                "node_executions": len(node_runs),
                "node_success_rate": f"{len(success_nodes) / len(node_runs):.1%}" if node_runs else "N/A",
                "avg_quality": f"{avg_quality:.1f}",
                "project": project,
            }
        except Exception as e:
            return {"enabled": True, "error": str(e)}


# Singleton monitor
_audit_monitor = None

def get_audit_monitor() -> ForgeAuditMonitor:
    global _audit_monitor
    if _audit_monitor is None:
        _audit_monitor = ForgeAuditMonitor()
    return _audit_monitor


# ─── Self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # no-op quand tracing off : le décorateur doit être transparent
    os.environ.pop("LANGSMITH_TRACING", None)
    globals()["_INITIALIZED"] = False

    @traced(name="dummy")
    def add(a, b, task_type=None):
        return a + b

    assert add(2, 3, task_type="test") == 5
    assert init_observability() is False
    print("forge_observability self-check: OK (no-op quand LANGSMITH_TRACING off)")
    print(f"enabled={is_enabled()} project_default={DEFAULT_PROJECT}")
