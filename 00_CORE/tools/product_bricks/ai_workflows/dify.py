"""
dify.py — Wrapper Dify (github.com/langgenius/dify)
===================================================
Plateforme d'apps LLM complète (UI, agents, RAG, back-office).
Docker requis.

Usage :
    from tools.product_bricks.ai_workflows import dify
    dify.deploy(project_path)                                 # télécharge le compose officiel
    dify.up(project_path)                                     # docker compose up
    ok = dify.status()                                        # True si service répond
    res = dify.call_agent(api_key, query, user_id)            # appelle l'API Dify
"""

from __future__ import annotations
import json, os, subprocess
from pathlib import Path
import urllib.request
import httpx
from ....forge_agents.forge_db import get_db

REPO_COMPOSE_URL = "https://raw.githubusercontent.com/langgenius/dify/main/docker/docker-compose.yaml"
DEFAULT_PORT = int(os.environ.get("DIFY_PORT", 8080))
DEFAULT_HOST = os.environ.get("DIFY_HOST", f"http://localhost:{DEFAULT_PORT}")


def deploy(project_path: str | Path) -> Path:
    """Télécharge le compose de Dify dans project_path."""
    out_dir = Path(project_path) / "dify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "docker-compose.yml"
    
    # Download Dify compose config
    print(f"dify: downloading official docker-compose → {out}")
    urllib.request.urlretrieve(REPO_COMPOSE_URL, str(out))
    
    # Write environment template for Dify setup
    env_file = out_dir / ".env"
    env_content = f"""# Dify .env
EXPOSE_PORT={DEFAULT_PORT}
API_PORT=5001
WEB_PORT=3000
DB_USERNAME=postgres
DB_PASSWORD=dify_postgres_pass
DB_DATABASE=dify
REDIS_PASSWORD=dify_redis_pass
"""
    env_file.write_text(env_content, encoding="utf-8")
    
    # Cache Dify deployment meta in unified Forge DB
    db = get_db()
    db.hot_set("dify_deployment_status", "deployed")
    db.hot_set("dify_deployment_path", str(out_dir))
    
    return out


def up(project_path: str | Path) -> None:
    """docker compose up -d (lance le service Dify)."""
    cf = Path(project_path) / "dify" / "docker-compose.yml"
    if not cf.exists():
        deploy(project_path)
    subprocess.run(["docker", "compose", "-f", str(cf), "up", "-d"], check=True)
    print(f"dify: UP → {DEFAULT_HOST}")
    
    db = get_db()
    db.hot_set("dify_deployment_status", "running")


def status(host: str = DEFAULT_HOST) -> bool:
    """True si Dify répond."""
    try:
        # Check standard check URL or console landing
        urllib.request.urlopen(f"{host}/console/api/setup", timeout=3)
        return True
    except Exception:
        # Fallback to general connection check
        try:
            urllib.request.urlopen(host, timeout=3)
            return True
        except Exception:
            return False


async def call_agent(api_key: str, query: str, user_id: str = "forge_user", host: str = DEFAULT_HOST) -> dict:
    """
    Appelle un agent configuré sur Dify via son endpoint d'API.
    A2A Compatible.
    """
    url = f"{host}/v1/chat-messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "user": user_id
    }
    
    # Query using httpx (supporting async db pipelines)
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=payload, headers=headers, timeout=30.0)
        res.raise_for_status()
        data = res.json()
        
    # Store event in Unified DB (deep table episodes)
    db = get_db()
    db.deep_insert("episodes", {
        "signal": f"DIFY_CALL|user={user_id}",
        "res": data.get("answer", "")[:200],
        "meta": {"query": query, "response": data},
        "ts": os.path.getmtime(__file__) if os.path.exists(__file__) else 0.0
    })
    
    return data
