"""
crafty_slug.py — Slug canonique (fix B1 bilan v5)
==================================================
Garantit unicité et déterminisme du slug prospect.
Règle : lower → strip accents → alphanum+tiret → dedup tirets → max 60 chars.
"""

from __future__ import annotations
import re
import unicodedata


def canonicalize(text: str) -> str:
    """Retourne le slug canonique d'un texte."""
    # 1. Normalise les accents (NFD → strip combining chars)
    nfd = unicodedata.normalize("NFD", text.lower())
    ascii_str = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # 2. Remplace tout non-alphanum par tiret
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str)
    # 3. Strip tirets bord + dedup
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    # 4. Tronque à 60 chars (bord propre sur tiret si possible)
    if len(slug) > 60:
        slug = slug[:60].rstrip("-")
    return slug


def prospect_slug(name: str, domain: str = "") -> str:
    """Slug unique prospect = canonicalize(name) [+ '-' + domain_root]."""
    base = canonicalize(name)
    if domain:
        root = canonicalize(domain.split(".")[0])
        combined = f"{base}-{root}"
        return combined[:60].rstrip("-")
    return base
