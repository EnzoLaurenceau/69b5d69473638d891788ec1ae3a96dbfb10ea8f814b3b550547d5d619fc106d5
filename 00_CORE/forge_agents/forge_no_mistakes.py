"""
forge_no_mistakes.py — No-Mistakes Quality Gate Integration
=============================================================
Intègre https://github.com/kunchenguid/no-mistakes comme quality gate
dans le pipeline Forge.

no-mistakes = git proxy qui :
  1. Crée un worktree isolé (disposable)
  2. Run une pipeline de validation : review → test → docs → lint → push → PR → CI
  3. Auto-fix les problèmes mécaniques
  4. Escalade les jugements humains
  5. Forward au remote SEULEMENT si tout est vert
  6. Ouvre un PR propre automatiquement

Intégration Forge :
  - Quality gate avant toute livraison
  - Evidence collection (patterns de validation)
  - Harness engine integration
  - Agent-native : /no-mistakes pour les agents Forge
"""

from __future__ import annotations
import json
import subprocess
import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


FORGE_ROOT = Path(__file__).parent.parent.parent


# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY GATE STAGES (from no-mistakes pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

PIPELINE_STAGES = [
    {"id": "review", "name": "Code Review", "description": "AI-driven code review", "auto_fix": True},
    {"id": "test", "name": "Test Suite", "description": "Run tests, check coverage", "auto_fix": False},
    {"id": "docs", "name": "Documentation", "description": "Check docs are up to date", "auto_fix": True},
    {"id": "lint", "name": "Linting", "description": "Style and format checks", "auto_fix": True},
    {"id": "security", "name": "Security Scan", "description": "Check for vulnerabilities", "auto_fix": False},
    {"id": "push", "name": "Push Gate", "description": "Forward only if all green", "auto_fix": False},
    {"id": "pr", "name": "PR Creation", "description": "Open clean PR automatically", "auto_fix": True},
    {"id": "ci", "name": "CI Monitor", "description": "Watch CI, auto-fix failures", "auto_fix": True},
]


@dataclass
class Finding:
    """Un problème détecté par la pipeline."""
    stage: str
    severity: str  # critical | high | medium | low | info
    message: str
    file_path: str = ""
    line: int = 0
    auto_fixable: bool = False
    fix_applied: bool = False
    fix_description: str = ""
    escalated: bool = False  # True = needs human decision


@dataclass
class StageResult:
    """Résultat d'un stage de la pipeline."""
    stage: str
    passed: bool
    findings: list[dict] = field(default_factory=list)
    duration_sec: float = 0.0
    auto_fixes_applied: int = 0
    output: str = ""


@dataclass
class GateResult:
    """Résultat complet du quality gate."""
    gate_id: str = ""
    project_path: str = ""
    stages: list[dict] = field(default_factory=list)
    total_findings: int = 0
    critical_findings: int = 0
    auto_fixes_applied: int = 0
    all_green: bool = False
    pr_url: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_sec: float = 0.0

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.datetime.now().isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# NO-MISTAKES WRAPPER
# ═══════════════════════════════════════════════════════════════════════════════

class NoMistakesGate:
    """
    Wrapper autour de no-mistakes CLI.
    Vérifie l'installation, init le gate, run la pipeline.
    """

    def __init__(self):
        self._installed: Optional[bool] = None

    def is_installed(self) -> bool:
        """Vérifie si no-mistakes est installé."""
        if self._installed is not None:
            return self._installed
        try:
            r = subprocess.run(["no-mistakes", "version"],
                               capture_output=True, text=True, timeout=10)
            self._installed = r.returncode == 0
        except Exception:
            self._installed = False
        return self._installed

    def install(self) -> bool:
        """Installe no-mistakes."""
        try:
            r = subprocess.run(
                ["curl", "-fsSL",
                 "https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                install_r = subprocess.run(
                    ["sh"], input=r.stdout, capture_output=True, text=True, timeout=60
                )
                self._installed = install_r.returncode == 0
                return self._installed
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return False

    def init_gate(self, project_path: str) -> dict:
        """Initialise le gate pour un projet."""
        if not self.is_installed():
            return {"error": "no-mistakes not installed", "hint": "Run: curl -fsSL https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh | sh"}
        try:
            r = subprocess.run(
                ["no-mistakes", "init"],
                cwd=project_path, capture_output=True, text=True, timeout=30,
            )
            return {"success": r.returncode == 0, "output": r.stdout + r.stderr}
        except Exception as e:
            return {"error": str(e)}

    def run_pipeline(self, project_path: str, branch: str = "main") -> GateResult:
        """Run la pipeline de validation complète."""
        result = GateResult(project_path=project_path)

        if not self.is_installed():
            result.stages.append(asdict(StageResult(
                stage="init", passed=False,
                findings=[{"severity": "critical", "message": "no-mistakes not installed"}],
            )))
            return result

        # Push through the gate
        try:
            r = subprocess.run(
                ["git", "push", "no-mistakes", branch],
                cwd=project_path, capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                result.stages.append(asdict(StageResult(
                    stage="push", passed=False,
                    findings=[{"severity": "critical", "message": f"Push failed: {r.stderr}"}],
                )))
                return result
        except Exception as e:
            result.stages.append(asdict(StageResult(
                stage="push", passed=False,
                findings=[{"severity": "critical", "message": str(e)}],
            )))
            return result

        # Run no-mistakes TUI (non-interactive)
        try:
            r = subprocess.run(
                ["no-mistakes", "-y"],
                cwd=project_path, capture_output=True, text=True, timeout=300,
            )
            result.all_green = r.returncode == 0
            result.stages.append(asdict(StageResult(
                stage="pipeline", passed=r.returncode == 0,
                output=r.stdout,
            )))
        except Exception as e:
            result.stages.append(asdict(StageResult(
                stage="pipeline", passed=False,
                findings=[{"severity": "critical", "message": str(e)}],
            )))

        result.ended_at = datetime.datetime.now().isoformat()
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# EVIDENCE PATTERNS (from .no-mistakes/evidence/)
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_PATTERNS = {
    "code_review": [
        "Check for hardcoded secrets (API keys, passwords, tokens)",
        "Check for TODO/FIXME/HACK comments that indicate unfinished work",
        "Check for placeholder text (lorem ipsum, example.com, etc.)",
        "Check for print() in production code (use logging instead)",
        "Check for unused imports",
        "Check for bare except clauses",
        "Check for mutable default arguments",
        "Check for SQL injection vulnerabilities",
        "Check for proper error handling",
        "Check for consistent naming conventions",
    ],
    "testing": [
        "All new code must have tests",
        "Test coverage must not decrease",
        "Tests must pass before merge",
        "Edge cases must be tested",
        "Integration tests for API changes",
    ],
    "documentation": [
        "Public APIs must have docstrings",
        "README must be updated for new features",
        "CHANGELOG must be updated",
        "Breaking changes must be documented",
        "Examples must be provided for complex features",
    ],
    "linting": [
        "Code must pass linter (ruff, eslint, etc.)",
        "Formatting must be consistent (black, prettier, etc.)",
        "Type annotations must be present for public APIs",
        "No unused variables",
        "No unreachable code",
    ],
    "security": [
        "No hardcoded credentials",
        "Dependencies must be audited",
        "Input validation must be present",
        "SQL queries must use parameterized statements",
        "File operations must validate paths",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# FORGE QUALITY GATE (standalone, no-mistakes optional)
# ═══════════════════════════════════════════════════════════════════════════════

class ForgeQualityGate:
    """
    Quality gate Forge qui peut fonctionner avec ou sans no-mistakes.
    Intègre les patterns de validation de no-mistakes dans le harness engine.
    """

    def __init__(self):
        self._nm = NoMistakesGate()
        # Cloisonné par tenant (W5-03c) : le répertoire de preuves est résolu à
        # l'instanciation (tenant en contexte au moment de la requête) via forge_store ;
        # sans tenant, repli GLOBAL historique (05_STATE/evidence) assuré par state_path.
        try:
            from .forge_store import state_path
        except ImportError:
            from forge_agents.forge_store import state_path
        self._evidence_dir = state_path("evidence")
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

    def validate_code(self, files: list[str]) -> list[Finding]:
        """Valide du code selon les patterns no-mistakes."""
        findings = []
        for fpath in files:
            p = Path(fpath)
            if not p.exists():
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue

            # Code review patterns
            for pattern in EVIDENCE_PATTERNS["code_review"]:
                if "hardcoded secrets" in pattern.lower():
                    import re
                    secret_patterns = [
                        r'api_key\s*=\s*["\'][A-Za-z0-9]{20,}',
                        r'password\s*=\s*["\'][^"\']+',
                        r'token\s*=\s*["\'][A-Za-z0-9]{20,}',
                    ]
                    for sp in secret_patterns:
                        if re.search(sp, content, re.IGNORECASE):
                            findings.append(Finding(
                                stage="review", severity="critical",
                                message=f"Possible hardcoded secret in {p.name}",
                                file_path=str(p), auto_fixable=False,
                            ))

                if "placeholder" in pattern.lower():
                    placeholders = ["lorem ipsum", "example.com", "placeholder", "TODO: implement"]
                    for ph in placeholders:
                        if ph.lower() in content.lower():
                            findings.append(Finding(
                                stage="review", severity="medium",
                                message=f"Placeholder text '{ph}' in {p.name}",
                                file_path=str(p), auto_fixable=True,
                            ))

                if "print()" in pattern.lower():
                    import re
                    if re.search(r'(?<!#)\bprint\s*\(', content):
                        # Only flag if not in __main__ or test
                        if '__main__' not in content and 'test_' not in p.name:
                            findings.append(Finding(
                                stage="lint", severity="low",
                                message=f"print() in {p.name} — use logging instead",
                                file_path=str(p), auto_fixable=True,
                            ))

            # Linting patterns
            if p.suffix == ".py":
                # Bare except
                if "except:" in content:
                    findings.append(Finding(
                        stage="lint", severity="high",
                        message=f"Bare except in {p.name} — specify exception type",
                        file_path=str(p), auto_fixable=True,
                    ))

                # Mutable default args
                import re
                if re.search(r'def\s+\w+\([^)]*=\s*(\[\]|\{\})', content):
                    findings.append(Finding(
                        stage="lint", severity="high",
                        message=f"Mutable default argument in {p.name}",
                        file_path=str(p), auto_fixable=True,
                    ))

        return findings

    def run_full_gate(self, project_path: str, files: list[str] = None) -> GateResult:
        """Run le quality gate complet."""
        result = GateResult(project_path=project_path)

        # 1. Code validation (Forge standalone)
        if files:
            findings = self.validate_code(files)
            result.stages.append(asdict(StageResult(
                stage="review",
                passed=all(f.severity != "critical" for f in findings),
                findings=[asdict(f) for f in findings],
                auto_fixes_applied=sum(1 for f in findings if f.auto_fixable),
            )))
            result.total_findings += len(findings)
            result.critical_findings += sum(1 for f in findings if f.severity == "critical")

        # 2. No-mistakes pipeline (if installed)
        if self._nm.is_installed():
            nm_result = self._nm.run_pipeline(project_path)
            result.stages.extend(nm_result.stages)
            result.all_green = nm_result.all_green
        else:
            result.stages.append(asdict(StageResult(
                stage="no-mistakes",
                passed=True,  # not blocking if not installed
                output="no-mistakes not installed — using Forge standalone validation only",
            )))

        result.ended_at = datetime.datetime.now().isoformat()
        if not result.all_green:
            result.all_green = result.critical_findings == 0

        # 3. Save evidence
        self._save_evidence(result)

        return result

    def _save_evidence(self, result: GateResult) -> None:
        """Persiste les résultats comme evidence."""
        filename = f"gate-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        filepath = self._evidence_dir / filename
        filepath.write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def get_evidence_history(self, limit: int = 10) -> list[dict]:
        """Historique des quality gates."""
        gates = []
        for f in sorted(self._evidence_dir.glob("gate-*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                gates.append({
                    "gate_id": data.get("gate_id", f.stem),
                    "all_green": data.get("all_green", False),
                    "total_findings": data.get("total_findings", 0),
                    "critical_findings": data.get("critical_findings", 0),
                    "auto_fixes": data.get("auto_fixes_applied", 0),
                    "started_at": data.get("started_at", ""),
                })
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return gates

    def get_validation_patterns(self) -> dict:
        """Retourne les patterns de validation pour injection dans les agents."""
        return EVIDENCE_PATTERNS


# Singleton
_gate: Optional[ForgeQualityGate] = None


def get_quality_gate() -> ForgeQualityGate:
    global _gate
    if _gate is None:
        _gate = ForgeQualityGate()
    return _gate


if __name__ == "__main__":
    gate = get_quality_gate()
    print(f"no-mistakes installed: {gate._nm.is_installed()}")
    print(f"\nValidation patterns:")
    for category, patterns in gate.get_validation_patterns().items():
        print(f"  {category}: {len(patterns)} rules")
    print(f"\nEvidence history: {len(gate.get_evidence_history())} gates")

    # Test validation on self
    import sys
    this_file = str(Path(__file__))
    findings = gate.validate_code([this_file])
    print(f"\nSelf-validation: {len(findings)} findings")
    for f in findings:
        print(f"  [{f.severity}] {f.message}")
