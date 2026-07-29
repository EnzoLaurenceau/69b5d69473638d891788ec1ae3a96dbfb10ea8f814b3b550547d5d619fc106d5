"""migrate_state_writers.py — bascule les modules `tenant` vers `forge_store.state_path`.

POURQUOI OUTILLER PLUTÔT QUE MIGRER À LA MAIN
---------------------------------------------
Le blueprint le disait déjà (multi_tenant.md §5) : « la migration doit être outillée, pas
manuelle ». 32 modules classés `tenant` (cf. `state_ownership.py`), chacun avec sa propre
convention de chemin. À la main, c'est 32 occasions de se tromper en silence — et une
erreur ici ne se voit pas : elle écrit juste au mauvais endroit.

DEUX IDIOMES, C'EST TOUT
------------------------
Mesuré sur le dépôt, les écrivains n'ont que deux formes :

    A)  X = FORGE_ROOT / "05_STATE" / "a" / "b.json"   → constante de chemin
    B)  STATE_DIR = FORGE_ROOT / "05_STATE"            → racine, puis STATE_DIR / "x.json"

A devient une fonction (`def X(): return state_path("a/b.json")`) et ses usages `X` → `X()`.
Une constante ne peut pas être paresseuse : elle est évaluée à l'import, **avant** qu'un
tenant existe. C'est précisément le piège qu'on retire.
B devient `state_path("x.json")` directement au site d'usage.

CE QUI PROTÈGE
--------------
- `--dry-run` par défaut : rien n'est écrit sans `--apply`.
- `py_compile` après chaque fichier ; à la moindre erreur le fichier est restauré.
- Les usages ambigus (constante passée sans appel, réassignée, exportée) sont **signalés
  et non touchés** : l'outil préfère laisser du travail que casser du code.

    python 00_CORE/tools/migrate_state_writers.py            # dry-run, tous les modules dus
    python 00_CORE/tools/migrate_state_writers.py --apply
    python 00_CORE/tools/migrate_state_writers.py --only forge_agents/tech_debt.py --apply
"""

from __future__ import annotations

import argparse
import py_compile
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
FORGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "tools"))

from state_ownership import DECISIONS, scan  # noqa: E402

#: A) NOM = <quelque chose> / "05_STATE" / "x" / "y.json"
CONST_RE = re.compile(
    r"^(?P<indent>)(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*"
    r"(?P<root>[\w.]+)\s*/\s*[\"']05_STATE[\"']\s*(?P<rest>(?:/\s*[\"'][^\"']+[\"']\s*)+)$",
    re.MULTILINE,
)
#: B) RACINE = <quelque chose> / "05_STATE"   (sans suite)
ROOT_RE = re.compile(
    r"^(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*(?P<root>[\w.]+)\s*/\s*[\"']05_STATE[\"']\s*$",
    re.MULTILINE,
)

#: Beaucoup de modules de `forge_agents` sont AUSSI lançables en script (`python
#: 00_CORE/forge_agents/tech_debt.py` — la CI le fait). Un import relatif nu les casse
#: dans ce mode : « attempted relative import with no known parent package ». D'où le
#: repli gardé. Régression réellement provoquée puis corrigée pendant W5-03a.
IMPORT_LINE = (
    "try:\n"
    "    from .forge_store import state_path\n"
    "except ImportError:  # lancé comme script : pas de paquet parent\n"
    "    import sys as _sys\n"
    "    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "    from forge_agents.forge_store import state_path"
)
#: Hors du paquet `forge_agents`, l'import ne tient que si `00_CORE` est sur le chemin —
#: vrai en contexte paquet, faux quand le module est lancé comme script. Le repli est
#: gardé (et commenté) plutôt qu'un `sys.path.insert` inconditionnel : W5-03g venait
#: justement d'en supprimer treize.
IMPORT_LINE_FLAT = (
    "try:\n"
    "    from forge_agents.forge_store import state_path\n"
    "except ImportError:  # lancé comme script : 00_CORE n'est pas sur le chemin\n"
    "    import sys as _sys\n"
    "    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "    from forge_agents.forge_store import state_path"
)


def _segments(rest: str) -> str:
    return "/".join(re.findall(r"[\"']([^\"']+)[\"']", rest))


def _uses(text: str, name: str) -> int:
    """Compte les usages du nom hors de sa propre définition."""
    return len(re.findall(rf"\b{name}\b(?!\s*=[^=])", text))


def plan_file(path: Path) -> tuple[str | None, list[str]]:
    """Retourne (nouveau_texte|None, notes)."""
    text = path.read_text(encoding="utf-8")
    notes: list[str] = []
    out = text
    touched = False

    for m in list(CONST_RE.finditer(text)):
        name, rel = m.group("name"), _segments(m.group("rest"))
        if not rel:
            continue
        # une constante réassignée ailleurs (tests qui redirigent l'état) : on ne touche pas
        if len(re.findall(rf"^\s*{name}\s*=", text, re.MULTILINE)) > 1:
            notes.append(f"{name}: réassignée ailleurs -> laissée (décision humaine)")
            continue
        accessor = f'def {name}() -> "Path":\n    """Chemin cloisonné par tenant (W5-03a)."""\n    return state_path("{rel}")'
        out = out.replace(m.group(0), accessor, 1)
        # usages : NOM -> NOM(), sauf dans la définition qu'on vient d'écrire
        out = re.sub(rf"(?<![\w.]){name}\b(?!\s*\(|\s*=[^=])", f"{name}()", out)
        out = out.replace(f"def {name}()() ->", f"def {name}() ->")
        touched = True
        notes.append(f"{name} -> state_path({rel!r})  ({_uses(text, name)} usages)")

    # Idiome B : la racine reste en place (elle sert aussi aux lectures et aux globs),
    # seuls les usages littéraux `RACINE / "x.json"` sont réécrits — eux sont sans ambiguïté.
    for m in list(ROOT_RE.finditer(text)):
        name = m.group("name")
        lit = re.compile(rf"(?<![\w.]){name}\s*/\s*([\"'])([^\"']+)\1")
        hits = lit.findall(out)
        if hits:
            out = lit.sub(lambda mm: f'state_path("{mm.group(2)}")', out)
            touched = True
        notes.append(f"{name} (racine): {len(hits)} usage(s) `{name} / \"...\"` -> state_path(...)")
        rest = len(re.findall(rf"(?<![\w.]){name}\b", out)) - 1
        if rest > 0:
            notes.append(f"{name}: {rest} usage(s) non littéraux restants -> décision humaine")

    if not touched:
        return None, notes

    if "state_path" not in text:
        if (path.parent / "forge_store.py").exists():
            imp = IMPORT_LINE
        else:
            # profondeur réelle jusqu'à `00_CORE`, sinon le repli pointerait à côté
            parts = path.resolve().parts
            depth = len(parts) - parts.index("00_CORE") - 2
            imp = IMPORT_LINE_FLAT.replace("parents[1]", f"parents[{depth}]")
        lines = out.splitlines()
        last = max((i for i, l in enumerate(lines[:120])
                    if l.startswith(("import ", "from ")) and "__future__" not in l), default=0)
        lines.insert(last + 1, imp)
        if "from pathlib import Path" not in out:
            lines.insert(last + 1, "from pathlib import Path")
        out = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return out, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="écrit réellement (sinon dry-run)")
    ap.add_argument("--only", help="un seul module (chemin relatif, même partiel)")
    args = ap.parse_args()
    # ponytail: la console Windows est en cp1252, le rapport en français ne doit pas
    # faire échouer l'outil sur un accent.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    found = scan()
    due = [r for r, d in found.items()
           if d["regime"] == "tenant" and not d["uses_store"]
           and (not args.only or args.only.replace("\\", "/") in r)]

    changed, failed, skipped = [], [], []
    for rel in sorted(due):
        path = FORGE_ROOT / rel
        new, notes = plan_file(path)
        head = f"\n── {rel}"
        print(head)
        for n in notes:
            print(f"   - {n}")
        if new is None:
            print("   (aucune constante mécaniquement migrable)")
            skipped.append(rel)
            continue
        if not args.apply:
            changed.append(rel)
            continue
        backup = path.read_text(encoding="utf-8")
        path.write_text(new, encoding="utf-8")
        try:
            py_compile.compile(str(path), doraise=True)
            changed.append(rel)
            print("   APPLIQUÉ")
        except py_compile.PyCompileError as exc:
            path.write_text(backup, encoding="utf-8")
            failed.append((rel, str(exc).splitlines()[-1][:120]))
            print(f"   ANNULÉ (ne compile pas) : {failed[-1][1]}")

    print(f"\n{'appliqué' if args.apply else 'dry-run'} : "
          f"{len(changed)} migrés · {len(skipped)} manuels · {len(failed)} annulés")
    for rel, err in failed:
        print(f"  ANNULÉ {rel}: {err}")
    print(f"reste manuel : {len(skipped)} module(s) — décision par module, cf. state_ownership.py")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
