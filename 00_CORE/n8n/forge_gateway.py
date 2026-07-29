"""forge_gateway — micro-service HTTP exposant la Forge aux workflows n8n.

Responsabilité unique (règle microservices) : traduire HTTP ⇄ fonctions Forge,
en émettant les métriques d'observabilité sur CHAQUE appel (tokens in/out/
inference, latence, hallucination, erreurs) → 05_STATE/forge_metrics.jsonl.

Lancer :  python 00_CORE/n8n/forge_gateway.py          (port 7788)
Deps   :  pip install fastapi uvicorn requests

Endpoints (tous POST JSON sauf mention) :
  /health          GET  — liveness
  /llm             {prompt, tier?, task_type?, max_tokens?, workflow?, agent?}
  /rag             {query, k?}
  /kag             {entities: [..], hops?}
  /blend           {query, k?, hops?}         — boucle RAG+KAG+arbitrage
  /judge           {claim, evidence}          — verdict hallucination
  /feedback        {query, answer}            — re-nourrit le graphe (agentique)
  /metrics/summary GET ?since_ts=             — agrégats par workflow/agent
  /metrics/recent  GET ?limit=                — derniers records bruts
  /metrics         GET  — exposition Prometheus (scrapée par forge-prometheus,
                          visualisée dans Grafana localhost:3000)

Chaque réponse inclut `_metrics` : {latency_ms, tokens_in, tokens_out} pour
que le workflow n8n puisse router dessus (ex: IF hallucination < 0.7 → retry).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "00_CORE"))

from fastapi import FastAPI, Response
from pydantic import BaseModel

from forge_agents.forge_metrics import observe, summary, load_records

app = FastAPI(title="Forge Gateway", version="1.0")


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class LLMReq(BaseModel):
    prompt: str
    tier: str = "SONNET"
    task_type: str | None = None
    system: str = ""
    max_tokens: int = 1500
    workflow: str = "n8n"
    agent: str = "llm"
    # Le gateway produit des réponses destinées à un humain / à un webhook :
    # le NANO_SYSTEM_PROMPT (protocole interne COMMAND|ARG) ne doit PAS être
    # injecté, sinon il pollue la sortie (et se fait lire comme une injection).
    # Mettre à True uniquement pour un appel sous-agent interne.
    nano_mode: bool = False
    use_openviking: bool = True


class RagReq(BaseModel):
    query: str
    k: int = 5
    workflow: str = "n8n"


class KagReq(BaseModel):
    entities: list[str]
    hops: int = 2
    workflow: str = "n8n"


class BlendReq(BaseModel):
    query: str
    k: int = 5
    hops: int = 2
    use_llm: bool = True
    use_judge: bool = True


class JudgeReq(BaseModel):
    claim: str
    evidence: str
    workflow: str = "n8n"


class FeedbackReq(BaseModel):
    query: str
    answer: str
    session_id: str = ""


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ts": time.time()}


@app.post("/llm")
def llm(req: LLMReq) -> dict:
    with observe(workflow=req.workflow, agent=req.agent, kind="llm",
                 node="gateway/llm") as m:
        from forge_agents.forge_llm import forge_call, LLMTier
        tier = LLMTier[req.tier.upper()] if req.tier.upper() in LLMTier.__members__ \
            else LLMTier.SONNET
        out = forge_call(req.prompt, tier=tier, system=req.system,
                         max_tokens=req.max_tokens, task_type=req.task_type,
                         node=f"n8n:{req.agent}", show_tokens=False,
                         nano_mode=req.nano_mode,
                         use_openviking=req.use_openviking)
        if isinstance(out, dict):
            text = out.get("text") or out.get("content") or str(out)
            m.tokens_in = out.get("input_tokens", 0) or _approx_tokens(req.prompt)
            m.tokens_out = out.get("output_tokens", 0) or _approx_tokens(text)
            m.tokens_inference = out.get("thinking_tokens", 0)
            m.provider = str(out.get("provider", ""))
            m.model = str(out.get("model", ""))
        else:
            text = str(out)
            m.tokens_in = _approx_tokens(req.prompt)
            m.tokens_out = _approx_tokens(text)
        return {"text": text,
                "_metrics": {"tokens_in": m.tokens_in,
                             "tokens_out": m.tokens_out,
                             "tokens_inference": m.tokens_inference,
                             "provider": m.provider}}


@app.post("/rag")
def rag(req: RagReq) -> dict:
    from forge_agents.knowledge_blender import rag_retrieve
    docs = rag_retrieve(req.query, k=req.k)
    return {"docs": docs, "_metrics": {"hits": len(docs)}}


@app.post("/kag")
def kag(req: KagReq) -> dict:
    from forge_agents.knowledge_blender import kag_expand
    facts = kag_expand(req.entities, hops=req.hops)
    return {"facts": facts, "_metrics": {"facts": len(facts)}}


@app.post("/blend")
def blend_ep(req: BlendReq) -> dict:
    from forge_agents.knowledge_blender import blend
    res = blend(req.query, k=req.k, hops=req.hops,
                use_llm=req.use_llm, use_judge=req.use_judge)
    return {"context": res["context"], "conflicts": res["conflicts"],
            "audit": res["audit"], "_metrics": res["audit"]}


@app.post("/judge")
def judge_ep(req: JudgeReq) -> dict:
    with observe(workflow=req.workflow, agent="judge", kind="judge",
                 node="gateway/judge") as m:
        from forge_agents.hallucination_judge import judge
        res = judge(claim=req.claim, evidence=req.evidence) or {}
        verdict = str(res.get("verdict", "UNVERIFIABLE")).upper()
        conf = res.get("confidence")
        m.hallucination_verdict = verdict
        if isinstance(conf, (int, float)):
            m.hallucination_score = float(conf)
        return {"verdict": verdict, "confidence": conf,
                "_metrics": {"verdict": verdict}}


@app.post("/feedback")
def feedback_ep(req: FeedbackReq) -> dict:
    from forge_agents.knowledge_blender import feedback
    feedback(req.query, req.answer, session_id=req.session_id)
    return {"ok": True}


@app.get("/metrics/summary")
def metrics_summary(since_ts: float = 0.0) -> dict:
    return summary(since_ts=since_ts)


@app.get("/metrics/recent")
def metrics_recent(limit: int = 50) -> dict:
    return {"records": load_records(limit=limit)}


_PROM_METRICS = [
    ("forge_wf_calls_total", "counter", "Appels par workflow/agent", "calls"),
    ("forge_wf_errors_total", "counter", "Erreurs par workflow/agent", "errors"),
    ("forge_wf_tokens_input_total", "counter", "Tokens input cumulés", "tokens_in"),
    ("forge_wf_tokens_output_total", "counter", "Tokens output cumulés", "tokens_out"),
    ("forge_wf_tokens_inference_total", "counter", "Tokens inference (thinking)", "tokens_inference"),
    ("forge_wf_cost_usd_total", "counter", "Coût cumulé USD", "cost_usd"),
    ("forge_wf_latency_p50_ms", "gauge", "Latence médiane (ms)", "latency_p50_ms"),
    ("forge_wf_latency_p95_ms", "gauge", "Latence p95 (ms)", "latency_p95_ms"),
    ("forge_wf_error_rate", "gauge", "Taux d'erreur (0-1)", "error_rate"),
    ("forge_wf_hallucination_avg", "gauge", "Score hallucination moyen (1=groundé)", "hallucination_avg"),
    ("forge_wf_hallucination_contradicted_total", "counter",
     "Affirmations contredites par l'évidence", "hallu_contradicted"),
]


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


@app.get("/metrics")
def prometheus_metrics() -> Response:
    """Exposition Prometheus des métriques workflow (job `forge_gateway`).

    Labels : workflow, agent. Alimente les dashboards Grafana (tokens in/out/
    inference, latence p50/p95, taux d'erreur, hallucination).
    """
    groups = summary().get("groups", [])
    lines: list[str] = []
    for name, mtype, help_text, key in _PROM_METRICS:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
        for g in groups:
            val = g.get(key)
            if val is None:
                continue
            labels = f'workflow="{_esc(g["workflow"])}",agent="{_esc(g["agent"])}"'
            lines.append(f"{name}{{{labels}}} {val}")
    return Response(content="\n".join(lines) + "\n",
                    media_type="text/plain; version=0.0.4; charset=utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7788)
