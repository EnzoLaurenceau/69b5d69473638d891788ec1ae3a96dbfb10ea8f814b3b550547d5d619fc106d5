"""
forge_visualizer.py — V6 Forge Dashboard Server
Sert le dashboard HTML + API JSON pour visualisation temps réel.

Lance : python forge_visualizer.py [--port 8420]
Dashboard : http://localhost:8420

Endpoints API :
  GET /api/forge-map      → carte cognitive complète
  GET /api/workflows      → graphe des workflows
  GET /api/capabilities   → capacités (agents, MCP, tools)
  GET /api/experience     → mémoire d'expérience (BigSet)
  GET /api/cost           → métriques coût/latence/hallucinations
  GET /api/trace          → trace d'exécution active
  GET /api/meta           → état de l'alter stratégique
  GET /api/events         → historique événements
  GET /api/health         → santé du système
"""

from __future__ import annotations
import json
import sys
import os
import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

# Ajouter le parent au path pour imports
FORGE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(FORGE_ROOT))

# Imports V6
try:
    from importlib import import_module
    kernel_mod = import_module("00_CORE.forge_agents.forge_kernel")
    brain_mod = import_module("00_CORE.forge_agents.forge_shared_brain")
    exp_mod = import_module("00_CORE.forge_agents.forge_experience_db")
    meta_mod = import_module("00_CORE.forge_agents.forge_meta")
    lazy_mod = import_module("00_CORE.forge_agents.forge_lazy")
    bus_mod = import_module("00_CORE.forge_agents.forge_event_bus")
    heal_mod = import_module("00_CORE.forge_agents.forge_self_heal")
    registry_mod = import_module("00_CORE.forge_agents.forge_system_registry")
    logger_mod = import_module("00_CORE.forge_agents.forge_execution_logger")
    pruner_mod = import_module("00_CORE.forge_agents.forge_mcp_pruner")
    V6_AVAILABLE = True
except Exception as e:
    print(f"[visualizer] V6 modules not loadable: {e}")
    V6_AVAILABLE = False


DASHBOARD_PATH = Path(__file__).parent / "forge_dashboard.html"


def build_forge_map() -> dict:
    """Construit la carte cognitive complète de la Forge."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}

    exp_db = exp_mod.get_experience_db()
    meta = meta_mod.get_meta()
    bus = bus_mod.get_event_bus()
    healer = heal_mod.get_healer()

    # Scan des composants Forge
    forge_agents_dir = FORGE_ROOT / "00_CORE" / "forge_agents"
    agents = []
    if forge_agents_dir.exists():
        for f in forge_agents_dir.glob("*.py"):
            if f.name.startswith("_"):
                continue
            agents.append({
                "id": f.stem,
                "type": "agent",
                "file": str(f.relative_to(FORGE_ROOT)),
                "size_bytes": f.stat().st_size,
            })

    # Tools registry
    registry_path = FORGE_ROOT / "00_CORE" / "tools" / "registry.json"
    tools = []
    if registry_path.exists():
        try:
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            for name, info in reg.get("tools", {}).items():
                tools.append({
                    "id": name,
                    "type": "tool",
                    "status": info.get("status", "unknown"),
                    "category": info.get("category", ""),
                })
        except Exception:
            pass

    # Edges = dépendances entre agents (imports)
    edges = []
    for agent in agents:
        agent_path = forge_agents_dir / f"{agent['id']}.py"
        if agent_path.exists():
            try:
                content = agent_path.read_text(encoding="utf-8")
                for other in agents:
                    if other["id"] != agent["id"] and other["id"] in content:
                        edges.append({
                            "source": agent["id"],
                            "target": other["id"],
                            "type": "dependency",
                        })
            except Exception:
                pass

    # Component health from experience DB
    health_summary = exp_db.summary()

    return {
        "nodes": agents + tools,
        "edges": edges,
        "agents_count": len(agents),
        "tools_count": len(tools),
        "edges_count": len(edges),
        "dead_components": health_summary.get("dead_components", []),
        "degraded_components": health_summary.get("degraded_components", []),
        "meta_status": meta.get_status(),
        "heal_summary": healer.summary(),
        "event_stats": bus.stats(),
        "generated_at": datetime.datetime.now().isoformat(),
    }


def build_workflow_graph() -> dict:
    """Graphe des workflows de la Forge."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}

    # Le workflow principal V6
    main_workflow = {
        "id": "main_v6",
        "name": "Forge V6 Main Workflow",
        "nodes": [
            {"id": "v6_init", "label": "V6 Init\n(Kernel + Brain)", "type": "init", "layer": 0},
            {"id": "estimate_budget", "label": "Estimate\nBudget", "type": "budget", "layer": 1},
            {"id": "orchestrator", "label": "Orchestrator", "type": "router", "layer": 2},
            {"id": "zsl_analysis", "label": "ZSL\nAnalysis", "type": "analysis", "layer": 3},
            {"id": "dynamic_agent", "label": "Dynamic\nAgent", "type": "agent", "layer": 3},
            {"id": "neuro_symbolic", "label": "Neuro\nSymbolic\nVerification", "type": "verify", "layer": 4},
            {"id": "anti_hallucination", "label": "Anti\nHallucination", "type": "verify", "layer": 5},
            {"id": "v6_post_exec", "label": "V6 Post\nExecution\n(Meta + DB)", "type": "meta", "layer": 6},
            {"id": "auto_complex", "label": "Auto\nComplexification", "type": "router", "layer": 7},
            {"id": "memory_pruner", "label": "Memory\nPruner", "type": "memory", "layer": 8},
            {"id": "post_mortem", "label": "Post\nMortem", "type": "meta", "layer": 9},
        ],
        "edges": [
            {"source": "v6_init", "target": "estimate_budget", "type": "sequential"},
            {"source": "estimate_budget", "target": "orchestrator", "type": "sequential"},
            {"source": "orchestrator", "target": "dynamic_agent", "type": "conditional", "label": "route_agent"},
            {"source": "orchestrator", "target": "zsl_analysis", "type": "conditional", "label": "route_zsl"},
            {"source": "zsl_analysis", "target": "dynamic_agent", "type": "sequential"},
            {"source": "dynamic_agent", "target": "v6_post_exec", "type": "conditional", "label": "route_after_agent"},
            {"source": "dynamic_agent", "target": "neuro_symbolic", "type": "conditional", "label": "route_verify"},
            {"source": "neuro_symbolic", "target": "anti_hallucination", "type": "sequential"},
            {"source": "anti_hallucination", "target": "auto_complex", "type": "conditional"},
            {"source": "anti_hallucination", "target": "dynamic_agent", "type": "conditional", "label": "retry"},
            {"source": "v6_post_exec", "target": "auto_complex", "type": "sequential"},
            {"source": "auto_complex", "target": "memory_pruner", "type": "conditional", "label": "continue"},
            {"source": "auto_complex", "target": "post_mortem", "type": "conditional", "label": "end"},
            {"source": "memory_pruner", "target": "orchestrator", "type": "loop"},
            {"source": "post_mortem", "target": "__end__", "type": "terminal"},
        ],
    }

    # Subconscient workflow
    subconscient = {
        "id": "subconscient",
        "name": "Subconscient (Background)",
        "nodes": [
            {"id": "consolidation", "label": "Memory\nConsolidation", "type": "memory"},
            {"id": "pattern_detect", "label": "Pattern\nDetection", "type": "analysis"},
            {"id": "score_update", "label": "Workflow\nScoring", "type": "meta"},
            {"id": "cleanup", "label": "Memory\nCleanup", "type": "memory"},
        ],
        "edges": [
            {"source": "consolidation", "target": "pattern_detect"},
            {"source": "pattern_detect", "target": "score_update"},
            {"source": "score_update", "target": "cleanup"},
        ],
    }

    return {
        "workflows": [main_workflow, subconscient],
        "total_workflows": 2,
    }


def build_capability_graph() -> dict:
    """Graphe des capacités de la Forge."""
    agents_dir = FORGE_ROOT / "00_CORE" / "forge_agents"
    tools_dir = FORGE_ROOT / "00_CORE" / "tools"

    capabilities = {
        "agents": [],
        "tools": [],
        "mcp": [],
        "skills": [],
    }

    # Agents
    if agents_dir.exists():
        for f in agents_dir.glob("*.py"):
            if f.name.startswith("_") or f.name == "__init__.py":
                continue
            try:
                content = f.read_text(encoding="utf-8")[:2000]
                # Detect capabilities from docstring
                caps = []
                if "kernel" in content.lower(): caps.append("kernel_extraction")
                if "mcp" in content.lower(): caps.append("mcp_integration")
                if "memory" in content.lower(): caps.append("memory")
                if "verify" in content.lower() or "hallucin" in content.lower(): caps.append("verification")
                if "scrape" in content.lower(): caps.append("scraping")
                if "llm" in content.lower() or "forge_call" in content.lower(): caps.append("llm_routing")
                if "graph" in content.lower(): caps.append("graph_operations")
                if "cache" in content.lower(): caps.append("caching")
                if "embed" in content.lower(): caps.append("embeddings")
                capabilities["agents"].append({
                    "id": f.stem,
                    "capabilities": caps,
                    "size": f.stat().st_size,
                })
            except Exception:
                pass

    # Tools
    if tools_dir.exists():
        for f in tools_dir.rglob("*.py"):
            if f.name.startswith("_"):
                continue
            rel = f.relative_to(tools_dir)
            capabilities["tools"].append({
                "id": str(rel).replace("\\", "/").replace(".py", ""),
                "category": str(rel.parent) if rel.parent != Path(".") else "root",
            })

    # Skills
    skills_dir = FORGE_ROOT / "00_CORE" / "impeccable" / "reference"
    if skills_dir.exists():
        for f in skills_dir.glob("*.md"):
            capabilities["skills"].append({"id": f.stem, "type": "reference"})

    taste_dir = FORGE_ROOT / "00_CORE" / "taste-skill"
    if taste_dir.exists():
        capabilities["skills"].append({"id": "taste-profile", "type": "profile"})

    return capabilities


def build_experience_data() -> dict:
    """Données d'expérience pour le Memory Graph."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    db = exp_mod.get_experience_db()
    return db.summary()


def build_cost_data() -> dict:
    """Métriques coût/latence/hallucinations."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    meta = meta_mod.get_meta()
    exp_db = exp_mod.get_experience_db()
    bus = bus_mod.get_event_bus()

    summary = exp_db.summary()
    return {
        "meta": {
            "confidence": meta.emotional.confidence,
            "uncertainty": meta.emotional.uncertainty,
            "risk": meta.emotional.risk,
            "reward": meta.emotional.reward,
            "curiosity": meta.emotional.curiosity,
        },
        "total_cost": summary.get("total_experiences", 0) * 0.15,  # estimation
        "hallucination_sources": summary.get("top_hallucination_sources", []),
        "best_workflows": summary.get("best_workflows", []),
        "event_stats": bus.stats(),
    }


def build_trace_data() -> dict:
    """Trace d'exécution active."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    tracer = bus_mod.get_tracer()
    return {
        "traces": tracer.get_traces(limit=10),
        "total": len(tracer.get_traces()),
    }


def build_meta_data() -> dict:
    """État complet de l'alter stratégique."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    meta = meta_mod.get_meta()
    return meta.get_status()


def build_events_data() -> dict:
    """Historique des événements."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    bus = bus_mod.get_event_bus()
    return {
        "events": bus.get_history(limit=100),
        "stats": bus.stats(),
    }


def build_health_data() -> dict:
    """Santé globale du système."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    exp_db = exp_mod.get_experience_db()
    meta = meta_mod.get_meta()
    healer = heal_mod.get_healer()

    return {
        "experience_db": exp_db.summary(),
        "meta_layer": meta.get_status(),
        "self_healing": healer.summary(),
        "forge_root": str(FORGE_ROOT),
        "v6_available": V6_AVAILABLE,
    }


def build_registry_data() -> dict:
    """System Registry complet."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    reg = registry_mod.get_registry()
    return reg.summary()


def build_mcp_prune_data() -> dict:
    """MCP Pruning analysis."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    pruner = pruner_mod.get_pruner()
    pruner.analyze()
    return pruner.get_summary()


def build_traces_data() -> dict:
    """Execution traces persistées."""
    if not V6_AVAILABLE:
        return {"error": "V6 modules not available"}
    logger = logger_mod.get_logger()
    return {
        "traces": logger.list_traces(limit=20),
        "stats": logger.get_stats(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP SERVER
# ═══════════════════════════════════════════════════════════════════════════════

class ForgeDashboardHandler(SimpleHTTPRequestHandler):
    """Handler HTTP pour le dashboard Forge."""

    def do_GET(self):
        routes = {
            "/api/forge-map": build_forge_map,
            "/api/workflows": build_workflow_graph,
            "/api/capabilities": build_capability_graph,
            "/api/experience": build_experience_data,
            "/api/cost": build_cost_data,
            "/api/trace": build_trace_data,
            "/api/meta": build_meta_data,
            "/api/events": build_events_data,
            "/api/health": build_health_data,
            "/api/registry": build_registry_data,
            "/api/mcp-prune": build_mcp_prune_data,
            "/api/traces": build_traces_data,
        }

        if self.path == "/" or self.path == "/dashboard":
            self._serve_dashboard()
        elif self.path in routes:
            self._serve_json(routes[self.path]())
        else:
            super().do_GET()

    def _serve_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8"))

    def _serve_dashboard(self):
        if DASHBOARD_PATH.exists():
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_PATH.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Dashboard HTML not found")

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def run_server(port: int = 8420):
    """Lance le serveur dashboard."""
    server = HTTPServer(("127.0.0.1", port), ForgeDashboardHandler)
    print(f"[Forge Dashboard] http://localhost:{port}")
    print(f"[Forge Dashboard] API: http://localhost:{port}/api/health")
    print(f"[Forge Dashboard] V6 modules: {'loaded' if V6_AVAILABLE else 'NOT available'}")
    print(f"[Forge Dashboard] Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Forge Dashboard] Stopped.")
        server.server_close()


if __name__ == "__main__":
    port = 8420
    if len(sys.argv) > 1 and sys.argv[1] == "--port":
        port = int(sys.argv[2])
    run_server(port)
