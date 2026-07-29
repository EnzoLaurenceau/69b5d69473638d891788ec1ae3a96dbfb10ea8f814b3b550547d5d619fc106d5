"""
dashboard_server.py — FastAPI server for Forge V6 Dashboard.

Start:
    uvicorn forge_agents.dashboard_server:app --port 7420 --reload
Or via run_forge.py:
    python run_forge.py --dashboard
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

FORGE_ROOT     = Path(__file__).parent.parent.parent
DASHBOARD_HTML = Path(__file__).parent / "forge_dashboard.html"
CHECKPOINT     = FORGE_ROOT / "05_STATE" / "checkpoint.json"
TOKEN_LOG_DIR  = FORGE_ROOT / "08_LOGS" / "tokens"

app = FastAPI(title="Forge V6 Dashboard", docs_url=None, redoc_url=None)

# ─── state readers ────────────────────────────────────────────────────────────

def _cp() -> dict:
    try:
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _last_token_session() -> dict:
    try:
        logs = sorted(TOKEN_LOG_DIR.glob("*.json"))
        return json.loads(logs[-1].read_text(encoding="utf-8")) if logs else {}
    except Exception:
        return {}

def _live() -> dict:
    cp   = _cp()
    tok  = _last_token_session()
    task = str(cp.get("current_task", ""))
    return {
        "active_node":      str(cp.get("current_node", cp.get("last_node", ""))),
        "current_task":     task[:80],
        "cycle":            cp.get("cycle", 0),
        "level":            cp.get("level", 1),
        "agent_name":       str(cp.get("dynamic_agent_name", "")),
        "status":           "running" if task else "idle",
        "token_estimate":   cp.get("token_estimate", {}),
        "token_actual":     cp.get("token_actual", {}),
        "efficiency_score": tok.get("efficiency_score", 0),
        "harness_grade":    cp.get("harness_grade", ""),
    }

# ─── graph topology (hardcoded mirror of forge_graph.py) ─────────────────────
# ponytail: importing build_forge_graph() cold is slow + needs DB. Static is fine —
# the topology almost never changes. If it does, update here.

_NODES = [
    {"id": "v6_init",      "label": "V6 Init",        "type": "init",     "layer": 0},
    {"id": "estimate",     "label": "Budget\nEst",     "type": "budget",   "layer": 1},
    {"id": "orchestrator", "label": "Orchestrator",    "type": "router",   "layer": 2},
    {"id": "dynamic",      "label": "Dynamic\nAgent",  "type": "agent",    "layer": 3},
    {"id": "zsl",          "label": "ZSL\nAnalysis",   "type": "analysis", "layer": 3},
    {"id": "v6_post",      "label": "Post\nExec",      "type": "meta",     "layer": 4},
    {"id": "neuro_sym",    "label": "Neuro Sym\nVerif","type": "verify",   "layer": 4},
    {"id": "auto_complex", "label": "Auto\nComplex",   "type": "meta",     "layer": 5},
    {"id": "anti_halluc",  "label": "Anti\nHalluc",    "type": "verify",   "layer": 5},
    {"id": "memory",       "label": "Memory\nPruner",  "type": "memory",   "layer": 6},
    {"id": "post_mortem",  "label": "Post\nMortem",    "type": "meta",     "layer": 6},
]
_EDGES = [
    {"source": "v6_init",      "target": "estimate",     "type": "straight"},
    {"source": "estimate",     "target": "orchestrator", "type": "straight"},
    {"source": "orchestrator", "target": "dynamic",      "type": "conditional"},
    {"source": "orchestrator", "target": "zsl",          "type": "conditional"},
    {"source": "zsl",          "target": "dynamic",      "type": "straight"},
    {"source": "dynamic",      "target": "v6_post",      "type": "straight"},
    {"source": "v6_post",      "target": "auto_complex", "type": "straight"},
    {"source": "auto_complex", "target": "orchestrator", "type": "loop"},
    {"source": "auto_complex", "target": "neuro_sym",    "type": "conditional"},
    {"source": "neuro_sym",    "target": "anti_halluc",  "type": "straight"},
    {"source": "anti_halluc",  "target": "memory",       "type": "straight"},
    {"source": "memory",       "target": "orchestrator", "type": "loop"},
    {"source": "memory",       "target": "post_mortem",  "type": "conditional"},
]

# ─── endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
async def serve_dashboard():
    try:
        html = DASHBOARD_HTML.read_text(encoding="utf-8")
    except Exception:
        html = "<h1>forge_dashboard.html not found</h1>"
    return HTMLResponse(html)


@app.get("/api/health")
async def api_health():
    cp = _cp()
    return {
        "status": "ok",
        "experience_db": {
            "total_experiences": cp.get("total_experiences", 0),
            "dead_components":   cp.get("dead_components", []),
        },
        "self_healing": cp.get("self_healing",
                               {"total_actions": 0, "executed": 0, "pending": 0, "by_type": {}}),
    }


@app.get("/api/capabilities")
async def api_capabilities():
    cp = _cp()
    agents_dir = Path(__file__).parent
    agents = [{"id": f.stem, "size": f.stat().st_size, "capabilities": []}
              for f in sorted(agents_dir.glob("*.py"))
              if not f.name.startswith("_") and f.stem != "dashboard_server"]
    return {
        "agents": cp.get("agents", agents),
        "tools":  cp.get("tools",  []),
        "skills": cp.get("skills", []),
    }


@app.get("/api/workflows")
async def api_workflows():
    cp       = _cp()
    live     = _live()
    active   = live["active_node"]
    return {
        "workflows": [{
            "name":        "V6 Main",
            "nodes":       _NODES,
            "edges":       _EDGES,
            "active_node": active,
        }]
    }


@app.get("/api/experience")
async def api_experience():
    cp = _cp()
    return {
        "best_workflows": cp.get("workflow_scores", []),
        "total":          cp.get("total_experiences", 0),
    }


@app.get("/api/events")
async def api_events():
    cp     = _cp()
    raw    = cp.get("nmp_log", [])
    events = []
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict):
                events.append({
                    "type":      e.get("action", "?"),
                    "source":    e.get("source", ""),
                    "data":      e.get("payload", {}),
                    "timestamp": e.get("ts", ""),
                })
    type_counts: dict = {}
    for e in events:
        type_counts[e["type"]] = type_counts.get(e["type"], 0) + 1
    return {
        "events": events[-50:],
        "stats":  {"total_events": len(events), "event_types": type_counts},
    }


@app.get("/api/meta")
async def api_meta():
    cp = _cp()
    return {
        "emotional":         cp.get("forge_meta", {
            "confidence": 0.7, "uncertainty": 0.3, "risk": 0.2,
            "reward": 0.6,     "curiosity": 0.5,   "novelty": 0.4,
        }),
        "recommendations":   cp.get("recommendations", []),
        "last_optimization": cp.get("last_optimization"),
    }


@app.get("/api/live")
async def api_live():
    return _live()


@app.get("/api/stream")
async def api_stream():
    """SSE endpoint — pushes live state on every checkpoint.json change (poll 2s)."""
    async def _gen() -> AsyncIterator[str]:
        last_mtime = 0.0
        while True:
            try:
                mtime = CHECKPOINT.stat().st_mtime if CHECKPOINT.exists() else 0.0
                if mtime != last_mtime:
                    last_mtime = mtime
                    yield f"data: {json.dumps(_live())}\n\n"
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── chat endpoint ───────────────────────────────────────────────────────────

# Claude model IDs (confirmed current)
_CLAUDE_MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-8",
}
# Free/Hermes model via RTK/OpenRouter
_HERMES_MODEL = "nousresearch/hermes-3-llama-3.1-405b:free"


@app.post("/api/chat")
async def api_chat(request: Request):
    """
    Streaming chat endpoint.
    Body: { model: "haiku"|"sonnet"|"opus"|"hermes", messages: [{role, content}] }
    SSE events: {type:"text",text} | {type:"usage",input,output,model} | {type:"mimo",bytes,ms} | {type:"error",msg}
    """
    body       = await request.json()
    model_key  = body.get("model", "sonnet")
    messages   = body.get("messages", [])
    is_hermes  = model_key == "hermes"

    async def _stream() -> AsyncIterator[str]:
        if is_hermes:
            # Route through forge_llm free tier (RTK → hermes-3)
            try:
                import sys as _sys, time as _time
                _sys.path.insert(0, str(Path(__file__).parent.parent))
                from forge_agents.forge_llm import forge_call, LLMTier
                user_msg = messages[-1]["content"] if messages else ""
                t0 = _time.monotonic()
                result = forge_call(user_msg, tier=LLMTier.HAIKU, task_type="general_purpose")
                ms = int((_time.monotonic() - t0) * 1000)
                raw_bytes = len(result.encode("utf-8"))
                yield f"data: {json.dumps({'type':'text','text':result})}\n\n"
                yield f"data: {json.dumps({'type':'mimo','bytes':raw_bytes,'ms':ms,'model':_HERMES_MODEL})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type':'error','msg':str(e)})}\n\n"
        else:
            # Claude with native streaming
            try:
                import anthropic
                model_id = _CLAUDE_MODELS.get(model_key, _CLAUDE_MODELS["sonnet"])
                client = anthropic.Anthropic()
                with client.messages.stream(
                    model=model_id,
                    max_tokens=4096,
                    messages=messages,
                ) as s:
                    for chunk in s.text_stream:
                        yield f"data: {json.dumps({'type':'text','text':chunk})}\n\n"
                    final = s.get_final_message()
                    yield f"data: {json.dumps({'type':'usage','input':final.usage.input_tokens,'output':final.usage.output_tokens,'model':model_id})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type':'error','msg':str(e)})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DASHBOARD_PORT", 7420))
    print(f"\n  Forge Dashboard → http://localhost:{port}\n")
    uvicorn.run("forge_agents.dashboard_server:app",
                host="0.0.0.0", port=port, reload=False)
