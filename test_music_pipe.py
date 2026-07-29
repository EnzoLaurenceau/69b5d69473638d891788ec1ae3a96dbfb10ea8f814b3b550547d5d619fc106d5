"""Tests E4-02 — Pipeline musique description -> generation -> export.

Tests sur la pipeline musicale complete :
  - generation placeholder (pas de MusicGen)
  - validation du fichier genere
  - bouclage pour atteindre la duree cible
  - normalisation LUFS
  - pipeline complet run()
"""

from __future__ import annotations

import importlib.util as _ilu
import sys
import tempfile
import types as _types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
_PKG = ROOT / "00_CORE" / "forge_agents"


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = _ilu.spec_from_file_location(name, str(path))
    mod = _types.ModuleType(name)
    mod.__file__ = str(path)
    mod.__package__ = "forge_agents"
    mod.__spec__ = spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if "forge_agents" not in sys.modules:
    _pkg = _types.ModuleType("forge_agents")
    _pkg.__path__ = [str(_PKG)]
    _pkg.__package__ = "forge_agents"
    sys.modules["forge_agents"] = _pkg

_load_module("forge_agents.forge_tenant", _PKG / "forge_tenant.py")
_load_module("forge_agents.graph_db", _PKG / "graph_db.py")
_load_module("forge_agents.forge_store", _PKG / "forge_store.py")
_load_module("forge_agents.audio_pipe", _PKG / "audio_pipe.py")
_mp = _load_module("forge_agents.music_pipe", _PKG / "music_pipe.py")

MusicPipeline = _mp.MusicPipeline
MusicResult = _mp.MusicResult
_generate_placeholder = _mp._generate_placeholder


@pytest.fixture
def pipe():
    return MusicPipeline()


@pytest.fixture
def placeholder_file(tmp_path):
    """Fichier WAV placeholder de 3 secondes."""
    return _generate_placeholder(3.0)


class TestPlaceholder:
    """Le placeholder genere un vrai fichier WAV."""

    def test_creates_file(self, tmp_path):
        path = _generate_placeholder(2.0)
        assert path.exists()
        assert path.stat().st_size > 0
        path.unlink()

    def test_duration_approximate(self):
        from forge_agents.audio_pipe import probe
        path = _generate_placeholder(5.0)
        info = probe(path)
        assert abs(info.duration - 5.0) < 0.5
        path.unlink()

    def test_is_wav(self):
        path = _generate_placeholder(1.0)
        assert path.suffix == ".wav"
        path.unlink()


class TestGenerate:
    """MusicPipeline.generate() utilise le placeholder quand MusicGen absent."""

    def test_returns_music_result(self, pipe):
        result = pipe.generate("Dark ambient", duration=3.0)
        assert isinstance(result, MusicResult)
        assert result.path.exists()
        result.path.unlink(missing_ok=True)

    def test_is_placeholder(self, pipe):
        result = pipe.generate("Test", duration=2.0)
        assert result.is_placeholder is True
        result.path.unlink(missing_ok=True)

    def test_prompt_stored(self, pipe):
        result = pipe.generate("Epic battle", duration=2.0)
        assert result.prompt == "Epic battle"
        result.path.unlink(missing_ok=True)

    def test_output_path_respected(self, pipe, tmp_path):
        out = tmp_path / "custom.wav"
        result = pipe.generate("Test", duration=2.0, output=out)
        assert result.path == out or out.exists()
        result.path.unlink(missing_ok=True)


class TestValidate:
    """MusicPipeline.validate() verifie le fichier genere."""

    def test_valid_file_passes(self, pipe, placeholder_file):
        result = pipe.validate(placeholder_file)
        assert result["passed"] is True
        assert result["file_exists"] is True
        assert result["format_ok"] is True
        assert result["duration_ok"] is True

    def test_missing_file_fails(self, pipe):
        result = pipe.validate(Path("/nonexistent/file.wav"))
        assert result["passed"] is False
        assert result["file_exists"] is False


class TestMakeLoop:
    """MusicPipeline.make_loop() etend la duree."""

    def test_loop_augments_duration(self, pipe, placeholder_file, tmp_path):
        out = tmp_path / "looped.wav"
        result = pipe.make_loop(placeholder_file, target_duration=10.0, output=out)
        assert out.exists()
        from forge_agents.audio_pipe import probe
        info = probe(out)
        assert info.duration >= 8.0  # ~10s avec fade


class TestNormalize:
    """MusicPipeline.normalize() normalise au LUFS cible."""

    def test_produces_file(self, pipe, placeholder_file, tmp_path):
        out = tmp_path / "normed.wav"
        result = pipe.normalize(placeholder_file, output=out)
        assert out.exists()
        assert out.stat().st_size > 0


class TestExport:
    """MusicPipeline.export() convertit le format."""

    def test_export_wav(self, pipe, placeholder_file, tmp_path):
        out = tmp_path / "exported.wav"
        result = pipe.export(placeholder_file, format="wav", output=out)
        assert out.exists()


class TestRun:
    """MusicPipeline.run() — pipeline complet."""

    def test_run_basic(self, pipe, tmp_path):
        result = pipe.run("Dark ambient", duration=5.0, loop=False,
                           output=str(tmp_path / "out.wav"))
        assert result.path.exists()
        assert result.is_placeholder is True
        assert "generate" in result.report["steps"]

    def test_run_with_loop(self, pipe, tmp_path):
        result = pipe.run("Epic music", duration=60.0, loop=True,
                           output=str(tmp_path / "looped.wav"))
        assert result.path.exists()
        assert "loop" in result.report["steps"]

    def test_run_with_normalize(self, pipe, tmp_path):
        result = pipe.run("Calm music", duration=5.0, loop=False,
                           normalize=True,
                           output=str(tmp_path / "normed.wav"))
        assert result.path.exists()
        assert "normalize" in result.report["steps"]

    def test_report_fields(self, pipe):
        result = pipe.run("Test", duration=3.0, loop=False)
        assert "prompt" in result.report
        assert "is_placeholder" in result.report
        assert "steps" in result.report
        assert "validation" in result.report
        result.path.unlink(missing_ok=True)


class TestMusicResult:
    """MusicResult dataclass."""

    def test_fields(self, pipe):
        result = pipe.generate("Test", duration=2.0)
        assert isinstance(result.path, Path)
        assert isinstance(result.prompt, str)
        assert isinstance(result.duration, float)
        assert isinstance(result.is_placeholder, bool)
        result.path.unlink(missing_ok=True)
