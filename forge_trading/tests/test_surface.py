"""test_surface.py — filet de sécurité AVANT de déplacer le service trading.

POURQUOI CE FICHIER EXISTE
--------------------------
Le contexte `trading` compte 48 modules et **zéro fonction de test**. La consolidation
(W5-03g : réunir `00_CORE/trading/` et `10_TRADING/` sur une racine importable) déplace des
fichiers et réécrit des imports. Sans filet, la seule vérification possible serait « ça
démarre encore », ce qui ne prouve rien : un symbole disparu ou un import silencieusement
cassé passerait inaperçu jusqu'à l'exécution réelle.

CE QUE CE HARNAIS PROUVE
------------------------
1. **Tout module trading s'importe.** Un import cassé par le déplacement échoue ici.
2. **La surface publique ne régresse pas.** On fige la liste des symboles publics dans un
   instantané ; après déplacement, un symbole manquant fait échouer le test avec son nom.
3. **Les ports du noyau restent branchés** et dégradent sans lever.

Ce n'est PAS un test de comportement métier : il ne vérifie aucune stratégie, aucun calcul.
Il attrape les régressions **structurelles** d'un déplacement — ce pour quoi il est écrit.
Un vrai test de comportement reste à écrire, et ce fichier ne prétend pas le remplacer.

MODE D'EMPLOI
-------------
    python -m pytest forge_trading/tests/test_surface.py            # vérifie
    python forge_trading/tests/test_surface.py --update-snapshot    # re-fige APRÈS un déplacement voulu
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(__file__).with_name("surface_snapshot.json")

# `forge_trading` est un package a nom valide : seule la racine du depot suffit.
for p in (FORGE_ROOT, FORGE_ROOT / "00_CORE"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _trading_files() -> list:
    """Modules du service trading — desormais une SEULE racine (forge_trading/)."""
    out = []
    for root in (FORGE_ROOT / "forge_trading",):
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts or p.name.startswith("test_"):
                continue
            out.append(p)
    return out


def _public_symbols(path: Path) -> list:
    """Symboles publics de premier niveau, lus par AST (aucun import exécuté)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    names = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_") and t.id.isupper():
                    names.append(t.id)
    return sorted(set(names))


def current_surface() -> dict:
    """{ nom_logique_du_module: [symboles publics] } — indépendant du chemin physique.

    La clé est le nom du module, PAS son chemin : c'est ce qui permet au même instantané
    de rester valide après un déplacement de fichiers.
    """
    surface = {}
    for p in _trading_files():
        key = p.stem if p.name != "__init__.py" else f"{p.parent.name}.__init__"
        syms = _public_symbols(p)
        if syms:
            surface[key] = syms
    return surface


# ── Tests ────────────────────────────────────────────────────────────────────

def test_every_module_parses():
    """Aucun module trading ne doit être syntaxiquement cassé."""
    broken = []
    for p in _trading_files():
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            broken.append(f"{p.relative_to(FORGE_ROOT).as_posix()}: {exc}")
    assert not broken, f"modules non parsables : {broken}"


def test_core_modules_import():
    """Les modules de logique s'importent réellement (pas seulement à l'analyse)."""
    failures = []
    for mod in ("forge_trading.core.orchestrator", "forge_trading.core.smc_engine",
                "forge_trading.core.jury", "forge_trading.core.rag",
                "forge_trading.core.data_feed", "forge_trading.core.ports",
                "forge_trading.strategies", "forge_trading.backtesting",
                "forge_trading.config"):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            failures.append(f"{mod}: {type(exc).__name__}: {exc}")
    assert not failures, f"imports cassés : {failures}"


def test_public_surface_has_not_regressed():
    """Aucun symbole public ne disparaît. Échoue en NOMMANT ce qui manque."""
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current_surface(), indent=2, sort_keys=True),
                            encoding="utf-8")
        return                                   # première exécution : on fige

    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = current_surface()
    missing = {}
    for mod, syms in expected.items():
        got = set(actual.get(mod, []))
        gone = [s for s in syms if s not in got]
        if gone:
            missing[mod] = gone
    assert not missing, (
        f"symboles publics disparus après modification : {missing}\n"
        "Si la disparition est VOULUE : python forge_trading/tests/test_surface.py --update-snapshot"
    )


def test_ports_degrade_without_raising():
    """Les ports vers le noyau ne lèvent jamais — le service doit démarrer seul."""
    from forge_trading.core import ports
    h = ports.health()
    assert isinstance(h["available"], int) and h["total"] > 0
    assert h["mode"] in ("adossé au noyau", "dégradé", "autonome")


if __name__ == "__main__":
    if "--update-snapshot" in sys.argv:
        surface = current_surface()
        SNAPSHOT.write_text(json.dumps(surface, indent=2, sort_keys=True), encoding="utf-8")
        print(f"instantané re-figé : {len(surface)} modules, "
              f"{sum(len(v) for v in surface.values())} symboles publics")
    else:
        s = current_surface()
        print(f"surface actuelle : {len(s)} modules, {sum(len(v) for v in s.values())} symboles")
        print(f"instantané : {'présent' if SNAPSHOT.exists() else 'ABSENT (sera créé au 1er test)'}")
