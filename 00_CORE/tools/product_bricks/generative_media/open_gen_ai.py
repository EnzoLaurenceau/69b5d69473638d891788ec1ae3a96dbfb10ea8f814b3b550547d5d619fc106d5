"""
open_gen_ai.py — Wrapper open-generative-ai (anil-matcha)
============================================================
Studio image+vidéo self-host, 200+ modèles (Flux, Kling, Sora, Veo). MIT.
Docker requis.

Usage :
    from tools.product_bricks.generative_media import open_gen_ai
    open_gen_ai.deploy(project_path)                         # écrit docker-compose
    open_gen_ai.up(project_path)                             # lance le service
    ok = open_gen_ai.status()                                # True si UP
    path = open_gen_ai.generate_image("...", "flux-schnell", "out.png")
    path = open_gen_ai.generate_video("...", "kling-v1",    "out.mp4")
"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
import urllib.request

REPO = "https://github.com/anil-matcha/open-generative-ai"
DEFAULT_PORT = int(os.environ.get("OPEN_GEN_AI_PORT", 7860))
DEFAULT_HOST = os.environ.get("OPEN_GEN_AI_HOST", f"http://localhost:{DEFAULT_PORT}")

_COMPOSE = """\
services:
  open-gen-ai:
    image: ghcr.io/anil-matcha/open-generative-ai:latest
    ports:
      - "{port}:7860"
    restart: unless-stopped
    environment:
      - GRADIO_SERVER_NAME=0.0.0.0
"""


def deploy(project_path: str | Path, port: int = DEFAULT_PORT) -> Path:
    """Écrit docker-compose.open-gen-ai.yml dans project_path."""
    out = Path(project_path) / "docker-compose.open-gen-ai.yml"
    out.write_text(_COMPOSE.format(port=port), encoding="utf-8")
    print(f"open_gen_ai: compose → {out}")
    return out


def up(project_path: str | Path) -> None:
    """docker compose up -d (lance le service)."""
    cf = Path(project_path) / "docker-compose.open-gen-ai.yml"
    subprocess.run(["docker", "compose", "-f", str(cf), "up", "-d"], check=True)
    print(f"open_gen_ai: UP → {DEFAULT_HOST}")


def status(host: str = DEFAULT_HOST) -> bool:
    """True si l'API Gradio répond."""
    try:
        urllib.request.urlopen(f"{host}/api/queue/status", timeout=3)
        return True
    except Exception:
        return False


def generate_image(
    prompt: str,
    model: str = "flux-schnell",
    output_path: str | Path | None = None,
    host: str = DEFAULT_HOST,
) -> str:
    """Génère une image et retourne son URL ou chemin local."""
    payload = json.dumps({"data": [prompt, model], "fn_index": 0}).encode()
    req = urllib.request.Request(
        f"{host}/run/predict",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.loads(r.read())
    img = result["data"][0]
    img_url = img.get("url", img) if isinstance(img, dict) else img
    if not str(img_url).startswith("http"):
        img_url = f"{host}/file={img_url}"
    if output_path:
        urllib.request.urlretrieve(img_url, str(output_path))
        return str(output_path)
    return img_url


def generate_video(
    prompt: str,
    model: str = "kling-v1",
    output_path: str | Path | None = None,
    host: str = DEFAULT_HOST,
) -> str:
    """Génère une vidéo et retourne son URL ou chemin local."""
    payload = json.dumps({"data": [prompt, model], "fn_index": 1}).encode()
    req = urllib.request.Request(
        f"{host}/run/predict",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        result = json.loads(r.read())
    vid = result["data"][0]
    vid_url = vid.get("url", vid) if isinstance(vid, dict) else vid
    if not str(vid_url).startswith("http"):
        vid_url = f"{host}/file={vid_url}"
    if output_path:
        urllib.request.urlretrieve(vid_url, str(output_path))
        return str(output_path)
    return vid_url


if __name__ == "__main__":
    up_ok = status()
    print(f"open_gen_ai: {'UP' if up_ok else 'DOWN'} @ {DEFAULT_HOST}")
    print(f"Repo  : {REPO}")
    print("Deploy: open_gen_ai.deploy(project_path) → docker compose up")
