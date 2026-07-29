#!/usr/bin/env python3
"""
pipeline_runner_mimo.py — Orchestration caveman Mimo (Pilier A+C bilan v5)
==========================================================================
Usage:
  python scripts/pipeline_runner_mimo.py --mode optimize --caveman
  python scripts/pipeline_runner_mimo.py --mode research --task "niche IA créateurs"
  python scripts/pipeline_runner_mimo.py --status

Modes:
  optimize   → cycle MARKET SCAN → PRODUCT HUNT → BUILD (idempotent)
  research   → RESEARCH agent uniquement
  close      → CLOSER_PRO agent uniquement

Flags:
  --caveman          stdout caveman court (défaut)
  --verbose          stdout complet (compat ascendante)
  --no-caveman       alias --verbose
  --cycles INT       max LangGraph cycles [défaut: 8]
  --seed INT         seed aléatoire pour idempotence [défaut: 42]
  --status           affiche daily_report et quitte

Idempotence : déjà_drafted détecté via slug canonique (crafty_slug).
UTF-8 stdout configuré automatiquement.
"""

from __future__ import annotations
import argparse
import datetime
import sys
import time
from pathlib import Path

# ── UTF-8 stdout (fix B7) ──────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FORGE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(FORGE_ROOT))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

from caveman_logger import get_caveman, reset_caveman
from crafty_slug import prospect_slug
from mimo_token_tracker import log_run, daily_report

# ── Import forge (graceful degradation) ───────────────────────────────────
try:
    from forge_agents.forge_llm import forge_call, LLMTier
    from forge_agents.graphify_checkpointer import graphify_query, graphify_index
    _FORGE_OK = True
except ImportError as _e:
    _FORGE_OK = False
    _FORGE_ERR = str(_e)


# ── Already-drafted idempotence (fix C5) ──────────────────────────────────

_drafted_slugs: set[str] = set()

def already_drafted(name: str, domain: str = "") -> bool:
    slug = prospect_slug(name, domain)
    return slug in _drafted_slugs

def mark_drafted(name: str, domain: str = "") -> str:
    slug = prospect_slug(name, domain)
    _drafted_slugs.add(slug)
    return slug


# ── Mode handlers ──────────────────────────────────────────────────────────

def run_optimize(caveman, cycles: int, seed: int) -> dict:
    caveman.log("ORCH", "START", "optimize", cycles=cycles, seed=seed)

    if not _FORGE_OK:
        caveman.log("ORCH", "ERR", "forge_import", reason=_FORGE_ERR[:60])
        return {"status": "error", "reason": "import_missing"}

    import random
    random.seed(seed)

    # Simule 30 prospects (remplacer par vrai pipeline)
    prospects = [f"prospect_{i:03d}" for i in range(30)]
    drafted = 0
    skipped = 0

    t0 = time.monotonic()
    for p in prospects:
        if already_drafted(p):
            skipped += 1
            caveman.log("PIPELINE", "SKIP", p, reason="already_drafted")
            continue
        # Appel forge HAIKU tier
        result = forge_call(f"Draft email for {p}", tier=LLMTier.HAIKU)
        if result:
            mark_drafted(p)
            drafted += 1
            caveman.log("PIPELINE", "DRAFTED", p)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    caveman.log("ORCH", "DONE", "optimize",
                drafted=drafted, skipped=skipped, ms=elapsed_ms)
    return {"drafted": drafted, "skipped": skipped, "ms": elapsed_ms}


def run_research(caveman, task: str) -> dict:
    caveman.log("ORCH", "START", "research", task=task[:40])
    if not _FORGE_OK:
        caveman.log("ORCH", "ERR", "forge_import")
        return {"status": "error"}

    t0 = time.monotonic()
    result = forge_call(task, tier=LLMTier.HAIKU, task_type="research")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    graphify_index(result or "", agent="RESEARCH", cycle=0)
    caveman.log("RESEARCH", "DONE", "indexed", ms=elapsed_ms)
    return {"status": "ok", "ms": elapsed_ms}


def run_close(caveman, task: str) -> dict:
    caveman.log("ORCH", "START", "close", task=task[:40])
    if not _FORGE_OK:
        caveman.log("ORCH", "ERR", "forge_import")
        return {"status": "error"}

    t0 = time.monotonic()
    result = forge_call(task, tier=LLMTier.HAIKU, task_type="close")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    caveman.log("CLOSER", "DONE", "close", ms=elapsed_ms)
    return {"status": "ok", "ms": elapsed_ms}


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Mimo pipeline runner (caveman mode)")
    p.add_argument("--mode", choices=["optimize", "research", "close"],
                   default="optimize")
    p.add_argument("--task", default="")
    p.add_argument("--cycles", type=int, default=8)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--caveman", dest="caveman", action="store_true", default=True)
    p.add_argument("--verbose", "--no-caveman", dest="caveman", action="store_false")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    if args.status:
        daily_report(quiet=False)
        return

    session_id = datetime.date.today().isoformat()
    caveman = reset_caveman(session_id)

    t_start = time.monotonic()
    result: dict = {}

    try:
        if args.mode == "optimize":
            result = run_optimize(caveman, args.cycles, args.seed)
        elif args.mode == "research":
            result = run_research(caveman, args.task or "market scan IA créateurs")
        elif args.mode == "close":
            result = run_close(caveman, args.task or "close prospect")
    finally:
        elapsed_total = int((time.monotonic() - t_start) * 1000)
        stdout_bytes = caveman._stdout_bytes
        caveman.flush_agg()
        caveman.alert_if_overrun()
        caveman.close()

        log_run(
            prospects_total=30 if args.mode == "optimize" else 0,
            prospects_drafted=result.get("drafted", 0),
            stdout_bytes=stdout_bytes,
            pipeline_ms=elapsed_total,
            session_id=session_id,
            extra={"mode": args.mode},
        )

    if not args.caveman:
        import json
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
