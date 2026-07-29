#!/usr/bin/env python3
"""
forge_bootstrap.py — Activation autonome de la stack Forge (optiforge)
=====================================================================
But : N'IMPORTE QUELLE IA appliquant le profil de la Forge (Claude, Hermes…)
appelle ce script au début de session et tout s'active tout seul — aucune
action manuelle de l'utilisateur requise.

Séquence idempotente :
  1. Force l'encodage UTF-8 (console Windows cp1252).
  2. Vérifie le CLI Docker. Absent → mode secours (rien à faire, on sort OK).
  3. Daemon Docker down → tente de démarrer Docker Desktop (Win/Mac) et attend.
  4. `docker compose up -d` (postgres pgvector + redis).
  5. Attend que PG+Redis soient sains (probe forge_db, ~90s max).
  6. Schéma appliqué automatiquement (forge_db._ensure_schema à la connexion).
  7. Installe les deps Python manquantes (redis/psycopg) si besoin.
  8. Rejoue le WAL si des writes étaient en attente.
  9. Affiche la santé finale.

Usage :
  python scripts/forge_bootstrap.py            # bootstrap complet
  python scripts/forge_bootstrap.py --no-deps  # sans pip install
  python scripts/forge_bootstrap.py --down      # arrête les containers
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent
COMPOSE = FORGE_ROOT / "00_CORE" / "db" / "docker-compose.yml"
sys.path.insert(0, str(FORGE_ROOT))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


# ─── Docker ───────────────────────────────────────────────────────────────────

def docker_available() -> bool:
    return shutil.which("docker") is not None


def daemon_up() -> bool:
    code, _ = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
    return code == 0


def start_docker_desktop() -> bool:
    """Démarre Docker Desktop selon l'OS. Retourne True si une tentative a eu lieu."""
    sysname = platform.system()
    if sysname == "Windows":
        candidates = [
            r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
            os.path.expandvars(r"%ProgramFiles%\Docker\Docker\Docker Desktop.exe"),
        ]
        for exe in candidates:
            if Path(exe).exists():
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
    elif sysname == "Darwin":
        if Path("/Applications/Docker.app").exists():
            subprocess.Popen(["open", "-a", "Docker"])
            return True
    else:  # Linux : tente le service (peut nécessiter les droits)
        code, _ = _run(["systemctl", "start", "docker"], timeout=20)
        return code == 0
    return False


def wait_daemon(max_wait: int = 90) -> bool:
    log(f"attente du daemon Docker (≤{max_wait}s)…")
    t0 = time.time()
    while time.time() - t0 < max_wait:
        if daemon_up():
            log("daemon Docker prêt.")
            return True
        time.sleep(4)
    return False


def compose_up() -> bool:
    log("docker compose up -d (postgres + redis)…")
    code, out = _run(["docker", "compose", "-f", str(COMPOSE), "up", "-d"], timeout=180)
    if code != 0:
        log(f"⚠ compose échec : {out[:300]}")
    return code == 0


def compose_down() -> None:
    log("docker compose down…")
    _run(["docker", "compose", "-f", str(COMPOSE), "down"], timeout=120)


# ─── Santé forge_db ───────────────────────────────────────────────────────────

def wait_db_healthy(max_wait: int = 90) -> dict:
    """Re-probe forge_db jusqu'à ce que PG+Redis soient up (ou timeout)."""
    log(f"attente santé PG+Redis (≤{max_wait}s)…")
    t0 = time.time()
    health = {}
    while time.time() - t0 < max_wait:
        # Nouveau probe à chaque tour (instance fraîche)
        import importlib
        from forge_agents import forge_db as _fdb
        importlib.reload(_fdb)
        db = _fdb.ForgeDB()
        health = db.health()
        if health["redis"] == "up" and health["postgres"] == "up":
            log("PG+Redis up. Schéma appliqué.")
            n = db.wal_replay()
            if n:
                log(f"WAL rejoué : {n} writes.")
            return health
        time.sleep(4)
    return health


# ─── Dépendances Python ───────────────────────────────────────────────────────

def ensure_deps() -> None:
    """
    Vérifie les deps CORE (sans lesquelles rien ne tourne, même en mode secours
    SQLite/JSON) + les deps PG/Redis (optionnelles, seulement si Docker est up).
    Avant ce fix : seules redis/psycopg étaient vérifiées -> `--bootstrap` pouvait
    dire "OK" alors que `import langgraph` plantait juste après (paquet jamais
    installé). Zero Manual Infra Mode veut dire zéro surprise ici aussi.
    """
    core_missing = []
    for mod, pip_name in (
        ("langgraph", "langgraph>=0.2.0"),
        ("langgraph.checkpoint.sqlite", "langgraph-checkpoint-sqlite>=1.0.0"),
        ("langchain_core", "langchain-core>=0.3.0"),
        ("anthropic", "anthropic>=0.40.0"),
        ("numpy", "numpy>=1.24.0"),
        ("dotenv", "python-dotenv>=1.0.0"),
    ):
        try:
            __import__(mod)
        except ImportError:
            core_missing.append(pip_name)

    if core_missing:
        log(f"install deps CORE manquantes : {core_missing}")
        _run([sys.executable, "-m", "pip", "install", "-q"] + core_missing, timeout=300)

    pg_missing = []
    for mod in ("redis", "psycopg"):
        try:
            __import__(mod)
        except ImportError:
            pg_missing.append(mod)
    if pg_missing:
        log(f"install deps PG/Redis manquantes : {pg_missing}")
        _run([sys.executable, "-m", "pip", "install", "-q",
              "redis>=5", "psycopg[binary]>=3", "pgvector>=0.3",
              "langgraph-checkpoint-postgres>=2"], timeout=300)


# ─── Orchestration ────────────────────────────────────────────────────────────

def bootstrap(install_deps: bool = True) -> int:
    log(f"Forge root : {FORGE_ROOT}")

    if install_deps:
        ensure_deps()

    if not docker_available():
        log("Docker absent → la Forge tourne en MODE SECOURS (SQLite/graph.json). OK.")
        return 0

    if not daemon_up():
        log("daemon Docker down → démarrage de Docker Desktop…")
        if start_docker_desktop():
            if not wait_daemon():
                log("⚠ daemon non prêt à temps → MODE SECOURS pour cette session.")
                return 0
        else:
            log("⚠ impossible de démarrer Docker → MODE SECOURS.")
            return 0

    compose_up()
    health = wait_db_healthy()
    log(f"santé finale : redis={health.get('redis')} postgres={health.get('postgres')} "
        f"mode={health.get('fallback')}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Bootstrap autonome de la stack Forge")
    ap.add_argument("--no-deps", action="store_true", help="Ne pas installer les deps Python")
    ap.add_argument("--down", action="store_true", help="Arrêter les containers et sortir")
    args = ap.parse_args()
    if args.down:
        compose_down()
        return
    sys.exit(bootstrap(install_deps=not args.no_deps))


if __name__ == "__main__":
    main()
