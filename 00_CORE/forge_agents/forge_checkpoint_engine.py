"""
forge_checkpoint_engine.py — Checkpointing intelligent par delta (V6.1)
========================================================================
Implémente la règle affinée en session de design (ChatGPT, 2026-07) :

    "Le système effectue un checkpoint toutes les 2 interactions
     utilisateur-IA, OU immédiatement en cas d'événement critique.
     Chaque checkpoint est un snapshot différentiel compressé du state
     global, incluant uniquement les changements significatifs des
     agents, de la mémoire, du graphe et des métriques."

AVANT ce fichier : `checkpoint_state_to_json()` était appelé après
CHAQUE step LangGraph (forge_graph.py:402), sans filtre — snapshot
complet à chaque tour. C'est exactement le piège identifié dans la
session de design ("plus de cache/snapshot = plus rapide" est FAUX) :
coût inutile, pas de notion de delta ni d'importance.

Ce module NE remplace PAS le stockage existant (cp_put/checkpoint_state_to_json
via nexus_bridge, déjà fonctionnel avec fallback JSON) — il AJOUTE la couche
de décision (trigger) + la chaîne d'audit event-sourced par-dessus, et calcule
un delta de surface (clés top-level) pour savoir CE QUI a changé sans dupliquer
un moteur de diff générique qui n'existe pas encore dans la Forge.

Portée honnête (MVP) :
  - Le déclenchement (2 tours OU critique) et la chaîne checkpoint_id/parent
    sont réels et testés sans dépendance externe.
  - Le "delta" est un diff de surface (clés changées + tailles de listes),
    pas un vrai diff structurel profond ni un replay incrémental complet —
    le state complet reste stocké à chaque checkpoint déclenché (via le
    mécanisme existant), donc la restauration est fiable dès aujourd'hui.
    Un vrai event-sourcing (stockage delta-only + replay) est un follow-up,
    pas fait ici pour ne pas fragiliser la restauration.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("forge_checkpoint_engine")

FORGE_ROOT = Path(__file__).parent.parent.parent
STATE_DIR = FORGE_ROOT / "05_STATE"
def _counter_path() -> Path:
    return state_path("turn_counter.json")

def _chain_path() -> Path:
    return state_path("checkpoint_chain.jsonl")


# Clés de state suivies pour le calcul de delta (surface, pas de deep-diff lib dispo)
TRACKED_KEYS = [
    "level", "cycle", "current_agent", "findings",
    "progress_done", "progress_todo", "meta_confidence", "meta_risk",
    "kernel_domain", "lazy_strategy",
]


def _now() -> str:
    return datetime.datetime.now().isoformat()


class TurnCheckpointer:
    """
    Compte les tours user<->IA, décide s'il faut snapshotter, calcule un delta
    de surface, et persiste via le mécanisme existant (checkpoint_state_to_json)
    tout en tenant une chaîne d'audit (checkpoint_id -> parent) légère et lisible.
    """

    def __init__(self, every_n_turns: int = 2):
        self.every_n_turns = every_n_turns
        self._turn_count = 0
        self._last_checkpoint_id: Optional[str] = None
        self._last_full_state: dict = {}
        self._forced_critical = False
        self._load()

    # ── Persistence du compteur (survit aux restarts process) ───────────────

    def _load(self) -> None:
        try:
            cp = _counter_path()
            if cp.exists():
                data = json.loads(cp.read_text(encoding="utf-8"))
                self._turn_count = data.get("turn_count", 0)
                self._last_checkpoint_id = data.get("last_checkpoint_id")
        except Exception as e:
            logger.debug(f"[checkpoint_engine] load counter: {e}")

    def _save_counter(self) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            _counter_path().write_text(json.dumps({
                "turn_count": self._turn_count,
                "last_checkpoint_id": self._last_checkpoint_id,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[checkpoint_engine] save counter: {e}")

    # ── API ───────────────────────────────────────────────────────────────

    def force_critical(self, reason: str = "") -> None:
        """A appeler par le code appelant (erreur, CVE alert, jury REJECTED...)
        pour forcer un checkpoint immédiat au prochain record_turn()."""
        self._forced_critical = True
        self._critical_reason = reason

    def compute_delta(self, new_state: dict) -> dict:
        """Diff de surface entre le dernier state complet connu et le nouveau."""
        delta: dict[str, Any] = {}
        for key in TRACKED_KEYS:
            old_val = self._last_full_state.get(key)
            new_val = new_state.get(key)
            if isinstance(new_val, list) and isinstance(old_val, list):
                if len(new_val) != len(old_val):
                    delta[key] = {"len_before": len(old_val), "len_after": len(new_val)}
            elif old_val != new_val:
                delta[key] = {"before": old_val, "after": new_val}
        return delta

    def record_turn(self, state: dict, critical: bool = False, reason: str = "") -> Optional[dict]:
        """
        Appelé après chaque tour (un step de graph, ou un échange user<->IA).
        Retourne le snapshot persisté si un checkpoint a été déclenché, sinon None
        (le tour est alors gardé seulement en mémoire éphémère — pas d'I/O disque).
        """
        self._turn_count += 1
        is_critical = critical or self._forced_critical
        crit_reason = reason or getattr(self, "_critical_reason", "")
        self._forced_critical = False

        trigger = is_critical or (self._turn_count % self.every_n_turns == 0)
        if not trigger:
            # Ephémère : pas de snapshot disque, juste mise à jour de l'état en RAM
            # pour que le prochain delta reste correct.
            self._last_full_state = {**self._last_full_state, **{k: state.get(k) for k in TRACKED_KEYS}}
            self._save_counter()
            return None

        delta = self.compute_delta(state)
        checkpoint_id = f"cp_{self._turn_count}"
        record = {
            "timestamp": _now(),
            "checkpoint_id": checkpoint_id,
            "parent": self._last_checkpoint_id,
            "trigger": "critical" if is_critical else f"every_{self.every_n_turns}_turns",
            "reason": crit_reason,
            "pipeline_state": {"level": state.get("level"), "cycle": state.get("cycle")},
            "active_agents": [state.get("current_agent")] if state.get("current_agent") else [],
            "memory_delta": {k: v for k, v in delta.items() if k in ("findings", "progress_done", "progress_todo")},
            "graph_delta": {k: v for k, v in delta.items() if k in ("level", "cycle", "kernel_domain")},
            "metrics_delta": {k: v for k, v in delta.items() if k.startswith("meta_") or k == "lazy_strategy"},
        }

        # 1. Persistance du state COMPLET via le mécanisme existant (fiabilité restore)
        try:
            from .graphify_checkpointer import checkpoint_state_to_json
            checkpoint_state_to_json(state, label=checkpoint_id)
        except Exception as e:
            logger.warning(f"[checkpoint_engine] persist state complet échoué: {e}")

        # 2. Append à la chaîne d'audit (event-sourced, léger, lisible par un humain)
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(_chain_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[checkpoint_engine] append chain échoué: {e}")

        self._last_checkpoint_id = checkpoint_id
        self._last_full_state = {k: state.get(k) for k in TRACKED_KEYS}
        self._save_counter()
        return record

    def restore_latest(self) -> dict:
        """
        Restaure le dernier state COMPLET connu (fiable dès aujourd'hui).
        La chaîne checkpoint_chain.jsonl donne l'historique/raison des snapshots
        pour audit, mais le restore lui-même relit le state complet le plus récent
        (pas de replay de delta — cf. portée honnête en tête de fichier).
        """
        from .graphify_checkpointer import load_last_checkpoint
        return load_last_checkpoint()

    def chain_tail(self, n: int = 10) -> list[dict]:
        """Dernières entrées de la chaîne d'audit (pour dashboard / debug)."""
        if not _chain_path().exists():
            return []
        try:
            lines = _chain_path().read_text(encoding="utf-8").splitlines()[-n:]
            return [json.loads(line) for line in lines if line.strip()]
        except Exception as e:
            logger.debug(f"[checkpoint_engine] chain_tail: {e}")
            return []

    def stats(self) -> dict:
        return {
            "turn_count": self._turn_count,
            "every_n_turns": self.every_n_turns,
            "last_checkpoint_id": self._last_checkpoint_id,
            "chain_entries": len(self.chain_tail(n=10_000)),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_checkpointer: Optional[TurnCheckpointer] = None


def get_turn_checkpointer() -> TurnCheckpointer:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = TurnCheckpointer()
    return _checkpointer


# ─── CLI / self-test (aucune dépendance externe) ─────────────────────────────

if __name__ == "__main__":
    import tempfile

    # Test isolé : redirige STATE_DIR vers un tmp dir pour ne pas polluer 05_STATE
    tmp = Path(tempfile.mkdtemp())
    # Override state_path for test
    import forge_agents.forge_store as _store
    _orig_state_path = _store.state_path
    _store.state_path = lambda name: tmp / name

    cp = TurnCheckpointer(every_n_turns=2)

    r1 = cp.record_turn({"level": "L1", "cycle": 1, "current_agent": "ORCH", "findings": []})
    print(f"turn 1 -> {'SNAPSHOT' if r1 else 'ephemeral'} (expected ephemeral)")
    assert r1 is None

    r2 = cp.record_turn({"level": "L1", "cycle": 2, "current_agent": "BUILDER", "findings": [{"id": "f1"}]})
    print(f"turn 2 -> {'SNAPSHOT' if r2 else 'ephemeral'} (expected SNAPSHOT, every_n_turns=2)")
    assert r2 is not None
    assert r2["checkpoint_id"] == "cp_2"

    cp.force_critical("jury REJECTED")
    r3 = cp.record_turn({"level": "L2", "cycle": 3, "current_agent": "CRITIC", "findings": [{"id": "f1"}]})
    print(f"turn 3 (forced critical) -> {'SNAPSHOT' if r3 else 'ephemeral'} (expected SNAPSHOT)")
    assert r3 is not None
    assert r3["trigger"] == "critical"
    assert r3["parent"] == "cp_2"

    print(f"\nstats -> {cp.stats()}")
    print("\nOK — trigger 2-tours + critical + chaînage parent validés (sans infra externe).")
