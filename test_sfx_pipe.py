"""Tests E4-03 — Pipeline SFX : banque categorisee, variations, layering.

Tests purs (pas de fichiers audio reels requis) :
  - register/pick/count/categories
  - variations (pick aleatoire)
  - fallback categorie parente
  - remove
  - doublons evites
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
_sp = _load_module("forge_agents.sfx_pipe", _PKG / "sfx_pipe.py")

SfxBank = _sp.SfxBank
SfxEntry = _sp.SfxEntry


@pytest.fixture
def bank(tmp_path):
    """Fresh SfxBank with temp file."""
    return SfxBank(tmp_path / "sfx_bank.json")


class TestRegister:
    """bank.register() adds entries to categories."""

    def test_register_single(self, bank):
        entry = bank.register("footsteps/stone", "/sfx/step1.wav", duration=0.5)
        assert isinstance(entry, SfxEntry)
        assert bank.count("footsteps/stone") == 1

    def test_register_multiple(self, bank):
        bank.register("footsteps/stone", "/sfx/step1.wav")
        bank.register("footsteps/stone", "/sfx/step2.wav")
        assert bank.count("footsteps/stone") == 2

    def test_register_different_categories(self, bank):
        bank.register("footsteps/stone", "/sfx/step1.wav")
        bank.register("ui/click", "/sfx/click.wav")
        assert bank.count("footsteps/stone") == 1
        assert bank.count("ui/click") == 1

    def test_register_with_tags(self, bank):
        entry = bank.register("ambient", "/sfx/wind.wav", tags=["wind", "loop"])
        stored = bank.entries("ambient")[0]
        assert stored["tags"] == ["wind", "loop"]

    def test_register_duplicate_ignored(self, bank):
        bank.register("footsteps", "/sfx/step1.wav")
        bank.register("footsteps", "/sfx/step1.wav")  # duplicate
        assert bank.count("footsteps") == 1


class TestPick:
    """bank.pick() selects randomly from a category."""

    def test_pick_returns_path(self, bank):
        bank.register("footsteps", "/sfx/step1.wav")
        result = bank.pick("footsteps")
        assert result == "/sfx/step1.wav"

    def test_pick_from_multiple(self, bank):
        bank.register("footsteps", "/sfx/step1.wav")
        bank.register("footsteps", "/sfx/step2.wav")
        results = {bank.pick("footsteps") for _ in range(100)}
        assert len(results) == 2  # both should appear

    def test_pick_empty_category(self, bank):
        result = bank.pick("nonexistent")
        assert result is None

    def test_pick_falls_back_to_parent(self, bank):
        bank.register("footsteps", "/sfx/step1.wav")
        result = bank.pick("footsteps/stone")  # subcategory
        assert result == "/sfx/step1.wav"


class TestCategories:
    """bank.categories() lists all categories."""

    def test_empty_bank(self, bank):
        assert bank.categories() == []

    def test_lists_categories(self, bank):
        bank.register("footsteps/stone", "/sfx/s1.wav")
        bank.register("ui/click", "/sfx/c1.wav")
        cats = bank.categories()
        assert "footsteps/stone" in cats
        assert "ui/click" in cats


class TestCount:
    """bank.count() counts entries."""

    def test_total_count(self, bank):
        bank.register("a", "/1.wav")
        bank.register("b", "/2.wav")
        bank.register("b", "/3.wav")
        assert bank.count() == 3

    def test_category_count(self, bank):
        bank.register("a", "/1.wav")
        bank.register("b", "/2.wav")
        assert bank.count("a") == 1
        assert bank.count("b") == 1
        assert bank.count("c") == 0


class TestRemove:
    """bank.remove() removes entries."""

    def test_remove_existing(self, bank):
        bank.register("footsteps", "/sfx/step1.wav")
        assert bank.remove("footsteps", "/sfx/step1.wav") is True
        assert bank.count("footsteps") == 0

    def test_remove_nonexistent(self, bank):
        assert bank.remove("footsteps", "/sfx/nope.wav") is False

    def test_removes_empty_category(self, bank):
        bank.register("ui", "/sfx/click.wav")
        bank.remove("ui", "/sfx/click.wav")
        assert "ui" not in bank.categories()


class TestPersistance:
    """Bank survives reload."""

    def test_survives_reload(self, tmp_path):
        path = tmp_path / "sfx.json"
        b1 = SfxBank(path)
        b1.register("steps", "/sfx/s1.wav", duration=0.5)
        b1.register("steps", "/sfx/s2.wav")

        b2 = SfxBank(path)
        assert b2.count("steps") == 2
        assert b2.pick("steps") in ("/sfx/s1.wav", "/sfx/s2.wav")


class TestEntries:
    """bank.entries() returns raw entries."""

    def test_returns_list(self, bank):
        bank.register("test", "/sfx/t.wav", duration=1.0, tags=["a"])
        entries = bank.entries("test")
        assert len(entries) == 1
        assert entries[0]["path"] == "/sfx/t.wav"
        assert entries[0]["duration"] == 1.0
        assert entries[0]["tags"] == ["a"]

    def test_empty_category(self, bank):
        assert bank.entries("empty") == []
