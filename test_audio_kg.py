"""Tests E4-05 — Liaison audio <-> World-KG.

Tests purs (pas de Kuzu requis) :
  - assign/lookup/lookup_all
  - by_label/by_kind filtering
  - unassign
  - persistance
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
_ak = _load_module("forge_agents.audio_kg", _PKG / "audio_kg.py")

AudioMap = _ak.AudioMap


@pytest.fixture
def amap(tmp_path):
    return AudioMap(tmp_path / "audio_map.json")


class TestAssign:
    """amap.assign() links audio to entities."""

    def test_assign_theme(self, amap):
        amap.assign("urth:Location:Nessus", "/music/nessus.wav", kind="theme")
        assert amap.lookup("urth:Location:Nessus") == "/music/nessus.wav"

    def test_assign_multiple_kinds(self, amap):
        amap.assign("urth:Location:Nessus", "/music/nessus.wav", kind="theme")
        amap.assign("urth:Location:Nessus", "sfx/crowd", kind="ambient")
        all_refs = amap.lookup_all("urth:Location:Nessus")
        assert all_refs["theme"] == "/music/nessus.wav"
        assert all_refs["ambient"] == "sfx/crowd"

    def test_assign_sfx(self, amap):
        amap.assign("urth:Item:Sword", "sfx/sword/unsheath", kind="sfx")
        assert amap.lookup("urth:Item:Sword", kind="sfx") == "sfx/sword/unsheath"


class TestLookup:
    """amap.lookup() retrieves audio for an entity."""

    def test_existing(self, amap):
        amap.assign("test:Location:A", "/a.wav")
        assert amap.lookup("test:Location:A") == "/a.wav"

    def test_missing_entity(self, amap):
        assert amap.lookup("nonexistent") is None

    def test_missing_kind(self, amap):
        amap.assign("test:A", "/a.wav", kind="theme")
        assert amap.lookup("test:A", kind="sfx") is None

    def test_lookup_all(self, amap):
        amap.assign("test:A", "/theme.wav", kind="theme")
        amap.assign("test:A", "/sfx.wav", kind="sfx")
        result = amap.lookup_all("test:A")
        assert len(result) == 2


class TestByLabel:
    """amap.by_label() filters by entity type."""

    def test_filters_locations(self, amap):
        amap.assign("urth:Location:Nessus", "/n.wav")
        amap.assign("urth:Location:Saltus", "/s.wav")
        amap.assign("urth:Faction:Guilde", "/g.wav")
        locations = amap.by_label("Location")
        assert len(locations) == 2
        assert "urth:Location:Nessus" in locations

    def test_empty_label(self, amap):
        assert amap.by_label("Quest") == {}


class TestByKind:
    """amap.by_kind() filters by audio type."""

    def test_filters_themes(self, amap):
        amap.assign("test:A", "/theme.wav", kind="theme")
        amap.assign("test:B", "/sfx.wav", kind="sfx")
        themes = amap.by_kind("theme")
        assert len(themes) == 1
        assert "test:A" in themes


class TestUnassign:
    """amap.unassign() removes audio."""

    def test_removes_kind(self, amap):
        amap.assign("test:A", "/a.wav", kind="theme")
        assert amap.unassign("test:A", kind="theme") is True
        assert amap.lookup("test:A") is None

    def test_nonexistent(self, amap):
        assert amap.unassign("nope") is False


class TestPersistance:
    """Map survives reload."""

    def test_survives_reload(self, tmp_path):
        path = tmp_path / "map.json"
        m1 = AudioMap(path)
        m1.assign("test:A", "/a.wav")

        m2 = AudioMap(path)
        assert m2.lookup("test:A") == "/a.wav"


class TestAllKeys:
    """amap.all_keys() lists mapped entities."""

    def test_returns_sorted(self, amap):
        amap.assign("test:B", "/b.wav")
        amap.assign("test:A", "/a.wav")
        assert amap.all_keys() == ["test:A", "test:B"]

    def test_empty(self, amap):
        assert amap.all_keys() == []
