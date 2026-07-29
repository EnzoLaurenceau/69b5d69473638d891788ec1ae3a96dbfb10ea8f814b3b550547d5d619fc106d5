"""
token_sprint_tracker.py — Boucle Data Science pour l'optimisation des tokens
=============================================================================

Pipeline :
  1) record_sprint()       → persiste estimation vs réel dans token_sprints (JSON fallback)
  2) historical_estimate() → interroge les sprints passés pour affiner les estimations
  3) detect_variance()     → calcule l'erreur de prédiction et déclenche auto-refinement
  4) sprint_summary()      → agrège les métriques par sprint pour le dashboard

Stockage : PostgreSQL si disponible, sinon JSON fallback dans 05_STATE/token_sprints.json
"""

from __future__ import annotations

import json
import datetime
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("token_sprint")

FORGE_ROOT = Path(__file__).parent.parent.parent


def SPRINT_STATE_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("token_sprints.json")


SPRINT_STATE_PATH().parent.mkdir(parents=True, exist_ok=True)


# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class SprintRecord:
    sprint_id: str
    task_id: str
    task_type: str  # normalized: market_scan, build, research, etc.
    model: str
    tokens_estimated_in: int
    tokens_estimated_out: int
    tokens_actual_in: int
    tokens_actual_out: int
    cost_estimated_usd: float
    cost_actual_usd: float
    hallucination_detected: bool = False
    latency_ms: float = 0.0
    variance_pct: float = 0.0  # (actual - estimated) / estimated * 100
    auto_refinement_triggered: bool = False
    ts: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())


# ─── Persistence (JSON fallback — no Postgres dependency) ────────────────────

def _load_sprints() -> list[dict]:
    if SPRINT_STATE_PATH().exists():
        try:
            return json.loads(SPRINT_STATE_PATH().read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return []


def _save_sprints(records: list[dict]) -> None:
    try:
        SPRINT_STATE_PATH().write_text(
            json.dumps(records, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"[token_sprint] write failed: {e}")


# ─── Core API ────────────────────────────────────────────────────────────────

def record_sprint(
    sprint_id: str,
    task_id: str,
    task_type: str,
    model: str,
    estimated_in: int,
    estimated_out: int,
    actual_in: int,
    actual_out: int,
    cost_estimated: float,
    cost_actual: float,
    hallucination_detected: bool = False,
    latency_ms: float = 0.0,
) -> SprintRecord:
    """Persiste une comparaison estimation vs réel."""
    variance = 0.0
    if cost_estimated > 0:
        variance = (cost_actual - cost_estimated) / cost_estimated * 100

    rec = SprintRecord(
        sprint_id=sprint_id,
        task_id=task_id,
        task_type=task_type,
        model=model,
        tokens_estimated_in=estimated_in,
        tokens_estimated_out=estimated_out,
        tokens_actual_in=actual_in,
        tokens_actual_out=actual_out,
        cost_estimated_usd=cost_estimated,
        cost_actual_usd=cost_actual,
        hallucination_detected=hallucination_detected,
        latency_ms=latency_ms,
        variance_pct=round(variance, 2),
        auto_refinement_triggered=abs(variance) > 25.0,
    )

    records = _load_sprints()
    records.append(asdict(rec))
    # Keep last 500 records
    if len(records) > 500:
        records = records[-500:]
    _save_sprints(records)

    if rec.auto_refinement_triggered:
        logger.info(
            f"[token_sprint] AUTO-REFINEMENT triggered for {task_type}/{model}: "
            f"variance {variance:+.1f}%"
        )

    return rec


def historical_estimate(task_type: str, model: str) -> Optional[dict]:
    """
    Query past sprints for the same task_type+model to produce a data-driven estimate.
    Returns {estimated_in, estimated_out, confidence, sample_count} or None.
    """
    records = _load_sprints()
    matches = [
        r for r in records
        if r.get("task_type") == task_type and r.get("model") == model
    ]

    if len(matches) < 2:
        return None  # Not enough data for statistical confidence

    # Weighted average: more recent records weigh more
    weights = [1.0 + i * 0.1 for i in range(len(matches))]
    total_weight = sum(weights)

    avg_in = sum(r["tokens_actual_in"] * w for r, w in zip(matches, weights)) / total_weight
    avg_out = sum(r["tokens_actual_out"] * w for r, w in zip(matches, weights)) / total_weight

    # Confidence based on sample size and variance consistency
    variances = [abs(r.get("variance_pct", 0)) for r in matches[-10:]]
    avg_variance = sum(variances) / len(variances) if variances else 100
    confidence = min(1.0, len(matches) / 10.0) * max(0.1, 1.0 - avg_variance / 100.0)

    return {
        "estimated_in": int(avg_in),
        "estimated_out": int(avg_out),
        "confidence": round(confidence, 3),
        "sample_count": len(matches),
        "avg_variance_pct": round(avg_variance, 2),
    }


def detect_variance(sprint_record: SprintRecord) -> dict:
    """
    Analyse un enregistrement et retourne les recommandations d'optimisation.
    """
    recs = []
    v = sprint_record.variance_pct

    if v > 25:
        recs.append({
            "action": "compress_prompt",
            "reason": f"Over-budget {v:+.1f}%",
            "target": sprint_record.model,
            "severity": "high" if v > 50 else "medium",
        })
        recs.append({
            "action": "restrict_output_format",
            "reason": f"Output variance high — force concise format",
            "target": sprint_record.task_type,
        })

    if v > 50:
        recs.append({
            "action": "downgrade_model",
            "reason": f"Severe over-budget {v:+.1f}% — switch to smaller model",
            "target": sprint_record.model,
            "from_model": sprint_record.model,
            "to_model": "gemini-2.5-flash",  # default downgrade
        })

    if v < -30:
        recs.append({
            "action": "upgrade_estimate",
            "reason": f"Under-budget {v:.1f}% — estimation too generous, tighten for accuracy",
            "target": sprint_record.task_type,
        })

    if sprint_record.hallucination_detected:
        recs.append({
            "action": "enable_neuro_symbolic_guard",
            "reason": "Hallucination detected in this task type",
            "target": sprint_record.task_type,
        })

    return {
        "variance_pct": v,
        "auto_refinement": sprint_record.auto_refinement_triggered,
        "recommendations": recs,
    }


def sprint_summary(sprint_id: str = "") -> dict:
    """
    Agrège les métriques pour le dashboard.
    Si sprint_id vide, agrège tous les sprints.
    """
    records = _load_sprints()
    if sprint_id:
        records = [r for r in records if r.get("sprint_id") == sprint_id]

    if not records:
        return {
            "total_records": 0,
            "sprints": {},
            "overall": {},
        }

    # Group by sprint_id
    by_sprint: dict[str, list] = {}
    for r in records:
        sid = r.get("sprint_id", "default")
        by_sprint.setdefault(sid, []).append(r)

    sprint_data = {}
    for sid, recs in by_sprint.items():
        total_est_cost = sum(r.get("cost_estimated_usd", 0) for r in recs)
        total_act_cost = sum(r.get("cost_actual_usd", 0) for r in recs)
        total_est_in = sum(r.get("tokens_estimated_in", 0) for r in recs)
        total_act_in = sum(r.get("tokens_actual_in", 0) for r in recs)
        total_est_out = sum(r.get("tokens_estimated_out", 0) for r in recs)
        total_act_out = sum(r.get("tokens_actual_out", 0) for r in recs)
        variances = [r.get("variance_pct", 0) for r in recs]
        avg_variance = sum(variances) / len(variances) if variances else 0
        hallucinations = sum(1 for r in recs if r.get("hallucination_detected"))
        refinements = sum(1 for r in recs if r.get("auto_refinement_triggered"))

        sprint_data[sid] = {
            "record_count": len(recs),
            "estimated_cost_usd": round(total_est_cost, 4),
            "actual_cost_usd": round(total_act_cost, 4),
            "estimated_tokens_in": total_est_in,
            "actual_tokens_in": total_act_in,
            "estimated_tokens_out": total_est_out,
            "actual_tokens_out": total_act_out,
            "avg_variance_pct": round(avg_variance, 2),
            "hallucination_count": hallucinations,
            "refinement_count": refinements,
            "task_types": list(set(r.get("task_type", "") for r in recs)),
        }

    # Overall stats
    all_variances = [r.get("variance_pct", 0) for r in records]
    overall = {
        "total_records": len(records),
        "sprint_count": len(by_sprint),
        "avg_variance_pct": round(sum(all_variances) / len(all_variances), 2) if all_variances else 0,
        "total_estimated_cost": round(sum(r.get("cost_estimated_usd", 0) for r in records), 4),
        "total_actual_cost": round(sum(r.get("cost_actual_usd", 0) for r in records), 4),
        "hallucination_rate": round(
            sum(1 for r in records if r.get("hallucination_detected")) / len(records) * 100, 2
        ) if records else 0,
        "refinement_rate": round(
            sum(1 for r in records if r.get("auto_refinement_triggered")) / len(records) * 100, 2
        ) if records else 0,
    }

    return {
        "total_records": len(records),
        "sprints": sprint_data,
        "overall": overall,
    }


# ─── Import existing token logs ─────────────────────────────────────────────

def import_existing_logs() -> int:
    """
    One-shot import of existing 08_LOGS/tokens/*.json into sprint records.
    Returns count of records imported.
    """
    try:
        from .token_tracker import normalize_task, ESTIMATES_BY_TASK, compute_cost, Model
    except ImportError:
        from token_tracker import normalize_task, ESTIMATES_BY_TASK, compute_cost, Model

    logs_dir = FORGE_ROOT / "08_LOGS" / "tokens"
    if not logs_dir.exists():
        return 0

    existing = _load_sprints()
    existing_keys = {(r.get("sprint_id"), r.get("task_id"), r.get("model")) for r in existing}
    imported = 0

    for f in sorted(logs_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        task = data.get("task", "")
        session_id = data.get("session_id", f.stem)
        raw_logs = data.get("raw_logs", [])
        task_type = normalize_task(task)

        # Get heuristic estimates for this task type
        heuristic_estimates = {}
        if task_type in ESTIMATES_BY_TASK:
            for model, in_tok, out_tok in ESTIMATES_BY_TASK[task_type]:
                model_val = model.value if hasattr(model, 'value') else str(model)
                heuristic_estimates[model_val] = {
                    "input": in_tok,
                    "output": out_tok,
                    "cost": compute_cost(model, in_tok, out_tok),
                }

        for log in raw_logs:
            model = log.get("model", "unknown")
            key = (session_id, task[:50], model)
            if key in existing_keys:
                continue

            est = heuristic_estimates.get(model, {})
            est_in = est.get("input", 0)
            est_out = est.get("output", 0)
            est_cost = est.get("cost", 0.0)

            actual_in = log.get("input_tokens", 0)
            actual_out = log.get("output_tokens", 0)
            actual_cost = log.get("cost_usd", 0.0)

            variance = 0.0
            if est_cost > 0:
                variance = (actual_cost - est_cost) / est_cost * 100

            rec = SprintRecord(
                sprint_id=session_id,
                task_id=task[:50],
                task_type=task_type,
                model=model,
                tokens_estimated_in=est_in,
                tokens_estimated_out=est_out,
                tokens_actual_in=actual_in,
                tokens_actual_out=actual_out,
                cost_estimated_usd=est_cost,
                cost_actual_usd=actual_cost,
                latency_ms=log.get("latency_ms", 0),
                ts=log.get("timestamp", ""),
                variance_pct=round(variance, 2),
                auto_refinement_triggered=abs(variance) > 25.0,
            )

            existing.append(asdict(rec))
            existing_keys.add(key)
            imported += 1

    if imported:
        _save_sprints(existing)
        logger.info(f"[token_sprint] Imported {imported} records from existing logs")

    return imported


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
    from forge_agents.token_tracker import normalize_task, ESTIMATES_BY_TASK, compute_cost, Model

    # Import existing logs
    count = import_existing_logs()
    print(f"Imported {count} existing records")

    # Show summary
    summary = sprint_summary()
    print(f"\nTotal records: {summary['total_records']}")
    print(f"Sprints: {len(summary['sprints'])}")
    if summary['overall']:
        o = summary['overall']
        print(f"Avg variance: {o['avg_variance_pct']}%")
        print(f"Est cost: ${o['total_estimated_cost']}")
        print(f"Act cost: ${o['total_actual_cost']}")
        print(f"Hallucination rate: {o['hallucination_rate']}%")
        print(f"Refinement rate: {o['refinement_rate']}%")

    # Show per-sprint breakdown
    for sid, sd in summary['sprints'].items():
        print(f"\n  Sprint: {sid}")
        print(f"    Records: {sd['record_count']}")
        print(f"    Est: ${sd['estimated_cost_usd']} | Act: ${sd['actual_cost_usd']}")
        print(f"    Variance: {sd['avg_variance_pct']}%")
