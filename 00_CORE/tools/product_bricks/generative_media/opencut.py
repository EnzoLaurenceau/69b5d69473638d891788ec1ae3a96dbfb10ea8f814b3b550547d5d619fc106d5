"""
opencut.py — Wrapper OpenCut (éditeur vidéo web)
=================================================
OpenCut : éditeur vidéo web open-source (alt. CapCut). MIT.
Self-host Docker. Pas d'API headless publique.

Montages automatisés → déployer + utiliser browser-use
(tools/automation/browser_use.py) pour piloter l'éditeur.

Usage :
    from tools.product_bricks.generative_media import opencut
    opencut.deploy(project_path)   # écrit docker-compose
    opencut.up(project_path)       # lance le service
    print(opencut.url())           # URL du studio web
"""
from __future__ import annotations
import subprocess
from pathlib import Path
import urllib.request

REPO = "https://github.com/OpenCut-app/opencut"
DEFAULT_PORT = int(__import__("os").environ.get("OPENCUT_PORT", 3000))

_COMPOSE = """\
services:
  opencut:
    image: ghcr.io/opencut-app/opencut:latest
    ports:
      - "{port}:3000"
    restart: unless-stopped
"""


def deploy(project_path: str | Path, port: int = DEFAULT_PORT) -> Path:
    """Écrit docker-compose.opencut.yml dans project_path."""
    out = Path(project_path) / "docker-compose.opencut.yml"
    out.write_text(_COMPOSE.format(port=port), encoding="utf-8")
    print(f"opencut: compose → {out}")
    return out


def up(project_path: str | Path) -> None:
    """docker compose up -d"""
    cf = Path(project_path) / "docker-compose.opencut.yml"
    subprocess.run(["docker", "compose", "-f", str(cf), "up", "-d"], check=True)
    print(f"opencut: UP → {url()}")


def url(port: int = DEFAULT_PORT) -> str:
    return f"http://localhost:{port}"


def status(port: int = DEFAULT_PORT) -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{port}", timeout=3)
        return True
    except Exception:
        return False


# ponytail: pas d'API headless — montages auto via browser-use
# from tools.automation import browser_use; browser_use.run(url())
def automate_hint() -> str:
    return (
        "OpenCut n'a pas d'API headless. "
        "Montages auto : déployer → piloter via tools/automation/browser_use.py"
    )


if __name__ == "__main__":
    print(f"opencut: {'UP' if status() else 'DOWN'} @ {url()}")
    print(f"Repo  : {REPO}")
    print(automate_hint())
