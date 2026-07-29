"""full_graph_connect.py — Intégration complète : connecte TOUT le vivant.

5 étapes :
  1. Connecter les agents orphelins aux projets (EXECUTES)
  2. Connecter les MemoryNodes orphelins aux agents (PRODUCED_BY, RECALLS)
  3. Ingestion sources manquantes (tech_debt, resources, github, catalog, kanban)
  4. Skills Hermes → Concept nodes + edges
  5. Anti-patterns + rapports → Concept nodes

Usage :
    python 00_CORE/tools/full_graph_connect.py          # dry-run
    python 00_CORE/tools/full_graph_connect.py --apply   # écrit
"""

from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
STATE = FORGE_ROOT / "05_STATE"
KB = FORGE_ROOT / "07_KNOWLEDGE_BASE"
REPORTS = FORGE_ROOT / "07_REPORTS"
FINDINGS = FORGE_ROOT / "06_FINDINGS"
HERMES_SKILLS = Path.home() / "AppData" / "Local" / "hermes" / "profiles" / "forge" / "skills"

sys.path.insert(0, str(FORGE_ROOT))
from forge_agents.graph_db import get_graph_db


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _canon_name(stem: str) -> str:
    CANON = {"ForgeAgents": "ForgeOrchestrator", "AgentNodes": "DynamicAgent",
             "ForgeLlm": "LLMRouter", "ForgeState": "StateSchema"}
    name = stem.replace("_", " ").title().replace(" ", "")
    return CANON.get(name, name)


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


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 : Connecter les agents orphelins
# ═════════════════════════════════════════════════════════════════════════════

def connect_orphan_agents(db, apply: bool) -> int:
    """Lie les agents orphelins au sprint actif et aux projets kanban."""
    edges = 0

    # 1a. Lire le kanban pour connaître les tâches et agents assignés
    kanban = STATE / "kanban" / "board.json"
    sprint_projects = []
    if kanban.exists():
        try:
            data = json.loads(kanban.read_text(encoding="utf-8"))
            for t in data.get("tasks", []):
                tid = t.get("id", "")
                name = f"sprint-6j-{tid.lower()}" if tid.startswith("S-") else tid
                status = t.get("status", "pending")
                task_name = t.get("name", "")[:200]
                # Créer le project si absent
                if apply:
                    db.add_project(name, status, task_name)
                sprint_projects.append(name)
        except Exception:
            pass

    # 1b. Scanner les modules agents et les lier au sprint actif
    agents_dir = FORGE_ROOT / "00_CORE" / "forge_agents"
    agent_names = []
    for py in sorted(agents_dir.glob("*.py")):
        if py.name.startswith("_") or py.name.startswith("test_"):
            continue
        name = _canon_name(py.stem)
        agent_names.append(name)

    # Lier chaque agent au sprint actif (sprint-6j-j3)
    active_sprint = "sprint-6j-j3"
    for name in agent_names:
        if apply:
            db.create_edge("EXECUTES", "Agent", name, "Project", active_sprint,
                           context="auto-connect: living graph")
        edges += 1

    # 1c. Lier les agents spécialistes aux projets kanban pertinents
    specialist_map = {
        "SEEEngine": ["sprint-6j-s-02", "sprint-6j-s-24"],
        "KnowledgeCurator": ["sprint-6j-s-09", "sprint-6j-s-11"],
        "AntiHallucination": ["sprint-6j-s-05", "sprint-6j-s-07"],
        "TokenTracker": ["sprint-6j-s-03", "sprint-6j-s-05", "sprint-6j-s-06"],
        "ForgeSpine": ["sprint-6j-s-07"],
        "MiroFish": ["sprint-6j-s-01"],
        "GraphifyIndexer": ["sprint-6j-s-09"],
        "ForgeHealth": ["sprint-6j-s-01"],
        "ClaudeHealth": ["sprint-6j-s-08"],
        "LegalCompliance": ["sprint-6j-s-01"],
        "FingerprintStore": ["sprint-6j-s-06"],
        "MemoryPruner": ["sprint-6j-s-11"],
        "PromptArchitect": ["sprint-6j-s-09"],
    }
    for agent, projects in specialist_map.items():
        for proj in projects:
            if apply:
                db.create_edge("EXECUTES", "Agent", agent, "Project", proj,
                               context="specialist assignment")
            edges += 1

    return edges


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 : Connecter les MemoryNodes orphelins
# ═════════════════════════════════════════════════════════════════════════════

def connect_orphan_memories(db, apply: bool) -> int:
    """Lie les MemoryNodes orphelins aux agents/producteurs."""
    edges = 0
    conn = db._conn

    # 2a. Hallucinations → PRODUCED_BY → Agent
    # Récupérer les hallucinations et leur agent
    try:
        r = conn.execute(
            "MATCH (m:MemoryNode) WHERE m.memory_type = 'hallucination' "
            "RETURN m.id, m.agent LIMIT 500"
        )
        hallucinations = []
        while r.has_next():
            row = r.get_next()
            hallucinations.append({"id": row[0], "agent": row[1] or ""})
    except Exception:
        hallucinations = []

    for h in hallucinations:
        agent = h["agent"]
        if not agent:
            continue
        # Mapper les noms d'agents non-canoniques
        agent_map = {
            "claude_code_cli": "ClaudeHealth",
            "claude-code": "ClaudeHealth",
            "mimo": "LLMRouter",
            "hermes": "ForgeOrchestrator",
        }
        canon = agent_map.get(agent.lower(), agent)
        # Vérifier que l'agent existe
        try:
            check = conn.execute(f"MATCH (a:Agent) WHERE a.name = '{canon}' RETURN a.name")
            if not check.has_next():
                continue
        except Exception:
            continue
        if apply:
            db.create_edge("PRODUCED_BY", "MemoryNode", h["id"], "Agent", canon,
                           context="hallucination source")
        edges += 1

    # 2b. Expériences → RECALLS → Agent
    try:
        r = conn.execute(
            "MATCH (m:MemoryNode) WHERE m.memory_type = 'procedural' "
            "RETURN m.id, m.agent LIMIT 200"
        )
        experiences = []
        while r.has_next():
            row = r.get_next()
            experiences.append({"id": row[0], "agent": row[1] or ""})
    except Exception:
        experiences = []

    for exp in experiences:
        agent = exp["agent"]
        if agent:
            canon = _canon_name(agent) if "_" in agent else agent
            if apply:
                db.create_edge("RECALLS", "Agent", canon, "MemoryNode", exp["id"],
                               context="experience recall")
            edges += 1

    # 2c. Métriques → RECALLS → TokenTracker
    try:
        r = conn.execute(
            "MATCH (m:MemoryNode) WHERE m.memory_type = 'metric' RETURN m.id"
        )
        while r.has_next():
            mid = r.get_next()[0]
            if apply:
                db.create_edge("RECALLS", "Agent", "TokenTracker", "MemoryNode", mid,
                               context="metric tracking")
            edges += 1
    except Exception:
        pass

    # 2d. Evidence → PRODUCED_BY → ForgeNoMistakes
    try:
        r = conn.execute(
            "MATCH (m:MemoryNode) WHERE m.memory_type = 'evidence' RETURN m.id"
        )
        while r.has_next():
            mid = r.get_next()[0]
            if apply:
                db.create_edge("PRODUCED_BY", "MemoryNode", mid, "Agent", "ForgeNoMistakes",
                               context="evidence collector")
            edges += 1
    except Exception:
        pass

    # 2e. Semantic findings → LINKS_TO → Concept
    try:
        r = conn.execute(
            "MATCH (m:MemoryNode) WHERE m.memory_type = 'semantic' RETURN m.id"
        )
        while r.has_next():
            mid = r.get_next()[0]
            # Lier au concept "B2B Prospection" ou "PromptFlow SaaS" selon le contenu
            for concept in ["B2B Prospection", "PromptFlow SaaS"]:
                try:
                    check = conn.execute(f"MATCH (c:Concept) WHERE c.title = '{concept}' RETURN c.title")
                    if check.has_next():
                        if apply:
                            db.create_edge("LINKS_TO", "MemoryNode", mid, "Concept", concept,
                                           context="semantic link")
                        edges += 1
                        break
                except Exception:
                    pass
    except Exception:
        pass

    return edges


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 : Ingestion sources manquantes
# ═════════════════════════════════════════════════════════════════════════════

def ingest_missing_sources(db, apply: bool) -> dict:
    """Ingestion de tech_debt, external_resources, github_inventory, catalog, kanban."""
    stats = {"concepts": 0, "repos": 0, "projects": 0, "edges": 0}

    # 3a. Tech debt → Concept nodes
    tech_file = STATE / "tech_debt.json"
    if tech_file.exists():
        try:
            data = json.loads(tech_file.read_text(encoding="utf-8"))
            # Le format est un dict avec "files" (liste de fichiers analysés)
            files = data.get("files", [])
            debt_concepts = {}
            for f in files:
                if isinstance(f, dict):
                    zone = f.get("zone", "unknown")
                    debt_score = f.get("debt_score", 0)
                    path = f.get("path", "")
                    if debt_score > 0:
                        zone_key = f"DEBT_ZONE: {zone}"
                        if zone_key not in debt_concepts:
                            debt_concepts[zone_key] = {"count": 0, "total_score": 0, "files": []}
                        debt_concepts[zone_key]["count"] += 1
                        debt_concepts[zone_key]["total_score"] += debt_score
                        debt_concepts[zone_key]["files"].append(path)

            for title, info in debt_concepts.items():
                avg = info["total_score"] / max(info["count"], 1)
                desc = f"{info['count']} fichiers, score moyen {avg:.1f}. Ex: {', '.join(info['files'][:3])}"
                if apply:
                    db.add_concept(title, "tech_debt", desc[:300])
                stats["concepts"] += 1
        except Exception as e:
            print(f"  [WARN] tech_debt parse error: {e}")

    # 3b. External resources → Concept nodes
    ext_file = KB / "external_resources.json"
    if ext_file.exists():
        try:
            data = json.loads(ext_file.read_text(encoding="utf-8"))
            resources = data.get("resources", [])
            for res in resources:
                if isinstance(res, str) and res.startswith("RES|"):
                    parts = res.split("|")
                    if len(parts) >= 5:
                        res_id = parts[1]
                        res_type = parts[2]
                        priority = parts[3]
                        purpose = parts[4][:200]
                        title = f"RES: {res_id}"
                        desc = f"[{priority}] {purpose}"
                        if apply:
                            db.add_concept(title, f"resource_{res_type}", desc)
                        stats["concepts"] += 1
        except Exception as e:
            print(f"  [WARN] external_resources parse error: {e}")

    # 3c. GitHub inventory → Repository nodes
    gh_file = KB / "github_inventory.json"
    if gh_file.exists():
        try:
            data = json.loads(gh_file.read_text(encoding="utf-8"))
            repos = data if isinstance(data, list) else data.get("repos", [])
            for repo in repos:
                if isinstance(repo, dict):
                    url = repo.get("url", repo.get("html_url", ""))
                    name = repo.get("name", "")
                    org = repo.get("owner", {}).get("login", "") if isinstance(repo.get("owner"), dict) else ""
                    desc = (repo.get("description", "") or "")[:300]
                    lang = repo.get("language", "") or ""
                    stars = repo.get("stargazers_count", 0) or 0
                    if url and apply:
                        db.add_repository(url, org, name, desc, stars=stars, language=lang)
                    stats["repos"] += 1
        except Exception as e:
            print(f"  [WARN] github_inventory parse error: {e}")

    # 3d. Knowledge base catalog → Concept nodes (datasets)
    catalog_file = KB / "catalog.json"
    if catalog_file.exists():
        try:
            data = json.loads(catalog_file.read_text(encoding="utf-8"))
            datasets = data.get("datasets", [])
            for ds in datasets:
                name = ds.get("name", "")
                rows = ds.get("rows", 0) or 0
                size = ds.get("size_mb", 0) or 0
                formats = ", ".join(ds.get("formats", []))
                title = f"DATASET: {name}"
                desc = f"{rows} rows, {size}MB, formats: {formats}"
                if apply:
                    db.add_concept(title, "dataset", desc[:300])
                stats["concepts"] += 1
        except Exception as e:
            print(f"  [WARN] catalog parse error: {e}")

    # 3e. Kanban tasks → Project nodes (complets)
    kanban_file = STATE / "kanban" / "board.json"
    if kanban_file.exists():
        try:
            data = json.loads(kanban_file.read_text(encoding="utf-8"))
            for t in data.get("tasks", []):
                tid = t.get("id", "")
                name = f"sprint-6j-{tid.lower()}" if tid.startswith("S-") else tid
                status = t.get("status", "pending")
                task_name = t.get("name", "")[:200]
                day = t.get("day", 0)
                if apply:
                    db.add_project(name, status, task_name, cycle=day)
                stats["projects"] += 1

                # Lier les tâches done aux ADRs pertinentes
                if status == "done":
                    adr_map = {
                        "S-01": "ADR-005", "S-02": "ADR-004", "S-06": "ADR-007",
                        "S-07": "ADR-005", "S-08": "ADR-001", "S-09": "ADR-001",
                    }
                    adr = adr_map.get(tid)
                    if adr and apply:
                        try:
                            db.create_edge("DEVIATION_FROM", "Project", name, "Decision", adr,
                                           context=f"sprint {tid} → {adr}")
                            stats["edges"] += 1
                        except Exception:
                            pass
        except Exception as e:
            print(f"  [WARN] kanban parse error: {e}")

    # 3f. Pending findings → Concept nodes
    pending_dir = FINDINGS / "pending"
    if pending_dir.exists():
        for f in pending_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                desc = data.get("_meta", {}).get("description", f.stem)
                title = f"PENDING: {desc[:80]}"
                if apply:
                    db.add_concept(title, "pending_finding", desc[:300])
                stats["concepts"] += 1
            except Exception:
                pass

    # 3g. Reports → Concept nodes
    if REPORTS.exists():
        for f in REPORTS.glob("*.md"):
            title = f"REPORT: {f.stem.replace('_', ' ').title()}"
            desc = f.read_text(encoding="utf-8", errors="ignore")[:300]
            if apply:
                db.add_concept(title, "report", desc)
            stats["concepts"] += 1

    return stats


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAPE 4 : Skills Hermes → Concept nodes
# ═════════════════════════════════════════════════════════════════════════════

def ingest_skills(db, apply: bool) -> dict:
    """Scan les skills Hermes et les ajoute comme Concept nodes."""
    stats = {"concepts": 0, "edges": 0}
    if not HERMES_SKILLS.exists():
        return stats

    for skill_dir in sorted(HERMES_SKILLS.rglob("SKILL.md")):
        try:
            content = skill_dir.read_text(encoding="utf-8", errors="ignore")
            # Extraire le nom du skill depuis le frontmatter ou le nom du dossier
            skill_name = skill_dir.parent.name
            # Chercher la description dans le frontmatter
            desc_match = re.search(r'description:\s*(.+?)(?:\n|$)', content)
            desc = desc_match.group(1).strip()[:200] if desc_match else skill_name
            # Catégorie = parent directory
            category = skill_dir.parent.parent.name if skill_dir.parent.parent != HERMES_SKILLS else "general"

            title = f"SKILL: {skill_name}"
            if apply:
                db.add_concept(title, f"skill_{category}", desc)
            stats["concepts"] += 1

            # Lier aux agents pertinents selon la catégorie
            agent_links = {
                "github": ["ForgeOrchestrator", "GraphifyIndexer"],
                "research": ["AdaptiveRAG", "ForgeSearchEngine"],
                "creative": ["PromptArchitect"],
                "mlops": ["FinetunePipeline"],
                "productivity": ["ForgeOrchestrator"],
                "software-development": ["SEEEngine", "ForgeOrchestrator"],
            }
            for agent in agent_links.get(category, []):
                if apply:
                    try:
                        db.create_edge("HOSTS_TOOL", "Repository", "https://github.com/hermes-agent",
                                       "Concept", title, context=f"skill: {skill_name}")
                        stats["edges"] += 1
                    except Exception:
                        pass
        except Exception:
            pass

    return stats


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAPE 5 : Anti-patterns + connections finales
# ═════════════════════════════════════════════════════════════════════════════

def connect_concepts(db, apply: bool) -> int:
    """Crée les edges CITES entre concepts existants et nouveaux."""
    edges = 0

    # 5a. Tech debt → CITES → architecture concepts
    debt_to_arch = {
        "DEBT_ZONE: core": "SPINE Architecture",
        "DEBT_ZONE: agents": "Expert per Micro-task",
        "DEBT_ZONE: tools": "Kuzu Graph Database",
        "DEBT_ZONE: web": "Deliver Gate",
    }
    for debt, arch in debt_to_arch.items():
        try:
            check = db._conn.execute(f"MATCH (c:Concept) WHERE c.title = '{debt}' RETURN c.title")
            if check.has_next():
                check2 = db._conn.execute(f"MATCH (c:Concept) WHERE c.title = '{arch}' RETURN c.title")
                if check2.has_next():
                    if apply:
                        db.create_edge("CITES", "Concept", debt, "Concept", arch,
                                       context="debt → architecture")
                    edges += 1
        except Exception:
            pass

    # 5b. Concepts → CITES → Decision ADRs
    concept_adr = {
        "Semantic Edit Engine": "ADR-002",
        "Multi-tenant Isolation": "ADR-003",
        "Kuzu Graph Database": "ADR-001",
        "LLM Cascade Routing": "ADR-004",
        "Anti-hallucination Loop": "ADR-005",
        "World Knowledge Graph": "ADR-006",
        "Zero-redundancy Gate": "ADR-007",
        "Deliver Gate": "ADR-008",
    }
    for concept, adr in concept_adr.items():
        try:
            check = db._conn.execute(f"MATCH (c:Concept) WHERE c.title = '{concept}' RETURN c.title")
            if check.has_next():
                if apply:
                    db.create_edge("DEVIATION_FROM", "Concept", concept, "Decision", adr,
                                   context=f"{concept} → {adr}")
                edges += 1
        except Exception:
            pass

    # 5c. Agents → CITES → Concepts (les agents utilisent des concepts)
    agent_concept = {
        "SEEEngine": "Semantic Edit Engine",
        "ForgeSpine": "SPINE Architecture",
        "AntiHallucination": "Anti-hallucination Loop",
        "KnowledgeCurator": "Kuzu Graph Database",
        "TokenTracker": "Zero-redundancy Gate",
        "FingerprintStore": "Zero-redundancy Gate",
        "LegalCompliance": "Deliver Gate",
        "WorldKG": "World Knowledge Graph",
        "LLMRouter": "LLM Cascade Routing",
        "ForgeStore": "Multi-tenant Isolation",
        "MiroFish": "Expert per Micro-task",
        "PromptArchitect": "Expert per Micro-task",
        "ClaudeHealth": "LLM Cascade Routing",
    }
    for agent, concept in agent_concept.items():
        try:
            check = db._conn.execute(f"MATCH (a:Agent) WHERE a.name = '{agent}' RETURN a.name")
            if check.has_next():
                if apply:
                    db.create_edge("CITES", "Agent", agent, "Concept", concept,
                                   context=f"{agent} uses {concept}")
                edges += 1
        except Exception:
            pass

    # 5d. Concepts → CITES → Concepts (dépendances)
    concept_deps = [
        ("Deliver Gate", "Anti-hallucination Loop", "quality gate depends on"),
        ("SPINE Architecture", "Anti-hallucination Loop", "SPINE includes HITL"),
        ("SPINE Architecture", "Deliver Gate", "SPINE includes deliver gate"),
        ("Zero-redundancy Gate", "Token Last Principle", "fingerprint is the gate"),
        ("Expert per Micro-task", "LLM Cascade Routing", "experts use forge_call"),
        ("World Knowledge Graph", "Kuzu Graph Database", "second Kuzu instance"),
        ("Multi-tenant Isolation", "Forge Store", "forge_store is the mechanism"),
        ("Forge Store", "Multi-tenant Isolation", "bidirectional dependency"),
    ]
    for src, dst, ctx in concept_deps:
        try:
            check1 = db._conn.execute(f"MATCH (c:Concept) WHERE c.title = '{src}' RETURN c.title")
            check2 = db._conn.execute(f"MATCH (c:Concept) WHERE c.title = '{dst}' RETURN c.title")
            if check1.has_next() and check2.has_next():
                if apply:
                    db.create_edge("CITES", "Concept", src, "Concept", dst, context=ctx)
                edges += 1
        except Exception:
            pass

    # 5e. Projets kanban → DEPENDS_ON → autres projets
    deps = [
        ("sprint-6j-s-09", "sprint-6j-s-08", "Kuzu needs install first"),
        ("sprint-6j-s-10", "sprint-6j-s-09", "NeuralMap needs populated graph"),
        ("sprint-6j-s-11", "sprint-6j-s-09", "Curation needs graph populated"),
        ("sprint-6j-s-13", "sprint-6j-s-12", "compose needs Docker installed"),
        ("sprint-6j-s-14", "sprint-6j-s-13", "build needs compose working"),
        ("sprint-6j-s-15", "sprint-6j-s-14", "smoke needs build done"),
        ("sprint-6j-s-17", "sprint-6j-s-16", "gate needs Herald compiled"),
        ("sprint-6j-s-18", "sprint-6j-s-17", "deploy needs gate passed"),
        ("sprint-6j-s-19", "sprint-6j-s-18", "smoke needs deploy done"),
        ("sprint-6j-s-20", "sprint-6j-s-19", "merge needs smoke passed"),
        ("sprint-6j-s-21", "sprint-6j-s-20", "doctrine after merge"),
        ("sprint-6j-s-22", "sprint-6j-s-20", "handoff after merge"),
        ("sprint-6j-s-23", "sprint-6j-s-20", "DOX after merge"),
    ]
    for src, dst, ctx in deps:
        if apply:
            try:
                db.create_edge("DEPENDS_ON", "Project", src, "Project", dst, context=ctx)
                edges += 1
            except Exception:
                pass
        else:
            edges += 1

    return edges


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
    for e in ["EXECUTES", "RECALLS", "LINKS_TO", "DEVIATION_FROM", "CITES",
              "REFERENCES", "HOSTS_TOOL", "PRODUCED_BY", "DEPENDS_ON"]:
        try:
            r = db._conn.execute(f"MATCH ()-[r:{e}]->() RETURN count(r)")
            edges[e] = r.get_next()[0]
        except Exception:
            edges[e] = 0
    total_nodes = sum(stats.values())
    total_edges = sum(edges.values())
    orphans = {}
    for t, pk in [("Agent","name"),("Concept","title"),("MemoryNode","id"),("Decision","adr_id")]:
        try:
            r = db._conn.execute(f"MATCH (n:{t}) WHERE NOT (n)-[]-() RETURN count(n)")
            c = r.get_next()[0]
            if c > 0:
                orphans[t] = c
        except Exception:
            pass
    return {"timestamp": time.time(), "nodes": stats, "edges": edges,
            "total_nodes": total_nodes, "total_edges": total_edges,
            "density": round(total_edges / max(total_nodes, 1), 2), "orphans": orphans}


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def run(apply: bool = False) -> dict:
    db = get_graph_db()
    db._ensure_init()
    t0 = time.time()

    print("═══ ÉTAPE 1 : Connecter agents orphelins ═══")
    e1 = connect_orphan_agents(db, apply)
    print(f"  → {e1} edges créées")

    print("\n═══ ÉTAPE 2 : Connecter MemoryNodes orphelins ═══")
    e2 = connect_orphan_memories(db, apply)
    print(f"  → {e2} edges créées")

    print("\n═══ ÉTAPE 3 : Ingestion sources manquantes ═══")
    s3 = ingest_missing_sources(db, apply)
    print(f"  → {s3['concepts']} concepts, {s3['repos']} repos, {s3['projects']} projets, {s3['edges']} edges")

    print("\n═══ ÉTAPE 4 : Skills Hermes ═══")
    s4 = ingest_skills(db, apply)
    print(f"  → {s4['concepts']} skills, {s4['edges']} edges")

    print("\n═══ ÉTAPE 5 : Connections finales (CITES, DEPENDS_ON) ═══")
    e5 = connect_concepts(db, apply)
    print(f"  → {e5} edges créées")

    elapsed = round(time.time() - t0, 1)
    rep = graph_health_report(db)

    # Write report
    report_path = STATE / "graph_health.json"
    report_path.write_text(json.dumps({
        "phase": "full_connect", "apply": apply, "elapsed_s": elapsed,
        "step1_agent_edges": e1, "step2_memory_edges": e2,
        "step3_ingestion": s3, "step4_skills": s4, "step5_concept_edges": e5,
        "health": rep,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    total_orphans = sum(rep["orphans"].values()) if rep["orphans"] else 0
    orphan_pct = round(100 * total_orphans / max(rep["total_nodes"], 1), 1)

    print(f"\n{'═══ APPLIED' if apply else '═══ DRY-RUN'} in {elapsed}s ═══")
    print(f"Nodes: {rep['total_nodes']}  |  Edges: {rep['total_edges']}  |  Density: {rep['density']}")
    print(f"Orphans: {total_orphans} ({orphan_pct}%)")
    for t, c in rep["nodes"].items():
        print(f"  {t}: {c}")
    print(f"Report → {report_path}")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    run(apply=args.apply)
