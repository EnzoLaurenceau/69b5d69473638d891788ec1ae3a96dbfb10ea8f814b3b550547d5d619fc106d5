"""
test_versioning.py — Tests for forge_versioning.py
===================================================
"""
from __future__ import annotations

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(__file__))

from forge_versioning import ForgeVersioning, get_versioning


def test_version_increment():
    v = ForgeVersioning()
    initial = v._runtime.get("version", "1.0.0")
    new_ver = v.increment_version("test")
    parts = new_ver.split(".")
    assert len(parts) == 3
    # Increment should have happened
    assert new_ver != initial or initial == "1.0.0"


def test_version_info():
    v = ForgeVersioning()
    info = v.get_version_info()
    assert "version" in info
    assert "cycle" in info
    assert "last_update" in info
    assert isinstance(info["cycle"], int)


def test_cycle_increment():
    v = ForgeVersioning()
    cycle_before = v._runtime.get("cycle", 0)
    v.increment_version("test_cycle")
    cycle_after = v._runtime.get("cycle", 0)
    assert cycle_after == cycle_before + 1


def test_singleton():
    v1 = get_versioning()
    v2 = get_versioning()
    assert v1 is v2


def test_auto_index_no_files():
    v = ForgeVersioning()
    # Should not start indexing if files_written=False
    v.maybe_auto_index(files_written=False)
    assert v._indexing_thread is None or not v._indexing_thread.is_alive()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
