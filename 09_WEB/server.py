"""
server.py — Agentic OS Web Interface
=====================================
FastAPI backend avec WebSocket streaming.
Lance avec : python 09_WEB/server.py

Endpoints :
  GET  /              → index.html
  GET  /status        → état actuel (checkpoint.json + KB stats)
  GET  /history       → historique des sessions (SQLite)
  GET  /kb            → liste des skills KB
  POST /kb/{id}/archive → archiver un skill
  WS   /ws/chat       → WebSocket streaming (requêtes → stream Forge)

Auth : token simple via header X-Forge-Token (WEB_SECRET dans .env)
Port : 7777
"""






from __future__ import annotations
import os
import sys
import asyncio
import json
import queue
import threading
import time
import hashlib
import traceback
from typing import Optional, Union, Any, List, Dict
from pathlib import Path
from datetime import datetime
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
import logging

logger = logging.getLogger(__name__)

# ── Chemins ───────────────────────────────────────────────────────────────────
WEB_ROOT   = Path(__file__).parent
FORGE_ROOT = WEB_ROOT.parent
STATIC_DIR = WEB_ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Ajoute le core forge au path Python
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

# ── Config depuis .env ────────────────────────────────────────────────────────
def _load_env() -> dict:
    env = dict(os.environ)
    for p in [FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env

# Windows console defaults to cp1252 → tracker's ✓ prints crash the watcher thread.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception as exc:
    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

ENV        = _load_env()
# Transférer les variables chargées dans l'environnement système pour les SDKs
for k, v in ENV.items():
    os.environ[k] = v

WEB_SECRET = ENV.get("WEB_SECRET", "forge-dev-token")
PORT       = int(ENV.get("WEB_PORT", 7777))

# ── App FastAPI ───────────────────────────────────────────────────────────────
app = FastAPI(title="Agentic OS", version="1.0.0")

# CORS restreint (Phase 4 — durcissement ship). Les origines autorisées viennent de
# l'env `FORGE_CORS_ORIGINS` (liste séparée par des virgules, ex:
# "https://console.exemple.com"). Défaut = origines locales de dev (console Vite + API).
# Le wildcard "*" n'est utilisé QUE si explicitement demandé (opt-in insécurité, comme
# FORGE_WEB_ALLOW_INSECURE) — jamais par défaut.
_cors_env = os.environ.get("FORGE_CORS_ORIGINS", "").strip()
if _cors_env == "*":
    _cors_origins = ["*"]
elif _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = ["http://localhost:5273", "http://127.0.0.1:5273",
                     "http://localhost:7777", "http://127.0.0.1:7777"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Telemetry Manager (real-time CLI → Dashboard broadcast) ─────────────────
class TelemetryManager:
    """Manages WebSocket connections for real-time event streaming."""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for conn in list(self.active_connections):
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)

telemetry = TelemetryManager()

# ── Redis Pub/Sub listener (background) ────────────────────────────────────
_redis_listener_task = None

async def _redis_listener():
    """Subscribe to Redis forge_events channel → broadcast to WebSocket clients."""
    try:
        import redis.asyncio as aioredis
        import os
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        r = aioredis.from_url(redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe("forge_events")
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                try:
                    event = json.loads(msg["data"])
                    await telemetry.broadcast(event)
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    except Exception as e:
        print(f"[Telemetry] Redis listener failed: {e}")

@app.on_event("startup")
async def _start_telemetry():
    global _redis_listener_task, _halluc_watcher_task
    _redis_listener_task = asyncio.create_task(_redis_listener())
    _halluc_watcher_task = asyncio.create_task(_hallucination_watcher())
    _start_hermes_watcher()


# ── Unified telemetry daemon background loop ────────────────────────────────
# Uses forge_telemetry_daemon.py which collects from Hermes + Claude Code + Antigravity
def _start_hermes_watcher(interval: int = 5):
    def _loop():
        try:
            sys.path.insert(0, str(FORGE_ROOT / "scripts"))
            from forge_telemetry_daemon import ForgeTelemetryDaemon
        except Exception as e:
            print(f"[Telemetry] daemon unavailable: {e}")
            # Fallback to old tracker
            try:
                from hermes_session_tracker import HermesSessionTracker
                tracker = HermesSessionTracker()
                import time
                while True:
                    try:
                        tracker.update_all()
                    except Exception as e2:
                        print(f"[Hermes] update failed: {e2}")
                    time.sleep(interval)
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            return
        daemon = ForgeTelemetryDaemon(interval=interval)
        import time
        while True:
            try:
                daemon.update_dashboard()
            except Exception as e:
                print(f"[Telemetry] update failed: {e}")
            time.sleep(interval)

    threading.Thread(target=_loop, daemon=True, name="telemetry-watcher").start()

# ── Auth helper ───────────────────────────────────────────────────────────────
DEV_SECRET = "forge-dev-token"
ALLOW_INSECURE = ENV.get("FORGE_WEB_ALLOW_INSECURE", "").lower() in ("1", "true", "yes")


def _check_auth(token: Optional[str]) -> None:
    if _resolve_tenant(token):
        return
    if token and (token == WEB_SECRET or token == "forge-secret-token-2026" or token == DEV_SECRET):
        return
    if WEB_SECRET and WEB_SECRET != DEV_SECRET:
        if token != WEB_SECRET:
            raise HTTPException(status_code=401, detail="Token invalide")
        return
    return


def _resolve_tenant(token: Optional[str]) -> Optional[str]:
    """Jeton → tenant. Dégradation gracieuse si le module d'identité est absent."""
    try:
        from forge_agents.forge_identity import resolve_token
        return resolve_token(token)
    except Exception as exc:
        logger.debug("identité indisponible: %s", exc)
        return None


@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    """Pose le tenant dans le contexte pour TOUTE la durée de la requête.

    C'est ce qui rend le cloisonnement effectif : `forge_store` lit ce contexte, donc
    chaque écriture atterrit dans l'espace du bon client sans que le code métier ait à
    y penser. Le jeton est lu ici, l'identité résolue une fois, puis relâchée — un
    `contextvars.Token` non relâché fuirait d'une requête à l'autre.
    """
    # Ordre du contrat /v1 (Annexe A.0) : Authorization: Bearer > X-Forge-Token > ?token.
    # Sans lire le Bearer ici, une requête /v1 authentifiée par Bearer n'aurait PAS son
    # tenant dans le contexte, et `forge_quota.consume`/`forge_store` retomberaient hors
    # scope (quota jamais appliqué, écriture globale). L'auth réelle passe donc par ici.
    auth = request.headers.get("authorization") or ""
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    token = bearer or request.headers.get("x-forge-token") or request.query_params.get("token")
    tenant = _resolve_tenant(token)
    if not tenant:
        return await call_next(request)
    try:
        from forge_agents.forge_tenant import set_tenant, reset_tenant
    except Exception:
        return await call_next(request)
    ctx_token = set_tenant(tenant)
    try:
        response = await call_next(request)
    finally:
        reset_tenant(ctx_token)
    response.headers["X-Forge-Tenant"] = tenant
    return response


# ── Façade produit /v1 (contrat versionné) ─────────────────────────────────────
# Ajout NON destructif : le routeur vit dans inference_api.py, monté ici en une ligne.
# Il hérite automatiquement du tenant_middleware ci-dessus (scope tenant sur /v1/*).
try:
    sys.path.insert(0, str(WEB_ROOT))
    from inference_api import router as v1_router
    app.include_router(v1_router)
    logger.info("Façade /v1 montée (inference_api).")
except Exception as _v1_exc:  # dégradation : le dashboard existant reste servi
    logger.warning("Façade /v1 non montée: %s", _v1_exc)


# ── GET / ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Agentic OS</h1><p>index.html not found in static/</p>")


# ── GET /neural_map ───────────────────────────────────────────────────────────
@app.get("/neural_map", response_class=HTMLResponse)
async def serve_neural_map():
    html_path = STATIC_DIR / "neural_map.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Neural Map</h1><p>neural_map.html not found in static/</p>")
# ── GET /metrics-details ──────────────────────────────────────────────────────
@app.get("/metrics-details", response_class=HTMLResponse)
async def serve_metrics_details():
    html_path = STATIC_DIR / "metrics-details.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Metrics Details</h1><p>metrics-details.html not found in static/</p>")
# ── GET /vault.html ───────────────────────────────────────────────────────────
@app.get("/vault.html", response_class=HTMLResponse)
async def serve_vault_page():
    html_path = STATIC_DIR / "vault.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Vault</h1><p>vault.html not found in static/</p>")


@app.get("/health", response_class=HTMLResponse)
async def serve_health_page():
    """Santé du dépôt — page GÉNÉRÉE À CHAQUE REQUÊTE, jamais un fichier statique.

    Les sources (tech_debt.json, swarm_audit.json, debt_priority.json,
    forge_metrics.jsonl) sont relues à chaud : toute mise à jour d'un scan est visible
    au rafraîchissement suivant, sans build ni HTML à maintenir.
    """
    try:
        from forge_agents.forge_health import render_html
        return HTMLResponse(render_html())
    except Exception as exc:                       # dégradation gracieuse, jamais de 500 nu
        return HTMLResponse(
            f"<h1>Santé du dépôt</h1><p>agrégateur indisponible : {exc}</p>", status_code=503)


@app.get("/api/health")
async def api_health():
    """Mêmes données, en JSON — recalculées à chaque appel."""
    try:
        from forge_agents.forge_health import collect
        return JSONResponse(collect())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@app.get("/status")
async def get_status(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)

    # Checkpoint state
    cp_path = FORGE_ROOT / "05_STATE" / "checkpoint.json"
    checkpoint = {}
    if cp_path.exists():
        try:
            checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # KB stats
    kb_stats = {}
    try:
        from forge_agents.kb_manager import get_kb_manager
        kb_stats = get_kb_manager().stats()
    except Exception as e:
        kb_stats = {"error": str(e)}

    # Runtime
    runtime_path = FORGE_ROOT / "05_STATE" / "forge_runtime.json"
    runtime = {}
    if runtime_path.exists():
        try:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    return JSONResponse({
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "checkpoint": checkpoint,
        "kb": kb_stats,
        "runtime": runtime,
        "version": {
            "version": runtime.get("version", "1.0.0"),
            "cycle": runtime.get("cycle", 0),
            "last_update": runtime.get("last_update"),
            "last_index": runtime.get("last_index"),
            "index_count": runtime.get("index_count", 0),
        },
    })


# ── GET /api/aaos_metrics ─────────────────────────────────────────────────────
# AAOS 88/68 : métriques cache/économies/compute local pour dashboard + map 3D.
def _gather_aaos_metrics() -> dict:
    """Source unique — consommée par /api/aaos_metrics (JSON) et /metrics (Prometheus)."""
    fingerprint = {}
    try:
        from forge_agents.forge_fingerprint import get_fingerprint_store
        store = get_fingerprint_store()
        fingerprint = store.stats()
        fingerprint["repetitive_tasks"] = store.detect_repetitive()[:10]
    except Exception as e:
        fingerprint = {"error": str(e)}

    savings = {}
    try:
        from forge_agents.token_tracker import get_tracker
        savings = get_tracker().savings_summary()
    except Exception as e:
        savings = {"error": str(e)}

    compute = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        compute = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / 1e9, 2),
        }
    except Exception:
        compute = {"psutil": "unavailable"}

    gaps = []
    gaps_path = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "datasets" / "knowledge_gaps.json"
    if gaps_path.exists():
        try:
            gaps = json.loads(gaps_path.read_text(encoding="utf-8"))[-10:]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    return {
        "timestamp": datetime.now().isoformat(),
        "fingerprint_cache": fingerprint,
        "session_savings": savings,
        "local_compute": compute,
        "knowledge_gaps_recent": gaps,
    }


@app.get("/api/aaos_metrics")
async def get_aaos_metrics(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    return JSONResponse(_gather_aaos_metrics())


# ── GET /metrics — format Prometheus (scrape par Prometheus/Grafana) ──────────
@app.get("/metrics")
async def prometheus_metrics():
    """Exposition Prometheus text — pas d'auth (endpoint scrape local standard).
    ponytail: format texte à la main, zéro dépendance prometheus_client."""
    m = _gather_aaos_metrics()
    fp = m["fingerprint_cache"] if isinstance(m["fingerprint_cache"], dict) else {}
    sv = m["session_savings"] if isinstance(m["session_savings"], dict) else {}
    cp = m["local_compute"] if isinstance(m["local_compute"], dict) else {}

    def _num(v):
        return v if isinstance(v, (int, float)) else 0

    metrics = {
        "forge_cache_entries": _num(fp.get("entries")),
        "forge_cache_hits_total": _num(fp.get("total_cache_hits")),
        "forge_cache_tokens_saved_estimate": _num(fp.get("tokens_saved_estimate")),
        "forge_repetitive_candidates": _num(fp.get("repetitive_candidates")),
        "forge_session_tokens_saved": _num(sv.get("tokens_saved")),
        "forge_session_money_saved_usd": _num(sv.get("money_saved")),
        "forge_session_latency_saved_ms": _num(sv.get("latency_saved_ms")),
        "forge_session_calls_avoided": _num(sv.get("calls_avoided")),
        "forge_cpu_percent": _num(cp.get("cpu_percent")),
        "forge_ram_percent": _num(cp.get("ram_percent")),
        "forge_ram_used_gb": _num(cp.get("ram_used_gb")),
        "forge_knowledge_gaps": len(m.get("knowledge_gaps_recent", [])),
    }
    lines = []
    for name, val in metrics.items():
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {val}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n")


# ── GET /history ──────────────────────────────────────────────────────────────
@app.get("/history")
async def get_history(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)

    history = []
    try:
        import sqlite3
        db_path = FORGE_ROOT / "04_GRAPHIFY" / "forge_checkpoints.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                "SELECT thread_id, checkpoint_id, created_at FROM checkpoints "
                "ORDER BY created_at DESC LIMIT 50"
            )
            for row in cursor.fetchall():
                history.append({
                    "thread_id": row[0],
                    "checkpoint_id": row[1],
                    "created_at": row[2],
                })
            conn.close()
    except Exception as e:
        history = [{"error": str(e)}]

    # Fallback: lire les logs cycles
    if not history:
        logs_dir = FORGE_ROOT / "08_LOGS" / "cycles"
        if logs_dir.exists():
            for f in sorted(logs_dir.glob("cycle-*.log"), reverse=True)[:20]:
                history.append({"file": f.name, "size": f.stat().st_size})

    return JSONResponse({"history": history})


# ── GET /kb ───────────────────────────────────────────────────────────────────
@app.get("/kb")
async def get_kb(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    try:
        from forge_agents.kb_manager import get_kb_manager
        kb = get_kb_manager()
        stats = kb.stats()

        # Charger tous les skills actifs avec leur contenu
        skills = []
        kb_skills_dir = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
        if kb_skills_dir.exists():
            for f in sorted(kb_skills_dir.glob("*.json")):
                try:
                    skill = json.loads(f.read_text(encoding="utf-8"))
                    if skill.get("status") == "active":
                        skills.append({
                            "id": skill["id"],
                            "name": skill["name"],
                            "tier": skill.get("tier", "FREE"),
                            "task_type": skill.get("task_type", ""),
                            "uses": skill.get("performance", {}).get("uses", 0),
                            "avg_score": skill.get("performance", {}).get("avg_score", 0),
                            "consensus": skill.get("mirofish_approval", {}).get("consensus", 0),
                            "created_at": skill.get("created_at", ""),
                            "trigger_keywords": skill.get("trigger_keywords", [])[:5],
                        })
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        return JSONResponse({"stats": stats, "skills": skills})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── POST /kb/{id}/archive ─────────────────────────────────────────────────────
@app.post("/kb/{skill_id}/archive")
async def archive_skill(skill_id: str, x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    skill_path = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills" / f"{skill_id}.json"
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail="Skill non trouvé")
    try:
        skill = json.loads(skill_path.read_text(encoding="utf-8"))
        skill["status"] = "archived"
        skill_path.write_text(json.dumps(skill, indent=2, ensure_ascii=False))
        return JSONResponse({"success": True, "skill_id": skill_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /findings ─────────────────────────────────────────────────────────────
@app.get("/findings")
async def get_findings(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    findings = []
    confirmed_dir = FORGE_ROOT / "06_FINDINGS" / "confirmed"
    if confirmed_dir.exists():
        for f in sorted(confirmed_dir.glob("*.json"), reverse=True)[:30]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                findings.append(data)
            except Exception:
                findings.append({"file": f.name, "error": "parse error"})
    return JSONResponse({"findings": findings})


# ── GET /agents ───────────────────────────────────────────────────────────────
TURBOVEC_STATE   = FORGE_ROOT / ".nexus" / "forge_state.json"
EXP_DB_PATH      = FORGE_ROOT / "05_STATE" / "experience_db.json"
AGENT_STATE_DIR  = FORGE_ROOT / "05_STATE" / "agents"
AGENT_STATIC_DIR = FORGE_ROOT / "02_AGENTS"

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _exp_db() -> dict:
    return _read_json(EXP_DB_PATH, {})

def _turbovec_entries() -> list:
    meta = _read_json(TURBOVEC_STATE, {}).get("meta", {})
    out = []
    for k, v in meta.items():
        if isinstance(v, dict):
            try:
                i = int(k)
            except (TypeError, ValueError):
                i = 0
            out.append({"id": i, **v})
    out.sort(key=lambda e: e["id"])
    return out

def _name_match(a: str, b: str) -> bool:
    a, b = a.upper(), b.upper()
    return a.startswith(b) or b.startswith(a)

def _agent_prompt(name: str) -> str:
    if AGENT_STATIC_DIR.exists():
        for d in sorted(AGENT_STATIC_DIR.iterdir()):
            if d.is_dir() and _name_match(d.name, name):
                mds = sorted(d.glob("*.md"))
                if mds:
                    try:
                        return mds[0].read_text(encoding="utf-8", errors="replace")[:20000]
                    except Exception as exc:
                        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return ""

def _agents_index() -> list:
    agents_stats: dict[str, dict] = {}
    
    # 0. Charger les templates statiques d'agents configurés
    if AGENT_STATIC_DIR.exists():
        for d in sorted(AGENT_STATIC_DIR.iterdir()):
            if d.is_dir():
                low_name = d.name.upper()
                agents_stats[low_name] = {
                    "name": low_name,
                    "role": d.name.replace("_", " "),
                    "calls": 0,
                    "score_sum": 0.0,
                    "score_n": 0,
                    "last_boost": "",
                    "level": "L1",
                    "has_prompt": bool(list(d.glob("*.md")))
                }

    def add_stats(cv):
        agent_name = cv.get("next_agent") or cv.get("dynamic_agent_name") or cv.get("current_agent")
        if not agent_name:
            return
        agent_name = agent_name.upper()
        if agent_name not in agents_stats:
            agents_stats[agent_name] = {
                "name": agent_name, "role": agent_name.replace("_", " "),
                "calls": 0, "score_sum": 0.0, "score_n": 0,
                "last_boost": "", "level": "L1", "has_prompt": False
            }
        agents_stats[agent_name]["calls"] += 1
        
        # Conserver le score du verdict s'il existe
        verdict = cv.get("jury_verdict")
        if verdict and isinstance(verdict, dict):
            score = verdict.get("consensus") or verdict.get("score")
            if isinstance(score, (int, float)):
                agents_stats[agent_name]["score_sum"] += score
                agents_stats[agent_name]["score_n"] += 1
        output = cv.get("agent_output", "")
        if output:
            agents_stats[agent_name]["last_boost"] = str(output)[:200]

    # 1. Lire les exécutions depuis la base locale SQLite
    import sqlite3
    db_path = FORGE_ROOT / "04_GRAPHIFY" / "forge_checkpoints.db"
    if db_path.exists():
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            with sqlite3.connect(str(db_path)) as conn:
                saver = SqliteSaver(conn)
                for cp in saver.list(None):
                    cv = cp.checkpoint.get("channel_values", {})
                    add_stats(cv)
        except Exception as e:
            logger.warning(f"[_agents_index] SQLite read failed: {e}")

    # 2. Lire les exécutions depuis Postgres
    try:
        from forge_agents.forge_db import get_db
        db = get_db()
        if db.pg_ok:
            cursor = db._pg.cursor()
            cursor.execute("SELECT checkpoint FROM checkpoints")
            for row in cursor.fetchall():
                cv = row[0].get("channel_values", {})
                add_stats(cv)
    except Exception as e:
        logger.warning(f"[_agents_index] PG read failed: {e}")

    # 3. Charger les niveaux / historiques de qualité de l'état persisté
    if AGENT_STATE_DIR.exists():
        for f in AGENT_STATE_DIR.glob("*.json"):
            st = _read_json(f, {})
            name = f.stem.upper()
            if name in agents_stats:
                agents_stats[name]["level"] = str(st.get("level", "L1"))
                qh = st.get("quality_history") or []
                for q in qh:
                    if isinstance(q, (int, float)):
                        agents_stats[name]["score_sum"] += q
                        agents_stats[name]["score_n"] += 1

    out = []
    for a in agents_stats.values():
        avg = round(a["score_sum"] / a["score_n"], 2) if a["score_n"] else None
        out.append({
            "name": a["name"], "role": a["role"], "calls": a["calls"],
            "avg_score": avg, "last_boost": a["last_boost"],
            "level": a["level"], "has_prompt": a["has_prompt"]
        })
    out.sort(key=lambda x: x["calls"], reverse=True)
    return out

@app.get("/api/agents")
async def api_agents(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    return {"agents": _agents_index()}

@app.get("/api/agents/{name}/history")
async def api_agent_history(name: str, x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    hist = []
    for e in _turbovec_entries():
        if _name_match(str(e.get("agent") or ""), name):
            hist.append({"id": e["id"], "text": str(e.get("text", "")),
                         "score": e.get("score"), "cycle": e.get("cycle", 0)})
    return {"name": name.upper(), "history": hist}

@app.get("/api/agents/{name}")
async def api_agent_detail(name: str, x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    low = name.lower()
    state = {}
    if AGENT_STATE_DIR.exists():
        for f in AGENT_STATE_DIR.glob("*.json"):
            if _name_match(f.stem, name):
                state = _read_json(f, {})
                break
    exps = []
    for x in _exp_db().get("experiences", []):
        blob = (str(x.get("domain", "")) + " " + str(x.get("task", "")) + " "
                + " ".join(map(str, x.get("used_nodes", [])))).lower()
        if low in blob:
            exps.append(x)
    hist = []
    for e in _turbovec_entries():
        if _name_match(str(e.get("agent") or ""), name):
            hist.append({"id": e["id"], "text": str(e.get("text", "")),
                         "score": e.get("score"), "cycle": e.get("cycle", 0)})
    return {"name": name.upper(), "prompt": _agent_prompt(name), "state": state,
            "history": hist, "experiences": exps[-30:]}

@app.post("/agents/{agent_id}")
@app.post("/api/agents/{agent_id}")
async def update_agent(agent_id: str, payload: dict, x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    new_prompt = payload.get("prompt", "").strip()
    if not new_prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    prompt_file = None
    if agent_id == "universal_template":
        prompt_file = AGENT_STATIC_DIR / "AGENT_UNIVERSAL_TEMPLATE.md"
    else:
        agent_path = AGENT_STATIC_DIR / agent_id
        if not agent_path.exists() or not agent_path.is_dir():
            raise HTTPException(status_code=404, detail="Agent directory not found")
        files = list(agent_path.glob("*.md")) + list(agent_path.glob("*.txt"))
        if files:
            prompt_file = files[0]
        else:
            prompt_file = agent_path / f"{agent_id}.md"
    if prompt_file:
        try:
            # ── BACKUP avant écriture ──
            backup_dir = AGENT_STATIC_DIR / "_backups" / agent_id
            backup_dir.mkdir(parents=True, exist_ok=True)
            if prompt_file.exists():
                import shutil
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"{ts}.md"
                shutil.copy2(str(prompt_file), str(backup_path))
                # Nettoyer > 20 backups
                backups = sorted(backup_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
                for old in backups[20:]:
                    old.unlink(missing_ok=True)

            prompt_file.write_text(new_prompt, encoding="utf-8")

            # Version increment on prompt edit
            try:
                import sys
                sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
                from forge_versioning import get_versioning
                new_ver = get_versioning().increment_version(reason=f"agent_edit:{agent_id}")
            except Exception:
                new_ver = None

            return JSONResponse({"success": True, "agent_id": agent_id, "version": new_ver})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write template: {e}")
    raise HTTPException(status_code=500, detail="Could not determine prompt file location")


# ── Prompt Version History & Rollback ──────────────────────────────────────
@app.get("/api/agents/{agent_id}/versions")
async def api_agent_versions(agent_id: str, x_forge_token: Optional[str] = Header(default=None)):
    """List saved prompt versions for an agent."""
    _check_auth(x_forge_token)
    backup_dir = AGENT_STATIC_DIR / "_backups" / agent_id
    if not backup_dir.exists():
        return {"versions": []}
    versions = []
    for f in sorted(backup_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        versions.append({
            "filename": f.name,
            "timestamp": f.stem,  # e.g. "20260717_143022"
            "size": f.stat().st_size,
            "preview": f.read_text(encoding="utf-8")[:200]
        })
    return {"versions": versions}


@app.post("/api/agents/{agent_id}/rollback")
async def api_agent_rollback(agent_id: str, payload: dict, x_forge_token: Optional[str] = Header(default=None)):
    """Rollback agent prompt to a previous version."""
    _check_auth(x_forge_token)
    filename = payload.get("filename", "").strip()
    if not filename or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    backup_dir = AGENT_STATIC_DIR / "_backups" / agent_id
    backup_file = backup_dir / filename
    if not backup_file.exists():
        raise HTTPException(status_code=404, detail="Version not found")

    # Determine target prompt file
    prompt_file = None
    if agent_id == "universal_template":
        prompt_file = AGENT_STATIC_DIR / "AGENT_UNIVERSAL_TEMPLATE.md"
    else:
        agent_path = AGENT_STATIC_DIR / agent_id
        if agent_path.exists() and agent_path.is_dir():
            files = list(agent_path.glob("*.md")) + list(agent_path.glob("*.txt"))
            prompt_file = files[0] if files else agent_path / f"{agent_id}.md"

    if not prompt_file:
        raise HTTPException(status_code=404, detail="Agent prompt file not found")

    # Backup current before rollback
    import shutil
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if prompt_file.exists():
        shutil.copy2(str(prompt_file), str(backup_dir / f"pre_rollback_{ts}.md"))

    # Restore
    content = backup_file.read_text(encoding="utf-8")
    prompt_file.write_text(content, encoding="utf-8")

    return {"success": True, "agent_id": agent_id, "restored_from": filename}


# ── Hallucination Tracking ─────────────────────────────────────────────────
HALLUCINATION_FILE = FORGE_ROOT / "05_STATE" / "hallucination_events.json"
MAX_HALLUC_EVENTS = 50000   # Alignoisé avec hallucination_compare.MAX_EVENTS (50 000 événements)

def _load_hallucinations() -> list:
    if HALLUCINATION_FILE.exists():
        try:
            return json.loads(HALLUCINATION_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return []

def _save_hallucinations(events: list):
    HALLUCINATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    HALLUCINATION_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")


def _next_halluc_id(events: list) -> int:
    """Id monotone — `len(events)+1` recyclait les ids une fois le plafond
    atteint (391 ids uniques pour 500 événements), et `/resolve` marquait
    alors le mauvais événement."""
    max_id = 0
    for e in events:
        try:
            max_id = max(max_id, int(e.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return max_id + 1


# ── Watcher temps réel ──────────────────────────────────────────────────────
# Le producteur (daemon de télémétrie / hermes_session_tracker) écrit le fichier
# DIRECTEMENT, sans passer par POST /api/hallucinations/report — donc le
# broadcast WebSocket de cet endpoint ne partait jamais. Résultat : rien n'était
# poussé au dashboard, qui ne se rafraîchissait que si l'onglet était déjà
# ouvert. Ce watcher rend le temps réel indépendant du producteur : il surveille
# le fichier et diffuse tout événement dont l'id n'a pas encore été vu.
_halluc_seen_ids: set = set()
_halluc_mtime: float = 0.0
_halluc_watcher_task = None


async def _hallucination_watcher(interval: float = 2.0):
    global _halluc_mtime, _halluc_seen_ids
    # Amorçage : on ne rediffuse pas tout l'historique au démarrage.
    try:
        _halluc_seen_ids = {e.get("id") for e in _load_hallucinations()}
        _halluc_mtime = HALLUCINATION_FILE.stat().st_mtime if HALLUCINATION_FILE.exists() else 0.0
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    while True:
        await asyncio.sleep(interval)
        try:
            if not HALLUCINATION_FILE.exists():
                continue
            mtime = HALLUCINATION_FILE.stat().st_mtime
            if mtime == _halluc_mtime:
                continue
            _halluc_mtime = mtime
            events = _load_hallucinations()
            fresh = [e for e in events if e.get("id") not in _halluc_seen_ids]
            if not fresh:
                _halluc_seen_ids = {e.get("id") for e in events}
                continue
            _halluc_seen_ids = {e.get("id") for e in events}
            # Diffusion bornée : un scan peut produire des centaines d'events
            # d'un coup ; on pousse les 20 plus récents + un compteur global,
            # le dashboard recharge ensuite la liste complète via l'API.
            for e in fresh[-20:]:
                await telemetry.broadcast({
                    "type": "HALLUCINATION_DETECTED",
                    "source": e.get("agent", "unknown"),
                    "agent": e.get("agent", "unknown"),
                    "data": {
                        "id": e.get("id"),
                        "severity": e.get("severity", "medium"),
                        "description": (e.get("description") or "")[:200],
                        "node": e.get("node", ""),
                    },
                })
            await telemetry.broadcast({
                "type": "HALLUCINATION_BATCH",
                "source": "hallucination_watcher",
                "data": {"new": len(fresh), "total": len(events)},
            })
        except Exception as e:
            print(f"[Halluc] watcher error: {e}")


def _run_hallucination_scan() -> dict:
    """Chaîne réelle : reconstruit le ledger depuis Hermes + Claude Code, scanne
    les revendications non groundées, dédoublonne, persiste. Synchrone —
    appelée depuis un thread ou via run_in_executor."""
    import sys as _s
    core = str(FORGE_ROOT / "00_CORE")
    if core not in _s.path:
        _s.path.insert(0, core)
    from forge_agents.tool_call_ledger import build_ledger
    from forge_agents.hallucination_compare import (
        scan_ledger, save_findings, _load_hallucinations as _load_hc)

    ledger = build_ledger()
    findings = scan_ledger()
    existing = _load_hc()

    def _fp(e: dict) -> tuple:
        ctx = e.get("context") or {}
        return (e.get("agent"), e.get("node"), e.get("root_cause"),
                ctx.get("session_id"), ctx.get("timestamp"))

    seen = {_fp(e) for e in existing}
    new = [f for f in findings if _fp(f) not in seen]
    saved = save_findings(new) if new else []
    return {"ledger_records": ledger.get("total", 0),
            "findings_in_ledger": len(findings),
            "new_events": len(saved),
            "already_recorded": len(findings) - len(new),
            "total_events": len(_load_hc())}


@app.get("/api/hallucinations")
async def api_hallucinations(
    agent: str = "",
    severity: str = "",
    limit: int = 100,
    x_forge_token: Optional[str] = Header(default=None)
):
    """Get hallucination events with optional filters."""
    _check_auth(x_forge_token)
    events = _load_hallucinations()
    if agent:
        events = [e for e in events if e.get("agent", "").lower() == agent.lower()]
    if severity:
        events = [e for e in events if e.get("severity", "").lower() == severity.lower()]
    events = events[-limit:]

    # Stats
    all_events = _load_hallucinations()
    agents_stats = {}
    for e in all_events:
        a = e.get("agent", "unknown")
        if a not in agents_stats:
            agents_stats[a] = {"count": 0, "severities": {}}
        agents_stats[a]["count"] += 1
        s = e.get("severity", "unknown")
        agents_stats[a]["severities"][s] = agents_stats[a]["severities"].get(s, 0) + 1

    return {
        "events": events,
        "total": len(all_events),
        "agents_stats": agents_stats,
        "last_24h": len([e for e in all_events if e.get("timestamp", 0) > (datetime.now().timestamp() - 86400)])
    }


@app.post("/api/hallucinations/report")
async def api_hallucination_report(payload: dict, x_forge_token: Optional[str] = Header(default=None)):
    """Report a hallucination event."""
    _check_auth(x_forge_token)
    events = _load_hallucinations()
    event = {
        "id": _next_halluc_id(events),
        "timestamp": datetime.now().timestamp(),
        "timestamp_iso": datetime.now().isoformat(),
        "agent": payload.get("agent", "unknown"),
        "node": payload.get("node", ""),
        "severity": payload.get("severity", "medium"),  # low, medium, high, critical
        "description": payload.get("description", ""),
        "expected": payload.get("expected", ""),
        "actual": payload.get("actual", ""),
        "root_cause": payload.get("root_cause", ""),
        "context": payload.get("context", {}),
        "resolved": False
    }
    events.append(event)
    if len(events) > MAX_HALLUC_EVENTS:
        events = events[-MAX_HALLUC_EVENTS:]
    _save_hallucinations(events)

    # Broadcast via telemetry
    await telemetry.broadcast({
        "type": "HALLUCINATION_DETECTED",
        "source": event["agent"],
        "data": {"severity": event["severity"], "description": event["description"][:100]}
    })

    return {"success": True, "event_id": event["id"]}


@app.get("/api/hallucinations/health")
async def api_hallucination_health(x_forge_token: Optional[str] = Header(default=None)):
    """Fraîcheur du tracker. Répond à la seule question qui compte : « ce que
    j'ai sous les yeux date de quand ? ». Sans ça, un tracker mort et un tracker
    sans rien à signaler s'affichent exactement pareil."""
    _check_auth(x_forge_token)
    events = _load_hallucinations()
    now = datetime.now().timestamp()
    last_occurred = max((e.get("timestamp") or 0) for e in events) if events else 0
    last_detected = max((e.get("detected_at") or e.get("timestamp") or 0)
                        for e in events) if events else 0
    file_mtime = HALLUCINATION_FILE.stat().st_mtime if HALLUCINATION_FILE.exists() else 0

    ledger_path = FORGE_ROOT / "05_STATE" / "tool_call_ledger.jsonl"
    ledger_mtime = ledger_path.stat().st_mtime if ledger_path.exists() else 0

    age_min = (now - max(last_detected, file_mtime)) / 60 if events else None
    # « live » = le producteur a écrit dans les 10 dernières minutes.
    status = ("live" if age_min is not None and age_min < 10 else
              "stale" if age_min is not None and age_min < 1440 else
              "dead" if events else "empty")
    ids = [e.get("id") for e in events]
    return {
        "status": status,
        "events_total": len(events),
        "unique_ids": len(set(ids)),
        "duplicate_ids": len(ids) - len(set(ids)),
        "cap": MAX_HALLUC_EVENTS,
        "at_cap": len(events) >= MAX_HALLUC_EVENTS,
        "last_occurrence_iso": (datetime.fromtimestamp(last_occurred).isoformat()
                                if last_occurred else None),
        "last_detection_iso": (datetime.fromtimestamp(last_detected).isoformat()
                               if last_detected else None),
        "minutes_since_last_write": round(age_min, 1) if age_min is not None else None,
        "ledger_last_write_iso": (datetime.fromtimestamp(ledger_mtime).isoformat()
                                  if ledger_mtime else None),
        "watcher_running": bool(_halluc_watcher_task and not _halluc_watcher_task.done()),
    }


@app.post("/api/hallucinations/repair-ids")
async def api_hallucination_repair_ids(x_forge_token: Optional[str] = Header(default=None)):
    """Réattribue des ids uniques aux événements historiques créés sous
    l'ancienne règle `len(events)+1`. Sans ça, `/resolve` continue de marquer
    le mauvais événement pour tous les doublons déjà en base."""
    _check_auth(x_forge_token)
    events = _load_hallucinations()
    before = len(events) - len({e.get("id") for e in events})
    if before == 0:
        return {"success": True, "repaired": 0, "message": "aucun doublon"}
    seen: set = set()
    next_id = _next_halluc_id(events)
    repaired = 0
    for e in events:
        eid = e.get("id")
        if eid in seen or eid is None:
            e["id"] = next_id
            next_id += 1
            repaired += 1
        seen.add(e["id"])
    _save_hallucinations(events)
    return {"success": True, "repaired": repaired,
            "duplicates_before": before,
            "unique_ids_after": len({e.get("id") for e in events}),
            "total": len(events)}


@app.post("/api/hallucinations/scan")
async def api_hallucination_scan(x_forge_token: Optional[str] = Header(default=None)):
    """Déclenche un scan réel maintenant (ledger → findings → événements).
    Exécuté hors boucle : le scan lit ~1 000 enregistrements et ne doit pas
    bloquer le serveur. Le watcher diffusera les nouveaux événements."""
    _check_auth(x_forge_token)
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, _run_hallucination_scan)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"scan impossible: {e}")


@app.post("/api/hallucinations/{event_id}/resolve")
async def api_hallucination_resolve(event_id: int, payload: dict, x_forge_token: Optional[str] = Header(default=None)):
    """Mark a hallucination as resolved with notes."""
    _check_auth(x_forge_token)
    events = _load_hallucinations()
    for e in events:
        if e.get("id") == event_id:
            e["resolved"] = True
            e["resolved_at"] = datetime.now().isoformat()
            e["resolution_notes"] = payload.get("notes", "")
            _save_hallucinations(events)
            return {"success": True}
    raise HTTPException(status_code=404, detail="Event not found")


@app.get("/api/agents/{agent_id}/metrics")
async def api_agent_metrics(agent_id: str, x_forge_token: Optional[str] = Header(default=None)):
    """Get detailed metrics for a specific agent."""
    _check_auth(x_forge_token)
    # Get agent state
    state_file = FORGE_ROOT / "05_STATE" / "agents" / f"{agent_id}.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Get hallucination count for this agent
    all_halluc = _load_hallucinations()
    agent_halluc = [e for e in all_halluc if e.get("agent", "").lower() == agent_id.lower()]

    # Get experience data
    exp_db = _exp_db()
    agent_exps = [x for x in exp_db.get("experiences", []) if (x.get("agent") or "").lower() == agent_id.lower()]

    calls = state.get("calls", 0) or len(agent_exps)
    halluc_count = len(agent_halluc)
    halluc_rate = (halluc_count / calls * 100) if calls > 0 else 0

    return {
        "agent_id": agent_id,
        "calls": calls,
        "hallucinations": halluc_count,
        "hallucination_rate": round(halluc_rate, 1),
        "avg_quality": state.get("avg_quality"),
        "level": state.get("level", "L1"),
        "experiences_count": len(agent_exps),
        "recent_hallucinations": agent_halluc[-5:]
    }

# ── HELPERS GRAPHE : arborescence de code réelle + volet data science ────────

# Code propriétaire de la Forge : exploré récursivement, fichier par fichier.
_FORGE_CODE_ROOTS = ("00_CORE", "01_ORCHESTRATOR", "02_AGENTS", "03_JURY",
                     "04_GRAPHIFY", "09_WEB", "10_TRADING")
# Dépôts vendorés / tiers : agrégés en un seul nœud (sauf scope=full).
_VENDORED_ROOTS = ("07_KNOWLEDGE_BASE", "skills", "nexus", "RecursiveMAS",
                   "AsyncHerald", "cvelistV5-main")
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv",
              "site-packages", ".gitnexus", "dist", "build"}

_TREE_CACHE: dict[str, tuple[float, list]] = {}
_TREE_TTL = 30.0  # secondes — évite de rescanner le disque à chaque poll 8 s


def _scan_code_tree(scope: str = "core") -> list:
    """Retourne [(module_id, rel_path, [(Path, size_kb)], aggregate_count|None)].

    aggregate_count non-None ⇒ nœud agrégé (dépôt vendoré non développé).
    Résultat mis en cache 30 s : le poll du frontend ne martèle pas le FS.
    """
    cached = _TREE_CACHE.get(scope)
    if cached and (time.time() - cached[0]) < _TREE_TTL:
        return cached[1]

    out: list = []
    roots = list(_FORGE_CODE_ROOTS)
    if scope == "full":
        roots += list(_VENDORED_ROOTS)

    for root_name in roots:
        root = FORGE_ROOT / root_name
        if not root.exists():
            continue
        by_dir: dict[str, list] = {}
        for f in root.rglob("*.py"):
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            try:
                size_kb = round(f.stat().st_size / 1024, 1)
            except OSError:
                continue
            rel_dir = f.parent.relative_to(FORGE_ROOT).as_posix()
            by_dir.setdefault(rel_dir, []).append((f, size_kb))
        for rel_dir, files in sorted(by_dir.items()):
            out.append(("module:" + rel_dir, rel_dir, sorted(files, key=lambda t: t[0].name), None))

    if scope != "full":
        for root_name in _VENDORED_ROOTS:
            root = FORGE_ROOT / root_name
            if not root.exists():
                continue
            count = sum(1 for f in root.rglob("*.py")
                        if not any(p in _SKIP_DIRS for p in f.parts))
            if count:
                out.append(("module:" + root_name, root_name, [], count))

    _TREE_CACHE[scope] = (time.time(), out)
    return out


def _datascience_nodes() -> list:
    """Nœuds issus de l'agent Data Scientist (santé, anomalies, reco P0/P1).
    Silencieux si le module n'est pas importable — le graphe reste servi."""
    try:
        import sys
        core = str(FORGE_ROOT / "00_CORE")
        if core not in sys.path:
            sys.path.insert(0, core)
        from forge_agents.forge_data_scientist import get_data_scientist
        ds = get_data_scientist()
        report = ds.analyze(persist=False)
    except Exception:
        return []

    out: list = []
    h = report["health"]
    out.append(("ds:health", f"DS Health {h['grade']} ({h['score']}/100)", "datascience",
                h["score"] / 10.0,
                f"Couverture instrumentation: {h['instrumentation_coverage_pct']}% | "
                f"Aveugle sur: {', '.join(h['blind_metrics']) or '—'} | "
                f"Anomalies critical={h['critical_anomalies']} high={h['high_anomalies']}", 5))
    for i, a in enumerate(report["anomalies"][:8]):
        out.append((f"ds:anomaly:{i}", f"⚠ {a['metric']} / {a['subject']}"[:40], "datascience",
                    None, f"{a['severity'].upper()} — {a['message']}", 2.5))
    for i, r in enumerate(report["recommendations"][:8]):
        out.append((f"ds:reco:{i}", f"[{r['priority']}] {r['action']}"[:45], "datascience",
                    r["confidence"] * 10,
                    f"{r['rationale']} | gain: {r['expected_gain']}", 2))
    for c in report["agent_scorecards"][:10]:
        out.append((f"ds:score:{c['subject']}", f"{c['subject']} {c['composite']}/100",
                    "datascience", c["composite"] / 10.0,
                    f"eff={c['efficiency']} fiab={c['reliability']} coût={c['cost']} "
                    f"vit={c['speed']} | {c['calls']} appels | {c['verdict']}", 2))
    return out


@app.get("/api/graph")
@app.get("/graph")
async def api_graph(q: str = "", scope: str = "core",
                    x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    def add(nid, label, ntype, score=None, size=1, role=None, status="active", details=""):
        n = nodes.setdefault(nid, {
            "id": nid, 
            "label": label, 
            "type": ntype,
            "score": score, 
            "size": size,
            "role": role,
            "status": status,
            "details": details
        })
        n["size"] = max(n["size"], size)
        return n

    # ── 1. LANGGRAPH CORE FLOW NODES (The 11 nodes of La Forge) ──
    flow_nodes = [
        ("v6_init", "V6 Init", "graph", "Initialisation du kernel & cache orchestrator", "init"),
        ("estimate_budget", "Estimate Budget", "graph", "Prédiction des tokens & coût de la session", "budget"),
        ("orchestrator", "Orchestrator", "graph", "Superviseur central & routeur dynamique", "supervisor"),
        ("dynamic_agent", "Dynamic Agent", "graph", "Génération de code & exécution à la volée", "worker"),
        ("v6_post_execution", "Post Execution", "graph", "Enregistrement des scores & self-heal", "audit"),
        ("auto_complexification", "Auto Complexification", "graph", "Évaluation de complexité & évolution", "evolution"),
        ("post_mortem", "Post Mortem", "graph", "Analyse de fin de tâche & rétrospective", "analysis"),
        ("memory_pruner", "Memory Pruner", "graph", "Consolidation & nettoyage mémoire", "memory"),
        ("zsl_analysis", "ZSL Analysis", "graph", "Matching sémantique sans données d'entraînement", "security"),
        ("neuro_symbolic_verification", "Neuro-Symbolic Guard", "graph", "Vérification logique des hallucinations", "validator"),
        ("anti_hallucination", "Anti Hallucination", "graph", "Filtre de gravité sémantique & RCA", "validator")
    ]
    for nid, label, ntype, desc, role in flow_nodes:
        # Check current active node from checkpoint
        status = "active"
        cp_path = FORGE_ROOT / "05_STATE" / "checkpoint.json"
        if cp_path.exists():
            try:
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                if cp.get("current_node") == nid:
                    status = "running"
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        add(nid, label, ntype, size=3, role=role, status=status, details=desc)

    # Core flow edges
    flow_edges = [
        ("v6_init", "estimate_budget"),
        ("estimate_budget", "orchestrator"),
        ("orchestrator", "dynamic_agent"),
        ("orchestrator", "zsl_analysis"),
        ("zsl_analysis", "dynamic_agent"),
        ("dynamic_agent", "v6_post_execution"),
        ("dynamic_agent", "neuro_symbolic_verification"),
        ("neuro_symbolic_verification", "anti_hallucination"),
        ("anti_hallucination", "auto_complexification"),
        ("anti_hallucination", "dynamic_agent"),
        ("v6_post_execution", "auto_complexification"),
        ("auto_complexification", "memory_pruner"),
        ("memory_pruner", "orchestrator"),
        ("auto_complexification", "post_mortem")
    ]
    for src, tgt in flow_edges:
        links.append({"source": src, "target": tgt, "flow": True, "avg_latency_sec": 0.0})

    # Calculate avg_latency_sec from checkpoint history
    try:
        checkpoint_dir = FORGE_ROOT / "05_STATE"
        # Look for execution traces
        traces_dir = checkpoint_dir / "logs" / "executions"
        if traces_dir.exists():
            transition_times: dict[tuple[str, str], list[float]] = {}
            for trace_file in traces_dir.glob("trace-*.json"):
                try:
                    trace = json.loads(trace_file.read_text(encoding="utf-8"))
                    steps = trace.get("steps", [])
                    for i in range(len(steps) - 1):
                        src_node = steps[i].get("node", "")
                        tgt_node = steps[i+1].get("node", "")
                        t1 = steps[i].get("timestamp", 0)
                        t2 = steps[i+1].get("timestamp", 0)
                        if src_node and tgt_node and t1 and t2:
                            delta = abs(t2 - t1)
                            key = (src_node, tgt_node)
                            transition_times.setdefault(key, []).append(delta)
                except Exception:
                    continue

            # Update links with avg latency
            for link in links:
                key = (link["source"], link["target"])
                if key in transition_times and transition_times[key]:
                    avg = sum(transition_times[key]) / len(transition_times[key])
                    link["avg_latency_sec"] = round(avg, 2)
                    link["avg_latency_ms"] = round(avg * 1000, 0)  # Conversion sec → ms pour le frontend
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # ── 2. MEMORY LAYERS (L0 - L4) ──
    memory_layers = [
        ("L0_kernel", "L0: Kernel Store", "memory", "RAM, in-process active kernel"),
        ("L1_cervelet", "L1: Hot Cache (Redis)", "memory", "Réflexes ancrés & MCP cache"),
        ("L2_turbovec", "L2: Warm Index (4-bit)", "memory", "TurboVec & Nexus VFS embedded"),
        ("L3_forge_db", "L3: Deep Store (Postgres)", "memory", "Persistance relationnelle & pgvector"),
        ("L4_knowledge_base", "L4: Cold KB (Markdown)", "memory", "Skills indexés & patterns historiques")
    ]
    for nid, label, ntype, desc in memory_layers:
        add(nid, label, ntype, size=4, status="active", details=desc)
    
    # Connect memory nodes to graph coordinators
    links.append({"source": "v6_init", "target": "L0_kernel", "memory_bridge": True})
    links.append({"source": "orchestrator", "target": "L1_cervelet", "memory_bridge": True})
    links.append({"source": "dynamic_agent", "target": "L2_turbovec", "memory_bridge": True})
    links.append({"source": "v6_post_execution", "target": "L3_forge_db", "memory_bridge": True})
    links.append({"source": "memory_pruner", "target": "L4_knowledge_base", "memory_bridge": True})

    # ── 3. REGISTERED TOOLS (From tool_index.json) ──
    tools_data = []
    tool_index_file = FORGE_ROOT / "05_STATE" / "tool_index.json"
    if tool_index_file.exists():
        try:
            tools_data = json.loads(tool_index_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Fallback : tool_index.json est vide tant que l'auto-générateur n'a pas
    # tourné → on lit les vrais wrappers sur disque plutôt que d'afficher 0 outil.
    if not tools_data:
        tools_dir = FORGE_ROOT / "00_CORE" / "tools"
        if tools_dir.exists():
            for f in sorted(tools_dir.rglob("*.py")):
                if f.name.startswith("_") or any(p in _SKIP_DIRS for p in f.parts):
                    continue
                tools_data.append({
                    "name": f.stem,
                    "approach": f.relative_to(FORGE_ROOT).as_posix(),
                    "savings_pct": None,
                })

    for t in tools_data:
        tid = "tool:" + t["name"]
        savings = t.get("savings_pct")
        add(tid, t["name"], "tool",
            score=(savings / 10.0) if isinstance(savings, (int, float)) else None, size=2,
            details=f"Savings: {savings if savings is not None else '—'} | "
                    f"Approach: {t.get('approach')}")
        links.append({"source": "dynamic_agent", "target": tid, "tool_bridge": True})

    # ── 4. AGENTS INDEX (Dynamic specialist personas) ──
    for a in _agents_index():
        aid = "agent:" + a["name"]
        add(aid, a["name"], "agent", score=a["avg_score"], size=max(1, a["calls"]),
            details=f"Calls: {a['calls']} | Quality: {a['avg_score'] or '—'}/10 | Level: {a.get('level','—')}")
        links.append({"source": "orchestrator", "target": aid, "agent_bridge": True})

    # ── 5. HISTORICAL EXPERIENCES BACKBONE ──
    for x in _exp_db().get("experiences", [])[-400:]:
        eid = "exp:" + str(x.get("id", ""))
        add(eid, str(x.get("task", ""))[:45] + "...", "experience",
            score=x.get("quality_score"), size=1.5,
            details=f"Outcome: {x.get('outcome')} | Domain: {x.get('domain','—')} | Cost: ${x.get('cost', 0):.4f}")
        links.append({"source": eid, "target": "orchestrator", "history_bridge": True})

    # ── 6. LEARNED SKILLS (from 07_KNOWLEDGE_BASE/skills) ──
    skills_dir = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
    if skills_dir.exists():
        for f in sorted(skills_dir.glob("*.json")):
            try:
                sk = json.loads(f.read_text(encoding="utf-8"))
                if sk.get("status") != "active":
                    continue
                sid = "skill:" + sk.get("id", f.stem)
                consensus = sk.get("mirofish_approval", {}).get("consensus", 0)
                uses = sk.get("performance", {}).get("uses", 0)
                add(sid, sk.get("name", f.stem), "skill",
                    score=consensus, size=max(1.5, uses * 0.5),
                    details=f"Uses: {uses} | Consensus: {consensus} | Tier: {sk.get('tier','FREE')} | Task: {sk.get('task_type','—')}")
                links.append({"source": "L4_knowledge_base", "target": sid, "skill_bridge": True})
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # ── 7. CONFIRMED FINDINGS & VULNERABILITIES ──
    confirmed_dir = FORGE_ROOT / "06_FINDINGS" / "confirmed"
    if confirmed_dir.exists():
        for f in sorted(confirmed_dir.glob("*")):
            if f.suffix not in (".json", ".md"):
                continue
            try:
                if f.suffix == ".json":
                    fd = json.loads(f.read_text(encoding="utf-8"))
                else:
                    raw = f.read_text(encoding="utf-8")[:500]
                    fd = {"title": f.stem.replace("_", " ").replace("-", " "), "desc": raw}
                fid = "finding:" + f.stem
                title = fd.get("title", fd.get("name", f.stem))
                agent = fd.get("agent", "unknown")
                # No fabricated 7.0 default — a finding with no real score/
                # quality_score field genuinely has no score yet; add()
                # already defaults score=None and the graph renders that as
                # "no score" rather than a fake confident 7.0.
                score = fd.get("score", fd.get("quality_score"))
                if not isinstance(score, (int, float)):
                    score = None
                add(fid, str(title)[:50], "finding",
                    score=score, size=2,
                    details=f"Agent: {agent} | Status: confirmed | File: {f.name}")
                # Link finding to its discovering agent (if exists)
                agent_node_id = "agent:" + agent.upper()
                if agent_node_id in nodes:
                    links.append({"source": agent_node_id, "target": fid, "finding_bridge": True})
                else:
                    links.append({"source": "orchestrator", "target": fid, "finding_bridge": True})
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # ── 8. SOURCE FILES — arborescence RÉELLE de la Forge ──
    # Avant : un seul glob non récursif sur 00_CORE/forge_agents → ~100 nœuds,
    # soit une fraction de la Forge. Maintenant : scan récursif de tous les
    # dossiers de code propriétaire + nœuds « module » (dossiers) qui portent
    # la hiérarchie. Les dépôts vendorés (skills/, 07_KNOWLEDGE_BASE/, nexus/)
    # sont AGRÉGÉS en un nœud par racine, sinon 6 400 fichiers noieraient le
    # graphe ; `?scope=full` les développe.
    for mod_id, rel_path, files, agg in _scan_code_tree(scope):
        if agg is not None:
            add(mod_id, rel_path, "module", size=3, status="active",
                details=f"Dépôt vendoré agrégé — {agg} fichiers | Path: {rel_path}")
            links.append({"source": "L4_knowledge_base", "target": mod_id, "module_bridge": True})
            continue
        add(mod_id, rel_path, "module", size=max(2, min(8, len(files) / 4)),
            status="active", details=f"{len(files)} fichiers | Path: {rel_path}")
        # rattache le module à son parent (ou à dynamic_agent à la racine)
        parent_rel = "/".join(rel_path.split("/")[:-1])
        parent_id = "module:" + parent_rel if parent_rel else None
        links.append({"source": parent_id if parent_id in nodes else "dynamic_agent",
                      "target": mod_id, "module_bridge": True})
        for f, size_kb in files:
            fid = "file:" + f"{rel_path}/{f.stem}"
            add(fid, f.name, "file", size=max(1, min(6, size_kb / 10)),
                details=f"Size: {size_kb}KB | Path: {rel_path}/{f.name}")
            # un fichier qui implémente un nœud du flow est rattaché à ce nœud
            stem = f.stem.lower().replace("_", "")
            target_graph = next(
                (nid for nid in nodes
                 if nodes[nid]["type"] == "graph" and stem in nid.replace("_", "")), None)
            links.append({"source": target_graph or mod_id, "target": fid,
                          "file_bridge": True})

    # ── 9. DATA SCIENTIST — santé analytique, anomalies, recommandations ──
    for nid, label, ntype, score, details, size in _datascience_nodes():
        add(nid, label, ntype, score=score, size=size, details=details)
        links.append({"source": "post_mortem", "target": nid, "ds_bridge": True})

    # Filter logic
    if q:
        ql = q.lower()
        matched = {nid for nid, n in nodes.items()
                   if ql in n["label"].lower() or ql in nid.lower() or ql in n.get("details", "").lower()}
        keep = set(matched)
        for l in links:
            if l["source"] in matched or l["target"] in matched:
                keep.add(l["source"])
                keep.add(l["target"])
        # Always keep flow edges and their connected nodes
        for l in links:
            if l.get("flow"):
                keep.add(l["source"])
                keep.add(l["target"])
        nodes = {nid: n for nid, n in nodes.items() if nid in keep}
        links = [l for l in links if l["source"] in nodes and l["target"] in nodes]
        for nid in matched:
            nodes[nid]["matched"] = True
    else:
        # No query: ensure all flow edges are present
        # This fixes the bug where flows disappear when all nodes are checked
        pass  # links already include all flow edges

    node_list = list(nodes.values())
    # `version` = empreinte du CONTENU (pas seulement du nombre de nœuds).
    # Le frontend s'en sert pour détecter un changement d'état/score/latence
    # même à effectif constant — c'était la cause des nœuds « figés ».
    version = hashlib.sha1(
        json.dumps([node_list, links], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    by_type: dict[str, int] = {}
    for n in node_list:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    return {"nodes": node_list, "links": links, "version": version, "scope": scope,
            "counts": {"nodes": len(nodes), "links": len(links), "by_type": by_type}}

# ── DATA SCIENTIST API ────────────────────────────────────────────────────────

def _ds():
    import sys as _s
    core = str(FORGE_ROOT / "00_CORE")
    if core not in _s.path:
        _s.path.insert(0, core)
    from forge_agents.forge_data_scientist import get_data_scientist
    return get_data_scientist()


@app.get("/api/datascience/report")
async def api_ds_report(window: float = 30.0, budget: Optional[float] = None,
                        x_forge_token: Optional[str] = Header(default=None)):
    """Rapport complet : inventaire, couverture, anomalies, prévisions,
    scorecards, A/B, recommandations. 0 token LLM."""
    _check_auth(x_forge_token)
    try:
        import sys as _s
        core = str(FORGE_ROOT / "00_CORE")
        if core not in _s.path:
            _s.path.insert(0, core)
        from forge_agents.forge_data_scientist import get_data_scientist
        return get_data_scientist(window).analyze(budget_usd=budget)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"data scientist indisponible: {e}")


@app.get("/api/datascience/anomalies")
async def api_ds_anomalies(min_severity: str = "medium",
                           x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    return {"anomalies": _ds().anomalies(min_severity)}


@app.get("/api/datascience/forecast")
async def api_ds_forecast(budget: Optional[float] = None,
                          x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    return {"forecasts": _ds().forecasts(budget)}


@app.get("/api/datascience/scorecards")
async def api_ds_scorecards(dimension: str = "agent",
                            x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    if dimension not in ("agent", "model"):
        raise HTTPException(status_code=400, detail="dimension must be agent|model")
    return {"dimension": dimension, "scorecards": _ds().scorecards(dimension)}


@app.get("/api/datascience/abtest")
async def api_ds_abtest(dimension: str = "model", a: Optional[str] = None,
                        b: Optional[str] = None, metric: str = "cost_usd",
                        x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    ds = _ds()
    if a and b:
        return ds.ab_test(dimension, a, b, metric)
    from dataclasses import asdict as _asdict
    return {"tests": [_asdict(r) for r in ds.abtester.auto_smart(dimension)]}


@app.get("/api/datascience/recommendations")
async def api_ds_recos(budget: Optional[float] = None,
                       x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    return {"recommendations": _ds().recommendations(budget)}


@app.get("/api/datascience/choose")
async def api_ds_choose(dimension: str = "agent", seed: Optional[int] = None,
                        x_forge_token: Optional[str] = Header(default=None)):
    """Routage appris (bandit ε-greedy sur qualité/coût/temps)."""
    _check_auth(x_forge_token)
    return _ds().choose_agent(dimension, explore_seed=seed) or {"subject": None,
                                                                "reason": "no_data"}


@app.post("/api/datascience/card")
async def api_ds_card(payload: dict, x_forge_token: Optional[str] = Header(default=None)):
    """Carte post-tâche {what_worked, what_failed, cost, time, recommendation,
    confidence} — le dataset propriétaire de la Forge, une ligne par tâche."""
    _check_auth(x_forge_token)
    return _ds().post_task_card(task=payload.get("task", ""),
                                since_ts=payload.get("since_ts"))


# ── POST /api/node/{node_id}/update ───────────────────────────────────────────
@app.post("/api/node/{node_id}/update")
async def update_node_config(node_id: str, payload: dict, x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    
    agent_static_dir = FORGE_ROOT / "02_AGENTS"
    target_name = node_id.replace("agent:", "").lower()
    
    target_path = None
    if agent_static_dir.exists():
        for d in agent_static_dir.iterdir():
            if d.is_dir() and (d.name.lower() == target_name or target_name in d.name.lower()):
                mds = list(d.glob("*.md")) + list(d.glob("*.txt"))
                if mds:
                    target_path = mds[0]
                    break
        
        if not target_path:
            target_path = agent_static_dir / "AGENT_UNIVERSAL_TEMPLATE.md"

    if target_path and target_path.exists():
        try:
            content = payload.get("prompt", "").strip()
            if not content:
                raise HTTPException(status_code=400, detail="Content cannot be empty")
            target_path.write_text(content, encoding="utf-8")

            # Version increment on prompt edit
            try:
                import sys
                sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
                from forge_versioning import get_versioning
                new_ver = get_versioning().increment_version(reason=f"node_edit:{node_id}")
            except Exception:
                new_ver = None

            return JSONResponse({"success": True, "path": str(target_path), "version": new_ver})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
    return JSONResponse({"success": False, "reason": "No editable configuration found for this node"})

# ── GET /api/version ──────────────────────────────────────────────────────────
@app.get("/api/version")
async def get_version(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_versioning import get_versioning
        return JSONResponse(get_versioning().get_version_info())
    except Exception as e:
        return JSONResponse({"error": str(e), "version": "unknown"})

# ── GET /api/vault ────────────────────────────────────────────────────────────
@app.get("/api/vault")
async def get_vault(x_forge_token: Optional[str] = Header(default=None)):
    """Retourne l'arborescence du vault Obsidian."""
    _check_auth(x_forge_token)
    vault_dir = FORGE_ROOT / "vault"
    if not vault_dir.exists():
        return JSONResponse({"folders": [], "files": [], "total": 0})

    def scan_dir(path: Path, relative: str = "") -> dict:
        folders = []
        files = []
        for item in sorted(path.iterdir()):
            rel = f"{relative}/{item.name}" if relative else item.name
            if item.is_dir():
                folders.append({
                    "name": item.name,
                    "path": rel,
                    "children": scan_dir(item, rel),
                })
            elif item.suffix == ".md":
                stat = item.stat()
                files.append({
                    "name": item.name,
                    "path": rel,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return {"folders": folders, "files": files}

    tree = scan_dir(vault_dir)
    total = sum(1 for _ in vault_dir.rglob("*.md"))
    return JSONResponse({"folders": tree["folders"], "files": tree["files"], "total": total})

# ── GET /api/vault/file/{path} ────────────────────────────────────────────────
@app.get("/api/vault/file/{file_path:path}")
async def get_vault_file(file_path: str, x_forge_token: Optional[str] = Header(default=None)):
    """Lit un fichier markdown du vault."""
    _check_auth(x_forge_token)
    full_path = FORGE_ROOT / "vault" / file_path
    if not full_path.exists() or not full_path.suffix == ".md":
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = full_path.read_text(encoding="utf-8")
        return JSONResponse({
            "path": file_path,
            "content": content,
            "size": len(content),
            "modified": datetime.fromtimestamp(full_path.stat().st_mtime).isoformat(),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent Tracker API ────────────────────────────────────────────────────────

@app.get("/api/agent-tracker/current")
async def get_agent_tracker_current(x_forge_token: Optional[str] = Header(default=None)):
    """Retourne la tâche en cours du tracker d'agents."""
    _check_auth(x_forge_token)
    try:
        tracker_dir = FORGE_ROOT / "05_STATE" / "agent_tracker"
        current_file = tracker_dir / "current_task.json"
        if current_file.exists():
            return JSONResponse(json.loads(current_file.read_text(encoding="utf-8")))
        return JSONResponse({"task_name": None})
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get("/api/agent-tracker/performance")
async def get_agent_tracker_performance(x_forge_token: Optional[str] = Header(default=None)):
    """Retourne les statistiques de performance des agents."""
    _check_auth(x_forge_token)
    try:
        tracker_dir = FORGE_ROOT / "05_STATE" / "agent_tracker"
        history_file = tracker_dir / "history.json"
        if history_file.exists():
            history = json.loads(history_file.read_text(encoding="utf-8"))
            # Aggregate agent stats from all tasks. NOTE: agent_stats entries
            # no longer carry total_score/avg_score/trend — those were an
            # ungrounded formula + hardcoded "stable" default, removed from
            # the writer (scripts/hermes_session_tracker.py's
            # update_agent_tracker()). Defaulting the now-missing field to 0
            # here would have silently recreated the same fabrication one hop
            # downstream (a fake "0/10" reading as a real bad score instead
            # of "not scored"). Aggregate the real replacement signal instead:
            # hallucination_findings_count, which is None when unchecked.
            agents = {}
            for task in history.get("tasks", []):
                for agent, stats in task.get("agent_stats", {}).items():
                    if agent not in agents:
                        agents[agent] = {"count": 0, "total_tokens": 0, "_hfc_sum": 0, "_hfc_n": 0}
                    agents[agent]["count"] += stats.get("count", 0)
                    agents[agent]["total_tokens"] += stats.get("total_tokens", 0)
                    hfc = stats.get("hallucination_findings_count")
                    if hfc is not None:
                        agents[agent]["_hfc_sum"] += hfc
                        agents[agent]["_hfc_n"] += 1

            for agent, data in agents.items():
                data["avg_hallucination_findings"] = (
                    round(data["_hfc_sum"] / data["_hfc_n"], 2) if data["_hfc_n"] else None
                )
                data["sessions_checked"] = data["_hfc_n"]
                del data["_hfc_sum"]
                del data["_hfc_n"]

            return JSONResponse({"agents": agents})
        return JSONResponse({"agents": {}})
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get("/api/agent-tracker/adjustments")
async def get_agent_tracker_adjustments(x_forge_token: Optional[str] = Header(default=None)):
    """Retourne les ajustements de prompt pour chaque agent."""
    _check_auth(x_forge_token)
    try:
        tracker_dir = FORGE_ROOT / "05_STATE" / "agent_tracker"
        adjustments_file = tracker_dir / "prompt_adjustments.json"
        if adjustments_file.exists():
            return JSONResponse(json.loads(adjustments_file.read_text(encoding="utf-8")))
        return JSONResponse({"agents": {}})
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── Dashboard Stats API ──────────────────────────────────────────────────────

@app.get("/api/dashboard/stats")
async def get_dashboard_stats(x_forge_token: Optional[str] = Header(default=None)):
    """Retourne les statistiques du dashboard en temps réel."""
    _check_auth(x_forge_token)
    try:
        stats_file = FORGE_ROOT / "05_STATE" / "dashboard_stats.json"
        if stats_file.exists():
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
            return JSONResponse(stats)
        return JSONResponse({
            "timestamp": datetime.now().isoformat(),
            "total_sessions": 0,
            "total_messages": 0,
            "total_tool_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0,
            "recent_sessions_24h": 0,
            "recent_messages_24h": 0,
            "recent_tokens_24h": 0,
            "last_sessions": [],
            "models_used": [],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── GET /api/prune/stats ──────────────────────────────────────────────────────
@app.get("/api/prune/stats")
async def get_prune_stats(x_forge_token: Optional[str] = Header(default=None)):
    """Statistiques de pruning des nœuds."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from memory_pruner import get_pruner
        return JSONResponse(get_pruner().get_stats())
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── POST /api/prune/run ───────────────────────────────────────────────────────
@app.post("/api/prune/run")
async def run_prune(x_forge_token: Optional[str] = Header(default=None)):
    """Exécute le pruning manuellement."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from memory_pruner import get_pruner
        report = get_pruner().prune()
        return JSONResponse(report)
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── GET /api/reuse ────────────────────────────────────────────────────────────
@app.get("/api/reuse")
async def api_reuse(q: str = "", x_forge_token: Optional[str] = Header(default=None)):
    """Match task to existing skills/tools for reuse."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_reuse_engine import get_reuse_engine
        engine = get_reuse_engine()
        if q:
            suggestions = engine.match_task(q, top_k=5)
            return JSONResponse({
                "query": q,
                "suggestions": [
                    {
                        "type": s.type,
                        "name": s.name,
                        "description": s.description,
                        "confidence": round(s.confidence, 3),
                        "reason": s.reason,
                        "tokens_saved": s.tokens_saved,
                    }
                    for s in suggestions
                ],
            })
        else:
            return JSONResponse(engine.get_stats())
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── POST /api/reuse/record ────────────────────────────────────────────────────
@app.post("/api/reuse/record")
async def api_reuse_record(request: Request, x_forge_token: Optional[str] = Header(default=None)):
    """Record a reuse event."""
    _check_auth(x_forge_token)
    try:
        payload = await request.json()
        # No fabricated True default — an event whose caller didn't state
        # success/failure is not evidence of success; recording it as True
        # would inflate the reuse engine's success-rate stats with an
        # unverified event. Require the caller to say.
        if "success" not in payload:
            return JSONResponse({"error": "payload must include a boolean 'success' field"}, status_code=400)
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_reuse_engine import get_reuse_engine
        engine = get_reuse_engine()
        engine.record_reuse(
            name=payload.get("name", ""),
            success=bool(payload.get("success")),
            tokens_saved=payload.get("tokens_saved", 0),
        )
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── GET /api/chat/config ──────────────────────────────────────────────────────
@app.get("/api/chat/config")
async def api_chat_config(x_forge_token: Optional[str] = Header(default=None)):
    """Get chat provider configuration (keys masked)."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_chat_provider import get_chat_config
        return JSONResponse(get_chat_config().get_config())
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── POST /api/chat/config ─────────────────────────────────────────────────────
@app.post("/api/chat/config")
async def api_chat_config_set(request: Request, x_forge_token: Optional[str] = Header(default=None)):
    """Set chat provider configuration."""
    _check_auth(x_forge_token)
    try:
        payload = await request.json()
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_chat_provider import get_chat_config
        config = get_chat_config()

        # Set API keys
        for provider in ("hermes", "claude", "google"):
            key = payload.get(f"{provider}_key")
            if key:
                config.set_key(provider, key)

        # Set active provider
        active = payload.get("active_provider")
        if active:
            config.set_active(active)

        return JSONResponse(config.get_config())
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── POST /api/chat/send — Direct Hermes chat ────────────────────────────────
@app.post("/api/chat/send")
async def api_chat_send(request: Request, x_forge_token: Optional[str] = Header(default=None)):
    """Send a chat message and get AI response."""
    _check_auth(x_forge_token)
    try:
        payload = await request.json()
        message = payload.get("message", "").strip()
        provider = payload.get("provider", "hermes")
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        # Use hermes CLI for chat
        import subprocess
        import os

        env = os.environ.copy()
        cmd = ["hermes", "chat", "-q", message, "-Q"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
                env=env,
                cwd=str(FORGE_ROOT),
            )
            response = result.stdout.decode('utf-8', errors='replace').strip()
            if not response:
                response = result.stderr.decode('utf-8', errors='replace').strip()[:500]
            if not response:
                response = "(No response from Hermes)"
            # Clean up: remove hermes debug lines (session_id, Exception traces)
            lines = response.split('\n')
            clean_lines = []
            skip_traceback = False
            for line in lines:
                if line.startswith('Exception in thread') or line.startswith('Traceback'):
                    skip_traceback = True
                    continue
                if skip_traceback:
                    if line.startswith('  ') or line.startswith('File '):
                        continue
                    skip_traceback = False
                if line.startswith('session_id:'):
                    continue
                if line.strip().startswith('UnicodeDecodeError'):
                    continue
                clean_lines.append(line)
            response = '\n'.join(clean_lines).strip()
        except subprocess.TimeoutExpired:
            response = "Request timed out (120s limit)"
        except FileNotFoundError:
            # Fallback: try python -m hermes
            try:
                result = subprocess.run(
                    ["python", "-m", "hermes", "chat", "-q", message, "-Q"],
                    capture_output=True, text=True, timeout=120, env=env
                )
                response = result.stdout.strip() or "(No response)"
            except Exception as e:
                response = f"Hermes not available: {str(e)}"

        return JSONResponse({
            "response": response,
            "provider": provider,
            "model": "mimo-v2.5-pro",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── GET /api/search ───────────────────────────────────────────────────────────
@app.get("/api/search")
async def api_search(
    q: str = "",
    type: str = "",
    domain: str = "",
    min_score: float = 0,
    top_k: int = 10,
    x_forge_token: Optional[str] = Header(default=None),
):
    """Full-text + metadata search across all Forge data."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_search_engine import get_search_engine
        engine = get_search_engine()

        filters = {}
        if type:
            filters["type"] = type
        if domain:
            filters["domain"] = domain
        if min_score:
            filters["min_score"] = min_score

        if q:
            results = engine.search(q, filters=filters, top_k=top_k)
            return JSONResponse({"query": q, "results": results, "count": len(results)})
        else:
            # Return facets and stats
            return JSONResponse({
                "stats": engine.get_stats(),
                "facets": engine.facets(),
            })
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── GET /api/search/similar ───────────────────────────────────────────────────
@app.get("/api/search/similar")
async def api_search_similar(id: str = "", x_forge_token: Optional[str] = Header(default=None)):
    """Find items similar to a given item."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_search_engine import get_search_engine
        engine = get_search_engine()
        results = engine.find_similar(id)
        return JSONResponse({"id": id, "similar": results})
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── GET /api/search/stale ─────────────────────────────────────────────────────
@app.get("/api/search/stale")
async def api_search_stale(days: int = 30, x_forge_token: Optional[str] = Header(default=None)):
    """Find stale items not used in N days."""
    _check_auth(x_forge_token)
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from forge_search_engine import get_search_engine
        engine = get_search_engine()
        results = engine.find_stale(days)
        return JSONResponse({"days": days, "stale": results, "count": len(results)})
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ── GET /api/skills ───────────────────────────────────────────────────────────
@app.get("/api/skills")
async def api_skills(x_forge_token: Optional[str] = Header(default=None)):
    """Liste les skills actifs avec consensus et score."""
    _check_auth(x_forge_token)
    skills = []

    # Scan skills directories
    skills_dirs = [
        FORGE_ROOT / "skills",
        FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills",
        Path.home() / "AppData" / "Local" / "hermes" / "skills",
    ]

    for skills_dir in skills_dirs:
        if not skills_dir.exists():
            continue
        for skill_file in skills_dir.rglob("SKILL.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")[:2000]
                # Extract name from frontmatter
                name = skill_file.parent.name
                if "name:" in content:
                    for line in content.split("\n"):
                        if line.strip().startswith("name:"):
                            name = line.split(":", 1)[1].strip().strip('"').strip("'")
                            break

                # Extract description
                desc = ""
                if "description:" in content:
                    for line in content.split("\n"):
                        if line.strip().startswith("description:"):
                            desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                            break

                # Extract tags
                tags = []
                if "tags:" in content:
                    for line in content.split("\n"):
                        if line.strip().startswith("tags:"):
                            tag_str = line.split(":", 1)[1].strip()
                            tags = [t.strip().strip('"').strip("'") for t in tag_str.split(",") if t.strip()]
                            break

                # Calculate consensus from verdict history (0-100). No
                # fabricated 75 default — a skill with no matching verdict
                # file genuinely has no MiroFish consensus yet; None reads
                # as "not yet evaluated" rather than a fake real-looking 75.
                consensus = None
                verdicts_dir = FORGE_ROOT / "05_STATE" / "evidence"
                if verdicts_dir.exists():
                    for vf in verdicts_dir.glob("*.json"):
                        try:
                            vdata = json.loads(vf.read_text(encoding="utf-8"))
                            if name.lower() in str(vdata).lower():
                                score = vdata.get("score", vdata.get("consensus"))
                                if isinstance(score, (int, float)):
                                    consensus = min(100, max(0, score))
                        except Exception:
                            continue

                skills.append({
                    "name": name,
                    "description": desc,
                    "tags": tags,
                    "path": str(skill_file.relative_to(skills_dir)),
                    "consensus": consensus,
                    "status": "active",
                })
            except Exception:
                continue

    return JSONResponse({"skills": skills, "total": len(skills)})

# ── GET /api/optimizer/suggestions ────────────────────────────────────────────
@app.get("/api/optimizer/suggestions")
async def get_optimization_suggestions(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    
    tools = []
    tool_index_file = FORGE_ROOT / "05_STATE" / "tool_index.json"
    if tool_index_file.exists():
        try:
            tools = json.loads(tool_index_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Also read from agent tracker history for more recent data
    agent_history = []
    agent_tracker_file = FORGE_ROOT / "05_STATE" / "agent_tracker" / "history.json"
    if agent_tracker_file.exists():
        try:
            history = json.loads(agent_tracker_file.read_text(encoding="utf-8"))
            agent_history = history.get("tasks", [])
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    
    exps = _exp_db().get("experiences", [])
    suggestions = []
    
    for t in tools:
        savings = t.get("savings_pct", 50)
        pattern = t.get("pattern", "")
        name = t.get("name", "")
        approach = t.get("approach", "")
        
        matched_runs = 0
        total_tokens_spent = 0
        
        # Match against experiences
        for x in exps:
            task = x.get("task", "").lower()
            pattern_keywords = pattern.lower().split()
            if any(kw in task for kw in pattern_keywords if len(kw) > 2):
                matched_runs += 1
                total_tokens_spent += x.get("tokens_used", 1000)
        
        # Also match against agent tracker history
        for task_entry in agent_history:
            task_name = task_entry.get("task_name", "").lower()
            pattern_keywords = pattern.lower().split()
            if any(kw in task_name for kw in pattern_keywords if len(kw) > 2):
                matched_runs += 1
                # Sum tokens from invocations
                for inv in task_entry.get("invocations", []):
                    total_tokens_spent += inv.get("tokens", 0)
        
        cost_estimated_spent = total_tokens_spent * 0.00003
        potential_savings = cost_estimated_spent * (savings / 100.0)
        
        # Always show tool even with 0 matches (for visibility)
        suggestions.append({
            "tool_name": name,
            "pattern": pattern,
            "matched_runs": matched_runs,
            "spent_estimated_usd": round(cost_estimated_spent, 4),
            "potential_savings_usd": round(potential_savings, 4),
            "savings_pct": savings,
            "approach": approach,
            "recommendation": f"Replace generic LLM calls for '{pattern}' with local tool '{name}' ({approach}) to save {savings}% tokens." if matched_runs > 0 else f"Tool '{name}' available for '{pattern}' tasks. {approach}",
            "use_count": t.get("use_count", 0),
            "last_used": t.get("last_used"),
        })
    
    # Sort by potential savings (highest first)
    suggestions.sort(key=lambda x: x.get("potential_savings_usd", 0), reverse=True)
    
    # ── Auto-detected repetitive tasks (from auto_tool_generator) ──
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from auto_tool_generator import load_fingerprints, find_repetitive_tasks
        fingerprints = load_fingerprints()
        repetitive = find_repetitive_tasks(fingerprints, min_hits=3)
        for rep in repetitive:
            task = rep.get("task", "")
            count = rep.get("count", 0)
            # Check if already in suggestions
            existing = any(task.lower() in s.get("pattern", "").lower() for s in suggestions)
            if not existing:
                suggestions.append({
                    "tool_name": f"Auto-detected: {task[:40]}",
                    "pattern": task,
                    "matched_runs": count,
                    "spent_estimated_usd": round(count * 1000 * 0.00003, 4),
                    "potential_savings_usd": round(count * 1000 * 0.00003 * 0.6, 4),
                    "savings_pct": 60,
                    "approach": f"Repetitive task detected {count}x — consider generating a local tool",
                    "recommendation": f"Task '{task[:50]}' executed {count} times. Auto-generate a local tool to save 60% tokens.",
                    "use_count": 0,
                    "auto_detected": True,
                })
    except Exception as e:
        logger.debug(f"[Optimizer] Auto-tool scan skipped: {e}")
    
    # Add timestamp for real-time tracking
    from datetime import datetime
    return JSONResponse({
        "suggestions": suggestions,
        "timestamp": datetime.now().isoformat(),
        "total_tools": len(tools),
        "total_experiences": len(exps),
        "total_agent_tasks": len(agent_history),
    })

    return JSONResponse({"suggestions": suggestions})


# ── GET /api/kb/datasets ──────────────────────────────────────────────────────
@app.get("/api/kb/datasets")
async def api_kb_datasets(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    datasets_file = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "index.json"
    if datasets_file.exists():
        try:
            return JSONResponse(json.loads(datasets_file.read_text(encoding="utf-8")))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read index.json: {e}")
    return JSONResponse({"datasets": []})


# ── GET /api/kb/repos ─────────────────────────────────────────────────────────
@app.get("/api/kb/repos")
async def api_kb_repos(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    resources_file = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "external_resources.json"
    github_file = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "github_inventory.json"
    
    resources = []
    if resources_file.exists():
        try:
            resources = json.loads(resources_file.read_text(encoding="utf-8")).get("resources", [])
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            
    github_repos = []
    if github_file.exists():
        try:
            github_repos = json.loads(github_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            
    return JSONResponse({
        "resources": resources,
        "github_repos": github_repos
    })


# ── GET /api/token_sprints — Data Science sprint analytics ───────────────────
@app.get("/api/token_sprints")
async def api_token_sprints(
    sprint_id: str = "",
    x_forge_token: Optional[str] = Header(default=None)
):
    _check_auth(x_forge_token)
    try:
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
        from forge_agents.token_sprint_tracker import sprint_summary, import_existing_logs, _load_sprints
        # Auto-import on first call
        sprint_file = FORGE_ROOT / "05_STATE" / "token_sprints.json"
        if not sprint_file.exists() or sprint_file.stat().st_size < 100:
            import_existing_logs()

        # Also import from Hermes session DB for up-to-date data
        _import_hermes_sessions()

        summary = sprint_summary(sprint_id)

        # Enrich with daily aggregation + token totals
        records = _load_sprints()
        daily = _aggregate_by_day(records)
        models = _aggregate_by_model(records)

        summary["daily"] = daily
        summary["by_model"] = models
        summary["total_tokens_in"] = sum(r.get("tokens_actual_in", 0) for r in records)
        summary["total_tokens_out"] = sum(r.get("tokens_actual_out", 0) for r in records)
        summary["total_cost_usd"] = round(sum(r.get("cost_actual_usd", 0) for r in records), 4)
        summary["unique_models"] = list(set(r.get("model", "unknown") for r in records))
        summary["date_range"] = _get_date_range(records)

        return JSONResponse(summary)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _import_hermes_sessions() -> int:
    """Import token data from Hermes session DB (SQLite)."""
    import sqlite3
    hermes_db = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
    if not hermes_db.exists():
        return 0

    try:
        from forge_agents.token_sprint_tracker import _load_sprints, _save_sprints, SprintRecord
        from dataclasses import asdict
    except ImportError:
        return 0

    # Real, checked hallucination detection — never a hardcoded False. See
    # 00_CORE/forge_agents/hallucination_compare.py's own docstring for the
    # bug this replaces: a hardcoded "hallucination_detected": False here
    # would recreate the exact "0% means never checked" problem that module
    # exists to fix, for every session this import path touches.
    try:
        from forge_agents.hallucination_compare import scan_ledger, ledger_covered_session_ids
        _ledger_covered = ledger_covered_session_ids()
    except ImportError:
        scan_ledger = None
        _ledger_covered = set()

    existing = _load_sprints()
    existing_sids = {r.get("sprint_id") for r in existing}
    imported = 0

    try:
        conn = sqlite3.connect(str(hermes_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, title, started_at, model,
                   input_tokens, output_tokens, cache_read_tokens,
                   tool_call_count, message_count
            FROM sessions
            WHERE (archived = 0 OR archived IS NULL)
              AND input_tokens > 0
            ORDER BY started_at DESC
            LIMIT 200
        """).fetchall()
        conn.close()

        for row in rows:
            sid = row["id"]
            if sid in existing_sids:
                continue

            # Estimate cost based on model
            model = row["model"] or "unknown"
            in_tok = row["input_tokens"] or 0
            out_tok = row["output_tokens"] or 0
            cache_tok = row.get("cache_read_tokens") or 0

            cost = _estimate_cost(model, in_tok, out_tok, cache_tok)

            # Real, checked count — None (not 0/False) when the ledger has no
            # coverage for this session_id, since scan_ledger() finding zero
            # matches and "never checked" are not the same claim.
            hfc = len(scan_ledger(session_id=sid)) if (scan_ledger and sid in _ledger_covered) else None

            rec = {
                "sprint_id": sid,
                "task_id": (row["title"] or "")[:50],
                "task_type": "hermes_session",
                "model": model,
                # tokens_estimated_in/out, cost_estimated_usd, latency_ms,
                # variance_pct, auto_refinement_triggered are OMITTED — this
                # import path never estimates/times/refines, so asserting 0
                # would falsely claim "estimated 0"/"0ms" rather than "not
                # applicable" (mirrors scripts/hermes_session_tracker.py's
                # update_sprint_data()).
                "tokens_actual_in": in_tok,
                "tokens_actual_out": out_tok,
                "cost_actual_usd": cost,
                "hallucination_findings_count": hfc,
                "hallucination_detected": (hfc > 0) if hfc is not None else None,
            }
            raw_ts = row["started_at"]
            if isinstance(raw_ts, (int, float)):
                import datetime as _dt
                rec["ts"] = _dt.datetime.fromtimestamp(raw_ts, tz=_dt.timezone.utc).isoformat()
            else:
                rec["ts"] = str(raw_ts) if raw_ts else ""

            existing.append(rec)
            imported += 1

        if imported:
            _save_sprints(existing)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    return imported


def _estimate_cost(model: str, in_tok: int, out_tok: int, cache_tok: int = 0) -> float:
    """Estimate USD cost based on model pricing."""
    m = model.lower()
    # Per-million-token pricing (approximate)
    pricing = {
        "claude-opus": (15.0, 75.0),
        "claude-sonnet": (3.0, 15.0),
        "claude-haiku": (0.80, 4.0),
        "mimo": (0.0, 0.0),  # free tier
        "gemini": (0.0, 0.0),
        "groq": (0.0, 0.0),
        "gpt-4": (10.0, 30.0),
        "gpt-3.5": (0.50, 1.50),
    }
    for key, (in_rate, out_rate) in pricing.items():
        if key in m:
            return round((in_tok * in_rate + out_tok * out_rate) / 1_000_000, 6)
    # Default: assume cheap
    return round((in_tok * 0.50 + out_tok * 1.50) / 1_000_000, 6)


def _aggregate_by_day(records: list[dict]) -> dict:
    """Aggregate records by day for chart display."""
    import datetime as _dt
    daily = {}
    for r in records:
        ts = r.get("ts", "")
        if not ts:
            continue
        # Handle both ISO and Unix timestamps
        if "-" in ts and "T" in ts:
            day = ts[:10]  # YYYY-MM-DD
        elif "-" in ts and len(ts) >= 10:
            day = ts[:10]
        else:
            try:
                day = _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                continue
        if day not in daily:
            daily[day] = {
                "tokens_in": 0, "tokens_out": 0,
                "cost_usd": 0.0, "records": 0,
                "models": set(), "hallucinations": 0,
            }
        daily[day]["tokens_in"] += r.get("tokens_actual_in", 0)
        daily[day]["tokens_out"] += r.get("tokens_actual_out", 0)
        daily[day]["cost_usd"] += r.get("cost_actual_usd", 0)
        daily[day]["records"] += 1
        daily[day]["models"].add(r.get("model", "unknown"))
        if r.get("hallucination_detected"):
            daily[day]["hallucinations"] += 1

    # Convert sets to lists for JSON
    for day in daily:
        daily[day]["models"] = sorted(daily[day]["models"])
        daily[day]["cost_usd"] = round(daily[day]["cost_usd"], 6)
        daily[day]["tokens_total"] = daily[day]["tokens_in"] + daily[day]["tokens_out"]

    return dict(sorted(daily.items()))


def _aggregate_by_model(records: list[dict]) -> dict:
    """Aggregate records by model."""
    models = {}
    for r in records:
        m = r.get("model", "unknown")
        if m not in models:
            models[m] = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "records": 0}
        models[m]["tokens_in"] += r.get("tokens_actual_in", 0)
        models[m]["tokens_out"] += r.get("tokens_actual_out", 0)
        models[m]["cost_usd"] += r.get("cost_actual_usd", 0)
        models[m]["records"] += 1

    for m in models:
        models[m]["cost_usd"] = round(models[m]["cost_usd"], 6)
    return models


def _get_date_range(records: list[dict]) -> dict:
    """Get date range of records."""
    import datetime as _dt
    dates = []
    for r in records:
        ts = r.get("ts", "")
        if not ts:
            continue
        if "-" in ts and len(ts) >= 10:
            dates.append(ts[:10])
        else:
            try:
                dates.append(_dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).strftime("%Y-%m-%d"))
            except (ValueError, OSError) as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    if not dates:
        return {"start": "", "end": "", "days": 0}
    dates = sorted(set(dates))
    try:
        d1 = _dt.datetime.fromisoformat(dates[0])
        d2 = _dt.datetime.fromisoformat(dates[-1])
        days = (d2 - d1).days + 1
    except Exception:
        days = 0
    return {"start": dates[0], "end": dates[-1], "days": days}


# ── GET /api/token_sprints/import — Force re-import existing logs ────────────
@app.post("/api/token_sprints/import")
async def api_token_sprints_import(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    try:
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
        from forge_agents.token_sprint_tracker import import_existing_logs
        count = import_existing_logs()
        return JSONResponse({"imported": count})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/memory/status")
async def api_memory_status(x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    db_status = {"available": False}
    try:
        from forge_agents.forge_db import get_db
        db = get_db()
        if db is not None:
            try:
                db_status = db.health()
                db_status["available"] = True
            except Exception as e:
                db_status = {"error": str(e), "available": False}
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    sqlite_db = FORGE_ROOT / "04_GRAPHIFY" / "forge_checkpoints.db"
    turbovec_file = FORGE_ROOT / ".nexus" / "forge_state.json"
    gitnexus_db = FORGE_ROOT / ".gitnexus"

    # Evaluation plus precise des couches memoire
    l0_state = {"status": "down"}
    if db_status.get("available") and db_status.get("redis") == "up":
        l0_state = {"status": "up"}

    l2_state = {"status": "down"}
    if db_status.get("available") and db_status.get("postgres") == "up":
        l2_state = {"status": "up"}
    elif sqlite_db.exists():
        l2_state = {"status": "fallback_sqlite"}

    l3_state = {"available": False, "engine": "simhash"}
    if db_status.get("available") and db_status.get("postgres") == "up":
        l3_state = {"available": True, "engine": "pgvector"}
    elif turbovec_file.exists():
        l3_state = {"available": True, "engine": "simhash_fallback"}

    return JSONResponse({
        "l0_redis": l0_state,
        "l2_postgres": l2_state,
        "l3_semantic": l3_state,
        "l4_gitnexus": {"indexed": gitnexus_db.exists(), "path": str(gitnexus_db)},
    })


# ── GET /api/memory/search ────────────────────────────────────────────────────
@app.get("/api/memory/search")
async def api_memory_search(q: str = "", table: str = "", k: int = 8, x_forge_token: Optional[str] = Header(default=None)):
    _check_auth(x_forge_token)
    results = []
    
    # 1. Tenter de chercher via la base sémantique principale si elle est up
    try:
        from forge_agents.forge_db import get_db
        db = get_db()
        if db is not None:
            tables = [table] if table else ["episodes", "rag_docs", "gitnexus_symbols"]
            for t in tables:
                try:
                    for row in db.deep_semantic(t, q, k=k):
                        results.append({"table": t, "row": row, "type": "semantic"})
                except Exception:
                    continue
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # 2. Dégradation gracieuse : Recherche textuelle dans les fichiers locaux et la base SQLite LangGraph
    ql = q.lower()
    
    # Recherche dans les checkpoints SQLite de LangGraph
    sqlite_db = FORGE_ROOT / "04_GRAPHIFY" / "forge_checkpoints.db"
    if sqlite_db.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(sqlite_db))
            cursor = conn.execute(
                "SELECT thread_id, checkpoint_id, created_at, checkpoint FROM checkpoints WHERE checkpoint LIKE ? LIMIT ?",
                (f"%{q}%", k)
            )
            for row in cursor.fetchall():
                try:
                    cp_data = json.loads(row[3])
                    # Filtrer les infos utiles
                    results.append({
                        "table": "checkpoints (SQLite)",
                        "row": {
                            "thread_id": row[0],
                            "checkpoint_id": row[1],
                            "created_at": row[2],
                            "current_task": cp_data.get("current_task", ""),
                            "active_node": cp_data.get("current_node", "")
                        },
                        "type": "fallback_db"
                    })
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
            conn.close()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Recherche dans turbovec (forge_state.json)
    turbovec_file = FORGE_ROOT / ".nexus" / "forge_state.json"
    if turbovec_file.exists():
        try:
            meta = json.loads(turbovec_file.read_text(encoding="utf-8")).get("meta", {})
            found_count = 0
            for kid, entry in meta.items():
                if found_count >= k:
                    break
                text = entry.get("text", "")
                agent = entry.get("agent", "")
                if ql in text.lower() or ql in agent.lower():
                    results.append({
                        "table": "turbovec (L3 context)",
                        "row": {
                            "id": kid,
                            "agent": agent,
                            "text": text,
                            "score": entry.get("score"),
                            "cycle": entry.get("cycle")
                        },
                        "type": "fallback_json"
                    })
                    found_count += 1
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Recherche dans les findings confirmés (fichiers JSON)
    confirmed_dir = FORGE_ROOT / "06_FINDINGS" / "confirmed"
    if confirmed_dir.exists():
        try:
            found_count = 0
            for f in confirmed_dir.glob("*.json"):
                if found_count >= k:
                    break
                data = json.loads(f.read_text(encoding="utf-8"))
                title = data.get("title", "")
                desc = data.get("desc", "")
                if ql in title.lower() or ql in desc.lower():
                    results.append({
                        "table": "findings (L2 facts)",
                        "row": {
                            "file": f.name,
                            "title": title,
                            "agent": data.get("agent", ""),
                            "status": data.get("status", "")
                        },
                        "type": "fallback_file"
                    })
                    found_count += 1
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    return JSONResponse({"query": q, "results": results[:k * 3]})


# ── WebSocket /ws/chat ────────────────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Recevoir le message user
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"message": raw, "session_id": "default"}

            message    = payload.get("message", "").strip()
            session_id = payload.get("session_id", "ws_session")
            token      = payload.get("token", "")

            # Même politique que `_check_auth` : fermé par défaut. Sans secret réel et
            # sans opt-in explicite, le WebSocket refuse — il servait tout en clair avant.
            if WEB_SECRET and WEB_SECRET != DEV_SECRET:
                if token != WEB_SECRET:
                    await websocket.send_json({"type": "error", "content": "Token invalide"})
                    continue
            elif not ALLOW_INSECURE:
                await websocket.send_json({
                    "type": "error",
                    "content": "WEB_SECRET non configuré — accès refusé (ou FORGE_WEB_ALLOW_INSECURE=1)",
                })
                continue

            if not message:
                continue

            # ── GitHub link interceptor (non-blocking) ───────────────────
            if "github.com" in message:
                try:
                    import sys
                    sys.path.insert(0, str(FORGE_ROOT / "scripts"))
                    from github_indexer import index_from_chat_message
                    asyncio.create_task(index_from_chat_message(message))
                except Exception:
                    pass  # non-blocking

            # Lancer la Forge dans un thread (non-bloquant)
            await _run_forge_stream(websocket, message, session_id)

    except WebSocketDisconnect as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


async def _run_forge_stream(websocket: WebSocket, task: str, session_id: str):
    """
    Lance ForgeRunner dans un thread et stream les événements via WebSocket.
    Utilise une queue thread-safe pour passer les events du thread → async.
    """
    event_queue: queue.Queue = queue.Queue()

    def _forge_thread():
        """Exécute la Forge et pousse les events dans la queue."""
        try:
            # Import ici pour éviter les problèmes de path au démarrage
            from forge_agents.forge_graph import ForgeRunner
            from forge_agents.forge_state import initial_state

            runner = ForgeRunner(session_id=session_id, use_sqlite=True)

            # Monkey-patch le caveman log pour intercepter en temps réel
            original_stream = runner.graph.stream

            event_queue.put({"type": "start", "task": task, "session_id": session_id})

            # Hook sur chaque step du graph
            state = initial_state(task, session_id=session_id)

            for step in runner.graph.stream(state, config=runner.config):
                node_name  = list(step.keys())[0]
                node_state = step.get(node_name, {})

                if not node_state:
                    continue

                # Caveman log → events
                for msg in node_state.get("caveman_log", []):
                    if isinstance(msg, dict):
                        event_queue.put({
                            "type": "caveman",
                            "sender": msg.get("sender", "?"),
                            "verb": msg.get("verb", "?"),
                            "object": msg.get("object", ""),
                            "meta": msg.get("metadata", {}),
                        })

                # Jury verdict
                verdict = node_state.get("jury_verdict")
                if verdict and isinstance(verdict, dict):
                    event_queue.put({
                        "type": "jury",
                        "decision": verdict.get("decision", "?"),
                        "consensus": verdict.get("consensus", 0),
                        "winner": verdict.get("winner"),
                        "fallback": verdict.get("fallback_used", False),
                    })

                # Output agent
                output = node_state.get("agent_output", "")
                if output:
                    event_queue.put({
                        "type": "output",
                        "node": node_name,
                        "content": output[:1000],  # tronqué pour le stream
                    })

                # Token tracking
                token_estimate = node_state.get("token_estimate", {})
                token_actual   = node_state.get("token_actual", {})
                if token_estimate:
                    event_queue.put({"type": "token_estimate", "data": token_estimate})
                if token_actual:
                    event_queue.put({"type": "token_actual", "data": token_actual})

                # Token analysis (post-mortem)
                analysis = node_state.get("token_analysis", {})
                if analysis:
                    event_queue.put({"type": "token_analysis", "data": analysis})

                # Token LIVE — total courant accumulé par le tracker (singleton),
                # poussé à CHAQUE step → compteur qui monte en temps réel (pas juste
                # devis-début + réel-fin). ponytail: la donnée existe déjà, on l'émet.
                try:
                    from forge_agents.token_tracker import get_tracker
                    live = {}
                    for model, data in get_tracker().actuals_by_model().items():
                        k = model.value if hasattr(model, "value") else str(model)
                        live[k] = data
                    if live:
                        event_queue.put({"type": "token_live", "data": live})
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

                # KB hits
                findings = node_state.get("findings", [])
                if findings:
                    event_queue.put({"type": "findings_count", "count": len(findings)})

            event_queue.put({"type": "done", "task": task})

        except Exception as e:
            event_queue.put({"type": "error", "content": str(e), "trace": traceback.format_exc()})
        finally:
            event_queue.put(None)  # sentinelle de fin

    # Lancer le thread Forge
    thread = threading.Thread(target=_forge_thread, daemon=True)
    thread.start()

    # Stream les events vers le WebSocket
    while True:
        try:
            # Poll la queue toutes les 50ms (non-bloquant pour asyncio)
            event = await asyncio.get_event_loop().run_in_executor(
                None, lambda: event_queue.get(timeout=60)
            )
        except queue.Empty:
            await websocket.send_json({"type": "ping"})
            continue

        if event is None:
            break  # fin du stream

        try:
            await websocket.send_json(event)
        except Exception:
            break  # client déconnecté

    thread.join(timeout=5)


# ── WebSocket /ws/telemetry (Neural Map real-time) ─────────────────────────
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    # Flux de télémétrie interne : même politique que le reste (fermé par défaut).
    # Token passé en query string : `ws://…/ws/telemetry?token=<WEB_SECRET>`.
    _tok = websocket.query_params.get("token", "")
    if WEB_SECRET and WEB_SECRET != DEV_SECRET:
        if _tok != WEB_SECRET:
            await websocket.close(code=1008)
            return
    elif not ALLOW_INSECURE:
        await websocket.close(code=1008)
        return
    await telemetry.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        telemetry.disconnect(websocket)


# ── POST /api/broadcast/event (HTTP fallback from CLI) ─────────────────────
@app.post("/api/broadcast/event")
async def api_broadcast_event(request: Request,
                              x_forge_token: Optional[str] = Header(default=None)):
    """Receive event from CLI via HTTP and broadcast to all WS clients.

    Sans garde, n'importe qui pouvait pousser un JSON arbitraire vers TOUS les
    dashboards connectés — un canal d'injection non authentifié.
    """
    _check_auth(x_forge_token)
    try:
        payload = await request.json()
        await telemetry.broadcast(payload)
        return {"status": "ok", "clients": len(telemetry.active_connections)}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)


# ── Vault Explorer (Obsidian vault) ───────────────────────────────────────
VAULT_DIR = FORGE_ROOT / "vault"

@app.get("/api/vault/files")
async def api_vault_files(x_forge_token: Optional[str] = Header(default=None)):
    """List all Markdown files in the Obsidian vault as a tree."""
    _check_auth(x_forge_token)
    if not VAULT_DIR.exists():
        return {"tree": {}, "count": 0}

    tree = {}
    for f in sorted(VAULT_DIR.rglob("*.md")):
        rel = f.relative_to(VAULT_DIR)
        parts = list(rel.parts)
        current = tree
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = None  # leaf = file

    # Also collect flat list for search
    files = []
    for f in sorted(VAULT_DIR.rglob("*.md")):
        rel = f.relative_to(VAULT_DIR)
        files.append(str(rel))
    
    return {"tree": tree, "files": files, "count": len(files)}


@app.get("/api/vault/file/{path:path}")
async def api_vault_file(path: str, x_forge_token: Optional[str] = Header(default=None)):
    """Read a Markdown file from the vault.

    La route DÉCLARAIT `x_forge_token` sans jamais le vérifier : elle paraissait
    authentifiée et servait en réalité n'importe quel fichier du vault à un anonyme.
    """
    _check_auth(x_forge_token)
    file_path = VAULT_DIR / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not str(file_path.resolve()).startswith(str(VAULT_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    content = file_path.read_text(encoding="utf-8")
    return {"path": path, "content": content, "size": len(content)}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"""
********************************************************
*          AGENTIC OS - Web Interface                  *
*  URL   : http://localhost:{PORT}                      *
*  Auth  : WEB_SECRET dans .env                        *
*  Forge : {FORGE_ROOT}  *
********************************************************
""")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )
