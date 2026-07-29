"""
forge_db_fallback.py — Cervelet de secours (warm standby)
=========================================================
Enveloppe les moteurs EXISTANTS derrière la même API que forge_db, pour servir
de secours chaud quand PG+Redis sont injoignables (optiforge two-tier).

Backends de secours (aucune nouvelle dépendance — stdlib uniquement) :
  - SQLite local `04_GRAPHIFY/forge_fallback.db` : KV chaud + tables profondes
    (= le rôle de secours de Redis + Postgres). Cohabite avec le SqliteSaver
    natif de LangGraph (forge_checkpoints.db).
  - graph.json via graphify_index/graphify_query (déjà présents) : miroir des
    graphify_nodes pour rester lisible par l'outil Graphify / Claude.

Tenu à chaud par DUAL-WRITE depuis forge_db.apply() tant que la DB primaire est
up → quand la DB tombe, le secours est déjà synchro.

Recherche sémantique de secours : SimHash + distance de Hamming (réutilise
semantic_cache), pas de pgvector.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("forge_db_fallback")

FORGE_ROOT = Path(__file__).parent.parent.parent
FALLBACK_DB = FORGE_ROOT / "04_GRAPHIFY" / "forge_fallback.db"
FALLBACK_DB.parent.mkdir(parents=True, exist_ok=True)

from .semantic_cache import _tokenize, _simhash, _hamming_similarity

# Tables profondes connues (mêmes noms que forge_db, schéma générique JSON)
_DEEP_TABLES = ("findings", "episodes", "langgraph_checkpoints",
                "graphify_nodes", "gitnexus_symbols", "tasks")


class FallbackStore:
    """Secours SQLite + graph.json, API miroir de forge_db."""

    def __init__(self):
        self._conn = sqlite3.connect(str(FALLBACK_DB), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, exp REAL)")
        for t in _DEEP_TABLES:
            pk = "thread_id" if t == "langgraph_checkpoints" else "id"
            # Stockage générique : pk + blob JSON complet + texte pour la recherche
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {t} "
                f"({pk} TEXT PRIMARY KEY, row JSON, content TEXT, ts REAL)")
        self._conn.commit()

    # ── KV chaud (secours de Redis) ──────────────────────────────────────────

    def hot_get(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT v, exp FROM kv WHERE k=?", (key,))
        r = cur.fetchone()
        if not r:
            return None
        if r["exp"] and r["exp"] < time.time():
            self._conn.execute("DELETE FROM kv WHERE k=?", (key,))
            self._conn.commit()
            return None
        return r["v"]

    def hot_set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        exp = (time.time() + ttl) if ttl else None
        self._conn.execute(
            "INSERT INTO kv (k, v, exp) VALUES (?,?,?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v, exp=excluded.exp",
            (key, value, exp))
        self._conn.commit()

    def hot_incr(self, key: str, amount: int = 1) -> int:
        cur = self.hot_get(key)
        new = (int(cur) if cur and str(cur).lstrip("-").isdigit() else 0) + amount
        self.hot_set(key, str(new))
        return new

    # ── Tables profondes (secours de Postgres) ───────────────────────────────

    def deep_insert(self, table: str, row: dict) -> None:
        if table not in _DEEP_TABLES:
            logger.debug(f"[fallback] table inconnue {table}, ignorée")
            return
        pk = "thread_id" if table == "langgraph_checkpoints" else "id"
        key = str(row.get(pk) or f"auto-{int(time.time()*1000)}")
        content = str(row.get("content", "") or row.get("res", ""))
        row = {**row, pk: key}
        self._conn.execute(
            f"INSERT INTO {table} ({pk}, row, content, ts) VALUES (?,?,?,?) "
            f"ON CONFLICT({pk}) DO UPDATE SET row=excluded.row, content=excluded.content, ts=excluded.ts",
            (key, json.dumps(row, ensure_ascii=False, default=str), content, time.time()))
        self._conn.commit()
        # NB : pas de miroir vers graph.json — il est déprécié au profit de PG et
        # l'append de graphify_index recréait des nœuds à chaque write (non-idempotent).
        # Le secours conserve les graphify_nodes dans sa propre table SQLite ci-dessus.

    def deep_query(self, table: str, filt: Optional[dict] = None, limit: int = 50) -> list[dict]:
        if table not in _DEEP_TABLES:
            return []
        rows = self._conn.execute(
            f"SELECT row FROM {table} ORDER BY ts DESC LIMIT ?", (limit * 4,)).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["row"])
            if filt and not all(str(d.get(k)) == str(v) for k, v in filt.items()):
                continue
            out.append(d)
            if len(out) >= limit:
                break
        return out

    def deep_semantic(self, table: str, text: str, k: int = 5) -> list[dict]:
        if table not in _DEEP_TABLES:
            return []
        target = _simhash(_tokenize(text or ""))
        scored = []
        for r in self._conn.execute(
                f"SELECT row, content FROM {table}").fetchall():
            sim = _hamming_similarity(target, _simhash(_tokenize(r["content"] or "")))
            scored.append((sim, json.loads(r["row"])))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:k]]

    # ── Dual-write : rejouer une op de forge_db pour rester chaud ─────────────

    def apply(self, op: str, args: dict) -> None:
        if op == "hot_set":
            self.hot_set(args["key"], args["value"], args.get("ttl"))
        elif op == "deep_insert":
            self.deep_insert(args["table"], args["row"])


_fallback: Optional[FallbackStore] = None


def get_fallback() -> FallbackStore:
    global _fallback
    if _fallback is None:
        _fallback = FallbackStore()
    return _fallback
