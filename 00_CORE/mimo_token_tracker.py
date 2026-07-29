"""
mimo_token_tracker.py — Métrique réelle Mimo (Pilier D bilan v5)
================================================================
log_run() → logs/tokens/run_<date>.json  (jamais de ×22 fantôme)
daily_report(quiet=True) → 1-liner caveman stdout

Différence vs token_tracker.py :
  - Centré sur runs/octets/prospects (pipeline Mimo)
  - Pas de TokenUsage LLM (ça reste dans token_tracker.py)
  - daily_report() peut fonctionner sans LangGraph
"""

from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

FORGE_ROOT = Path(__file__).parent.parent
RUNS_DIR = FORGE_ROOT / "08_LOGS" / "tokens"
RUNS_DIR.mkdir(parents=True, exist_ok=True)


def log_run(
    *,
    prospects_total: int,
    prospects_drafted: int,
    stdout_bytes: int,
    pipeline_ms: int,
    session_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Path:
    """Enregistre les métriques réelles d'un run pipeline dans un fichier JSON."""
    sid = session_id or datetime.date.today().isoformat()
    ts = datetime.datetime.utcnow().isoformat()
    payload = {
        "session_id": sid,
        "timestamp": ts,
        "prospects_total": prospects_total,
        "prospects_drafted": prospects_drafted,
        "stdout_bytes": stdout_bytes,
        "pipeline_ms": pipeline_ms,
        **(extra or {}),
    }
    path = RUNS_DIR / f"run_{sid}.json"
    # Accumule dans une liste si le fichier existe déjà
    existing: list = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        except Exception:
            existing = []
    existing.append(payload)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def daily_report(quiet: bool = True) -> str:
    """
    Lit tous les runs du jour et produit un résumé.
    quiet=True → 1-liner caveman ; quiet=False → tableau.
    """
    today = datetime.date.today().isoformat()
    path = RUNS_DIR / f"run_{today}.json"
    if not path.exists():
        line = f"MIMO DAILY no_runs_today date={today}"
        if not quiet:
            print(line)
        return line

    runs: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    total_runs     = len(runs)
    total_drafted  = sum(r.get("prospects_drafted", 0) for r in runs)
    total_prospects= sum(r.get("prospects_total", 0) for r in runs)
    avg_bytes      = int(sum(r.get("stdout_bytes", 0) for r in runs) / max(total_runs, 1))
    avg_ms         = int(sum(r.get("pipeline_ms", 0) for r in runs) / max(total_runs, 1))

    if quiet:
        line = (f"MIMO DAILY runs={total_runs} drafted={total_drafted}/{total_prospects} "
                f"avg_bytes={avg_bytes} avg_ms={avg_ms}")
        print(line)
        return line

    # Verbose
    lines = [
        f"=== Mimo Daily Report {today} ===",
        f"  Runs        : {total_runs}",
        f"  Drafted     : {total_drafted} / {total_prospects}",
        f"  Avg stdout  : {avg_bytes} bytes/run",
        f"  Avg latency : {avg_ms} ms/run",
        f"  Log file    : {path}",
    ]
    report = "\n".join(lines)
    print(report)
    return report
