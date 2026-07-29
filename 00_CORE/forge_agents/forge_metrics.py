"""forge_metrics — observabilité unifiée par workflow/agent.

Chaque appel LLM / étape de workflow (n8n ou interne) émet un MetricRecord :
tokens input / output / inference (thinking), latence ms, score hallucination,
coût, provenance (workflow, agent, node). Sink : 05_STATE/forge_metrics.jsonl
(append-only, une ligne JSON par événement) + relais vers token_tracker.

Usage :
    from forge_agents.forge_metrics import record, observe, summary

    with observe(workflow="blend_rag_kag", agent="rag_retrieve") as m:
        docs = rag.search_docs(q)
        m.tokens_in = 1200; m.tokens_out = 300

    record(kind="llm", workflow="n8n:core_loop", agent="dynamic_agent",
           tokens_in=800, tokens_out=450, latency_ms=2100,
           hallucination_score=0.93)

    summary()  # agrégats par workflow/agent (appels, tokens, p50/p95 latence)
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import logging

logger = logging.getLogger("ForgeMetrics")

_ROOT = Path(__file__).resolve().parent.parent.parent
METRICS_PATH = _ROOT / "05_STATE" / "forge_metrics.jsonl"

_lock = threading.Lock()


@dataclass
class MetricRecord:
    kind: str = "llm"              # llm | rag | kag | judge | workflow | tool | task
    task_id: str = ""              # ticket du backlog (E6-01) — ex: "E6-01". Vide
                                   # = événement hors tâche tracée ; les lignes
                                   # écrites avant E6-01 n'ont pas le champ.
    workflow: str = ""             # ex: "n8n:core_loop", "blend_rag_kag"
    agent: str = ""                # ex: "dynamic_agent", "rag_retrieve"
    node: str = ""                 # node n8n / node LangGraph
    provider: str = ""             # claude_cli | mimo | groq | ...
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_inference: int = 0      # thinking/reasoning tokens si exposés
    latency_ms: int = 0
    hallucination_score: Optional[float] = None  # 0..1 (1 = groundé)
    hallucination_verdict: str = ""              # SUPPORTED | CONTRADICTED | UNVERIFIABLE
    cost_usd: float = 0.0
    ok: bool = True
    error: str = ""
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)


#: nom du ledger dans l'espace du tenant (cf. forge_store)
_NS, _KEY = "metrics", "forge_metrics.jsonl"
_warned_global = False


def _tenant_store():
    """Retourne le module `forge_store` si un tenant est résolvable, sinon None.

    MODE DE TRANSITION (blueprint multi_tenant.md §5) : tant que l'identité n'est pas
    branchée (W5-03b), un appel sans tenant retombe sur le ledger GLOBAL historique
    plutôt que d'échouer — migrer module par module ne doit pas casser l'existant.
    L'usage non cloisonné est tracé une fois, pour rester visible.
    `FORGE_TENANT_STRICT=1` supprime le repli : utile pour tester l'état final.
    """
    global _warned_global
    try:
        from .forge_tenant import current_tenant_or_none
        from . import forge_store
    except Exception:
        return None
    if current_tenant_or_none() is not None:
        return forge_store
    if os.environ.get("FORGE_TENANT_STRICT", "").lower() in ("1", "true", "yes"):
        from .forge_tenant import current_tenant
        current_tenant()          # lève volontairement : mode strict demandé
    if not _warned_global:
        _warned_global = True
        logger.warning(
            "métriques écrites dans le ledger GLOBAL (aucun tenant en contexte) — "
            "définis FORGE_SINGLE_TENANT ou utilise tenant_scope() ; cf. multi_tenant.md"
        )
    return None


def record(**kwargs: Any) -> MetricRecord:
    """Écrit un événement métrique. Cloisonné par tenant dès qu'un tenant est résolu."""
    rec = MetricRecord(**kwargs)
    store = _tenant_store()
    if store is not None:
        store.append(_NS, _KEY, asdict(rec))
    else:
        line = json.dumps(asdict(rec), ensure_ascii=False, default=str)
        with _lock:
            METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with METRICS_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    _relay_to_token_tracker(rec)
    return rec


def _relay_to_token_tracker(rec: MetricRecord) -> None:
    """Alimente le TokenTracker existant (estimate/post-mortem) sans le dupliquer."""
    if rec.tokens_in == 0 and rec.tokens_out == 0:
        return
    try:
        from forge_agents.token_tracker import get_tracker, TokenUsage
        t = get_tracker()
        t.add_log(TokenUsage(
            task=rec.workflow or rec.kind,
            node=rec.node or rec.agent,
            input_tokens=rec.tokens_in,
            output_tokens=rec.tokens_out,
        ))
    except Exception:
        pass  # tracker optionnel — le JSONL reste la source de vérité


class observe:
    """Context manager : mesure la latence, capture l'erreur, émet le record.

    with observe(workflow="w", agent="a", kind="rag") as m:
        ...; m.tokens_in = 100
    """

    def __init__(self, **kwargs: Any):
        self.rec = MetricRecord(**kwargs)
        self._t0 = 0.0

    def __enter__(self) -> MetricRecord:
        self._t0 = time.perf_counter()
        return self.rec

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.rec.latency_ms = int((time.perf_counter() - self._t0) * 1000)
        if exc is not None:
            self.rec.ok = False
            self.rec.error = f"{exc_type.__name__}: {exc}"
        d = asdict(self.rec)
        d.pop("ts", None)
        record(**{k: v for k, v in d.items()})
        return False  # ne masque pas l'exception


def _percentile(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    idx = min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def load_records(limit: int = 5000, since_ts: float = 0.0) -> list[dict]:
    """Lit le ledger du tenant courant ; à défaut, le ledger global historique."""
    store = _tenant_store()
    if store is not None:
        rows = store.read_lines(_NS, _KEY)
        return [d for d in rows if d.get("ts", 0) >= since_ts][-limit:]

    if not METRICS_PATH.exists():
        return []
    out: list[dict] = []
    with METRICS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("ts", 0) >= since_ts:
                out.append(d)
    return out[-limit:]


def summary(since_ts: float = 0.0) -> dict:
    """Agrégats par (workflow, agent) : appels, tokens, latence p50/p95,
    taux d'erreur, score hallucination moyen, coût cumulé."""
    groups: dict[tuple, dict] = {}
    for d in load_records(since_ts=since_ts):
        key = (d.get("workflow", ""), d.get("agent", ""))
        g = groups.setdefault(key, {
            "workflow": key[0], "agent": key[1], "calls": 0, "errors": 0,
            "tokens_in": 0, "tokens_out": 0, "tokens_inference": 0,
            "cost_usd": 0.0, "latencies": [], "hallu_scores": [],
            "hallu_contradicted": 0,
        })
        g["calls"] += 1
        g["errors"] += 0 if d.get("ok", True) else 1
        g["tokens_in"] += d.get("tokens_in", 0)
        g["tokens_out"] += d.get("tokens_out", 0)
        g["tokens_inference"] += d.get("tokens_inference", 0)
        g["cost_usd"] += d.get("cost_usd", 0.0)
        g["latencies"].append(d.get("latency_ms", 0))
        hs = d.get("hallucination_score")
        if hs is not None:
            g["hallu_scores"].append(hs)
        if d.get("hallucination_verdict") == "CONTRADICTED":
            g["hallu_contradicted"] += 1

    rows = []
    for g in groups.values():
        lat = sorted(g.pop("latencies"))
        scores = g.pop("hallu_scores")
        g["latency_p50_ms"] = _percentile(lat, 0.50)
        g["latency_p95_ms"] = _percentile(lat, 0.95)
        g["hallucination_avg"] = round(sum(scores) / len(scores), 3) if scores else None
        g["error_rate"] = round(g["errors"] / g["calls"], 3) if g["calls"] else 0.0
        rows.append(g)
    rows.sort(key=lambda r: -r["calls"])
    return {"groups": rows, "total_calls": sum(r["calls"] for r in rows)}


def render_summary_table(since_ts: float = 0.0) -> str:
    s = summary(since_ts=since_ts)
    lines = [
        f"{'workflow':<24} {'agent':<20} {'calls':>5} {'in':>8} {'out':>8} "
        f"{'p50ms':>6} {'p95ms':>6} {'hallu':>6} {'err%':>5}",
        "-" * 96,
    ]
    for r in s["groups"]:
        hallu = f"{r['hallucination_avg']:.2f}" if r["hallucination_avg"] is not None else "-"
        lines.append(
            f"{r['workflow'][:24]:<24} {r['agent'][:20]:<20} {r['calls']:>5} "
            f"{r['tokens_in']:>8} {r['tokens_out']:>8} {r['latency_p50_ms']:>6} "
            f"{r['latency_p95_ms']:>6} {hallu:>6} {r['error_rate']*100:>4.0f}%"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_summary_table())
