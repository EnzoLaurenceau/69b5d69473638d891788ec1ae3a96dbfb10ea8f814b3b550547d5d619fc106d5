"""
graph_db.py — Kuzu Graph Database pour La Forge
================================================
Base de données graphe embarquée (in-process, aucun serveur).
Stocke les relations entre agents, projets, concepts, mémoires et décisions.

Schéma:
  Nodes: Agent, Project, Concept, MemoryNode, Decision
  Edges: EXECUTES, RECALLS, LINKS_TO, DEVIATION_FROM, PRODUCED_BY, DEPENDS_ON

Usage:
    from forge_agents.graph_db import get_graph_db
    db = get_graph_db()
    db.add_agent("Backend_Expert", level="L2")
    db.link_agent_memory("Backend_Expert", "mem-001", "RECALLS")
    results = db.query_related("Backend_Expert", hops=2)
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ForgeGraphDB")

def _esc(value) -> str:
    """Échappe une valeur avant interpolation dans une requête Cypher.

    L'échappement précédent n'échappait que le quote simple, PAS l'antislash : une
    entrée se terminant par un antislash neutralisait alors le quote fermant et
    permettait de sortir de la chaîne. L'antislash doit être échappé EN PREMIER,
    sinon on ré-échappe ses propres échappements.

    Ces valeurs proviennent de sorties de LLM : elles sont non fiables par nature.
    Correctif de fond (hors périmètre ici) : requêtes paramétrées côté driver.

    W6-01 — cette fonction ne s'exécutait PAS. Elle appelait `str.replace_esc(...)`,
    méthode qui n'existe pas : chaque appel levait `AttributeError`, avalé par le
    `try/except` de l'appelant. Le durcissement annoncé en W5-06 n'a donc jamais tourné,
    et les écritures dans le graphe échouaient en silence. D'où `test_graph_db_escaping`,
    qui vérifie le comportement et pas la présence du code.
    """
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _label(value: str, allowed) -> str:
    """Valide un label ou un type d'arête contre la liste connue.

    Un label ne peut pas être passé en paramètre à Cypher : il fait partie de la
    structure de la requête, pas de ses données. La seule défense est donc la liste
    blanche — l'échapper ne servirait à rien.
    """
    if value not in allowed:
        raise ValueError(f"label inconnu: {value!r} — attendu l'un de {sorted(allowed)}")
    return value


def _num(value, default=0):
    """Force une valeur numérique interpolée dans une requête.

    Ces valeurs ne sont pas entre quotes dans la requête : `_esc` ne les protégerait
    pas. Une chaîne qui arrive ici sort directement dans le corps du Cypher.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        logger.warning("valeur numérique invalide %r -> %s", value, default)
        return default
    return int(f) if f.is_integer() else f


FORGE_ROOT = Path(__file__).parent.parent.parent
KUZU_DB_PATH = FORGE_ROOT / "04_GRAPHIFY" / "kuzu_graph"

# ── Node Labels ──────────────────────────────────────────────────────────────
NODE_TABLES = ["Agent", "Project", "Concept", "MemoryNode", "Decision", "Repository"]

# ── Edge Labels ──────────────────────────────────────────────────────────────
EDGE_TABLES = {
    "EXECUTES":      ("Agent", "Project"),
    "RECALLS":       ("Agent", "MemoryNode"),
    "LINKS_TO":      ("MemoryNode", "Concept"),
    "DEVIATION_FROM": ("Project", "Decision"),
    "PRODUCED_BY":   ("MemoryNode", "Agent"),
    "DEPENDS_ON":    ("Project", "Project"),
    "CITES":         ("Concept", "Concept"),
    "REFERENCES":    ("Project", "Repository"),
    "HOSTS_TOOL":    ("Repository", "Concept"),
    "USES":          ("Agent", "Concept"),
}


class ForgeGraphDB:
    """
    Wrapper Kuzu pour le graphe de connaissances de La Forge.
    Lazy init : la DB n'est ouverte qu'au premier appel.
    """

    def __init__(self, db_path: str | Path = KUZU_DB_PATH):
        self._db_path = str(db_path)
        self._db = None
        self._conn = None
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return

        try:
            import kuzu
            # Kuzu crée lui-même le répertoire — ne pas os.makedirs
            parent = os.path.dirname(self._db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._db = kuzu.Database(self._db_path)
            self._conn = kuzu.Connection(self._db)
            self._create_schema()
            self._initialized = True
            logger.info(f"[GraphDB] Kuzu initialized at {self._db_path}")
        except Exception as e:
            logger.error(f"[GraphDB] init failed: {e}")
            raise

    def _create_schema(self) -> None:
        """Crée les tables de nodes et d'edges si elles n'existent pas."""
        conn = self._conn

        # Node tables (PRIMARY KEY inclus dans le schema)
        node_schemas = {
            "Agent":      "name STRING, level STRING, role STRING, prompt_preview STRING, success_rate DOUBLE, created TIMESTAMP, PRIMARY KEY(name)",
            "Project":    "name STRING, status STRING, task STRING, cycle INT64, quality DOUBLE, blueprint STRING, PRIMARY KEY(name)",
            "Concept":    "title STRING, category STRING, description STRING, occurrences INT64, PRIMARY KEY(title)",
            "MemoryNode": "id STRING, summary STRING, memory_type STRING, agent STRING, score DOUBLE, cycle INT64, created TIMESTAMP, PRIMARY KEY(id)",
            "Decision":   "adr_id STRING, title STRING, rationale STRING, status STRING, created TIMESTAMP, PRIMARY KEY(adr_id)",
            "Repository": "url STRING, org STRING, name STRING, description STRING, stars INT64, language STRING, last_push STRING, occurrences INT64, priority DOUBLE, cloned BOOL DEFAULT false, PRIMARY KEY(url)",
        }

        for table, schema in node_schemas.items():
            try:
                conn.execute(f"CREATE NODE TABLE IF NOT EXISTS {table}({schema})")
            except Exception as e:
                logger.debug(f"[GraphDB] node table {table}: {e}")

        # Edge tables
        edge_schemas = {
            "EXECUTES":       "FROM Agent TO Project",
            "RECALLS":        "FROM Agent TO MemoryNode",
            "LINKS_TO":       "FROM MemoryNode TO Concept",
            "DEVIATION_FROM": "FROM Project TO Decision",
            "PRODUCED_BY":    "FROM MemoryNode TO Agent",
            "DEPENDS_ON":     "FROM Project TO Project",
            "CITES":          "FROM Concept TO Concept",
            "REFERENCES":     "FROM Project TO Repository",
            "HOSTS_TOOL":     "FROM Repository TO Concept",
            "USES":           "FROM Agent TO Concept",
        }

        for edge, schema in edge_schemas.items():
            try:
                conn.execute(f"CREATE REL TABLE IF NOT EXISTS {edge}({schema}, weight DOUBLE DEFAULT 1.0, context STRING DEFAULT '')")
            except Exception as e:
                logger.debug(f"[GraphDB] edge table {edge}: {e}")

    # ── CRUD Operations ──────────────────────────────────────────────────────

    def add_agent(self, name: str, level: str = "L1", role: str = "",
                  prompt_preview: str = "", success_rate: float = 0.0) -> bool:
        """Ajoute ou met à jour un agent dans le graphe."""
        self._ensure_init()
        try:
            # Escape single quotes
            name_e = _esc(name)
            role_e = _esc(role)
            prompt_e = _esc(prompt_preview[:200])
            success_rate = _num(success_rate, 0.0)
            
            self._conn.execute(
                f"MATCH (a:Agent) WHERE a.name = '{name_e}' RETURN a.name"
            )
            result = self._conn.execute(f"MATCH (a:Agent) WHERE a.name = '{name_e}' RETURN a.name")
            if result.has_next():
                self._conn.execute(
                    f"MATCH (a:Agent) WHERE a.name = '{name_e}' "
                    f"SET a.level = '{_esc(level)}', a.role = '{role_e}', "
                    f"a.prompt_preview = '{prompt_e}', a.success_rate = {success_rate}"
                )
            else:
                self._conn.execute(
                    f"CREATE (a:Agent {{name: '{name_e}', level: '{_esc(level)}', "
                    f"role: '{role_e}', prompt_preview: '{prompt_e}', "
                    f"success_rate: {success_rate}, created: current_timestamp()}})"
                )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] add_agent({name}): {e}")
            return False

    def add_project(self, name: str, status: str = "active", task: str = "",
                    cycle: int = 0, quality: float = 0.0, blueprint: str = "") -> bool:
        self._ensure_init()
        try:
            name_e = _esc(name)
            task_e = _esc(task[:200])
            bp_e = _esc(blueprint[:500])
            cycle = _num(cycle, 0)
            quality = _num(quality, 0.0)

            result = self._conn.execute(f"MATCH (p:Project) WHERE p.name = '{name_e}' RETURN p.name")
            if result.has_next():
                self._conn.execute(
                    f"MATCH (p:Project) WHERE p.name = '{name_e}' "
                    f"SET p.status = '{_esc(status)}', p.cycle = {cycle}, p.quality = {quality}"
                )
            else:
                self._conn.execute(
                    f"CREATE (p:Project {{name: '{name_e}', status: '{_esc(status)}', "
                    f"task: '{task_e}', cycle: {cycle}, quality: {quality}, "
                    f"blueprint: '{bp_e}'}})"
                )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] add_project({name}): {e}")
            return False

    def add_concept(self, title: str, category: str = "technical",
                    description: str = "") -> bool:
        self._ensure_init()
        try:
            title_e = _esc(title)
            cat_e = _esc(category)
            desc_e = _esc(description[:300])

            result = self._conn.execute(f"MATCH (c:Concept) WHERE c.title = '{title_e}' RETURN c.title")
            if result.has_next():
                self._conn.execute(
                    f"MATCH (c:Concept) WHERE c.title = '{title_e}' "
                    f"SET c.occurrences = c.occurrences + 1"
                )
            else:
                self._conn.execute(
                    f"CREATE (c:Concept {{title: '{title_e}', category: '{cat_e}', "
                    f"description: '{desc_e}', occurrences: 1}})"
                )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] add_concept({title}): {e}")
            return False

    def add_repository(self, url: str, org: str = "", name: str = "",
                       description: str = "", stars: int = 0, language: str = "",
                       last_push: str = "", occurrences: int = 0,
                       priority: float = 0.0, cloned: bool = False) -> bool:
        """Ajoute ou met à jour un dépôt GitHub dans le graphe."""
        self._ensure_init()
        try:
            url_e = _esc(url)
            org_e = _esc(org)
            name_e = _esc(name)
            desc_e = _esc((description or "")[:300])
            lang_e = _esc((language or ""))
            push_e = _esc((last_push or ""))
            stars = _num(stars, 0)
            occurrences = _num(occurrences, 0)
            priority = _num(priority, 0.0)
            cloned = "true" if cloned else "false"

            result = self._conn.execute(
                f"MATCH (r:Repository) WHERE r.url = '{url_e}' RETURN r.url"
            )
            if result.has_next():
                self._conn.execute(
                    f"MATCH (r:Repository) WHERE r.url = '{url_e}' "
                    f"SET r.stars = {stars}, r.occurrences = {occurrences}, "
                    f"r.priority = {priority}, r.cloned = {cloned}"
                )
            else:
                self._conn.execute(
                    f"CREATE (r:Repository {{url: '{url_e}', org: '{org_e}', "
                    f"name: '{name_e}', description: '{desc_e}', stars: {stars}, "
                    f"language: '{lang_e}', last_push: '{push_e}', "
                    f"occurrences: {occurrences}, priority: {priority}, "
                    f"cloned: {cloned}}})"
                )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] add_repository({url}): {e}")
            return False

    def add_memory(self, mem_id: str, summary: str, memory_type: str = "episodic",
                   agent: str = "", score: float = 0.0, cycle: int = 0) -> bool:
        self._ensure_init()
        try:
            id_e = _esc(mem_id)
            summary_e = _esc(summary[:500])
            type_e = _esc(memory_type)
            agent_e = _esc(agent)

            self._conn.execute(
                f"CREATE (m:MemoryNode {{id: '{id_e}', summary: '{summary_e}', "
                f"memory_type: '{type_e}', agent: '{agent_e}', score: {score}, "
                f"cycle: {cycle}, created: current_timestamp()}})"
            )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] add_memory({mem_id}): {e}")
            return False

    def add_decision(self, adr_id: str, title: str, rationale: str = "",
                     status: str = "accepted") -> bool:
        self._ensure_init()
        try:
            adr_e = _esc(adr_id)
            title_e = _esc(title)
            rat_e = _esc(rationale[:500])

            self._conn.execute(
                f"CREATE (d:Decision {{adr_id: '{adr_e}', title: '{title_e}', "
                f"rationale: '{rat_e}', status: '{_esc(status)}', created: current_timestamp()}})"
            )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] add_decision({adr_id}): {e}")
            return False

    # ── Edge Operations ──────────────────────────────────────────────────────

    def create_edge(self, edge_type: str, from_label: str, from_key: str,
                    to_label: str, to_key: str, weight: float = 1.0,
                    context: str = "") -> bool:
        """Crée une relation entre deux nodes."""
        self._ensure_init()
        if edge_type not in EDGE_TABLES:
            logger.warning(f"[GraphDB] unknown edge type: {edge_type}")
            return False
        try:
            # Labels et poids ne sont PAS entre quotes dans la requête : `_esc` ne les
            # protégerait pas. Liste blanche pour la structure, coercition pour le nombre.
            from_label = _label(from_label, NODE_TABLES)
            to_label = _label(to_label, NODE_TABLES)
            weight = _num(weight, 1.0)
            from_key_e = _esc(from_key)
            to_key_e = _esc(to_key)
            ctx_e = _esc(context[:200])

            _PK = {"Agent": "name", "Project": "name", "Concept": "title",
                   "MemoryNode": "id", "Decision": "adr_id", "Repository": "url"}
            from_pk = _PK[from_label]
            to_pk = _PK[to_label]

            self._conn.execute(
                f"MATCH (a:{from_label}), (b:{to_label}) "
                f"WHERE a.{from_pk} = '{from_key_e}' AND b.{to_pk} = '{to_key_e}' "
                f"CREATE (a)-[r:{edge_type} {{weight: {weight}, context: '{ctx_e}'}}]->(b)"
            )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] create_edge({edge_type}): {e}")
            return False

    def link_agent_project(self, agent: str, project: str, context: str = "") -> bool:
        return self.create_edge("EXECUTES", "Agent", agent, "Project", project, context=context)

    def link_agent_memory(self, agent: str, memory_id: str, context: str = "") -> bool:
        return self.create_edge("RECALLS", "Agent", agent, "MemoryNode", memory_id, context=context)

    def link_memory_concept(self, memory_id: str, concept: str, context: str = "") -> bool:
        return self.create_edge("LINKS_TO", "MemoryNode", memory_id, "Concept", concept, context=context)

    def link_project_decision(self, project: str, adr_id: str, context: str = "") -> bool:
        return self.create_edge("DEVIATION_FROM", "Project", project, "Decision", adr_id, context=context)

    def link_project_repository(self, project: str, repo_url: str, context: str = "") -> bool:
        return self.create_edge("REFERENCES", "Project", project, "Repository", repo_url, context=context)

    def link_repository_concept(self, repo_url: str, concept: str, context: str = "") -> bool:
        return self.create_edge("HOSTS_TOOL", "Repository", repo_url, "Concept", concept, context=context)

    # ── Query Operations ─────────────────────────────────────────────────────

    def query_related(self, node_key: str, hops: int = 2, limit: int = 20) -> list[dict]:
        """Trouve tous les nodes reliés jusqu'à N hops."""
        self._ensure_init()
        results = []
        hops = _num(hops, 2)
        limit = _num(limit, 20)
        try:
            # Essayer toutes les combinaisons de node type
            for label in NODE_TABLES:
                pk = "name" if label in ("Agent", "Project", "Concept") else "id" if label == "MemoryNode" else "adr_id" if label == "Decision" else "url"
                key_e = _esc(node_key)
                query = (
                    f"MATCH (a:{label})-[r*1..{hops}]-(b) "
                    f"WHERE a.{pk} = '{key_e}' "
                    f"RETURN DISTINCT label(b) AS node_type, "
                    f"b.name AS name, b.title AS title, b.id AS id, "
                    f"b.summary AS summary "
                    f"LIMIT {limit}"
                )
                result = self._conn.execute(query)
                while result.has_next():
                    row = result.get_next()
                    node_type = row[0] if row[0] else "?"
                    name = row[1] or row[2] or row[3] or "?"
                    summary = row[4] or ""
                    results.append({
                        "node_type": node_type,
                        "name": name,
                        "summary": summary[:200],
                        "hops": hops,
                    })
        except Exception as e:
            logger.debug(f"[GraphDB] query_related({node_key}): {e}")
        return results

    def get_agent_stats(self, agent: str) -> dict:
        """Retourne les stats d'un agent dans le graphe."""
        self._ensure_init()
        try:
            key_e = _esc(agent)
            # Projects executed
            r1 = self._conn.execute(
                f"MATCH (a:Agent)-[:EXECUTES]->(p:Project) "
                f"WHERE a.name = '{key_e}' "
                f"RETURN count(p) AS projects, avg(p.quality) AS avg_quality"
            )
            projects, avg_quality = 0, 0.0
            if r1.has_next():
                row = r1.get_next()
                projects = row[0] or 0
                avg_quality = row[1] or 0.0

            # Memories recalled
            r2 = self._conn.execute(
                f"MATCH (a:Agent)-[:RECALLS]->(m:MemoryNode) "
                f"WHERE a.name = '{key_e}' "
                f"RETURN count(m) AS memories"
            )
            memories = 0
            if r2.has_next():
                memories = r2.get_next()[0] or 0

            return {
                "agent": agent,
                "projects_executed": projects,
                "avg_quality": round(avg_quality, 2),
                "memories_recalled": memories,
            }
        except Exception as e:
            logger.debug(f"[GraphDB] get_agent_stats({agent}): {e}")
            return {"agent": agent, "error": str(e)}

    def get_orphan_nodes(self) -> list[dict]:
        """Trouve les nodes sans aucune connexion (orphelins)."""
        self._ensure_init()
        _PK = {"Agent": "name", "Project": "name", "Concept": "title",
               "MemoryNode": "id", "Decision": "adr_id", "Repository": "url"}
        orphans = []
        try:
            for label in NODE_TABLES:
                pk = _PK[label]
                result = self._conn.execute(
                    f"MATCH (n:{label}) WHERE NOT (n)-[]-() "
                    f"RETURN n.{pk} AS key, label(n) AS type LIMIT 50"
                )
                while result.has_next():
                    row = result.get_next()
                    orphans.append({"type": row[1], "key": row[0]})
        except Exception as e:
            logger.debug(f"[GraphDB] get_orphan_nodes: {e}")
        return orphans

    def delete_node(self, label: str, key: str) -> bool:
        """Supprime un nœud par son label et sa clé primaire."""
        self._ensure_init()
        _PK = {"Agent": "name", "Project": "name", "Concept": "title",
               "MemoryNode": "id", "Decision": "adr_id", "Repository": "url"}
        try:
            label = _label(label, NODE_TABLES)
            pk = _PK[label]
            key_e = _esc(key)
            self._conn.execute(
                f"MATCH (n:{label}) WHERE n.{pk} = '{key_e}' DETACH DELETE n"
            )
            return True
        except Exception as e:
            logger.debug(f"[GraphDB] delete_node({label}, {key}): {e}")
            return False

    def get_all_nodes(self, label: str, limit: int = 100) -> list[dict]:
        """Retourne tous les nodes d'un type donné."""
        self._ensure_init()
        nodes = []
        try:
            label = _label(label, NODE_TABLES)
            limit = _num(limit, 100)
            result = self._conn.execute(f"MATCH (n:{label}) RETURN n.* LIMIT {limit}")
            cols = [c.replace("n.", "") for c in result.get_column_names()]
            while result.has_next():
                row = result.get_next()
                nodes.append(dict(zip(cols, row)))
        except Exception as e:
            logger.debug(f"[GraphDB] get_all_nodes({label}): {e}")
        return nodes

    def count_nodes(self) -> dict:
        """Compte les nodes par type."""
        self._ensure_init()
        counts = {}
        for label in NODE_TABLES:
            try:
                result = self._conn.execute(f"MATCH (n:{label}) RETURN count(n)")
                if result.has_next():
                    counts[label] = result.get_next()[0]
            except Exception:
                counts[label] = 0
        return counts

    def export_to_mermaid(self, focus: str = "", max_nodes: int = 30) -> str:
        """Exporte le graphe en format Mermaid pour Obsidian."""
        self._ensure_init()
        lines = ["graph LR"]
        max_nodes = _num(max_nodes, 50)

        try:
            # Get edges with node names
            for edge_type, (from_label, to_label) in EDGE_TABLES.items():
                from_pk = "name" if from_label in ("Agent", "Project", "Concept") else "id"
                to_pk = "name" if to_label in ("Agent", "Project", "Concept") else "id" if to_label == "MemoryNode" else "adr_id"

                where = ""
                if focus:
                    focus_e = _esc(focus)
                    where = f" WHERE a.{from_pk} = '{focus_e}' OR b.{to_pk} = '{focus_e}'"

                result = self._conn.execute(
                    f"MATCH (a:{from_label})-[r:{edge_type}]->(b:{to_label}){where} "
                    f"RETURN a.{from_pk}, b.{to_pk} LIMIT {max_nodes}"
                )
                while result.has_next():
                    row = result.get_next()
                    a_name = str(row[0]).replace(" ", "_")[:30]
                    b_name = str(row[1]).replace(" ", "_")[:30]
                    arrow = f"-->|{edge_type}|"
                    lines.append(f"    {a_name} {arrow} {b_name}")
        except Exception as e:
            logger.debug(f"[GraphDB] export_to_mermaid: {e}")

        if len(lines) == 1:
            lines.append("    empty[\"Aucune relation trouvée\"]")

        return "\n".join(lines)

    def get_edges(self, focus: str = "", limit: int = 200) -> list[dict]:
        """Arêtes structurées du graphe : `[{source, target, type, source_type, target_type}]`.

        Même source que `export_to_mermaid` (les `EDGE_TABLES` connues), mais rendue en JSON
        pour la neural map de la console — nœuds typés + relations typées (pivot/expand).
        `focus` restreint aux arêtes touchant une entité donnée.
        """
        self._ensure_init()
        edges: list[dict] = []
        limit = _num(limit, 200)
        try:
            for edge_type, (from_label, to_label) in EDGE_TABLES.items():
                from_pk = "name" if from_label in ("Agent", "Project", "Concept") else "id"
                to_pk = "name" if to_label in ("Agent", "Project", "Concept") else "id" if to_label == "MemoryNode" else "adr_id"
                where = ""
                if focus:
                    focus_e = _esc(focus)
                    where = f" WHERE a.{from_pk} = '{focus_e}' OR b.{to_pk} = '{focus_e}'"
                result = self._conn.execute(
                    f"MATCH (a:{from_label})-[r:{edge_type}]->(b:{to_label}){where} "
                    f"RETURN a.{from_pk}, b.{to_pk} LIMIT {limit}"
                )
                while result.has_next():
                    row = result.get_next()
                    edges.append({
                        "source": str(row[0]), "target": str(row[1]),
                        "type": edge_type,
                        "source_type": from_label, "target_type": to_label,
                    })
        except Exception as e:
            logger.debug(f"[GraphDB] get_edges: {e}")
        return edges

    def close(self) -> None:
        """Ferme la connexion Kuzu."""
        self._conn = None
        self._db = None
        self._initialized = False

    def repair_orphans(self) -> dict:
        """Répare les nœuds orphelins en créant des arêtes manquantes.

        Stratégie :
        - Agent orphelin → USES edge vers un Concept générique 'forge_system'
        - MemoryNode orphelin → PRODUCED_BY edge vers Agent 'knowledge_blender'
        - Autres orphelins → rapportés mais non connectés (pas d'arête légitime)

        Retourne {repaired: int, skipped: int, details: list[str]}.
        """
        self._ensure_init()
        orphans = self.get_orphan_nodes()
        repaired = 0
        skipped = 0
        details: list[str] = []

        # S'assurer que les cibles existent
        self.add_concept("forge_system", category="system",
                         description="Concept racine pour les agents orphelins")
        self.add_agent("knowledge_blender", level="L1",
                       role="rag_kag_feedback")

        for orphan in orphans:
            otype = orphan["type"]
            okey = orphan["key"]

            if otype == "Agent":
                # Agent orphelin → USES forge_system (ancre le graphe)
                try:
                    self.create_edge("USES", "Agent", okey,
                                     "Concept", "forge_system",
                                     context="orphan_repair")
                    repaired += 1
                    details.append(f"Agent:{okey} → USES → Concept:forge_system")
                except Exception as e:
                    skipped += 1
                    details.append(f"Agent:{okey} SKIP: {e}")

            elif otype == "MemoryNode":
                # MemoryNode orphelin → PRODUCED_BY knowledge_blender
                try:
                    self.create_edge("PRODUCED_BY", "MemoryNode", okey,
                                     "Agent", "knowledge_blender",
                                     context="orphan_repair")
                    repaired += 1
                    details.append(f"MemoryNode:{okey} → PRODUCED_BY → Agent:knowledge_blender")
                except Exception as e:
                    skipped += 1
                    details.append(f"MemoryNode:{okey} SKIP: {e}")

            else:
                skipped += 1
                details.append(f"{otype}:{okey} — pas de stratégie de réparation")

        return {"repaired": repaired, "skipped": skipped, "details": details,
                "total_orphans": len(orphans)}


# ── Singleton ────────────────────────────────────────────────────────────────

_graph_db: Optional[ForgeGraphDB] = None

def get_graph_db() -> ForgeGraphDB:
    global _graph_db
    if _graph_db is None:
        _graph_db = ForgeGraphDB()
    return _graph_db

def reset_graph_db() -> None:
    global _graph_db
    if _graph_db:
        _graph_db.close()
    _graph_db = None


# ── Self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import shutil
    test_path = FORGE_ROOT / "04_GRAPHIFY" / "kuzu_test"
    if test_path.exists():
        shutil.rmtree(test_path)

    db = ForgeGraphDB(test_path)

    # Add nodes
    db.add_agent("Backend_Expert", level="L2", role="backend")
    db.add_agent("Security_Auditor", level="L3", role="security")
    db.add_project("rest-api-build", status="active", task="Build REST API", quality=7.5)
    db.add_concept("FastAPI", category="framework")
    db.add_concept("Pydantic", category="library")
    db.add_memory("mem-001", "Used FastAPI for REST endpoints", agent="Backend_Expert", score=8.0)
    db.add_decision("ADR-001", "Use FastAPI over Flask", rationale="Async support, type hints")

    # Create edges
    db.link_agent_project("Backend_Expert", "rest-api-build")
    db.link_agent_memory("Backend_Expert", "mem-001")
    db.link_memory_concept("mem-001", "FastAPI")
    db.link_project_decision("rest-api-build", "ADR-001")
    db.create_edge("CITES", "Concept", "FastAPI", "Concept", "Pydantic", context="data validation")

    # Query
    related = db.query_related("Backend_Expert", hops=2)
    print(f"Related to Backend_Expert: {len(related)} nodes")
    for r in related:
        print(f"  {r['node_type']}: {r['name']}")

    # Stats
    stats = db.get_agent_stats("Backend_Expert")
    print(f"Agent stats: {stats}")

    # Mermaid
    mermaid = db.export_to_mermaid()
    print(f"\nMermaid:\n{mermaid}")

    # Counts
    counts = db.count_nodes()
    print(f"Node counts: {counts}")

    # Orphans
    orphans = db.get_orphan_nodes()
    print(f"Orphans: {len(orphans)}")

    db.close()
    shutil.rmtree(test_path)
    print("\nforge_graph_db self-check: OK")
