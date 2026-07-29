"""Tests E6-04 — alerte de dérive budget par sprint / coupe-circuit.

Tests purs (données simulées, pas de base) :
  - sprint_drift() calcule correctement la dérive
  - seuls les tâches mesurées comptent
  - check_sprint() leve BudgetCircuitBreaker au bon seuil
  - les seuils sont configurables par env
"""

from __future__ import annotations

import importlib.util as _ilu
import os
import sys
import types as _types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
_PKG = ROOT / "00_CORE" / "forge_agents"


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = _ilu.spec_from_file_location(name, str(path))
    mod = _types.ModuleType(name)
    mod.__file__ = str(path)
    mod.__package__ = "forge_agents"
    mod.__spec__ = spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if "forge_agents" not in sys.modules:
    _pkg = _types.ModuleType("forge_agents")
    _pkg.__path__ = [str(_PKG)]
    _pkg.__package__ = "forge_agents"
    sys.modules["forge_agents"] = _pkg

_budget = _load_module("forge_agents.budget_alert", _PKG / "budget_alert.py")

sprint_drift = _budget.sprint_drift
check_sprint = _budget.check_sprint
BudgetCircuitBreaker = _budget.BudgetCircuitBreaker
warn_pct = _budget.warn_pct
circuit_pct = _budget.circuit_pct
DEFAULT_WARN_PCT = _budget.DEFAULT_WARN_PCT
DEFAULT_CIRCUIT_PCT = _budget.DEFAULT_CIRCUIT_PCT


# Fixtures
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure env vars don't leak between tests."""
    monkeypatch.delenv("BUDGET_WARN_PCT", raising=False)
    monkeypatch.delenv("BUDGET_CIRCUIT_PCT", raising=False)


TASKS_ON_BUDGET = [
    {"id": "T1", "effort_days": 2.0, "actual_days": 2.0, "actual_tokens": 1000},
    {"id": "T2", "effort_days": 3.0, "actual_days": 3.0, "actual_tokens": 2000},
]

TASKS_OVER_BUDGET = [
    {"id": "T1", "effort_days": 2.0, "actual_days": 3.0, "actual_tokens": 1000},
    {"id": "T2", "effort_days": 3.0, "actual_days": 5.0, "actual_tokens": 2000},
]

TASKS_MIX = [
    {"id": "T1", "effort_days": 2.0, "actual_days": 3.0, "actual_tokens": 1000},
    {"id": "T2", "effort_days": 3.0, "actual_days": 0.0, "actual_tokens": 0},  # not measured
]


class TestSprintDrift:
    """sprint_drift() with injected tasks (no database)."""

    def test_on_budget(self):
        r = sprint_drift("E1", tasks=TASKS_ON_BUDGET)
        assert r["drift_pct"] == 0.0
        assert r["over_warn"] is False
        assert r["over_circuit"] is False

    def test_over_budget(self):
        r = sprint_drift("E1", tasks=TASKS_OVER_BUDGET)
        # estimated=5.0, actual=8.0, drift=3.0 => 60 %
        assert r["drift_pct"] == 60.0
        assert r["over_warn"] is True
        assert r["over_circuit"] is True

    def test_only_measured_tasks_count(self):
        r = sprint_drift("E1", tasks=TASKS_MIX)
        # Only T1 is measured: est=2.0, real=3.0 => 50 %
        assert r["tasks"] == 2
        assert r["tasks_measured"] == 1
        assert r["estimated_days"] == 2.0
        assert r["actual_days"] == 3.0
        assert r["drift_pct"] == 50.0

    def test_no_measured_tasks(self):
        empty = [{"id": "X", "effort_days": 5.0, "actual_days": 0.0, "actual_tokens": 0}]
        r = sprint_drift("E1", tasks=empty)
        assert r["tasks_measured"] == 0
        assert r["drift_pct"] == 0.0

    def test_empty_tasks(self):
        r = sprint_drift("E1", tasks=[])
        assert r["tasks"] == 0
        assert r["drift_pct"] == 0.0

    def test_negative_drift(self):
        tasks = [{"id": "T1", "effort_days": 5.0, "actual_days": 2.0, "actual_tokens": 500}]
        r = sprint_drift("E1", tasks=tasks)
        assert r["drift_pct"] == -60.0
        assert r["over_warn"] is False
        assert r["over_circuit"] is False

    def test_report_fields(self):
        r = sprint_drift("E1", tasks=TASKS_ON_BUDGET)
        for key in ("epic", "estimated_days", "actual_days", "drift_days",
                     "drift_pct", "over_warn", "over_circuit", "warn_pct",
                     "circuit_pct", "tasks", "tasks_measured"):
            assert key in r, f"missing key: {key}"


class TestCheckSprint:
    """check_sprint() — circuit breaker."""

    def test_does_not_raise_when_under_threshold(self):
        r = check_sprint("E1", tasks=TASKS_ON_BUDGET)
        assert r["over_circuit"] is False

    def test_raises_when_over_threshold(self):
        with pytest.raises(BudgetCircuitBreaker) as exc_info:
            check_sprint("E1", tasks=TASKS_OVER_BUDGET)
        assert exc_info.value.report["over_circuit"] is True
        assert "E1" in str(exc_info.value)

    def test_exception_carries_report(self):
        try:
            check_sprint("E1", tasks=TASKS_OVER_BUDGET)
            assert False, "should have raised"
        except BudgetCircuitBreaker as e:
            assert isinstance(e.report, dict)
            assert e.report["epic"] == "E1"


class TestThresholds:
    """Seuils configurables par variable d'env."""

    def test_default_thresholds(self):
        assert warn_pct() == DEFAULT_WARN_PCT
        assert circuit_pct() == DEFAULT_CIRCUIT_PCT

    def test_custom_warn_pct(self, monkeypatch):
        monkeypatch.setenv("BUDGET_WARN_PCT", "10")
        assert warn_pct() == 10.0

    def test_custom_circuit_pct(self, monkeypatch):
        monkeypatch.setenv("BUDGET_CIRCUIT_PCT", "75")
        assert circuit_pct() == 75.0

    def test_custom_threshold_changes_behavior(self, monkeypatch):
        # At default (50%), 60% drift triggers circuit breaker
        with pytest.raises(BudgetCircuitBreaker):
            check_sprint("E1", tasks=TASKS_OVER_BUDGET)

        # Raise threshold to 80% -> 60% drift no longer triggers
        monkeypatch.setenv("BUDGET_CIRCUIT_PCT", "80")
        r = check_sprint("E1", tasks=TASKS_OVER_BUDGET)
        assert r["over_circuit"] is False
        assert r["over_warn"] is True  # still over warn (20%)

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BUDGET_WARN_PCT", "not_a_number")
        assert warn_pct() == DEFAULT_WARN_PCT


class TestEdgeCases:
    """Edge cases: zero effort, single task, mixed states."""

    def test_zero_effort_no_crash(self):
        tasks = [{"id": "T1", "effort_days": 0.0, "actual_days": 5.0, "actual_tokens": 1000}]
        r = sprint_drift("E1", tasks=tasks)
        assert r["drift_pct"] == 0.0  # no baseline -> can't compute %

    def test_single_task_measured(self):
        tasks = [{"id": "T1", "effort_days": 3.0, "actual_days": 4.5, "actual_tokens": 500}]
        r = sprint_drift("E1", tasks=tasks)
        assert r["tasks_measured"] == 1
        assert r["drift_pct"] == 50.0

    def test_tokens_only_marks_as_measured(self):
        """A task with actual_tokens > 0 but actual_days = 0 is measured."""
        tasks = [{"id": "T1", "effort_days": 2.0, "actual_days": 0.0, "actual_tokens": 100}]
        r = sprint_drift("E1", tasks=tasks)
        assert r["tasks_measured"] == 1
