"""
shadcn_caller.py — Wrapper CLI shadcn/ui
==========================================
Appelle `npx shadcn@latest` uniquement quand l'orchestrateur choisit shadcn
après consultation du design_kb. Ne jamais imposer automatiquement.
Node.js requis.
"""
from __future__ import annotations
import subprocess
from pathlib import Path


def init(project_path: str | Path) -> None:
    """npx shadcn@latest init dans le répertoire projet."""
    _run(["npx", "shadcn@latest", "init"], cwd=str(project_path))


def add(project_path: str | Path, components: list[str]) -> None:
    """npx shadcn@latest add <components...>"""
    _run(["npx", "shadcn@latest", "add"] + components, cwd=str(project_path))


def _run(cmd: list[str], cwd: str) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"shadcn: {result.stderr or result.stdout}")
    print(result.stdout)


if __name__ == "__main__":
    # ponytail: dry-run self-check
    r = subprocess.run(["node", "--version"], capture_output=True, text=True)
    print(f"shadcn_caller: Node.js {r.stdout.strip() or 'non trouvé'}")
    print("init(project_path) / add(project_path, ['button', 'card', ...]) prêts")
