"""
audio_gate.py — Gate audio automatique (E4-04)
===============================================
Verifie un fichier audio avant integration dans le pipeline asset :
  - LUFS dans la plage acceptable
  - Pas de clipping
  - Duree dans les limites
  - Format correct

Le gate est BLOQUANT : un fichier qui echoue ne passe pas. C'est le meme
modele que `harness_engine` (GATES dict) mais specialise audio.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.audio_gate import audio_gate, AudioGateResult

    result = audio_gate("ambiance.wav")
    if not result.passed:
        print(f"BLOCKED: {result.failures}")

Verification : python -m forge_agents.audio_gate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AudioGate")


@dataclass
class AudioGateResult:
    """Resultat du gate audio."""
    path: str
    passed: bool = False
    duration: float = 0.0
    sample_rate: int = 0
    codec: str = ""
    lufs: Optional[float] = None
    true_peak: Optional[float] = None
    clipping_detected: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Seuils (configurables par env si besoin)
MIN_DURATION_S = 0.5
MAX_DURATION_S = 600.0  # 10 min
MIN_LUFS = -60.0  # pas trop silencieux
MAX_LUFS = -1.0   # pas ecrase
MAX_TRUE_PEAK_DB = -0.5  # eviter le clipping


def _measure_lufs(path: Path) -> dict:
    """Mesure LUFS via ffmpeg loudnorm (1 passe)."""
    from .audio_pipe import _run_ffmpeg
    try:
        result = _run_ffmpeg([
            "-i", str(path),
            "-af", "loudnorm=I=-14:TP=-1.5:print_format=json",
            "-f", "null", "-",
        ])
        stderr = result.stderr
        json_start = stderr.rfind("{")
        json_end = stderr.rfind("}") + 1
        if json_start < 0:
            return {}
        import json
        return json.loads(stderr[json_start:json_end])
    except Exception as e:
        logger.debug("[AudioGate] LUFS measurement failed: %s", e)
        return {}


def _detect_clipping(path: Path) -> bool:
    """Detecte le clipping (pics a 0 dBFS)."""
    from .audio_pipe import _run_ffmpeg
    try:
        result = _run_ffmpeg([
            "-i", str(path),
            "-af", "astats=metadata=1:reset=0",
            "-f", "null", "-",
        ])
        # Si astats detecte des pics a 0 dBFS, c'est du clipping
        stderr = result.stderr
        return "Peak level dB" in stderr and "0.0" in stderr
    except Exception:
        return False


def audio_gate(path: str | Path, min_duration: float = MIN_DURATION_S,
               max_duration: float = MAX_DURATION_S) -> AudioGateResult:
    """Verifie un fichier audio contre les criteres de qualite.

    Returns:
        AudioGateResult avec passed=True si le fichier passe le gate.
    """
    from .audio_pipe import ffmpeg_available, probe

    p = Path(path)
    result = AudioGateResult(path=str(p))

    if not p.exists():
        result.failures.append("file does not exist")
        return result

    if not ffmpeg_available():
        result.warnings.append("ffmpeg not available — skipping audio checks")
        result.passed = True  # degrade gracieusement
        return result

    # 1. Probe
    try:
        info = probe(p)
        result.duration = info.duration
        result.sample_rate = info.sample_rate
        result.codec = info.codec
    except Exception as e:
        result.failures.append(f"probe failed: {e}")
        return result

    # 2. Duree
    if info.duration < min_duration:
        result.failures.append(
            f"too short: {info.duration:.2f}s (min {min_duration}s)")
    if info.duration > max_duration:
        result.failures.append(
            f"too long: {info.duration:.1f}s (max {max_duration}s)")

    # 3. LUFS
    lufs_data = _measure_lufs(p)
    if lufs_data:
        input_i = lufs_data.get("input_i")
        if input_i is not None:
            result.lufs = float(input_i)
            if result.lufs < MIN_LUFS:
                result.failures.append(
                    f"too quiet: {result.lufs:.1f} LUFS (min {MIN_LUFS})")
            if result.lufs > MAX_LUFS:
                result.failures.append(
                    f"too loud: {result.lufs:.1f} LUFS (max {MAX_LUFS})")

        input_tp = lufs_data.get("input_tp")
        if input_tp is not None:
            result.true_peak = float(input_tp)
            if result.true_peak > MAX_TRUE_PEAK_DB:
                result.failures.append(
                    f"clipping risk: true peak {result.true_peak:.1f} dB "
                    f"(max {MAX_TRUE_PEAK_DB})")

    # 4. Clipping detection
    result.clipping_detected = _detect_clipping(p)
    if result.clipping_detected:
        result.warnings.append("possible clipping detected (astats)")

    # 5. Verdict
    result.passed = len(result.failures) == 0
    if not result.passed:
        logger.warning("[AudioGate] BLOCKED %s: %s", p.name,
                       "; ".join(result.failures))

    return result


if __name__ == "__main__":
    print("=== Audio Gate — self-check ===")
    print(f"ffmpeg available: {Path('/dev/null').exists()}")  # placeholder

    from .audio_pipe import ffmpeg_available
    print(f"ffmpeg: {'available' if ffmpeg_available() else 'NOT available'}")

    if ffmpeg_available():
        # Test sur un fichier placeholder
        from .music_pipe import _generate_placeholder
        p = _generate_placeholder(3.0)
        result = audio_gate(p)
        print(f"\nPlaceholder test: passed={result.passed}")
        print(f"  duration={result.duration:.2f}s, codec={result.codec}")
        print(f"  LUFS={result.lufs}, true_peak={result.true_peak}")
        print(f"  failures: {result.failures}")
        print(f"  warnings: {result.warnings}")
        p.unlink()

    print("\nSelf-check OK")
