"""
coolify.py — Wrapper Coolify (github.com/coollabsio/coolify)
============================================================
PaaS self-host (alt. Vercel/Heroku). Déploie en PROD : URL + HTTPS + CI.
Étape DELIVER de tout produit MVP.

Usage :
    from tools.delivery import coolify
    coolify.configure(host="https://coolify.mondomaine.com", token="...")
    projects = coolify.list_projects()
    svc = coolify.deploy_from_git(project_id, repo_url, branch="main")
    coolify.deploy_docker(project_id, compose_path)
    status = coolify.get_status(service_id)
    url = coolify.get_url(service_id)
"""

from __future__ import annotations
import json, os, urllib.request
from pathlib import Path
from typing import Any

_HOST = os.environ.get("COOLIFY_HOST", "")
_TOKEN = os.environ.get("COOLIFY_TOKEN", "")


def configure(host: str, token: str) -> None:
    """Configure l'instance Coolify à appeler (modifie les globals de session)."""
    global _HOST, _TOKEN
    _HOST = host.rstrip("/")
    _TOKEN = token


def _require_config() -> None:
    if not _HOST or not _TOKEN:
        raise RuntimeError(
            "Coolify non configuré. Appelle coolify.configure(host, token) "
            "ou définis COOLIFY_HOST + COOLIFY_TOKEN dans .env"
        )


def _req(method: str, path: str, payload: dict | None = None) -> Any:
    _require_config()
    url = f"{_HOST}/api/v1/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload else None
    headers = {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read()
        return json.loads(body) if body else {}


def list_projects() -> list[dict]:
    """Liste tous les projets Coolify."""
    return _req("GET", "projects")


def list_services(project_id: str) -> list[dict]:
    """Liste les services d'un projet."""
    return _req("GET", f"projects/{project_id}/services")


def deploy_from_git(
    project_id: str,
    repo_url: str,
    branch: str = "main",
    build_pack: str = "nixpacks",
    port: int = 3000,
    environment_id: str | None = None,
) -> dict:
    """
    Crée + déploie une app depuis un repo Git.
    Retourne le service créé (avec service_id et url).
    """
    payload: dict = {
        "project_uuid": project_id,
        "git_repository": repo_url,
        "git_branch": branch,
        "build_pack": build_pack,
        "ports_exposes": str(port),
    }
    if environment_id:
        payload["environment_name"] = environment_id
    return _req("POST", "applications", payload)


def deploy_docker(project_id: str, compose_path: str | Path) -> dict:
    """
    Déploie un docker-compose existant sur Coolify.
    Retourne le service créé.
    """
    content = Path(compose_path).read_text(encoding="utf-8")
    return _req("POST", "services", {
        "project_uuid": project_id,
        "docker_compose_raw": content,
    })


def redeploy(service_id: str) -> dict:
    """Force un redéploiement (équivalent git push → CI)."""
    return _req("POST", f"applications/{service_id}/restart")


def get_status(service_id: str) -> str:
    """Retourne le statut du service : 'running' | 'stopped' | 'building' | …"""
    svc = _req("GET", f"applications/{service_id}")
    return svc.get("status", "unknown")


def get_url(service_id: str) -> str:
    """Retourne l'URL publique (HTTPS) du service."""
    svc = _req("GET", f"applications/{service_id}")
    return svc.get("fqdn", "")


def set_env(service_id: str, key: str, value: str) -> dict:
    """Injecte une variable d'environnement dans un service."""
    return _req("POST", f"applications/{service_id}/envs", {"key": key, "value": value})


def health(host: str = "") -> bool:
    """True si l'instance Coolify répond (pas besoin de token)."""
    target = (host or _HOST).rstrip("/")
    if not target:
        return False
    try:
        urllib.request.urlopen(f"{target}/api/v1/healthcheck", timeout=4)
        return True
    except Exception:
        return False


# ponytail: wrapper HTTP mince. Coolify gère CI, HTTPS, DNS. On délègue, on n'invente pas.
if __name__ == "__main__":
    configured = bool(_HOST and _TOKEN)
    print(f"coolify: {'configuré' if configured else 'non configuré'} @ {_HOST or '(pas de host)'}")
    if configured:
        print(f"health: {health()}")
    print("vars: COOLIFY_HOST + COOLIFY_TOKEN dans .env")
    print("ops: list_projects() deploy_from_git() deploy_docker() get_status() get_url()")
