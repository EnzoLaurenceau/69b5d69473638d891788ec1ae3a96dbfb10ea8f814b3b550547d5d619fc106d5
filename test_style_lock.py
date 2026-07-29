"""Tests E3-02 — Style-lock : bible visuelle dans le World-KG.

Tests purs (pas de Kuzu requis) :
  - StyleLock roundtrip sérialisation
  - inject_style() ajoute le suffixe correctement
  - describe() rend une description lisible
  - Edge cases (None, vide, ponctuation)
"""

from __future__ import annotations

import importlib.util as _ilu
import json
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

_sl = _load_module("forge_agents.style_lock", _PKG / "style_lock.py")

StyleLock = _sl.StyleLock
inject_style = _sl.inject_style
LOCK_NAME = _sl.LOCK_NAME


SAMPLE_LOCK = StyleLock(
    palette=["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
    mood="dark, mysterious, ancient",
    lighting="low-key, torchlight, bioluminescent accents",
    prompt_suffix="dark fantasy art style, muted colors, detailed textures",
    refs=["Moebius", "Blasphemous"],
    resolution="1024x1024",
    technique="digital painting",
)


class TestStyleLockDataclass:
    """StyleLock creation and defaults."""

    def test_defaults(self):
        lock = StyleLock()
        assert lock.palette == []
        assert lock.mood == ""
        assert lock.prompt_suffix == ""
        assert lock.refs == []

    def test_from_params(self):
        assert SAMPLE_LOCK.palette == ["#1a1a2e", "#16213e", "#0f3460", "#e94560"]
        assert SAMPLE_LOCK.mood == "dark, mysterious, ancient"
        assert SAMPLE_LOCK.technique == "digital painting"


class TestSerialization:
    """Roundtrip dict <-> StyleLock."""

    def test_to_dict(self):
        d = SAMPLE_LOCK.to_dict()
        assert isinstance(d, dict)
        assert d["palette"] == SAMPLE_LOCK.palette
        assert d["mood"] == SAMPLE_LOCK.mood
        assert d["prompt_suffix"] == SAMPLE_LOCK.prompt_suffix

    def test_from_dict(self):
        d = SAMPLE_LOCK.to_dict()
        lock = StyleLock.from_dict(d)
        assert lock.palette == SAMPLE_LOCK.palette
        assert lock.mood == SAMPLE_LOCK.mood
        assert lock.prompt_suffix == SAMPLE_LOCK.prompt_suffix
        assert lock.refs == SAMPLE_LOCK.refs
        assert lock.resolution == SAMPLE_LOCK.resolution
        assert lock.technique == SAMPLE_LOCK.technique

    def test_roundtrip(self):
        d = SAMPLE_LOCK.to_dict()
        lock = StyleLock.from_dict(d)
        assert lock.to_dict() == d

    def test_from_dict_missing_keys(self):
        lock = StyleLock.from_dict({"palette": ["#fff"]})
        assert lock.palette == ["#fff"]
        assert lock.mood == ""
        assert lock.refs == []

    def test_from_dict_empty(self):
        lock = StyleLock.from_dict({})
        assert lock.palette == []
        assert lock.prompt_suffix == ""

    def test_json_roundtrip(self):
        d = SAMPLE_LOCK.to_dict()
        j = json.dumps(d, ensure_ascii=False)
        d2 = json.loads(j)
        lock = StyleLock.from_dict(d2)
        assert lock.palette == SAMPLE_LOCK.palette


class TestDescribe:
    """describe() renders human-readable style info."""

    def test_full_style(self):
        desc = SAMPLE_LOCK.describe()
        assert "digital painting" in desc
        assert "#1a1a2e" in desc
        assert "dark, mysterious" in desc
        assert "Moebius" in desc
        assert "1024x1024" in desc

    def test_empty_style(self):
        lock = StyleLock()
        desc = lock.describe()
        assert desc == ""

    def test_partial_style(self):
        lock = StyleLock(palette=["#000"], mood="dark")
        desc = lock.describe()
        assert "#000" in desc
        assert "dark" in desc
        assert "Lighting" not in desc


class TestInjectStyle:
    """inject_style() appends style suffix to prompt."""

    def test_basic_injection(self):
        result = inject_style("un marchand de reliques", SAMPLE_LOCK)
        assert "marchand" in result
        assert "dark fantasy" in result
        assert result.startswith("un marchand")

    def test_none_lock(self):
        result = inject_style("test prompt", None)
        assert result == "test prompt"

    def test_empty_suffix(self):
        lock = StyleLock(prompt_suffix="")
        result = inject_style("test", lock)
        assert result == "test"

    def test_whitespace_suffix(self):
        lock = StyleLock(prompt_suffix="  ")
        result = inject_style("test", lock)
        assert result == "test"

    def test_no_double_comma(self):
        result = inject_style("un marchand,", SAMPLE_LOCK)
        assert ",," not in result

    def test_period_handling(self):
        result = inject_style("un marchand.", SAMPLE_LOCK)
        assert ",," not in result
        assert "dark fantasy" in result

    def test_suffix_starts_with_comma(self):
        lock = StyleLock(prompt_suffix=", dark fantasy")
        result = inject_style("test", lock)
        # Should not produce "test, , dark fantasy"
        assert ", ," not in result

    def test_preserves_original_prompt(self):
        prompt = "a merchant in the lower city"
        result = inject_style(prompt, SAMPLE_LOCK)
        assert prompt in result


class TestStoreName:
    """LOCK_NAME is the DesignDecision name in the KG."""

    def test_lock_name_is_string(self):
        assert isinstance(LOCK_NAME, str)
        assert len(LOCK_NAME) > 0

    def test_lock_name_stable(self):
        assert LOCK_NAME == "Visual Style Lock"
