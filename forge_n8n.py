#!/usr/bin/env python3
"""
forge_n8n.py — point d'entrée n8n / observabilité (même convention que run_forge.py)
====================================================================================
Usage (depuis la racine de la Forge) :
  python forge_n8n.py status     # n8n joignable ? + liste des workflows
  python forge_n8n.py import     # 00_CORE/n8n/workflows/*.json  →  n8n
  python forge_n8n.py export     # n8n  →  00_CORE/n8n/workflows/*.json (git)
  python forge_n8n.py sync       # exécutions n8n → 05_STATE/forge_metrics.jsonl
  python forge_n8n.py metrics    # table d'agrégats (tokens, latence, hallucination)
  python forge_n8n.py gateway    # démarre le gateway FastAPI sur :7788

Pré-requis : N8N_API_KEY dans le .env racine (Settings → n8n API dans l'UI).
"""

import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent
sys.path.insert(0, str(FORGE_ROOT))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

# Console Windows cp1252 → UTF-8 (tables/accents)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

USAGE = __doc__


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    if cmd == "metrics":
        from forge_agents.forge_metrics import render_summary_table
        print(render_summary_table())
        return 0

    if cmd == "gateway":
        import uvicorn
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "n8n"))
        from forge_gateway import app
        print("Gateway Forge → http://127.0.0.1:7788  (Ctrl+C pour arrêter)")
        uvicorn.run(app, host="127.0.0.1", port=7788)
        return 0

    from forge_agents.n8n_bridge import N8nBridge
    n8n = N8nBridge()

    if cmd == "status":
        up = n8n.ping()
        print(f"n8n : {'UP' if up else 'DOWN'} @ {n8n.base_url}")
        if not up:
            print("  → docker compose -f 00_CORE/n8n/docker-compose.yml up -d")
            return 1
        if not n8n.api_key:
            print("  ⚠ N8N_API_KEY absente du .env — API publique inaccessible.")
            print("    UI localhost:5678 → Settings → n8n API → créer une clé.")
            return 1
        try:
            wfs = n8n.list_workflows()
        except Exception as e:
            print(f"  ⚠ API injoignable ({e}). Compte owner créé dans l'UI ?")
            return 1
        print(f"  {len(wfs)} workflow(s) :")
        for w in wfs:
            print(f"   [{w['id']}] {'ON ' if w.get('active') else 'off'} {w['name']}")
        return 0

    if cmd == "import":
        for r in n8n.import_dir():
            print(f"  {r['action']:8} {r['name']}  (id={r['id']})")
        return 0

    if cmd == "export":
        for p in n8n.export_dir():
            print(f"  écrit {p}")
        return 0

    if cmd == "sync":
        print(f"  {n8n.sync_executions_to_metrics()} exécution(s) → forge_metrics")
        return 0

    print(f"Commande inconnue : {cmd}\n")
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
