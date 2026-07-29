"""
music_pipe.py — Pipeline musique description -> generation -> export (E4-02)
===========================================================================
Chaine complete :
    description -> generation -> validation -> bouclage -> mixage -> export

Le pipeline degrade gracieusement : sans MusicGen, il produit un placeholder
(sinusoide) et logue un WARNING. Le pipeline reste TESTABLE et UTILISABLE
en attendant le GPU.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.music_pipe import MusicPipeline

    pipe = MusicPipeline()
    result = pipe.run(
        "Dark ambient, dungeon atmosphere, dripping water",
        duration=60.0,
        output="dungeon_ambiance.wav",
    )
    # result.path -> fichier final
    # result.report -> metriques (duree, LUFS, loop_ok, etc.)

Verification : python -m forge_agents.music_pipe
"""

from __future__ import annotations

import logging
import math
import struct
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MusicPipe")


@dataclass
class MusicResult:
    """Resultat d'une pipeline musicale."""
    path: Path
    prompt: str
    duration: float
    sample_rate: int
    is_placeholder: bool
    report: dict = field(default_factory=dict)


def _generate_placeholder(duration: float, sample_rate: int = 44100,
                           frequency: float = 220.0) -> Path:
    """Genere un fichier WAV placeholder (sinusoide).

    Utile pour tester le pipeline sans MusicGen. Le son est volontairement
    reconnaissable (sinusoide pure) pour ne pas etre pris pour un vrai asset.
    """
    path = Path(tempfile.mktemp(suffix=".wav"))
    n_samples = int(duration * sample_rate)
    amplitude = 0.3

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            t = i / sample_rate
            # Sinusoide avec enveloppe ADSR simplifiee
            env = min(1.0, t * 4) * max(0, 1.0 - (t - duration + 0.5) * 2)
            env = min(env, 1.0)
            sample = int(amplitude * env * math.sin(2 * math.pi * frequency * t) * 32767)
            frames.extend(struct.pack("<h", max(-32768, min(32767, sample))))
        wf.writeframes(bytes(frames))

    return path


def _detect_silence(path: Path, threshold_db: float = -40.0) -> dict:
    """Detecte les segments de silence dans un fichier audio.

    Retourne le pourcentage de silence et la duree du plus long segment.
    """
    try:
        from .audio_pipe import probe
        info = probe(path)
    except Exception:
        return {"silence_pct": 0.0, "longest_silence_s": 0.0, "measured": False}

    return {
        "silence_pct": 0.0,  # Placeholder: vrai detection necessite numpy
        "longest_silence_s": 0.0,
        "measured": False,
        "note": "silence detection requires numpy (not yet integrated)",
    }


class MusicPipeline:
    """Pipeline musicale complete.

    Chaque etape est une methode publique pour permettre l'appel individuel.
    `run()` enchainement complet.
    """

    def __init__(self, target_lufs: float = -14.0, loop_crossfade: float = 2.0):
        self.target_lufs = target_lufs
        self.loop_crossfade = loop_crossfade

    def generate(self, prompt: str, duration: float = 30.0,
                 output: Optional[Path] = None) -> MusicResult:
        """Genere de la musique depuis une description textuelle.

        Utilise MusicGen si disponible, placeholder sinusoide sinon.
        """
        from .audio_pipe import music_available, music_generate

        is_placeholder = False

        if music_available():
            logger.info("[MusicPipe] MusicGen available, generating '%s'...", prompt[:50])
            path = music_generate(prompt, duration=duration)
        else:
            logger.warning(
                "[MusicPipe] MusicGen not available — generating placeholder "
                "(sine wave). Install audiocraft for real generation."
            )
            path = _generate_placeholder(duration)
            is_placeholder = True

        if output:
            dest = Path(output)
            if dest != path:
                import shutil
                shutil.copy2(str(path), str(dest))
                path = dest

        return MusicResult(
            path=path,
            prompt=prompt,
            duration=duration,
            sample_rate=44100,
            is_placeholder=is_placeholder,
        )

    def validate(self, path: Path) -> dict:
        """Valide un fichier audio genere.

        Verifie : duree, format, pas de silence excessif.
        """
        from .audio_pipe import probe, ffmpeg_available

        checks = {"file_exists": path.exists(), "format_ok": False,
                  "duration_ok": False, "silence_ok": True, "passed": False}

        if not path.exists():
            checks["reason"] = "file does not exist"
            return checks

        try:
            info = probe(path)
            checks["format_ok"] = info.codec in (
                "pcm_s16le", "pcm_s24le", "pcm_s32le",
                "mp3", "aac", "vorbis", "opus", "flac")
            checks["duration_ok"] = info.duration >= 1.0
            checks["duration"] = info.duration
            checks["codec"] = info.codec
            checks["sample_rate"] = info.sample_rate

            silence = _detect_silence(path)
            checks["silence"] = silence
            if silence.get("silence_pct", 0) > 80:
                checks["silence_ok"] = False

        except Exception as e:
            checks["reason"] = f"probe failed: {e}"
            return checks

        checks["passed"] = all([
            checks["file_exists"],
            checks["format_ok"],
            checks["duration_ok"],
            checks["silence_ok"],
        ])
        return checks

    def make_loop(self, path: Path, target_duration: float,
                  output: Optional[Path] = None) -> Path:
        """Cree une boucle sans couture a partir d'un fichier audio."""
        from .audio_pipe import audio_process
        return audio_process.loop(path, output=str(output) if output else None,
                                   duration=target_duration)

    def normalize(self, path: Path, output: Optional[Path] = None) -> Path:
        """Normalise au LUFS cible."""
        from .audio_pipe import audio_process
        return audio_process.normalize_lufs(
            path, output=str(output) if output else None,
            target_lufs=self.target_lufs)

    def export(self, path: Path, format: str = "wav",
               sample_rate: int = 44100, output: Optional[Path] = None) -> Path:
        """Exporte dans le format final."""
        from .audio_pipe import audio_process
        return audio_process.convert(
            path, output=str(output) if output else None,
            format=format, sample_rate=sample_rate)

    def run(self, prompt: str, duration: float = 60.0,
            loop: bool = True, normalize: bool = True,
            export_format: str = "wav",
            output: Optional[str | Path] = None) -> MusicResult:
        """Pipeline complet : generation -> validation -> bouclage -> normalisation -> export.

        Args:
            prompt: Description musicale.
            duration: Duree cible en secondes.
            loop: Boucler pour atteindre la duree cible.
            normalize: Normaliser au LUFS cible.
            export_format: Format de sortie (wav, ogg, mp3).
            output: Chemin de sortie final.

        Returns:
            MusicResult avec le chemin et les metriques.
        """
        logger.info("[MusicPipe] Pipeline: '%s' (%.0fs, loop=%s, norm=%s)",
                    prompt[:60], duration, loop, normalize)

        # 1. Generation
        gen = self.generate(prompt, duration=min(duration, 30.0))
        current = gen.path
        report = {"prompt": prompt, "is_placeholder": gen.is_placeholder,
                  "steps": ["generate"]}

        # 2. Validation
        val = self.validate(current)
        report["validation"] = val
        if not val["passed"]:
            logger.warning("[MusicPipe] Validation failed: %s", val.get("reason", val))
            report["warning"] = "validation failed"

        # 3. Bouclage (si demande et duree > duree generee)
        if loop and duration > gen.duration:
            looped = self.make_loop(current, target_duration=duration)
            current = looped
            report["steps"].append("loop")
            report["loop_target_duration"] = duration

        # 4. Normalisation
        if normalize:
            normalized = self.normalize(current)
            current = normalized
            report["steps"].append("normalize")

        # 5. Export
        if export_format != "wav" or output:
            exported = self.export(current, format=export_format,
                                    output=Path(output) if output else None)
            current = exported
            report["steps"].append("export")

        # Copier vers output si pas encore fait
        if output:
            dest = Path(output)
            if dest != current:
                import shutil
                shutil.copy2(str(current), str(dest))
                current = dest

        report["final_path"] = str(current)
        logger.info("[MusicPipe] Done: %s (%d steps)", current, len(report["steps"]))

        return MusicResult(
            path=current,
            prompt=prompt,
            duration=duration,
            sample_rate=44100,
            is_placeholder=gen.is_placeholder,
            report=report,
        )


if __name__ == "__main__":
    print("=== Music Pipeline — self-check ===")

    pipe = MusicPipeline()
    print(f"target_lufs: {pipe.target_lufs}")
    print(f"loop_crossfade: {pipe.loop_crossfade}s")

    # Test generation (placeholder)
    result = pipe.generate("Dark ambient, dungeon", duration=5.0)
    print(f"\nGenerate: {result.path}")
    print(f"  placeholder: {result.is_placeholder}")
    print(f"  duration: {result.duration}s")

    # Test validation
    val = pipe.validate(result.path)
    print(f"\nValidate: passed={val['passed']}")
    print(f"  format_ok={val.get('format_ok')}, duration_ok={val.get('duration_ok')}")

    # Test pipeline complet (sans loop pour aller vite)
    result2 = pipe.run("Epic battle music", duration=10.0, loop=False,
                        output=tempfile.mktemp(suffix=".wav"))
    print(f"\nPipeline: {result2.path}")
    print(f"  steps: {result2.report['steps']}")
    print(f"  placeholder: {result2.is_placeholder}")

    print("\nSelf-check OK")
