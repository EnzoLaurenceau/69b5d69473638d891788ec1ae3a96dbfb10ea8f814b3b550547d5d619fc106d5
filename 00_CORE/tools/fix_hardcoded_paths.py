"""fix_hardcoded_paths.py — supprime les chemins absolus utilisateur du code.

POURQUOI
--------
17 occurrences de `C:\\Users\\<user>\\Documents\\MODELS\\.claude` en dur. Double problème
pour un produit shippable :
  - **portabilité** : le code ne tourne que sur une machine ;
  - **confidentialité** : le nom d'utilisateur fuite dans le dépôt.

LE FIX
------
    FORGE_ROOT = Path(r"C:\\Users\\X\\Documents\\MODELS\\.claude")
      →  FORGE_ROOT = Path(__file__).resolve().parents[N]

    FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", r"C:\\...\\.claude"))
      →  FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[N]))

`N` = profondeur du fichier dans le dépôt, calculée, jamais devinée. Le repli par variable
d'environnement est préservé quand il existe. Les sous-chemins (`…\\.claude\\05_STATE\\x.json`)
sont reconstruits en `/ "05_STATE" / "x.json"`.

HORS PÉRIMÈTRE
--------------
Un chemin absolu pointant HORS du dépôt (autre projet) n'est pas dérivable de `__file__` :
il est signalé, jamais réécrit en silence.

CLI :
    python 00_CORE/tools/fix_hardcoded_paths.py            # dry-run
    python 00_CORE/tools/fix_hardcoded_paths.py --apply
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
_CORE = str(FORGE_ROOT / "00_CORE")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

# Chemin absolu Windows vers la racine du dépôt, avec sous-chemin optionnel.
_ABS = re.compile(
    r'r?"(?P<full>[A-Za-z]:\\\\?Users\\\\?[^"\\]+\\\\?Documents\\\\?MODELS\\\\?\.claude(?P<rest>(?:\\\\?[^"]*)?))"'
)
_ROOT_TAIL = re.compile(r"(?i)[A-Za-z]:\\Users\\[^\\]+\\Documents\\MODELS\\\.claude")
#: une vraie assignation de code utilisant Path(...) — exclut docstrings et commentaires
_CODE_ASSIGN = re.compile(r"^\s*[A-Za-z_][\w.]*\s*(?::[^=]+)?=\s*.*Path\(")
#: l'outil ne se réécrit pas lui-même (sa doc cite le motif qu'il traque)
_SELF = Path(__file__).name


def _depth(rel: Path) -> int:
    """Nombre de `parents` à remonter depuis le fichier pour atteindre la racine."""
    return len(rel.parts) - 1


def _expr_for(rel: Path, rest: str) -> str:
    """Expression Python remplaçant le littéral, sous-chemin inclus."""
    base = f"Path(__file__).resolve().parents[{_depth(rel)}]"
    parts = [p for p in rest.replace("\\\\", "\\").split("\\") if p]
    for p in parts:
        base += f' / "{p}"'
    return base


def build_fixed(rel: Path, text: str) -> tuple[str, int, list]:
    """Retourne (contenu corrigé, nb de remplacements, chemins hors dépôt signalés)."""
    outside: list = []
    fixed = 0
    lines = text.splitlines(keepends=True)

    for i, line in enumerate(lines):
        # N'agir QUE sur une vraie ligne de code (assignation utilisant Path(...)).
        # Sans ce filtre, l'outil réécrit les docstrings et commentaires qui citent un
        # chemin en exemple — y compris les siens.
        if not _CODE_ASSIGN.match(line):
            if re.search(r"(?i)[A-Za-z]:\\\\?Users\\\\?[A-Za-z]+", line) and not line.lstrip().startswith("#"):
                outside.append(f"{rel.as_posix()}:{i+1}: {line.strip()[:100]} [non-code]")
            continue
        if not _ROOT_TAIL.search(line.replace("\\\\", "\\")):
            # chemin absolu utilisateur mais PAS vers ce dépôt → hors périmètre
            if re.search(r"(?i)[A-Za-z]:\\\\?Users\\\\?[A-Za-z]+", line):
                outside.append(f"{rel.as_posix()}:{i+1}: {line.strip()[:100]}")
            continue

        m = _ABS.search(line)
        if not m:
            outside.append(f"{rel.as_posix()}:{i+1}: {line.strip()[:100]}")
            continue

        expr = _expr_for(rel, m.group("rest") or "")
        new_line = line[: m.start()] + expr + line[m.end():]
        # `Path(<expr>)` deviendrait redondant : Path(Path(...)) → on aplatit
        new_line = re.sub(r"Path\(\s*(Path\(__file__\)\.resolve\(\)\.parents\[\d+\][^)]*)\)",
                          r"\1", new_line)
        lines[i] = new_line
        fixed += 1

    return "".join(lines), fixed, outside


def scan() -> list:
    from forge_agents.tech_debt import collect_files
    out = []
    for abs_p, rel, _z in collect_files(include_vendored=False):
        if abs_p.suffix.lower() != ".py" or abs_p.name == _SELF:
            continue
        try:
            text = abs_p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not re.search(r"(?i)[A-Za-z]:\\\\?Users\\\\?[A-Za-z]+", text):
            continue
        new, n, outside = build_fixed(rel, text)
        out.append({"file": rel.as_posix(), "fixed": n, "outside": outside,
                    "content": new, "changed": new != text})
    return out


def run(apply: bool = False) -> dict:
    from forge_agents.semantic_edit_engine.edit_pipeline import run_edit

    results, skipped = [], []
    for c in scan():
        if not c["changed"]:
            skipped.extend(c["outside"])
            continue
        try:
            ast.parse(c["content"])
        except SyntaxError as exc:
            results.append({"file": c["file"], "fixed": c["fixed"],
                            "status": "generation_invalide", "reason": str(exc)})
            continue
        res = run_edit(FORGE_ROOT / c["file"], modified_code=c["content"], apply=apply)
        results.append({"file": c["file"], "fixed": c["fixed"], "status": res.status,
                        "strategy": res.strategy, "emit_cost": res.emit_cost,
                        "reason": res.reason})
        skipped.extend(c["outside"])
    return {"applied": apply, "results": results,
            "total_fixed": sum(r["fixed"] for r in results),
            "outside_repo": skipped}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Supprime les chemins absolus utilisateur")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rep = run(args.apply)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    print(f"{'APPLIQUÉ' if args.apply else 'DRY-RUN'} — "
          f"{len(rep['results'])} fichier(s), {rep['total_fixed']} chemin(s) dérivés")
    print(f"{'statut':<18}{'n':>3}{'strat':>10}{'emit':>7}  fichier")
    for r in rep["results"]:
        print(f"{r['status']:<18}{r['fixed']:>3}{r.get('strategy',''):>10}"
              f"{r.get('emit_cost',0):>7}  {r['file']}")
        if r.get("reason"):
            print(f"{'':<18}↳ {r['reason'][:95]}")
    if rep["outside_repo"]:
        print(f"\nHORS DÉPÔT — à traiter à la main ({len(rep['outside_repo'])}) :")
        for o in rep["outside_repo"][:10]:
            print("  ", o)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
