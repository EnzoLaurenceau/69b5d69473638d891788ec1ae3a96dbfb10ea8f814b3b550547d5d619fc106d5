"""patch_review.py — revue statique d'un patch AVANT application.

Principe central : **seuls les diagnostics INTRODUITS par le patch comptent.**
On analyse l'avant et l'après, on soustrait. La dette préexistante n'est pas le
problème du patch — sinon tout patch sur un fichier sale serait rejeté.

Outils branchés, tous optionnels (aucun n'est requis) :

| Outil    | Langages        | Détection                        |
|----------|-----------------|----------------------------------|
| ruff     | Python          | `ruff` PATH, sinon `python -m ruff` |
| semgrep  | multi           | `semgrep` PATH                   |
| eslint   | JS/TS           | `eslint` PATH, sinon `npx eslint`  |

Absent → l'outil est reporté comme `skipped`, jamais comme un échec. Un outil qui
manque ne doit pas bloquer une livraison ; il doit se voir dans le rapport.

Usage :
    from .patch_review import review_patch
    rep = review_patch(original, modified, Path("mod.py"))
    if rep.blocked: ...

Self-check : python -m forge_agents.semantic_edit_engine.patch_review
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .semantic_safety import check_safety

logger = logging.getLogger(__name__)

TIMEOUT_S = 45
_PY = {".py", ".pyi"}
_JS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


@dataclass
class Diagnostic:
    tool: str
    code: str
    message: str
    line: int = 0

    def key(self) -> str:
        """Identité indépendante de la ligne — un décalage de lignes n'est pas un nouveau problème."""
        return f"{self.tool}:{self.code}:{self.message.strip()}"

    def __str__(self) -> str:
        return f"{self.tool} {self.code} (L{self.line}): {self.message}"


@dataclass
class ReviewReport:
    introduced: list = field(default_factory=list)   # diagnostics ajoutés par le patch
    resolved: list = field(default_factory=list)     # diagnostics supprimés par le patch
    tools_run: list = field(default_factory=list)
    tools_skipped: list = field(default_factory=list)
    safety: object = None
    blocked_by_safety: bool = False

    @property
    def blocked(self) -> bool:
        return self.blocked_by_safety or bool(self.introduced)

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "blocked_by_safety": self.blocked_by_safety,
            "introduced": [str(d) for d in self.introduced],
            "resolved": [str(d) for d in self.resolved],
            "tools_run": self.tools_run,
            "tools_skipped": self.tools_skipped,
            "safety": self.safety.to_dict() if self.safety else None,
        }

    def summary(self) -> str:
        state = "BLOCKED" if self.blocked else "OK"
        return (
            f"REVIEW {state} — +{len(self.introduced)} introduit(s), "
            f"-{len(self.resolved)} résolu(s), outils: {len(self.tools_run)} lancé(s) / "
            f"{len(self.tools_skipped)} indisponible(s)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNERS — chacun retourne (diagnostics, disponible)
# ═══════════════════════════════════════════════════════════════════════════════

def _run(cmd: list, cwd: Path | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("commande KO %s: %s", cmd[0], exc)
        return None


def _ruff_cmd() -> list | None:
    if shutil.which("ruff"):
        return ["ruff"]
    probe = _run([sys.executable, "-m", "ruff", "--version"])
    return [sys.executable, "-m", "ruff"] if probe and probe.returncode == 0 else None


def _ruff(path: Path) -> tuple[list, bool]:
    base = _ruff_cmd()
    if not base:
        return [], False
    proc = _run([*base, "check", "--output-format", "json", "--force-exclude", str(path)])
    if proc is None:
        return [], False
    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], False
    return [
        Diagnostic(
            tool="ruff",
            code=str(d.get("code") or "?"),
            message=str(d.get("message") or ""),
            line=int((d.get("location") or {}).get("row") or 0),
        )
        for d in raw
    ], True


def _semgrep(path: Path) -> tuple[list, bool]:
    if not shutil.which("semgrep"):
        return [], False
    proc = _run(["semgrep", "--config", "auto", "--json", "--quiet", str(path)])
    if proc is None:
        return [], False
    try:
        raw = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return [], False
    return [
        Diagnostic(
            tool="semgrep",
            code=str(r.get("check_id") or "?"),
            message=str((r.get("extra") or {}).get("message") or ""),
            line=int((r.get("start") or {}).get("line") or 0),
        )
        for r in raw.get("results", [])
    ], True


def _eslint(path: Path) -> tuple[list, bool]:
    if shutil.which("eslint"):
        cmd = ["eslint"]
    elif shutil.which("npx"):
        cmd = ["npx", "--no-install", "eslint"]
    else:
        return [], False
    proc = _run([*cmd, "--format", "json", str(path)])
    if proc is None or not (proc.stdout or "").strip().startswith("["):
        return [], False
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], False
    return [
        Diagnostic(
            tool="eslint",
            code=str(m.get("ruleId") or "?"),
            message=str(m.get("message") or ""),
            line=int(m.get("line") or 0),
        )
        for f in raw
        for m in f.get("messages", [])
    ], True


def _runners_for(suffix: str) -> list:
    runners = [("semgrep", _semgrep)]
    if suffix in _PY:
        runners.insert(0, ("ruff", _ruff))
    elif suffix in _JS:
        runners.insert(0, ("eslint", _eslint))
    return runners


# ═══════════════════════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════════════════════

def review_patch(original: str, modified: str, file_path: Path | str) -> ReviewReport:
    """Analyse avant/après et ne retient que ce que le patch introduit."""
    path = Path(file_path)
    report = ReviewReport()

    report.safety = check_safety(original, modified, path)
    report.blocked_by_safety = report.safety.blocked

    before: dict = {}
    after: dict = {}
    for name, runner in _runners_for(path.suffix):
        diags_before, ok_b = _lint_snapshot(runner, original, path)
        if not ok_b:
            report.tools_skipped.append(name)
            continue
        diags_after, ok_a = _lint_snapshot(runner, modified, path)
        if not ok_a:
            report.tools_skipped.append(name)
            continue
        report.tools_run.append(name)
        for d in diags_before:
            before[d.key()] = d
        for d in diags_after:
            after[d.key()] = d

    report.introduced = [after[k] for k in after.keys() - before.keys()]
    report.resolved = [before[k] for k in before.keys() - after.keys()]
    return report


def _lint_snapshot(runner, content: str, path: Path) -> tuple[list, bool]:
    """Écrit le contenu dans un fichier temporaire de même extension et lance l'outil."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=path.suffix, delete=False, encoding="utf-8", dir=path.parent if path.parent.exists() else None
        ) as fh:
            fh.write(content)
            tmp = Path(fh.name)
        return runner(tmp)
    except OSError as exc:
        logger.debug("snapshot KO: %s", exc)
        return [], False
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def review_candidate(candidate) -> ReviewReport:
    """Revue d'un PatchCandidate (patch_optimizer)."""
    return review_patch(candidate.original, candidate.modified, candidate.file_path)


if __name__ == "__main__":  # pragma: no cover
    old = "import os\n\n\ndef f():\n    return os.sep\n"
    new = "import os\n\n\ndef f():\n    return os.sep + missing\n"
    rep = review_patch(old, new, Path("demo.py"))
    print(rep.summary())
    print("safety:", rep.safety.summary())
    for d in rep.introduced:
        print("  introduit:", d)
    print("outils indisponibles:", rep.tools_skipped or "aucun")
