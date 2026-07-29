#!/usr/bin/env python3
"""
forge_memory_warmup.py — Warm-up complet des 5 couches mémoire de La Forge
===========================================================================
Conçu pour s'exécuter au boot Windows (via Task Scheduler) OU manuellement.
Orchestre le démarrage séquentiel de TOUTES les couches mémoire :

  L3 infra  → Docker Desktop + PostgreSQL(pgvector) + Redis
  L3 db     → Health check + WAL replay
  L1 hot    → Cervelet (réflexes ancrés) + SemanticCache
  L2 warm   → TurboVec 4-bit index + Nexus Bridge (embedded)
  L4 cold   → Knowledge Base integrity check
  L0 cache  → Cache Orchestrator + LMCache init

Usage :
  python scripts/forge_memory_warmup.py            # warm-up complet
  python scripts/forge_memory_warmup.py --dry-run   # simulation sans side-effects
  python scripts/forge_memory_warmup.py --status    # état de chaque couche

Idempotent : peut être relancé sans risque. Dégradation gracieuse partout.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

FORGE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(FORGE_ROOT))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

# Force UTF-8 (Windows cp1252)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

BOOT_LOG_DIR = FORGE_ROOT / "08_LOGS" / "boot"
BOOT_LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────────────

log_file = BOOT_LOG_DIR / f"boot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(log_file), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ForgeWarmup")


# ─── Result tracker ──────────────────────────────────────────────────────────

class WarmupReport:
    """Collecte le statut de chaque couche."""

    def __init__(self):
        self.layers: dict[str, dict] = {}
        self.start_time = time.time()

    def record(self, layer: str, status: str, detail: str = "", elapsed: float = 0.0):
        self.layers[layer] = {
            "status": status,
            "detail": detail,
            "elapsed_s": round(elapsed, 2),
        }
        icon = "✅" if status == "ok" else ("⚠️" if status == "degraded" else "❌")
        logger.info(f"  {icon} {layer}: {status} — {detail}")

    def summary(self) -> dict:
        total = round(time.time() - self.start_time, 2)
        ok = sum(1 for v in self.layers.values() if v["status"] == "ok")
        degraded = sum(1 for v in self.layers.values() if v["status"] == "degraded")
        failed = sum(1 for v in self.layers.values() if v["status"] == "failed")
        return {
            "total_elapsed_s": total,
            "ok": ok,
            "degraded": degraded,
            "failed": failed,
            "layers": self.layers,
            "timestamp": datetime.datetime.now().isoformat(),
        }

    def print_banner(self):
        s = self.summary()
        print(f"\n{'='*60}")
        print(f"  FORGE MEMORY WARMUP — COMPLETE")
        print(f"  Total: {s['total_elapsed_s']}s | OK: {s['ok']} | Degraded: {s['degraded']} | Failed: {s['failed']}")
        print(f"{'='*60}\n")


# ═════════════════════════════════════════════════════════════════════════════
# LAYER WARMUP FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════


def warmup_l3_infra(report: WarmupReport, dry_run: bool = False):
    """L3 — Docker Desktop + PostgreSQL + Redis (via forge_bootstrap)."""
    t0 = time.time()
    if dry_run:
        report.record("L3_infra", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        sys.path.insert(0, str(FORGE_ROOT / "scripts"))
        from forge_bootstrap import (
            docker_available, daemon_up, start_docker_desktop,
            wait_daemon, compose_up, wait_db_healthy, ensure_deps
        )

        # 1. Deps Python
        ensure_deps()

        # 2. Docker
        if not docker_available():
            report.record("L3_infra", "degraded",
                          "Docker absent → mode secours SQLite/JSON", time.time() - t0)
            return

        if not daemon_up():
            logger.info("  Docker daemon down → démarrage Docker Desktop…")
            start_docker_desktop()
            if not wait_daemon(max_wait=120):
                report.record("L3_infra", "degraded",
                              "Docker daemon timeout → mode secours", time.time() - t0)
                return

        # 3. Compose up
        compose_up()

        # 4. Wait healthy
        health = wait_db_healthy(max_wait=90)
        pg = health.get("postgres", "down")
        rd = health.get("redis", "down")

        if pg == "up" and rd == "up":
            report.record("L3_infra", "ok",
                          f"PG={pg} Redis={rd} WAL_replayed", time.time() - t0)
        else:
            report.record("L3_infra", "degraded",
                          f"PG={pg} Redis={rd} → fallback actif", time.time() - t0)

    except Exception as e:
        report.record("L3_infra", "degraded", f"bootstrap error: {e}", time.time() - t0)


def warmup_l3_db(report: WarmupReport, dry_run: bool = False):
    """L3 — forge_db health + WAL replay."""
    t0 = time.time()
    if dry_run:
        report.record("L3_db", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.forge_db import get_db
        db = get_db()
        health = db.health()

        # WAL replay si writes en attente
        wal_pending = health.get("wal_pending", 0)
        if wal_pending > 0:
            n = db.wal_replay()
            logger.info(f"  WAL rejoué : {n} writes")

        mode = health.get("fallback", "unknown")
        report.record("L3_db", "ok",
                      f"mode={mode} redis={health.get('redis')} pg={health.get('postgres')}",
                      time.time() - t0)

    except Exception as e:
        report.record("L3_db", "degraded", f"forge_db: {e}", time.time() - t0)


def warmup_l1_cervelet(report: WarmupReport, dry_run: bool = False):
    """L1 — Cervelet : charge les réflexes ancrés en RAM."""
    t0 = time.time()
    if dry_run:
        report.record("L1_cervelet", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.cervelet import CerveletArtificiel

        cervelet = CerveletArtificiel()

        # Charger l'état persisté
        state_file = FORGE_ROOT / ".nexus" / "cervelet_state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                reflexes_count = len(data.get("reflexes", {}))
                report.record("L1_cervelet", "ok",
                              f"{reflexes_count} réflexes chargés depuis {state_file.name}",
                              time.time() - t0)
            except Exception as e:
                report.record("L1_cervelet", "degraded",
                              f"state corrompu: {e}", time.time() - t0)
        else:
            report.record("L1_cervelet", "ok",
                          "aucun état persisté (premier boot)", time.time() - t0)

    except Exception as e:
        report.record("L1_cervelet", "degraded", f"cervelet: {e}", time.time() - t0)


def warmup_l1_shared_brain(report: WarmupReport, dry_run: bool = False):
    """L1 — Shared Brain : GlobalKernelStore + MCPProxyCache init."""
    t0 = time.time()
    if dry_run:
        report.record("L1_shared_brain", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.forge_shared_brain import (
            GlobalKernelStore, MCPProxyCache, SharedReasoningState
        )

        # Initialiser les singletons
        kernel_store = GlobalKernelStore()
        mcp_cache = MCPProxyCache()
        reasoning = SharedReasoningState()

        report.record("L1_shared_brain", "ok",
                      f"KernelStore + MCPCache + ReasoningState initialisés",
                      time.time() - t0)

    except Exception as e:
        report.record("L1_shared_brain", "degraded",
                      f"shared_brain: {e}", time.time() - t0)


def warmup_l2_turbovec(report: WarmupReport, dry_run: bool = False):
    """L2 — TurboVec 4-bit semantic index."""
    t0 = time.time()
    if dry_run:
        report.record("L2_turbovec", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.turbovec_brain import get_turbovec_brain

        # get_turbovec_brain() → __init__ → _load_state() automatique
        brain = get_turbovec_brain()
        pressure = brain.token_pressure()
        n_vectors = pressure.get("vectors_stored", 0)
        tokens = pressure.get("session_tokens", 0)

        report.record("L2_turbovec", "ok",
                      f"{n_vectors} vecteurs, {tokens} tokens session",
                      time.time() - t0)

    except Exception as e:
        report.record("L2_turbovec", "degraded", f"turbovec: {e}", time.time() - t0)


def warmup_l2_nexus(report: WarmupReport, dry_run: bool = False):
    """L2 — Nexus Bridge (embedded VFS)."""
    t0 = time.time()
    if dry_run:
        report.record("L2_nexus", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.nexus_bridge import memory_retrieve

        # Trigger la connexion lazy (nexus embedded ou fallback JSON)
        result = memory_retrieve("warmup_probe", k=1, max_chars=100)

        nexus_data = FORGE_ROOT / "nexus-data"
        if nexus_data.exists():
            report.record("L2_nexus", "ok",
                          f"Nexus embedded connecté (data_dir={nexus_data})",
                          time.time() - t0)
        else:
            report.record("L2_nexus", "degraded",
                          "Nexus absent → fallback JSON/SQLite", time.time() - t0)

    except Exception as e:
        report.record("L2_nexus", "degraded", f"nexus: {e}", time.time() - t0)


def warmup_l2_semantic_cache(report: WarmupReport, dry_run: bool = False):
    """L2 — SemanticCache (SimHash dedup)."""
    t0 = time.time()
    if dry_run:
        report.record("L2_semantic_cache", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.semantic_cache import get_cache

        cache = get_cache()
        stats = cache.stats()
        report.record("L2_semantic_cache", "ok",
                      f"entries={stats['entries']} hits={stats['total_hits']}",
                      time.time() - t0)

    except Exception as e:
        report.record("L2_semantic_cache", "degraded",
                      f"semantic_cache: {e}", time.time() - t0)


def warmup_l4_knowledge_base(report: WarmupReport, dry_run: bool = False):
    """L4 — Knowledge Base (cold memory) integrity check."""
    t0 = time.time()
    if dry_run:
        report.record("L4_knowledge_base", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.kb_manager import get_kb_manager

        kb = get_kb_manager()
        stats = kb.stats()
        n_skills = stats.get("total_skills", 0)
        n_patterns = stats.get("total_patterns", 0)

        report.record("L4_knowledge_base", "ok",
                      f"{n_skills} skills, {n_patterns} patterns indexés",
                      time.time() - t0)

    except Exception as e:
        report.record("L4_knowledge_base", "degraded",
                      f"kb_manager: {e}", time.time() - t0)


def warmup_l0_cache_orchestrator(report: WarmupReport, dry_run: bool = False):
    """L0 — Cache Orchestrator (cascade L0→L4)."""
    t0 = time.time()
    if dry_run:
        report.record("L0_cache_orchestrator", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.forge_cache_orchestrator import get_cache_orchestrator

        orch = get_cache_orchestrator()
        stats = orch.stats()
        report.record("L0_cache_orchestrator", "ok",
                      f"orchestrator prêt — {stats}",
                      time.time() - t0)

    except Exception as e:
        report.record("L0_cache_orchestrator", "degraded",
                      f"cache_orch: {e}", time.time() - t0)


def warmup_experience_db(report: WarmupReport, dry_run: bool = False):
    """Experience DB — BigSet (workflow scores, component health)."""
    t0 = time.time()
    if dry_run:
        report.record("experience_db", "ok", "dry-run (skipped)", time.time() - t0)
        return

    try:
        from forge_agents.forge_experience_db import get_experience_db

        # get_experience_db() → __init__ → _load() automatique
        exp_db = get_experience_db()
        stats = exp_db.summary()
        n_exp = stats.get("total_experiences", 0)
        n_wf = stats.get("workflows_tracked", 0)

        report.record("experience_db", "ok",
                      f"{n_exp} expériences, {n_wf} workflows",
                      time.time() - t0)

    except Exception as e:
        report.record("experience_db", "degraded",
                      f"experience_db: {e}", time.time() - t0)


def warmup_checkpoint_state(report: WarmupReport, dry_run: bool = False):
    """State — Charge le dernier checkpoint (05_STATE/checkpoint.json)."""
    t0 = time.time()
    cp_path = FORGE_ROOT / "05_STATE" / "checkpoint.json"

    if not cp_path.exists():
        report.record("checkpoint", "ok", "aucun checkpoint (session fraîche)", time.time() - t0)
        return

    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        session = data.get("session_id", "?")
        level = data.get("level", "?")
        cycle = data.get("cycle", 0)
        report.record("checkpoint", "ok",
                      f"session={session} level={level} cycle={cycle}",
                      time.time() - t0)

    except Exception as e:
        report.record("checkpoint", "degraded", f"checkpoint corrompu: {e}", time.time() - t0)


# ═════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════════════

def run_warmup(dry_run: bool = False) -> dict:
    """Exécute le warm-up complet de toutes les couches mémoire."""
    report = WarmupReport()

    logger.info("=" * 60)
    logger.info("  FORGE MEMORY WARMUP — START")
    logger.info(f"  Mode: {'DRY-RUN' if dry_run else 'LIVE'}")
    logger.info(f"  Forge root: {FORGE_ROOT}")
    logger.info("=" * 60)

    # Ordre de démarrage : infra d'abord, puis couches de haut en bas
    steps = [
        ("L3 — Infrastructure (Docker + PG + Redis)", warmup_l3_infra),
        ("L3 — Database health + WAL",                warmup_l3_db),
        ("L1 — Cervelet (réflexes ancrés)",           warmup_l1_cervelet),
        ("L1 — Shared Brain (Kernel + MCP + Reasoning)", warmup_l1_shared_brain),
        ("L2 — TurboVec 4-bit index",                 warmup_l2_turbovec),
        ("L2 — Nexus Bridge (embedded VFS)",           warmup_l2_nexus),
        ("L2 — Semantic Cache",                        warmup_l2_semantic_cache),
        ("L4 — Knowledge Base (cold memory)",          warmup_l4_knowledge_base),
        ("L0 — Cache Orchestrator (cascade)",          warmup_l0_cache_orchestrator),
        ("     Experience DB (BigSet)",                warmup_experience_db),
        ("     Checkpoint State",                      warmup_checkpoint_state),
    ]

    for label, fn in steps:
        logger.info(f"\n─── {label} ───")
        try:
            fn(report, dry_run=dry_run)
        except Exception as e:
            logger.error(f"  CRASH dans {label}: {e}")

    report.print_banner()

    # Sauvegarder le rapport
    summary = report.summary()
    report_path = BOOT_LOG_DIR / "last_warmup.json"
    try:
        report_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Mettre à jour daemon_state.json
    daemon_state = FORGE_ROOT / "05_STATE" / "daemon_state.json"
    try:
        daemon_state.write_text(
            json.dumps({
                "warmup_at": datetime.datetime.now().isoformat(),
                "status": "ok" if summary["failed"] == 0 else "degraded",
                "ok": summary["ok"],
                "degraded": summary["degraded"],
                "failed": summary["failed"],
                "elapsed_s": summary["total_elapsed_s"],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    return summary


def cmd_status():
    """Affiche l'état du dernier warm-up."""
    report_path = BOOT_LOG_DIR / "last_warmup.json"
    if not report_path.exists():
        print("Aucun warm-up précédent trouvé.")
        return

    data = json.loads(report_path.read_text(encoding="utf-8"))
    print(f"\n  Dernier warm-up : {data.get('timestamp', '?')}")
    print(f"  Durée           : {data.get('total_elapsed_s', '?')}s")
    print(f"  OK: {data.get('ok', 0)} | Degraded: {data.get('degraded', 0)} | Failed: {data.get('failed', 0)}")
    print()
    for name, info in data.get("layers", {}).items():
        icon = "✅" if info["status"] == "ok" else ("⚠️" if info["status"] == "degraded" else "❌")
        print(f"  {icon} {name}: {info['detail']} ({info['elapsed_s']}s)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Forge Memory Warmup — Démarre toutes les couches mémoire"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulation sans effets de bord")
    parser.add_argument("--status", action="store_true",
                        help="Affiche l'état du dernier warm-up")
    args = parser.parse_args()

    if args.status:
        cmd_status()
        return

    summary = run_warmup(dry_run=args.dry_run)
    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
