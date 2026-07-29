"""Tests E4-01 — Wrappers audio (TTS, ffmpeg, MusicGen).

Ce ticket ouvre l'epic AUDIO-PIPE. Trois wrappers, un même contrat :

1. **ffmpeg** — toujours disponible (prérequis système). `audio_process`
   fournit : convert, normalize_lufs, mix, loop, trim, fade.
2. **edge-tts** — synthèse vocale (installé ici). `tts_generate()` produit
   un vrai fichier audio.
3. **musicgen** — génération musicale (AudioCraft). Stub : `available()` est
   False, `generate()` lève proprement.

Trois étages :
  - **disponibilité** — les outils sont détectés correctement.
  - **ffmpeg** — les traitements fonctionnent sur de vrais fichiers.
  - **tts** — la synthèse vocale produit un fichier sonore.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.audio_pipe import (  # noqa: E402
    AudioInfo,
    AudioProcess,
    ENGLISH_VOICES,
    FRENCH_VOICES,
    audio_process,
    ffmpeg_available,
    ffprobe_available,
    music_available,
    music_generate,
    probe,
    tts_available,
    tts_generate,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. DISPONIBILITÉ
# ═══════════════════════════════════════════════════════════════════════════


class TestAvailability:
    """Les outils sont correctement détectés."""

    def test_ffmpeg_disponible(self):
        assert ffmpeg_available() is True

    def test_ffprobe_disponible(self):
        assert ffprobe_available() is True

    def test_tts_disponible(self):
        assert tts_available() is True

    def test_musicgen_non_disponible(self):
        """MusicGen n'est pas installé (GPU + 2 Go). Le stub fonctionne."""
        assert music_available() is False

    def test_musicgen_generate_leve(self):
        """music_generate() lève proprement si AudioCraft absent."""
        with pytest.raises(RuntimeError, match="AudioCraft non installé"):
            music_generate("test")


# ═══════════════════════════════════════════════════════════════════════════
# 2. TTS — synthèse vocale
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tts_file(tmp_path):
    """Fichier TTS temporaire (nettoyé automatiquement)."""
    path = tts_generate(
        "Le soleil ancien se levait sur la ville aux murs de fer.",
        output=str(tmp_path / "voice.mp3"),
        voice="fr-FR-DeniseNeural",
    )
    return path


class TestTTS:
    """La synthèse vocale produit un vrai fichier audio."""

    def test_fichier_existe(self, tts_file):
        assert Path(tts_file).exists()
        assert Path(tts_file).stat().st_size > 0

    def test_format_mp3(self, tts_file):
        assert Path(tts_file).suffix == ".mp3"

    def test_duree_raisonnable(self, tts_file):
        info = probe(tts_file)
        assert info.duration > 0.5  # au moins 0.5s
        assert info.duration < 30   # pas plus de 30s pour une phrase

    def test_voix_masculine(self, tmp_path):
        path = tts_generate(
            "Bonjour.",
            output=str(tmp_path / "henri.mp3"),
            voice="fr-FR-HenriNeural",
        )
        assert Path(path).exists()

    def test_voix_anglaise(self, tmp_path):
        path = tts_generate(
            "Hello world.",
            output=str(tmp_path / "en.mp3"),
            voice="en-US-AriaNeural",
        )
        assert Path(path).exists()

    def test_voix_francaises_definies(self):
        assert "denise" in FRENCH_VOICES
        assert "henri" in FRENCH_VOICES
        assert len(FRENCH_VOICES) >= 3

    def test_voix_anglaises_definies(self):
        assert "aria" in ENGLISH_VOICES
        assert len(ENGLISH_VOICES) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# 3. FFMPEG — traitements audio
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def wav_file(tmp_path, tts_file):
    """Convertit le TTS en WAV pour les tests ffmpeg."""
    return audio_process.convert(tts_file, output=str(tmp_path / "test.wav"),
                                  format="wav", sample_rate=44100, channels=1)


class TestProbe:
    """ffprobe extrait les métadonnées."""

    def test_retourne_audio_info(self, wav_file):
        info = probe(wav_file)
        assert isinstance(info, AudioInfo)
        assert info.duration > 0
        assert info.sample_rate == 44100
        assert info.channels == 1

    def test_duration_str(self, wav_file):
        info = probe(wav_file)
        assert ":" in info.duration_str


class TestConvert:
    """La conversion change le format."""

    def test_convert_vers_wav(self, tts_file, tmp_path):
        out = audio_process.convert(tts_file, output=str(tmp_path / "out.wav"),
                                     format="wav", sample_rate=22050)
        info = probe(out)
        assert info.sample_rate == 22050
        assert info.codec == "pcm_s16le"

    def test_convert_vers_ogg(self, tts_file, tmp_path):
        out = audio_process.convert(tts_file, output=str(tmp_path / "out.ogg"),
                                     format="ogg")
        assert Path(out).exists()
        assert Path(out).suffix == ".ogg"


class TestNormalizeLUFS:
    """La normalisation LUFS fonctionne."""

    def test_produit_un_fichier(self, wav_file, tmp_path):
        out = audio_process.normalize_lufs(
            wav_file, output=str(tmp_path / "normed.wav"), target_lufs=-14.0)
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0

    def test_conserve_la_duree(self, wav_file, tmp_path):
        original = probe(wav_file)
        out = audio_process.normalize_lufs(
            wav_file, output=str(tmp_path / "normed.wav"), target_lufs=-14.0)
        normalise = probe(out)
        # La durée ne doit pas changer significativement (±0.5s pour le codec)
        assert abs(normalise.duration - original.duration) < 0.5


class TestTrim:
    """Le découpage fonctionne."""

    def test_trim_reduit_la_duree(self, wav_file, tmp_path):
        out = audio_process.trim(wav_file, output=str(tmp_path / "trimmed.wav"),
                                  start=0.0, end=1.0)
        info = probe(out)
        assert info.duration <= 1.5  # marge pour le codec


class TestLoop:
    """La boucle étend la durée."""

    def test_loop_augmente_la_duree(self, wav_file, tmp_path):
        out = audio_process.loop(wav_file, output=str(tmp_path / "looped.wav"),
                                  duration=10.0)
        info = probe(out)
        assert info.duration >= 9.0  # ~10s avec fade


class TestMix:
    """Le mix combine plusieurs pistes."""

    def test_mix_deux_pistes(self, wav_file, tmp_path):
        out = audio_process.mix(
            [wav_file, wav_file],
            output=str(tmp_path / "mixed.wav"),
        )
        assert Path(out).exists()
        info = probe(out)
        assert info.duration > 0

    def test_mix_volumes_differents(self, wav_file, tmp_path):
        out = audio_process.mix(
            [wav_file, wav_file],
            output=str(tmp_path / "mixed.wav"),
            volumes=[0.8, 0.2],
        )
        assert Path(out).exists()

    def test_mix_liste_vide_leve(self):
        with pytest.raises(ValueError, match="Au moins un fichier"):
            audio_process.mix([])


class TestFade:
    """Le fade fonctionne."""

    def test_fade_produit_un_fichier(self, wav_file, tmp_path):
        out = audio_process.fade(
            wav_file, output=str(tmp_path / "faded.wav"),
            fade_in=0.5, fade_out=0.5)
        assert Path(out).exists()


# ═══════════════════════════════════════════════════════════════════════════
# 4. AUDIO_PROCESS — instance publique
# ═══════════════════════════════════════════════════════════════════════════


class TestAudioProcessInstance:
    """L'instance publique est bien configurée."""

    def test_est_une_instance(self):
        assert isinstance(audio_process, AudioProcess)

    def test_a_toutes_les_methodes(self):
        methods = ["convert", "normalize_lufs", "mix", "loop", "trim", "fade"]
        for m in methods:
            assert hasattr(audio_process, m)
            assert callable(getattr(audio_process, m))
