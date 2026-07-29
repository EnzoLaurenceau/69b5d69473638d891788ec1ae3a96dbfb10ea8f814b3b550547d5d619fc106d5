"""seed_local.py — Phase 1 : provisionne le tenant `local` pour les tests en boucle.

Crée (ou fait pivoter) un jeton réel via `forge_identity`, plutôt que de s'appuyer
uniquement sur le repli `FORGE_SINGLE_TENANT` — ça exerce le même chemin d'auth Bearer
que la Phase 3 (multi-tenant), donc le smoke test de la Phase 1 est déjà représentatif.

Usage :
    python scripts/seed_local.py
    → écrit le jeton dans 05_STATE/identity/.local_token (gitignoré) et l'affiche.
"""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

TOKEN_FILE = FORGE_ROOT / "05_STATE" / "identity" / ".local_token"
TENANT_ID = "local"


def main() -> None:
    from forge_agents.forge_identity import create_tenant, rotate_token
    from forge_agents.forge_tenant import TenantError

    try:
        token = create_tenant(TENANT_ID, label="Phase 1 — seed local")
        print(f"tenant '{TENANT_ID}' créé.")
    except TenantError:
        token = rotate_token(TENANT_ID)
        print(f"tenant '{TENANT_ID}' existait déjà — jeton régénéré.")

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    print(f"jeton écrit dans {TOKEN_FILE}")
    print(f"TOKEN={token}")


if __name__ == "__main__":
    main()
