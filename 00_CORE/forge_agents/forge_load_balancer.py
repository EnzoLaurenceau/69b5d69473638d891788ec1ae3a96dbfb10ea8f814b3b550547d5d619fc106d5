"""
forge_load_balancer.py — Load Balancer for Forge Nodes
=======================================================
Plan B §2.5 : Répartition de charge pour désengorger les nœuds.

Si la latence d'un nœud augmente de 50%, instancie un clone temporaire.
Redistribue vers des nœuds sous-utilisés.

Usage:
    from forge_agents.forge_load_balancer import get_load_balancer
    lb = get_load_balancer()
    node = lb.select_node("dynamic_agent", available_nodes)
    lb.record_latency("dynamic_agent", latency_ms=2500)
    report = lb.get_report()
"""

from __future__ import annotations
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("LoadBalancer")


@dataclass
class NodeMetrics:
    """Métriques de performance d'un nœud."""
    name: str
    latencies: list[float] = field(default_factory=list)
    calls: int = 0
    failures: int = 0
    last_used: float = 0.0
    clone_count: int = 0

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies[-20:]) / len(self.latencies[-20:]) if self.latencies else 0.0

    @property
    def baseline_latency(self) -> float:
        """Latence de base (premiers appels)."""
        if len(self.latencies) < 3:
            return self.avg_latency
        return sum(self.latencies[:5]) / min(5, len(self.latencies))

    @property
    def is_congested(self) -> bool:
        """Congestionné si latence +50% vs baseline."""
        baseline = self.baseline_latency
        if baseline <= 0:
            return False
        return self.avg_latency > baseline * 1.5

    @property
    def failure_rate(self) -> float:
        return self.failures / max(1, self.calls)


class ForgeLoadBalancer:
    """Répartition de charge entre les nœuds de la Forge."""

    def __init__(self):
        self._metrics: dict[str, NodeMetrics] = {}
        self._clones: dict[str, list[str]] = defaultdict(list)  # node → [clone_names]

    def _get_or_create(self, node_name: str) -> NodeMetrics:
        if node_name not in self._metrics:
            self._metrics[node_name] = NodeMetrics(name=node_name)
        return self._metrics[node_name]

    def record_latency(self, node_name: str, latency_ms: float):
        """Enregistre la latence d'un nœud."""
        m = self._get_or_create(node_name)
        m.latencies.append(latency_ms)
        m.calls += 1
        m.last_used = time.time()

        # Vérifier congestion
        if m.is_congested and m.clone_count < 2:
            clone_name = f"{node_name}_clone_{m.clone_count + 1}"
            self._clones[node_name].append(clone_name)
            m.clone_count += 1
            logger.warning(f"[LoadBalancer] CONGESTION: {node_name} → spawning {clone_name}")

    def record_failure(self, node_name: str):
        """Enregistre un échec."""
        m = self._get_or_create(node_name)
        m.failures += 1
        m.calls += 1

    def select_node(self, preferred: str, available: list[str]) -> str:
        """
        Sélectionne le meilleur nœud disponible.
        Préfère le nœud demandé, mais bascule si congestionné.
        """
        # Filtrer les nœuds disponibles
        candidates = [n for n in available if n in self._metrics or n == preferred]

        if not candidates:
            return preferred

        # Si le préféré n'est pas congestionné, le garder
        if preferred in self._metrics:
            m = self._metrics[preferred]
            if not m.is_congested:
                return preferred

        # Sinon, chercher le moins chargé
        best = min(candidates, key=lambda n: self._metrics.get(n, NodeMetrics(name=n)).avg_latency)
        if best != preferred:
            logger.info(f"[LoadBalancer] Rerouting: {preferred} → {best}")
        return best

    def get_clones(self, node_name: str) -> list[str]:
        """Retourne les clones d'un nœud."""
        return self._clones.get(node_name, [])

    def get_report(self) -> dict:
        """Rapport de charge."""
        nodes = {}
        for name, m in self._metrics.items():
            nodes[name] = {
                "avg_latency_ms": round(m.avg_latency, 1),
                "baseline_latency_ms": round(m.baseline_latency, 1),
                "calls": m.calls,
                "failures": m.failures,
                "failure_rate": round(m.failure_rate, 3),
                "congested": m.is_congested,
                "clones": self._clones.get(name, []),
            }
        return {
            "total_nodes": len(self._metrics),
            "congested": sum(1 for n in nodes.values() if n["congested"]),
            "nodes": nodes,
        }


# Singleton
_instance: ForgeLoadBalancer | None = None


def get_load_balancer() -> ForgeLoadBalancer:
    global _instance
    if _instance is None:
        _instance = ForgeLoadBalancer()
    return _instance
