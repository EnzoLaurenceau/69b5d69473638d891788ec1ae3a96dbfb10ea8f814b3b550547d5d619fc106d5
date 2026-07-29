"""smoke_run.py — Phase 1 : preuve de bout en bout de la plateforme d'inférence locale.

Boucle vérifiée : auth Bearer → POST /v1/agents/run → WS /v1/stream (live) →
GET /v1/runs/{id} (terminé) → GET /v1/metrics. C'est le critère d'acceptation
central de la Phase 1 (cf. PLAN_PLATEFORME_INFERENCE.md).

Prérequis : `python scripts/seed_local.py` (une fois), puis l'API démarrée
(`docker compose -f docker-compose.local.yml up -d` ou `python 09_WEB/server.py`).

Usage :
    python scripts/smoke_run.py ["tâche optionnelle"]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

FORGE_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = FORGE_ROOT / "05_STATE" / "identity" / ".local_token"
BASE_URL = "http://localhost:7777"
TASK = sys.argv[1] if len(sys.argv) > 1 else "dis bonjour en une phrase"


def _load_token() -> str:
    if not TOKEN_FILE.exists():
        print(f"ERREUR : {TOKEN_FILE} introuvable. Lance d'abord scripts/seed_local.py")
        sys.exit(1)
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


async def _stream_events(run_id: str, headers: dict) -> list[dict]:
    """Se connecte à WS /v1/stream et collecte les events jusqu'à run.done|run.error."""
    try:
        import websockets
    except ImportError:
        print("  (module `websockets` absent — repli sur polling GET /v1/runs)")
        return await _poll_fallback(run_id, headers)

    token = headers["Authorization"].split(" ", 1)[1]
    uri = f"ws://localhost:7777/v1/stream?run_id={run_id}&token={token}"
    events: list[dict] = []
    async with websockets.connect(uri) as ws:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=90)
            ev = json.loads(raw)
            if ev.get("type") == "heartbeat":
                continue
            events.append(ev)
            print(f"  [{ev.get('seq'):>3}] {ev['type']:<20} {json.dumps(ev.get('data', {}))[:100]}")
            if ev["type"] in ("run.done", "run.error"):
                break
    return events


async def _poll_fallback(run_id: str, headers: dict) -> list[dict]:
    async with httpx.AsyncClient() as client:
        for _ in range(60):
            r = await client.get(f"{BASE_URL}/v1/runs/{run_id}", headers=headers)
            snap = r.json()
            if snap["status"] in ("done", "error", "cancelled"):
                return [{"type": f"run.{snap['status']}", "data": snap}]
            await asyncio.sleep(1)
    return []


async def main() -> None:
    token = _load_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        print(f"→ POST /v1/agents/run  task={TASK!r}")
        r = await client.post(f"{BASE_URL}/v1/agents/run", json={"task": TASK}, headers=headers)
        if r.status_code != 202:
            print(f"ÉCHEC : status {r.status_code} — {r.text}")
            sys.exit(1)
        run_id = r.json()["run_id"]
        print(f"  run_id={run_id}")

        print(f"→ WS /v1/stream?run_id={run_id}")
        events = await _stream_events(run_id, headers)

        print("→ GET /v1/runs/{run_id}")
        r = await client.get(f"{BASE_URL}/v1/runs/{run_id}", headers=headers)
        final = r.json()
        print(f"  status final : {final['status']}")

        print("→ GET /v1/metrics")
        r = await client.get(f"{BASE_URL}/v1/metrics", headers=headers)
        print(f"  {r.json()}")

    ok = final["status"] == "done" and any(e["type"] == "run.done" for e in events)
    print("\n✔ SMOKE TEST OK" if ok else "\n✘ SMOKE TEST ÉCHOUÉ")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
