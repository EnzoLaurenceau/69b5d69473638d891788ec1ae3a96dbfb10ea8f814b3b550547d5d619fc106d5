"""forge_claude_health.py — Health tracker pour Claude CLI/API
============================================================

Problème : Claude peut être indisponible pour plusieurs raisons :
  - Not logged in (session OAuth expirée)
  - Rate limited (429, quota épuisé, reset demain)
  - Server error (500/502/503)
  - Network down

Ce module :
  1. Teste la disponibilité de Claude au démarrage (warm-up check)
  2. Cache le statut avec TTL adaptatif (pas de re-test inutile)
  3. Détecte le type d'erreur et estime le reset time
  4. Fournit un fallback automatique vers MiMo/autres providers

Usage :
    from forge_agents.forge_claude_health import claude_health, ClaudeStatus

    health = claude_health()
    if health.is_available():
        # utiliser Claude
    else:
        # fallback MiMo
        print(health.fallback_reason())

Kill switch : FORGE_CLAUDE_CHECK=0 → skip le health check (assume available).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ClaudeHealth")

FORGE_ROOT = Path(__file__).parent.parent.parent
HEALTH_FILE = FORGE_ROOT / "05_STATE" / "identity" / "claude_health.json"


class ClaudeStatus(str, Enum):
    """État de santé de Claude."""
    UNKNOWN  = "unknown"    # pas encore testé
    READY    = "ready"      # fonctionnel
    NOT_LOGGED_IN = "not_logged_in"  # session OAuth expirée
    RATE_LIMITED  = "rate_limited"   # quota épuisé
    SERVER_ERROR  = "server_error"   # erreur serveur (5xx)
    NETWORK_ERROR = "network_error"  # réseau down
    CLI_MISSING   = "cli_missing"    # CLI non installé


# ── Patterns d'erreur Claude CLI ──────────────────────────────────────────────

_ERROR_PATTERNS: list[tuple[str, ClaudeStatus]] = [
    # Rate limiting
    (r"rate.?limit", ClaudeStatus.RATE_LIMITED),
    (r"429", ClaudeStatus.RATE_LIMITED),
    (r"quota.?exceed", ClaudeStatus.RATE_LIMITED),
    (r"too many requests", ClaudeStatus.RATE_LIMITED),
    (r"usage.?limit", ClaudeStatus.RATE_LIMITED),
    (r"overloaded", ClaudeStatus.RATE_LIMITED),
    # Auth
    (r"not logged in", ClaudeStatus.NOT_LOGGED_IN),
    (r"unauthorized", ClaudeStatus.NOT_LOGGED_IN),
    (r"401", ClaudeStatus.NOT_LOGGED_IN),
    (r"authentication", ClaudeStatus.NOT_LOGGED_IN),
    (r"login", ClaudeStatus.NOT_LOGGED_IN),
    # Server errors
    (r"5[0-9]{2}", ClaudeStatus.SERVER_ERROR),
    (r"server.?error", ClaudeStatus.SERVER_ERROR),
    (r"internal.?error", ClaudeStatus.SERVER_ERROR),
    # Network
    (r"network.?error", ClaudeStatus.NETWORK_ERROR),
    (r"connection.?refused", ClaudeStatus.NETWORK_ERROR),
    (r"timeout", ClaudeStatus.NETWORK_ERROR),
    (r"ECONNREFUSED", ClaudeStatus.NETWORK_ERROR),
    (r"ENOTFOUND", ClaudeStatus.NETWORK_ERROR),
]


def _detect_status(stderr: str, returncode: int) -> ClaudeStatus:
    """Détecte le statut à partir de la sortie stderr et du code de retour."""
    text = (stderr or "").lower()
    for pattern, status in _ERROR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return status
    if returncode != 0:
        return ClaudeStatus.SERVER_ERROR
    return ClaudeStatus.READY


def _estimate_reset_time(status: ClaudeStatus, stderr: str) -> Optional[float]:
    """Estime le timestamp de reset à partir du message d'erreur.

    Cherche des patterns comme :
      - "resets at 2026-07-28T09:00:00Z"
      - "try again in 3600 seconds"
      - "reset: 2026-07-28"
    """
    text = stderr or ""

    # ISO timestamp dans le message
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text)
    if iso_match:
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(iso_match.group(1))
            return dt.timestamp()
        except ValueError:
            pass

    # "try again in N seconds"
    sec_match = re.search(r"(?:try again|wait|retry)\s+(?:in\s+)?(\d+)\s*(?:s|sec|seconds)", text, re.I)
    if sec_match:
        return time.time() + int(sec_match.group(1))

    # Defaults par statut
    if status == ClaudeStatus.RATE_LIMITED:
        # Rate limit : assume reset dans ~1h (conservative)
        return time.time() + 3600
    if status == ClaudeStatus.NOT_LOGGED_IN:
        # Login : pas de reset automatique, nécessite intervention
        return None
    return None


@dataclass
class HealthSnapshot:
    """Snapshot de santé Claude."""
    status: ClaudeStatus = ClaudeStatus.UNKNOWN
    last_check: float = 0.0
    reset_at: Optional[float] = None     # timestamp estimé de disponibilité
    error_message: str = ""
    consecutive_failures: int = 0
    check_duration_ms: int = 0


class ClaudeHealthTracker:
    """Tracker de santé Claude avec cache persistant et TTL adaptatif."""

    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = self._load()
        self._warm_up_done = False

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> HealthSnapshot:
        """Charge le dernier snapshot depuis le disque."""
        try:
            data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
            return HealthSnapshot(
                status=ClaudeStatus(data.get("status", "unknown")),
                last_check=data.get("last_check", 0.0),
                reset_at=data.get("reset_at"),
                error_message=data.get("error_message", ""),
                consecutive_failures=data.get("consecutive_failures", 0),
            )
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return HealthSnapshot()

    def _save(self) -> None:
        """Persiste le snapshot sur disque."""
        try:
            HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "status": self._snapshot.status.value,
                "last_check": self._snapshot.last_check,
                "reset_at": self._snapshot.reset_at,
                "error_message": self._snapshot.error_message[:200],
                "consecutive_failures": self._snapshot.consecutive_failures,
            }
            tmp = HEALTH_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, HEALTH_FILE)
        except OSError as e:
            logger.debug("health save failed: %s", e)

    # ── TTL adaptatif ─────────────────────────────────────────────────────

    def _ttl(self) -> float:
        """TTL en secondes entre les checks. Plus d'échecs → plus long."""
        f = self._snapshot.consecutive_failures
        if f == 0:
            return 300     # 5 min si OK
        if f == 1:
            return 60      # 1 min après 1er échec (retry rapide)
        if f <= 3:
            return 300     # 5 min après 2-3 échecs
        return 900         # 15 min si échecs répétés

    def _needs_check(self) -> bool:
        """True si un check est nécessaire (TTL expiré ou reset time atteint)."""
        now = time.time()
        snap = self._snapshot

        # Si on a un reset_at et qu'il est passé → re-check immédiat
        if snap.reset_at and now >= snap.reset_at:
            return True

        # TTL expiré
        return (now - snap.last_check) > self._ttl()

    # ── Health check ──────────────────────────────────────────────────────

    def check(self, force: bool = False) -> HealthSnapshot:
        """Vérifie la santé de Claude CLI. Cache le résultat avec TTL adaptatif.

        Args:
            force: force le check même si le TTL n'est pas expiré.
        """
        with self._lock:
            # Skip si check récent (sauf force)
            if not force and not self._needs_check():
                return self._snapshot

            # Skip si désactivé par .env
            env_val = self._env("FORGE_CLAUDE_CHECK", "1")
            if env_val.lower() not in ("true", "1", "yes"):
                return self._snapshot

            return self._do_check()

    def _do_check(self) -> HealthSnapshot:
        """Exécute le check réel (appel CLI rapide)."""
        exe = shutil.which("claude") or shutil.which("claude.cmd")
        if not exe:
            self._snapshot = HealthSnapshot(
                status=ClaudeStatus.CLI_MISSING,
                last_check=time.time(),
                error_message="CLI `claude` introuvable (PATH)",
                consecutive_failures=self._snapshot.consecutive_failures + 1,
            )
            self._save()
            return self._snapshot

        # Ping rapide : "say ok" → teste login + connectivity + rate limit
        t0 = time.time()
        try:
            proc = subprocess.run(
                [exe, "-p", "--model", "haiku", "--output-format", "text"],
                input="say ok",
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=30,
            )
            elapsed = int((time.time() - t0) * 1000)
            stderr = proc.stderr or ""
            stdout = proc.stdout or ""

            status = _detect_status(stderr, proc.returncode)

            # Vérifie aussi si stdout est vide (CLI bug silencieux)
            if status == ClaudeStatus.READY and not stdout.strip():
                status = ClaudeStatus.SERVER_ERROR
                stderr = "CLI returned empty output"

            if status == ClaudeStatus.READY:
                self._snapshot = HealthSnapshot(
                    status=ClaudeStatus.READY,
                    last_check=time.time(),
                    consecutive_failures=0,
                    check_duration_ms=elapsed,
                )
                logger.info(f"[CLAUDE_HEALTH] ✓ READY ({elapsed}ms)")
            else:
                reset_at = _estimate_reset_time(status, stderr)
                self._snapshot = HealthSnapshot(
                    status=status,
                    last_check=time.time(),
                    reset_at=reset_at,
                    error_message=stderr[:200],
                    consecutive_failures=self._snapshot.consecutive_failures + 1,
                    check_duration_ms=elapsed,
                )
                logger.warning(f"[CLAUDE_HEALTH] ✗ {status.value}: {stderr[:100]}")

        except subprocess.TimeoutExpired:
            self._snapshot = HealthSnapshot(
                status=ClaudeStatus.NETWORK_ERROR,
                last_check=time.time(),
                error_message="timeout (30s)",
                consecutive_failures=self._snapshot.consecutive_failures + 1,
            )
        except Exception as e:
            self._snapshot = HealthSnapshot(
                status=ClaudeStatus.SERVER_ERROR,
                last_check=time.time(),
                error_message=str(e)[:200],
                consecutive_failures=self._snapshot.consecutive_failures + 1,
            )

        self._save()
        return self._snapshot

    # ── Public API ────────────────────────────────────────────────────────

    def is_available(self, force: bool = False) -> bool:
        """True si Claude est disponible maintenant."""
        snap = self.check(force=force)
        return snap.status == ClaudeStatus.READY

    def status(self) -> ClaudeStatus:
        """Statut actuel (sans re-check)."""
        return self._snapshot.status

    def fallback_reason(self) -> str:
        """Raison humaine du fallback (pour les logs/UI)."""
        snap = self._snapshot
        if snap.status == ClaudeStatus.READY:
            return ""
        if snap.status == ClaudeStatus.NOT_LOGGED_IN:
            return "Claude CLI non connecté — lance `claude` et connecte-toi"
        if snap.status == ClaudeStatus.RATE_LIMITED:
            if snap.reset_at:
                import datetime
                reset_str = datetime.datetime.fromtimestamp(snap.reset_at).strftime("%H:%M")
                return f"Claude rate-limited — reset estimé à {reset_str}"
            return "Claude rate-limited — réessaie plus tard"
        if snap.status == ClaudeStatus.CLI_MISSING:
            return "Claude CLI non installé"
        if snap.status == ClaudeStatus.NETWORK_ERROR:
            return "Réseau indisponible"
        return f"Claude indisponible ({snap.status.value}): {snap.error_message[:80]}"

    def snapshot(self) -> HealthSnapshot:
        """Snapshot complet (pour debug/dashboard)."""
        return self._snapshot

    def force_available(self) -> None:
        """Force le statut à READY (après un login réussi par ex.)."""
        with self._lock:
            self._snapshot = HealthSnapshot(
                status=ClaudeStatus.READY,
                last_check=time.time(),
                consecutive_failures=0,
            )
            self._save()

    def warm_up(self) -> None:
        """Warm-up check au démarrage de la Forge. Appelé une seule fois."""
        if self._warm_up_done:
            return
        self._warm_up_done = True
        if self._needs_check():
            snap = self.check()
            if snap.status != ClaudeStatus.READY:
                logger.warning(f"[CLAUDE_HEALTH] Warm-up: {self.fallback_reason()}")

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _env(key: str, default: str = "") -> str:
        v = os.environ.get(key)
        if v is not None:
            return v
        for p in [FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"]:
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, val = line.partition("=")
                        if k.strip() == key:
                            return val.strip().strip('"').strip("'")
        return default


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracker: Optional[ClaudeHealthTracker] = None
_tracker_lock = threading.Lock()


def claude_health() -> ClaudeHealthTracker:
    """Singleton du tracker de santé Claude."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ClaudeHealthTracker()
    return _tracker


# ── Self-check ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Claude Health Check ===")
    h = claude_health()
    snap = h.check(force=True)
    print(f"  Status    : {snap.status.value}")
    print(f"  Available : {h.is_available()}")
    print(f"  Duration  : {snap.check_duration_ms}ms")
    print(f"  Failures  : {snap.consecutive_failures}")
    if snap.error_message:
        print(f"  Error     : {snap.error_message[:100]}")
    if snap.reset_at:
        import datetime
        print(f"  Reset at  : {datetime.datetime.fromtimestamp(snap.reset_at).isoformat()}")
    reason = h.fallback_reason()
    if reason:
        print(f"  Fallback  : {reason}")
    print()
    print("ALL TESTS PASSED")
