#!/usr/bin/env python3
"""
pull_metrics.py — agrège les runs LangSmith des 2 bras + score d'autonomie.
==========================================================================
  python pull_metrics.py                 # les 2 projets + grade des builds
  python pull_metrics.py --since 2h      # fenêtre temporelle (défaut: 24h)

Sort un tableau comparatif: tokens (in/out), latence, coût, nb runs, autonomie.
Nécessite LANGSMITH_API_KEY. Le score d'autonomie vient de grade.py (déterministe,
n'a pas besoin de LangSmith).
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

HERE = Path(__file__).resolve().parent
FORGE_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from grade import grade  # scoring autonomie déterministe

PROJECTS = {"nu": "ab-website-nu", "forge": "ab-website-forge"}


def _load_dotenv():
    for p in (FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_since(s: str) -> timedelta:
    unit = s[-1].lower()
    n = float(s[:-1])
    return {"h": timedelta(hours=n), "d": timedelta(days=n), "m": timedelta(minutes=n)}.get(unit, timedelta(hours=24))


def ls_metrics(project: str, after) -> dict:
    from langsmith import Client
    client = Client()
    runs = list(client.list_runs(project_name=project, start_time=after))
    tin = sum((r.prompt_tokens or 0) for r in runs)
    tout = sum((r.completion_tokens or 0) for r in runs)
    cost = sum(float(r.total_cost or 0) for r in runs)
    lat = [(r.end_time - r.start_time).total_seconds() for r in runs if r.end_time and r.start_time]
    return {"runs": len(runs), "tokens_in": tin, "tokens_out": tout,
            "cost_usd": round(cost, 4), "latency_s_total": round(sum(lat), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="24h")
    args = ap.parse_args()
    _load_dotenv()
    after = datetime.now(timezone.utc) - _parse_since(args.since)

    rows = {}
    for arm, project in PROJECTS.items():
        m = {"runs": "?", "tokens_in": "?", "tokens_out": "?", "cost_usd": "?", "latency_s_total": "?"}
        try:
            m = ls_metrics(project, after)
        except Exception as e:
            print(f"  [!] LangSmith {project}: {e}")
        build = HERE / "builds" / arm
        m["autonomy"] = grade(build)["autonomy_score"] if build.exists() else "—"
        rows[arm] = m

    cols = ["runs", "tokens_in", "tokens_out", "cost_usd", "latency_s_total", "autonomy"]
    print(f"\n{'métrique':<18}{'NU':>14}{'FORGE':>14}")
    print("-" * 46)
    for c in cols:
        print(f"{c:<18}{str(rows['nu'][c]):>14}{str(rows['forge'][c]):>14}")
    print()


if __name__ == "__main__":
    main()
