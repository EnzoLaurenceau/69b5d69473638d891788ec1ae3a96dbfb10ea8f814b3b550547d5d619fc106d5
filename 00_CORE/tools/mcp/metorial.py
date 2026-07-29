"""
metorial.py — Wrapper Metorial (hub d'intégrations MCP)
========================================================
Metorial connecte tout LLM à 1200+ intégrations via MCP/CLI/API.

Règle MCP mise à jour :
  mcp-registry (connecteur existant ?) → metorial (intégration hub ?) → mcpify (générer)

Usage :
    from tools.mcp import metorial
    results = metorial.search("stripe")           # cherche une intégration
    metorial.connect("stripe", project_path)      # génère la config MCP
    integrations = metorial.list_integrations()   # liste tout
"""
from __future__ import annotations
import json, subprocess
from pathlib import Path

REPO = "https://github.com/metorial/metorial"
INSTALL_CMD = "npm install -g @metorial/cli"

# Ordre de résolution MCP (règle forge mise à jour)
RESOLUTION_ORDER = ["mcp-registry", "metorial", "mcpify"]


def _is_installed() -> bool:
    return subprocess.run(["metorial", "--version"], capture_output=True).returncode == 0


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["metorial", *args], capture_output=True, text=True)


def search(query: str) -> list[dict]:
    """Cherche une intégration Metorial."""
    if not _is_installed():
        print(f"metorial: non installé — {INSTALL_CMD}")
        return [{"hint": f"Install puis: metorial search {query}"}]
    r = _cli("search", query, "--json")
    try:
        return json.loads(r.stdout) if r.returncode == 0 else [{"error": r.stderr}]
    except json.JSONDecodeError:
        return [{"raw": r.stdout}]


def connect(integration_id: str, project_path: str | Path) -> Path | None:
    """Génère la config MCP pour l'intégration dans project_path/.mcp/."""
    if not _is_installed():
        print(f"metorial: non installé — {INSTALL_CMD}")
        return None
    mcp_dir = Path(project_path) / ".mcp"
    mcp_dir.mkdir(exist_ok=True)
    r = _cli("connect", integration_id, "--output", str(mcp_dir))
    if r.returncode == 0:
        print(f"metorial: config MCP → {mcp_dir}")
        return mcp_dir
    print(f"metorial error: {r.stderr}")
    return None


def list_integrations() -> list[dict]:
    if not _is_installed():
        return [{"info": INSTALL_CMD, "repo": REPO}]
    r = _cli("list", "--json")
    try:
        return json.loads(r.stdout) if r.returncode == 0 else [{"error": r.stderr}]
    except json.JSONDecodeError:
        return [{"raw": r.stdout}]


if __name__ == "__main__":
    installed = _is_installed()
    print(f"metorial: CLI {'installée' if installed else 'non installée'}")
    if not installed:
        print(f"Install : {INSTALL_CMD}")
    print(f"Repo    : {REPO}")
    print(f"Ordre résolution MCP : {' → '.join(RESOLUTION_ORDER)}")
