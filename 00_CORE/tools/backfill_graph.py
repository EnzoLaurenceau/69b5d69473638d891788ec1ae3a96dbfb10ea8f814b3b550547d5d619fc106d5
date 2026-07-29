"""backfill_graph.py — Peuple le graphe Kuzu avec les données réelles de la Forge.

Sources :
  - Agents du codebase (forge_agents/*.py)
  - Concepts architecturaux clés
  - Décisions (ADRs) majeures
  - Findings confirmés (06_FINDINGS/confirmed/)
  - Cycles Forge (sprints)

Usage :
    python 00_CORE/tools/backfill_graph.py          # dry-run (print)
    python 00_CORE/tools/backfill_graph.py --apply   # écrit dans Kuzu
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FORGE_ROOT))

from forge_agents.graph_db import get_graph_db


# ── Agents réels de la Forge ────────────────────────────────────────────────
AGENTS = [
    {"name": "ForgeOrchestrator",    "level": "L3", "role": "orchestrator",  "prompt_preview": "Boucle principale LangGraph — routing, décomposition, synthèse"},
    {"name": "DynamicAgent",         "level": "L2", "role": "specialist",    "prompt_preview": "Exécute une micro-task avec un expert dédié"},
    {"name": "BackendExpert",        "level": "L2", "role": "specialist",    "prompt_preview": "Architecture API, BDD, auth, déploiement"},
    {"name": "FrontendExpert",       "level": "L2", "role": "specialist",    "prompt_preview": "UI/UX, React, responsive, accessibilité"},
    {"name": "KnowledgeCurator",     "level": "L2", "role": "curator",       "prompt_preview": "Sync Kuzu → Obsidian vault, détection orphelins"},
    {"name": "AntiHallucination",    "level": "L2", "role": "guard",         "prompt_preview": "Vérifie les sorties LLM, escalade si UNKNOWN"},
    {"name": "Herald",               "level": "L1", "role": "notifier",      "prompt_preview": "Notifications multi-canal (Telegram, Discord, email)"},
    {"name": "MiroFish",             "level": "L2", "role": "judge",          "prompt_preview": "Jury de qualité — scoring multi-persona"},
    {"name": "SEEEngine",            "level": "L2", "role": "editor",         "prompt_preview": "Semantic Edit Engine — patch minimaliste du code"},
    {"name": "GraphifyIndexer",      "level": "L1", "role": "indexer",        "prompt_preview": "Indexation du dépôt client dans le graphe"},
    {"name": "WorldKG",              "level": "L2", "role": "ontology",       "prompt_preview": "Graphe ontologique monde (RPG, lore, factions)"},
    {"name": "ForgeHealth",          "level": "L1", "role": "monitor",        "prompt_preview": "Santé du dépôt client — dette, couverture"},
    {"name": "ClaudeHealth",         "level": "L1", "role": "monitor",        "prompt_preview": "Health tracker Claude CLI — TTL adaptatif, fallback"},
    {"name": "AdaptiveRAG",          "level": "L2", "role": "retrieval",      "prompt_preview": "RAG adaptatif — re-ranking, contexte dynamique"},
    {"name": "TokenTracker",         "level": "L1", "role": "accounting",     "prompt_preview": "Comptabilité tokens — coût par tâche, budget MiMo"},
    {"name": "MemoryPruner",         "level": "L1", "role": "maintenance",    "prompt_preview": "Élagage du graphe mémoire — TTL, score minimal"},
    {"name": "FingerprintStore",     "level": "L1", "role": "cache",          "prompt_preview": "Cache sémantique — même tâche+contexte → 0 token"},
    {"name": "ForgeSpine",           "level": "L2", "role": "guard",          "prompt_preview": "Honnêteté + HITL + deliver gate + cache facade"},
    {"name": "LegalCompliance",      "level": "L1", "role": "guard",          "prompt_preview": "Gate légal — RGPD, CGV, cookies sur livrables"},
    {"name": "PromptArchitect",      "level": "L2", "role": "architect",      "prompt_preview": "Conception JIT d'experts — roster + auto-promotion"},
]

# ── Concepts architecturaux ─────────────────────────────────────────────────
CONCEPTS = [
    {"title": "Semantic Edit Engine",     "category": "architecture", "description": "SEE — édition minimale du code via patch symbolique, jamais réécriture complète"},
    {"title": "Multi-tenant Isolation",   "category": "architecture", "description": "Cloisonnement tenant/platform/exempt via forge_store + state_ownership"},
    {"title": "Zero-redundancy Gate",     "category": "optimization", "description": "AAOS — fingerprint sémantique avant tout appel LLM, cache 7j"},
    {"title": "Token Last Principle",     "category": "optimization", "description": "Classifier déterministe avant LLM — pas de token si la règle suffit"},
    {"title": "Anti-hallucination Loop",  "category": "quality",      "description": "Détection + révision + escalade HITL si UNKNOWN persistant"},
    {"title": "Deliver Gate",             "category": "quality",      "description": "legal_check + herald avant livraison — blocked si non conforme"},
    {"title": "Expert per Micro-task",    "category": "architecture", "description": "Décomposition sémantique → un expert dédié par micro-task → synthèse"},
    {"title": "Kuzu Graph Database",      "category": "infrastructure", "description": "Graphe embarqué — Agent/Project/Concept/MemoryNode/Decision/Repository"},
    {"title": "World Knowledge Graph",    "category": "infrastructure", "description": "Ontologie monde séparée — Character/Faction/Location/Quest (RPG)"},
    {"title": "Forge Store",              "category": "architecture", "description": "Abstraction état multi-tenant — put/append/state_path"},
    {"title": "LLM Cascade Routing",     "category": "architecture", "description": "Claude (défaut) → MiMo → Gemini → ds2api → Groq (FREE tier)"},
    {"title": "SPINE Architecture",       "category": "architecture", "description": "Colonne vertébrale — honnêteté + deliver gate + cache/batch facade"},
    {"title": "PromptFlow SaaS",          "category": "business",     "description": "Produit Shopify — prompt packs, Notion templates, guides IA"},
    {"title": "B2B Prospection",          "category": "business",     "description": "Playbook Apollo/Hunter/LinkedIn pour agences et freelances"},
]

# ── Décisions majeures (ADR) ────────────────────────────────────────────────
DECISIONS = [
    {"adr_id": "ADR-001", "title": "Kuzu over Neo4j",              "rationale": "Embarqué, zéro serveur, Python natif, suffisant pour le scale Forge", "status": "accepted"},
    {"adr_id": "ADR-002", "title": "SEE obligatoire",              "rationale": "Jamais de réécriture complète — patch minimaliste via symbol_resolver", "status": "accepted"},
    {"adr_id": "ADR-003", "title": "Multi-tenant par forge_store",  "rationale": "state_path() + tenant_scope() — isolation sans conteneurs", "status": "accepted"},
    {"adr_id": "ADR-004", "title": "Claude comme LLM par défaut",  "rationale": "Qualité supérieure ; cascade gratuit en fallback (MiMo→Gemini→Groq)", "status": "accepted"},
    {"adr_id": "ADR-005", "title": "HITL sur UNKNOWN",             "rationale": "La Forge dit qu'elle ne sait pas au lieu d'inventer — escalade humaine", "status": "accepted"},
    {"adr_id": "ADR-006", "title": "World KG séparé de graph_db",  "rationale": "Ontologie monde ≠ graphe code — deux bases Kuzu, zéro pollution", "status": "accepted"},
    {"adr_id": "ADR-007", "title": "Fingerprint avant appel LLM",  "rationale": "Même tâche+contexte dans TTL 7j → résultat rejoué, 0 token", "status": "accepted"},
    {"adr_id": "ADR-008", "title": "Deliver gate obligatoire",     "rationale": "legal_check + herald avant toute livraison client", "status": "accepted"},
]

# ── Repositories de référence ───────────────────────────────────────────────
REPOSITORIES = [
    {"url": "https://github.com/kuzudb/kuzu",           "org": "kuzudb",     "name": "kuzu",           "description": "Embedded graph database", "language": "C++", "stars": 0},
    {"url": "https://github.com/langchain-ai/langgraph", "org": "langchain", "name": "langgraph",      "description": "Stateful multi-agent framework", "language": "Python", "stars": 0},
    {"url": "https://github.com/anthropics/anthropic-sdk-python", "org": "anthropics", "name": "anthropic-sdk", "description": "Claude SDK Python", "language": "Python", "stars": 0},
    {"url": "https://github.com/xiaomi/mimo",            "org": "xiaomi",     "name": "mimo",           "description": "MiMo LLM (FREE tier)", "language": "Python", "stars": 0},
]

# ── Findings confirmés → MemoryNodes ────────────────────────────────────────
FINDINGS_DIR = FORGE_ROOT / "06_FINDINGS" / "confirmed"


def load_findings() -> list[dict]:
    """Charge les findings confirmés comme MemoryNodes."""
    memories = []
    if not FINDINGS_DIR.exists():
        return memories
    for f in FINDINGS_DIR.iterdir():
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                fid = data.get("id", f.stem)
                desc = data.get("_meta", {}).get("description", f.stem)
                memories.append({
                    "id": fid,
                    "summary": desc[:500],
                    "memory_type": "semantic",
                    "agent": "KnowledgeCurator",
                    "score": 0.8,
                })
            except Exception:
                pass
        elif f.suffix == ".md":
            memories.append({
                "id": f"FND_{f.stem}",
                "summary": f.read_text(encoding="utf-8", errors="ignore")[:500],
                "memory_type": "semantic",
                "agent": "KnowledgeCurator",
                "score": 0.7,
            })
    return memories


# ── Cycles Forge (sprints) → Projects ───────────────────────────────────────
SPRINTS = [
    {"name": "sprint-6j-j1", "status": "completed", "task": "Vérité mesurable S-01→S-04", "cycle": 1, "quality": 8.0},
    {"name": "sprint-6j-j2", "status": "completed", "task": "Hémorragie MiMo S-05→S-07 + S-24 (SEE fix)", "cycle": 2, "quality": 9.0},
    {"name": "sprint-6j-j3", "status": "active",    "task": "Kuzu réel S-08→S-11", "cycle": 3, "quality": 0.0},
    {"name": "sprint-6j-j4", "status": "planned",   "task": "Docker S-12→S-15", "cycle": 4, "quality": 0.0},
    {"name": "sprint-6j-j5", "status": "planned",   "task": "Herald + Coolify S-16→S-19", "cycle": 5, "quality": 0.0},
    {"name": "sprint-6j-j6", "status": "planned",   "task": "Fusion, doctrine, doc S-20→S-23", "cycle": 6, "quality": 0.0},
]


def backfill(apply: bool = False) -> None:
    """Peuple le graphe. Si apply=False, dry-run."""
    db = get_graph_db() if apply else None

    stats = {"agents": 0, "concepts": 0, "decisions": 0, "repos": 0,
             "projects": 0, "memories": 0, "edges": 0}

    # Agents
    for a in AGENTS:
        stats["agents"] += 1
        if apply:
            db.add_agent(a["name"], a["level"], a["role"], a["prompt_preview"])
        print(f"  Agent: {a['name']} ({a['role']})")

    # Concepts
    for c in CONCEPTS:
        stats["concepts"] += 1
        if apply:
            db.add_concept(c["title"], c["category"], c["description"])
        print(f"  Concept: {c['title']}")

    # Decisions
    for d in DECISIONS:
        stats["decisions"] += 1
        if apply:
            db.add_decision(d["adr_id"], d["title"], d["rationale"], d["status"])
        print(f"  Decision: {d['adr_id']} — {d['title']}")

    # Repositories
    for r in REPOSITORIES:
        stats["repos"] += 1
        if apply:
            db.add_repository(r["url"], r["org"], r["name"], r["description"], language=r["language"])
        print(f"  Repository: {r['name']}")

    # Projects (sprints)
    for s in SPRINTS:
        stats["projects"] += 1
        if apply:
            db.add_project(s["name"], s["status"], s["task"], s["cycle"], s["quality"])
        print(f"  Project: {s['name']} ({s['status']})")

    # MemoryNodes (findings)
    findings = load_findings()
    for m in findings:
        stats["memories"] += 1
        if apply:
            db.add_memory(m["id"], m["summary"], m["memory_type"], m["agent"], m["score"])
        print(f"  Memory: {m['id']}")

    # ── Edges ────────────────────────────────────────────────────────────────
    edges = []

    # Agent → Project (who works on what)
    edges += [
        ("EXECUTES", "Agent", "ForgeOrchestrator", "Project", "sprint-6j-j3", "orchestre J3"),
        ("EXECUTES", "Agent", "SEEEngine",         "Project", "sprint-6j-j2", "fix SEE"),
        ("EXECUTES", "Agent", "KnowledgeCurator",  "Project", "sprint-6j-j3", "backfill graphe"),
        ("EXECUTES", "Agent", "DynamicAgent",      "Project", "sprint-6j-j1", "exécution micro-tasks"),
    ]

    # Agent → Memory (who recalls what)
    for m in findings:
        edges.append(("RECALLS", "Agent", m["agent"], "MemoryNode", m["id"], "curated finding"))

    # Memory → Concept (semantic links)
    edges += [
        ("LINKS_TO", "MemoryNode", "FND_unknown_b2b_prospection_playbook", "Concept", "B2B Prospection", "finding → concept"),
        ("LINKS_TO", "MemoryNode", "FND_unknown_shopify_store_ids",        "Concept", "PromptFlow SaaS",  "shopify IDs"),
    ]

    # Project → Decision (which ADR applies)
    edges += [
        ("DEVIATION_FROM", "Project", "sprint-6j-j2", "Decision", "ADR-002", "SEE fix → SEE obligatoire"),
        ("DEVIATION_FROM", "Project", "sprint-6j-j3", "Decision", "ADR-001", "Kuzu réel → Kuzu over Neo4j"),
    ]

    # Project → Repository
    edges += [
        ("REFERENCES", "Project", "sprint-6j-j3", "Repository", "https://github.com/kuzudb/kuzu", "kuzu install"),
    ]

    # Repository → Concept (tools used)
    edges += [
        ("HOSTS_TOOL", "Repository", "https://github.com/kuzudb/kuzu",            "Concept", "Kuzu Graph Database",    "graph engine"),
        ("HOSTS_TOOL", "Repository", "https://github.com/langchain-ai/langgraph", "Concept", "Expert per Micro-task",  "agent framework"),
        ("HOSTS_TOOL", "Repository", "https://github.com/anthropics/anthropic-sdk-python", "Concept", "LLM Cascade Routing", "Claude SDK"),
    ]

    # Concept → Concept (citations)
    edges += [
        ("CITES", "Concept", "Deliver Gate",           "Concept", "Anti-hallucination Loop", "both are quality gates"),
        ("CITES", "Concept", "SPINE Architecture",     "Concept", "Anti-hallucination Loop", "SPINE includes HITL"),
        ("CITES", "Concept", "SPINE Architecture",     "Concept", "Deliver Gate",            "SPINE includes deliver gate"),
        ("CITES", "Concept", "Zero-redundancy Gate",   "Concept", "Token Last Principle",    "fingerprint is the gate"),
        ("CITES", "Concept", "Expert per Micro-task",  "Concept", "LLM Cascade Routing",     "experts use forge_call"),
        ("CITES", "Concept", "World Knowledge Graph",  "Concept", "Kuzu Graph Database",     "second Kuzu instance"),
        ("CITES", "Concept", "Multi-tenant Isolation", "Concept", "Forge Store",              "forge_store is the mechanism"),
    ]

    for edge_type, from_label, from_key, to_label, to_key, ctx in edges:
        stats["edges"] += 1
        if apply:
            db.create_edge(edge_type, from_label, from_key, to_label, to_key, context=ctx)
        print(f"  Edge: {from_key} -[{edge_type}]-> {to_key}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'APPLIED' if apply else 'DRY-RUN'}: "
          f"{stats['agents']} agents, {stats['concepts']} concepts, "
          f"{stats['decisions']} decisions, {stats['repos']} repos, "
          f"{stats['projects']} projects, {stats['memories']} memories, "
          f"{stats['edges']} edges")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="écrit dans Kuzu (sinon dry-run)")
    args = ap.parse_args()
    backfill(apply=args.apply)
