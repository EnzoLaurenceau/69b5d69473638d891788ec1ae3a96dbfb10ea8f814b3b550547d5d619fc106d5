"""see_edit.py — point d'entrée unique du Semantic Edit Engine (MCPT).

Câble ce qui était orphelin : optimizer (plan de coût minimal) → application
transactionnelle (rollback auto si le fichier ne compile plus) → métriques
(`05_STATE/forge_metrics.jsonl`).

Python :
    from tools.see_edit import apply_minimal_edit
    res = apply_minimal_edit("blog/models.py", "ajoute un check is_active",
                             modified_code=code_cible, dry_run=True)
    print(res["strategy"], res["token_savings_pct"], res["ops"])

CLI :
    python 00_CORE/tools/see_edit.py <fichier> --target <symbole> --new <fichier_cible> [--apply]
    python 00_CORE/tools/see_edit.py <fichier> --instruction "..." [--apply]

Sans `--apply` → dry-run : on montre le plan gagnant et l'économie, on ne touche à rien.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_CORE = Path(__file__).resolve().parent.parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from forge_agents.semantic_edit_engine.patch_optimizer import get_patch_optimizer  # noqa: E402
from forge_agents.semantic_edit_engine.edit_metrics import record_edit  # noqa: E402
from forge_agents.semantic_edit_engine.edit_pipeline import run_edit  # noqa: E402


def plan_minimal_edit(
    file_path: str | Path,
    instruction: str = "",
    target_name: str | None = None,
    modified_code: str | None = None,
) -> dict | None:
    """Calcule le plan d'édition de coût minimal. N'écrit rien.

    Retourne None si le fichier est absent, la cible introuvable, ou si aucun
    plan ne reproduit exactement la transformation demandée.
    """
    t0 = time.perf_counter()
    cand = get_patch_optimizer().optimize(instruction, Path(file_path), target_name, modified_code)
    if cand is None:
        return None
    metrics = record_edit(cand, latency_ms=int((time.perf_counter() - t0) * 1000))
    out = cand.to_dict()
    out["token_savings_pct"] = metrics.token_savings
    out["diff"] = cand.diff
    out["_candidate"] = cand
    return out


def apply_minimal_edit(
    file_path: str | Path,
    instruction: str = "",
    target_name: str | None = None,
    modified_code: str | None = None,
    dry_run: bool = True,
    test_cmd: str | None = None,
    force: bool = False,
) -> dict | None:
    """Boucle complète : plan → gate impact → revue → application → tests.

    Délègue à `edit_pipeline.run_edit`. Tout gate bloquant arrête la chaîne ; toute
    étape indisponible est reportée dans `gates_skipped` et n'arrête rien.
    `force=True` passe outre les gates bloquants (le forçage reste tracé).
    """
    res = run_edit(
        file_path,
        instruction=instruction,
        target_name=target_name,
        modified_code=modified_code,
        apply=not dry_run,
        test_cmd=test_cmd,
        force=force,
    )
    if res.status == "no_plan":
        return None
    out = res.to_dict()
    out["applied"] = res.status == "applied"
    return out


def _main() -> int:
    ap = argparse.ArgumentParser(description="Semantic Edit Engine — édition de coût minimal")
    ap.add_argument("file", help="fichier à éditer")
    ap.add_argument("--target", default=None, help="symbole visé (fonction/classe)")
    ap.add_argument("--instruction", default="", help="intention en langage naturel")
    ap.add_argument("--new", default=None, help="fichier contenant le code cible (mode 0 token)")
    ap.add_argument("--apply", action="store_true", help="applique réellement (sinon dry-run)")
    ap.add_argument("--test", default=None, help="commande de test — rollback auto si rouge")
    ap.add_argument("--force", action="store_true", help="passe outre les gates bloquants (tracé)")
    args = ap.parse_args()

    modified = Path(args.new).read_text(encoding="utf-8") if args.new else None
    res = apply_minimal_edit(
        args.file,
        args.instruction,
        args.target,
        modified,
        dry_run=not args.apply,
        test_cmd=args.test,
        force=args.force,
    )
    if res is None:
        print("Aucun plan d'édition — fichier absent, cible identique, ou transformation non dérivable.")
        return 1
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(_main())
