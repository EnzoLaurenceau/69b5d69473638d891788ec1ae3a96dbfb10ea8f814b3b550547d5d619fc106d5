"""
rtk.py — wrapper Rust Token Killer (rtk-ai/rtk, https://www.rtk-ai.app).
=======================================================================
RTK N'EST PAS UN LLM. C'est un filtre qui COMPRESSE la sortie des commandes
(ls/cat/grep/git/tests/docker…) de 60-90 % AVANT qu'elle n'entre dans le
contexte d'un LLM. But : « tout utilise rtk pour optimiser les tokens ».

Deux niveaux d'intégration :
  1. GLOBAL (session agent) : `rtk init -g` installe un hook PreToolUse →
     toutes les sorties de commandes de Claude Code passent par rtk. (le vrai
     "tout" — géré hors-Python, cf. scripts/rtk_setup.py / CLAUDE.md).
  2. INTERNE (forge Python) : toute commande dont la sortie nourrit un LLM
     s'exécute via rtk_run() ci-dessous, au lieu de subprocess brut.

Binaire : PATH ('rtk') sinon build vendored 00_CORE/rtk/target/release/rtk.
Absent → dégradation gracieuse (commande brute, aucune compression, jamais de crash).

NMP: TOOL|INDEX|rtk|savings=60-90|pattern=command output token compression|approach=rtk binary wrap + graceful raw fallback
"""

from __future__ import annotations
import os
import shlex
import shutil
import subprocess
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
_EXE = "rtk.exe" if os.name == "nt" else "rtk"
_VENDORED = FORGE_ROOT / "00_CORE" / "rtk" / "target" / "release" / _EXE

_bin_cache: str | None = None


def rtk_bin() -> str | None:
    """Chemin du binaire rtk : PATH d'abord, sinon build vendored. None si absent."""
    global _bin_cache
    if _bin_cache and Path(_bin_cache).exists():
        return _bin_cache
    p = shutil.which("rtk")
    if not p and _VENDORED.exists():
        p = str(_VENDORED)
    _bin_cache = p
    return p


def available() -> bool:
    return rtk_bin() is not None


def rtk_run(command: str, timeout: int = 120, cwd: str | None = None) -> str:
    """
    Exécute `command` via rtk → sortie COMPRESSÉE (tokens optimisés).

    Fallback gracieux : si rtk absent, exécute la commande brute (aucune
    compression) plutôt que d'échouer. Retourne stdout+stderr concaténés.
    """
    try:
        args = shlex.split(command, posix=(os.name != "nt"))
    except ValueError:
        args = command.split()
    if not args:
        return ""

    b = rtk_bin()
    exec_args = [b, *args] if b else args
    try:
        out = subprocess.run(
            exec_args, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
            shell=(b is None and os.name == "nt"),
        )
        return (out.stdout or "") + (out.stderr or "")
    except FileNotFoundError:
        # binaire/commande introuvable → tentative brute via shell
        out = subprocess.run(command, shell=True, capture_output=True,
                             text=True, timeout=timeout, cwd=cwd)
        return (out.stdout or "") + (out.stderr or "")


def gain() -> str:
    """Stats d'économie de tokens rapportées par rtk ('rtk gain'). '' si rtk absent."""
    b = rtk_bin()
    if not b:
        return ""
    try:
        out = subprocess.run([b, "gain"], capture_output=True, text=True, timeout=15)
        return out.stdout or ""
    except Exception:
        return ""


# ── Self-check (ponytail : vérif runnable) ──────────────────────────────────
def _demo() -> None:
    # rtk_run marche même sans binaire (fallback brut) : une commande triviale
    # portable renvoie un output non vide.
    probe = "cmd /c echo rtk_ok" if os.name == "nt" else "echo rtk_ok"
    out = rtk_run(probe, timeout=20)
    assert "rtk_ok" in out, f"fallback brut cassé: {out!r}"
    print("rtk self-check OK | bin =", rtk_bin() or "(absent → fallback brut)")


if __name__ == "__main__":
    _demo()
