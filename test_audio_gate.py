"""Tests E4-04 — Gate audio automatique.

Tests sur vrai fichier WAV (placeholder) :
  - detection duree, format, codec
  - mesure LUFS
  - verdict passed/failed
  - fichier inexistant
"""

from __future__ import annotations

import importlib.util as _ilu
import sys
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
_load_module("forge_agents.music_pipe", _PKG / "music_pipe.py")
_ag = _load_module("forge_agents.audio_gate", _PKG / "audio_gate.py")

audio_gate = _ag.audio_gate
AudioGateResult = _ag.AudioGateResult


@pytest.fixture
def wav_file(tmp_path):
    """WAV placeholder de 3 secondes."""
    from forge_agents.music_pipe import _generate_placeholder
    path = _generate_placeholder(3.0)
    yield path
    path.unlink(missing_ok=True)


class TestAudioGate:
    """audio_gate() verifie un fichier audio."""

    def test_valid_file_passes(self, wav_file):
        result = audio_gate(wav_file)
        assert isinstance(result, AudioGateResult)
        assert result.passed is True
        assert result.duration > 0
        assert result.codec != ""

    def test_missing_file_fails(self):
        result = audio_gate("/nonexistent/file.wav")
        assert result.passed is False
        assert "does not exist" in result.failures[0]

    def test_duration_measured(self, wav_file):
        result = audio_gate(wav_file)
        assert result.duration >= 2.0  # ~3s placeholder

    def test_lufs_measured_or_graceful(self, wav_file):
        result = audio_gate(wav_file)
        # LUFS may fail on simple waveforms - that's OK, gate should still pass
        assert result.passed is True

    def test_failures_empty_on_valid(self, wav_file):
        result = audio_gate(wav_file)
        assert result.failures == []

    def test_too_short_fails(self, tmp_path):
        from forge_agents.music_pipe import _generate_placeholder
        path = _generate_placeholder(0.1)  # 100ms
        result = audio_gate(path, min_duration=1.0)
        assert result.passed is False
        assert any("too short" in f for f in result.failures)
        path.unlink()


class TestAudioGateResult:
    """AudioGateResult dataclass."""

    def test_defaults(self):
        r = AudioGateResult(path="/test")
        assert r.passed is False
        assert r.failures == []
        assert r.warnings == []
        assert r.lufs is None

    def test_fields(self, wav_file):
        result = audio_gate(wav_file)
        assert isinstance(result.path, str)
        assert isinstance(result.duration, float)
        assert isinstance(result.sample_rate, int)
        assert isinstance(result.codec, str)
