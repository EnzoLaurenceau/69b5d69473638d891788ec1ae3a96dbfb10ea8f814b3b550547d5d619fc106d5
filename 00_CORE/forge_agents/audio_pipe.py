"""
audio_pipe.py — Wrappers audio pour la Forge (ticket E4-01)
===========================================================
Trois outils, un même contrat : `available()` → `generate()` / `process()`.

1. **edge_tts** — synthèse vocale (Microsoft Edge, gratuit, sans clé).
   Le TTS le plus fiable disponible : pas de GPU, pas d'API payante, 300+ voix.
2. **ffmpeg** — traitement audio (mix, loop, normalisation LUFS, conversion).
   Le couteau suisse. Tout passe par ffmpeg en dernier.
3. **musicgen** — génération musicale (Meta AudioCraft). Stub : le modèle
   n'est pas installé ici (GPU requis, ~2 Go). L'API est prête pour quand il
   le sera — `available()` renvoie False proprement au lieu de crasher.

POURQUOI UN SEUL MODULE
-----------------------
E4-02 (pipeline musique), E4-03 (SFX), E4-04 (gate audio) et E4-05 (KG↔audio)
importeront tous d'ici. Les wrappers individuels sont des détails d'implémentation ;
la façade publique est ce module.

USAGE
-----
    from forge_agents.audio_pipe import tts_generate, audio_process, music_generate

    # Voix
    path = tts_generate("Le bourreau marchait seul.", voice="fr-FR-DeniseNeural")

    # Musique (si MusicGen installé)
    if music_available():
        path = music_generate("Dark ambient, dungeon atmosphere", duration=30)

    # Post-traitement (toujours disponible)
    audio_process.normalize_lufs(input_path, target_lufs=-14.0)
    audio_process.mix([voice_path, music_path], output_path)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# FFMPEG — le socle commun
# ═══════════════════════════════════════════════════════════════════════════


def ffmpeg_available() -> bool:
    """ffmpeg est-il dans le PATH ?"""
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    """ffprobe est-il dans le PATH ?"""
    return shutil.which("ffprobe") is not None


def _run_ffmpeg(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Lance ffmpeg avec les arguments donnés. Lève si absent ou en erreur."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg introuvable dans le PATH")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    logger.debug("ffmpeg: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_ffprobe(args: list[str]) -> subprocess.CompletedProcess:
    """Lance ffprobe."""
    if not ffprobe_available():
        raise RuntimeError("ffprobe introuvable dans le PATH")
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json"] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


@dataclass
class AudioInfo:
    """Métadonnées extraites par ffprobe."""
    duration: float  # secondes
    sample_rate: int
    channels: int
    codec: str
    bit_rate: int  # bps
    format_name: str

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"


def probe(path: str | Path) -> AudioInfo:
    """Extrait les métadonnées d'un fichier audio via ffprobe."""
    result = _run_ffprobe(["-show_format", "-show_streams", str(path)])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe a échoué : {result.stderr.strip()}")
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    stream = next((s for s in data.get("streams", [])
                   if s.get("codec_type") == "audio"), {})
    return AudioInfo(
        duration=float(fmt.get("duration", 0)),
        sample_rate=int(stream.get("sample_rate", 0)),
        channels=int(stream.get("channels", 0)),
        codec=stream.get("codec_name", ""),
        bit_rate=int(fmt.get("bit_rate", 0)),
        format_name=fmt.get("format_name", ""),
    )


class AudioProcess:
    """Traitements audio via ffmpeg. Chaque méthode est un wrapper sûr.

    Toutes les méthodes retournent le chemin de sortie et acceptent un
    `output` optionnel ; si omis, un fichier temporaire est créé.
    """

    # ── Conversion ────────────────────────────────────────────────────────

    def convert(self, input: str | Path, output: str | Path = None,
                format: str = "wav", sample_rate: int = 44100,
                channels: int = 2) -> Path:
        """Convertit un fichier audio vers un format/échantillonnage donné."""
        out = Path(output) if output else Path(tempfile.mktemp(suffix=f".{format}"))
        _run_ffmpeg([
            "-i", str(input),
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-f", format,
            str(out),
        ])
        return out

    # ── Normalisation LUFS ────────────────────────────────────────────────

    def normalize_lufs(self, input: str | Path, output: str | Path = None,
                       target_lufs: float = -14.0,
                       target_tp: float = -1.5) -> Path:
        """Normalise un fichier au LUFS cible (EBU R128).

        Deux passes : mesure puis application. Le standard broadcast est
        -23 LUFS ; -14 est le standard web/YouTube ; -16 pour les podcasts.
        """
        out = Path(output) if output else Path(tempfile.mktemp(suffix=".wav"))

        # Pass 1 : mesure
        measure = _run_ffmpeg([
            "-i", str(input),
            "-af", f"loudnorm=I={target_lufs}:TP={target_tp}:print_format=json",
            "-f", "null", "-",
        ])
        # La sortie stderr contient le JSON loudnorm
        stderr = measure.stderr
        # Extraire le JSON entre accolades
        json_start = stderr.rfind("{")
        json_end = stderr.rfind("}") + 1
        if json_start < 0:
            # Fallback : normalisation simple sans mesure
            _run_ffmpeg([
                "-i", str(input),
                "-af", f"loudnorm=I={target_lufs}:TP={target_tp}",
                str(out),
            ])
            return out

        measured = json.loads(stderr[json_start:json_end])

        # Pass 2 : application
        _run_ffmpeg([
            "-i", str(input),
            "-af", (
                f"loudnorm=I={target_lufs}:TP={target_tp}"
                f":measured_I={measured.get('input_i', -23)}"
                f":measured_LRA={measured.get('input_lra', 7)}"
                f":measured_TP={measured.get('input_tp', -2)}"
                f":measured_thresh={measured.get('input_thresh', -34)}"
                f":offset={measured.get('target_offset', 0)}"
                f":linear=true"
            ),
            str(out),
        ])
        return out

    # ── Mix ────────────────────────────────────────────────────────────────

    def mix(self, inputs: list[str | Path], output: str | Path = None,
            volumes: list[float] | None = None) -> Path:
        """Mixe plusieurs fichiers audio en un seul.

        `volumes` : facteur de volume pour chaque piste (1.0 = inchangé).
        Par défaut, les pistes sont mixées à volume égal (1/N).
        """
        if not inputs:
            raise ValueError("Au moins un fichier requis pour le mix")
        out = Path(output) if output else Path(tempfile.mktemp(suffix=".wav"))

        if volumes is None:
            volumes = [1.0 / len(inputs)] * len(inputs)

        # Construire le filtre amix
        filter_parts = []
        for i, vol in enumerate(volumes):
            filter_parts.append(f"[{i}:a]volume={vol}[a{i}]")
        mix_inputs = "".join(f"[a{i}]" for i in range(len(inputs)))
        filter_parts.append(f"{mix_inputs}amix=inputs={len(inputs)}:duration=longest[out]")
        filter_str = ";".join(filter_parts)

        args = []
        for inp in inputs:
            args += ["-i", str(inp)]
        args += ["-filter_complex", filter_str, "-map", "[out]", str(out)]

        _run_ffmpeg(args)
        return out

    # ── Loop ───────────────────────────────────────────────────────────────

    def loop(self, input: str | Path, output: str | Path = None,
             duration: float = 60.0) -> Path:
        """Boucle un fichier audio pour atteindre la durée cible.

        Utile pour les ambiances de lieu (une boucle de 30s → 5 min).
        """
        out = Path(output) if output else Path(tempfile.mktemp(suffix=".wav"))
        _run_ffmpeg([
            "-stream_loop", "-1",
            "-i", str(input),
            "-t", str(duration),
            "-af", "afade=t=in:d=2,afade=t=out:st=" + str(max(0, duration - 2)) + ":d=2",
            str(out),
        ])
        return out

    # ── Trim ───────────────────────────────────────────────────────────────

    def trim(self, input: str | Path, output: str | Path = None,
             start: float = 0.0, end: float | None = None) -> Path:
        """Découpe un extrait audio."""
        out = Path(output) if output else Path(tempfile.mktemp(suffix=Path(input).suffix))
        args = ["-i", str(input), "-ss", str(start)]
        if end is not None:
            args += ["-to", str(end)]
        args += ["-c", "copy", str(out)]
        _run_ffmpeg(args)
        return out

    # ── Fade ───────────────────────────────────────────────────────────────

    def fade(self, input: str | Path, output: str | Path = None,
             fade_in: float = 1.0, fade_out: float = 1.0) -> Path:
        """Applique un fade in/out."""
        out = Path(output) if output else Path(tempfile.mktemp(suffix=Path(input).suffix))
        info = probe(input)
        fade_out_start = max(0, info.duration - fade_out)
        _run_ffmpeg([
            "-i", str(input),
            "-af", f"afade=t=in:d={fade_in},afade=t=out:st={fade_out_start}:d={fade_out}",
            str(out),
        ])
        return out


#: Instance publique — pas d'état, juste des wrappers ffmpeg.
audio_process = AudioProcess()


# ═══════════════════════════════════════════════════════════════════════════
# TTS — synthèse vocale (edge-tts)
# ═══════════════════════════════════════════════════════════════════════════


def tts_available() -> bool:
    """edge-tts est-il installé ?"""
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


#: Voix françaises disponibles par défaut (Edge TTS).
FRENCH_VOICES = {
    "denise": "fr-FR-DeniseNeural",      # féminine, naturelle
    "henri": "fr-FR-HenriNeural",        # masculine, naturelle
    "eleonore": "fr-FR-EloiseNeural",    # féminine, jeune
    "remi": "fr-FR-RemiMultilingualNeural",  # multilingue
}

#: Voix anglaises.
ENGLISH_VOICES = {
    "aria": "en-US-AriaNeural",
    "guy": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
    "davis": "en-US-DavisNeural",
}


def tts_generate(text: str, output: str | Path = None,
                 voice: str = "fr-FR-DeniseNeural",
                 rate: str = "+0%", pitch: str = "+0Hz") -> Path:
    """Génère un fichier audio à partir de texte (edge-tts).

    Args:
        text: Le texte à prononcer.
        output: Chemin de sortie (défaut: temporaire .mp3).
        voice: Nom de la voix Edge TTS (voir FRENCH_VOICES, ENGLISH_VOICES).
        rate: Vitesse de parole ("+10%", "-20%").
        pitch: Tonalité ("+5Hz", "-10Hz").

    Returns:
        Le chemin du fichier généré.
    """
    if not tts_available():
        raise RuntimeError("edge-tts non installé (pip install edge-tts)")

    import edge_tts
    import asyncio

    out = Path(output) if output else Path(tempfile.mktemp(suffix=".mp3"))

    async def _generate():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(out))

    # edge-tts est async — on exécute dans la boucle courante ou une nouvelle
    try:
        loop = asyncio.get_running_loop()
        loop.run_until_complete(_generate())
    except RuntimeError:
        asyncio.run(_generate())

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"TTS a échoué : fichier vide ({out})")

    logger.info("TTS: %d caractères → %s (%s)", len(text), out, voice)
    return out


async def tts_generate_stream(text: str, voice: str = "fr-FR-DeniseNeural",
                               rate: str = "+0%", pitch: str = "+0Hz"):
    """Génère un flux audio TTS (async, pour le streaming).

    Yields des chunks bytes. Utile pour l'intégration avec un serveur HTTP.
    """
    if not tts_available():
        raise RuntimeError("edge-tts non installé")

    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


async def tts_list_voices(language: str = "fr") -> list[dict]:
    """Liste les voix disponibles pour une langue donnée.

    Returns:
        Liste de dicts avec 'Name', 'Gender', 'Locale'.
    """
    if not tts_available():
        raise RuntimeError("edge-tts non installé")

    import edge_tts

    voices = await edge_tts.list_voices()
    return [v for v in voices if v.get("Locale", "").startswith(language)]


# ═══════════════════════════════════════════════════════════════════════════
# MUSICGEN — génération musicale (Meta AudioCraft)
# ═══════════════════════════════════════════════════════════════════════════


def music_available() -> bool:
    """MusicGen/AudioCraft est-il installé ? (nécessite GPU + ~2 Go)"""
    try:
        import audiocraft  # noqa: F401
        return True
    except ImportError:
        return False


def music_generate(prompt: str, output: str | Path = None,
                   duration: float = 30.0, model: str = "facebook/musicgen-small",
                   temperature: float = 1.0) -> Path:
    """Génère de la musique à partir d'une description textuelle.

    Nécessite AudioCraft (pip install audiocraft) + GPU recommandé.
    Le modèle par défaut (musicgen-small) fait ~300 Mo ; musicgen-medium ~1.5 Go.

    Args:
        prompt: Description de la musique ("Dark ambient, dungeon atmosphere").
        output: Chemin de sortie (défaut: temporaire .wav).
        duration: Durée en secondes (max ~30s pour small, ~300s pour medium).
        model: Modèle HuggingFace à utiliser.
        temperature: Température de génération (0.0 = déterministe, 2.0 = très aléatoire).

    Returns:
        Le chemin du fichier généré.

    Raises:
        RuntimeError: si AudioCraft n'est pas installé.
    """
    if not music_available():
        raise RuntimeError(
            "AudioCraft non installé. Installer avec : "
            "pip install audiocraft\n"
            "GPU recommandé (le modèle small fait ~300 Mo)."
        )

    import torch
    from audiocraft.models import MusicGen

    out = Path(output) if output else Path(tempfile.mktemp(suffix=".wav"))

    logger.info("MusicGen: chargement du modèle %s...", model)
    m = MusicGen.get_pretrained(model)
    m.set_generation_params(
        duration=min(duration, 300),
        temperature=temperature,
        top_k=250,
        top_p=0.0,
    )

    logger.info("MusicGen: génération '%s' (%.1fs)...", prompt[:60], duration)
    wav = m.generate([prompt], progress=True)

    # Sauvegarder
    import torchaudio
    torchaudio.save(str(out), wav[0].cpu(), sample_rate=m.sample_rate)

    logger.info("MusicGen: → %s", out)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# SELF-CHECK
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    print("=== audio_pipe self-check ===")
    print(f"ffmpeg:     {'✅' if ffmpeg_available() else '❌'}")
    print(f"ffprobe:    {'✅' if ffprobe_available() else '❌'}")
    print(f"edge-tts:   {'✅' if tts_available() else '❌'}")
    print(f"MusicGen:   {'✅' if music_available() else '❌ (GPU + 2 Go requis)'}")

    if tts_available():
        print(f"\nVoix FR:  {', '.join(FRENCH_VOICES.values())}")
        print(f"Voix EN:  {', '.join(ENGLISH_VOICES.values())}")

    if ffmpeg_available():
        print(f"\nffmpeg version: {subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True).stdout.splitlines()[0]}")
