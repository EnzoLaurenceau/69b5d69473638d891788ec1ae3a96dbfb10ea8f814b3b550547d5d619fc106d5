"""Tests de l'agent Data Scientist — déterministes, sans I/O réseau, sans LLM.

Chaque test cible une propriété que le module DOIT garantir :
  - pas de fausse anomalie sur baseline nulle (le bug corrigé)
  - pas de conclusion A/B sur métrique non instrumentée
  - le score de santé est plafonné par la couverture d'instrumentation
  - le contrat de la carte post-tâche est respecté

Lancement : python -m forge_agents.test_forge_data_scientist
"""

from __future__ import annotations

import time
import unittest

from .forge_data_scientist import (
    DataLake, Observation, AnomalyDetector, Forecaster, AgentProfiler,
    ABTester, OptimizationEngine, DataScientist, Policy,
    _robust_z, _ols_slope, _welch_t,
)

DAY = 86400.0


class _FakeLake(DataLake):
    """DataLake alimenté en mémoire — aucun accès disque."""

    def __init__(self, obs: list[Observation], window_days: float = 30.0):
        super().__init__(window_days=window_days)
        self._obs = sorted(obs, key=lambda o: o.ts)

    def observations(self, refresh: bool = False) -> list[Observation]:
        return self._obs


def _mk(day_offset: float, **kw) -> Observation:
    base = time.time() - day_offset * DAY
    kw.setdefault("source", "metrics")
    return Observation(ts=base, **kw)


class TestStats(unittest.TestCase):
    def test_robust_z_constant_series(self):
        # Série constante : aucun écart → z nul, pas d'anomalie fabriquée.
        self.assertEqual(_robust_z(5.0, [5.0] * 8), 0.0)

    def test_robust_z_outlier(self):
        self.assertGreater(abs(_robust_z(100.0, [1, 1, 2, 1, 1, 2, 1])), 3.0)

    def test_ols_slope_perfect_line(self):
        slope, intercept, r2 = _ols_slope([0, 1, 2, 3], [0, 2, 4, 6])
        self.assertAlmostEqual(slope, 2.0)
        self.assertAlmostEqual(intercept, 0.0)
        self.assertAlmostEqual(r2, 1.0)

    def test_welch_identical_samples(self):
        t, dof, d = _welch_t([1, 2, 3, 4], [1, 2, 3, 4])
        self.assertAlmostEqual(t, 0.0)
        self.assertAlmostEqual(d, 0.0)


class TestAnomalies(unittest.TestCase):
    def test_no_false_positive_on_zero_baseline(self):
        """Régression : un trou d'instrumentation (aucune latence mesurée les
        jours précédents) ne doit PAS produire une anomalie « +100 % »."""
        obs = [_mk(d, agent="a", latency_ms=0.0) for d in range(10, 3, -1) for _ in range(3)]
        obs += [_mk(0, agent="a", latency_ms=7000.0) for _ in range(3)]
        anomalies = AnomalyDetector(_FakeLake(obs)).detect("low")
        self.assertEqual([a for a in anomalies if a.metric == "latency_ms"], [])

    def test_detects_real_latency_regression(self):
        obs = []
        for d in range(10, 0, -1):
            obs += [_mk(d, agent="a", latency_ms=100.0) for _ in range(4)]
        obs += [_mk(0, agent="a", latency_ms=900.0) for _ in range(4)]
        anomalies = AnomalyDetector(_FakeLake(obs)).detect("medium")
        lat = [a for a in anomalies if a.metric == "latency_ms"]
        self.assertTrue(lat, "une multiplication par 9 de la latence doit être détectée")
        self.assertGreater(lat[0].delta_pct, 100)

    def test_ignores_improvement(self):
        obs = []
        for d in range(10, 0, -1):
            obs += [_mk(d, agent="a", latency_ms=900.0) for _ in range(4)]
        obs += [_mk(0, agent="a", latency_ms=100.0) for _ in range(4)]
        anomalies = AnomalyDetector(_FakeLake(obs)).detect("low")
        self.assertEqual([a for a in anomalies if a.metric == "latency_ms"], [])


class TestForecast(unittest.TestCase):
    def test_insufficient_history(self):
        f = Forecaster(_FakeLake([_mk(0, cost_usd=1.0)])).forecast("cost_usd")
        self.assertIn("pas assez d'historique", f.message)

    def test_rising_trend_and_budget_exhaustion(self):
        obs = []
        for d in range(9, -1, -1):
            obs.append(_mk(d, cost_usd=1.0 + (9 - d) * 0.5))
        f = Forecaster(_FakeLake(obs)).forecast("cost_usd", budget_usd=20.0, spent_usd=0.0)
        self.assertEqual(f.trend, "rising")
        self.assertGreater(f.slope_per_day, 0)
        self.assertIsNotNone(f.budget_exhausted_in_days)
        self.assertGreater(f.budget_exhausted_in_days, 0)


class TestProfiler(unittest.TestCase):
    def test_ranks_reliable_agent_first(self):
        obs = [_mk(1, agent="good", latency_ms=50, cost_usd=0.001, ok=True) for _ in range(10)]
        obs += [_mk(1, agent="bad", latency_ms=5000, cost_usd=0.1, ok=False) for _ in range(10)]
        cards = AgentProfiler(_FakeLake(obs)).profile("agent")
        self.assertEqual(cards[0].subject, "good")
        self.assertEqual(cards[0].verdict, "preferred")
        self.assertLess(cards[-1].composite, cards[0].composite)

    def test_min_calls_filter(self):
        obs = [_mk(1, agent="rare", latency_ms=10)]
        self.assertEqual(AgentProfiler(_FakeLake(obs), min_calls=3).profile("agent"), [])


class TestABTest(unittest.TestCase):
    def test_uninstrumented_metric_is_not_a_verdict(self):
        obs = [_mk(1, model="A", cost_usd=0.0) for _ in range(10)]
        obs += [_mk(1, model="B", cost_usd=0.0) for _ in range(10)]
        r = ABTester(_FakeLake(obs)).compare("model", "A", "B", "cost_usd")
        self.assertIsNone(r.winner)
        self.assertIn("non instrumentée", r.message)

    def test_insufficient_sample(self):
        obs = [_mk(1, model="A", latency_ms=10), _mk(1, model="B", latency_ms=99)]
        r = ABTester(_FakeLake(obs)).compare("model", "A", "B", "latency_ms")
        self.assertIsNone(r.winner)
        self.assertIn("insuffisant", r.message)

    def test_clear_winner_on_latency(self):
        obs = [_mk(1, model="fast", latency_ms=10 + i) for i in range(20)]
        obs += [_mk(1, model="slow", latency_ms=900 + i) for i in range(20)]
        r = ABTester(_FakeLake(obs)).compare("model", "fast", "slow", "latency_ms")
        self.assertEqual(r.winner, "fast")   # lower is better
        self.assertGreater(r.confidence, 0.5)


class TestOptimizationAndHealth(unittest.TestCase):
    def test_flags_missing_instrumentation(self):
        obs = [_mk(1, agent="a") for _ in range(50)]   # aucun coût/latence/token
        recs = OptimizationEngine(_FakeLake(obs)).recommend()
        self.assertTrue(any(r.category == "data" and r.priority == "P0" for r in recs))

    def test_health_capped_by_coverage(self):
        ds = DataScientist()
        ds.lake = _FakeLake([_mk(1, agent="a") for _ in range(50)])
        ds.engine = OptimizationEngine(ds.lake)
        ds.detector, ds.forecaster = ds.engine.detector, ds.engine.forecaster
        ds.profiler, ds.abtester = ds.engine.profiler, ds.engine.abtester
        rep = ds.analyze(persist=False)
        self.assertLess(rep["health"]["score"], 85,
                        "aucune métrique mesurée ne peut pas donner un grade A")
        self.assertIn("cost_usd", rep["health"]["blind_metrics"])


class TestPostTaskCard(unittest.TestCase):
    def test_contract_fields(self):
        ds = DataScientist()
        ds.lake = _FakeLake([_mk(1, agent="w", ok=True, cost_usd=0.01, latency_ms=100)
                             for _ in range(5)]
                            + [_mk(1, agent="f", ok=False) for _ in range(2)])
        ds.engine = OptimizationEngine(ds.lake)
        ds.detector, ds.forecaster = ds.engine.detector, ds.engine.forecaster
        ds.profiler, ds.abtester = ds.engine.profiler, ds.engine.abtester
        card = ds.post_task_card()
        for k in ("what_worked", "what_failed", "cost", "time_ms",
                  "recommendation", "confidence", "samples"):
            self.assertIn(k, card)
        self.assertEqual(card["what_worked"], "w")
        self.assertEqual(card["what_failed"], "f")
        self.assertTrue(0.0 <= card["confidence"] <= 1.0)

    def test_empty_lake_is_null_not_invented(self):
        ds = DataScientist()
        ds.lake = _FakeLake([])
        ds.engine = OptimizationEngine(ds.lake)
        ds.detector, ds.forecaster = ds.engine.detector, ds.engine.forecaster
        ds.profiler, ds.abtester = ds.engine.profiler, ds.engine.abtester
        card = ds.post_task_card()
        self.assertIsNone(card["what_worked"])
        self.assertEqual(card["confidence"], 0.0)


class TestPolicy(unittest.TestCase):
    def _profiler(self):
        obs = [_mk(1, agent="good", latency_ms=50, cost_usd=0.001, ok=True) for _ in range(20)]
        obs += [_mk(1, agent="bad", latency_ms=5000, cost_usd=0.1, ok=False) for _ in range(20)]
        return AgentProfiler(_FakeLake(obs))

    def test_exploits_best_arm(self):
        d = Policy(self._profiler(), epsilon=0.0).choose("agent", explore_seed=0)
        self.assertEqual(d.subject, "good")
        self.assertEqual(d.reason, "exploit")
        self.assertGreater(d.expected_reward, 0.5)

    def test_explores_deterministically(self):
        pol = Policy(self._profiler(), epsilon=1.0)
        a = pol.choose("agent", explore_seed=7)
        b = pol.choose("agent", explore_seed=7)
        self.assertEqual(a.subject, b.subject)      # rejouable
        self.assertEqual(a.reason, "explore")

    def test_cold_start_priority(self):
        obs = [_mk(1, agent="known", latency_ms=10, ok=True) for _ in range(30)]
        obs += [_mk(1, agent="fresh", latency_ms=10, ok=True) for _ in range(3)]
        d = Policy(AgentProfiler(_FakeLake(obs))).choose("agent")
        self.assertEqual(d.reason, "cold_start")

    def test_no_data_returns_none(self):
        self.assertIsNone(Policy(AgentProfiler(_FakeLake([]))).choose("agent"))


class TestRealStores(unittest.TestCase):
    """Fume-test sur les vrais fichiers du dépôt : le module doit tenir debout
    quel que soit l'état réel des stores (vides, partiels, corrompus)."""

    def test_analyze_on_real_data(self):
        rep = DataScientist().analyze(persist=False)
        for k in ("inventory", "coverage", "anomalies", "forecasts",
                  "agent_scorecards", "recommendations", "health"):
            self.assertIn(k, rep)
        self.assertIsInstance(rep["health"]["score"], int)

    def test_advisory_is_bounded(self):
        adv = DataScientist().advisory(task="test", domain="general")
        self.assertLessEqual(len(adv.splitlines()), 10,
                             "l'advisory est un réflexe, pas un rapport")


if __name__ == "__main__":
    unittest.main(verbosity=2)
