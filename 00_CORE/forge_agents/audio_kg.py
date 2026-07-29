"""
audio_kg.py — Liaison audio <-> World-KG (E4-05)
==================================================
Chaque lieu du monde a un theme musical, chaque faction un motif, chaque objet
un SFX. Ce module mappe les entites du World-KG vers leurs fichiers audio.

STOCKAGE
--------
La map est un JSON persistant (audio_kg_map.json) : {entity_key -> audio_ref}.
`entity_key` est la cle World-KG (`world_id:Label:slug`). `audio_ref` est :
  - un chemin de fichier (local)
  - une categorie SFX (pour pick aleatoire via sfx_pipe)
  - une description textuelle (pour generation future via music_pipe)

POURQUOI PAS DES PROPRIETES KG
-------------------------------
Ajouter `theme_music` aux 10 types de nœuds du World-KG polluerait le schéma
de l'ontologie narrative avec des données de pipeline asset. La map séparée
est plus propre : elle ne change pas le KG, elle le DECORE.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.audio_kg import get_audio_map

    m = get_audio_map()
    m.assign("urth:Location:Nessus", "D:/music/nessus_theme.wav", kind="theme")
    m.assign("urth:Character:Severian", "sfx/footsteps/stone", kind="sfx")

    theme = m.lookup("urth:Location:Nessus")  # -> "D:/music/nessus_theme.wav"
    all_locations = m.by_label("Location")      # -> {"urth:Location:Nessus": ...}

Verification : python -m forge_agents.audio_kg
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AudioKG")


class AudioMap:
    """Map entite World-KG -> fichier/categorie audio."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self._data: Optional[dict] = None

    def _ensure_path(self) -> Path:
        if self._path is None:
            from .forge_store import state_path
            self._path = state_path("audio_kg_map.json")
        return self._path

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        p = self._ensure_path()
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
            self._data = dict(raw)
        except (OSError, ValueError):
            self._data = {}
        return self._data

    def _save(self) -> None:
        p = self._ensure_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    def assign(self, entity_key: str, audio_ref: str,
               kind: str = "theme") -> None:
        """Assigne un audio a une entite du World-KG.

        Args:
            entity_key: Cle World-KG (ex: "urth:Location:Nessus").
            audio_ref: Chemin, categorie SFX, ou description.
            kind: Type d'assignation ("theme", "sfx", "ambient", "voice").
        """
        data = self._load()
        entry = data.setdefault(entity_key, {})
        entry[kind] = audio_ref
        data[entity_key] = entry
        self._save()
        logger.info("[AudioMap] %s -> %s (%s)", entity_key, audio_ref, kind)

    def lookup(self, entity_key: str, kind: str = "theme") -> Optional[str]:
        """Recupere l'audio d'une entite."""
        data = self._load()
        entry = data.get(entity_key, {})
        return entry.get(kind)

    def lookup_all(self, entity_key: str) -> dict[str, str]:
        """Recupere tous les audio d'une entite."""
        return dict(self._load().get(entity_key, {}))

    def by_label(self, label: str) -> dict[str, dict]:
        """Toutes les entites d'un type (Location, Faction, etc.)."""
        data = self._load()
        prefix = f":{label}:"
        return {k: v for k, v in data.items() if prefix in k}

    def by_kind(self, kind: str = "theme") -> dict[str, str]:
        """Toutes les entites ayant un type d'audio donne."""
        data = self._load()
        return {k: v[kind] for k, v in data.items() if kind in v}

    def unassign(self, entity_key: str, kind: str = "theme") -> bool:
        """Retire un audio."""
        data = self._load()
        entry = data.get(entity_key, {})
        if kind in entry:
            del entry[kind]
            if not entry:
                del data[entity_key]
            self._save()
            return True
        return False

    def all_keys(self) -> list[str]:
        """Toutes les entites mappees."""
        return sorted(self._load().keys())

    def count(self) -> int:
        return len(self._load())


_MAP: dict[str, AudioMap] = {}


def get_audio_map(path: Optional[Path] = None) -> AudioMap:
    key = str(path) if path else "<default>"
    if key not in _MAP:
        _MAP[key] = AudioMap(path)
    return _MAP[key]


def reset_audio_map() -> None:
    _MAP.clear()


if __name__ == "__main__":
    print("=== Audio KG Map — self-check ===")

    m = AudioMap(Path("/tmp/test_audio_kg.json"))

    m.assign("urth:Location:Nessus", "D:/music/nessus_theme.wav", kind="theme")
    m.assign("urth:Location:Nessus", "sfx/crowd/murmur", kind="ambient")
    m.assign("urth:Faction:Guilde", "D:/music/guilde_marche.wav", kind="theme")
    m.assign("urth:Item:Terminus", "sfx/sword/unsheath", kind="sfx")

    print(f"Mapped: {m.count()} entities")
    print(f"Nessus theme: {m.lookup('urth:Location:Nessus')}")
    print(f"Nessus all: {m.lookup_all('urth:Location:Nessus')}")
    print(f"Locations: {m.by_label('Location')}")
    print(f"Themes: {m.by_kind('theme')}")

    m.unassign("urth:Item:Terminus", "sfx")
    print(f"\nAfter unassign: {m.count()} entities")

    print("\nSelf-check OK")
