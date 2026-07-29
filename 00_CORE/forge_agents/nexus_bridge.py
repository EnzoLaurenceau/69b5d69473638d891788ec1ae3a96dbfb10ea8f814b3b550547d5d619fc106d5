"""
nexus_bridge.py — Interface unifiée Nexus pour la Forge
========================================================
Remplace d'un coup :
  • openviking.py       (context retrieval → nexus hybrid search)
  • semantic_cache.py   (dedup → nexus CAS automatique)
  • graphify_checkpointer.py (checkpoints + graph.json → nexus VFS)

Architecture :
  nexusd embarqué (embedded, zéro daemon externe) — démarre dans le
  process Python avec data_dir=./nexus-data. Si nexus non installé,
  bascule sur les fallbacks JSON/SQLite existants (dégradation gracieuse).

Installation : pip install nexus-ai-fs
Docs         : https://nexi-lab.github.io/nexus/

Namespaces VFS utilisés :
  /memory/          → knowledge graph (remplace graph.json)
  /checkpoints/     → LangGraph state (remplace forge_checkpoints.db)
  /turbovec/        → état 4-bit index (remplace .nexus/forge_state.json)
  /findings/        → findings confirmés (remplace 06_FINDINGS/)
  /state/           → checkpoint.json session
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("NexusBridge")

FORGE_ROOT   = Path(__file__).parent.parent.parent
NEXUS_DATA   = FORGE_ROOT / "nexus-data"
# Fallback paths (si nexus absent)
_FALLBACK_GRAPH   = FORGE_ROOT / "04_GRAPHIFY" / "graph.json"


def _fallback_cp_dir() -> Path:
    """Répertoire de checkpoints de repli, cloisonné par tenant (W5-03c) et résolu à
    l'appel via forge_store — les checkpoints LangGraph d'un run appartiennent au client.
    Sans tenant en contexte → repli GLOBAL historique (05_STATE/checkpoints)."""
    try:
        from .forge_store import state_path
    except ImportError:
        from forge_agents.forge_store import state_path
    d = state_path("checkpoints")
    d.mkdir(parents=True, exist_ok=True)
    return d

# ─── Singleton Nexus connection ───────────────────────────────────────────────
_nx = None
_nx_available = None   # None = not tested yet

async def _connect() -> Optional[Any]:
    """Connexion lazy au nexusd embarqué. None si nexus absent."""
    global _nx, _nx_available
    if _nx_available is False:
        return None
    if _nx is not None:
        return _nx
    try:
        import nexus  # type: ignore
        # ponytail: profile="embedded" = storage+eventlog, zéro Raft/federation
        _nx = await nexus.connect(config={
            "data_dir": str(NEXUS_DATA),
            "profile": "embedded",
        })
        _nx_available = True
        logger.info(f"[NexusBridge] connecté (embedded) data_dir={NEXUS_DATA}")
    except Exception as e:
        _nx_available = False
        logger.debug(f"[NexusBridge] nexus absent, mode fallback JSON : {e}")
        _nx = None
    return _nx

def _sync(coro):
    """Run async coroutine depuis contexte sync (forge est majoritairement sync)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Dans un event loop existant (LangGraph async) → future
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(asyncio.run, coro)
                return future.result(timeout=10)
        else:
            return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)

# ─── Memory : store + retrieve (remplace openviking + graphify_index) ─────────

async def _memory_store_async(key: str, text: str, metadata: dict | None = None) -> bool:
    nx = await _connect()
    if nx is None:
        # Fallback graph.json
        try:
            data = json.loads(_FALLBACK_GRAPH.read_text()) if _FALLBACK_GRAPH.exists() else {"nodes": []}
            node = {"id": key, "text": text, **(metadata or {})}
            # Dédoublonne par id
            data["nodes"] = [n for n in data["nodes"] if n.get("id") != key] + [node]
            _FALLBACK_GRAPH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.debug(f"[NexusBridge] fallback store fail: {e}")
        return False
    try:
        path = f"/memory/{key}.md"
        await nx.write(path, text.encode())
        return True
    except Exception as e:
        logger.debug(f"[NexusBridge] memory_store fail: {e}")
        return False

async def _memory_retrieve_async(query: str, k: int = 5, max_chars: int = 1200) -> str:
    nx = await _connect()
    if nx is None:
        # Fallback graph.json keyword search (même logique qu'openviking)
        try:
            if not _FALLBACK_GRAPH.exists():
                return ""
            graph = json.loads(_FALLBACK_GRAPH.read_text())
            keywords = query.lower().split()
            nodes = graph.get("nodes", [])
            scored = []
            for n in nodes:
                txt = json.dumps(n).lower()
                score = sum(1 for kw in keywords if kw in txt)
                if score > 0:
                    scored.append((score, n))
            scored.sort(reverse=True)
            results = [json.dumps(n, ensure_ascii=False)[:200] for _, n in scored[:k]]
            return "\n".join(results)[:max_chars] if results else ""
        except Exception:
            return ""
    try:
        results = await nx.search(query, mode="hybrid", limit=k)
        chunks = [r.content if hasattr(r, "content") else str(r) for r in results]
        return "\n".join(chunks)[:max_chars]
    except Exception as e:
        logger.debug(f"[NexusBridge] memory_retrieve fail: {e}")
        return ""

def memory_store(key: str, text: str, metadata: dict | None = None) -> bool:
    """Indexe du contenu. Remplace graphify_index()."""
    return _sync(_memory_store_async(key, text, metadata))

def memory_retrieve(query: str, k: int = 5, max_chars: int = 1200) -> str:
    """Récupère le contexte le plus pertinent. Remplace openviking.retrieve_context()."""
    return _sync(_memory_retrieve_async(query, k, max_chars))

# ─── Checkpoints : LangGraph state (remplace graphify_checkpointer) ───────────

async def _cp_put_async(thread_id: str, state: dict) -> bool:
    nx = await _connect()
    payload = json.dumps(state, ensure_ascii=False, default=str).encode()
    if nx is None:
        (_fallback_cp_dir() / f"{thread_id}.json").write_bytes(payload)
        return False
    try:
        await nx.write(f"/checkpoints/{thread_id}.json", payload)
        return True
    except Exception as e:
        logger.debug(f"[NexusBridge] cp_put fail: {e}")
        (_fallback_cp_dir() / f"{thread_id}.json").write_bytes(payload)
        return False

async def _cp_get_async(thread_id: str) -> dict:
    nx = await _connect()
    if nx is None:
        p = _fallback_cp_dir() / f"{thread_id}.json"
        return json.loads(p.read_bytes()) if p.exists() else {}
    try:
        data = await nx.read(f"/checkpoints/{thread_id}.json")
        return json.loads(data)
    except Exception:
        p = _fallback_cp_dir() / f"{thread_id}.json"
        return json.loads(p.read_bytes()) if p.exists() else {}

def cp_put(thread_id: str, state: dict) -> bool:
    """Sauvegarde un checkpoint LangGraph. Remplace forge_db.cp_put()."""
    return _sync(_cp_put_async(thread_id, state))

def cp_get(thread_id: str) -> dict:
    """Récupère un checkpoint. Remplace forge_db.cp_get()."""
    return _sync(_cp_get_async(thread_id))

# ─── turbovec state redirect ───────────────────────────────────────────────────

async def _turbovec_write_async(state: dict) -> bool:
    nx = await _connect()
    payload = json.dumps(state, ensure_ascii=False, default=str).encode()
    if nx is None:
        p = FORGE_ROOT / ".nexus" / "forge_state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
        return False
    try:
        await nx.write("/turbovec/state.json", payload)
        return True
    except Exception as e:
        logger.debug(f"[NexusBridge] turbovec_write fail: {e}")
        p = FORGE_ROOT / ".nexus" / "forge_state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
        return False

async def _turbovec_read_async() -> dict:
    nx = await _connect()
    if nx is None:
        p = FORGE_ROOT / ".nexus" / "forge_state.json"
        return json.loads(p.read_bytes()) if p.exists() else {}
    try:
        data = await nx.read("/turbovec/state.json")
        return json.loads(data)
    except Exception:
        p = FORGE_ROOT / ".nexus" / "forge_state.json"
        return json.loads(p.read_bytes()) if p.exists() else {}

def turbovec_write(state: dict) -> bool:
    return _sync(_turbovec_write_async(state))

def turbovec_read() -> dict:
    return _sync(_turbovec_read_async())

# ─── Findings store ───────────────────────────────────────────────────────────

async def _finding_put_async(finding_id: str, content: str, confirmed: bool = False) -> bool:
    nx = await _connect()
    sub = "confirmed" if confirmed else "pending"
    payload = content.encode()
    if nx is None:
        p = FORGE_ROOT / "06_FINDINGS" / sub / f"{finding_id}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
        return False
    try:
        await nx.write(f"/findings/{sub}/{finding_id}.md", payload)
        return True
    except Exception as e:
        logger.debug(f"[NexusBridge] finding_put fail: {e}")
        return False

def finding_put(finding_id: str, content: str, confirmed: bool = False) -> bool:
    return _sync(_finding_put_async(finding_id, content, confirmed))

# ─── Health ───────────────────────────────────────────────────────────────────

def health() -> dict:
    """Retourne le statut nexus (disponible ou fallback)."""
    return {
        "nexus": _nx_available,
        "data_dir": str(NEXUS_DATA),
        "fallback_graph": str(_FALLBACK_GRAPH),
    }
