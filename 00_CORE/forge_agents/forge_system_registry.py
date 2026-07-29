"""
forge_system_registry.py — V6 System Registry
Carte complète de tous les composants Forge : agents, tools, MCP, skills.
Chaque composant est un node avec capabilities, inputs, outputs, reliability, cost.

Structure :
  nodes.json   → tous les composants
  edges.json   → dépendances entre composants
  capabilities.json → index des capacités

Le registry est auto-scanné depuis le filesystem + registry.json existant.
"""

from __future__ import annotations
import json
import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


FORGE_ROOT = Path(__file__).parent.parent.parent
REGISTRY_DIR = FORGE_ROOT / "05_STATE" / "system_registry"


@dataclass
class SystemNode:
    """Un composant de la Forge."""
    id: str
    type: str  # "agent" | "mcp" | "workflow" | "memory" | "tool" | "skill"
    capabilities: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    reliability: float = 0.8  # 0.0 → 1.0
    cost: float = 0.0  # coût par appel ($)
    latency: float = 0.0  # latence moyenne (sec)
    file_path: str = ""
    size_bytes: int = 0
    status: str = "active"  # active | degraded | dead | planned
    tags: list[str] = field(default_factory=list)
    last_used: str = ""
    call_count: int = 0
    # AAOS 59 — budgets & policies par composant (0/"" = pas de limite)
    provider_preferred: str = ""
    provider_fallback: list[str] = field(default_factory=list)
    max_tokens_budget: int = 0        # tokens max par appel
    max_cost_day: float = 0.0         # $ max par jour
    latency_p95_ms: int = 0           # SLO latence p95
    cache_semantic: bool = True       # cache sémantique + fingerprint actifs
    cache_ttl_days: int = 30
    concurrency_group: str = ""       # sérialisation des écritures concurrentes


@dataclass
class SystemEdge:
    """Dépendance entre deux composants."""
    source: str
    target: str
    type: str = "dependency"  # dependency | data_flow | control_flow
    weight: float = 1.0


@dataclass
class Capability:
    """Une capacité de la Forge."""
    name: str
    providers: list[str] = field(default_factory=list)  # node IDs
    domain: str = ""
    description: str = ""


class SystemRegistry:
    """
    Registry global de la Forge.
    Scanne le filesystem, lit le registry.json existant,
    produit le System Registry structuré V6.
    """

    def __init__(self):
        self.nodes: dict[str, SystemNode] = {}
        self.edges: list[SystemEdge] = []
        self.capabilities: dict[str, Capability] = {}
        self._scan_time: Optional[str] = None

    def scan(self) -> None:
        """Scan complet du système existant."""
        self._scan_agents()
        self._scan_tools()
        self._scan_skills()
        self._scan_edges()
        self._index_capabilities()
        self._scan_time = datetime.datetime.now().isoformat()

    def _scan_agents(self) -> None:
        """Scanne forge_agents/*.py comme agents."""
        agents_dir = FORGE_ROOT / "00_CORE" / "forge_agents"
        if not agents_dir.exists():
            return
        for f in agents_dir.glob("*.py"):
            if f.name.startswith("_") or f.name == "__init__.py":
                continue
            node_id = f.stem
            # Détecter les capabilities depuis le docstring
            caps = self._detect_capabilities(f)
            self.nodes[node_id] = SystemNode(
                id=node_id,
                type="agent",
                capabilities=caps,
                file_path=str(f.relative_to(FORGE_ROOT)),
                size_bytes=f.stat().st_size,
                status="active",
            )

    def _scan_tools(self) -> None:
        """Scanne tools/registry.json + tools/**/*.py comme tools."""
        registry_path = FORGE_ROOT / "00_CORE" / "tools" / "registry.json"
        if registry_path.exists():
            try:
                reg = json.loads(registry_path.read_text(encoding="utf-8"))
                for entry in reg.get("tools", []):
                    if not isinstance(entry, str) or not entry.startswith("TOOL|"):
                        continue
                    parts = entry.split("|")
                    if len(parts) < 7:
                        continue
                    node_id = parts[1]
                    kind = parts[2]
                    status = parts[3]
                    purpose = parts[4]
                    wrapper = parts[5]
                    tags = parts[6].split(",") if parts[6] else []
                    self.nodes[node_id] = SystemNode(
                        id=node_id,
                        type="tool",
                        file_path=wrapper,
                        status=status,
                        tags=tags,
                    )
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Scanner aussi les fichiers .py dans tools/
        tools_dir = FORGE_ROOT / "00_CORE" / "tools"
        if tools_dir.exists():
            for f in tools_dir.rglob("*.py"):
                if f.name.startswith("_"):
                    continue
                rel = f.relative_to(tools_dir)
                node_id = str(rel).replace("\\", "/").replace(".py", "")
                if node_id not in self.nodes:
                    self.nodes[node_id] = SystemNode(
                        id=node_id,
                        type="tool",
                        file_path=str(f.relative_to(FORGE_ROOT)),
                        size_bytes=f.stat().st_size,
                    )

    def _scan_skills(self) -> None:
        """Scanne les skills comme composants."""
        # impeccable references
        ref_dir = FORGE_ROOT / "00_CORE" / "impeccable" / "reference"
        if ref_dir.exists():
            for f in ref_dir.glob("*.md"):
                self.nodes[f"skill:{f.stem}"] = SystemNode(
                    id=f"skill:{f.stem}",
                    type="skill",
                    file_path=str(f.relative_to(FORGE_ROOT)),
                    size_bytes=f.stat().st_size,
                )

    def _scan_edges(self) -> None:
        """Détecte les dépendances entre agents (imports)."""
        agents_dir = FORGE_ROOT / "00_CORE" / "forge_agents"
        agent_ids = [n for n in self.nodes if self.nodes[n].type == "agent"]
        for aid in agent_ids:
            fpath = agents_dir / f"{aid}.py"
            if not fpath.exists():
                continue
            try:
                content = fpath.read_text(encoding="utf-8")
                for other_id in agent_ids:
                    if other_id != aid and other_id in content:
                        self.edges.append(SystemEdge(
                            source=aid,
                            target=other_id,
                            type="dependency",
                        ))
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def _detect_capabilities(self, fpath: Path) -> list[str]:
        """Détecte les capabilities d'un agent depuis son code."""
        try:
            content = fpath.read_text(encoding="utf-8")[:3000].lower()
        except Exception:
            return []
        caps = []
        mapping = {
            "kernel": "kernel_extraction", "mcp": "mcp_integration",
            "memory": "memory", "verify": "verification", "hallucin": "verification",
            "scrape": "scraping", "llm": "llm_routing", "forge_call": "llm_routing",
            "graph": "graph_operations", "cache": "caching", "embed": "embeddings",
            "rag": "rag", "agent": "orchestration", "orchestrat": "orchestration",
            "deploy": "deployment", "test": "testing", "monitor": "monitoring",
        }
        for keyword, cap in mapping.items():
            if keyword in content and cap not in caps:
                caps.append(cap)
        return caps

    def _index_capabilities(self) -> None:
        """Indexe les capabilities pour recherche rapide."""
        for nid, node in self.nodes.items():
            for cap in node.capabilities:
                if cap not in self.capabilities:
                    self.capabilities[cap] = Capability(name=cap)
                if nid not in self.capabilities[cap].providers:
                    self.capabilities[cap].providers.append(nid)

    def save(self) -> None:
        """Persiste le registry en JSON."""
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

        nodes_data = {nid: asdict(n) for nid, n in self.nodes.items()}
        edges_data = [asdict(e) for e in self.edges]
        caps_data = {cid: asdict(c) for cid, c in self.capabilities.items()}

        (REGISTRY_DIR / "nodes.json").write_text(
            json.dumps(nodes_data, indent=2, ensure_ascii=False), encoding="utf-8")
        (REGISTRY_DIR / "edges.json").write_text(
            json.dumps(edges_data, indent=2, ensure_ascii=False), encoding="utf-8")
        (REGISTRY_DIR / "capabilities.json").write_text(
            json.dumps(caps_data, indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> dict:
        """Résumé du registry."""
        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for n in self.nodes.values():
            type_counts[n.type] = type_counts.get(n.type, 0) + 1
            status_counts[n.status] = status_counts.get(n.status, 0) + 1
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "total_capabilities": len(self.capabilities),
            "by_type": type_counts,
            "by_status": status_counts,
            "scan_time": self._scan_time,
        }

    def get_node(self, node_id: str) -> Optional[SystemNode]:
        return self.nodes.get(node_id)

    def find_capability(self, cap: str) -> list[str]:
        """Trouve les providers d'une capability."""
        c = self.capabilities.get(cap)
        return c.providers if c else []


# Singleton
_registry: Optional[SystemRegistry] = None


def get_registry() -> SystemRegistry:
    global _registry
    if _registry is None:
        _registry = SystemRegistry()
        _registry.scan()
    return _registry


def refresh_registry() -> SystemRegistry:
    """Force un re-scan."""
    global _registry
    _registry = SystemRegistry()
    _registry.scan()
    return _registry


if __name__ == "__main__":
    reg = get_registry()
    reg.save()
    s = reg.summary()
    print(f"Nodes: {s['total_nodes']}")
    print(f"Edges: {s['total_edges']}")
    print(f"Capabilities: {s['total_capabilities']}")
    print(f"By type: {s['by_type']}")
    print(f"Saved to {REGISTRY_DIR}")
