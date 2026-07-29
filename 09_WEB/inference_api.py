"""inference_api.py — Façade produit **/v1** (contrat versionné) au-dessus du moteur Forge.

Principe (cf. PLAN_PLATEFORME_INFERENCE.md, Annexe A) : `/v1` est une façade MINCE,
stable et versionnée. Elle **n'édite aucun symbole existant** de `server.py` — elle est
montée par `app.include_router(v1_router)`. Elle réutilise :

  - l'auth/tenant déjà en place (`forge_identity.resolve_token` + le `tenant_middleware`
    global de server.py qui pose le contexte pour toute la durée de la requête HTTP) ;
  - le moteur `ForgeRunner` (`forge_graph`) + `initial_state` (`forge_state`) ;
  - la taxonomie d'events de `_run_forge_stream`, **NORMALISÉE** en enveloppe versionnée
    `{v, run_id, seq, ts, type, data}` (Annexe D).

Streaming découplé (Annexe A.1) : `POST /v1/agents/run` rend un `run_id` immédiatement (202),
le thread Forge tourne en fond et pousse ses events dans un `RunRegistry` **en mémoire** ;
`WS /v1/stream?run_id=` draine ce buffer (avec replay `since_seq`). Pas de dépendance dure à
Redis. Décision verrouillée « 1 process / tenant » → le registre en mémoire suffit.

Propagation tenant : le contexte `contextvars` ne passe PAS aux threads. On capture donc le
tenant à la requête et on le **repose** (`set_tenant`) au démarrage du thread Forge, pour que
`forge_store` écrive dans le bon espace. (Pré-résout une partie du gap Phase 3.)
"""
from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["inference"])

# ── Résolution du tenant (indépendante de server.py pour éviter l'import circulaire) ──
_SINGLE = os.environ.get("FORGE_SINGLE_TENANT", "").strip() or None


def _resolve_tenant(token: Optional[str]) -> Optional[str]:
    """Jeton Bearer/`token` → tenant. Repli `FORGE_SINGLE_TENANT` en local (opt-in insécurité)."""
    if token:
        try:
            from forge_agents.forge_identity import resolve_token
            t = resolve_token(token)
            if t:
                return t
        except Exception:
            pass
    return _SINGLE


def _token_from(request: Optional[Request] = None,
                authorization: Optional[str] = None,
                x_forge_token: Optional[str] = None,
                ws: Optional[WebSocket] = None) -> Optional[str]:
    """Extrait le jeton dans l'ordre : Bearer > X-Forge-Token > query `token`."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_forge_token:
        return x_forge_token
    if ws is not None:
        return ws.query_params.get("token")
    if request is not None:
        return request.query_params.get("token")
    return None


def _require_tenant(authorization: Optional[str], x_forge_token: Optional[str],
                    request: Optional[Request] = None) -> str:
    """Résout le tenant ou lève 401. Fermé par défaut (sauf FORGE_SINGLE_TENANT)."""
    tenant = _resolve_tenant(_token_from(request=request, authorization=authorization,
                                         x_forge_token=x_forge_token))
    if not tenant:
        raise HTTPException(status_code=401, detail="token invalide ou absent")
    return tenant


# ── Enveloppe d'event + normalisation (Annexe D) ──────────────────────────────
def _envelope(run: "Run", ev_type: str, data: dict) -> dict:
    run.seq += 1
    return {"v": 1, "run_id": run.run_id, "seq": run.seq,
            "ts": time.time(), "type": ev_type, "data": data}


def _normalize(raw: dict) -> tuple[str, dict]:
    """Event moteur brut → (type /v1, data). Le contrat /v1 est le nôtre, on le stabilise."""
    t = raw.get("type")
    if t == "start":
        return "run.started", {"task": raw.get("task"), "session_id": raw.get("session_id")}
    if t == "caveman":
        return "agent.thinking", {"agent": raw.get("sender"),
                                  "delta": f"{raw.get('verb','')} {raw.get('object','')}".strip()}
    if t == "jury":
        return "jury.verdict", {k: raw.get(k) for k in ("decision", "consensus", "winner", "fallback")}
    if t == "output":
        return "agent.output", {"node": raw.get("node"), "content": raw.get("content")}
    if t in ("token_estimate", "token_actual", "token_live"):
        return "budget.update", {"phase": t, "data": raw.get("data", {})}
    if t == "token_analysis":
        return "budget.postmortem", {"data": raw.get("data", {})}
    if t == "findings_count":
        return "graph.update", {"findings": raw.get("count", 0)}
    if t == "done":
        return "run.done", {"task": raw.get("task")}
    if t == "error":
        return "run.error", {"error": raw.get("content"), "trace": raw.get("trace")}
    return f"engine.{t}", {k: v for k, v in raw.items() if k != "type"}


# ── Registre des runs (en mémoire, scopé tenant) ──────────────────────────────
@dataclass
class Run:
    run_id: str
    tenant: str
    task: str
    agent: Optional[str] = None
    status: str = "queued"          # queued → running → done | error | cancelled
    seq: int = 0
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    ended: Optional[float] = None
    result: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    events: list = field(default_factory=list)   # buffer append-only (replay + historique)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cancel: threading.Event = field(default_factory=threading.Event)

    def push(self, ev_type: str, data: dict) -> None:
        with self._lock:
            self.events.append(_envelope(self, ev_type, data))

    def snapshot(self) -> dict:
        return {"run_id": self.run_id, "task": self.task, "agent": self.agent,
                "status": self.status,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost": self.cost,
                "created": self.created, "started": self.started, "ended": self.ended,
                "result": self.result}


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(self, tenant: str, task: str, agent: Optional[str]) -> Run:
        run = Run(run_id=f"run_{uuid.uuid4().hex[:12]}", tenant=tenant, task=task, agent=agent)
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def get(self, run_id: str, tenant: str) -> Optional[Run]:
        run = self._runs.get(run_id)
        if run is None or run.tenant != tenant:   # isolation : jamais le run d'un autre tenant
            return None
        return run

    def list(self, tenant: str, limit: int = 50, status: Optional[str] = None) -> list[dict]:
        out = [r.snapshot() for r in self._runs.values()
               if r.tenant == tenant and (status is None or r.status == status)]
        out.sort(key=lambda r: r["created"], reverse=True)
        return out[:limit]


REGISTRY = RunRegistry()


# ── Exécution moteur (thread) ─────────────────────────────────────────────────
def _run_engine(run: Run) -> None:
    """Lance ForgeRunner dans ce thread, normalise chaque event dans le buffer du run.

    On repose le tenant ici (les contextvars ne se propagent pas au thread), sinon
    `forge_store` refuserait d'écrire (fermé par défaut). ATTENTION : le vrai travail
    moteur tourne dans le thread INTERNE `_thread` ci-dessous, qui démarre lui aussi avec
    un contexte vide — c'est là, et pas seulement ici, qu'il faut reposer le tenant
    (sinon `forge_store`/`forge_graph` écriraient hors de l'espace du client).
    """
    try:
        from forge_agents.forge_tenant import set_tenant
        set_tenant(run.tenant)
    except Exception:
        pass  # dégradation : en mono-tenant FORGE_SINGLE_TENANT résout depuis l'env

    q: queue.Queue = queue.Queue()

    def _thread() -> None:
        # Le worker est un thread distinct → contextvars non héritées. On rétablit le
        # tenant du run pour toute la durée du stream moteur (cf. forge_tenant.propagate).
        try:
            from forge_agents.forge_tenant import tenant_scope
            _scope = tenant_scope(run.tenant)
            _scope.__enter__()
        except Exception:
            _scope = None
        try:
            from forge_agents.forge_graph import ForgeRunner
            from forge_agents.forge_state import initial_state
            runner = ForgeRunner(session_id=run.run_id, use_sqlite=True)
            q.put({"type": "start", "task": run.task, "session_id": run.run_id})
            state = initial_state(run.task, session_id=run.run_id)
            for step in runner.graph.stream(state, config=runner.config):
                if run._cancel.is_set():
                    q.put({"type": "error", "content": "cancelled"})
                    break
                node_name = list(step.keys())[0]
                node_state = step.get(node_name, {}) or {}
                for msg in node_state.get("caveman_log", []):
                    if isinstance(msg, dict):
                        q.put({"type": "caveman", **{k: msg.get(k) for k in
                               ("sender", "verb", "object")}})
                v = node_state.get("jury_verdict")
                if isinstance(v, dict):
                    q.put({"type": "jury", "decision": v.get("decision"),
                           "consensus": v.get("consensus"), "winner": v.get("winner"),
                           "fallback": v.get("fallback_used", False)})
                out = node_state.get("agent_output", "")
                if out:
                    run.result = out
                    q.put({"type": "output", "node": node_name, "content": out[:1000]})
                for key in ("token_estimate", "token_actual", "token_analysis"):
                    if node_state.get(key):
                        q.put({"type": key, "data": node_state[key]})
            q.put({"type": "done", "task": run.task})
        except Exception as e:
            q.put({"type": "error", "content": str(e), "trace": traceback.format_exc()})
        finally:
            if _scope is not None:
                try:
                    _scope.__exit__(None, None, None)
                except Exception:
                    pass
            q.put(None)

    run.status = "running"
    run.started = time.time()
    worker = threading.Thread(target=_thread, daemon=True)
    worker.start()

    while True:
        try:
            raw = q.get(timeout=120)
        except queue.Empty:
            run.push("heartbeat", {})
            continue
        if raw is None:
            break
        ev_type, data = _normalize(raw)
        run.push(ev_type, data)
        if ev_type == "run.done":
            run.status = "done"
        elif ev_type == "run.error":
            run.status = "cancelled" if run._cancel.is_set() else "error"
    run.ended = time.time()
    worker.join(timeout=5)


# ── A.1 — Cœur inférence ──────────────────────────────────────────────────────
class RunReq(BaseModel):
    task: str
    agent: Optional[str] = None
    budget_tokens: Optional[int] = None
    mode: Optional[str] = None


@router.post("/agents/run", status_code=202)
async def run_agent(req: RunReq, authorization: Optional[str] = Header(default=None),
                    x_forge_token: Optional[str] = Header(default=None)):
    tenant = _require_tenant(authorization, x_forge_token)
    # Enforce quota AVANT d'exécuter (429 propre) — best-effort si module absent.
    try:
        from forge_agents.forge_quota import consume, QuotaExceeded
        try:
            consume("requests", 1.0, enforce=True)
        except QuotaExceeded as qe:
            return JSONResponse(status_code=429, content={
                "error": "quota dépassé", "resource": getattr(qe, "resource", "requests"),
                "used": getattr(qe, "used", None), "limit": getattr(qe, "limit", None)})
    except HTTPException:
        raise
    except Exception:
        pass
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task vide")
    run = REGISTRY.create(tenant, req.task.strip(), req.agent)
    threading.Thread(target=_run_engine, args=(run,), daemon=True,
                     name=f"v1-run-{run.run_id}").start()
    return {"run_id": run.run_id, "status": run.status}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, authorization: Optional[str] = Header(default=None),
                  x_forge_token: Optional[str] = Header(default=None)):
    tenant = _require_tenant(authorization, x_forge_token)
    run = REGISTRY.get(run_id, tenant)
    if not run:
        raise HTTPException(status_code=404, detail="run introuvable")
    return run.snapshot()


@router.get("/runs")
async def list_runs(limit: int = 50, status: Optional[str] = None,
                    authorization: Optional[str] = Header(default=None),
                    x_forge_token: Optional[str] = Header(default=None)):
    tenant = _require_tenant(authorization, x_forge_token)
    return {"runs": REGISTRY.list(tenant, limit=limit, status=status)}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, authorization: Optional[str] = Header(default=None),
                     x_forge_token: Optional[str] = Header(default=None)):
    tenant = _require_tenant(authorization, x_forge_token)
    run = REGISTRY.get(run_id, tenant)
    if not run:
        raise HTTPException(status_code=404, detail="run introuvable")
    run._cancel.set()
    return {"run_id": run_id, "status": "cancelling"}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    """Draine le buffer d'un run (filtré tenant + run_id), avec replay `since_seq`."""
    await ws.accept()
    tenant = _resolve_tenant(_token_from(ws=ws))
    run_id = ws.query_params.get("run_id", "")
    if not tenant:
        await ws.send_json({"type": "error", "content": "token invalide"})
        await ws.close(code=1008)
        return
    run = REGISTRY.get(run_id, tenant)
    if not run:
        await ws.send_json({"type": "error", "content": "run introuvable"})
        await ws.close(code=1008)
        return
    try:
        since = int(ws.query_params.get("since_seq", "0"))
    except ValueError:
        since = 0
    sent = since
    try:
        while True:
            with run._lock:
                pending = [e for e in run.events if e["seq"] > sent]
            for ev in pending:
                await ws.send_json(ev)
                sent = ev["seq"]
            if run.status in ("done", "error", "cancelled") and not pending:
                break
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return
    except Exception:
        return


# ── A.2 / A.3 — Lecture (façades sur l'existant, dégradation gracieuse) ────────
@router.get("/agents")
async def agents(authorization: Optional[str] = Header(default=None),
                 x_forge_token: Optional[str] = Header(default=None)):
    _require_tenant(authorization, x_forge_token)
    # Source stable : chaque agent = un sous-dossier de 02_AGENTS/.
    try:
        from pathlib import Path
        agents_dir = Path(__file__).resolve().parent.parent / "02_AGENTS"
        names = sorted(p.name for p in agents_dir.iterdir()
                       if p.is_dir() and not p.name.startswith("."))
        return {"agents": [{"name": n, "status": "idle"} for n in names]}
    except Exception:
        return {"agents": [], "note": "registre agents indisponible"}


@router.get("/metrics")
async def metrics(authorization: Optional[str] = Header(default=None),
                  x_forge_token: Optional[str] = Header(default=None)):
    _require_tenant(authorization, x_forge_token)
    data = {"tokens_in": 0, "tokens_out": 0, "cost": 0.0, "savings_pct": 0.0, "agents_active": 0}
    try:
        from forge_agents.forge_metrics import summary
        s = summary() or {}
        data.update({k: s[k] for k in data if k in s})
    except Exception:
        pass
    return data


@router.get("/budget/mimo")
async def budget_mimo(authorization: Optional[str] = Header(default=None),
                      x_forge_token: Optional[str] = Header(default=None)):
    """Solde du plan d'abonnement MiMo — axe FOURNISSEUR, distinct de `/quota`.

    `/quota` répond « combien CE tenant a consommé sur l'heure » ; ici on répond
    « combien il reste sur notre abonnement ce mois-ci ». Depuis qu'il n'existe plus
    de tier gratuit, c'est le seul chiffre qui dit ce que coûte réellement un offload.

    Ouvert au jeton tenant, comme `/metrics` (qui expose déjà un coût). Le jour où la
    plateforme sert des clients externes, cette route passe côté `_require_admin` :
    un solde d'abonnement est une donnée d'exploitation, pas une donnée client.
    """
    _require_tenant(authorization, x_forge_token)
    try:
        from forge_agents.mimo_budget import report
        return report()
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": f"budget MiMo indisponible: {e}"})


@router.get("/quota")
async def quota(authorization: Optional[str] = Header(default=None),
                x_forge_token: Optional[str] = Header(default=None)):
    _require_tenant(authorization, x_forge_token)
    try:
        from forge_agents.forge_quota import report
        return report()
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": f"quota indisponible: {e}"})


# Types de nœuds réels du graphe (cf. graph_db.NODE_TABLES) + la clé qui les identifie.
_GRAPH_LABELS = (
    ("Agent", "name"), ("Project", "name"), ("Concept", "name"),
    ("MemoryNode", "id"), ("Decision", "adr_id"), ("Repository", "id"),
)

# Sous-groupe (niveau 2 "régions" de la neural map) : par type, LA colonne déjà stockée qui
# regroupe fonctionnellement les nœuds. Pour Agent c'est `role` (= role_tag, 9 valeurs, posé par
# knowledge_curator._sync_agent). Sert au sous-clustering / au volet de tri côté console.
_SUBGROUP_FIELD = {
    "Agent": "role", "Project": "status", "Concept": "category",
    "MemoryNode": "memory_type", "Decision": "status", "Repository": "language",
}


# Plafond dur de sécurité : le graphe de la Forge fait plusieurs milliers de nœuds et la
# neural map (canvas) les affiche tous. On garde néanmoins un maximum pour ne pas renvoyer
# un JSON illimité ; si on l'atteint, on le SIGNALE (`truncated`) — jamais de coupe muette.
_GRAPH_MAX = 20000


@router.get("/graph")
async def graph(limit: int = 8000,
                type: Optional[str] = None,
                q: Optional[str] = None,
                focus: Optional[str] = None,
                authorization: Optional[str] = Header(default=None),
                x_forge_token: Optional[str] = Header(default=None)):
    """Graphe pour la neural map : nœuds TYPÉS (type + key) + arêtes TYPÉES + stats.

    Query builder (côté serveur, pour tenir plusieurs milliers de nœuds) :
      - `type`  : ne renvoyer qu'un type de nœud (Agent, Project, …) ;
      - `q`     : sous-chaîne (insensible à la casse) filtrant sur la `key` ;
      - `focus` : voisinage d'une entité (ses arêtes + les deux extrémités) — pivot/expand ;
      - `limit` : plafond par type (borné à _GRAPH_MAX).
    Chaque nœud porte son `type` (label) et une `key` canonique. `truncated=True` si un type
    a atteint le plafond (rien n'est coupé en silence). Dégrade proprement si Kuzu est absent.
    """
    _require_tenant(authorization, x_forge_token)
    per_label = max(1, min(int(limit or 8000), _GRAPH_MAX))
    ql = (q or "").strip().lower()
    want_type = (type or "").strip() or None
    try:
        from forge_agents.graph_db import get_graph_db
        db = get_graph_db()

        stats = {}
        try:
            stats = db.count_nodes()
        except Exception:
            pass

        # Pivot : voisinage d'une entité — on part des arêtes qui la touchent.
        if focus:
            edges = []
            try:
                edges = db.get_edges(focus=focus, limit=per_label)
            except Exception:
                pass
            keys = {focus} | {e["source"] for e in edges} | {e["target"] for e in edges}
            nodes = [{"key": k, "type": _type_of(edges, k)} for k in keys]
            return {"nodes": nodes, "edges": edges, "stats": stats, "focus": focus}

        nodes = []
        truncated = False
        for label, pk in _GRAPH_LABELS:
            if want_type and label != want_type:
                continue
            try:
                rows = db.get_all_nodes(label, limit=per_label)
                if len(rows) >= per_label:
                    truncated = True
                for raw in rows:
                    key = raw.get(pk) or raw.get("name") or raw.get("id") or ""
                    key = str(key)
                    if ql and ql not in key.lower():
                        continue
                    grp = str(raw.get(_SUBGROUP_FIELD.get(label, ""), "") or "")
                    nodes.append({**raw, "type": label, "key": key, "group": grp})
            except Exception:
                pass

        keyset = {n["key"] for n in nodes}
        edges = []
        try:
            # On ne garde que les arêtes dont les DEUX extrémités sont dans l'ensemble affiché.
            edges = [e for e in db.get_edges(limit=per_label * 4)
                     if e["source"] in keyset and e["target"] in keyset]
        except Exception:
            pass
        return {"nodes": nodes, "edges": edges, "stats": stats, "truncated": truncated}
    except Exception:
        return {"nodes": [], "edges": [], "stats": {}, "note": "graphe indisponible"}


def _type_of(edges: list, key: str) -> str:
    """Type d'un nœud déduit des arêtes qui le touchent (pour le mode focus)."""
    for e in edges:
        if e.get("source") == key and e.get("source_type"):
            return e["source_type"]
        if e.get("target") == key and e.get("target_type"):
            return e["target_type"]
    return ""


#: `kanban.py` range ses tâches à plat avec un `status` ; la console affiche des colonnes.
#: La traduction se fait ICI, une fois, plutôt que dans chaque vue qui consomme le board.
_BOARD_COLUMN_OF = {
    "pending": "todo", "in_progress": "doing", "done": "done", "blocked": "blocked",
}
_BOARD_COLUMNS = ("todo", "doing", "done", "blocked")


def _board_global_fallback_allowed() -> bool:
    """Le board GLOBAL peut-il être servi quand le tenant n'en a pas ?

    Le board du sprint de la Forge vit au chemin GLOBAL (`05_STATE/kanban/`) parce que le
    CLI `kanban.py` tourne sans tenant en contexte, alors que l'API en a toujours un et lit
    `05_STATE/tenants/<id>/kanban/`. Les deux ne se voient pas — d'où un board plein côté
    CLI et vide côté console.

    Servir le board GLOBAL à un tenant serait une FUITE dès qu'il y a plusieurs clients :
    c'est le board de l'opérateur. On ne l'autorise donc que quand il n'y a personne à qui
    fuiter — une seule identité enregistrée — ou sur opt-in explicite de l'opérateur. La
    garde se referme d'elle-même le jour où un second tenant est créé.
    """
    if os.environ.get("FORGE_BOARD_GLOBAL_FALLBACK", "").strip() in ("1", "true", "yes"):
        return True
    try:
        from forge_agents.forge_identity import list_tenants
        return len(list_tenants()) <= 1
    except Exception:
        return False


@router.get("/orchestrator/board")
async def board(authorization: Optional[str] = Header(default=None),
                x_forge_token: Optional[str] = Header(default=None)):
    """Board kanban dans la forme que la console consomme, et **d'où il vient**.

    L'ancienne version renvoyait `kanban.load()` brut — `{tasks:[…]}` — alors que la
    console attend `{columns:{…}}` : elle n'affichait donc rien, sans erreur. Ici on
    traduit, et on expose `scope` (`tenant` | `global`) parce qu'un board qui n'est pas
    celui du tenant courant doit se signaler plutôt que de passer pour le sien.
    """
    _require_tenant(authorization, x_forge_token)
    try:
        from forge_dispatch import kanban
        raw = kanban.load() or {}
        scope = "tenant"
        if not raw.get("tasks") and _board_global_fallback_allowed():
            # Chemin GLOBAL historique — le même repli que `forge_store.state_path()`
            # applique quand aucun tenant n'est en contexte, écrit ici en clair.
            from forge_agents.forge_store import FORGE_ROOT as _STATE_ROOT
            gpath = _STATE_ROOT / "05_STATE" / "kanban" / "board.json"
            if gpath.exists():
                import json as _json
                raw = _json.loads(gpath.read_text(encoding="utf-8-sig"))
                scope = "global"

        columns: dict[str, list] = {c: [] for c in _BOARD_COLUMNS}
        for t in raw.get("tasks", []):
            # Statut inconnu → visible dans `todo` plutôt qu'escamoté : une tâche qu'on
            # ne sait pas classer doit sauter aux yeux, pas disparaître du board.
            columns[_BOARD_COLUMN_OF.get(str(t.get("status", "")), "todo")].append(t)

        return {
            "columns": columns,
            "counts": {c: len(v) for c, v in columns.items()},
            "scope": scope,
            "parent_task": raw.get("parent_task", ""),
            "updated": raw.get("updated"),
        }
    except Exception as e:
        return {"columns": {c: [] for c in _BOARD_COLUMNS},
                "counts": {c: 0 for c in _BOARD_COLUMNS},
                "scope": "tenant", "note": f"board indisponible: {e}"}


@router.get("/backlog")
async def backlog(authorization: str = Header(default=None),
                  x_forge_token: Optional[str] = Header(default=None)):
    """Backlog RPG complet : tâches, résumé, chemin critique, épics."""
    _require_tenant(authorization, x_forge_token)
    try:
        from forge_agents.forge_backlog import get_backlog
        bl = get_backlog()
        tasks = bl.all()
        cp = bl.critical_path(remaining=True)
        return {
            "summary": bl.validate(),
            "epic_summary": bl.epic_summary(),
            "critical_path": cp,
            "tasks": tasks,
        }
    except Exception as e:
        return {"summary": {"tasks": 0, "cycles": [], "dangling_dependencies": [],
                            "ready": [], "by_state": {}},
                "epic_summary": {},
                "critical_path": {"duration_days": 0, "path": [], "critical": [],
                                  "schedule": {}},
                "tasks": [],
                "note": f"backlog indisponible: {e}"}


def _key_present(name: str) -> bool:
    """Une clé est-elle configurée ? Lit l'environnement ET le .env.

    Réutilise `forge_mimo._env` (déjà chargé de lire `.env`/`.env.local`) plutôt que
    de redémarrer une lecture de fichier ici. Repli sur l'environnement seul si le
    module n'est pas importable — un tableau de bord ne doit jamais casser l'API.
    """
    try:
        from forge_agents.forge_mimo import _env
        return bool(_env(name, "").strip())
    except Exception:
        return bool(os.environ.get(name, "").strip())


@router.get("/router/tiers")
async def router_tiers(authorization: Optional[str] = Header(default=None),
                       x_forge_token: Optional[str] = Header(default=None)):
    _require_tenant(authorization, x_forge_token)
    # État RÉEL du routeur, lu — pas déclaré.
    #
    # Cette liste était statique et annonçait MiMo/Gemini/Groq/Cerebras en `free`. Les quatre
    # étaient faux. Décision 2026-07-25 : **plus aucun tier gratuit** — les proxies et offres
    # gratuites se sont montrés trop instables. On repart sur du payant assumé.
    #
    #   Claude   abonnement (Claude Code) — raisonnement, orchestration, validation
    #   MiMo     payant : 17 €/mois pour 11 Md tokens, facturé par bloc de 1000 — volume
    #   Gemini   pas d'accès API sur l'abonnement AI Pro
    #   Groq     abandonné (instable)
    #   ds2api   abandonné (proxy instable)
    #   Cerebras retiré du code
    #
    # Conséquence à garder en tête : il n'existe plus de destination gratuite où décharger
    # du volume. Chaque token offloadé est facturé. Un tableau de bord qui affiche « gratuit »
    # sur l'un de ces tiers pousse à router du volume vers du payant sans le savoir.
    #
    # `wired` = le code du routeur contient encore une branche pour ce fournisseur ;
    # `available` = une clé est réellement configurée ici et maintenant. ds2api et Groq
    # restent `wired: True` tant que `forge_llm._call_paid_tier` n'a pas été purgé — dire
    # l'inverse masquerait du code encore capable de s'exécuter si une clé traînait.
    tiers = [
        {"name": "Claude", "kind": "subscription", "wired": True, "available": True,
         "detail": "CLI abonnement (claude -p), SDK en repli — raisonnement et orchestration"},
        {"name": "MiMo", "kind": "paid", "wired": True,
         "available": _key_present("MIMO_API_KEY"),
         "detail": "17 €/mois pour 11 Md tokens, facturé par bloc de 1000 — moteur de volume, "
                   "appelé par swarm/spine hors cascade forge_call"},
        {"name": "ds2api", "kind": "removed", "wired": True,
         "available": _key_present("DS2API_KEY"),
         "detail": "abandonné — proxy trop instable ; branche encore présente dans forge_llm"},
        {"name": "Groq", "kind": "removed", "wired": True,
         "available": _key_present("GROQ_API_KEY"),
         "detail": "abandonné — trop instable ; branche encore présente dans forge_llm"},
        {"name": "Gemini", "kind": "removed", "wired": False, "available": False,
         "detail": "accès API non inclus dans l'abonnement AI Pro"},
        {"name": "Cerebras", "kind": "removed", "wired": False, "available": False,
         "detail": "retiré du code"},
    ]
    return {
        "tiers": tiers,
        "default_policy": "Claude (abonnement) → MiMo (payant)",
        "free_tier_available": False,
    }


# ── A.4 — Admin : provisioning tenant (rôle opérateur, ≠ jeton tenant) ─────────
# Le jeton opérateur est SÉPARÉ du jeton tenant : un client ne doit jamais pouvoir
# créer/supprimer des espaces ni éditer des quotas. Fermé par défaut — sans
# FORGE_ADMIN_TOKEN défini, l'admin est refusé (403), sauf opt-in local explicite
# (FORGE_WEB_ALLOW_INSECURE=1), même politique d'insécurité assumée qu'ailleurs.
def _require_admin(authorization: Optional[str], x_forge_token: Optional[str]) -> None:
    admin_token = os.environ.get("FORGE_ADMIN_TOKEN", "").strip()
    presented = _token_from(authorization=authorization, x_forge_token=x_forge_token)
    if admin_token:
        import hmac
        if presented and hmac.compare_digest(presented, admin_token):
            return
        raise HTTPException(status_code=403, detail="jeton opérateur requis")
    # Pas de jeton opérateur configuré : autorisé uniquement en mode local insécurité.
    if os.environ.get("FORGE_WEB_ALLOW_INSECURE", "").strip() in ("1", "true", "yes"):
        return
    raise HTTPException(status_code=403,
                        detail="admin désactivé : définir FORGE_ADMIN_TOKEN (rôle opérateur)")


class TenantCreateReq(BaseModel):
    tenant_id: str
    label: Optional[str] = None
    limits: Optional[dict] = None          # {storage_bytes?, requests?, llm_tokens?}


class TokenActionReq(BaseModel):
    action: str                            # "issue" (rotation) | "revoke"


@router.post("/admin/tenants", status_code=201)
async def admin_create_tenant(req: TenantCreateReq,
                              authorization: Optional[str] = Header(default=None),
                              x_forge_token: Optional[str] = Header(default=None)):
    _require_admin(authorization, x_forge_token)
    from forge_agents.forge_identity import create_tenant
    from forge_agents.forge_tenant import TenantError
    try:
        token = create_tenant(req.tenant_id, label=req.label or "")
    except TenantError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # Limites optionnelles (hors espace tenant, non falsifiables).
    applied = None
    if req.limits:
        try:
            from forge_agents.forge_quota import set_limits
            applied = _limits_public(set_limits(req.tenant_id, **req.limits))
        except Exception as e:
            applied = {"error": f"limites non appliquées: {e}"}
    return {"tenant_id": req.tenant_id, "token": token, "limits": applied}


@router.post("/admin/tenants/{tenant_id}/tokens")
async def admin_tenant_tokens(tenant_id: str, req: TokenActionReq,
                              authorization: Optional[str] = Header(default=None),
                              x_forge_token: Optional[str] = Header(default=None)):
    _require_admin(authorization, x_forge_token)
    from forge_agents.forge_identity import rotate_token, revoke
    from forge_agents.forge_tenant import TenantError
    action = (req.action or "").lower()
    if action == "issue":
        try:
            return {"tenant_id": tenant_id, "token": rotate_token(tenant_id)}
        except TenantError as e:
            raise HTTPException(status_code=404, detail=str(e))
    if action == "revoke":
        ok = revoke(tenant_id)
        if not ok:
            raise HTTPException(status_code=404, detail="tenant inconnu")
        return {"tenant_id": tenant_id, "status": "revoked"}
    raise HTTPException(status_code=400, detail="action attendue: 'issue' ou 'revoke'")


@router.get("/admin/tenants")
async def admin_list_tenants(authorization: Optional[str] = Header(default=None),
                             x_forge_token: Optional[str] = Header(default=None)):
    _require_admin(authorization, x_forge_token)
    from forge_agents.forge_identity import list_tenants
    out = []
    for t in list_tenants():
        entry = dict(t)
        try:
            from forge_agents.forge_quota import limits_for
            entry["limits"] = _limits_public(limits_for(t["tenant"]))
        except Exception:
            entry["limits"] = None
        out.append(entry)
    return {"tenants": out}


def _limits_public(limits: Any) -> dict:
    """Limites → dict JSON (sans secret). Best-effort sur la dataclass `Limits`."""
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(limits):
            return asdict(limits)
    except Exception:
        pass
    return {k: getattr(limits, k) for k in ("storage_bytes", "requests", "llm_tokens")
            if hasattr(limits, k)}
