"""
knowledge_curator.py — Agent Curateur de Connaissances
=======================================================
Mission asynchrone lancée après chaque cycle de la Forge.
Synchronise les données de Postgres + Kuzu vers un vault Obsidian.

Pipeline:
  1. Détecte les changements (nouveaux agents, projets, mémoires)
  2. Génère des notes Markdown structurées dans /vault/
  3. Insère des liens bidirectionnels ([[Agent]], [[Concept]])
  4. Identifie les concepts orphelins
  5. Génère des graphes Mermaid par projet

Arborescence du vault:
  /vault/
    /Agents/       — Fiches d'identité des agents
    /Projects/     — Fiches de tâches + Mermaid
    /Knowledge/    — Concepts techniques
    /Decisions/    — ADR (Architecture Decision Records)
    /Memories/     — Épisodique (traces), Sémantique (fragments RAG)

Usage:
    from forge_agents.knowledge_curator import get_curator
    curator = get_curator()
    curator.curate(state)  # après un cycle Forge
    curator.full_sync()    # re-synchronisation complète
"""

from __future__ import annotations
import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("KnowledgeCurator")

FORGE_ROOT = Path(__file__).parent.parent.parent
VAULT_ROOT = FORGE_ROOT / "vault"

# ── Seuil de qualité pour la mémoire ─────────────────────────────────────────
# Un finding avec score < MEMORY_SCORE_MIN n'est PAS synchronisé dans le graphe.
# Évite de polluer Kuzu avec des résultats LLM de basse qualité.
MEMORY_SCORE_MIN = float(os.environ.get("FORGE_MEMORY_SCORE_MIN", "0.4"))

# ── Pruning des orphelins ────────────────────────────────────────────────────
# Un nœud orphelin (sans arête) avec score < ORPHAN_PRUNE_SCORE est supprimé.
# Au-dessus, on note seulement (le curateur peut le relier plus tard).
ORPHAN_PRUNE_SCORE = float(os.environ.get("FORGE_ORPHAN_PRUNE_SCORE", "0.3"))


class KnowledgeCurator:
    """
    Agent Curateur — sync asynchrone Kuzu/Postgres → Obsidian vault.
    Génère des notes .md structurées avec liens bidirectionnels.
    
    S'abonne aux événements TASK_COMPLETE et prompt_updated du bus
    pour maintenir le vault à jour automatiquement.
    """

    def __init__(self, vault_path: str | Path = VAULT_ROOT):
        self._vault = Path(vault_path)
        self._db = None
        self._subscribed = False
        self._changes_detected = {
            "agents": [],
            "projects": [],
            "memories": [],
            "concepts": [],
            "decisions": [],
        }

    def _ensure_dirs(self) -> None:
        """Crée l'arborescence du vault si elle n'existe pas."""
        for subdir in ["Agents", "Projects", "Knowledge", "Decisions", "Memories"]:
            (self._vault / subdir).mkdir(parents=True, exist_ok=True)

    def _get_db(self):
        if self._db is None:
            from .graph_db import get_graph_db
            self._db = get_graph_db()
        return self._db

    # ── Event Subscription ─────────────────────────────────────────────────────

    def subscribe_to_events(self):
        """
        S'abonne aux événements TASK_COMPLETE et prompt_updated du bus.
        Déclenche sync automatique du vault.
        """
        if self._subscribed:
            return
        try:
            from .forge_event_bus import get_event_bus
            bus = get_event_bus()

            def _on_task_complete(event):
                logger.info("[Curator] TASK_COMPLETE detected → syncing vault")
                try:
                    self.curate({"current_task": event.get("data", {}).get("task", "")})
                except Exception as e:
                    logger.debug(f"[Curator] Auto-sync failed: {e}")

            def _on_prompt_updated(event):
                logger.info("[Curator] prompt_updated detected → full sync")
                try:
                    self.full_sync()
                except Exception as e:
                    logger.debug(f"[Curator] Full sync failed: {e}")

            bus.subscribe("TASK_COMPLETE", _on_task_complete)
            bus.subscribe("prompt_updated", _on_prompt_updated)
            self._subscribed = True
            logger.info("[Curator] Subscribed to TASK_COMPLETE + prompt_updated")
        except Exception as e:
            logger.debug(f"[Curator] Event subscription failed: {e}")

    # ── Curate (post-cycle) ──────────────────────────────────────────────────

    def curate(self, state: dict) -> dict:
        """
        Point d'entrée principal : appelé après chaque cycle Forge.
        Détecte les changements et met à jour le vault.
        """
        self._ensure_dirs()
        db = self._get_db()

        results = {
            "agents_synced": 0,
            "projects_synced": 0,
            "memories_synced": 0,
            "concepts_synced": 0,
            "decisions_synced": 0,
            "mermaid_generated": 0,
            "orphans_found": 0,
        }

        # 1. Sync agent
        agent_name = state.get("dynamic_agent_name", "")
        if agent_name:
            self._sync_agent(state, db)
            results["agents_synced"] = 1

        # 2. Sync project
        task = state.get("current_task", "")
        if task:
            self._sync_project(state, db)
            results["projects_synced"] = 1

        # 3. Sync memories (findings)
        findings = state.get("findings", [])
        for finding in findings:
            if finding.get("status") == "confirmed":
                self._sync_memory(finding, state, db)
                results["memories_synced"] += 1

        # 4. Extract and sync concepts
        concepts = self._extract_concepts(state)
        for concept in concepts:
            self._sync_concept(concept, db)
            results["concepts_synced"] += 1

        # 5. Generate Mermaid for this project
        if task:
            self._generate_project_mermaid(state, db)
            results["mermaid_generated"] = 1

        # 6. Detect orphans — prune low-score, note high-score
        orphans = db.get_orphan_nodes()
        if orphans:
            pruned, kept = self._prune_orphans(orphans, db)
            results["orphans_found"] = len(orphans)
            results["orphans_pruned"] = pruned
            results["orphans_kept"] = kept

        logger.info(f"[Curator] synced: {results}")
        return results

    # ── Full Sync ────────────────────────────────────────────────────────────

    def full_sync(self) -> dict:
        """
        Re-synchronisation complète : régénère tout le vault depuis Kuzu.
        Utile après un changement de schema ou pour régénérer les notes.
        """
        self._ensure_dirs()
        db = self._get_db()

        results = {
            "agents": 0,
            "projects": 0,
            "concepts": 0,
            "memories": 0,
            "decisions": 0,
        }

        # Sync all agents
        agents = db.get_all_nodes("Agent")
        for agent in agents:
            name = agent.get("name", "unknown")
            self._write_agent_note(name, agent, db)
            results["agents"] += 1

        # Sync all projects
        projects = db.get_all_nodes("Project")
        for project in projects:
            name = project.get("name", "unknown")
            self._write_project_note(name, project, db)
            results["projects"] += 1

        # Sync all concepts
        concepts = db.get_all_nodes("Concept")
        for concept in concepts:
            title = concept.get("title", "unknown")
            self._write_concept_note(title, concept, db)
            results["concepts"] += 1

        # Sync all memories
        memories = db.get_all_nodes("MemoryNode")
        for mem in memories:
            mem_id = mem.get("id", "unknown")
            self._write_memory_note(mem_id, mem, db)
            results["memories"] += 1

        # Sync all decisions
        decisions = db.get_all_nodes("Decision")
        for dec in decisions:
            adr_id = dec.get("adr_id", "unknown")
            self._write_decision_note(adr_id, dec, db)
            results["decisions"] += 1

        # Generate orphans note
        orphans = db.get_orphan_nodes()
        if orphans:
            self._generate_orphan_note(orphans)

        logger.info(f"[Curator] full_sync: {results}")
        return results

    # ── Sync Methods ─────────────────────────────────────────────────────────

    def _sync_agent(self, state: dict, db) -> None:
        """Synchronise un agent dans Kuzu et génère la note Obsidian."""
        name = state.get("dynamic_agent_name", "unknown")
        role = state.get("role_tag", "backend")
        prompt = state.get("dynamic_agent_prompt", "")[:200]
        level = state.get("level", "L1")

        verdict = state.get("jury_verdict") or {}
        success_rate = verdict.get("consensus", 0.0) / 10.0 if verdict else 0.0

        db.add_agent(name, level=level, role=role,
                     prompt_preview=prompt, success_rate=success_rate)
        self._write_agent_note(name, {
            "name": name, "level": level, "role": role,
            "prompt_preview": prompt, "success_rate": success_rate,
        }, db)

    def _sync_project(self, state: dict, db) -> None:
        """Synchronise un projet dans Kuzu et génère la note Obsidian."""
        task = state.get("current_task", "unknown")
        cycle = state.get("cycle", 0)
        verdict = state.get("jury_verdict") or {}
        quality = verdict.get("consensus", 0.0) if verdict else 0.0
        status = "completed" if state.get("task_complete") else "active"
        blueprint = state.get("blueprint", "")[:500]

        # Slugify task name for project name
        slug = re.sub(r'[^a-zA-Z0-9_-]', '-', task[:50]).strip('-').lower()
        name = f"{slug}-c{cycle}"

        db.add_project(name, status=status, task=task,
                       cycle=cycle, quality=quality, blueprint=blueprint)

        # Link agent → project
        agent = state.get("dynamic_agent_name", "")
        if agent:
            db.link_agent_project(agent, name)

        self._write_project_note(name, {
            "name": name, "status": status, "task": task,
            "cycle": cycle, "quality": quality, "blueprint": blueprint,
        }, db)

    def _sync_memory(self, finding: dict, state: dict, db) -> None:
        """Synchronise un finding comme MemoryNode dans Kuzu."""
        mem_id = finding.get("id", f"mem-{finding.get('agent', 'unk')}")
        content = finding.get("content", "")[:500]
        score = finding.get("score", 0.0)
        agent = finding.get("agent", "")
        cycle = finding.get("cycle", 0)

        # (a) Seuil de qualité : skip si score trop bas
        if score < MEMORY_SCORE_MIN:
            logger.debug(f"[Curator] skip memory {mem_id}: score {score:.2f} < {MEMORY_SCORE_MIN}")
            return

        db.add_memory(mem_id, summary=content, memory_type="episodic",
                      agent=agent, score=score, cycle=cycle)

        # Link agent → memory
        if agent:
            db.link_agent_memory(agent, mem_id)

        self._write_memory_note(mem_id, {
            "id": mem_id, "summary": content, "memory_type": "episodic",
            "agent": agent, "score": score, "cycle": cycle,
        }, db)

    def _sync_concept(self, concept: dict, db) -> None:
        """Synchronise un concept dans Kuzu et génère la note."""
        title = concept["title"]
        category = concept.get("category", "technical")
        description = concept.get("description", "")

        db.add_concept(title, category=category, description=description)
        self._write_concept_note(title, concept, db)

    def _extract_concepts(self, state: dict) -> list[dict]:
        """Extrait les concepts techniques du state (heuristique, 0 token)."""
        concepts = []
        text = state.get("agent_output", "") + " " + state.get("current_task", "")

        # Patterns techniques courants
        tech_patterns = {
            "framework": ["fastapi", "flask", "django", "react", "vue", "angular", "langchain", "langgraph"],
            "library": ["pydantic", "sqlalchemy", "requests", "pillow", "numpy", "pandas"],
            "tool": ["docker", "kubernetes", "redis", "postgres", "kuzu", "git", "nginx"],
            "concept": ["api", "rest", "graphql", "microservice", "rag", "llm", "embedding"],
            "language": ["python", "javascript", "typescript", "rust", "go"],
        }

        text_lower = text.lower()
        for category, keywords in tech_patterns.items():
            for kw in keywords:
                if kw in text_lower:
                    concepts.append({
                        "title": kw.title(),
                        "category": category,
                        "description": f"Detected in task: {state.get('current_task', '')[:100]}",
                    })

        # Deduplicate
        seen = set()
        unique = []
        for c in concepts:
            if c["title"] not in seen:
                seen.add(c["title"])
                unique.append(c)
        return unique

    # ── Note Generation ──────────────────────────────────────────────────────

    def _write_agent_note(self, name: str, data: dict, db) -> None:
        """Génère une note Obsidian pour un agent."""
        related = db.query_related(name, hops=2, limit=10)
        links = self._format_links(related)

        stats = db.get_agent_stats(name)
        mermaid = db.export_to_mermaid(focus=name, max_nodes=15)

        note = f"""---
type: agent
name: {name}
level: {data.get('level', 'L1')}
role: {data.get('role', 'unknown')}
success_rate: {data.get('success_rate', 0.0)}
updated: {datetime.datetime.now().isoformat(timespec='seconds')}
---

# Agent: {name}

| Propriété | Valeur |
|-----------|--------|
| Niveau | {data.get('level', 'L1')} |
| Rôle | {data.get('role', 'unknown')} |
| Success Rate | {data.get('success_rate', 0.0):.1%} |
| Projets exécutés | {stats.get('projects_executed', 0)} |
| Qualité moyenne | {stats.get('avg_quality', 0.0):.1f}/10 |

## Prompt Preview
```
{data.get('prompt_preview', '(aucun)')}
```

## Relations
{links}

## Graphe
```mermaid
{mermaid}
```

---
*Auto-généré par Knowledge Curator*
"""
        self._vault_file(f"Agents/{name}.md", note)

    def _write_project_note(self, name: str, data: dict, db) -> None:
        """Génère une note Obsidian pour un projet."""
        related = db.query_related(name, hops=2, limit=10)
        links = self._format_links(related)
        mermaid = db.export_to_mermaid(focus=name, max_nodes=15)

        note = f"""---
type: project
name: {name}
status: {data.get('status', 'active')}
cycle: {data.get('cycle', 0)}
quality: {data.get('quality', 0.0)}
updated: {datetime.datetime.now().isoformat(timespec='seconds')}
---

# Projet: {name}

| Propriété | Valeur |
|-----------|--------|
| Tâche | {data.get('task', '?')[:100]} |
| Status | {data.get('status', 'active')} |
| Cycle | {data.get('cycle', 0)} |
| Qualité | {data.get('quality', 0.0):.1f}/10 |

## Blueprint
{data.get('blueprint', '(aucun blueprint)')}

## Relations
{links}

## Exécution LangGraph
```mermaid
{mermaid}
```

---
*Auto-généré par Knowledge Curator*
"""
        self._vault_file(f"Projects/{name}.md", note)

    def _write_concept_note(self, title: str, data: dict, db) -> None:
        """Génère une note Obsidian pour un concept."""
        related = db.query_related(title, hops=2, limit=10)
        links = self._format_links(related)

        note = f"""---
type: concept
title: {title}
category: {data.get('category', 'technical')}
occurrences: {data.get('occurrences', 1)}
updated: {datetime.datetime.now().isoformat(timespec='seconds')}
---

# Concept: {title}

| Propriété | Valeur |
|-----------|--------|
| Catégorie | {data.get('category', 'technical')} |
| Occurrences | {data.get('occurrences', 1)} |

## Description
{data.get('description', '(aucune description)')}

## Relations
{links}

---
*Auto-généré par Knowledge Curator*
"""
        self._vault_file(f"Knowledge/{title}.md", note)

    def _write_memory_note(self, mem_id: str, data: dict, db) -> None:
        """Génère une note Obsidian pour une mémoire épisodique."""
        related = db.query_related(mem_id, hops=2, limit=10)
        links = self._format_links(related)

        note = f"""---
type: memory
id: {mem_id}
memory_type: {data.get('memory_type', 'episodic')}
agent: {data.get('agent', 'unknown')}
score: {data.get('score', 0.0)}
cycle: {data.get('cycle', 0)}
updated: {datetime.datetime.now().isoformat(timespec='seconds')}
---

# Mémoire: {mem_id}

| Propriété | Valeur |
|-----------|--------|
| Type | {data.get('memory_type', 'episodic')} |
| Agent | [[{data.get('agent', 'unknown')}]] |
| Score | {data.get('score', 0.0):.1f}/10 |
| Cycle | {data.get('cycle', 0)} |

## Contenu
{data.get('summary', '(aucun résumé)')}

## Relations
{links}

---
*Auto-généré par Knowledge Curator*
"""
        self._vault_file(f"Memories/{mem_id}.md", note)

    def _write_decision_note(self, adr_id: str, data: dict, db) -> None:
        """Génère une note Obsidian pour une décision architecturale."""
        related = db.query_related(adr_id, hops=2, limit=10)
        links = self._format_links(related)

        note = f"""---
type: decision
adr_id: {adr_id}
title: {data.get('title', '?')}
status: {data.get('status', 'accepted')}
updated: {datetime.datetime.now().isoformat(timespec='seconds')}
---

# {adr_id}: {data.get('title', '?')}

| Propriété | Valeur |
|-----------|--------|
| Status | {data.get('status', 'accepted')} |

## Rationale
{data.get('rationale', '(aucune rationale)')}

## Relations
{links}

---
*Auto-généré par Knowledge Curator*
"""
        self._vault_file(f"Decisions/{adr_id}.md", note)

    def _generate_project_mermaid(self, state: dict, db) -> None:
        """Génère un Mermaid flowchart de l'exécution LangGraph pour le projet."""
        task = state.get("current_task", "unknown")
        slug = re.sub(r'[^a-zA-Z0-9_-]', '-', task[:50]).strip('-').lower()
        cycle = state.get("cycle", 0)
        name = f"{slug}-c{cycle}"

        # Build execution flow from state
        agent = state.get("dynamic_agent_name", "agent")
        verdict = state.get("jury_verdict") or {}
        quality = verdict.get("consensus", 0.0) if verdict else 0.0

        mermaid = f"""```mermaid
graph TD
    A[v6_init] --> B[estimate_budget]
    B --> C[orchestrator]
    C --> D[generate_blueprint]
    D --> E[validate_blueprint]
    E -->|approved| F[{agent}]
    E -->|rejected| D
    F --> G[v6_post_execution]
    G --> H[auto_complexification]
    H -->|continue| C
    H -->|end| I[post_mortem]

    style F fill:#1A3F6B,color:#fff
    style I fill:#F7A711,color:#000
```

**Qualité finale:** {quality:.1f}/10 | **Cycle:** {cycle} | **Agent:** {agent}
"""

        # Update the project note with execution graph
        note_path = self._vault / "Projects" / f"{name}.md"
        if note_path.exists():
            content = note_path.read_text(encoding="utf-8")
            # Append mermaid at the end if not already present
            if "```mermaid" not in content:
                content += f"\n\n## Exécution LangGraph\n{mermaid}"
                note_path.write_text(content, encoding="utf-8")

    def _generate_orphan_note(self, orphans: list[dict]) -> None:
        """Génère une note pour les nodes orphelins."""
        if not orphans:
            return

        orphan_lines = []
        for o in orphans:
            orphan_lines.append(f"- **{o['type']}**: `{o['key']}`")

        note = f"""---
type: meta
updated: {datetime.datetime.now().isoformat(timespec='seconds')}
---

# Concepts Orphelins

Ces nodes dans Kuzu n'ont aucune connexion. Ils doivent être liés ou supprimés.

{chr(10).join(orphan_lines)}

---
*Auto-généré par Knowledge Curator — {len(orphans)} orphelins détectés*
"""
        self._vault_file("Knowledge/_orphans.md", note)

    def _prune_orphans(self, orphans: list[dict], db) -> tuple[int, int]:
        """Prune les orphelins : supprime ceux avec score < ORPHAN_PRUNE_SCORE, note les autres.

        Returns (pruned_count, kept_count).
        """
        pruned = 0
        kept = 0
        high_orphans = []

        for o in orphans:
            label = o["type"]
            key = o["key"]
            # Seuls les MemoryNode ont un score lisible ; les autres → garder (note)
            if label == "MemoryNode":
                try:
                    # Cherche le score du nœud
                    pk = "id"
                    r = db._conn.execute(
                        f"MATCH (n:MemoryNode) WHERE n.{pk} = '{key}' RETURN n.score"
                    )
                    if r.has_next():
                        score = r.get_next()[0] or 0.0
                        if score < ORPHAN_PRUNE_SCORE:
                            db.delete_node(label, key)
                            pruned += 1
                            logger.info(f"[Curator] pruned orphan {label}:{key} (score={score:.2f})")
                            continue
                except Exception:
                    pass
            # Agents, Concepts, etc. sans score → garder + noter
            high_orphans.append(o)
            kept += 1

        # Note les orphelins conservés
        if high_orphans:
            self._generate_orphan_note(high_orphans)

        return pruned, kept

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _format_links(self, related: list[dict]) -> str:
        """Formate les relations en liens Obsidian bidirectionnels."""
        if not related:
            return "(aucune relation)"

        links = []
        for r in related:
            node_type = r.get("node_type", "?")
            name = r.get("name", "?")
            summary = r.get("summary", "")[:80]
            icon = {"Agent": "🤖", "Project": "📁", "Concept": "💡",
                    "MemoryNode": "🧠", "Decision": "📋"}.get(node_type, "📌")
            links.append(f"- {icon} [[{name}]] — {summary}")

        return "\n".join(links)

    def _vault_file(self, rel_path: str, content: str) -> None:
        """Écrit un fichier dans le vault."""
        full_path = self._vault / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        logger.debug(f"[Curator] wrote {full_path}")

    def get_vault_stats(self) -> dict:
        """Retourne les stats du vault."""
        if not self._vault.exists():
            return {"exists": False}

        counts = {}
        for subdir in ["Agents", "Projects", "Knowledge", "Decisions", "Memories"]:
            dir_path = self._vault / subdir
            if dir_path.exists():
                counts[subdir] = len(list(dir_path.glob("*.md")))
            else:
                counts[subdir] = 0

        total = sum(counts.values())
        return {
            "exists": True,
            "total_notes": total,
            "by_folder": counts,
            "vault_path": str(self._vault),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_curator: Optional[KnowledgeCurator] = None

def get_curator() -> KnowledgeCurator:
    global _curator
    if _curator is None:
        _curator = KnowledgeCurator()
    return _curator

def reset_curator() -> None:
    global _curator
    _curator = None


# ── Self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import shutil
    from forge_agents.graph_db import ForgeGraphDB

    test_vault = FORGE_ROOT / "04_GRAPHIFY" / "vault_test"
    test_kuzu = str(FORGE_ROOT / "04_GRAPHIFY" / "kuzu_curator_test")

    # Clean
    if test_vault.exists():
        shutil.rmtree(test_vault, ignore_errors=True)
    p = __import__('pathlib').Path(test_kuzu)
    if p.exists():
        shutil.rmtree(test_kuzu, ignore_errors=True)

    # Setup
    curator = KnowledgeCurator(test_vault)
    curator._db = ForgeGraphDB(test_kuzu)

    # Simulate a Forge state
    mock_state = {
        "current_task": "Build REST API with FastAPI",
        "cycle": 1,
        "level": "L2",
        "dynamic_agent_name": "Backend_Expert",
        "dynamic_agent_prompt": "Tu es un expert backend Python/FastAPI...",
        "role_tag": "backend",
        "blueprint": "## Architecture\n- main.py\n- api/routes.py\n- models/user.py",
        "task_complete": True,
        "jury_verdict": {"consensus": 8.5, "decision": "APPROVED"},
        "agent_output": "Created FastAPI endpoints with Pydantic models and SQLAlchemy ORM.",
        "findings": [
            {"id": "F-BACKEND-001", "agent": "Backend_Expert", "cycle": 1,
             "content": "FastAPI auto-generates OpenAPI docs from type hints",
             "score": 8.0, "status": "confirmed"},
            {"id": "F-BACKEND-002", "agent": "Backend_Expert", "cycle": 1,
             "content": "Pydantic v2 uses Rust-based validation (5x faster)",
             "score": 9.0, "status": "confirmed"},
        ],
    }

    # Curate
    results = curator.curate(mock_state)
    print(f"Curate results: {results}")

    # Check vault
    stats = curator.get_vault_stats()
    print(f"Vault stats: {stats}")

    # Full sync
    full = curator.full_sync()
    print(f"Full sync: {full}")

    # Check a note
    agent_note = test_vault / "Agents" / "Backend_Expert.md"
    if agent_note.exists():
        content = agent_note.read_text(encoding="utf-8")
        print(f"\nAgent note preview:\n{content[:500]}")

    # Cleanup
    curator._db.close()
    shutil.rmtree(test_vault, ignore_errors=True)
    shutil.rmtree(test_kuzu, ignore_errors=True)
    print("\nknowledge_curator: OK")
