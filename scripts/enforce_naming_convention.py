"""
enforce_naming_convention.py — Restructurateur & Enforceur de Nommage
======================================================================
Plan A §2 : Renomme les fichiers selon la convention unifiée.

Convention:
  Skills:    SKL_[domain]_[action]_[topic]_[ver].json
  Findings:  FND_[agent]_[topic]_[task-slug].json
  Tools:     tool_[domain]_[action]_[target].py
  Obsidian:  AGT_[name].md, ADR_[num]_[topic].md, PRJ_[slug].md

Usage:
    python scripts/enforce_naming_convention.py
    python scripts/enforce_naming_convention.py --dry-run
    python scripts/enforce_naming_convention.py --skills-only
    python scripts/enforce_naming_convention.py --findings-only
"""

from __future__ import annotations
import argparse
import json
import logging
import re
import shutil
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("NamingConvention")

FORGE_ROOT = Path(__file__).parent.parent
SKILLS_DIR = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
FINDINGS_DIR = FORGE_ROOT / "06_FINDINGS"
VAULT_DIR = FORGE_ROOT / "vault"


def slugify(text: str, max_len: int = 30) -> str:
    """Convertit un texte en slug propre."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text[:max_len].strip('_')


def extract_domain(task_type: str, name: str) -> str:
    """Extrait le domaine à partir du task_type ou du nom."""
    domain_map = {
        "security": "security",
        "audit": "security",
        "build": "dev",
        "code": "dev",
        "research": "research",
        "marketing": "marketing",
        "landing": "marketing",
        "data": "data",
        "scraping": "data",
        "optimization": "opti",
        "token": "opti",
        "forge": "forge",
        "agent": "forge",
    }
    combined = (task_type + " " + name).lower()
    for key, domain in domain_map.items():
        if key in combined:
            return domain
    return "general"


def extract_action(content: str, name: str) -> str:
    """Extrait l'action principale."""
    action_map = {
        "create": "create",
        "créer": "create",
        "build": "build",
        "construire": "build",
        "analyze": "analyze",
        "analyser": "analyze",
        "audit": "audit",
        "scan": "scan",
        "optimize": "optimize",
        "optimiser": "optimize",
        "test": "test",
        "deploy": "deploy",
        "setup": "setup",
        "configure": "config",
    }
    combined = (content + " " + name).lower()
    for key, action in action_map.items():
        if key in combined:
            return action
    return "manage"


def rename_skill_file(skill_path: Path, dry_run: bool = False) -> tuple[str, str]:
    """Renomme un fichier skill selon la convention SKL_[domain]_[action]_[topic]_[ver].json."""
    try:
        data = json.loads(skill_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        logger.warning(f"Cannot parse {skill_path.name}: {e}")
        return skill_path.name, skill_path.name

    name = data.get("name", skill_path.stem)
    task_type = data.get("task_type", "")
    prompt = data.get("prompt", "")
    skill_id = data.get("id", skill_path.stem)

    # Extract components
    domain = extract_domain(task_type, name)
    action = extract_action(prompt, name)
    topic = slugify(name, max_len=25)

    # Generate new name
    new_name = f"SKL_{domain}_{action}_{topic}_v1.json"

    # Avoid collisions
    new_path = skill_path.parent / new_name
    counter = 2
    while new_path.exists() and new_path != skill_path:
        new_name = f"SKL_{domain}_{action}_{topic}_v{counter}.json"
        new_path = skill_path.parent / new_name
        counter += 1

    if new_name == skill_path.name:
        return skill_path.name, skill_path.name

    if not dry_run:
        # Update internal id
        data["id"] = new_name.replace(".json", "")
        data["naming_version"] = "v1"
        new_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        if new_path != skill_path:
            skill_path.unlink(missing_ok=True)

    return skill_path.name, new_name


def rename_finding_file(finding_path: Path, dry_run: bool = False) -> tuple[str, str]:
    """Renomme un fichier finding selon la convention FND_[agent]_[topic]_[slug].json."""
    try:
        data = json.loads(finding_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        logger.warning(f"Cannot parse {finding_path.name}: {e}")
        return finding_path.name, finding_path.name

    agent = data.get("agent", "unknown")
    title = data.get("title", finding_path.stem)
    finding_id = data.get("id", finding_path.stem)

    # Extract components
    agent_slug = slugify(agent, max_len=15)
    topic_slug = slugify(title, max_len=25)

    # Generate new name
    new_name = f"FND_{agent_slug}_{topic_slug}.json"

    # Avoid collisions
    new_path = finding_path.parent / new_name
    counter = 2
    while new_path.exists() and new_path != finding_path:
        new_name = f"FND_{agent_slug}_{topic_slug}_{counter}.json"
        new_path = finding_path.parent / new_name
        counter += 1

    if new_name == finding_path.name:
        return finding_path.name, finding_path.name

    if not dry_run:
        data["id"] = new_name.replace(".json", "")
        data["naming_version"] = "v1"
        new_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        if new_path != finding_path:
            finding_path.unlink(missing_ok=True)

    return finding_path.name, new_name


def update_indexes():
    """Met à jour les index qui référencent les anciens noms."""
    # Update tool_index.json if exists
    tool_index = FORGE_ROOT / "05_STATE" / "tool_index.json"
    if tool_index.exists():
        try:
            data = json.loads(tool_index.read_text(encoding="utf-8"))
            # Re-index skills
            if isinstance(data, list):
                for item in data:
                    if "path" in item:
                        p = Path(item["path"])
                        if p.exists():
                            item["path"] = str(p)
            tool_index.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Updated tool_index.json")
        except Exception as e:
            logger.debug(f"tool_index update skipped: {e}")


def rename_tool_file(tool_path: Path, dry_run: bool = False) -> tuple[str, str]:
    """Renomme un fichier tool selon la convention tool_[domain]_[action]_[target].py."""
    try:
        content = tool_path.read_text(encoding="utf-8", errors="replace")[:2000]
    except Exception:
        return tool_path.name, tool_path.name

    name = tool_path.stem

    # Skip already compliant
    if name.startswith("tool_"):
        return tool_path.name, tool_path.name

    # Extract domain and action from content/name
    domain = extract_domain("", name)
    action = extract_action(content, name)
    target = slugify(name, max_len=25)

    new_name = f"tool_{domain}_{action}_{target}.py"

    new_path = tool_path.parent / new_name
    counter = 2
    while new_path.exists() and new_path != tool_path:
        new_name = f"tool_{domain}_{action}_{target}_{counter}.py"
        new_path = tool_path.parent / new_name
        counter += 1

    if new_name == tool_path.name:
        return tool_path.name, tool_path.name

    if not dry_run:
        shutil.copy2(tool_path, new_path)
        if new_path != tool_path:
            tool_path.unlink(missing_ok=True)

    return tool_path.name, new_name


def main():
    parser = argparse.ArgumentParser(description="Enforce naming convention")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--skills-only", action="store_true", help="Skills only")
    parser.add_argument("--findings-only", action="store_true", help="Findings only")
    parser.add_argument("--tools-only", action="store_true", help="Tools only")
    args = parser.parse_args()

    renamed_skills = []
    renamed_findings = []
    renamed_tools = []

    # 1. Rename skills
    if not args.findings_only and not args.tools_only:
        logger.info(f"Processing skills in {SKILLS_DIR}...")
        if SKILLS_DIR.exists():
            for skill_file in sorted(SKILLS_DIR.glob("*.json")):
                if skill_file.name.startswith("SKL_"):
                    logger.info(f"  Already compliant: {skill_file.name}")
                    continue
                old, new = rename_skill_file(skill_file, dry_run=args.dry_run)
                if old != new:
                    renamed_skills.append((old, new))
                    logger.info(f"  {old} → {new}")
                else:
                    logger.info(f"  Unchanged: {old}")

    # 2. Rename findings
    if not args.skills_only:
        logger.info(f"Processing findings in {FINDINGS_DIR}...")
        for subdir in ("confirmed", "pending"):
            findings_dir = FINDINGS_DIR / subdir
            if findings_dir.exists():
                for finding_file in sorted(findings_dir.glob("*.json")):
                    if finding_file.name == "FINDING_TEMPLATE.json":
                        continue
                    if finding_file.name.startswith("FND_"):
                        logger.info(f"  Already compliant: {finding_file.name}")
                        continue
                    old, new = rename_finding_file(finding_file, dry_run=args.dry_run)
                    if old != new:
                        renamed_findings.append((old, new))
                        logger.info(f"  {old} → {new}")
                    else:
                        logger.info(f"  Unchanged: {old}")

    # 2b. Rename tools
    if not args.skills_only and not args.findings_only:
        scripts_dir = FORGE_ROOT / "scripts"
        logger.info(f"Processing tools in {scripts_dir}...")
        if scripts_dir.exists():
            for tool_file in sorted(scripts_dir.glob("*.py")):
                if tool_file.name == "__init__.py":
                    continue
                if tool_file.name.startswith("tool_"):
                    logger.info(f"  Already compliant: {tool_file.name}")
                    continue
                # Skip this script itself
                if tool_file.name == "enforce_naming_convention.py":
                    continue
                old, new = rename_tool_file(tool_file, dry_run=args.dry_run)
                if old != new:
                    renamed_tools.append((old, new))
                    logger.info(f"  {old} → {new}")
                else:
                    logger.info(f"  Unchanged: {old}")

    # 3. Update indexes
    if not args.dry_run and (renamed_skills or renamed_findings):
        update_indexes()

    # Summary
    logger.info(f"\n{'='*50}")
    logger.info(f"Skills renamed: {len(renamed_skills)}")
    logger.info(f"Findings renamed: {len(renamed_findings)}")
    logger.info(f"Tools renamed: {len(renamed_tools)}")
    if args.dry_run:
        logger.info("(DRY-RUN — no files were actually renamed)")


if __name__ == "__main__":
    main()
