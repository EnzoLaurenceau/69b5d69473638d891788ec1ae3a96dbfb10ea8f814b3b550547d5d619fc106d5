"""edit_pipeline.py — boucle complète d'une modification de code sûre.

    plan (MCPT)  →  gate impact  →  revue statique  →  application  →  tests  →  diff
                         ↓ CRITICAL      ↓ régression        ↓ ne compile plus / tests KO
                       ABORT            ABORT               ROLLBACK

C'est le seul appelant légitime de `patch_optimizer`, `impact_gate`, `patch_review` et
`auto_rollback` — conformément à la règle d'admission de POSITIONING.md §6 : une brique
n'existe que si quelque chose l'appelle.

Aucune étape ne peut être sautée silencieusement : chaque gate indisponible est reporté
(`skipped`) dans le résultat, jamais masqué. `force=True` permet de passer outre un gate
bloquant — le forçage est enregistré dans le résultat et dans les métriques.

Usage :
    from .edit_pipeline import run_edit
    res = run_edit("mod.py", target_name="guard", modified_code=code, apply=True,
                   test_cmd="python -m pytest tests/test_guard.py -q")

Self-check : python -m forge_agents.semantic_edit_engine.edit_pipeline
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .auto_rollback import get_rollback_manager
from .edit_metrics import record_edit
from .impact_gate import check_candidate as check_impact_candidate
from .patch_optimizer import get_patch_optimizer
from .patch_review import review_candidate

logger = logging.getLogger(__name__)

TEST_TIMEOUT_S = 600

# États terminaux du pipeline
NO_PLAN = "no_plan"                    # aucune transformation dérivable
BLOCKED_IMPACT = "blocked_impact"      # blast radius CRITICAL
BLOCKED_REVIEW = "blocked_review"      # le patch introduit une régression
PLANNED = "planned"                    # dry-run : plan validé, rien écrit
APPLY_FAILED = "apply_failed"          # écriture refusée (ne compile plus)
TESTS_FAILED = "tests_failed"          # appliqué puis annulé : tests rouges
APPLIED = "applied"                    # succès


@dataclass
class EditResult:
    status: str = NO_PLAN
    file: str = ""
    target: str = ""
    strategy: str = ""
    ops: list = field(default_factory=list)
    emit_cost: int = 0
    mcpt_cost: float = 0.0
    patch_score: float = 0.0
    token_savings_pct: float = 0.0
    diff: str = ""
    impact: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    tests: dict = field(default_factory=dict)
    gates_skipped: list = field(default_factory=list)
    forced: bool = False
    rolled_back: bool = False
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (PLANNED, APPLIED)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["ok"] = self.ok
        d.pop("diff", None)
        return d

    def summary(self) -> str:
        head = f"{self.status.upper()} — {self.target or self.file}"
        if self.strategy:
            head += f" [{self.strategy}, emit={self.emit_cost}, économie={self.token_savings_pct}%]"
        return head if not self.reason else f"{head} — {self.reason}"


def run_edit(
    file_path: str | Path,
    instruction: str = "",
    target_name: str | None = None,
    modified_code: str | None = None,
    apply: bool = False,
    test_cmd: str | None = None,
    force: bool = False,
) -> EditResult:
    """Exécute la boucle complète. Ne lève pas : tout échec est un statut."""
    path = Path(file_path)
    result = EditResult(file=str(path), target=target_name or "", forced=force)

    # ── 1. Plan de coût minimal ────────────────────────────────────────────────
    t0_opt = time.perf_counter()
    candidate = get_patch_optimizer().optimize(instruction, path, target_name, modified_code)
    if candidate is None:
        result.reason = "aucun plan : fichier absent, cible identique, ou transformation non dérivable"
        return result

    metrics = record_edit(candidate, workflow="edit_pipeline",
                          latency_ms=int((time.perf_counter() - t0_opt) * 1000))
    result.status = PLANNED
    result.strategy = candidate.strategy.value
    result.ops = candidate.to_dict()["ops"]
    result.emit_cost = candidate.emit_cost
    result.mcpt_cost = round(candidate.mcpt_cost, 2)
    result.patch_score = round(candidate.score, 4)
    result.token_savings_pct = metrics.token_savings
    result.diff = candidate.diff

    # ── 2. Gate impact (blast radius) ──────────────────────────────────────────
    impact = check_impact_candidate(candidate)
    result.impact = impact.to_dict()
    if not impact.available:
        result.gates_skipped.append(f"impact:{impact.reason}")
    elif impact.blocked and not force:
        result.status = BLOCKED_IMPACT
        result.reason = (
            f"blast radius {impact.risk} — {impact.impacted_count} symboles, "
            f"{impact.processes_affected} flux impactés"
        )
        return result

    # ── 3. Revue statique (seules les régressions introduites comptent) ────────
    review = review_candidate(candidate)
    result.review = review.to_dict()
    result.gates_skipped += [f"review:{t}" for t in review.tools_skipped]
    if review.blocked and not force:
        result.status = BLOCKED_REVIEW
        result.reason = (
            review.safety.summary()
            if review.blocked_by_safety
            else f"{len(review.introduced)} diagnostic(s) introduit(s) par le patch"
        )
        return result

    if not apply:
        return result  # dry-run : plan validé, rien écrit

    # ── 4-5-6. Application transactionnelle → tests → rollback si rouge ────────
    manager = get_rollback_manager()
    snapshot = manager.create_snapshot(path)
    content = path.read_text(encoding="utf-8")
    patched_symbol = candidate.plan.apply(candidate.original)
    if candidate.original == content:
        new_content = patched_symbol
    else:
        new_content = content.replace(candidate.original, patched_symbol, 1)
        if new_content is content or new_content == content:
            # replace() n'a pas trouvé candidate.original dans le fichier.
            # Cause fréquente : le symbol_resolver a normalisé les line endings
            # ou le fichier a été modifié entre la planification et l'application.
            result.status = APPLY_FAILED
            result.reason = (
                "le texte original du symbole n'a pas été retrouvé dans le fichier — "
                "possible décalage de line endings ou modification concurrente"
            )
            return result

    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        result.status = APPLY_FAILED
        result.reason = f"écriture impossible: {exc}"
        return result

    if not manager.verify(path):
        # rollback() renvoie un bool : NE PAS l'ignorer. Si la restauration échoue,
        # le fichier reste cassé — prétendre `rolled_back=True` masquerait le pire cas.
        result.rolled_back = manager.rollback(snapshot)
        result.status = APPLY_FAILED
        result.reason = "le fichier ne compile plus après application — annulé"
        if not result.rolled_back:
            result.reason += " ; ROLLBACK ÉCHOUÉ — fichier laissé modifié, intervention requise"
        return result

    if test_cmd:
        tests = _run_tests(test_cmd, path.parent)
        result.tests = tests
        if not tests["passed"]:
            result.rolled_back = manager.rollback(snapshot)
            result.status = TESTS_FAILED
            result.reason = f"tests en échec (exit {tests['exit_code']}) — annulé"
            if not result.rolled_back:
                result.reason += " ; ROLLBACK ÉCHOUÉ — fichier laissé modifié, intervention requise"
            return result

    result.status = APPLIED
    return result


def _run_tests(cmd: str, cwd: Path) -> dict:
    """Lance la commande de test. Une commande introuvable ≠ des tests verts."""
    started = time.time()
    try:
        proc = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=TEST_TIMEOUT_S, cwd=cwd
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "exit_code": -1, "duration_ms": TEST_TIMEOUT_S * 1000,
                "tail": f"timeout après {TEST_TIMEOUT_S}s", "cmd": cmd}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"passed": False, "exit_code": -1, "duration_ms": 0,
                "tail": f"commande non exécutable: {exc}", "cmd": cmd}

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return {
        "passed": proc.returncode == 0,
        "exit_code": proc.returncode,
        "duration_ms": int((time.time() - started) * 1000),
        "tail": output[-800:],
        "cmd": cmd,
    }


if __name__ == "__main__":  # pragma: no cover
    import tempfile

    src = "def guard(user):\n    if user:\n        return 1\n    return 0\n"
    ok_target = "def guard(user):\n    if user and user.active:\n        return 1\n    return 0\n"
    bad_target = "def guard(user):\n    return missing_helper(user)\n"

    for label, target, apply_it in [
        ("dry-run sain", ok_target, False),
        ("patch cassé (revue)", bad_target, False),
        ("application réelle", ok_target, True),
    ]:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(src)
            tmp = Path(fh.name)
        try:
            res = run_edit(tmp, target_name="guard", modified_code=target, apply=apply_it)
            print(f"{label:<22} {res.summary()}")
            if res.gates_skipped:
                print(f"{'':<22} gates indisponibles: {res.gates_skipped}")
            if apply_it:
                print(f"{'':<22} fichier patché: {'oui' if 'user.active' in tmp.read_text(encoding='utf-8') else 'non'}")
        finally:
            tmp.unlink(missing_ok=True)
