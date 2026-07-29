"""
budget_alert.py — Alerte de dérive budget par sprint / coupe-circuit (ticket E6-04)
===================================================================================
`mimo_budget.check()` vérifie AVANT chaque appel LLM : « le plan supporte-t-il
cette dépense de plus ? ». C'est un garde-fou par APPEL. Ce module agrège au
niveau du SPRINT (ou de l'epic) : « la dérive cumulée de ce sprint dépasse-t-elle
le seuil qu'on s'est fixé ? ».

DEUX SEUILS, PAS UN
--------------------
- `BUDGET_WARN_PCT` (défaut 20 %) : la dérive dépasse ce seuil -> le rapport
  signale `over_warn=True`. C'est un avertissement, pas un blocage.
- `BUDGET_CIRCUIT_PCT` (défaut 50 %) : la dérive dépasse ce seuil ->
  `check_sprint()` lève `BudgetCircuitBreaker`. C'est le coupe-circuit.

Pourquoi deux seuils : un seul seuil oblige à choisir entre alerter trop tôt
(fausses alarmes) et alerter trop tard (budget déjà cramé). Deux seuils
donnent une zone tampon où l'humain peut intervenir avant le blocage.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.budget_alert import check_sprint, sprint_drift

    # Vérification bloquante (coupe-circuit)
    check_sprint("E3")   # lève BudgetCircuitBreaker si dérive > 50 %

    # Rapport non bloquant
    report = sprint_drift("E3")

Vérification : `python -m forge_agents.budget_alert`
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("BudgetAlert")

DEFAULT_WARN_PCT = 20.0
DEFAULT_CIRCUIT_PCT = 50.0


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def warn_pct() -> float:
    return _float_env("BUDGET_WARN_PCT", DEFAULT_WARN_PCT)


def circuit_pct() -> float:
    return _float_env("BUDGET_CIRCUIT_PCT", DEFAULT_CIRCUIT_PCT)


class BudgetCircuitBreaker(RuntimeError):
    """La dérive cumulée d'un sprint dépasse le seuil du coupe-circuit."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def sprint_drift(epic: str, tasks: Optional[list[dict]] = None) -> dict:
    """Dérive cumulée d'un epic : estimé total vs réel total.

    La dérive est calculée sur les tâches MESURÉES uniquement : une tâche non
    commencée n'a pas de réel, l'inclure diluerait la dérive de celles qui ont
    été faites.
    """
    if tasks is None:
        from .forge_task_ledger import variance
        from .forge_backlog import Backlog
        bl = Backlog()
        tasks_raw = bl.by_epic(epic)
        tasks = []
        for t in tasks_raw:
            v = variance(t["id"])
            tasks.append({**t, **v})

    estimated = 0.0
    actual = 0.0
    measured = 0
    total = 0

    for t in tasks:
        total += 1
        est = float(t.get("effort_days", 0) or 0)
        real = float(t.get("actual_days", 0) or 0)
        is_measured = (t.get("measured", False)
                      or real > 0
                      or int(t.get("actual_tokens", 0) or 0) > 0)
        if is_measured:
            measured += 1
            estimated += est
            actual += real

    drift = actual - estimated
    drift_pct = round(100 * drift / estimated, 1) if estimated else 0.0
    wp = warn_pct()
    cp = circuit_pct()

    report = {
        "epic": epic,
        "estimated_days": round(estimated, 4),
        "actual_days": round(actual, 4),
        "drift_days": round(drift, 4),
        "drift_pct": drift_pct,
        "over_warn": drift_pct >= wp,
        "over_circuit": drift_pct >= cp,
        "warn_pct": wp,
        "circuit_pct": cp,
        "tasks": total,
        "tasks_measured": measured,
    }

    if report["over_warn"]:
        level = "CRITICAL" if report["over_circuit"] else "WARNING"
        logger.warning(
            "[BudgetAlert] %s - epic %s : drive %+.1f %% "
            "(%.2f j real vs %.2f j estime, %d/%d taches mesurees)",
            level, epic, drift_pct, actual, estimated, measured, total)

    return report


def check_sprint(epic: str, tasks: Optional[list[dict]] = None) -> dict:
    """Coupe-circuit : leve BudgetCircuitBreaker si la drive depasse le seuil."""
    report = sprint_drift(epic, tasks=tasks)
    if report["over_circuit"]:
        raise BudgetCircuitBreaker(
            f"Coupe-circuit budget : epic {epic} a {report['drift_pct']:+.1f} % "
            f"de drive (seuil {report['circuit_pct']} %). "
            f"{report['actual_days']:.2f} j real vs "
            f"{report['estimated_days']:.2f} j estime "
            f"sur {report['tasks_measured']}/{report['tasks']} taches mesurees.",
            report=report)
    return report


def all_epics_drift() -> list[dict]:
    """Rapport de drive pour tous les epics ayant des taches mesurees."""
    from .forge_task_ledger import epic_costs
    costs = epic_costs()
    out = []
    for epic_name in sorted(costs):
        report = sprint_drift(epic_name)
        if report["tasks_measured"] > 0:
            out.append(report)
    return out


if __name__ == "__main__":
    print("=== Budget Alert - self-check ===")
    print(f"Seuil avertissement : {warn_pct()} %")
    print(f"Seuil coupe-circuit : {circuit_pct()} %")

    fake_tasks = [
        {"id": "T1", "effort_days": 2.0, "actual_days": 2.5, "actual_tokens": 1000},
        {"id": "T2", "effort_days": 3.0, "actual_days": 4.0, "actual_tokens": 2000},
        {"id": "T3", "effort_days": 1.0, "actual_days": 0.0, "actual_tokens": 0},
    ]
    report = sprint_drift("TEST", tasks=fake_tasks)
    print(f"\nDrive simulee : {report['drift_pct']:+.1f} % "
          f"({report['actual_days']} j real vs {report['estimated_days']} j estime)")
    print(f"over_warn={report['over_warn']}, over_circuit={report['over_circuit']}")
    print(f"Taches : {report['tasks_measured']}/{report['tasks']} mesurees")

    heavy_tasks = [
        {"id": "H1", "effort_days": 1.0, "actual_days": 3.0, "actual_tokens": 5000},
    ]
    try:
        check_sprint("HEAVY", tasks=heavy_tasks)
        print("\nCoupe-circuit : PAS declenche")
    except BudgetCircuitBreaker as e:
        print(f"\nCoupe-circuit DECLENCHE : {e}")

    print("\nSelf-check OK")
