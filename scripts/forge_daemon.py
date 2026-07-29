#!/usr/bin/env python3
"""
forge_daemon.py — Boot daemon & Service Guardian for La Forge
=============================================================
Runs at Windows login. Starts Docker containers, warmup, web server.
Shows Tkinter popup if any service fails after 60s timeout.

Usage:
    python scripts/forge_daemon.py              # normal boot
    python scripts/forge_daemon.py --check      # health check only
    python scripts/forge_daemon.py --dry-run    # simulate without starting

Install as startup task:
    schtasks /create /tn "ForgeDaemon" /tr "pythonw scripts\\forge_daemon.py" /sc ONLOGON /rl HIGHEST
"""

from __future__ import annotations
import argparse
import logging
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from dataclasses import dataclass

FORGE_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = FORGE_ROOT / "08_LOGS" / "boot"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "daemon.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("forge_daemon")


# ═══════════════════════════════════════════════════════════════════════════════
# SERVICE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ServiceStatus:
    name: str
    ok: bool
    detail: str = ""


def check_redis() -> ServiceStatus:
    """Check if Redis is running."""
    try:
        import redis
        import os
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        r = redis.from_url(redis_url, socket_timeout=3)
        r.ping()
        return ServiceStatus("Redis", True, "PONG")
    except Exception as e:
        return ServiceStatus("Redis", False, str(e)[:100])


def check_docker() -> ServiceStatus:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return ServiceStatus("Docker", True, "running")
        return ServiceStatus("Docker", False, result.stderr.decode(errors="replace")[:100])
    except FileNotFoundError:
        return ServiceStatus("Docker", False, "docker not found")
    except Exception as e:
        return ServiceStatus("Docker", False, str(e)[:100])


def check_web_server(port: int = 7777) -> ServiceStatus:
    """Check if the Forge web server is responding."""
    try:
        import urllib.request
        req = urllib.request.Request(f"http://localhost:{port}/status")
        with urllib.request.urlopen(req, timeout=5):
            return ServiceStatus("WebServer", True, f"port {port}")
    except Exception as e:
        return ServiceStatus("WebServer", False, str(e)[:100])


def check_postgres() -> ServiceStatus:
    """Check if PostgreSQL is running (Docker or native)."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex(("localhost", 5432))
        s.close()
        if result == 0:
            return ServiceStatus("PostgreSQL", True, "port 5432 open")
        return ServiceStatus("PostgreSQL", False, "port 5432 closed")
    except Exception as e:
        return ServiceStatus("PostgreSQL", False, str(e)[:100])


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP SEQUENCE
# ═══════════════════════════════════════════════════════════════════════════════

def start_docker_containers() -> bool:
    """Start Forge Docker containers (Redis, PostgreSQL)."""
    containers = ["forge_redis", "forge_postgres"]
    success = True
    for name in containers:
        try:
            result = subprocess.run(
                ["docker", "start", name],
                capture_output=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                logger.info(f"  ✓ Docker: {name} started")
            else:
                logger.warning(f"  ✗ Docker: {name} — {result.stderr.decode(errors='replace')[:100]}")
                success = False
        except Exception as e:
            logger.warning(f"  ✗ Docker: {name} — {e}")
            success = False
    return success


def run_warmup() -> bool:
    """Run memory warmup script."""
    warmup_script = FORGE_ROOT / "scripts" / "forge_memory_warmup.py"
    if not warmup_script.exists():
        logger.info("  skip warmup (script not found)")
        return True
    try:
        result = subprocess.run(
            [sys.executable, str(warmup_script)],
            capture_output=True, timeout=120, cwd=str(FORGE_ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            logger.info("  ✓ Warmup complete")
            return True
        logger.warning(f"  ✗ Warmup failed: {result.stderr.decode(errors='replace')[:200]}")
        return False
    except Exception as e:
        logger.warning(f"  ✗ Warmup: {e}")
        return False


def start_web_server() -> bool:
    """Start the Forge web server as a background process."""
    server_script = FORGE_ROOT / "09_WEB" / "server.py"
    if not server_script.exists():
        logger.warning(f"  ✗ Server script not found: {server_script}")
        return False
    try:
        proc = subprocess.Popen(
            [sys.executable, str(server_script)],
            cwd=str(FORGE_ROOT),
            stdout=LOG_DIR.open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        logger.info(f"  ✓ Web server started (PID {proc.pid})")
        return True
    except Exception as e:
        logger.warning(f"  ✗ Web server: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TKINTER GUARDIAN POPUP
# ═══════════════════════════════════════════════════════════════════════════════

def show_guardian_popup(failed_services: list[ServiceStatus]) -> None:
    """Show a Tkinter popup with failed services and retry button."""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        logger.error("Tkinter not available — showing console fallback")
        for svc in failed_services:
            print(f"  ❌ {svc.name}: {svc.detail}")
        return

    root = tk.Tk()
    root.title("Forge Guardian — Service Alert")
    root.geometry("450x350")
    root.configure(bg="#1a1a2e")
    root.attributes("-topmost", True)

    # Header
    header = tk.Label(
        root, text="⚠ FORGE GUARDIAN", font=("Consolas", 16, "bold"),
        fg="#ff6b6b", bg="#1a1a2e",
    )
    header.pack(pady=(15, 5))

    subtitle = tk.Label(
        root, text="Services en échec au démarrage :",
        fg="#aaa", bg="#1a1a2e", font=("Consolas", 10),
    )
    subtitle.pack()

    # Failed services list
    for svc in failed_services:
        frame = tk.Frame(root, bg="#2d2d44", padx=10, pady=5)
        frame.pack(fill="x", padx=20, pady=3)

        tk.Label(
            frame, text=f"❌ {svc.name}",
            fg="#ff6b6b", bg="#2d2d44", font=("Consolas", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            frame, text=svc.detail[:80],
            fg="#888", bg="#2d2d44", font=("Consolas", 8),
            anchor="w",
        ).pack(fill="x")

    # Retry button
    def retry():
        root.destroy()
        logger.info("[Guardian] Retry requested — restarting failed services...")
        # Re-run the daemon
        subprocess.Popen(
            [sys.executable, str(Path(__file__))],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    btn_frame = tk.Frame(root, bg="#1a1a2e")
    btn_frame.pack(pady=15)

    retry_btn = tk.Button(
        btn_frame, text="🔄 Relancer les services", command=retry,
        bg="#4ecdc4", fg="#1a1a2e", font=("Consolas", 11, "bold"),
        padx=20, pady=8, relief="flat", cursor="hand2",
    )
    retry_btn.pack(side="left", padx=5)

    logs_btn = tk.Button(
        btn_frame, text="📋 Ouvrir logs",
        command=lambda: os.startfile(str(LOG_DIR)),
        bg="#555", fg="#fff", font=("Consolas", 10),
        padx=15, pady=8, relief="flat", cursor="hand2",
    )
    logs_btn.pack(side="left", padx=5)

    root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def health_check() -> list[ServiceStatus]:
    """Run all health checks."""
    checks = [
        check_docker,
        check_redis,
        check_postgres,
        check_web_server,
    ]
    results = []
    for check_fn in checks:
        try:
            results.append(check_fn())
        except Exception as e:
            results.append(ServiceStatus(check_fn.__name__, False, str(e)))
    return results


def main():
    parser = argparse.ArgumentParser(description="Forge Daemon & Guardian")
    parser.add_argument("--check", action="store_true", help="Health check only")
    parser.add_argument("--dry-run", action="store_true", help="Simulate boot")
    parser.add_argument("--timeout", type=int, default=60, help="Guardian popup timeout (s)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("FORGE DAEMON — Boot sequence starting")
    logger.info("=" * 60)

    if args.check:
        results = health_check()
        for r in results:
            icon = "✓" if r.ok else "❌"
            logger.info(f"  {icon} {r.name}: {r.detail}")
        failed = [r for r in results if not r.ok]
        if failed:
            logger.warning(f"{len(failed)} service(s) down!")
            sys.exit(1)
        logger.info("All services healthy!")
        return

    if args.dry_run:
        logger.info("[DRY RUN] Would start: Docker → Warmup → WebServer")
        return

    # Step 1: Start Docker containers
    logger.info("\n── Starting Docker containers ──")
    start_docker_containers()

    # Step 2: Memory warmup
    logger.info("\n── Memory warmup ──")
    run_warmup()

    # Step 3: Start web server
    logger.info("\n── Starting web server ──")
    start_web_server()

    # Step 4: Wait and health check
    logger.info(f"\n── Waiting {args.timeout}s for services to stabilize ──")
    time.sleep(args.timeout)

    results = health_check()
    failed = [r for r in results if not r.ok]

    if failed:
        logger.warning(f"\n⚠ {len(failed)} service(s) failed after {args.timeout}s:")
        for r in failed:
            logger.warning(f"  ❌ {r.name}: {r.detail}")
        show_guardian_popup(failed)
    else:
        logger.info("\n✓ All services healthy!")


if __name__ == "__main__":
    main()
