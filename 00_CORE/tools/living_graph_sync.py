"""living_graph_sync.py — Living Knowledge Graph : sync TOUTES les sources de données.

Pipeline quotidien (cron 10h). Chaque source de 05_STATE/ est lue et projetée
dans le graphe Kuzu comme nœuds typés + edges typés. Le graphe est VIVANT :
il reflète l'état actuel de la Forge, pas un snapshot statique.

Sources couvertes :
  1. forge_agents/*.py        → Agent nodes
  2. 06_FINDINGS/confirmed/   → Concept nodes (findings)
  3. 05_STATE/kanban/         → Project nodes
  4. hallucination_events.json → MemoryNode (type=hallucination)
  5. experience_db.json        → MemoryNode (type=procedural)
  6. tech_debt.json            → Concept nodes (debt items)
  7. forge_metrics.jsonl       → MemoryNode (type=metric, agrégé)
  8. tool_call_ledger.jsonl    → Concept nodes (tools used)
  9. agent_tracker/history.json → edges Agent→Project
 10. token_sprints.json        → Project nodes (sprints)
 11. tool_index.json           → Concept nodes (tool catalog)
 12. evidence/                 → MemoryNode (type=evidence)
 13. 07_KNOWLEDGE_BASE/datasets/ → Concept nodes (datasets)
 14. Living graph health       → rapport JSON

Usage :
    python 00_CORE/tools/living_graph_sync.py           # dry-run
    python 00_CORE/tools/living_graph_sync.py --apply   # écrit dans Kuzu
    python 00_CORE/tools/living_graph_sync.py --report  # rapport seul
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
STATE = FORGE_ROOT / "05_STATE"
sys.path.insert(0, str(FORGE_ROOT))

from forge_agents.graph_db import get_graph_db

# ── Config ───────────────────────────────────────────────────────────────────
HALLUCINATION_MAX = 200      # dernières hallucinations à ingérer
METRIC_AGGREGATE_WINDOW = 7  # jours pour les métriques agrégées
MEMORY_SCORE_MIN = float(os.environ.get("FORGE_MEMORY_SCORE_MIN", "0.4"))


# ═════════════════════════════════════════════════════════════════════════════
# 1. AGENTS — scan codebase
# ═════════════════════════════════════════════════════════════════════════════

def scan_agents() -> list[dict]:
    agents_dir = FORGE_ROOT / "00_CORE" / "forge_agents"
    found = []
    for py in sorted(agents_dir.glob("*.py")):
        if py.name.startswith("_") or py.name.startswith("test_"):
            continue
        txt = py.read_text(encoding="utf-8", errors="ignore")
        doc_match = re.search(r'"""(.+?)(?:\n|""")', txt)
        desc = doc_match.group(1).strip()[:200] if doc_match else py.stem
        role = _detect_role(py.stem)
        name = _canon_name(py.stem)
        found.append({"name": name, "level": "L2" if role in ("orchestrator","guard","judge","editor","architect") else "L1",
                       "role": role, "prompt_preview": desc, "source": str(py.relative_to(FORGE_ROOT))})
    return found


def _detect_role(stem: str) -> str:
    n = stem.lower()
    for kw, role in [
        ("health|monitor", "monitor"), ("guard|anti|spine|legal|fallow", "guard"),
        ("curator|knowledge|blender", "curator"), ("tracker|metric|token|budget|sprint", "accounting"),
        ("index|graphify", "indexer"), ("cache|fingerprint|lmcache|semantic_cache", "cache"),
        ("rag|search|retrieval", "retrieval"), ("orchestrat|dispatch|kernel", "orchestrator"),
        ("edit|patch|see|inference_patch", "editor"), ("judge|jury|fish|hallucination_judge", "judge"),
        ("herald|notif", "notifier"), ("pruner|memory|mcp_pruner", "maintenance"),
        ("world|ontology", "ontology"), ("architect|prompt", "architect"),
    ]:
        if re.search(kw, n):
            return role
    return "specialist"


def _canon_name(stem: str) -> str:
    CANON = {"ForgeAgents": "ForgeOrchestrator", "AgentNodes": "DynamicAgent",
             "ForgeLlm": "LLMRouter", "ForgeState": "StateSchema"}
    name = stem.replace("_", " ").title().replace(" ", "")
    return CANON.get(name, name)


# ═════════════════════════════════════════════════════════════════════════════
# 2. FINDINGS → Concept
# ═════════════════════════════════════════════════════════════════════════════

def scan_findings() -> list[dict]:
    findings_dir = FORGE_ROOT / "06_FINDINGS" / "confirmed"
    concepts = []
    if not findings_dir.exists():
        return concepts
    for f in findings_dir.iterdir():
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                desc = data.get("_meta", {}).get("description", f.stem)
                concepts.append({"title": f"FND: {desc[:80]}", "category": "finding", "description": desc[:300]})
            except Exception:
                pass
        elif f.suffix == ".md":
            concepts.append({"title": f"FND: {f.stem}", "category": "finding",
                             "description": f.read_text(encoding="utf-8", errors="ignore")[:300]})
    return concepts


# ═════════════════════════════════════════════════════════════════════════════
# 3. KANBAN → Project
# ═════════════════════════════════════════════════════════════════════════════

def scan_kanban() -> list[dict]:
    projects = []
    for kf in list(STATE.glob("**/kanban*.json")) + list(STATE.glob("**/board*.json")):
        try:
            data = json.loads(kf.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("items", data.get("columns", {}).get("doing", []) + data.get("columns", {}).get("todo", []) + data.get("columns", {}).get("done", []))
            for item in (items if isinstance(items, list) else []):
                if isinstance(item, dict):
                    projects.append({
                        "name": item.get("id", item.get("name", "")),
                        "status": item.get("status", "active"),
                        "task": item.get("title", item.get("task", ""))[:200],
                    })
        except Exception:
            pass
    return projects


# ═════════════════════════════════════════════════════════════════════════════
# 4. HALLUCINATIONS → MemoryNode (type=hallucination)
# ═════════════════════════════════════════════════════════════════════════════

def scan_hallucinations(existing_ids: set[str]) -> list[dict]:
    hfile = STATE / "hallucination_events.json"
    if not hfile.exists():
        return []
    try:
        events = json.loads(hfile.read_text(encoding="utf-8"))
    except Exception:
        return []
    memories = []
    for ev in events[-HALLUCINATION_MAX:]:
        hid = f"halluc_{ev.get('id', 0)}"
        if hid in existing_ids:
            continue
        severity = ev.get("severity", "unknown")
        agent = ev.get("agent", "unknown")
        desc = ev.get("description", "")[:300]
        # Score basé sur sévérité : low=0.5, medium=0.7, high=0.9
        score = {"low": 0.5, "medium": 0.7, "high": 0.9}.get(severity, 0.5)
        if score < MEMORY_SCORE_MIN:
            continue
        memories.append({
            "id": hid, "summary": f"[{severity}] {agent}: {desc}",
            "memory_type": "hallucination", "agent": agent, "score": score,
            "_edges": [("AntiHallucination", "PRODUCED_BY")],
        })
    return memories


# ═════════════════════════════════════════════════════════════════════════════
# 5. EXPERIENCES → MemoryNode (type=procedural)
# ═════════════════════════════════════════════════════════════════════════════

def scan_experiences(existing_ids: set[str]) -> list[dict]:
    efile = STATE / "experience_db.json"
    if not efile.exists():
        return []
    try:
        data = json.loads(efile.read_text(encoding="utf-8"))
        exps = data.get("experiences", []) if isinstance(data, dict) else data
    except Exception:
        return []
    memories = []
    for exp in exps:
        eid = f"exp_{exp.get('kernel_id', exp.get('task', 'unk')[:30])}"
        if eid in existing_ids:
            continue
        task = exp.get("task", "")[:200]
        outcome = exp.get("outcome", "unknown")
        score = 0.8 if outcome == "success" else 0.4
        if score < MEMORY_SCORE_MIN:
            continue
        nodes = exp.get("used_nodes", [])
        memories.append({
            "id": eid, "summary": f"[{outcome}] {task}",
            "memory_type": "procedural", "agent": "ForgeOrchestrator", "score": score,
            "_edges": [(n, "RECALLS") for n in nodes[:5]],
        })
    return memories


# ═════════════════════════════════════════════════════════════════════════════
# 6. TECH DEBT → Concept
# ═════════════════════════════════════════════════════════════════════════════

def scan_tech_debt() -> list[dict]:
    dfile = STATE / "tech_debt.json"
    if not dfile.exists():
        return []
    try:
        data = json.loads(dfile.read_text(encoding="utf-8"))
    except Exception:
        return []
    concepts = []
    items = data.get("items", data.get("debt", [])) if isinstance(data, dict) else []
    for item in items[:50]:  # cap pour ne pas surcharger
        if isinstance(item, dict):
            title = item.get("title", item.get("description", ""))[:80]
            if title:
                concepts.append({"title": f"DEBT: {title}", "category": "tech_debt",
                                 "description": item.get("description", title)[:300]})
    return concepts


# ═════════════════════════════════════════════════════════════════════════════
# 7. METRICS → MemoryNode (type=metric, agrégé par jour)
# ═════════════════════════════════════════════════════════════════════════════

def scan_metrics(existing_ids: set[str]) -> list[dict]:
    mfile = STATE / "forge_metrics.jsonl"
    if not mfile.exists():
        return []
    memories = []
    daily = {}
    try:
        for line in mfile.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ts = ev.get("timestamp", 0)
            day = time.strftime("%Y-%m-%d", time.localtime(ts))
            cost = ev.get("cost_usd", 0) or 0
            tokens = ev.get("total_tokens", 0) or 0
            if day not in daily:
                daily[day] = {"cost": 0, "tokens": 0, "calls": 0}
            daily[day]["cost"] += cost
            daily[day]["tokens"] += tokens
            daily[day]["calls"] += 1
    except Exception:
        pass
    for day, agg in sorted(daily.items())[-METRIC_AGGREGATE_WINDOW:]:
        mid = f"metric_{day}"
        if mid in existing_ids:
            continue
        memories.append({
            "id": mid,
            "summary": f"Metrics {day}: {agg['calls']} calls, {agg['tokens']} tokens, ${agg['cost']:.4f}",
            "memory_type": "metric", "agent": "TokenTracker", "score": 0.9,
        })
    return memories


# ═════════════════════════════════════════════════════════════════════════════
# 8. TOOL CALLS → Concept (outils les plus utilisés)
# ═════════════════════════════════════════════════════════════════════════════

def scan_tool_usage() -> list[dict]:
    lfile = STATE / "tool_call_ledger.jsonl"
    if not lfile.exists():
        return []
    tool_counts = {}
    try:
        for line in lfile.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            tool = ev.get("tool", ev.get("name", ""))
            if tool:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
    except Exception:
        pass
    concepts = []
    for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1])[:30]:
        concepts.append({"title": f"TOOL: {tool}", "category": "tool_usage",
                         "description": f"Used {count} times in tool call ledger"})
    return concepts


# ═════════════════════════════════════════════════════════════════════════════
# 9. AGENT TRACKER → edges Agent→Project
# ═════════════════════════════════════════════════════════════════════════════

def scan_agent_tracker() -> list[tuple]:
    """Retourne des edges (agent, project) depuis l'historique d'exécution."""
    tfile = STATE / "agent_tracker" / "history.json"
    if not tfile.exists():
        return []
    edges = []
    try:
        data = json.loads(tfile.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else data.get("history", [])
        for entry in entries[-100:]:  # 100 dernières entrées
            agent = entry.get("agent", entry.get("name", ""))
            task = entry.get("task", entry.get("project", ""))
            if agent and task:
                task_key = task[:60].replace(" ", "-").lower()
                edges.append(("EXECUTES", "Agent", _canon_name(agent), "Project", task_key, f"tracker: {task[:50]}"))
    except Exception:
        pass
    return edges


# ═════════════════════════════════════════════════════════════════════════════
# 10. EVIDENCE → MemoryNode (type=evidence)
# ═════════════════════════════════════════════════════════════════════════════

def scan_evidence(existing_ids: set[str]) -> list[dict]:
    edir = STATE / "evidence"
    if not edir.exists():
        return []
    memories = []
    for f in edir.glob("*.json"):
        eid = f"evidence_{f.stem}"
        if eid in existing_ids:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            desc = data.get("description", data.get("summary", f.stem))[:300]
            memories.append({"id": eid, "summary": desc, "memory_type": "evidence",
                             "agent": "ForgeNoMistakes", "score": 0.8})
        except Exception:
            pass
    return memories


# ═════════════════════════════════════════════════════════════════════════════
# GRAPH HEALTH REPORT
# ═════════════════════════════════════════════════════════════════════════════

def graph_health_report(db) -> dict:
    stats = {}
    for t in ["Agent", "Project", "Concept", "MemoryNode", "Decision", "Repository"]:
        try:
            r = db._conn.execute(f"MATCH (n:{t}) RETURN count(n)")
            stats[t] = r.get_next()[0]
        except Exception:
            stats[t] = 0
    edges = {}
    for e in ["EXECUTES", "RECALLS", "LINKS_TO", "DEVIATION_FROM", "CITES", "REFERENCES", "HOSTS_TOOL", "PRODUCED_BY"]:
        try:
            r = db._conn.execute(f"MATCH ()-[r:{e}]->() RETURN count(r)")
            edges[e] = r.get_next()[0]
        except Exception:
            edges[e] = 0
    total_nodes = sum(stats.values())
    total_edges = sum(edges.values())
    # Orphelins
    orphans = {}
    for t, pk in [("Agent", "name"), ("Concept", "title"), ("MemoryNode", "id")]:
        try:
            r = db._conn.execute(f"MATCH (n:{t}) WHERE NOT (n)-[]-() RETURN n.{pk} LIMIT 20")
            ol = []
            while r.has_next():
                ol.append(r.get_next()[0])
            if ol:
                orphans[t] = ol
        except Exception:
            pass
    return {"timestamp": time.time(), "nodes": stats, "edges": edges,
            "total_nodes": total_nodes, "total_edges": total_edges,
            "density": round(total_edges / max(total_nodes, 1), 2), "orphans": orphans}


# ═════════════════════════════════════════════════════════════════════════════
# MAIN SYNC
# ═════════════════════════════════════════════════════════════════════════════

def sync(apply: bool = False, report_only: bool = False) -> dict:
    db = get_graph_db()
    db._ensure_init()

    if report_only:
        rep = graph_health_report(db)
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return rep

    actions = {"agents": 0, "concepts": 0, "projects": 0, "memories": 0, "edges": 0}
    t0 = time.time()

    # Existing memory IDs (pour éviter les doublons)
    existing_ids = set()
    try:
        r = db._conn.execute("MATCH (m:MemoryNode) RETURN m.id")
        while r.has_next():
            existing_ids.add(r.get_next()[0])
    except Exception:
        pass

    # 1. Agents
    for a in scan_agents():
        actions["agents"] += 1
        if apply:
            db.add_agent(a["name"], a["level"], a["role"], a["prompt_preview"])
    print(f"  [1/10] Agents: {actions['agents']}")

    # 2. Findings → Concept
    for c in scan_findings():
        actions["concepts"] += 1
        if apply:
            db.add_concept(c["title"], c["category"], c["description"])
    print(f"  [2/10] Findings: {actions['concepts']}")

    # 3. Kanban → Project
    for p in scan_kanban():
        actions["projects"] += 1
        if apply:
            db.add_project(p["name"], p["status"], p["task"])
    print(f"  [3/10] Kanban: {actions['projects']}")

    # 4. Hallucinations → MemoryNode
    haluc = scan_hallucinations(existing_ids)
    for m in haluc:
        actions["memories"] += 1
        if apply:
            db.add_memory(m["id"], m["summary"], m["memory_type"], m["agent"], m["score"])
            for agent_name, edge_type in m.get("_edges", []):
                db.create_edge(edge_type, "Agent", agent_name, "MemoryNode", m["id"], context="hallucination")
                actions["edges"] += 1
    print(f"  [4/10] Hallucinations: {len(haluc)}")

    # 5. Experiences → MemoryNode
    exps = scan_experiences(existing_ids)
    for m in exps:
        actions["memories"] += 1
        if apply:
            db.add_memory(m["id"], m["summary"], m["memory_type"], m["agent"], m["score"])
            for node_name, edge_type in m.get("_edges", []):
                try:
                    db.create_edge(edge_type, "Agent", node_name, "MemoryNode", m["id"], context="experience")
                    actions["edges"] += 1
                except Exception:
                    pass
    print(f"  [5/10] Experiences: {len(exps)}")

    # 6. Tech debt → Concept
    for c in scan_tech_debt():
        actions["concepts"] += 1
        if apply:
            db.add_concept(c["title"], c["category"], c["description"])
    print(f"  [6/10] Tech debt: {actions['concepts']} concepts total")

    # 7. Metrics → MemoryNode
    metrics = scan_metrics(existing_ids)
    for m in metrics:
        actions["memories"] += 1
        if apply:
            db.add_memory(m["id"], m["summary"], m["memory_type"], m["agent"], m["score"])
    print(f"  [7/10] Metrics: {len(metrics)}")

    # 8. Tool usage → Concept
    for c in scan_tool_usage():
        actions["concepts"] += 1
        if apply:
            db.add_concept(c["title"], c["category"], c["description"])
    print(f"  [8/10] Tool usage: {actions['concepts']} concepts total")

    # 9. Agent tracker → edges
    tracker_edges = scan_agent_tracker()
    if apply:
        for edge_type, from_label, from_key, to_label, to_key, ctx in tracker_edges:
            try:
                db.create_edge(edge_type, from_label, from_key, to_label, to_key, context=ctx)
                actions["edges"] += 1
            except Exception:
                pass
    print(f"  [9/10] Tracker edges: {len(tracker_edges)}")

    # 10. Evidence → MemoryNode
    evidence = scan_evidence(existing_ids)
    for m in evidence:
        actions["memories"] += 1
        if apply:
            db.add_memory(m["id"], m["summary"], m["memory_type"], m["agent"], m["score"])
    print(f"  [10/10] Evidence: {len(evidence)}")

    # Health report
    rep = graph_health_report(db)
    elapsed = round(time.time() - t0, 1)

    # Write report
    report_path = STATE / "graph_health.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "sync": actions, "health": rep, "elapsed_s": elapsed,
        "sources": ["agents", "findings", "kanban", "hallucinations", "experiences",
                     "tech_debt", "metrics", "tool_usage", "agent_tracker", "evidence"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'APPLIED' if apply else 'DRY-RUN'} in {elapsed}s")
    print(f"Graph: {rep['total_nodes']} nodes, {rep['total_edges']} edges, density={rep['density']}")
    if rep["orphans"]:
        total_orphans = sum(len(v) for v in rep["orphans"].values())
        print(f"Orphans: {total_orphans} ({', '.join(f'{k}:{len(v)}' for k,v in rep['orphans'].items())})")
    print(f"Report → {report_path}")
    return {"sync": actions, "health": rep}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="écrit dans Kuzu")
    ap.add_argument("--report", action="store_true", help="rapport seul")
    args = ap.parse_args()
    sync(apply=args.apply, report_only=args.report)
