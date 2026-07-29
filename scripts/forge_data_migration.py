"""
forge_data_migration.py — One-shot migration + pipeline integration
====================================================================
Fixes all non-compliant data and integrates auto-tagging into the pipeline.

Usage:
    python scripts/forge_data_migration.py
    python scripts/forge_data_migration.py --dry-run
    python scripts/forge_data_migration.py --add-meta-only  # no rename
"""

from __future__ import annotations
import argparse
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("DataMigration")

FORGE_ROOT = Path(__file__).parent.parent


def add_metadata_to_json(path: Path, data_type: str, domain: str = "gen", dry_run: bool = False):
    """Add _meta key to JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return
        if "_meta" in data:
            return  # Already tagged

        meta = {
            "prefix": data_type.upper()[:3],
            "domain": domain,
            "type": data_type,
            "source": "migration",
            "tagged_at": datetime.now().isoformat(),
            "original_name": path.name,
        }

        if not dry_run:
            data["_meta"] = meta
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"  {'[DRY] ' if dry_run else ''}Meta added: {path.name}")
    except Exception as e:
        logger.debug(f"  Skip {path.name}: {e}")


def rename_file(path: Path, new_name: str, dry_run: bool = False) -> Path:
    """Rename file if needed."""
    if path.name == new_name:
        return path

    new_path = path.parent / new_name
    counter = 2
    while new_path.exists() and new_path != path:
        stem = new_name.rsplit('.', 1)[0]
        ext = new_name.rsplit('.', 1)[1] if '.' in new_name else ''
        new_name = f"{stem}_{counter}.{ext}" if ext else f"{stem}_{counter}"
        new_path = path.parent / new_name
        counter += 1

    if not dry_run:
        path.rename(new_path)
    logger.info(f"  {'[DRY] ' if dry_run else ''}{path.name} → {new_name}")
    return new_path


def migrate_token_logs(dry_run: bool = False):
    """Migrate token logs to TKL_ prefix."""
    logger.info("=== Token Logs ===")
    tokens_dir = FORGE_ROOT / "08_LOGS" / "tokens"
    if not tokens_dir.exists():
        return

    for f in sorted(tokens_dir.glob("*.json")):
        if f.name.startswith("TKL_"):
            continue

        # Extract date from filename
        parts = f.stem.split("_")
        date_str = ""
        for p in parts:
            if len(p) == 8 and p.isdigit():
                date_str = p
                break

        # Determine domain from content
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            task = data.get("task_name", data.get("task", ""))
            domain = "gen"
            for kw, d in {"security": "sec", "build": "dev", "research": "res",
                         "marketing": "mkt", "forge": "frg", "optimization": "opt"}.items():
                if kw in task.lower():
                    domain = d
                    break
        except:
            domain = "gen"
            data = {}

        new_name = f"TKL_{domain}_{f.stem}_{date_str or 'nodate'}.json"
        rename_file(f, new_name, dry_run)
        add_metadata_to_json(tokens_dir / new_name, "token_log", domain, dry_run)


def migrate_state_files(dry_run: bool = False):
    """Add metadata to state files (don't rename — they're referenced by code)."""
    logger.info("=== State Files ===")
    state_dir = FORGE_ROOT / "05_STATE"
    if not state_dir.exists():
        return

    for f in sorted(state_dir.glob("*.json")):
        if f.name.startswith("STT_"):
            continue
        # Don't rename state files — they're referenced by code
        add_metadata_to_json(f, "state", "frg", dry_run)


def migrate_agent_files(dry_run: bool = False):
    """Add metadata to agent files."""
    logger.info("=== Agent Files ===")
    agents_dir = FORGE_ROOT / "02_AGENTS"
    if not agents_dir.exists():
        return

    for f in sorted(agents_dir.rglob("*.json")):
        if f.name in ("personas.json", "config.json", "sources.json"):
            add_metadata_to_json(f, "agent", "frg", dry_run)


def migrate_skill_metadata(dry_run: bool = False):
    """Add metadata to skills that are missing it."""
    logger.info("=== Skill Metadata ===")
    skills_dir = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
    if not skills_dir.exists():
        return

    for f in sorted(skills_dir.glob("*.json")):
        add_metadata_to_json(f, "skill", "gen", dry_run)


def clean_pycache(dry_run: bool = False):
    """Remove .pyc files from scripts/."""
    logger.info("=== Clean __pycache__ ===")
    scripts_dir = FORGE_ROOT / "scripts"
    if not scripts_dir.exists():
        return

    for f in scripts_dir.glob("*.pyc"):
        if not dry_run:
            f.unlink()
        logger.info(f"  {'[DRY] ' if dry_run else ''}Removed: {f.name}")


def main():
    parser = argparse.ArgumentParser(description="Data migration")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--add-meta-only", action="store_true", help="Add metadata, no rename")
    args = parser.parse_args()

    logger.info(f"{'DRY-RUN ' if args.dry_run else ''}Starting data migration...")

    migrate_skill_metadata(args.dry_run)
    migrate_state_files(args.dry_run)
    migrate_agent_files(args.dry_run)

    if not args.add_meta_only:
        migrate_token_logs(args.dry_run)

    clean_pycache(args.dry_run)

    logger.info("\nDone!")


if __name__ == "__main__":
    main()
