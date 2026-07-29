"""
memory_pruner.py — Archivage & Suppression Automatique de Nœuds
================================================================
Plan A §2.4 : Éviter l'engorgement de la Neural Map 3D et des contextes.

Règles:
  - 30 jours d'inactivité → status = "archived", retiré du cache chaud
  - 90 jours d'archivage → suppression définitive

Usage:
    from forge_agents.memory_pruner import get_pruner
    pruner = get_pruner()
    report = pruner.prune()  # exécute archivage + suppression
    stats = pruner.get_stats()  # état actuel
"""

from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("MemoryPruner")

FORGE_ROOT = Path(__file__).parent.parent.parent


def REGISTRY_DIR() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("system_registry")


def PRUNE_LOG() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("prune_log.json")


# Seuils (jours)
ARCHIVE_THRESHOLD_DAYS = 30
DELETE_THRESHOLD_DAYS = 90


class MemoryPruner:
    """Archivage et suppression automatique des nœuds inactifs."""

    def __init__(self):
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self._load_registry()

    def _load_registry(self):
        """Charge le system_registry si disponible."""
        nodes_file = REGISTRY_DIR() / "nodes.json"
        edges_file = REGISTRY_DIR() / "edges.json"
        try:
            if nodes_file.exists():
                self._nodes = json.loads(nodes_file.read_text(encoding="utf-8"))
            if edges_file.exists():
                self._edges = json.loads(edges_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[Pruner] Failed to load registry: {e}")

    def _save_registry(self):
        """Sauvegarde le system_registry."""
        try:
            REGISTRY_DIR().mkdir(parents=True, exist_ok=True)
            (REGISTRY_DIR() / "nodes.json").write_text(
                json.dumps(self._nodes, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[Pruner] Failed to save registry: {e}")

    def _log_prune(self, action: str, node_id: str, reason: str):
        """Log une action de pruning."""
        try:
            PRUNE_LOG().parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now().isoformat(),
                "action": action,
                "node_id": node_id,
                "reason": reason,
            }
            # Append to log
            existing = []
            if PRUNE_LOG().exists():
                try:
                    existing = json.loads(PRUNE_LOG().read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            existing.append(entry)
            PRUNE_LOG().write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def _get_last_used(self, node: dict) -> Optional[datetime]:
        """Extrait la date de dernière utilisation d'un nœud."""
        # Cherche dans différents champs possibles
        for field in ("last_used", "last_accessed", "updated_at", "last_update", "timestamp"):
            val = node.get(field)
            if val:
                try:
                    if isinstance(val, (int, float)):
                        return datetime.fromtimestamp(val)
                    return datetime.fromisoformat(val.replace("Z", "+00:00").replace("+00:00", ""))
                except Exception:
                    continue
        return None

    def prune(self) -> dict:
        """
        Exécute le pruning complet:
        1. Archive les nœuds inactifs depuis 30 jours
        2. Supprime les nœuds archivés depuis 90 jours
        """
        now = datetime.now()
        archived_count = 0
        deleted_count = 0
        skipped_count = 0

        for node in self._nodes:
            node_id = node.get("id", node.get("name", "unknown"))
            status = node.get("status", "active")

            # Skip already deleted
            if status == "deleted":
                continue

            last_used = self._get_last_used(node)
            if last_used is None:
                skipped_count += 1
                continue

            days_inactive = (now - last_used).days

            # Suppression (90 jours archivé)
            if status == "archived" and days_inactive >= DELETE_THRESHOLD_DAYS:
                node["status"] = "deleted"
                node["deleted_at"] = now.isoformat()
                deleted_count += 1
                self._log_prune("delete", node_id, f"archived for {days_inactive} days")
                logger.info(f"[Pruner] Deleted: {node_id} (archived {days_inactive}d)")

            # Archivage (30 jours inactif)
            elif status == "active" and days_inactive >= ARCHIVE_THRESHOLD_DAYS:
                node["status"] = "archived"
                node["archived_at"] = now.isoformat()
                archived_count += 1
                self._log_prune("archive", node_id, f"inactive for {days_inactive} days")
                logger.info(f"[Pruner] Archived: {node_id} (inactive {days_inactive}d)")

        # Sauvegarder si des changements ont eu lieu
        if archived_count > 0 or deleted_count > 0:
            self._save_registry()

        report = {
            "archived": archived_count,
            "deleted": deleted_count,
            "skipped": skipped_count,
            "total_nodes": len(self._nodes),
            "timestamp": now.isoformat(),
        }
        logger.info(f"[Pruner] Done: {archived_count} archived, {deleted_count} deleted")
        return report

    def get_stats(self) -> dict:
        """Retourne les statistiques de pruning."""
        active = sum(1 for n in self._nodes if n.get("status", "active") == "active")
        archived = sum(1 for n in self._nodes if n.get("status") == "archived")
        deleted = sum(1 for n in self._nodes if n.get("status") == "deleted")

        return {
            "total": len(self._nodes),
            "active": active,
            "archived": archived,
            "deleted": deleted,
            "archive_threshold_days": ARCHIVE_THRESHOLD_DAYS,
            "delete_threshold_days": DELETE_THRESHOLD_DAYS,
        }

    def restore(self, node_id: str) -> bool:
        """Restaure un nœud archivé."""
        for node in self._nodes:
            if node.get("id") == node_id and node.get("status") == "archived":
                node["status"] = "active"
                node["restored_at"] = datetime.now().isoformat()
                self._save_registry()
                logger.info(f"[Pruner] Restored: {node_id}")
                return True
        return False


# Singleton
_instance: MemoryPruner | None = None


def get_pruner() -> MemoryPruner:
    global _instance
    if _instance is None:
        _instance = MemoryPruner()
    return _instance
