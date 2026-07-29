"""n8n_bridge — client API n8n (self-hosted community, 00_CORE/n8n/).

n8n = plateforme unique pour tout workflow / agent / automation de la Forge.
Ce module rend chaque workflow :
  - ÉDITABLE   : export/import JSON versionné git (00_CORE/n8n/workflows/)
                 + édition visuelle dans l'éditeur n8n (localhost:5678)
  - OBSERVABLE : pull des exécutions (statut, durée, nodes) → forge_metrics

Env : N8N_BASE_URL (défaut http://localhost:5678), N8N_API_KEY
      (Settings → n8n API → create key, puis dans .env — jamais en clair).

Usage :
    from forge_agents.n8n_bridge import N8nBridge
    n8n = N8nBridge()
    n8n.list_workflows()
    n8n.import_dir()                  # pousse 00_CORE/n8n/workflows/*.json
    n8n.export_dir()                  # tire les workflows n8n → git
    n8n.sync_executions_to_metrics()  # exécutions n8n → forge_metrics.jsonl
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

if __package__ in (None, ""):  # lancé comme script → rendre 00_CORE importable
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from forge_agents.forge_metrics import record
import logging
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = _ROOT / "00_CORE" / "n8n" / "workflows"


def SYNC_STATE() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("n8n_sync_state.json")


def _hydrate_env() -> None:
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class N8nBridge:
    def __init__(self, base_url: str = "", api_key: str = ""):
        _hydrate_env()
        self.base_url = (base_url or os.environ.get("N8N_BASE_URL",
                         "http://localhost:5678")).rstrip("/")
        self.api_key = api_key or os.environ.get("N8N_API_KEY", "")

    # ------------------------------------------------------------- HTTP core

    def _req(self, method: str, path: str, **kw) -> Any:
        headers = {"X-N8N-API-KEY": self.api_key,
                   "Content-Type": "application/json"}
        r = requests.request(method, f"{self.base_url}/api/v1{path}",
                             headers=headers, timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.text else {}

    def ping(self) -> bool:
        try:
            requests.get(f"{self.base_url}/healthz", timeout=5).raise_for_status()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ workflows

    def list_workflows(self) -> list[dict]:
        return self._req("GET", "/workflows").get("data", [])

    def get_workflow(self, wf_id: str) -> dict:
        return self._req("GET", f"/workflows/{wf_id}")

    def create_workflow(self, spec: dict) -> dict:
        clean = {k: spec[k] for k in ("name", "nodes", "connections", "settings")
                 if k in spec}
        clean.setdefault("settings", {})
        return self._req("POST", "/workflows", json=clean)

    def update_workflow(self, wf_id: str, spec: dict) -> dict:
        clean = {k: spec[k] for k in ("name", "nodes", "connections", "settings")
                 if k in spec}
        return self._req("PUT", f"/workflows/{wf_id}", json=clean)

    def activate(self, wf_id: str, active: bool = True) -> dict:
        action = "activate" if active else "deactivate"
        return self._req("POST", f"/workflows/{wf_id}/{action}")

    def trigger_webhook(self, webhook_path: str, payload: dict,
                        test: bool = False) -> Any:
        prefix = "webhook-test" if test else "webhook"
        r = requests.post(f"{self.base_url}/{prefix}/{webhook_path}",
                          json=payload, timeout=300)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return r.text

    # ------------------------------------------- git-versioned export/import

    @staticmethod
    def _slug(name: str) -> str:
        import unicodedata
        ascii_name = (unicodedata.normalize("NFKD", name)
                      .encode("ascii", "ignore").decode())
        slug = "".join(c if c.isalnum() else "_" for c in ascii_name.lower())
        while "__" in slug:
            slug = slug.replace("__", "_")
        return slug.strip("_") or "workflow"

    def _existing_paths_by_name(self, out_dir: Path) -> dict[str, Path]:
        """Fichiers déjà présents, indexés par le `name` qu'ils contiennent."""
        mapping: dict[str, Path] = {}
        for path in out_dir.glob("*.json"):
            try:
                name = json.loads(path.read_text(encoding="utf-8")).get("name")
            except Exception:
                continue
            if name:
                mapping[name] = path
        return mapping

    def export_dir(self, out_dir: Path = WORKFLOWS_DIR) -> list[str]:
        """n8n → git : chaque workflow en JSON diffable (édition traçable).

        Réutilise le fichier existant qui porte déjà ce `name` — sinon un
        aller-retour export/import créerait un doublon à chaque passage.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = self._existing_paths_by_name(out_dir)
        written = []
        for wf in self.list_workflows():
            full = self.get_workflow(wf["id"])
            path = existing.get(wf["name"]) or out_dir / f"{self._slug(wf['name'])}.json"
            keep = {k: full.get(k) for k in
                    ("name", "nodes", "connections", "settings")}
            path.write_text(json.dumps(keep, indent=2, ensure_ascii=False),
                            encoding="utf-8")
            written.append(str(path))
        return written

    def import_dir(self, src_dir: Path = WORKFLOWS_DIR) -> list[dict]:
        """git → n8n : crée ou met à jour (match par nom)."""
        existing = {w["name"]: w["id"] for w in self.list_workflows()}
        results = []
        for path in sorted(src_dir.glob("*.json")):
            spec = json.loads(path.read_text(encoding="utf-8"))
            name = spec.get("name", path.stem)
            if name in existing:
                res = self.update_workflow(existing[name], spec)
                results.append({"name": name, "action": "updated",
                                "id": existing[name]})
            else:
                res = self.create_workflow(spec)
                results.append({"name": name, "action": "created",
                                "id": res.get("id")})
        return results

    # ------------------------------------------------- executions → metrics

    def list_executions(self, limit: int = 50,
                        status: Optional[str] = None) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "includeData": "false"}
        if status:
            params["status"] = status
        return self._req("GET", "/executions", params=params).get("data", [])

    def sync_executions_to_metrics(self, limit: int = 100) -> int:
        """Chaque exécution n8n → un record forge_metrics (latence, statut).

        Idempotent : mémorise le dernier id synchronisé dans 05_STATE.
        Les tokens LLM sont déjà émis par le gateway au moment de l'appel ;
        ici on capture le niveau WORKFLOW (durée bout-en-bout, échecs).
        """
        seen: set[str] = set()
        if SYNC_STATE().exists():
            try:
                seen = set(json.loads(SYNC_STATE().read_text(encoding="utf-8"))
                           .get("execution_ids", []))
            except Exception:
                seen = set()
        synced = 0
        for ex in self.list_executions(limit=limit):
            ex_id = str(ex.get("id"))
            if ex_id in seen:
                continue
            started, stopped = ex.get("startedAt"), ex.get("stoppedAt")
            latency_ms = 0
            if started and stopped:
                from datetime import datetime
                fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
                try:
                    latency_ms = int((datetime.strptime(stopped, fmt)
                                      - datetime.strptime(started, fmt))
                                     .total_seconds() * 1000)
                except ValueError as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            record(
                kind="workflow",
                workflow=f"n8n:{ex.get('workflowId', '?')}",
                agent="n8n_execution",
                node=str(ex.get("mode", "")),
                latency_ms=latency_ms,
                ok=ex.get("status") in ("success", None),
                error="" if ex.get("status") in ("success", None)
                      else str(ex.get("status")),
                meta={"execution_id": ex_id,
                      "workflow_name": ex.get("workflowName", "")},
            )
            seen.add(ex_id)
            synced += 1
        SYNC_STATE().parent.mkdir(parents=True, exist_ok=True)
        SYNC_STATE().write_text(
            json.dumps({"execution_ids": sorted(seen)[-2000:]}),
            encoding="utf-8")
        return synced


if __name__ == "__main__":
    import sys
    n8n = N8nBridge()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(f"n8n up: {n8n.ping()} @ {n8n.base_url}")
        if n8n.api_key:
            for w in n8n.list_workflows():
                print(f"  [{w['id']}] {'ON ' if w.get('active') else 'off'} {w['name']}")
    elif cmd == "export":
        for p in n8n.export_dir():
            print(f"  écrit {p}")
    elif cmd == "import":
        for r in n8n.import_dir():
            print(f"  {r['action']:8} {r['name']}  (id={r['id']})")
    elif cmd == "sync":
        print(f"  {n8n.sync_executions_to_metrics()} exécution(s) → forge_metrics")
    else:
        print(f"Commande inconnue : {cmd} "
              f"(status | import | export | sync)")
