"""
forge_db.py — Store unifié de la Forge : PostgreSQL(pgvector) + Redis
=====================================================================
Façade de persistance UNIQUE (optiforge.txt). Remplace les 5 stores éclatés
(SQLite LangGraph, graph.json, checkpoint.json, .nexus/*.json, gitnexus) par
une seule stack à deux vitesses :

  Redis (chaud)            → réflexes Cervelet, compteurs, état session, findings chauds
  Postgres + pgvector      → findings, episodes, checkpoints, graphify_nodes, gitnexus_symbols

Architecture two-tier (optiforge) :
  PRIMAIRE   = PG + Redis (cette façade)
  SECOURS    = LangGraph SQLite + graph.json + gitnexus (forge_db_fallback.py)
               warm standby tenu par DUAL-WRITE, activé SEULEMENT si DB injoignable.
  WAL        = 04_GRAPHIFY/wal.jsonl — journal des writes pendant une panne DB,
               rejoué (wal_replay) au retour de la DB.

Dépendances optionnelles : si `redis` / `psycopg` absents OU serveurs down,
bascule transparente sur le secours. Jamais bloquant.

API :
  hot_get/hot_set/hot_incr           → Redis (KV chaud)
  deep_insert/deep_query/deep_semantic → Postgres (tables profondes + pgvector)
  cp_put/cp_get                       → checkpoints (blob par thread_id)
  health()                            → {redis, postgres, fallback, wal_pending}
  wal_replay()                        → rejoue le journal après reconnexion
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("forge_db")

FORGE_ROOT = Path(__file__).parent.parent.parent
WAL_PATH = FORGE_ROOT / "04_GRAPHIFY" / "wal.jsonl"
WAL_PATH.parent.mkdir(parents=True, exist_ok=True)

# Réutilise le SimHash léger (aucune dépendance API) pour les embeddings pgvector
from .semantic_cache import _tokenize, _simhash

EMBED_DIM = 64


# ─── .env loader minimal ──────────────────────────────────────────────────────

def _load_env() -> dict:
    env = dict(os.environ)
    env_file = FORGE_ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return env


_ENV = _load_env()
DATABASE_URL = _ENV.get("DATABASE_URL", "postgresql://forge:forge@localhost:5433/forge")
REDIS_URL = _ENV.get("REDIS_URL", "redis://localhost:6380/0")


# ─── Embedding léger (SimHash → vecteur float 64-dim) ─────────────────────────

def light_embedding(text: str) -> list[float]:
    """SimHash 64 bits → vecteur [-1,1]^64. Déterministe, zéro appel API."""
    h = _simhash(_tokenize(text or ""), hashbits=EMBED_DIM)
    return [1.0 if (h >> i) & 1 else -1.0 for i in range(EMBED_DIM)]


# ─── ForgeDB ──────────────────────────────────────────────────────────────────

class ForgeDB:
    """Store unifié PG+Redis avec dual-write secours + WAL."""

    def __init__(self):
        self._redis = None
        self._pg = None
        self._fallback = None
        self._probed = False
        self.redis_ok = False
        self.pg_ok = False
        self._probe_backends()

    # ── Probe / connexions ────────────────────────────────────────────────────

    def _probe_backends(self) -> None:
        """Détecte une fois la dispo Redis/Postgres ; bascule secours sinon."""
        # Redis
        try:
            import redis  # type: ignore
            self._redis = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2,
                                                decode_responses=True)
            self._redis.ping()
            self.redis_ok = True
        except Exception as e:
            logger.info(f"[forge_db] Redis indisponible → secours ({e.__class__.__name__})")
            self._redis = None
            self.redis_ok = False

        # Postgres
        try:
            import psycopg  # type: ignore
            self._pg = psycopg.connect(DATABASE_URL, connect_timeout=3, autocommit=True)
            self._ensure_schema()
            self.pg_ok = True
        except Exception as e:
            logger.info(f"[forge_db] Postgres indisponible → secours ({e.__class__.__name__})")
            self._pg = None
            self.pg_ok = False

        self._probed = True
        # Mémorise si la DB a déjà été vue up : le WAL ne journalise QUE les
        # writes perdus pendant une panne d'une DB qui fonctionnait. En mode
        # secours permanent (PG/Redis jamais présents), le secours EST le store
        # de référence → pas de WAL (sinon il grossit sans fin).
        if not hasattr(self, "_ever_up"):
            self._ever_up = self.db_up
        elif self.db_up:
            self._ever_up = True

    @property
    def fallback(self):
        """Adaptateur secours chargé paresseusement (warm standby)."""
        if self._fallback is None:
            try:
                from .forge_db_fallback import get_fallback
                self._fallback = get_fallback()
            except Exception as e:
                logger.warning(f"[forge_db] Secours indisponible : {e}")
                self._fallback = _NullFallback()
        return self._fallback

    @property
    def db_up(self) -> bool:
        """La DB primaire est-elle exploitable (au moins un des deux back-ends) ?"""
        return self.redis_ok or self.pg_ok

    def _ensure_schema(self) -> None:
        """Crée extension + tables si absentes (idempotent)."""
        if not self._pg:
            return
        ddl = """
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY, agent TEXT, cycle INT, content TEXT,
            score REAL, status TEXT, ts DOUBLE PRECISION,
            embedding vector(64)
        );
        CREATE TABLE IF NOT EXISTS episodes (
            id BIGSERIAL PRIMARY KEY, signal TEXT, res TEXT, meta JSONB,
            salience REAL DEFAULT 0, ts DOUBLE PRECISION, dedup TEXT
        );
        ALTER TABLE episodes ADD COLUMN IF NOT EXISTS dedup TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS episodes_dedup_idx ON episodes(dedup);
        CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
            thread_id TEXT PRIMARY KEY, blob JSONB, ts DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS graphify_nodes (
            id TEXT PRIMARY KEY, agent TEXT, cycle INT, content TEXT,
            ts DOUBLE PRECISION, embedding vector(64)
        );
        CREATE TABLE IF NOT EXISTS gitnexus_symbols (
            id TEXT PRIMARY KEY, name TEXT, kind TEXT, payload JSONB
        );
        CREATE TABLE IF NOT EXISTS rag_docs (
            id TEXT PRIMARY KEY, doc_id TEXT, file_path TEXT, file_name TEXT,
            doc_hash TEXT, content TEXT, size_bytes BIGINT, agent TEXT,
            ts DOUBLE PRECISION, embedding vector(64)
        );
        CREATE INDEX IF NOT EXISTS rag_docs_doc_id_idx ON rag_docs(doc_id);
        CREATE TABLE IF NOT EXISTS token_sprints (
            id SERIAL PRIMARY KEY,
            sprint_id TEXT,
            task_id TEXT,
            task_type TEXT,
            model TEXT,
            tokens_estimated_in INT,
            tokens_estimated_out INT,
            tokens_actual_in INT,
            tokens_actual_out INT,
            cost_estimated_usd REAL,
            cost_actual_usd REAL,
            hallucination_detected BOOLEAN DEFAULT FALSE,
            latency_ms REAL DEFAULT 0,
            variance_pct REAL DEFAULT 0,
            auto_refinement_triggered BOOLEAN DEFAULT FALSE,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_token_sprints_sprint ON token_sprints(sprint_id);
        CREATE INDEX IF NOT EXISTS idx_token_sprints_task_type ON token_sprints(task_type);
        CREATE INDEX IF NOT EXISTS idx_token_sprints_model ON token_sprints(model);
        """
        # Backlog persistant (E1-01). Le DDL est DÉRIVÉ de `_TASK_PROPS` — ajouter
        # une propriété là-bas suffit, on ne recopie pas de colonnes ici. Import
        # tardif : forge_backlog appelle get_db(), un import au chargement du
        # module créerait un cycle.
        try:
            from .forge_backlog import table_ddl
            ddl += "\n        " + table_ddl()
        except Exception as e:  # pragma: no cover - le reste du schéma doit survivre
            logger.warning(f"[forge_db] DDL backlog ignoré : {e}")
        try:
            with self._pg.cursor() as cur:
                cur.execute(ddl)
        except Exception as e:
            logger.warning(f"[forge_db] _ensure_schema: {e}")

    # ── REDIS — KV chaud ──────────────────────────────────────────────────────

    def hot_get(self, key: str) -> Optional[str]:
        if self.redis_ok:
            try:
                return self._redis.get(key)
            except Exception:
                self.redis_ok = False
        return self.fallback.hot_get(key)

    def hot_set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        wrote = False
        if self.redis_ok:
            try:
                self._redis.set(key, value, ex=ttl)
                wrote = True
            except Exception:
                self.redis_ok = False
        # dual-write secours (best-effort) si DB up, sinon WAL
        if wrote:
            self._dualwrite("hot_set", {"key": key, "value": value, "ttl": ttl})
        else:
            self._on_outage("hot_set", {"key": key, "value": value, "ttl": ttl})
            self.fallback.hot_set(key, value, ttl)

    def hot_incr(self, key: str, amount: int = 1) -> int:
        if self.redis_ok:
            try:
                return int(self._redis.incrby(key, amount))
            except Exception:
                self.redis_ok = False
        return self.fallback.hot_incr(key, amount)

    # ── POSTGRES — tables profondes ──────────────────────────────────────────

    def deep_insert(self, table: str, row: dict) -> None:
        if self.pg_ok:
            try:
                self._pg_upsert(table, row)
                self._dualwrite("deep_insert", {"table": table, "row": row})
                return
            except Exception as e:
                logger.warning(f"[forge_db] deep_insert PG: {e}")
                self.pg_ok = False
        self._on_outage("deep_insert", {"table": table, "row": row})
        self.fallback.deep_insert(table, row)

    def _pg_upsert(self, table: str, row: dict) -> None:
        """Upsert idempotent par clé primaire (1ère colonne du row si 'id'/'thread_id')."""
        import psycopg
        import hashlib
        row = dict(row)
        # rag_docs : la clé métier est doc_id ; on la recopie en PK.
        if table == "rag_docs" and "id" not in row:
            row["id"] = row.get("doc_id") or row.get("doc_hash", "")
        # embedding auto pour les tables vectorielles
        if table in ("findings", "graphify_nodes", "rag_docs") and "embedding" not in row:
            src = row.get("content") or f"{row.get('file_name', '')} {row.get('file_path', '')}"
            row["embedding"] = light_embedding(src)
        # episodes : timeline append-only avec clé de dédup déterministe
        # (idempotence de la migration ; les events runtime distincts par ts
        #  obtiennent un dedup unique → toujours insérés).
        if table == "episodes":
            row.pop("id", None)
            sig = f"{row.get('signal','')}|{row.get('res','')}|{row.get('ts','')}"
            row["dedup"] = hashlib.md5(sig.encode()).hexdigest()
            cols = list(row.keys())
            placeholders = ", ".join(["%s"] * len(cols))
            vals = [json.dumps(row[c], ensure_ascii=False) if isinstance(row[c], (dict, list))
                    else row[c] for c in cols]
            with self._pg.cursor() as cur:
                cur.execute(
                    f"INSERT INTO episodes ({', '.join(cols)}) VALUES ({placeholders}) "
                    f"ON CONFLICT (dedup) DO NOTHING", vals)
            return
        cols = list(row.keys())
        pk = "thread_id" if table == "langgraph_checkpoints" else "id"
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT ({pk}) DO UPDATE SET {updates}")
        vals = []
        for c in cols:
            v = row[c]
            if c == "embedding" and isinstance(v, list):
                v = "[" + ",".join(str(x) for x in v) + "]"
            elif isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            vals.append(v)
        with self._pg.cursor() as cur:
            cur.execute(sql, vals)

    def deep_query(self, table: str, filt: Optional[dict] = None, limit: int = 50) -> list[dict]:
        if self.pg_ok:
            try:
                where, vals = "", []
                if filt:
                    where = " WHERE " + " AND ".join(f"{k}=%s" for k in filt)
                    vals = list(filt.values())
                with self._pg.cursor() as cur:
                    cur.execute(f"SELECT * FROM {table}{where} LIMIT %s", vals + [limit])
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"[forge_db] deep_query PG: {e}")
                self.pg_ok = False
        return self.fallback.deep_query(table, filt, limit)

    def deep_semantic(self, table: str, text: str, k: int = 5) -> list[dict]:
        """Recherche sémantique pgvector (cosine) sur embedding SimHash."""
        if self.pg_ok:
            try:
                emb = "[" + ",".join(str(x) for x in light_embedding(text)) + "]"
                with self._pg.cursor() as cur:
                    cur.execute(
                        f"SELECT *, embedding <=> %s AS dist FROM {table} "
                        f"ORDER BY dist ASC LIMIT %s", [emb, k])
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"[forge_db] deep_semantic PG: {e}")
                self.pg_ok = False
        return self.fallback.deep_semantic(table, text, k)

    # ── CHECKPOINTS (LangGraph blob par thread) ───────────────────────────────

    def cp_put(self, thread_id: str, blob: dict) -> None:
        self.deep_insert("langgraph_checkpoints",
                         {"thread_id": thread_id, "blob": blob, "ts": time.time()})

    def cp_get(self, thread_id: str) -> Optional[dict]:
        rows = self.deep_query("langgraph_checkpoints", {"thread_id": thread_id}, limit=1)
        if rows:
            b = rows[0].get("blob")
            return b if isinstance(b, dict) else json.loads(b) if b else None
        return None

    # ── DUAL-WRITE + WAL ──────────────────────────────────────────────────────

    def _dualwrite(self, op: str, args: dict) -> None:
        """DB up : miroir best-effort vers le secours pour le garder chaud."""
        try:
            self.fallback.apply(op, args)
        except Exception as e:
            logger.debug(f"[forge_db] dual-write secours échoué ({op}): {e}")

    def _on_outage(self, op: str, args: dict) -> None:
        """DB down : journalise le write au WAL pour rejeu ultérieur.

        Uniquement si la DB a déjà fonctionné cette session (vraie panne).
        En mode secours permanent, le secours est le store de référence → pas de WAL.
        """
        if not getattr(self, "_ever_up", False):
            return
        try:
            with open(WAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"op": op, "args": args, "ts": time.time()},
                                   ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[forge_db] WAL append échoué: {e}")

    def wal_pending(self) -> int:
        if not WAL_PATH.exists():
            return 0
        try:
            return sum(1 for _ in open(WAL_PATH, encoding="utf-8"))
        except Exception:
            return 0

    def wal_replay(self) -> int:
        """Rejoue le journal WAL dans la DB primaire, puis le tronque. Idempotent."""
        if not WAL_PATH.exists():
            return 0
        # Re-probe systématique : le WAL contient des writes PG ; il faut vérifier
        # que PG lui-même est revenu (db_up=True dès que Redis seul est up ne suffit pas).
        self._probe_backends()
        if not self.pg_ok and not self.redis_ok:
            logger.info("[forge_db] wal_replay: DB toujours down, abandon")
            return 0

        replayed = 0
        lines = WAL_PATH.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                op, args = rec["op"], rec["args"]
                if op == "hot_set":
                    self.hot_set(args["key"], args["value"], args.get("ttl"))
                elif op == "deep_insert":
                    self.deep_insert(args["table"], args["row"])
                replayed += 1
            except Exception as e:
                logger.warning(f"[forge_db] wal_replay ligne ignorée: {e}")
        # Troncature après rejeu réussi
        try:
            WAL_PATH.write_text("", encoding="utf-8")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        logger.info(f"[forge_db] WAL rejoué: {replayed} writes")
        return replayed

    # ── HEALTH ────────────────────────────────────────────────────────────────

    def sync_gitnexus(self) -> int:
        """Sync .gitnexus/ symbol index → gitnexus_symbols (PG) + Redis meta. Idempotent."""
        import json as _json
        meta_path = FORGE_ROOT / ".gitnexus" / "meta.json"
        index_path = FORGE_ROOT / ".gitnexus" / "parse-cache" / "index.json"
        if not meta_path.exists():
            return 0
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            self.hot_set("gitnexus:meta", _json.dumps({
                "nodes": meta.get("nodeCount", 0),
                "edges": meta.get("edgeCount", 0),
                "clusters": meta.get("clusterCount", 0),
                "flows": meta.get("flowCount", 0),
            }), ttl=3600)
            count = 0
            if index_path.exists():
                idx = _json.loads(index_path.read_text(encoding="utf-8"))
                entries = idx.items() if isinstance(idx, dict) else enumerate(idx)
                for sym_id, entry in entries:
                    self.deep_insert("gitnexus_symbols", {
                        "id": str(sym_id),
                        "name": entry.get("name", str(sym_id)) if isinstance(entry, dict) else str(entry),
                        "kind": entry.get("kind", "symbol") if isinstance(entry, dict) else "symbol",
                        "payload": entry if isinstance(entry, dict) else {"v": entry},
                    })
                    count += 1
            logger.info(f"[forge_db] gitnexus_sync: {count} symbols → PG+Redis")
            return count
        except Exception as e:
            logger.warning(f"[forge_db] sync_gitnexus: {e}")
            return 0

    def health(self) -> dict:
        return {
            "redis": "up" if self.redis_ok else "down",
            "postgres": "up" if self.pg_ok else "down",
            "fallback": "active" if not self.db_up else "standby",
            "wal_pending": self.wal_pending(),
        }


# ─── NullFallback (si même le secours échoue) ─────────────────────────────────

class _NullFallback:
    def hot_get(self, key): return None
    def hot_set(self, key, value, ttl=None): pass
    def hot_incr(self, key, amount=1): return amount
    def deep_insert(self, table, row): pass
    def deep_query(self, table, filt=None, limit=50): return []
    def deep_semantic(self, table, text, k=5): return []
    def apply(self, op, args): pass


# ─── Singleton ────────────────────────────────────────────────────────────────

_db: Optional[ForgeDB] = None


def get_db() -> ForgeDB:
    global _db
    if _db is None:
        _db = ForgeDB()
    return _db


def sync_gitnexus() -> int:
    """Module-level: sync .gitnexus/ index into forge memory layers. Idempotent."""
    return get_db().sync_gitnexus()



# ─── File locks (MVP ticket 8) — lock:<filepath> en Redis, TTL 300s ──────────

def acquire_file_lock(filepath: str, agent_id: str, ttl: int = 300) -> bool:
    """Pose lock:<filepath> si libre (ou déjà détenu par le même agent).
    À appeler AVANT tout Write/Edit d'un agent. Retourne False si un autre
    agent détient le lock. Pas de rollback auto (Snapshot Engine V2)."""
    db = get_db()
    key = f"lock:{filepath}"
    holder = db.hot_get(key)
    if holder and holder != agent_id:
        return False
    db.hot_set(key, agent_id, ttl=ttl)
    return True


def release_file_lock(filepath: str, agent_id: str) -> None:
    """Libère le lock si détenu par agent_id."""
    db = get_db()
    key = f"lock:{filepath}"
    if db.hot_get(key) == agent_id:
        try:
            r = getattr(db, "_redis", None)
            if r is not None:
                r.delete(key)
            else:
                db.hot_set(key, "", ttl=1)
        except Exception:
            db.hot_set(key, "", ttl=1)

# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    db = get_db()
    if len(sys.argv) > 1 and sys.argv[1] == "--replay":
        n = db.wal_replay()
        print(f"WAL replayed: {n}")
    h = db.health()
    print(f"redis={h['redis']} postgres={h['postgres']} "
          f"fallback={h['fallback']} wal_pending={h['wal_pending']}")
