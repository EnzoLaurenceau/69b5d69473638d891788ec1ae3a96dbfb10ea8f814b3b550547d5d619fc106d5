"""Exporte un pack de données brutes pour benchmark externe (Forge vs Claude naif).

Usage: python 00_CORE/tools/export_benchmark_pack.py [outdir]
Defaut outdir: 08_LOGS/benchmark_pack/

ponytail: pas de CLI, pas de config, pas de dependance. Lit ce qui existe, ecrit du CSV/JSON.
"""
import csv
import glob
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "08_LOGS", "benchmark_pack")


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return default


def jlines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [json.loads(l) for l in f if l.strip()]
    except Exception:
        return []


def wcsv(name, rows, cols):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path, len(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = {}

    # 1. Appels LLM workers de la Forge (telemetrie token_tracker)
    calls = []
    for f in sorted(glob.glob(os.path.join(ROOT, "08_LOGS", "tokens", "*.json"))):
        rep = jload(f, {}) or {}
        for r in rep.get("raw_logs") or []:
            r = dict(r)
            r["report"] = os.path.basename(f)
            r["task"] = rep.get("task", "")
            r["session_id"] = rep.get("session_id", "")
            calls.append(r)
    p, n = wcsv("forge_llm_calls.csv", calls, [
        "timestamp", "session_id", "task", "node_name", "task_type",
        "model", "input_tokens", "output_tokens", "cost_usd", "latency_ms", "report"])
    manifest["forge_llm_calls.csv"] = {"rows": n, "desc": "1 ligne = 1 appel LLM worker, avec noeud, modele route, tokens, cout, latence"}

    # 2. Metriques par agent/workflow (forge_metrics.jsonl)
    m = jlines(os.path.join(ROOT, "05_STATE", "forge_metrics.jsonl"))
    p, n = wcsv("forge_agent_metrics.csv", m, [
        "ts", "kind", "workflow", "agent", "node", "provider", "model",
        "tokens_in", "tokens_out", "latency_ms", "cost_usd",
        "hallucination_score", "hallucination_verdict", "ok", "error"])
    manifest["forge_agent_metrics.csv"] = {"rows": n, "desc": "telemetrie par agent/workflow: tokens, latence, verdict hallucination, erreurs"}

    # 3. Tool calls (mesure du volume brut entrant dans le contexte)
    led = jlines(os.path.join(ROOT, "05_STATE", "tool_call_ledger.jsonl"))
    rows = [{
        "timestamp": x.get("timestamp"),
        "source": x.get("source"),
        "session_id": x.get("session_id"),
        "tool_name": x.get("tool_name"),
        "model": x.get("model"),
        "raw_result_chars": len(x.get("tool_result_raw") or ""),
        "truncated": bool(x.get("truncated")),
        "is_error": bool(x.get("is_error")),
    } for x in led]
    p, n = wcsv("tool_calls.csv", rows, list(rows[0]) if rows else ["timestamp"])
    manifest["tool_calls.csv"] = {"rows": n, "desc": "1 ligne = 1 tool call. raw_result_chars = volume brut AVANT compression RTK; truncated = compresse/tronque"}

    # 4. Sessions (Claude Code = cote 'naif', Forge/Hermes = cote optimise)
    dash = jload(os.path.join(ROOT, "05_STATE", "dashboard_stats.json"), {}) or {}
    sess = dash.get("last_sessions") or []
    p, n = wcsv("sessions.csv", sess, [
        "session_id", "provider", "source", "project", "model", "started_at", "ended_at",
        "message_count", "user_messages", "assistant_messages",
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "total_tokens"])
    manifest["sessions.csv"] = {"rows": n, "desc": "sessions recentes tracees. provider=claude-code -> execution Claude directe; provider=forge/hermes -> execution routee"}

    # 5. Agregats globaux
    agg = {
        "generated_at": dash.get("timestamp"),
        "provider_summary": dash.get("provider_summary"),
        "totals": {k: dash.get(k) for k in (
            "total_sessions", "total_messages", "total_tool_calls",
            "total_input_tokens", "total_output_tokens", "total_tokens", "total_cost_usd")},
        "models_used": dash.get("models_used"),
    }
    with open(os.path.join(OUT, "aggregates.json"), "w", encoding="utf-8") as f:
        json.dump(agg, f, indent=2, ensure_ascii=False)
    manifest["aggregates.json"] = {"desc": "totaux par provider: claude-code (direct) vs forge/hermes (route). Le cout $ n'est facture que cote claude-code."}

    # 6. Table de routage observee (noeud -> modeles reellement utilises)
    routing = {}
    for c in calls:
        node = c.get("node_name") or "?"
        routing.setdefault(node, {}).setdefault(c.get("model", "?"), 0)
        routing[node][c["model"]] += 1
    with open(os.path.join(OUT, "routing_observed.json"), "w", encoding="utf-8") as f:
        json.dump(routing, f, indent=2, ensure_ascii=False)
    manifest["routing_observed.json"] = {"desc": "routage REEL observe: noeud -> {modele: nb appels}. Pas la config, ce qui s'est execute."}

    with open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    for k, v in manifest.items():
        print(f"{k:28} {v.get('rows','-'):>6}  {v['desc'][:70]}")
    print("\n->", OUT)


if __name__ == "__main__":
    main()
