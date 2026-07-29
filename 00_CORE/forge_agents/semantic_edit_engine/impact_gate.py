"""impact_gate.py — blast radius GitNexus AVANT patch, en code et non en règle humaine.

CLAUDE.md impose déjà « impact() avant toute édition ». C'était une consigne adressée
à un humain (ou à Claude) — donc contournable par oubli. Ici c'est un gate exécutable
que le pipeline d'édition traverse automatiquement.

Politique par défaut :
    CRITICAL → BLOCK (le patch ne s'applique pas sans forçage explicite)
    HIGH     → WARN  (passe, mais signalé et journalisé)
    MEDIUM / LOW / inconnu → OK

Dégradation gracieuse : pas de `.gitnexus/run.cjs`, pas de `node`, index absent ou
périmé → `available=False`, **jamais de blocage**. Un outil d'analyse indisponible ne
doit pas empêcher de travailler ; il doit se voir dans le rapport.

Usage :
    from .impact_gate import check_impact
    rep = check_impact("optimize_patch", "00_CORE/.../patch_optimizer.py")
    if rep.blocked: ...

Self-check : python -m forge_agents.semantic_edit_engine.impact_gate
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).resolve().parents[3]
RUNNER = FORGE_ROOT / ".gitnexus" / "run.cjs"
TIMEOUT_S = int(os.environ.get("FORGE_IMPACT_TIMEOUT", "180"))

BLOCKING_RISKS = {"CRITICAL"}
WARNING_RISKS = {"HIGH"}


@dataclass
class ImpactReport:
    symbol: str = ""
    risk: str = "UNKNOWN"
    impacted_count: int = 0
    direct: int = 0
    processes_affected: int = 0
    modules_affected: int = 0
    available: bool = False
    reason: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.available and self.risk.upper() in BLOCKING_RISKS

    @property
    def warned(self) -> bool:
        return self.available and self.risk.upper() in WARNING_RISKS

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "risk": self.risk,
            "impacted_count": self.impacted_count,
            "direct": self.direct,
            "processes_affected": self.processes_affected,
            "modules_affected": self.modules_affected,
            "available": self.available,
            "blocked": self.blocked,
            "reason": self.reason,
        }

    def summary(self) -> str:
        if not self.available:
            return f"IMPACT indisponible ({self.reason}) — non bloquant"
        state = "BLOCKED" if self.blocked else ("WARN" if self.warned else "OK")
        return (
            f"IMPACT {state} — {self.symbol}: risque {self.risk}, "
            f"{self.impacted_count} symbole(s), {self.processes_affected} flux, "
            f"{self.modules_affected} module(s)"
        )


def _repo_name() -> str:
    """Nom du dépôt tel qu'enregistré dans le registre GitNexus (= nom du dossier)."""
    return os.environ.get("FORGE_GITNEXUS_REPO") or FORGE_ROOT.name


def check_impact(
    symbol: str,
    file_path: str | Path | None = None,
    direction: str = "upstream",
    repo: str | None = None,
) -> ImpactReport:
    """Interroge GitNexus sur le blast radius d'un symbole. Ne lève jamais."""
    report = ImpactReport(symbol=symbol)

    if not symbol:
        report.reason = "aucun symbole ciblé"
        return report
    if not RUNNER.exists():
        report.reason = f"runner absent: {RUNNER}"
        return report
    node = shutil.which("node")
    if not node:
        report.reason = "node introuvable dans le PATH"
        return report

    cmd = [
        node, str(RUNNER), "impact", symbol,
        "--repo", repo or _repo_name(),
        "--direction", direction,
        "--summary-only",
    ]
    if file_path:
        cmd += ["--file", str(file_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=FORGE_ROOT)
    except subprocess.TimeoutExpired:
        report.reason = f"timeout après {TIMEOUT_S}s"
        return report
    except (OSError, subprocess.SubprocessError) as exc:
        report.reason = f"exécution impossible: {exc}"
        return report

    payload = _extract_json(proc.stdout or "")
    if payload is None:
        report.reason = "sortie GitNexus illisible"
        return report
    if "error" in payload:
        report.reason = str(payload["error"])[:200]
        return report

    summary = payload.get("summary") or {}
    report.available = True
    report.raw = payload
    report.risk = str(payload.get("risk") or "UNKNOWN").upper()
    report.impacted_count = int(payload.get("impactedCount") or 0)
    report.direct = int(summary.get("direct") or 0)
    report.processes_affected = int(summary.get("processes_affected") or 0)
    report.modules_affected = int(summary.get("modules_affected") or 0)
    return report


def _extract_json(text: str) -> dict | None:
    """Isole l'objet JSON dans une sortie qui peut contenir des lignes de log."""
    text = text.strip()
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def check_candidate(candidate) -> ImpactReport:
    """Gate d'impact pour un PatchCandidate (patch_optimizer)."""
    symbol = getattr(candidate, "target_name", "") or ""
    if symbol in {"", "file"}:
        rep = ImpactReport(symbol=symbol)
        rep.reason = "patch non ancré sur un symbole nommé"
        return rep
    return check_impact(symbol, candidate.file_path)


if __name__ == "__main__":  # pragma: no cover
    for sym, fp in [
        ("optimize_patch", "00_CORE/forge_agents/semantic_edit_engine/patch_optimizer.py"),
        ("forge_call", None),
        ("symbole_qui_nexiste_pas", None),
    ]:
        rep = check_impact(sym, fp)
        print(rep.summary())
