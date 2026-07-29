"""
sfx_pipe.py — Pipeline SFX : banque categorisee, variations, layering (E4-03)
==============================================================================
Un RPG a besoin de centaines de petits sons : pas de marche, cliquetis d'epee,
cri de marchand, bruissement de feuilles. Ce module organise ces effets en
banque categorisee et fournit : selection aleatoire (variations), layering
(combinaison), et export.

ARCHITECTURE
------------
La banque est un JSON persistant (sfx_bank.json) qui mappe categories vers
listes de fichiers. Les fichiers WAV eux-memes ne sont PAS dans le depot
(assets binaires). La banque stocke les METADONNEES : chemin, duree, tags.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.sfx_pipe import get_sfx_bank

    bank = get_sfx_bank()
    bank.register("footsteps/stone", "D:/sfx/step_stone_01.wav", tags=["step", "stone"])
    bank.register("footsteps/stone", "D:/sfx/step_stone_02.wav", tags=["step", "stone"])

    # Selection aleatoire (variation)
    path = bank.pick("footsteps/stone")

    # Layering
    from forge_agents.sfx_pipe import layer_sfx
    combined = layer_sfx([path1, path2], output="combined.wav")

Verification : python -m forge_agents.sfx_pipe
"""

from __future__ import annotations

import json
import logging
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("SfxPipe")


@dataclass
class SfxEntry:
    """Entree dans la banque SFX."""
    path: str
    duration: float = 0.0
    tags: list[str] = field(default_factory=list)
    added_at: float = 0.0


class SfxBank:
    """Banque d'effets sonores categorisee.

    Categories hierarchiques separees par '/' : "footsteps/stone", "ui/click".
    Chaque categorie peut contenir N fichiers — pick() en choisit un au hasard
    pour produire des variations.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self._data: dict[str, list[dict]] = {}
        self._loaded = False

    def _ensure_path(self) -> Path:
        if self._path is None:
            from .forge_store import state_path
            self._path = state_path("sfx_bank.json")
        return self._path

    def _load(self) -> dict:
        if self._loaded:
            return self._data
        p = self._ensure_path()
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
            self._data = dict(raw)
        except (OSError, ValueError):
            self._data = {}
        self._loaded = True
        return self._data

    def _save(self) -> None:
        p = self._ensure_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    def register(self, category: str, path: str | Path,
                 duration: float = 0.0, tags: Optional[list[str]] = None) -> SfxEntry:
        """Ajoute un fichier SFX a une categorie."""
        import time
        entry = SfxEntry(
            path=str(path),
            duration=duration,
            tags=tags or [],
            added_at=time.time(),
        )
        data = self._load()
        data.setdefault(category, [])
        # Eviter les doublons (meme chemin dans meme categorie)
        if any(e["path"] == entry.path for e in data[category]):
            logger.debug("[SfxBank] %s already in %s", entry.path, category)
            return entry
        data[category].append({
            "path": entry.path,
            "duration": entry.duration,
            "tags": entry.tags,
            "added_at": entry.added_at,
        })
        self._save()
        logger.info("[SfxBank] registered %s -> %s", entry.path, category)
        return entry

    def pick(self, category: str) -> Optional[str]:
        """Selectionne aleatoirement un fichier dans une categorie (variation)."""
        data = self._load()
        entries = data.get(category, [])
        if not entries:
            # Essayer la categorie parente (ex: "footsteps/stone" -> "footsteps")
            parent = category.rsplit("/", 1)[0]
            if parent != category:
                entries = data.get(parent, [])
        if not entries:
            logger.warning("[SfxBank] category '%s' is empty", category)
            return None
        chosen = random.choice(entries)
        return chosen["path"]

    def categories(self) -> list[str]:
        """Liste toutes les categories."""
        return sorted(self._load().keys())

    def count(self, category: str = "") -> int:
        """Nombre de fichiers dans une categorie (ou total)."""
        data = self._load()
        if category:
            return len(data.get(category, []))
        return sum(len(v) for v in data.values())

    def entries(self, category: str) -> list[dict]:
        """Liste les entrees d'une categorie."""
        return list(self._load().get(category, []))

    def remove(self, category: str, path: str) -> bool:
        """Retire un fichier d'une categorie."""
        data = self._load()
        entries = data.get(category, [])
        before = len(entries)
        data[category] = [e for e in entries if e["path"] != path]
        if len(data[category]) < before:
            if not data[category]:
                del data[category]
            self._save()
            return True
        return False


_BANK: dict[str, SfxBank] = {}


def get_sfx_bank(path: Optional[Path] = None) -> SfxBank:
    """Instance singleton de la banque SFX."""
    key = str(path) if path else "<default>"
    if key not in _BANK:
        _BANK[key] = SfxBank(path)
    return _BANK[key]


def reset_sfx_bank() -> None:
    """Reinitialise le cache (tests)."""
    _BANK.clear()


def layer_sfx(inputs: list[str | Path], output: str | Path = None,
              volumes: Optional[list[float]] = None) -> Path:
    """Combine plusieurs fichiers SFX en un seul (layering).

    Utile pour creer des effets composes : pas + echo + ambiance.
    Utilise audio_process.mix() sous le capot.
    """
    from .audio_pipe import audio_process
    if not inputs:
        raise ValueError("Au moins un fichier requis pour le layering")
    return audio_process.mix(inputs, output=str(output) if output else None,
                              volumes=volumes)


if __name__ == "__main__":
    print("=== SFX Pipeline — self-check ===")

    bank = SfxBank(Path(tempfile.mktemp(suffix=".json")))

    # Register
    bank.register("footsteps/stone", "/sfx/step1.wav", duration=0.5, tags=["step"])
    bank.register("footsteps/stone", "/sfx/step2.wav", duration=0.6, tags=["step"])
    bank.register("footsteps/wood", "/sfx/wood1.wav", duration=0.4, tags=["step", "wood"])
    bank.register("ui/click", "/sfx/click.wav", duration=0.1, tags=["ui"])

    print(f"Categories: {bank.categories()}")
    print(f"Total entries: {bank.count()}")
    print(f"footsteps/stone: {bank.count('footsteps/stone')} entries")

    # Pick (variation)
    picked = bank.pick("footsteps/stone")
    print(f"\nRandom pick from footsteps/stone: {picked}")

    # Pick from parent
    picked2 = bank.pick("footsteps")
    print(f"Random pick from footsteps (parent): {picked2}")

    # Remove
    bank.remove("ui/click", "/sfx/click.wav")
    print(f"\nAfter remove: {bank.count()} entries")

    print("\nSelf-check OK")
