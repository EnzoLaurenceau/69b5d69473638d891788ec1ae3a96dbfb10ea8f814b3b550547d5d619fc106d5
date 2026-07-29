"""
repowise.py — Wrapper Repowise (2 features gap uniquement)
===========================================================
Features gap vs Forge actuelle (GitNexus + Herald) :
  1. ADR auto-gen  — Architecture Decision Records depuis l'historique git
  2. Git analytics — churn, velocity, hotspots par fichier/module

Features DÉJÀ couvertes ailleurs — NE PAS dupliquer :
  Dead code     → Herald
  Code health   → Herald + GitNexus
  Impact        → GitNexus

Usage :
    from tools.mcp import repowise
    adrs  = repowise.get_adr(repo_path)       # {adrs: [...]}
    stats = repowise.get_analytics(repo_path)  # {hotspots, velocity, churn}
"""
from __future__ import annotations
import json, subprocess
from pathlib import Path

REPO = "https://github.com/repowise-dev/repowise"
INSTALL_CMD = "npm install -g repowise"


def _is_installed() -> bool:
    return subprocess.run(["repowise", "--version"], capture_output=True).returncode == 0


def _run(*args: str, cwd: str | None = None) -> dict:
    r = subprocess.run(
        ["repowise", *args, "--format", "json"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        return {"error": r.stderr or "repowise: commande échouée"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"raw": r.stdout}


def get_adr(repo_path: str | Path) -> dict:
    """Architecture Decision Records auto-générés depuis l'historique git."""
    if not _is_installed():
        return {"error": f"repowise non installé — {INSTALL_CMD}"}
    return _run("adr", cwd=str(repo_path))


def get_analytics(repo_path: str | Path) -> dict:
    """Churn / velocity / hotspots par fichier (git analytics)."""
    if not _is_installed():
        return {"error": f"repowise non installé — {INSTALL_CMD}"}
    return _run("analytics", cwd=str(repo_path))


# ponytail: thin wrapper, 2 features seulement.
# Dead code/health → Herald. Impact → GitNexus. Ne pas élargir.

if __name__ == "__main__":
    installed = _is_installed()
    print(f"repowise: {'installé' if installed else f'non installé ({INSTALL_CMD})'}")
    print("Features Forge : ADR (get_adr) + git analytics (get_analytics)")
    print("Hors scope     : dead code (Herald), health (Herald+GitNexus), impact (GitNexus)")
