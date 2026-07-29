"""
evomap_evolve.py — Pont LOCAL-ONLY vers evomap `evolver` (auto-amélioration).
================================================================================
Objectif : capturer les apprentissages d'une session en Genes/Capsules locales
réutilisables (le but "apprendre à mieux coder" demandé), SANS la couche réseau
de evomap.

Garde-fous (volontaires, non négociables ici) :
  • SOUS-PROCESS uniquement → jamais `import evolver` → la licence GPL-3.0
    reste à distance (agrégation, pas œuvre dérivée).
  • EVOLVER_VALIDATOR_ENABLED=0 → désactive le rôle validateur réseau
    (ON par défaut côté evolver depuis v1.69.0).
  • Sous-commandes autorisées : solidify / review / distill UNIQUEMENT.
    JAMAIS login / sync / recipe --publish / buy / atp / setup-hooks
    (= upload de stratégies, marché à crédits, hooks injectés).

Pré-requis pour que ce module fasse autre chose qu'un no-op :
  1. evolver disponible — soit `npm i -g @evomap/evolver` (binaire sur le PATH),
     soit pointer EVOLVER_BIN vers son index.js (ex: install locale temporaire).
  2. cwd doit être un dépôt git (evolver l'exige). La Forge n'est pas un repo git
     par défaut → `git init` la racine, ou passer cwd=<un repo>.

Si l'une manque → retourne {"ok": False, "skipped": "..."} proprement (jamais
d'exception qui casserait le graph).

Activation dans le graph : variable d'env FORGE_EVOLVE=1 (lue par post_mortem_node).
CLI : `python run_forge.py --evolve`  (ou `--task ... --evolve`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]  # ...\.claude

# Sous-commandes locales autorisées. Tout le reste est réseau/commerce → interdit.
ALLOWED = frozenset({"solidify", "review", "distill"})


def _evolver_cmd() -> list[str] | None:
    """Résout la commande de base evolver, ou None si introuvable."""
    # 1) override explicite : EVOLVER_BIN = chemin du binaire ou de index.js
    override = os.environ.get("EVOLVER_BIN")
    if override and Path(override).exists():
        return ["node", override] if override.endswith(".js") else [override]
    # 2) binaire global sur le PATH
    found = shutil.which("evolver")
    return [found] if found else None


def is_available() -> bool:
    return _evolver_cmd() is not None


def evolve(
    subcommand: str = "solidify",
    intent: str = "optimize",
    cwd: str | None = None,
    dry_run: bool = False,
    timeout: int = 180,
) -> dict:
    """
    Lance `evolver <subcommand>` en local, validateur réseau désactivé.

    Retourne un dict structuré (jamais d'exception propagée) :
      {"ok": bool, "stdout"?: str, "stderr"?: str, "code"?: int,
       "skipped"?: str, "error"?: str}
    """
    if subcommand not in ALLOWED:
        return {"ok": False, "error": f"subcommand '{subcommand}' interdite (réseau/commerce). Autorisé: {sorted(ALLOWED)}"}

    base = _evolver_cmd()
    if base is None:
        return {"ok": False, "skipped": "evolver introuvable (npm i -g @evomap/evolver, ou EVOLVER_BIN=<...index.js>)"}

    work = cwd or str(FORGE_ROOT)
    if not (Path(work) / ".git").exists():
        return {"ok": False, "skipped": f"cwd n'est pas un repo git ({work}) — evolver l'exige. `git init` ou passer cwd."}

    cmd = base + [subcommand]
    if subcommand == "solidify":
        cmd.append(f"--intent={intent}")
        if dry_run:
            cmd.append("--dry-run")

    # Couche réseau coupée : validateur OFF + aucune sous-commande réseau ici.
    env = dict(os.environ)
    env["EVOLVER_VALIDATOR_ENABLED"] = "0"

    try:
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True,
                           text=True, timeout=timeout)
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": (p.stdout or "")[-2000:],
            "stderr": (p.stderr or "")[-1000:],
        }
    except FileNotFoundError:
        return {"ok": False, "skipped": "evolver/node introuvable à l'exécution"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout après {timeout}s"}
    except Exception as e:  # garde-fou : ne jamais casser le graph
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import json
    import sys

    sub = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "solidify"
    print(json.dumps(evolve(subcommand=sub, dry_run="--dry-run" in sys.argv), indent=2, ensure_ascii=False))
