"""
forge_autostart_gui.py — Pop-up Gardien Système (Tkinter)
===========================================================
Plan A §2.3 : Alerte visuelle si le boot de la Forge échoue.

Vérifie les ports critiques (7777, 6380, 5433) après 60s au boot.
Si un port est bloqué → pop-up avec boutons "Relancer" et "Logs".

Usage:
    python scripts/forge_autostart_gui.py
    # Ou appelé depuis forge_autostart.bat après timeout
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

FORGE_ROOT = Path(__file__).parent.parent
LOG_DIR = FORGE_ROOT / "08_LOGS" / "boot"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Ports critiques à vérifier
CRITICAL_PORTS = {
    7777: "Forge Server (FastAPI/Uvicorn)",
    6380: "Redis (tg-bot-workflow)",
    5433: "PostgreSQL (tg-bot-workflow)",
}

# Délai avant vérification (secondes)
BOOT_DELAY = int(os.environ.get("FORGE_BOOT_DELAY", "60"))

# Couleurs HELB Design System
HELB_BLUE = "#1A3F6B"
HELB_ORANGE = "#F7A711"
HELB_GREEN = "#28A745"
HELB_RED = "#DC3545"
BG_DARK = "#1a1a2e"
FG_LIGHT = "#e0e0e0"


# ─── Port Check ──────────────────────────────────────────────────────────────

def check_port(port: int, host: str = "localhost", timeout: float = 3.0) -> bool:
    """Vérifie si un port est ouvert."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def check_all_ports() -> dict[int, bool]:
    """Vérifie tous les ports critiques."""
    results = {}
    for port in CRITICAL_PORTS:
        results[port] = check_port(port)
    return results


# ─── Logging ─────────────────────────────────────────────────────────────────

def log_event(message: str):
    """Écrit dans le log de boot."""
    log_file = LOG_DIR / "gui_guardian.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


# ─── Actions ─────────────────────────────────────────────────────────────────

def restart_services():
    """Relance les services Docker et le serveur Forge."""
    log_event("User clicked: Restart Services")
    results = []

    # 1. Docker services
    try:
        r = subprocess.run(
            ["docker", "start", "redis", "postgres"],
            capture_output=True, text=True, timeout=30
        )
        results.append(f"Docker: {r.stdout.strip() or r.stderr.strip()}")
    except FileNotFoundError:
        results.append("Docker: not found")
    except subprocess.TimeoutExpired:
        results.append("Docker: timeout")
    except Exception as e:
        results.append(f"Docker: {e}")

    # 2. Forge server
    try:
        server_script = FORGE_ROOT / "09_WEB" / "server.py"
        if server_script.exists():
            subprocess.Popen(
                [sys.executable, str(server_script)],
                cwd=str(FORGE_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
            )
            results.append("Forge server: started")
        else:
            results.append("Forge server: server.py not found")
    except Exception as e:
        results.append(f"Forge server: {e}")

    log_event(f"Restart results: {results}")
    return results


def open_logs():
    """Ouvre le dossier de logs."""
    log_event("User clicked: Open Logs")
    log_path = str(LOG_DIR)
    try:
        if sys.platform == "win32":
            os.startfile(log_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", log_path])
        else:
            subprocess.Popen(["xdg-open", log_path])
    except Exception as e:
        log_event(f"Failed to open logs: {e}")


# ─── GUI ─────────────────────────────────────────────────────────────────────

class ForgeGuardianGUI:
    """Pop-up d'alerte pour les erreurs de boot."""

    def __init__(self, port_status: dict[int, bool]):
        self.port_status = port_status
        self.failed_ports = [p for p, ok in port_status.items() if not ok]

        self.root = tk.Tk()
        self.root.title("Forge Guardian — Boot Alert")
        self.root.geometry("500x400")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)

        # Icon (optional)
        try:
            self.root.iconbitmap(default="")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        self._build_ui()

    def _build_ui(self):
        """Construit l'interface."""
        # Header
        header = tk.Frame(self.root, bg=HELB_RED, height=60)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="⚠ FORGE BOOT ALERT",
            font=("Segoe UI", 16, "bold"), fg="white", bg=HELB_RED
        ).pack(expand=True)

        # Status frame
        status_frame = tk.Frame(self.root, bg=BG_DARK, padx=20, pady=10)
        status_frame.pack(fill="x")

        tk.Label(
            status_frame,
            text=f"{len(self.failed_ports)} service(s) not responding after {BOOT_DELAY}s:",
            font=("Segoe UI", 11), fg=FG_LIGHT, bg=BG_DARK
        ).pack(anchor="w")

        # Port details
        for port, ok in self.port_status.items():
            service = CRITICAL_PORTS.get(port, f"Port {port}")
            color = HELB_GREEN if ok else HELB_RED
            status = "✓ OK" if ok else "✗ FAILED"

            row = tk.Frame(status_frame, bg=BG_DARK)
            row.pack(fill="x", pady=2)

            tk.Label(
                row, text=f"  {status}",
                font=("Segoe UI", 10, "bold"), fg=color, bg=BG_DARK, width=10
            ).pack(side="left")

            tk.Label(
                row, text=f"{service} (:{port})",
                font=("Segoe UI", 10), fg=FG_LIGHT, bg=BG_DARK
            ).pack(side="left")

        # Log preview
        log_frame = tk.Frame(self.root, bg=BG_DARK, padx=20, pady=5)
        log_frame.pack(fill="both", expand=True)

        tk.Label(
            log_frame, text="Recent boot logs:",
            font=("Segoe UI", 10), fg=FG_LIGHT, bg=BG_DARK
        ).pack(anchor="w")

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=6, bg="#0d0d1a", fg=FG_LIGHT,
            font=("Consolas", 9), state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, pady=(5, 0))

        # Load recent logs
        self._load_recent_logs()

        # Buttons
        btn_frame = tk.Frame(self.root, bg=BG_DARK, padx=20, pady=15)
        btn_frame.pack(fill="x")

        tk.Button(
            btn_frame, text="🔄 Relancer les services",
            font=("Segoe UI", 11, "bold"),
            bg=HELB_ORANGE, fg="white",
            activebackground="#e6950a", activeforeground="white",
            relief="flat", padx=20, pady=8,
            command=self._on_restart
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btn_frame, text="📂 Ouvrir les Logs",
            font=("Segoe UI", 11),
            bg=HELB_BLUE, fg="white",
            activebackground="#153358", activeforeground="white",
            relief="flat", padx=20, pady=8,
            command=open_logs
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btn_frame, text="✕ Fermer",
            font=("Segoe UI", 11),
            bg="#555", fg="white",
            activebackground="#333", activeforeground="white",
            relief="flat", padx=20, pady=8,
            command=self.root.destroy
        ).pack(side="right")

    def _load_recent_logs(self):
        """Charge les logs récents."""
        log_file = LOG_DIR / "autostart.log"
        if not log_file.exists():
            return
        try:
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            recent = lines[-10:]  # Last 10 lines
            self.log_text.config(state="normal")
            self.log_text.insert("end", "\n".join(recent))
            self.log_text.config(state="disabled")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def _on_restart(self):
        """Callback bouton Relancer."""
        log_event("Restart initiated from GUI")
        results = restart_services()
        messagebox.showinfo(
            "Restart Results",
            "\n".join(results),
            parent=self.root
        )
        # Re-check ports after restart
        time.sleep(3)
        new_status = check_all_ports()
        still_failed = [p for p, ok in new_status.items() if not ok]
        if not still_failed:
            messagebox.showinfo("Success", "All services are now running!", parent=self.root)
            self.root.destroy()
        else:
            messagebox.showwarning(
                "Still Failing",
                f"Ports still down: {still_failed}\nCheck logs for details.",
                parent=self.root
            )

    def show(self):
        """Affiche la fenêtre."""
        self.root.mainloop()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    """Point d'entrée principal."""
    log_event(f"Guardian started — waiting {BOOT_DELAY}s before check...")

    # Attendre le délai de boot
    time.sleep(BOOT_DELAY)

    # Vérifier les ports
    log_event("Checking critical ports...")
    port_status = check_all_ports()
    failed = [p for p, ok in port_status.items() if not ok]

    log_event(f"Port check results: {port_status}")

    if failed:
        log_event(f"ALERT: {len(failed)} port(s) failed: {failed}")
        # Afficher le pop-up
        gui = ForgeGuardianGUI(port_status)
        gui.show()
    else:
        log_event("All ports OK — no alert needed")


if __name__ == "__main__":
    main()
