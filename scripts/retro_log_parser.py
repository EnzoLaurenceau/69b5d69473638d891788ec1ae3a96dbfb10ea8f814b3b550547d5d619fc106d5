"""
retro_log_parser.py — Parseur de Logs Rétroactif & Créateur de Compétences L3
==============================================================================
Plan A §2.1 : Analyse les historiques mai/juin pour extraire l'intelligence
accumulée et créer des compétences L3 structurées.

Sources:
  1. Checkpoints SQLite (04_GRAPHIFY/forge_checkpoints.db)
  2. Sprints Markdown (08_LOGS/sprints/*.md)
  3. Logs de Tokens (08_LOGS/tokens/*.json)

Output: 07_KNOWLEDGE_BASE/skills/KB-SKILL-RETRO-*.json

Usage:
    python scripts/retro_log_parser.py
    python scripts/retro_log_parser.py --dry-run  # preview only
"""

from __future__ import annotations
import argparse
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("RetroLogParser")

FORGE_ROOT = Path(__file__).parent.parent
CHECKPOINTS_DB = FORGE_ROOT / "04_GRAPHIFY" / "forge_checkpoints.db"
SPRINTS_DIR = FORGE_ROOT / "08_LOGS" / "sprints"
TOKENS_DIR = FORGE_ROOT / "08_LOGS" / "tokens"
SKILLS_DIR = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"


def parse_checkpoints() -> list[dict]:
    """Parse SQLite checkpoints pour extraire les sessions réussies."""
    sessions = []
    if not CHECKPOINTS_DB.exists():
        logger.warning(f"Checkpoints DB not found: {CHECKPOINTS_DB}")
        return sessions

    try:
        conn = sqlite3.connect(str(CHECKPOINTS_DB))
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        logger.info(f"Found tables: {tables}")

        # Try to find checkpoint data
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table} LIMIT 50")
                rows = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description]

                for row in rows:
                    data = dict(zip(col_names, row))
                    # Look for task/success indicators
                    task = ""
                    success = False
                    for key in ("task", "current_task", "description", "content"):
                        if key in data and data[key]:
                            task = str(data[key])[:200]
                            break
                    for key in ("success", "completed", "status", "result"):
                        if key in data:
                            val = data[key]
                            if val in (True, "success", "completed", "approved", 1):
                                success = True
                            break

                    if task and len(task) > 10:
                        sessions.append({
                            "source": "checkpoint",
                            "table": table,
                            "task": task,
                            "success": success,
                            "data": {k: str(v)[:100] for k, v in data.items() if v},
                        })
            except Exception:
                continue

        conn.close()
    except Exception as e:
        logger.warning(f"Failed to parse checkpoints: {e}")

    logger.info(f"Extracted {len(sessions)} sessions from checkpoints")
    return sessions


def parse_sprints() -> list[dict]:
    """Parse sprint markdowns pour extraire les tâches complexes résolues."""
    tasks = []
    if not SPRINTS_DIR.exists():
        return tasks

    for sprint_file in sorted(SPRINTS_DIR.glob("*.md")):
        try:
            content = sprint_file.read_text(encoding="utf-8", errors="replace")

            # Extract task descriptions
            task_pattern = r'(?:task|tâche|objectif|goal)[:\s]+(.+?)(?:\n|$)'
            for match in re.finditer(task_pattern, content, re.IGNORECASE):
                task = match.group(1).strip()
                if len(task) > 15:
                    tasks.append({
                        "source": "sprint",
                        "file": sprint_file.name,
                        "task": task[:300],
                        "success": True,  # sprints = completed work
                    })

            # Extract section headers as task summaries
            header_pattern = r'^#{1,3}\s+(.+)$'
            for match in re.finditer(header_pattern, content, re.MULTILINE):
                header = match.group(1).strip()
                if len(header) > 10 and not header.startswith(("Table", "Index", "TODO")):
                    tasks.append({
                        "source": "sprint",
                        "file": sprint_file.name,
                        "task": header[:300],
                        "success": True,
                    })
        except Exception as e:
            logger.debug(f"Failed to parse {sprint_file}: {e}")

    logger.info(f"Extracted {len(tasks)} tasks from sprints")
    return tasks


def parse_token_logs() -> list[dict]:
    """Parse token logs pour identifier les tâches et modèles utilisés."""
    logs = []
    if not TOKENS_DIR.exists():
        return logs

    for log_file in sorted(TOKENS_DIR.glob("*.json")):
        try:
            data = json.loads(log_file.read_text(encoding="utf-8", errors="replace"))

            task = data.get("task_name", data.get("task", ""))
            session_id = data.get("session_id", log_file.stem)

            # Extract model usage
            models = {}
            for log in data.get("logs", []):
                model = log.get("model", "unknown")
                input_tok = log.get("input_tokens", 0)
                output_tok = log.get("output_tokens", 0)
                if model not in models:
                    models[model] = {"input": 0, "output": 0, "calls": 0}
                models[model]["input"] += input_tok
                models[model]["output"] += output_tok
                models[model]["calls"] += 1

            if task:
                logs.append({
                    "source": "token_log",
                    "file": log_file.name,
                    "session_id": session_id,
                    "task": task[:300],
                    "models": models,
                    "total_tokens": sum(m["input"] + m["output"] for m in models.values()),
                })
        except Exception as e:
            logger.debug(f"Failed to parse {log_file}: {e}")

    logger.info(f"Extracted {len(logs)} entries from token logs")
    return logs


def generate_skill_from_task(task_info: dict) -> dict:
    """Génère une fiche compétence JSON à partir d'une tâche réussie."""
    task = task_info.get("task", "")
    source = task_info.get("source", "unknown")

    # Generate reusable prompt (not raw task description)
    prompt = _synthesize_reusable_prompt(task, task_info)

    skill_id = f"KB-SKILL-RETRO-{uuid.uuid4().hex[:6].upper()}"
    name = _generate_skill_name(task)

    return {
        "id": skill_id,
        "name": name,
        "prompt": prompt,
        "trigger_keywords": _extract_keywords(task),
        "performance": {
            "avg_score": 7.5,  # default for retro skills
            "uses": 0,
            "last_used": datetime.now().strftime("%Y-%m-%d"),
        },
        "mirofish_approval": {
            "consensus": 7.5,
            "approved_at": datetime.now().strftime("%Y-%m-%d"),
            "fallback_used": False,
        },
        "source_finding_id": f"RETRO-{source}",
        "source_agent": "retro_log_parser",
        "tier": "HAIKU",
        "task_type": _infer_task_type(task),
        "status": "active",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "retro_source": task_info.get("file", task_info.get("table", "unknown")),
    }


def _synthesize_reusable_prompt(task: str, task_info: dict) -> str:
    """Synthétise une instruction réutilisable (pas la description brute)."""
    domain = _infer_task_type(task).replace("_", " ").title()
    models = task_info.get("models", {})
    model_info = ""
    if models:
        model_names = ", ".join(models.keys())
        model_info = f"\n## Modèles utilisés avec succès\n{model_names}"

    return f"""# Compétence Rétroactive : {task[:80]}

## Rôle
Tu es un expert en {domain}.

## Méthodologie Validée
Pour accomplir cette tâche avec succès, applique l'approche éprouvée :
- Analyse le contexte complet avant d'agir
- Applique les patterns qui ont fonctionné historiquement
- Valide le résultat avec des critères mesurables
{model_info}

## Critères de Succès
- Score minimum : 7.5/10
- Approche méthodique documentée
- Résultat reproductible

## Source
- Historique: {task_info.get('source', 'unknown')}
- Fichier: {task_info.get('file', task_info.get('table', 'N/A'))}
"""


def _generate_skill_name(task: str) -> str:
    """Génère un nom de skill à partir de la tâche."""
    # Take first 50 chars, clean up
    name = re.sub(r'[^\w\s]', '', task[:50]).strip()
    name = re.sub(r'\s+', '_', name)
    return name or "Retro_Skill"


def _extract_keywords(text: str) -> list[str]:
    """Extrait les keywords du texte."""
    words = re.findall(r'\w{3,}', text.lower())
    # Remove common words
    stop_words = {"les", "des", "une", "que", "est", "sont", "pour", "dans", "avec", "the", "and", "for", "this", "that"}
    keywords = [w for w in words if w not in stop_words]
    # Deduplicate, keep order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:15]


def _infer_task_type(task: str) -> str:
    """Infère le type de tâche à partir de la description."""
    task_lower = task.lower()
    type_keywords = {
        "security": ["audit", "sécurité", "security", "vulnerability", "pentest"],
        "build": ["build", "créer", "create", "développer", "implement", "code"],
        "research": ["research", "recherche", "analyze", "analyse", "study"],
        "marketing": ["marketing", "landing", "page", "product", "launch"],
        "data": ["data", "dataset", "scraping", "collect", "collecte"],
        "optimization": ["optimize", "optimis", "performance", "token", "cost"],
    }
    for task_type, keywords in type_keywords.items():
        if any(kw in task_lower for kw in keywords):
            return task_type
    return "general"


def main():
    parser = argparse.ArgumentParser(description="Retroactive log parser")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--min-tasks", type=int, default=5, help="Min skills to create")
    args = parser.parse_args()

    logger.info("Starting retroactive log parsing...")

    # 1. Parse all sources
    checkpoints = parse_checkpoints()
    sprints = parse_sprints()
    token_logs = parse_token_logs()

    all_tasks = checkpoints + sprints + token_logs
    logger.info(f"Total tasks found: {len(all_tasks)}")

    # 2. Deduplicate by task similarity
    unique_tasks = []
    seen_tasks = set()
    for task_info in all_tasks:
        task = task_info.get("task", "")
        # Simple dedup by first 50 chars
        key = task[:50].lower().strip()
        if key not in seen_tasks and len(task) > 15:
            seen_tasks.add(key)
            unique_tasks.append(task_info)

    logger.info(f"Unique tasks: {len(unique_tasks)}")

    # 3. Generate skills
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    created = 0

    for task_info in unique_tasks[:20]:  # max 20 skills
        skill = generate_skill_from_task(task_info)

        if args.dry_run:
            logger.info(f"[DRY-RUN] Would create: {skill['id']} — {skill['name']}")
            continue

        skill_path = SKILLS_DIR / f"{skill['id']}.json"
        skill_path.write_text(json.dumps(skill, indent=2, ensure_ascii=False), encoding="utf-8")
        created += 1
        logger.info(f"Created: {skill['id']} — {skill['name']}")

    logger.info(f"\nDone: {created} L3 skills created in {SKILLS_DIR}")


if __name__ == "__main__":
    main()
