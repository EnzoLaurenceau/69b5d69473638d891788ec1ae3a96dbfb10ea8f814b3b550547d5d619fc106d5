#!/usr/bin/env python3
"""
migrate_to_pg.py — Migration one-shot des stores éclatés → PG+Redis (optiforge)
===============================================================================
Aspire les 5 stores legacy dans le store unifié forge_db :

  04_GRAPHIFY/forge_checkpoints.db  (LangGraph SQLite)  → langgraph_checkpoints
  04_GRAPHIFY/graph.json            (Graphify)          → graphify_nodes
  05_STATE/checkpoint.json          (master state)      → findings + hot kv
  .nexus/*.json                     (caches)            → episodes / hot kv
  index gitnexus (.gitnexus / *.db) (code intel)        → gitnexus_symbols

Idempotent (upsert par clé). À la fin, archive les fichiers legacy dans
09_ARCHIVE/<date>/ (les moteurs restent en place pour servir de secours).

Usage :
  python scripts/migrate_to_pg.py            # migre + archive
  python scripts/migrate_to_pg.py --dry-run  # compte sans écrire
  python scripts/migrate_to_pg.py --purge-legacy   # supprime au lieu d'archiver
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

FORGE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(FORGE_ROOT))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

from forge_agents.forge_db import get_db  # noqa: E402

GRAPHIFY_DIR = FORGE_ROOT / "04_GRAPHIFY"
STATE_DIR = FORGE_ROOT / "05_STATE"
NEXUS_DIR = FORGE_ROOT / ".nexus"
ARCHIVE_DIR = FORGE_ROOT / "09_ARCHIVE" / date.today().isoformat()


def _count(d: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in d.items())


def migrate_langgraph(db, dry: bool) -> int:
    """SQLite LangGraph checkpoints → table langgraph_checkpoints."""
    src = GRAPHIFY_DIR / "forge_checkpoints.db"
    if not src.exists():
        return 0
    n = 0
    try:
        conn = sqlite3.connect(str(src))
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "checkpoints" not in tables:
            return 0
        for r in conn.execute("SELECT * FROM checkpoints"):
            d = dict(r)
            thread = str(d.get("thread_id", f"legacy-{n}"))
            if not dry:
                db.cp_put(thread, {k: str(v) for k, v in d.items()})
            n += 1
        conn.close()
    except Exception as e:
        print(f"  ! langgraph: {e}")
    return n


def migrate_graphify(db, dry: bool) -> int:
    """graph.json → table graphify_nodes."""
    src = GRAPHIFY_DIR / "graph.json"
    if not src.exists():
        return 0
    n = 0
    try:
        graph = json.loads(src.read_text(encoding="utf-8"))
        for node in graph.get("nodes", []):
            nid = str(node.get("id") or f"node-{n}")
            if not dry:
                db.deep_insert("graphify_nodes", {
                    "id": nid,
                    "agent": node.get("agent", "ORCH"),
                    "cycle": int(node.get("cycle", 0) or 0),
                    "content": str(node.get("content", ""))[:2000],
                    "ts": time.time(),
                })
            n += 1
    except Exception as e:
        print(f"  ! graphify: {e}")
    return n


def migrate_master_state(db, dry: bool) -> int:
    """checkpoint.json → findings + hot kv (état session)."""
    src = STATE_DIR / "checkpoint.json"
    if not src.exists():
        return 0
    n = 0
    try:
        cp = json.loads(src.read_text(encoding="utf-8"))
        for f in cp.get("findings", []):
            fid = str(f.get("id") or f"F-LEGACY-{n}")
            if not dry:
                db.deep_insert("findings", {
                    "id": fid,
                    "agent": f.get("agent", "?"),
                    "cycle": int(f.get("cycle", 0) or 0),
                    "content": str(f.get("content", ""))[:2000],
                    "score": float(f.get("score", 0) or 0),
                    "status": f.get("status", "pending"),
                    "ts": time.time(),
                })
            n += 1
        if not dry:
            db.hot_set("forge:last_state", json.dumps({
                "level": cp.get("level", "L1"),
                "cycle": cp.get("cycle", 0),
                "session_id": cp.get("session_id", ""),
                "last_task": cp.get("last_task", ""),
            }, ensure_ascii=False))
    except Exception as e:
        print(f"  ! master_state: {e}")
    return n


def migrate_nexus(db, dry: bool) -> int:
    """.nexus/*.json → episodes (logs cervelet/agent) + hot kv (caches)."""
    if not NEXUS_DIR.exists():
        return 0
    n = 0
    for jf in NEXUS_DIR.glob("*.json"):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        logs = data.get("logs", []) if isinstance(data, dict) else []
        for log in logs:
            if not dry:
                db.deep_insert("episodes", {
                    "signal": str(log.get("signal", jf.stem)),
                    "res": str(log.get("res", ""))[:1000],
                    "meta": log if isinstance(log, dict) else {},
                    "salience": 0.0,
                    "ts": float(log.get("ts", time.time())),
                })
            n += 1
        if not dry and isinstance(data, dict):
            db.hot_set(f"nexus:{jf.stem}", json.dumps(data, ensure_ascii=False)[:50000])
    return n


def migrate_gitnexus(db, dry: bool) -> int:
    """Index gitnexus (.gitnexus/*.db ou *.json) → gitnexus_symbols (best-effort)."""
    candidates = list((FORGE_ROOT / ".gitnexus").glob("*.db")) if (FORGE_ROOT / ".gitnexus").exists() else []
    n = 0
    for db_file in candidates:
        try:
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            sym_table = next((t for t in tables if "symbol" in t.lower()), None)
            if sym_table:
                for r in conn.execute(f"SELECT * FROM {sym_table} LIMIT 100000"):
                    d = dict(r)
                    sid = str(d.get("id") or d.get("name") or f"sym-{n}")
                    if not dry:
                        db.deep_insert("gitnexus_symbols", {
                            "id": sid,
                            "name": str(d.get("name", "")),
                            "kind": str(d.get("kind", d.get("type", ""))),
                            "payload": d,
                        })
                    n += 1
            conn.close()
        except Exception as e:
            print(f"  ! gitnexus {db_file.name}: {e}")
    return n


def archive_legacy(purge: bool) -> list[str]:
    """Archive (ou supprime) les fichiers legacy. Les moteurs restent en place."""
    targets = [
        GRAPHIFY_DIR / "graph.json",
        STATE_DIR / "checkpoint.json",
    ]
    targets += list(NEXUS_DIR.glob("*.json")) if NEXUS_DIR.exists() else []
    done = []
    if not purge:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for t in targets:
        if not t.exists():
            continue
        try:
            if purge:
                t.unlink()
                done.append(f"purged {t.name}")
            else:
                shutil.copy2(t, ARCHIVE_DIR / t.name)
                done.append(f"archived {t.name}")
        except Exception as e:
            done.append(f"skip {t.name} ({e})")
    return done


def run_migration(dry: bool = False, purge: bool = False) -> dict:
    db = get_db()
    h = db.health()
    print(f"[migrate] DB health: redis={h['redis']} postgres={h['postgres']} "
          f"fallback={h['fallback']}")
    if not db.db_up and not dry:
        print("[migrate] ⚠ DB primaire down — la migration écrira dans le SECOURS "
              "(SQLite) puis sera rejouée via WAL au retour de la DB.")

    counts = {
        "langgraph_checkpoints": migrate_langgraph(db, dry),
        "graphify_nodes": migrate_graphify(db, dry),
        "findings": migrate_master_state(db, dry),
        "episodes": migrate_nexus(db, dry),
        "gitnexus_symbols": migrate_gitnexus(db, dry),
    }
    print(f"[migrate] {'(dry-run) ' if dry else ''}migré: {_count(counts)}")

    if not dry:
        actions = archive_legacy(purge)
        for a in actions:
            print(f"[migrate] {a}")
    return counts


def main():
    ap = argparse.ArgumentParser(description="Migration legacy → PG+Redis (optiforge)")
    ap.add_argument("--dry-run", action="store_true", help="Compter sans écrire")
    ap.add_argument("--purge-legacy", action="store_true",
                    help="Supprimer les fichiers legacy au lieu de les archiver")
    args = ap.parse_args()
    run_migration(dry=args.dry_run, purge=args.purge_legacy)


if __name__ == "__main__":
    main()
