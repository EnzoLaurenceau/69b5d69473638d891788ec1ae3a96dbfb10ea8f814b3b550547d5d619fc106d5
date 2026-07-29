"""
forge_data_scientist.py — Agent Data Scientist de La Forge.

Bounded context : ANALYTICS. Une seule responsabilité — transformer les données
brutes produites par la Forge en décisions d'optimisation exploitables.

Doctrine respectée :
  - 0 token LLM. 100 % déterministe (stdlib uniquement, pas de numpy/pandas).
    Le "raisonnement" du Data Scientist est de la statistique, pas de la
    génération. Il ne peut donc pas halluciner.
  - Service découplé : il LIT les stores existants (forge_metrics.jsonl,
    experience_db.json, tool_call_ledger.jsonl, agent_tracker/history.json)
    et ÉCRIT un seul artefact (05_STATE/data_scientist_report.json).
    Aucun autre module n'a besoin d'être modifié pour qu'il fonctionne.
  - Contrat API explicite : get_data_scientist().analyze() -> dict sérialisable.

Chaîne d'agents data (cf. 09_TASKS/queue/Créer agent Data Scientist) :
    DataLake (engineer) → Profiler/Anomaly (analyst) → Forecast/ABTest
    (scientist) → OptimizationEngine (ML/optim) → advisory (orchestrateur)

CLI :
    python -m forge_agents.forge_data_scientist report
    python -m forge_agents.forge_data_scientist anomalies
    python -m forge_agents.forge_data_scientist forecast
    python -m forge_agents.forge_data_scientist profile
    python -m forge_agents.forge_data_scientist abtest --dim model --metric cost_usd
    python -m forge_agents.forge_data_scientist export        # DuckDB/Parquet si dispo
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional
import logging

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE = _ROOT / "05_STATE"

# Cloisonnement par tenant (W5-03c) : les entrées lues (métriques, exp-db, ledger, tracker)
# et l'artefact écrit (report, warehouse) sont résolus À L'APPEL via `forge_store.state_path`,
# jamais à l'import (aucun tenant en contexte à l'import). Sans tenant → repli GLOBAL historique
# assuré par `state_path` lui-même, donc le mode opérateur mono-utilisateur reste identique.
try:
    from .forge_store import state_path as _state_path
except ImportError:  # exécution hors package
    from forge_agents.forge_store import state_path as _state_path


def _metrics_path() -> Path:
    # forge_metrics écrit en mode tenant sous le namespace `metrics/` (forge_store.append),
    # et à plat en mode GLOBAL. On vise le chemin tenant, avec repli plat si absent.
    p = _state_path("metrics/forge_metrics.jsonl")
    return p if p.exists() else _state_path("forge_metrics.jsonl")

def _exp_db_path() -> Path:   return _state_path("experience_db.json")
def _ledger_path() -> Path:   return _state_path("tool_call_ledger.jsonl")
def _tracker_path() -> Path:  return _state_path("agent_tracker/history.json")
def _report_path() -> Path:   return _state_path("data_scientist_report.json")
def _warehouse_dir() -> Path: return _state_path("warehouse")

DAY = 86400.0

# Coût unitaire de secours quand un événement n'a pas de cost_usd (USD / 1M tokens).
# Sert uniquement à ne pas compter 0 pour les providers gratuits mesurés en tokens.
_FALLBACK_COST_PER_MTOK = {
    "claude": 0.0,      # abonnement — coût marginal nul par doctrine
    "claude_cli": 0.0,
    "claude-code": 0.0,
    "mimo": 0.0,
    "groq": 0.0,
    "cerebras": 0.0,
    "gemini": 0.0,
}


# ── 1. DATA LAKE ─────────────────────────────────────────────────────────────

@dataclass
class Observation:
    """Ligne normalisée du data lake. Un événement = une exécution mesurée."""
    ts: float
    source: str                 # metrics | experience | ledger | tracker
    kind: str = ""              # llm | tool | workflow | judge | ...
    agent: str = ""
    model: str = ""
    provider: str = ""
    workflow: str = ""
    domain: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    ok: bool = True
    hallucination_score: Optional[float] = None
    quality: Optional[float] = None      # 0..10
    task: str = ""

    @property
    def day(self) -> int:
        return int(self.ts // DAY)


def _read_jsonl(path: Path, limit: Optional[int] = None) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows[-limit:] if limit else rows


def _parse_ts(value: Any) -> float:
    """Accepte epoch float/int ou ISO-8601. Retourne 0.0 si illisible."""
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, str) and value:
        try:
            from datetime import datetime
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    return 0.0


def _infer_cost(tokens_total: int, provider: str, model: str) -> float:
    key = (provider or model or "").lower()
    for prefix, rate in _FALLBACK_COST_PER_MTOK.items():
        if key.startswith(prefix):
            return tokens_total / 1_000_000 * rate
    return 0.0


class DataLake:
    """Data Engineer : collecte + normalise. Aucune interprétation ici."""

    def __init__(self, window_days: float = 30.0):
        self.window_days = window_days
        self._obs: Optional[list[Observation]] = None

    # -- collecte par source ------------------------------------------------

    def _from_metrics(self) -> Iterable[Observation]:
        for r in _read_jsonl(_metrics_path()):
            ts = _parse_ts(r.get("ts"))
            if not ts:
                continue
            ti = int(r.get("tokens_in") or 0)
            to = int(r.get("tokens_out") or 0)
            tinf = int(r.get("tokens_inference") or 0)
            total = ti + to + tinf
            cost = float(r.get("cost_usd") or 0.0)
            provider = str(r.get("provider") or "")
            model = str(r.get("model") or "")
            if cost == 0.0 and total:
                cost = _infer_cost(total, provider, model)
            hs = r.get("hallucination_score")
            yield Observation(
                ts=ts, source="metrics", kind=str(r.get("kind") or ""),
                agent=str(r.get("agent") or ""), model=model, provider=provider,
                workflow=str(r.get("workflow") or ""),
                tokens_in=ti, tokens_out=to, tokens_total=total,
                latency_ms=float(r.get("latency_ms") or 0.0),
                cost_usd=cost, ok=bool(r.get("ok", True)),
                hallucination_score=float(hs) if isinstance(hs, (int, float)) else None,
                task=str(r.get("workflow") or r.get("node") or ""),
            )

    def _from_experiences(self) -> Iterable[Observation]:
        exp_db_path = _exp_db_path()
        if not exp_db_path.exists():
            return
        try:
            db = json.loads(exp_db_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for x in db.get("experiences", []):
            ts = _parse_ts(x.get("timestamp"))
            if not ts:
                continue
            tokens = int(x.get("tokens_used") or 0)
            provider = str(x.get("provider") or "")
            meta = x.get("metadata") or {}
            outcome = x.get("outcome")
            q = x.get("quality_score")
            cost = float(x.get("cost") or 0.0) or _infer_cost(tokens, provider, str(meta.get("model") or ""))
            yield Observation(
                ts=ts, source="experience", kind="workflow",
                agent=str(x.get("agent") or meta.get("agent") or ""),
                model=str(meta.get("model") or ""), provider=provider,
                domain=str(x.get("domain") or ""),
                tokens_in=0, tokens_out=0, tokens_total=tokens,
                latency_ms=float(x.get("duration_ms") or 0.0),
                cost_usd=cost,
                ok=(outcome not in ("failure", "error", "fail", False)),
                quality=float(q) if isinstance(q, (int, float)) else None,
                task=str(x.get("task") or ""),
            )

    def _from_ledger(self) -> Iterable[Observation]:
        # Le ledger est volumineux (1000+ lignes) : on ne garde que le signal
        # utile (succès/échec par outil), pas les payloads.
        for r in _read_jsonl(_ledger_path(), limit=5000):
            ts = _parse_ts(r.get("timestamp"))
            if not ts:
                continue
            yield Observation(
                ts=ts, source="ledger", kind="tool",
                agent=str(r.get("tool_name") or ""),
                model=str(r.get("model") or ""),
                provider=str(r.get("source") or ""),
                ok=not bool(r.get("is_error")),
                task=str(r.get("tool_name") or ""),
            )

    def _from_tracker(self) -> Iterable[Observation]:
        tracker_path = _tracker_path()
        if not tracker_path.exists():
            return
        try:
            data = json.loads(tracker_path.read_text(encoding="utf-8"))
        except Exception:
            return
        tasks = data.get("tasks") if isinstance(data, dict) else data
        if not isinstance(tasks, list):
            return
        for t in tasks:
            if not isinstance(t, dict):
                continue
            ts = _parse_ts(t.get("timestamp") or t.get("started_at") or t.get("ts"))
            if not ts:
                continue
            yield Observation(
                ts=ts, source="tracker", kind="workflow",
                agent=str(t.get("agent") or t.get("name") or ""),
                tokens_total=int(t.get("tokens") or 0),
                latency_ms=float(t.get("duration_ms") or 0.0),
                ok=str(t.get("status", "ok")).lower() not in ("failed", "error", "ko"),
                task=str(t.get("task") or ""),
            )

    # -- API ---------------------------------------------------------------

    def observations(self, refresh: bool = False) -> list[Observation]:
        if self._obs is not None and not refresh:
            return self._obs
        cutoff = time.time() - self.window_days * DAY
        obs: list[Observation] = []
        for producer in (self._from_metrics, self._from_experiences,
                         self._from_ledger, self._from_tracker):
            try:
                obs.extend(o for o in producer() if o.ts >= cutoff)
            except Exception:
                continue
        obs.sort(key=lambda o: o.ts)
        self._obs = obs
        return obs

    def inventory(self) -> dict:
        obs = self.observations()
        by_source: dict[str, int] = {}
        for o in obs:
            by_source[o.source] = by_source.get(o.source, 0) + 1
        span = (obs[-1].ts - obs[0].ts) / DAY if len(obs) > 1 else 0.0
        return {
            "rows": len(obs),
            "by_source": by_source,
            "window_days": self.window_days,
            "span_days": round(span, 2),
            "oldest_ts": obs[0].ts if obs else None,
            "newest_ts": obs[-1].ts if obs else None,
        }

    def coverage(self) -> dict:
        """Taux d'instrumentation par champ. C'est LA métrique honnête : une
        analyse ne vaut que ce que vaut la couverture de ses entrées."""
        obs = self.observations()
        n = len(obs) or 1
        fields = {
            "cost_usd": sum(1 for o in obs if o.cost_usd > 0),
            "latency_ms": sum(1 for o in obs if o.latency_ms > 0),
            "tokens_total": sum(1 for o in obs if o.tokens_total > 0),
            "model": sum(1 for o in obs if o.model),
            "agent": sum(1 for o in obs if o.agent),
            "hallucination_score": sum(1 for o in obs if o.hallucination_score is not None),
            "quality": sum(1 for o in obs if o.quality is not None),
        }
        pct = {k: round(v / n * 100, 1) for k, v in fields.items()}
        weak = [k for k, v in pct.items() if v < 20]
        return {"rows": len(obs), "pct": pct, "weak_fields": weak,
                "overall": round(sum(pct.values()) / len(pct), 1)}

    def export_warehouse(self) -> dict:
        """Parquet/DuckDB si les libs sont là, sinon JSONL colonne-plat.
        Le lake reste exploitable dans tous les cas (pas de dépendance dure)."""
        warehouse_dir = _warehouse_dir()
        warehouse_dir.mkdir(parents=True, exist_ok=True)
        rows = [asdict(o) for o in self.observations()]
        out: dict[str, Any] = {"rows": len(rows), "formats": []}

        jsonl = warehouse_dir / "observations.jsonl"
        with jsonl.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        out["formats"].append(str(jsonl.relative_to(_ROOT)))

        try:
            import duckdb  # type: ignore
            db = warehouse_dir / "forge_analytics.duckdb"
            con = duckdb.connect(str(db))
            con.execute("CREATE OR REPLACE TABLE observations AS SELECT * FROM read_json_auto(?)",
                        [str(jsonl)])
            con.execute("COPY observations TO ? (FORMAT PARQUET)",
                        [str(warehouse_dir / "observations.parquet")])
            con.close()
            out["formats"] += [str(db.relative_to(_ROOT)),
                               str((warehouse_dir / "observations.parquet").relative_to(_ROOT))]
        except Exception as e:
            out["duckdb"] = f"unavailable ({type(e).__name__}) — JSONL only"
        return out


# ── 2. STATS PRIMITIVES ──────────────────────────────────────────────────────

def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def _mad(vals: list[float]) -> float:
    """Median Absolute Deviation — robuste aux outliers, contrairement à l'écart-type."""
    if not vals:
        return 0.0
    m = _median(vals)
    return _median([abs(v - m) for v in vals])


def _robust_z(value: float, baseline: list[float]) -> float:
    """Z-score robuste (modified z-score de Iglewicz-Hoaglin)."""
    if len(baseline) < 3:
        return 0.0
    mad = _mad(baseline)
    med = _median(baseline)
    if mad == 0:
        # Série constante : tout écart non nul est une rupture nette.
        return 0.0 if value == med else math.copysign(10.0, value - med)
    return 0.6745 * (value - med) / mad


def _ols_slope(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Régression linéaire simple. Retourne (pente, ordonnée, r2)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, intercept, max(0.0, r2)


def _welch_t(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """Welch's t-test. Retourne (t, dof, cohen_d). Pas de scipy : on renvoie
    la statistique brute + effect size, la décision se prend sur des seuils."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 0.0, 0.0
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    denom = math.sqrt(va / na + vb / nb)
    if denom == 0:
        return 0.0, 0.0, 0.0
    t = (ma - mb) / denom
    num = (va / na + vb / nb) ** 2
    den = (va ** 2) / (na ** 2 * (na - 1)) + (vb ** 2) / (nb ** 2 * (nb - 1))
    dof = num / den if den > 0 else 0.0
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)) if na + nb > 2 else 0.0
    d = (ma - mb) / pooled if pooled > 0 else 0.0
    return t, dof, d


def _norm(value: float, best: float, worst: float) -> float:
    """Normalise vers 0..100 ; best peut être < worst (métrique à minimiser)."""
    if best == worst:
        return 100.0
    ratio = (value - worst) / (best - worst)
    return round(max(0.0, min(1.0, ratio)) * 100, 1)


# ── 3. ANOMALIES ─────────────────────────────────────────────────────────────

@dataclass
class Anomaly:
    metric: str
    subject: str                # model / agent / workflow concerné
    dimension: str              # model | agent | workflow | global
    baseline: float
    current: float
    delta_pct: float
    z: float
    severity: str               # low | medium | high | critical
    message: str


class AnomalyDetector:
    """Data Analyst : détecte les ruptures sur coût, latence, échec, hallucination."""

    METRICS = (
        ("cost_usd", "coût", "sum", True),
        ("latency_ms", "latence", "mean", True),
        ("failure_rate", "taux d'échec", "rate", True),
        ("hallucination_risk", "risque hallucination", "rate", True),
        ("tokens_total", "tokens", "sum", True),
    )

    def __init__(self, lake: DataLake, baseline_days: int = 7):
        self.lake = lake
        self.baseline_days = baseline_days

    def _daily_series(self, obs: list[Observation], metric: str) -> dict[int, float]:
        """Série journalière. Un jour SANS mesure pour la métrique est ABSENT de
        la série — il n'est pas compté comme 0. Sinon un trou d'instrumentation
        produit une baseline nulle et donc une fausse anomalie « +100 % »."""
        buckets: dict[int, list[Observation]] = {}
        for o in obs:
            buckets.setdefault(o.day, []).append(o)
        series: dict[int, float] = {}
        for day, rows in buckets.items():
            if metric == "cost_usd":
                measured = [r.cost_usd for r in rows if r.cost_usd > 0]
                if measured:
                    series[day] = sum(measured)
            elif metric == "tokens_total":
                measured = [r.tokens_total for r in rows if r.tokens_total > 0]
                if measured:
                    series[day] = float(sum(measured))
            elif metric == "latency_ms":
                lat = [r.latency_ms for r in rows if r.latency_ms > 0]
                if lat:
                    series[day] = statistics.fmean(lat)
            elif metric == "failure_rate":
                series[day] = 1.0 - (sum(1 for r in rows if r.ok) / len(rows))
            elif metric == "hallucination_risk":
                hs = [1.0 - r.hallucination_score for r in rows
                      if r.hallucination_score is not None]
                if hs:
                    series[day] = statistics.fmean(hs)
        return series

    @staticmethod
    def _severity(z: float, delta_pct: float) -> str:
        az, ad = abs(z), abs(delta_pct)
        if az >= 6 or ad >= 100:
            return "critical"
        if az >= 4 or ad >= 50:
            return "high"
        if az >= 3 or ad >= 25:
            return "medium"
        return "low"

    def detect(self, min_severity: str = "medium") -> list[Anomaly]:
        obs = self.lake.observations()
        if len(obs) < 5:
            return []
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        found: list[Anomaly] = []

        groups: list[tuple[str, str, list[Observation]]] = [("global", "forge", obs)]
        for dim, attr in (("model", "model"), ("agent", "agent"), ("workflow", "workflow")):
            by: dict[str, list[Observation]] = {}
            for o in obs:
                key = getattr(o, attr) or ""
                if key:
                    by.setdefault(key, []).append(o)
            for key, rows in by.items():
                if len(rows) >= 5:
                    groups.append((dim, key, rows))

        for dim, subject, rows in groups:
            for metric, label, _agg, higher_is_bad in self.METRICS:
                series = self._daily_series(rows, metric)
                if len(series) < 4:
                    continue
                days = sorted(series)
                current_day, current = days[-1], series[days[-1]]
                baseline_days = days[-(self.baseline_days + 1):-1]
                baseline_vals = [series[d] for d in baseline_days]
                if len(baseline_vals) < 3:
                    continue
                base = _median(baseline_vals)
                if base == 0:
                    # Pas de baseline exploitable → « nouveau signal », pas une
                    # anomalie. On ne fabrique pas un +100 % sur une division par 0.
                    continue
                z = _robust_z(current, baseline_vals)
                delta = (current - base) / base * 100
                if higher_is_bad and delta <= 0:
                    continue
                sev = self._severity(z, delta)
                if order[sev] < order[min_severity]:
                    continue
                found.append(Anomaly(
                    metric=metric, subject=subject, dimension=dim,
                    baseline=round(base, 6), current=round(current, 6),
                    delta_pct=round(delta, 1), z=round(z, 2), severity=sev,
                    message=f"{label} {subject} {delta:+.0f}% vs baseline {self.baseline_days}j "
                            f"({base:.4g} → {current:.4g})",
                ))
        found.sort(key=lambda a: (order[a.severity], abs(a.z)), reverse=True)
        return found


# ── 4. PRÉVISIONS ────────────────────────────────────────────────────────────

@dataclass
class Forecast:
    metric: str
    slope_per_day: float
    r2: float
    current_daily: float
    predicted_7d: float
    predicted_30d: float
    trend: str                       # rising | stable | falling
    budget_exhausted_in_days: Optional[float] = None
    message: str = ""


class Forecaster:
    """Data Scientist : extrapole les séries journalières (OLS + EWMA)."""

    def __init__(self, lake: DataLake, detector: Optional[AnomalyDetector] = None):
        self.lake = lake
        self.detector = detector or AnomalyDetector(lake)

    @staticmethod
    def _ewma(values: list[float], alpha: float = 0.4) -> float:
        if not values:
            return 0.0
        acc = values[0]
        for v in values[1:]:
            acc = alpha * v + (1 - alpha) * acc
        return acc

    def forecast(self, metric: str = "cost_usd",
                 budget_usd: Optional[float] = None,
                 spent_usd: float = 0.0) -> Forecast:
        obs = self.lake.observations()
        series = self.detector._daily_series(obs, metric)
        if len(series) < 3:
            return Forecast(metric=metric, slope_per_day=0.0, r2=0.0, current_daily=0.0,
                            predicted_7d=0.0, predicted_30d=0.0, trend="stable",
                            message="pas assez d'historique (< 3 jours) pour prévoir")
        days = sorted(series)
        xs = [float(d - days[0]) for d in days]
        ys = [series[d] for d in days]
        slope, intercept, r2 = _ols_slope(xs, ys)
        smooth = self._ewma(ys)
        last_x = xs[-1]
        p7 = max(0.0, slope * (last_x + 7) + intercept)
        p30 = max(0.0, slope * (last_x + 30) + intercept)
        rel = slope / smooth if smooth else 0.0
        trend = "rising" if rel > 0.05 else ("falling" if rel < -0.05 else "stable")

        exhausted = None
        msg = (f"{metric} : {smooth:.4g}/j lissé, tendance {trend} "
               f"({slope:+.4g}/j, r²={r2:.2f}) → J+7 ≈ {p7:.4g}, J+30 ≈ {p30:.4g}")
        if budget_usd and metric == "cost_usd":
            remaining = budget_usd - spent_usd
            daily = max(smooth, 1e-9)
            if remaining <= 0:
                exhausted = 0.0
            elif slope > 0:
                # somme arithmétique : remaining = n*daily + slope*n(n+1)/2
                a, b, c = slope / 2, daily + slope / 2, -remaining
                disc = b * b - 4 * a * c
                exhausted = ((-b + math.sqrt(disc)) / (2 * a)) if disc >= 0 else remaining / daily
            else:
                exhausted = remaining / daily
            msg += f" | budget épuisé dans ~{exhausted:.0f} jours"

        return Forecast(metric=metric, slope_per_day=round(slope, 8), r2=round(r2, 3),
                        current_daily=round(smooth, 6), predicted_7d=round(p7, 6),
                        predicted_30d=round(p30, 6), trend=trend,
                        budget_exhausted_in_days=(round(exhausted, 1) if exhausted is not None else None),
                        message=msg)

    def forecast_all(self, budget_usd: Optional[float] = None,
                     spent_usd: float = 0.0) -> list[Forecast]:
        return [self.forecast("cost_usd", budget_usd, spent_usd),
                self.forecast("tokens_total"),
                self.forecast("latency_ms"),
                self.forecast("failure_rate")]


# ── 5. PROFILAGE DES AGENTS ──────────────────────────────────────────────────

@dataclass
class Scorecard:
    subject: str
    dimension: str              # agent | model
    calls: int
    efficiency: float           # 0..100 — sortie utile / token
    reliability: float          # 0..100 — succès + absence d'hallucination
    cost: float                 # 0..100 — 100 = le moins cher
    speed: float                # 0..100 — 100 = le plus rapide
    composite: float
    avg_cost_usd: float
    avg_latency_ms: float
    success_rate: float
    avg_tokens: float
    verdict: str                # preferred | ok | watch | avoid


class AgentProfiler:
    """Attribue à chaque agent/modèle un scorecard 0-100 exploitable par
    l'orchestrateur pour choisir automatiquement le meilleur exécutant."""

    def __init__(self, lake: DataLake, min_calls: int = 3):
        self.lake = lake
        self.min_calls = min_calls

    def profile(self, dimension: str = "agent") -> list[Scorecard]:
        obs = self.lake.observations()
        by: dict[str, list[Observation]] = {}
        for o in obs:
            key = getattr(o, dimension, "") or ""
            if key:
                by.setdefault(key, []).append(o)
        by = {k: v for k, v in by.items() if len(v) >= self.min_calls}
        if not by:
            return []

        stats = {}
        for k, rows in by.items():
            lat = [r.latency_ms for r in rows if r.latency_ms > 0]
            toks = [r.tokens_total for r in rows if r.tokens_total > 0]
            hall = [r.hallucination_score for r in rows if r.hallucination_score is not None]
            stats[k] = {
                "calls": len(rows),
                "avg_cost": statistics.fmean([r.cost_usd for r in rows]),
                "avg_lat": statistics.fmean(lat) if lat else 0.0,
                "avg_tok": statistics.fmean(toks) if toks else 0.0,
                "success": sum(1 for r in rows if r.ok) / len(rows),
                "grounded": statistics.fmean(hall) if hall else None,
            }

        costs = [s["avg_cost"] for s in stats.values()]
        lats = [s["avg_lat"] for s in stats.values() if s["avg_lat"] > 0] or [0.0]
        toks = [s["avg_tok"] for s in stats.values() if s["avg_tok"] > 0] or [0.0]

        cards: list[Scorecard] = []
        for k, s in stats.items():
            cost_score = _norm(s["avg_cost"], best=min(costs), worst=max(costs))
            speed = _norm(s["avg_lat"], best=min(lats), worst=max(lats)) if s["avg_lat"] > 0 else 50.0
            eff = _norm(s["avg_tok"], best=min(toks), worst=max(toks)) if s["avg_tok"] > 0 else 50.0
            grounded = s["grounded"] if s["grounded"] is not None else 1.0
            reliability = round(s["success"] * 70 + grounded * 30, 1)
            composite = round(eff * 0.2 + reliability * 0.4 + cost_score * 0.2 + speed * 0.2, 1)
            verdict = ("preferred" if composite >= 75 else
                       "ok" if composite >= 55 else
                       "watch" if composite >= 35 else "avoid")
            cards.append(Scorecard(
                subject=k, dimension=dimension, calls=s["calls"],
                efficiency=eff, reliability=reliability, cost=cost_score, speed=speed,
                composite=composite, avg_cost_usd=round(s["avg_cost"], 6),
                avg_latency_ms=round(s["avg_lat"], 1), success_rate=round(s["success"], 3),
                avg_tokens=round(s["avg_tok"], 1), verdict=verdict,
            ))
        cards.sort(key=lambda c: c.composite, reverse=True)
        return cards

    def best(self, dimension: str = "agent") -> Optional[Scorecard]:
        cards = self.profile(dimension)
        return cards[0] if cards else None


# ── 6. A/B TESTING ───────────────────────────────────────────────────────────

@dataclass
class ABResult:
    dimension: str
    metric: str
    variant_a: str
    variant_b: str
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    delta_pct: float
    t_stat: float
    dof: float
    cohen_d: float
    winner: Optional[str]
    confidence: float           # 0..1
    message: str


class ABTester:
    """Compare deux variantes (modèle, agent, provider, workflow) sur une
    métrique. Sans scipy : décision par |t| + taille d'effet + n minimum."""

    LOWER_IS_BETTER = {"cost_usd", "latency_ms", "tokens_total", "failure_rate"}

    def __init__(self, lake: DataLake, min_n: int = 5):
        self.lake = lake
        self.min_n = min_n

    def _values(self, rows: list[Observation], metric: str) -> list[float]:
        if metric == "failure_rate":
            return [0.0 if r.ok else 1.0 for r in rows]
        if metric == "quality":
            return [r.quality for r in rows if r.quality is not None]
        vals = [getattr(r, metric, 0.0) for r in rows]
        return [float(v) for v in vals if isinstance(v, (int, float))]

    def compare(self, dimension: str, variant_a: str, variant_b: str,
                metric: str = "cost_usd") -> ABResult:
        obs = self.lake.observations()
        ra = [o for o in obs if (getattr(o, dimension, "") or "") == variant_a]
        rb = [o for o in obs if (getattr(o, dimension, "") or "") == variant_b]
        va, vb = self._values(ra, metric), self._values(rb, metric)
        if len(va) < self.min_n or len(vb) < self.min_n:
            return ABResult(dimension, metric, variant_a, variant_b, len(va), len(vb),
                            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, 0.0,
                            f"échantillon insuffisant (n≥{self.min_n} requis, "
                            f"a={len(va)}, b={len(vb)}) — pas de conclusion")
        if all(v == 0 for v in va) and all(v == 0 for v in vb):
            return ABResult(dimension, metric, variant_a, variant_b, len(va), len(vb),
                            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, 0.0,
                            f"{metric} non instrumentée sur ces variantes "
                            f"(toutes les valeurs à 0) — test impossible")
        ma, mb = statistics.fmean(va), statistics.fmean(vb)
        t, dof, d = _welch_t(va, vb)
        delta = ((mb - ma) / ma * 100) if ma else 0.0
        lower_better = metric in self.LOWER_IS_BETTER
        better = (variant_b if (mb < ma) == lower_better else variant_a)
        # Confiance : |t| > 2 ≈ p<0.05 pour dof raisonnable ; on la borne.
        confidence = max(0.0, min(0.99, (abs(t) - 1.0) / 3.0)) * min(1.0, abs(d))
        winner = better if (abs(t) >= 2.0 and abs(d) >= 0.2) else None
        msg = (f"{variant_a} ({ma:.4g}, n={len(va)}) vs {variant_b} ({mb:.4g}, n={len(vb)}) "
               f"sur {metric} : {delta:+.1f}% | t={t:.2f} d={d:.2f} → "
               + (f"gagnant {winner} (confiance {confidence:.0%})" if winner else "non concluant"))
        return ABResult(dimension, metric, variant_a, variant_b, len(va), len(vb),
                        round(ma, 6), round(mb, 6), round(delta, 1), round(t, 3),
                        round(dof, 1), round(d, 3), winner, round(confidence, 3), msg)

    def auto(self, dimension: str = "model", metric: str = "cost_usd",
             top_k: int = 3) -> list[ABResult]:
        """Compare automatiquement les variantes les plus utilisées 2 à 2."""
        obs = self.lake.observations()
        counts: dict[str, int] = {}
        for o in obs:
            key = getattr(o, dimension, "") or ""
            if key:
                counts[key] = counts.get(key, 0) + 1
        top = [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_k]]
        out: list[ABResult] = []
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                out.append(self.compare(dimension, top[i], top[j], metric))
        return out

    def auto_smart(self, dimension: str = "model",
                   metrics: tuple[str, ...] = ("cost_usd", "latency_ms",
                                               "tokens_total", "failure_rate"),
                   top_k: int = 3) -> list[ABResult]:
        """Essaie les métriques dans l'ordre et retourne la première réellement
        instrumentée. Évite de rendre 3 lignes « 0 vs 0 » quand le coût est nul
        par construction (abonnement Claude, tiers gratuits)."""
        fallback: list[ABResult] = []
        for m in metrics:
            res = self.auto(dimension, m, top_k)
            if any(r.n_a >= self.min_n and (r.mean_a or r.mean_b) for r in res):
                return res
            fallback = fallback or res
        return fallback


# ── 7. MOTEUR D'OPTIMISATION ─────────────────────────────────────────────────

@dataclass
class Recommendation:
    priority: str               # P0 | P1 | P2
    category: str               # cost | latency | reliability | routing | data
    action: str
    rationale: str
    expected_gain: str
    confidence: float


class OptimizationEngine:
    """Traduit anomalies + prévisions + profils en actions concrètes.
    Règles explicites — auditables, pas de boîte noire."""

    def __init__(self, lake: DataLake):
        self.lake = lake
        self.detector = AnomalyDetector(lake)
        self.forecaster = Forecaster(lake, self.detector)
        self.profiler = AgentProfiler(lake)
        self.abtester = ABTester(lake)

    def recommend(self, budget_usd: Optional[float] = None) -> list[Recommendation]:
        recs: list[Recommendation] = []
        obs = self.lake.observations()

        if len(obs) < 10:
            recs.append(Recommendation(
                "P0", "data",
                "Instrumenter davantage : appeler forge_metrics.record()/observe() "
                "dans forge_llm, harness_engine et les nœuds LangGraph",
                f"Seulement {len(obs)} observations sur {self.lake.window_days:.0f}j — "
                "toute analyse en dessous de ~30 points est du bruit",
                "Fiabilité des analyses ×3", 0.95))

        cov = self.lake.coverage()
        if cov["weak_fields"]:
            recs.append(Recommendation(
                "P0", "data",
                "Compléter l'instrumentation des champs : " + ", ".join(cov["weak_fields"]),
                f"couverture {cov['overall']}% — champs sous 20 % : "
                + ", ".join(f"{k}={cov['pct'][k]}%" for k in cov["weak_fields"]),
                "Débloque anomalies/prévisions/A-B sur ces métriques", 0.99))
        for metric in ("cost_usd", "latency_ms", "tokens_total"):
            if len(self.detector._daily_series(obs, metric)) < 3:
                recs.append(Recommendation(
                    "P1", "data", f"Émettre {metric} sur au moins 3 jours distincts",
                    f"série journalière trop courte → prévision impossible sur {metric}",
                    "Active la prévision et la détection d'anomalie", 0.99))

        for a in self.detector.detect(min_severity="high")[:5]:
            cat = {"cost_usd": "cost", "tokens_total": "cost", "latency_ms": "latency"}.get(
                a.metric, "reliability")
            recs.append(Recommendation(
                "P0" if a.severity == "critical" else "P1", cat,
                f"Investiguer {a.dimension}={a.subject} sur {a.metric}",
                a.message, f"Retour baseline = {abs(a.delta_pct):.0f}% récupérés",
                min(0.95, 0.5 + abs(a.z) / 20)))

        f = self.forecaster.forecast("cost_usd", budget_usd)
        if f.trend == "rising" and f.r2 >= 0.3:
            recs.append(Recommendation(
                "P1", "cost", "Basculer les tâches de volume vers le tier gratuit "
                              "(MiMo/Gemini/Groq) via forge_llm",
                f.message, f"−{min(85, int(f.slope_per_day / max(f.current_daily,1e-9) * 100))}% "
                           "sur la trajectoire de coût", round(f.r2, 2)))
        if f.budget_exhausted_in_days is not None and f.budget_exhausted_in_days < 14:
            recs.append(Recommendation(
                "P0", "cost", "Plafonner le budget / activer le cache sémantique agressif",
                f"budget épuisé dans ~{f.budget_exhausted_in_days:.0f} jours au rythme actuel",
                "Évite la coupure de service", 0.9))

        cards = self.profiler.profile("agent")
        if cards:
            best, worst = cards[0], cards[-1]
            if best.subject != worst.subject and best.composite - worst.composite >= 20:
                recs.append(Recommendation(
                    "P1", "routing",
                    f"Router par défaut vers « {best.subject} » plutôt que « {worst.subject} »",
                    f"composite {best.composite} vs {worst.composite} "
                    f"(fiabilité {best.reliability} vs {worst.reliability}, "
                    f"coût {best.cost} vs {worst.cost})",
                    f"+{best.composite - worst.composite:.0f} pts de score composite",
                    min(0.9, 0.4 + min(best.calls, worst.calls) / 50)))
            for c in cards:
                if c.verdict == "avoid":
                    recs.append(Recommendation(
                        "P2", "reliability", f"Retirer ou corriger « {c.subject} »",
                        f"composite {c.composite}/100, succès {c.success_rate:.0%}, "
                        f"{c.calls} appels", "Moins d'échecs et de retries", 0.6))

        for r in self.abtester.auto_smart("model")[:3]:
            if r.winner:
                recs.append(Recommendation(
                    "P1", "routing", f"Préférer le modèle « {r.winner} »",
                    r.message, f"{abs(r.delta_pct):.0f}% de coût", r.confidence))

        order = {"P0": 0, "P1": 1, "P2": 2}
        recs.sort(key=lambda r: (order[r.priority], -r.confidence))
        return recs


# ── 7bis. POLITIQUE D'APPRENTISSAGE (bandit ε-greedy) ────────────────────────

@dataclass
class PolicyDecision:
    subject: str
    reason: str                 # exploit | explore | cold_start
    expected_reward: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)


class Policy:
    """Le volet « apprentissage » demandé, dans sa forme honnête.

    Pas de deep-RL : avec quelques dizaines d'exécutions par agent, un réseau
    n'apprendrait que du bruit. Un bandit ε-greedy sur la récompense
    (qualité − coût − temps) est le bon niveau : il converge vite, il est
    auditable, et il explore encore assez pour découvrir un meilleur agent.

    reward = 0.4·fiabilité + 0.2·coût + 0.2·vitesse + 0.2·efficacité  (0..1)
    — exactement le `composite` du Scorecard, normalisé.
    """

    def __init__(self, profiler: AgentProfiler, epsilon: float = 0.15):
        self.profiler = profiler
        self.epsilon = epsilon

    @staticmethod
    def reward(card: Scorecard) -> float:
        return round(card.composite / 100.0, 4)

    def choose(self, dimension: str = "agent",
               exclude: Optional[set[str]] = None,
               explore_seed: Optional[int] = None) -> Optional[PolicyDecision]:
        """Choisit un exécutant. `explore_seed` rend l'exploration reproductible
        (déterminisme requis pour les tests et pour rejouer une décision)."""
        cards = [c for c in self.profiler.profile(dimension)
                 if not exclude or c.subject not in exclude]
        if not cards:
            return None
        ranked = [(c.subject, self.reward(c)) for c in cards]
        best, best_r = ranked[0]

        # Cold start : un bras jamais assez tiré est prioritaire sur l'exploitation.
        cold = [c for c in cards if c.calls < self.profiler.min_calls * 2]
        if cold:
            c = cold[0]
            return PolicyDecision(c.subject, "cold_start", self.reward(c), ranked[:5])

        if explore_seed is not None and len(ranked) > 1:
            # exploration déterministe : hash du seed → indice dans la queue
            slot = explore_seed % 100
            if slot < int(self.epsilon * 100):
                alt = ranked[1 + (explore_seed % (len(ranked) - 1))]
                return PolicyDecision(alt[0], "explore", alt[1], ranked[:5])
        return PolicyDecision(best, "exploit", best_r, ranked[:5])


# ── 8. AGENT DATA SCIENTIST (façade) ─────────────────────────────────────────

class DataScientist:
    """Façade unique. C'est ce que le reste de la Forge importe."""

    def __init__(self, window_days: float = 30.0):
        self.lake = DataLake(window_days=window_days)
        self.engine = OptimizationEngine(self.lake)
        self.detector = self.engine.detector
        self.forecaster = self.engine.forecaster
        self.profiler = self.engine.profiler
        self.abtester = self.engine.abtester
        self.policy = Policy(self.profiler)

    # -- capacités ----------------------------------------------------------

    def choose_agent(self, dimension: str = "agent",
                     exclude: Optional[set[str]] = None,
                     explore_seed: Optional[int] = None) -> Optional[dict]:
        """Décision de routage apprise (bandit ε-greedy). None = pas de données."""
        d = self.policy.choose(dimension, exclude, explore_seed)
        return asdict(d) if d else None

    def anomalies(self, min_severity: str = "medium") -> list[dict]:
        return [asdict(a) for a in self.detector.detect(min_severity)]

    def forecasts(self, budget_usd: Optional[float] = None) -> list[dict]:
        return [asdict(f) for f in self.forecaster.forecast_all(budget_usd)]

    def scorecards(self, dimension: str = "agent") -> list[dict]:
        return [asdict(c) for c in self.profiler.profile(dimension)]

    def ab_test(self, dimension: str, a: str, b: str, metric: str = "cost_usd") -> dict:
        return asdict(self.abtester.compare(dimension, a, b, metric))

    def recommendations(self, budget_usd: Optional[float] = None) -> list[dict]:
        return [asdict(r) for r in self.engine.recommend(budget_usd)]

    def post_task_card(self, task: str = "", since_ts: Optional[float] = None) -> dict:
        """La carte post-tâche : dataset propriétaire du fonctionnement de la Forge.
        Format contractuel (cf. tâche source) :
          {what_worked, what_failed, cost, time, recommendation, confidence}"""
        obs = self.lake.observations()
        if since_ts:
            obs = [o for o in obs if o.ts >= since_ts]
        if task:
            tl = task.lower()
            scoped = [o for o in obs if tl in (o.task or "").lower()
                      or tl in (o.workflow or "").lower()]
            obs = scoped or obs
        if not obs:
            return {"task": task, "what_worked": None, "what_failed": None,
                    "cost": 0.0, "time_ms": 0.0, "recommendation": None,
                    "confidence": 0.0, "samples": 0}
        ok_rows = [o for o in obs if o.ok]
        ko_rows = [o for o in obs if not o.ok]

        def _top(rows: list[Observation]) -> Optional[str]:
            counts: dict[str, int] = {}
            for r in rows:
                key = r.agent or r.model or r.workflow or r.kind
                if key:
                    counts[key] = counts.get(key, 0) + 1
            return max(counts, key=counts.get) if counts else None

        recs = self.recommendations()
        lat = [o.latency_ms for o in obs if o.latency_ms > 0]
        # Confiance = volume d'échantillon × cohérence du taux de succès
        n = len(obs)
        rate = len(ok_rows) / n
        confidence = round(min(0.99, (1 - math.exp(-n / 20)) * (0.5 + abs(rate - 0.5))), 2)
        return {
            "task": task,
            "what_worked": _top(ok_rows),
            "what_failed": _top(ko_rows),
            "cost": round(sum(o.cost_usd for o in obs), 6),
            "tokens": sum(o.tokens_total for o in obs),
            "time_ms": round(sum(lat), 1),
            "avg_time_ms": round(statistics.fmean(lat), 1) if lat else 0.0,
            "success_rate": round(rate, 3),
            "recommendation": recs[0]["action"] if recs else None,
            "confidence": confidence,
            "samples": n,
        }

    # -- rapport complet ----------------------------------------------------

    def analyze(self, budget_usd: Optional[float] = None, persist: bool = True) -> dict:
        report = {
            "generated_at": time.time(),
            "window_days": self.lake.window_days,
            "inventory": self.lake.inventory(),
            "coverage": self.lake.coverage(),
            "anomalies": self.anomalies("medium"),
            "forecasts": self.forecasts(budget_usd),
            "agent_scorecards": self.scorecards("agent"),
            "model_scorecards": self.scorecards("model"),
            "ab_tests": [asdict(r) for r in self.abtester.auto_smart("model")],
            "recommendations": self.recommendations(budget_usd),
            "post_task_card": self.post_task_card(),
            "policy_decision": self.choose_agent(),
        }
        report["health"] = self._health(report)
        if persist:
            try:
                report_path = _report_path()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return report

    @staticmethod
    def _health(report: dict) -> dict:
        crit = sum(1 for a in report["anomalies"] if a["severity"] == "critical")
        high = sum(1 for a in report["anomalies"] if a["severity"] == "high")
        rows = report["inventory"]["rows"]
        cov = report["coverage"]
        # Le score de santé est PLAFONNÉ par la couverture d'instrumentation :
        # on ne déclare pas la Forge « saine » sur des métriques non mesurées.
        score = 100 - crit * 25 - high * 10
        if rows < 30:
            score -= 20
        score = max(0, min(100, min(score, int(cov["overall"]) + 30)))
        return {"score": score,
                "grade": "A" if score >= 85 else "B" if score >= 70 else
                         "C" if score >= 50 else "D",
                "critical_anomalies": crit, "high_anomalies": high,
                "instrumentation_coverage_pct": cov["overall"],
                "blind_metrics": cov["weak_fields"],
                "data_sufficiency": "ok" if rows >= 30 else "insufficient"}

    # -- advisory pour l'orchestrateur (0 token, ≤ 6 lignes) ----------------

    def advisory(self, task: str = "", domain: str = "", max_lines: int = 6) -> str:
        """Texte compact injecté dans le contexte de l'orchestrateur.
        Volontairement borné : c'est un réflexe, pas un rapport."""
        lines: list[str] = []
        try:
            for a in self.detector.detect("high")[:2]:
                lines.append(f"- ⚠ ANOMALIE {a.severity.upper()} : {a.message}")
            f = self.forecaster.forecast("cost_usd")
            if f.trend == "rising" and f.r2 >= 0.3:
                lines.append(f"- 📈 Coût en hausse ({f.slope_per_day:+.4g}/j, r²={f.r2:.2f}) "
                             f"→ router le volume vers le tier gratuit")
            best = self.profiler.best("agent")
            if best and best.verdict == "preferred":
                lines.append(f"- ✅ Exécutant recommandé : {best.subject} "
                             f"(composite {best.composite}/100, {best.calls} appels)")
            for c in self.profiler.profile("agent"):
                if c.verdict == "avoid":
                    lines.append(f"- ⛔ ÉVITER {c.subject} (composite {c.composite}/100, "
                                 f"succès {c.success_rate:.0%})")
                    break
            for r in self.engine.recommend()[:1]:
                if r.priority == "P0":
                    lines.append(f"- 🎯 P0 : {r.action} — {r.rationale}")
        except Exception:
            return ""
        if not lines:
            return ""
        return "\n\n[DATA SCIENTIST — analytics]\n" + "\n".join(lines[:max_lines])


_DS: Optional[DataScientist] = None


def get_data_scientist(window_days: float = 30.0) -> DataScientist:
    global _DS
    if _DS is None or _DS.lake.window_days != window_days:
        _DS = DataScientist(window_days=window_days)
    return _DS


def refresh() -> DataScientist:
    """Force la relecture des stores (à appeler après une exécution)."""
    ds = get_data_scientist()
    ds.lake.observations(refresh=True)
    return ds


# ── 9. RENDU TEXTE + CLI ─────────────────────────────────────────────────────

def render_report(report: dict) -> str:
    out: list[str] = []
    h, inv = report["health"], report["inventory"]
    out.append(f"╔═ DATA SCIENTIST — santé {h['grade']} ({h['score']}/100) ═╗")
    out.append(f"  Données : {inv['rows']} obs / {inv['span_days']}j — {inv['by_source']}"
               f"  [{h['data_sufficiency']}]")
    out.append(f"  Instrumentation : {h['instrumentation_coverage_pct']}% "
               f"— aveugle sur : {', '.join(h['blind_metrics']) or '—'}")

    out.append("\n── ANOMALIES ──")
    if report["anomalies"]:
        for a in report["anomalies"][:8]:
            out.append(f"  [{a['severity'].upper():8}] {a['message']}")
    else:
        out.append("  aucune anomalie ≥ medium")

    out.append("\n── PRÉVISIONS ──")
    for f in report["forecasts"]:
        out.append(f"  {f['message']}")

    out.append("\n── SCORECARDS AGENTS ──")
    if report["agent_scorecards"]:
        out.append(f"  {'agent':<28} {'comp':>5} {'eff':>5} {'fiab':>5} {'coût':>5} {'vit':>5}  n")
        for c in report["agent_scorecards"][:12]:
            out.append(f"  {c['subject'][:28]:<28} {c['composite']:>5} {c['efficiency']:>5} "
                       f"{c['reliability']:>5} {c['cost']:>5} {c['speed']:>5}  {c['calls']}"
                       f"  {c['verdict']}")
    else:
        out.append("  pas assez d'appels par agent (min 3)")

    out.append("\n── A/B TESTS (modèles, coût) ──")
    if report["ab_tests"]:
        for r in report["ab_tests"]:
            out.append(f"  {r['message']}")
    else:
        out.append("  pas assez de variantes mesurées")

    out.append("\n── RECOMMANDATIONS ──")
    for r in report["recommendations"][:10]:
        out.append(f"  [{r['priority']}][{r['category']}] {r['action']}")
        out.append(f"         ↳ {r['rationale']} | gain: {r['expected_gain']} "
                   f"| conf {r['confidence']:.0%}")

    c = report["post_task_card"]
    out.append("\n── CARTE POST-TÂCHE ──")
    out.append(f"  what_worked={c['what_worked']} | what_failed={c['what_failed']} | "
               f"cost=${c['cost']:.4f} | time={c['avg_time_ms']}ms | conf={c['confidence']}")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="forge_data_scientist",
                                description="Agent Data Scientist de La Forge (0 token LLM)")
    p.add_argument("command", nargs="?", default="report",
                   choices=["report", "anomalies", "forecast", "profile", "abtest",
                            "card", "export", "advisory", "choose"])
    p.add_argument("--window", type=float, default=30.0, help="fenêtre en jours")
    p.add_argument("--budget", type=float, default=None, help="budget USD pour la prévision")
    p.add_argument("--dim", default="model", help="dimension A/B ou profil")
    p.add_argument("--metric", default="cost_usd")
    p.add_argument("--a", default=None)
    p.add_argument("--b", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    ds = get_data_scientist(args.window)
    cmd = args.command

    if cmd == "report":
        rep = ds.analyze(budget_usd=args.budget)
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str)
              if args.json else render_report(rep))
        print(f"\n→ {_report_path()}")
    elif cmd == "anomalies":
        data = ds.anomalies("low")
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
              else "\n".join(f"[{a['severity']}] {a['message']}" for a in data) or "aucune")
    elif cmd == "forecast":
        data = ds.forecasts(args.budget)
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
              else "\n".join(f['message'] for f in data))
    elif cmd == "profile":
        data = ds.scorecards(args.dim if args.dim in ("agent", "model") else "agent")
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
              else "\n".join(f"{c['subject']:<30} {c['composite']:>6}/100  {c['verdict']}"
                             for c in data) or "pas assez de données")
    elif cmd == "abtest":
        if args.a and args.b:
            r = ds.ab_test(args.dim, args.a, args.b, args.metric)
            print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else r["message"])
        else:
            rs = [asdict(x) for x in ds.abtester.auto_smart(args.dim)]
            print(json.dumps(rs, ensure_ascii=False, indent=2) if args.json
                  else "\n".join(r["message"] for r in rs) or "pas assez de variantes")
    elif cmd == "choose":
        print(json.dumps(ds.choose_agent(args.dim if args.dim in ("agent", "model") else "agent"),
                         ensure_ascii=False, indent=2))
    elif cmd == "card":
        print(json.dumps(ds.post_task_card(), ensure_ascii=False, indent=2))
    elif cmd == "export":
        print(json.dumps(ds.lake.export_warehouse(), ensure_ascii=False, indent=2))
    elif cmd == "advisory":
        print(ds.advisory() or "(rien à signaler)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
