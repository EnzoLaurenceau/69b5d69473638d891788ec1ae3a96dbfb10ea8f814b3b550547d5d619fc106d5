"""
forge_versioning.py — Version Tracking & Auto-Indexing for Forge
================================================================
Section 2 du plan Hermes B : Indexation Automatique Post-Tâche
& Suivi des Cycles d'Évolution.

Features:
  1. Auto-indexing post-task (gitnexus analyze in background thread)
  2. Version tracking in forge_runtime.json
  3. Version increment on prompt modifications

Usage:
    from forge_agents.forge_versioning import get_versioning
    v = get_versioning()
    v.maybe_auto_index(files_written=True)  # non-blocking
    v.increment_version()  # on prompt edit
    info = v.get_version_info()  # for dashboard
"""

from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("ForgeVersioning")

FORGE_ROOT = Path(__file__).parent.parent.parent
RUNTIME_PATH = FORGE_ROOT / "05_STATE" / "forge_runtime.json"


class ForgeVersioning:
    """Version tracking + auto-indexing for the Forge."""

    def __init__(self):
        self._lock = threading.Lock()
        self._indexing_thread: threading.Thread | None = None
        self._runtime = self._load_runtime()

    def _load_runtime(self) -> dict:
        """Load forge_runtime.json or create default."""
        try:
            if RUNTIME_PATH.exists():
                data = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
                # Ensure version fields exist
                data.setdefault("version", "1.0.0")
                data.setdefault("cycle", 0)
                data.setdefault("last_update", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
                data.setdefault("last_index", None)
                data.setdefault("index_count", 0)
                return data
        except Exception as e:
            logger.warning(f"[Versioning] Failed to load runtime: {e}")

        return {
            "version": "1.0.0",
            "cycle": 0,
            "last_update": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_index": None,
            "index_count": 0,
        }

    def _save_runtime(self):
        """Persist forge_runtime.json."""
        try:
            RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._runtime["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            RUNTIME_PATH.write_text(
                json.dumps(self._runtime, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[Versioning] Failed to save runtime: {e}")

    def get_version_info(self) -> dict:
        """Get current version info (for dashboard)."""
        return {
            "version": self._runtime.get("version", "1.0.0"),
            "cycle": self._runtime.get("cycle", 0),
            "last_update": self._runtime.get("last_update"),
            "last_index": self._runtime.get("last_index"),
            "index_count": self._runtime.get("index_count", 0),
        }

    def increment_version(self, reason: str = "prompt_edit"):
        """Increment version number (called on prompt modifications)."""
        with self._lock:
            version = self._runtime.get("version", "1.0.0")
            parts = version.split(".")
            try:
                # Increment patch version (1.0.4 → 1.0.5)
                parts[-1] = str(int(parts[-1]) + 1)
                new_version = ".".join(parts)
            except (ValueError, IndexError):
                new_version = "1.0.1"

            self._runtime["version"] = new_version
            self._runtime["cycle"] = self._runtime.get("cycle", 0) + 1
            self._save_runtime()
            logger.info(f"[Versioning] {version} → {new_version} (cycle {self._runtime['cycle']}, reason: {reason})")
            return new_version

    def maybe_auto_index(self, files_written: bool = False):
        """
        Auto-index after task execution if files were written.
        Runs gitnexus analyze in a non-blocking thread.
        """
        if not files_written:
            return

        # Don't start if already indexing
        if self._indexing_thread and self._indexing_thread.is_alive():
            logger.debug("[Versioning] Indexing already in progress, skipping")
            return

        def _run_index():
            try:
                logger.info("[Versioning] Starting auto-index (gitnexus analyze)...")
                result = subprocess.run(
                    ["npx", "gitnexus", "analyze"],
                    capture_output=True, text=True,
                    cwd=str(FORGE_ROOT), timeout=60
                )
                if result.returncode == 0:
                    with self._lock:
                        self._runtime["last_index"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        self._runtime["index_count"] = self._runtime.get("index_count", 0) + 1
                        self._save_runtime()
                    logger.info(f"[Versioning] Auto-index complete (count: {self._runtime['index_count']})")
                else:
                    logger.warning(f"[Versioning] gitnexus analyze failed: {result.stderr[:200]}")
            except FileNotFoundError:
                logger.debug("[Versioning] npx/gitnexus not found, skipping auto-index")
            except subprocess.TimeoutExpired:
                logger.warning("[Versioning] gitnexus analyze timed out (60s)")
            except Exception as e:
                logger.debug(f"[Versioning] Auto-index error: {e}")

        self._indexing_thread = threading.Thread(target=_run_index, daemon=True)
        self._indexing_thread.start()


# Singleton
_instance: ForgeVersioning | None = None


def get_versioning() -> ForgeVersioning:
    global _instance
    if _instance is None:
        _instance = ForgeVersioning()
    return _instance
