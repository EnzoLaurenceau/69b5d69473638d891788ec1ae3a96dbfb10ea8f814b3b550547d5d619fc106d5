"""
obsidian_sync.py — Moteur d'Exportation Obsidian Vault
========================================================
Plan A §2.1 : Script de synchronisation du vault Markdown.

Wrapper around KnowledgeCurator pour exécution standalone.
Génère le vault sous /vault/ avec:
  /Agents/       — Fiches d'identité des agents
  /Projects/     — Fiches de tâches + Mermaid
  /Knowledge/    — Concepts techniques
  /Decisions/    — ADR (Architecture Decision Records)
  /Memories/     — Épisodique + Sémantique

Usage:
    python scripts/obsidian_sync.py
    python scripts/obsidian_sync.py --full  # full sync
"""

from __future__ import annotations
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("ObsidianSync")

FORGE_ROOT = Path(__file__).parent.parent


def main():
    """Point d'entrée standalone."""
    sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

    try:
        from forge_agents.knowledge_curator import get_curator
    except ImportError:
        logger.error("Cannot import knowledge_curator")
        sys.exit(1)

    curator = get_curator()

    # Subscribe to events for auto-sync
    curator.subscribe_to_events()

    if "--full" in sys.argv:
        logger.info("Running full sync...")
        results = curator.full_sync()
    else:
        logger.info("Running incremental sync...")
        results = curator.curate({"current_task": "manual sync"})

    logger.info(f"Sync complete: {results}")


if __name__ == "__main__":
    main()
