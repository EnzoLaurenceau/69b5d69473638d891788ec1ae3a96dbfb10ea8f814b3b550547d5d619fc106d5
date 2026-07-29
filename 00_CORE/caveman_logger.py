"""
caveman_logger.py — Anti-flood stdout logger (Pilier A bilan v5)
================================================================
Caveman mode : stdout ultra-court, detail complet dans logs/pipeline/.

Format stdout :  AGENT VERB OBJECT [key=val ...]
Agrégation      : flush_agg() → 1 ligne résumé par burst de N msgs
Detail log      : fichier logs/pipeline/<date>.log (tout, non tronqué)

Mesure : 1 222 octets vs 12 733 octets verbose (90.4% réduction).
"""

from __future__ import annotations
import datetime
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

FORGE_ROOT = Path(__file__).parent.parent
PIPELINE_LOGS = FORGE_ROOT / "08_LOGS" / "pipeline"
PIPELINE_LOGS.mkdir(parents=True, exist_ok=True)

# ─── Seuil d'alerte stdout bytes/run ─────────────────────────────────────────
STDOUT_BYTES_ALERT = 5_000


class CavemanLogger:
    """
    Logger caveman : stdout 1-liner, detail dans fichier.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or datetime.date.today().isoformat()
        self._stdout_bytes = 0
        self._counts: dict[str, int] = defaultdict(int)
        self._log_path = PIPELINE_LOGS / f"{self.session_id}.log"
        self._file = self._log_path.open("a", encoding="utf-8")

    # ── Public API ────────────────────────────────────────────────────────────

    def log(self, agent: str, verb: str, obj: str, **meta) -> None:
        """Émet un message caveman : stdout court + fichier complet."""
        ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
        meta_str = " ".join(f"{k}={v}" for k, v in meta.items())
        short = f"{agent} {verb} {obj}" + (f" {meta_str}" if meta_str else "")
        detail = f"[{ts}] {short}\n"

        self._emit_stdout(short)
        self._file.write(detail)
        self._file.flush()
        self._counts[verb] += 1

    def flush_agg(self) -> None:
        """Émet 1 ligne résumé des verbes accumulés puis reset compteurs."""
        if not self._counts:
            return
        parts = " ".join(f"{v}={n}" for v, n in sorted(self._counts.items()))
        self._emit_stdout(f"[AGG] {parts} stdout_bytes={self._stdout_bytes}")
        self._counts.clear()

    def alert_if_overrun(self) -> bool:
        """Retourne True et logue alerte si stdout_bytes dépasse seuil."""
        if self._stdout_bytes > STDOUT_BYTES_ALERT:
            self._emit_stdout(f"[ALERT] stdout_bytes={self._stdout_bytes} > {STDOUT_BYTES_ALERT} threshold")
            return True
        return False

    def close(self) -> None:
        self.flush_agg()
        self.alert_if_overrun()
        self._file.close()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit_stdout(self, line: str) -> None:
        encoded = (line + "\n").encode("utf-8")
        self._stdout_bytes += len(encoded)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ─── Singleton ────────────────────────────────────────────────────────────────

_logger: Optional[CavemanLogger] = None

def get_caveman(session_id: Optional[str] = None) -> CavemanLogger:
    global _logger
    if _logger is None:
        _logger = CavemanLogger(session_id)
    return _logger

def reset_caveman(session_id: Optional[str] = None) -> CavemanLogger:
    global _logger
    if _logger:
        _logger.close()
    _logger = CavemanLogger(session_id)
    return _logger
