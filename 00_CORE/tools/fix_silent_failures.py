"""fix_silent_failures.py — rend observables les `except …: pass` (sans changer le flux).

POURQUOI
--------
178 `except: pass` au scan déterministe, 75 findings `silent-failure` au swarm : c'est LA
dette structurante de la Forge. Un échec avalé sans trace contredit frontalement le
positionnement « plateforme d'exécution observable » (POSITIONING.md §6).

LE FIX
------
    except Exception:          →   except Exception as exc:
        pass                           logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

Le contrôle de flux est **identique** : on continue toujours après l'exception. Seule
change l'observabilité. C'est donc un changement à risque quasi nul, et mécaniquement
applicable — le cas d'école du MCPT.

COMMENT
-------
La cible est calculée **déterministement** (AST pour localiser, réécriture LIGNE À LIGNE
pour ne pas reformater le fichier — `ast.unparse` détruirait la propriété d'édition
minimale). Puis `edit_pipeline.run_edit` dérive le plan de coût minimal et traverse les
gates (sûreté sémantique → revue → application transactionnelle → tests → rollback).
Aucun appel LLM : la transformation est connue.

GARDE-FOUS
----------
- Fichier sans `logger` module-level → ignoré (on n'injecte pas d'import à grande échelle).
- `except:` nu (sans type) → ignoré (impossible de lier `as` sans changer la sémantique).
- Un handler dont le corps n'est PAS exactement `pass` → ignoré.

CLI :
    python 00_CORE/tools/fix_silent_failures.py --limit 5              # dry-run
    python 00_CORE/tools/fix_silent_failures.py --files a.py --apply --test "python -m pytest -q"
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

LOG_CALL = 'logger.debug("exception ignorée (%s): %s", type({name}).__name__, {name})'
_LOGGER_DEF = re.compile(r"^\s*logger\s*=", re.M)


def _has_logger(text: str) -> bool:
    return bool(_LOGGER_DEF.search(text))


def ensure_logger(text: str) -> tuple[str, bool]:
    """Injecte `import logging` + `logger = logging.getLogger(__name__)` si absents.

    Point d'insertion calculé par AST, après le DERNIER import de premier niveau : cela
    respecte l'obligation que `from __future__ import …` reste en tête, et évite de se
    glisser dans la docstring de module. Si le fichier n'a aucun import, on insère juste
    après la docstring.
    """
    if _LOGGER_DEF.search(text):
        return text, False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text, False

    lines = text.splitlines(keepends=True)
    last_import_end = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_end = max(last_import_end, getattr(node, "end_lineno", node.lineno))

    if last_import_end == 0:                      # aucun import : après la docstring
        body = list(ast.iter_child_nodes(tree))
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            last_import_end = getattr(body[0], "end_lineno", 1)

    has_logging_import = bool(re.search(r"^\s*import logging\b", text, re.M))
    block = ""
    if not has_logging_import:
        block += "import logging\n"
    block += "\nlogger = logging.getLogger(__name__)\n"

    lines.insert(last_import_end, block)
    return "".join(lines), True


def find_sites(text: str) -> list:
    """Handlers dont le corps est exactement `pass`, avec un type d'exception nommé."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:                      # `except:` nu — on n'y touche pas
            continue
        if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
            continue
        p = node.body[0]
        sites.append({
            "handler_line": node.lineno,
            "pass_line": p.lineno,
            "pass_col": p.col_offset,
            "name": node.name,                     # déjà un `as X` ?
            "oneliner": p.lineno == node.lineno,
        })
    return sorted(sites, key=lambda s: -s["pass_line"])   # bas → haut : indices stables


def build_fixed(text: str, add_logger: bool = False) -> tuple[str, int]:
    """Retourne (contenu corrigé, nb de sites traités). Réécriture ligne à ligne."""
    sites = find_sites(text)
    if not sites:
        return text, 0
    if add_logger and not _has_logger(text):
        text, _injected = ensure_logger(text)
        sites = find_sites(text)          # les lignes ont bougé : relocaliser
    lines = text.splitlines(keepends=True)
    fixed = 0

    for s in sites:
        pi = s["pass_line"] - 1
        if pi >= len(lines):
            continue
        name = s["name"] or "exc"
        call = LOG_CALL.format(name=name)

        if s["oneliner"]:
            # `except X: pass` → `except X as exc: logger.debug(...)`
            line = lines[pi]
            m = re.match(r"^(\s*except\s+)(.+?)(\s*:\s*)pass(\s*)$", line)
            if not m:
                continue
            head, exc_type, colon, tail = m.groups()
            if s["name"] is None:
                exc_type = f"{exc_type.strip()} as {name}"
            lines[pi] = f"{head}{exc_type}{colon}{call}{tail or chr(10)}"
            fixed += 1
            continue

        # forme multi-lignes : remplacer la ligne `pass` en conservant l'indentation
        indent = lines[pi][: len(lines[pi]) - len(lines[pi].lstrip())]
        if lines[pi].strip() != "pass":
            continue
        lines[pi] = f"{indent}{call}\n"
        # lier l'exception si le handler ne le fait pas déjà
        if s["name"] is None:
            hi = s["handler_line"] - 1
            hm = re.match(r"^(\s*except\s+)(.+?)(\s*:\s*)$", lines[hi].rstrip("\n"))
            if hm:
                head, exc_type, colon = hm.groups()
                lines[hi] = f"{head}{exc_type.strip()} as {name}{colon}\n"
            else:
                lines[pi] = f"{indent}logger.debug(\"exception ignorée\")\n"
        fixed += 1

    return "".join(lines), fixed


def candidates(files: list[str] | None = None, limit: int = 0,
               add_logger: bool = False) -> list:
    """Fichiers éligibles, triés par nombre de sites décroissant."""
    if files:
        rels = [Path(f).as_posix() for f in files]
    else:
        from forge_agents.tech_debt import collect_files
        rels = [rel.as_posix() for _a, rel, _z in collect_files(include_vendored=False)
                if rel.suffix == ".py"]

    out = []
    for rel in rels:
        p = FORGE_ROOT / rel
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        sites = find_sites(text)
        if not sites:
            continue
        if not _has_logger(text) and not add_logger:
            out.append({"file": rel, "sites": len(sites), "skip": "pas de logger module-level"})
            continue
        out.append({"file": rel, "sites": len(sites), "skip": ""})
    out.sort(key=lambda c: (bool(c["skip"]), -c["sites"]))
    eligible = [c for c in out if not c["skip"]]
    return (eligible[:limit] if limit else eligible), [c for c in out if c["skip"]]


def run(files: list[str] | None = None, limit: int = 0, apply: bool = False,
        test_cmd: str | None = None, add_logger: bool = False) -> dict:
    from forge_agents.semantic_edit_engine.edit_pipeline import run_edit

    eligible, skipped = candidates(files, limit, add_logger)
    results = []
    for c in eligible:
        p = FORGE_ROOT / c["file"]
        original = p.read_text(encoding="utf-8")
        fixed, n = build_fixed(original, add_logger)
        if n == 0 or fixed == original:
            continue
        # sécurité : le résultat doit parser
        try:
            ast.parse(fixed)
        except SyntaxError as exc:
            results.append({"file": c["file"], "sites": n, "status": "generation_invalide",
                            "reason": str(exc)})
            continue
        res = run_edit(p, modified_code=fixed, apply=apply, test_cmd=test_cmd)
        results.append({
            "file": c["file"], "sites": n, "status": res.status,
            "strategy": res.strategy, "emit_cost": res.emit_cost,
            "ops": len(res.ops), "rolled_back": res.rolled_back,
            "reason": res.reason,
            "review_blocked": (res.review or {}).get("blocked"),
        })
    return {"applied": apply, "results": results,
            "skipped_no_logger": skipped,
            "total_sites": sum(r["sites"] for r in results)}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Rend observables les except…: pass")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--test", default=None, help="commande de test (rollback si rouge)")
    ap.add_argument("--add-logger", action="store_true",
                    help="injecte un logger dans les fichiers qui n'en ont pas")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = run(args.files, args.limit, args.apply, args.test, args.add_logger)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print(f"{'APPLIQUÉ' if args.apply else 'DRY-RUN'} — "
          f"{len(report['results'])} fichier(s), {report['total_sites']} site(s)")
    print(f"{'statut':<18}{'sites':>6}{'strat':>11}{'emit':>7}{'ops':>5}  fichier")
    for r in report["results"]:
        print(f"{r['status']:<18}{r['sites']:>6}{r.get('strategy',''):>11}"
              f"{r.get('emit_cost',0):>7}{r.get('ops',0):>5}  {r['file']}")
        if r.get("reason"):
            print(f"{'':<18}↳ {r['reason'][:100]}")
    if report["skipped_no_logger"]:
        tot = sum(c["sites"] for c in report["skipped_no_logger"])
        print(f"\nignorés (pas de logger) : {len(report['skipped_no_logger'])} fichiers, {tot} sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
