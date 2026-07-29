"""
langflow.py — Wrapper Langflow (github.com/langflow-ai/langflow)
================================================================
Builder visuel de flows IA + RAG. Docker requis.
Produit = workflow IA, agent multi-étapes, RAG sur documents.

Usage :
    from tools.product_bricks.ai_workflows import langflow
    langflow.deploy(project_path)               # écrit docker-compose
    langflow.up(project_path)                   # docker compose up
    ok = langflow.status()                      # True si service répond
    flow_id = langflow.create_flow(json_def)    # crée un flow depuis JSON
    result = langflow.run_flow(flow_id, inputs) # exécute un flow
    flows = langflow.list_flows()               # liste les flows disponibles
"""

from __future__ import annotations
import json, os, subprocess, urllib.request
from pathlib import Path

DEFAULT_PORT = int(os.environ.get("LANGFLOW_PORT", 7860))
DEFAULT_HOST = os.environ.get("LANGFLOW_HOST", f"http://localhost:{DEFAULT_PORT}")
DOCKER_IMAGE = "langflowai/langflow:latest"

_COMPOSE = """\
services:
  langflow:
    image: {image}
    ports:
      - "{port}:7860"
    volumes:
      - langflow_data:/app/langflow
    environment:
      - LANGFLOW_AUTO_LOGIN=true
      - LANGFLOW_SUPERUSER=admin
      - LANGFLOW_SUPERUSER_PASSWORD=forge_langflow
    restart: unless-stopped
volumes:
  langflow_data:
"""


def deploy(project_path: str | Path) -> Path:
    """Écrit le docker-compose Langflow dans project_path/langflow/."""
    out_dir = Path(project_path) / "langflow"
    out_dir.mkdir(parents=True, exist_ok=True)
    cf = out_dir / "docker-compose.yml"
    cf.write_text(_COMPOSE.format(image=DOCKER_IMAGE, port=DEFAULT_PORT), encoding="utf-8")
    print(f"langflow: compose → {cf}")
    return cf


def up(project_path: str | Path) -> None:
    """docker compose up -d."""
    cf = Path(project_path) / "langflow" / "docker-compose.yml"
    if not cf.exists():
        deploy(project_path)
    subprocess.run(["docker", "compose", "-f", str(cf), "up", "-d"], check=True)
    print(f"langflow: UP → {DEFAULT_HOST}")


def status(host: str = DEFAULT_HOST) -> bool:
    """True si Langflow répond."""
    try:
        urllib.request.urlopen(f"{host}/api/v1/version", timeout=3)
        return True
    except Exception:
        try:
            urllib.request.urlopen(host, timeout=3)
            return True
        except Exception:
            return False


def _get(path: str, host: str = DEFAULT_HOST) -> dict:
    req = urllib.request.Request(f"{host}/api/v1/{path}")
    req.add_header("accept", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _post(path: str, payload: dict, host: str = DEFAULT_HOST) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{host}/api/v1/{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def list_flows(host: str = DEFAULT_HOST) -> list[dict]:
    """Retourne la liste des flows disponibles [{id, name, description}]."""
    return _get("flows", host=host).get("flows", [])


def create_flow(flow_json: dict | str, host: str = DEFAULT_HOST) -> str:
    """Crée un flow depuis une définition JSON. Retourne le flow_id."""
    if isinstance(flow_json, str):
        flow_json = json.loads(flow_json)
    resp = _post("flows", flow_json, host=host)
    return resp.get("id", "")


def run_flow(flow_id: str, inputs: dict, host: str = DEFAULT_HOST) -> dict:
    """
    Exécute un flow avec des inputs. Retourne le résultat.
    inputs = {"input_value": "...", "tweaks": {...}}
    """
    return _post(f"run/{flow_id}", inputs, host=host)


def export_flow(flow_id: str, dest: str | Path, host: str = DEFAULT_HOST) -> Path:
    """Exporte un flow en JSON vers dest."""
    flow = _get(f"flows/{flow_id}", host=host)
    out = Path(dest)
    out.write_text(json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# ponytail: wrapper mince — Langflow gère UI+persistance. On appelle, on n'invente pas.
if __name__ == "__main__":
    up_status = status()
    print(f"langflow: service {'UP' if up_status else 'DOWN'} @ {DEFAULT_HOST}")
    if up_status:
        flows = list_flows()
        print(f"flows disponibles: {len(flows)}")
    print(f"deploy: docker run -p {DEFAULT_PORT}:7860 {DOCKER_IMAGE}")
