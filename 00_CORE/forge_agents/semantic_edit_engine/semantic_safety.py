"""semantic_safety.py — vérifie qu'un patch ne casse pas le contrat du code.

Le PatchScorer mesure si un patch est *petit et compilable*. Ici on mesure s'il est
*sûr* : contrat public préservé, imports cohérents, pas de référence pendante.

Zéro dépendance externe — `ast` de la stdlib pour Python, heuristiques regex sinon
(ruff/semgrep/eslint ne sont pas installés ; leur intégration est le rôle de
`patch_review.py`, en dégradation gracieuse).

Trois niveaux de verdict :
    BLOCK  — le patch casse quelque chose de vérifiable → ne pas appliquer
    WARN   — changement de contrat public, légitime mais à valider
    OK     — rien de détecté

Usage :
    from .semantic_safety import check_safety
    report = check_safety(original, modified, Path("mod.py"))
    if report.blocked: ...

Self-check : python -m forge_agents.semantic_edit_engine.semantic_safety
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

BLOCK = "BLOCK"
WARN = "WARN"


@dataclass
class SafetyIssue:
    level: str          # BLOCK | WARN
    check: str          # identifiant du contrôle
    detail: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.check}: {self.detail}"


@dataclass
class SafetyReport:
    issues: list = field(default_factory=list)
    checks_run: list = field(default_factory=list)
    language: str = "unknown"

    @property
    def blocked(self) -> bool:
        return any(i.level == BLOCK for i in self.issues)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, level: str, check: str, detail: str) -> None:
        self.issues.append(SafetyIssue(level=level, check=check, detail=detail))

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "blocked": self.blocked,
            "checks_run": self.checks_run,
            "issues": [{"level": i.level, "check": i.check, "detail": i.detail} for i in self.issues],
        }

    def summary(self) -> str:
        if self.ok:
            return f"SAFETY OK ({self.language}, {len(self.checks_run)} contrôles)"
        blocks = sum(1 for i in self.issues if i.level == BLOCK)
        return f"SAFETY {'BLOCKED' if self.blocked else 'WARN'} — {blocks} block, {len(self.issues) - blocks} warn"


# ═══════════════════════════════════════════════════════════════════════════════
# PYTHON — analyse AST
# ═══════════════════════════════════════════════════════════════════════════════

def _signature(node) -> str:
    """Signature normalisée d'une fonction : noms des paramètres + ceux à défaut."""
    a = node.args
    names = [p.arg for p in (*a.posonlyargs, *a.args)]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    names += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    n_defaults = len(a.defaults) + len([d for d in a.kw_defaults if d is not None])
    return f"({', '.join(names)})|defaults={n_defaults}"


def _public_api(tree: ast.AST) -> dict:
    """Symboles publics de premier niveau (hors `_privé`) → signature."""
    api = {}
    for node in ast.iter_child_nodes(tree):
        name = getattr(node, "name", None)
        if not name or name.startswith("_"):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            api[name] = _signature(node)
        elif isinstance(node, ast.ClassDef):
            methods = {
                m.name: _signature(m)
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_")
            }
            api[name] = f"class|{sorted(methods.items())}"
    return api


def _imported_names(tree: ast.AST) -> set:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _used_names(tree: ast.AST) -> set:
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} | {
        n.value.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }


def _bound_names(tree: ast.AST) -> set:
    """Noms définis quelque part (assignation, def, class, for, with, except, args…)."""
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.alias):
            bound.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, ast.Global):
            bound.update(node.names)
    return bound


def _check_python(original: str, modified: str, report: SafetyReport) -> None:
    report.language = "python"

    # 1. Syntaxe — un patch qui ne parse pas ne s'applique jamais.
    report.checks_run.append("syntax")
    try:
        new_tree = ast.parse(modified)
    except SyntaxError as exc:
        report.add(BLOCK, "syntax", f"le code modifié ne parse pas: {exc}")
        return
    try:
        old_tree = ast.parse(original)
    except SyntaxError:
        # L'original était déjà cassé (fragment de symbole) — on ne compare pas de contrat.
        report.checks_run.append("api_signature:skipped")
        old_tree = None

    # 2. Contrat public — suppression = BLOCK, changement de signature = WARN.
    if old_tree is not None:
        report.checks_run.append("api_signature")
        old_api, new_api = _public_api(old_tree), _public_api(new_tree)
        for name, sig in old_api.items():
            if name not in new_api:
                report.add(BLOCK, "api_removed", f"symbole public supprimé: {name}")
            elif new_api[name] != sig:
                report.add(WARN, "api_changed", f"signature publique modifiée: {name} {sig} → {new_api[name]}")

    # 3. Références pendantes — nom utilisé, jamais défini ni importé ni builtin.
    report.checks_run.append("dangling_refs")
    builtins_names = set(dir(__builtins__)) if not isinstance(__builtins__, dict) else set(__builtins__)
    known = _bound_names(new_tree) | _imported_names(new_tree) | builtins_names | {"self", "cls", "__name__", "__file__", "__doc__"}
    new_unknown = _used_names(new_tree) - known
    if old_tree is not None:
        # On ne signale que ce que LE PATCH introduit, pas la dette préexistante.
        old_known = _bound_names(old_tree) | _imported_names(old_tree) | builtins_names | {"self", "cls", "__name__", "__file__", "__doc__"}
        new_unknown -= _used_names(old_tree) - old_known
    for name in sorted(new_unknown):
        report.add(BLOCK, "dangling_ref", f"nom utilisé mais jamais défini ni importé: {name}")

    # 4. Import devenu inutile ou import perdu alors qu'il sert encore.
    report.checks_run.append("imports")
    if old_tree is not None:
        used_after = _used_names(new_tree)
        for name in sorted(_imported_names(old_tree) - _imported_names(new_tree)):
            if name in used_after:
                report.add(BLOCK, "import_removed", f"import retiré alors qu'il est encore utilisé: {name}")
        for name in sorted(_imported_names(new_tree) - _imported_names(old_tree)):
            if name not in used_after:
                report.add(WARN, "import_unused", f"import ajouté mais non utilisé: {name}")


# ═══════════════════════════════════════════════════════════════════════════════
# AUTRES LANGAGES — heuristiques honnêtes (pas de faux sentiment de sûreté)
# ═══════════════════════════════════════════════════════════════════════════════

_BRACKETS = {")": "(", "]": "[", "}": "{"}

_JS_FUNC = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
    r"|(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
)


def _balanced(text: str) -> bool:
    """Équilibrage des délimiteurs, en ignorant chaînes et commentaires ligne."""
    stack, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            quote, i = ch, i + 1
            while i < n and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif ch in "([{":
            stack.append(ch)
        elif ch in _BRACKETS:
            if not stack or stack.pop() != _BRACKETS[ch]:
                return False
        i += 1
    return not stack


def _check_generic(original: str, modified: str, report: SafetyReport, suffix: str) -> None:
    report.language = suffix.lstrip(".") or "text"

    report.checks_run.append("brackets_balanced")
    if _balanced(original) and not _balanced(modified):
        report.add(BLOCK, "brackets", "le patch déséquilibre les parenthèses/accolades/crochets")

    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        report.checks_run.append("api_signature")
        def api(text: str) -> dict:
            out = {}
            for m in _JS_FUNC.finditer(text):
                name = m.group(1) or m.group(3)
                params = (m.group(2) or m.group(4) or "").strip()
                if name:
                    out[name] = params
            return out
        old_api, new_api = api(original), api(modified)
        for name, params in old_api.items():
            if name not in new_api:
                report.add(BLOCK, "api_removed", f"fonction supprimée: {name}")
            elif new_api[name] != params:
                report.add(WARN, "api_changed", f"signature modifiée: {name}({params}) → {name}({new_api[name]})")

    report.checks_run.append(f"deep_analysis:unavailable({report.language})")


# ═══════════════════════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════════════════════

def check_safety(original: str, modified: str, file_path: Path | str) -> SafetyReport:
    """Compare l'avant/après d'un patch et retourne les atteintes détectées."""
    path = Path(file_path)
    report = SafetyReport()
    if original == modified:
        report.checks_run.append("noop")
        return report
    if path.suffix == ".py":
        _check_python(original, modified, report)
    else:
        _check_generic(original, modified, report, path.suffix)
    return report


def check_candidate(candidate) -> SafetyReport:
    """Vérifie un PatchCandidate (patch_optimizer)."""
    return check_safety(candidate.original, candidate.modified, candidate.file_path)


if __name__ == "__main__":  # pragma: no cover
    cases = [
        ("ajout sûr", "def f(a):\n    return a\n", "def f(a):\n    return a + 1\n"),
        ("API supprimée", "def f(a):\n    return a\n", "def g(a):\n    return a\n"),
        ("signature changée", "def f(a):\n    return a\n", "def f(a, b=1):\n    return a\n"),
        ("ref pendante", "def f(a):\n    return a\n", "def f(a):\n    return a + missing_thing\n"),
        ("import retiré mais utilisé", "import os\n\n\ndef f():\n    return os.sep\n", "def f():\n    return os.sep\n"),
        ("syntaxe cassée", "def f():\n    return 1\n", "def f():\n    return (\n"),
    ]
    for label, old, new in cases:
        rep = check_safety(old, new, Path("demo.py"))
        print(f"{label:<28} {rep.summary()}")
        for issue in rep.issues:
            print(f"    {issue}")
