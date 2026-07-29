"""
twenty_crm.py — Wrapper réutilisable pour Twenty CRM (open-source, self-host).
================================================================================
Outil Forge : provisionne un CRM PRÉCIS par projet qui en a besoin.
Twenty = alternative open-source à Salesforce. Stack TS/NestJS/React/GraphQL/PG.
Self-host via Docker Compose. API GraphQL → objets/champs custom = CRM sur mesure.

⚠️ LICENCE : AGPL-3.0-or-later (copyleft réseau) + fichiers `@license Enterprise`
  (licence commerciale). Pour VENDRE/héberger un CRM client : autorisé sous AGPL
  MAIS (1) offrir le source modifié aux utilisateurs du service ; (2) NE PAS livrer
  les fichiers Enterprise sans licence commerciale Twenty. Cf. TOOLS.md.

Tout en SOUS-PROCESS (docker) + HTTP (GraphQL). Aucune exception propagée
(retourne toujours un dict {ok, ...}) → ne casse jamais le pipeline.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]          # ...\.claude
MVP_OUT = FORGE_ROOT / "mvp_output"
_RAW = "https://raw.githubusercontent.com/twentyhq/twenty/main/packages/twenty-docker"
COMPOSE_URL = f"{_RAW}/docker-compose.yml"
ENV_URL = f"{_RAW}/.env.example"


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "forge"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _project_name(project: str) -> str:
    return "forge_" + re.sub(r"[^a-z0-9_]+", "_", project.lower()).strip("_") + "_crm"


def prepare(project: str, port: int = 3000) -> dict:
    """Crée mvp_output/<project>/crm/ avec le compose + .env Twenty officiels."""
    crm = MVP_OUT / project / "crm"
    crm.mkdir(parents=True, exist_ok=True)
    try:
        (crm / "docker-compose.yml").write_text(_fetch(COMPOSE_URL), encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"fetch compose: {e}", "dir": str(crm),
                "hint": "voir docs.twenty.com/developers/self-host"}
    try:
        env = _fetch(ENV_URL)
    except Exception:
        env = "# remplir selon docs.twenty.com self-host\n"
    env = re.sub(r"(?m)^SERVER_URL=.*$", f"SERVER_URL=http://localhost:{port}", env)
    if "APP_SECRET" not in env:
        env += f"\nAPP_SECRET={os.urandom(24).hex()}\n"
    (crm / ".env").write_text(env, encoding="utf-8")
    return {"ok": True, "dir": str(crm), "port": port, "project": _project_name(project),
            "next": f'docker compose -p {_project_name(project)} --env-file .env up -d  (dans {crm})'}


def up(project: str, timeout: int = 600) -> dict:
    if not docker_available():
        return {"ok": False, "skipped": "docker introuvable (installer Docker Desktop)"}
    crm = MVP_OUT / project / "crm"
    if not (crm / "docker-compose.yml").exists():
        return {"ok": False, "error": "non préparé — appelle prepare() d'abord"}
    try:
        p = subprocess.run(["docker", "compose", "-p", _project_name(project), "--env-file", ".env", "up", "-d"],
                           cwd=str(crm), capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "code": p.returncode,
                "stdout": (p.stdout or "")[-1500:], "stderr": (p.stderr or "")[-1200:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def down(project: str) -> dict:
    crm = MVP_OUT / project / "crm"
    try:
        p = subprocess.run(["docker", "compose", "-p", _project_name(project), "down"],
                           cwd=str(crm), capture_output=True, text=True, timeout=180)
        return {"ok": p.returncode == 0, "stdout": (p.stdout or "")[-800:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def graphql(base_url: str, token: str, query: str, variables: dict | None = None, timeout: int = 30) -> dict:
    """Appel GraphQL Twenty (créer objets/champs custom, insérer data, etc.)."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/graphql", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "forge"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read().decode("utf-8", "replace"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def health(base_url: str = "http://localhost:3000") -> dict:
    try:
        req = urllib.request.Request(base_url, headers={"User-Agent": "forge"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": 200 <= r.status < 500, "status": r.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    proj = sys.argv[1] if len(sys.argv) > 1 else "demo"
    print(json.dumps(prepare(proj), indent=2, ensure_ascii=False))
