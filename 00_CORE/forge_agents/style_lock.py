"""
style_lock.py — Style-lock : bible visuelle stockée dans le World-KG (E3-02)
=============================================================================
Chaque génération d'asset visuel (concept art, sprite, texture) doit respecter
une bible visuelle cohérente : palette de couleurs, ambiance, éclairage, suffixe
de prompt. Sans style-lock, 500 assets générés indépendamment ne vont pas
ensemble — c'est le risque n°3 de l'audit.

Ce module ne génère PAS d'images. Il stocke et rend le style ; c'est `open_gen_ai`
(ou ComfyUI, E3-03) qui l'injecte dans le prompt de génération.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.style_lock import StyleLock, store_lock, get_lock, inject_style

    lock = StyleLock(
        palette=["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
        mood="dark, mysterious, ancient",
        lighting="low-key, torchlight, bioluminescent accents",
        prompt_suffix=", dark fantasy art style, muted colors, detailed textures",
        refs=["Moebius (ligne claire sombre)", "Blasphemous (pixel art gothique)"],
    )

    store_lock(kg, lock)                   # stocke dans le World-KG
    lock = get_lock(kg)                    # relit
    prompt = inject_style("un marchand", lock)  # "un marchand, dark fantasy art style, ..."

Vérification : `python -m forge_agents.style_lock`
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("StyleLock")

#: Nom du DesignDecision dans le World-KG. Un seul par monde.
LOCK_NAME = "Visual Style Lock"


@dataclass
class StyleLock:
    """Bible visuelle d'un monde. Sera injectée dans chaque prompt de génération."""

    #: Palette de couleurs hex (4-8 couleurs dominantes).
    palette: list[str] = field(default_factory=list)

    #: Ambiance générale (ex: "dark, mysterious, ancient").
    mood: str = ""

    #: Éclairage (ex: "low-key, torchlight, bioluminescent accents").
    lighting: str = ""

    #: Suffixe ajouté à chaque prompt de génération d'image.
    prompt_suffix: str = ""

    #: Références visuelles (noms d'artistes, styles, jeux).
    refs: list[str] = field(default_factory=list)

    #: Résolution cible (ex: "1024x1024").
    resolution: str = ""

    #: Style technique (ex: "pixel art", "oil painting", "3D render").
    technique: str = ""

    def to_dict(self) -> dict:
        """Sérialise en dict pour stockage KG."""
        return {
            "palette": self.palette,
            "mood": self.mood,
            "lighting": self.lighting,
            "prompt_suffix": self.prompt_suffix,
            "refs": self.refs,
            "resolution": self.resolution,
            "technique": self.technique,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StyleLock":
        """Désérialise depuis un dict."""
        return cls(
            palette=d.get("palette", []),
            mood=d.get("mood", ""),
            lighting=d.get("lighting", ""),
            prompt_suffix=d.get("prompt_suffix", ""),
            refs=d.get("refs", []),
            resolution=d.get("resolution", ""),
            technique=d.get("technique", ""),
        )

    def describe(self) -> str:
        """Description lisible pour injection dans un prompt système."""
        parts = []
        if self.technique:
            parts.append(f"Technique: {self.technique}")
        if self.palette:
            parts.append(f"Palette: {', '.join(self.palette)}")
        if self.mood:
            parts.append(f"Mood: {self.mood}")
        if self.lighting:
            parts.append(f"Lighting: {self.lighting}")
        if self.refs:
            parts.append(f"References: {', '.join(self.refs)}")
        if self.resolution:
            parts.append(f"Resolution: {self.resolution}")
        return "\n".join(parts)


def store_lock(kg, lock: StyleLock) -> str:
    """Stocke le style-lock dans le World-KG comme DesignDecision.

    Écrase le précédent (un seul style-lock par monde).
    """
    existing = kg.get("DesignDecision", LOCK_NAME)
    if existing:
        # Mettre à jour
        key = existing.get("id", "")
        kg.upsert("DesignDecision", LOCK_NAME,
                   question="What is the visual style for this world?",
                   choice=json.dumps(lock.to_dict(), ensure_ascii=False),
                   rationale="Style-lock E3-02 : coherence visuelle du pipeline asset",
                   decided_by="E3-02",
                   canon="generated",
                   status="validated")
    else:
        key = kg.add_decision(
            LOCK_NAME,
            question="What is the visual style for this world?",
            choice=json.dumps(lock.to_dict(), ensure_ascii=False),
            rationale="Style-lock E3-02 : coherence visuelle du pipeline asset",
            decided_by="E3-02",
            canon="generated",
            status="validated")
    logger.info("[StyleLock] stored for world %s", kg.world_id)
    return key


def get_lock(kg) -> Optional[StyleLock]:
    """Lit le style-lock depuis le World-KG. None si absent."""
    node = kg.get("DesignDecision", LOCK_NAME)
    if node is None:
        return None
    choice = node.get("choice", "")
    if not choice:
        return None
    try:
        data = json.loads(choice)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[StyleLock] choice is not valid JSON: %s", choice[:100])
        return None
    return StyleLock.from_dict(data)


def inject_style(prompt: str, lock: Optional[StyleLock]) -> str:
    """Ajoute le suffixe de style à un prompt de génération.

    Si lock est None ou n'a pas de suffixe, le prompt est rendu tel quel.
    Le séparateur est une virgule — pas un espace, pour ne pas fusionner le
    dernier mot du prompt avec le premier du suffixe.
    """
    if lock is None or not lock.prompt_suffix:
        return prompt
    suffix = lock.prompt_suffix.strip()
    if not suffix:
        return prompt
    # Éviter la double virgule si le prompt finit déjà par une ponctuation
    if prompt.rstrip().endswith((",", ";", ".")):
        return f"{prompt.rstrip()} {suffix.lstrip(', ')}"
    return f"{prompt}, {suffix.lstrip(', ')}"


if __name__ == "__main__":
    print("=== Style-lock — self-check ===")

    lock = StyleLock(
        palette=["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
        mood="dark, mysterious, ancient",
        lighting="low-key, torchlight",
        prompt_suffix="dark fantasy art style, muted colors, detailed textures",
        refs=["Moebius", "Blasphemous"],
        resolution="1024x1024",
        technique="digital painting",
    )

    print(f"\nStyle-lock :")
    print(lock.describe())

    # Serialize roundtrip
    d = lock.to_dict()
    lock2 = StyleLock.from_dict(d)
    assert lock2.palette == lock.palette
    assert lock2.mood == lock.mood
    assert lock2.prompt_suffix == lock.prompt_suffix
    print("\nRoundtrip OK")

    # Inject style
    p1 = inject_style("un marchand de reliques", lock)
    print(f"\nPrompt injecte : {p1}")
    assert "dark fantasy" in p1
    assert "marchand" in p1

    p2 = inject_style("un marchand de reliques,", lock)
    print(f"Prompt avec virgule : {p2}")
    assert ",," not in p2  # pas de double virgule

    p3 = inject_style("test", None)
    assert p3 == "test"
    print("Sans lock : prompt intact")

    print("\nSelf-check OK")
