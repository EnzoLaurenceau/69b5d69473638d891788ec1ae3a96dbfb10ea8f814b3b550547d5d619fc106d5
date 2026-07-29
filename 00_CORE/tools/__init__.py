"""Bibliothèque d'outils externes encapsulés de la Forge. Voir registry.json + TOOLS.md."""
from __future__ import annotations
import json
from pathlib import Path

_REGISTRY = Path(__file__).parent / "registry.json"
_RESOURCES = Path(__file__).parent.parent.parent / "07_KNOWLEDGE_BASE" / "external_resources.json"


def _parse_nmp(line: str, prefix: str) -> dict | None:
    parts = line.split("|", 6)
    if len(parts) < 6 or parts[0] != prefix:
        return None
    return {"id": parts[1], "type": parts[2], "priority": parts[3],
            "purpose": parts[4], "wrapper": parts[5],
            "tags": parts[6].split(",") if len(parts) > 6 else []}


def parse_registry() -> list[dict]:
    """Parse registry.json NMP tools → list[dict(id,kind,status,purpose,wrapper,tags)]."""
    d = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    result = []
    for line in d.get("tools", []):
        parts = line.split("|", 6)
        if len(parts) >= 6 and parts[0] == "TOOL":
            result.append({"id": parts[1], "kind": parts[2], "status": parts[3],
                           "purpose": parts[4], "wrapper": parts[5],
                           "tags": parts[6].split(",") if len(parts) > 6 else []})
    return result


def parse_resources() -> list[dict]:
    """Parse external_resources.json NMP resources → list[dict]."""
    d = json.loads(_RESOURCES.read_text(encoding="utf-8"))
    return [r for r in (_parse_nmp(line, "RES") for line in d.get("resources", [])) if r]


def find_tool(query: str) -> list[dict]:
    """Recherche floue dans le registry par mot-clé (id/tags/purpose)."""
    q = query.lower()
    return [t for t in parse_registry()
            if q in t["id"] or q in t["purpose"].lower() or any(q in tag for tag in t["tags"])]
