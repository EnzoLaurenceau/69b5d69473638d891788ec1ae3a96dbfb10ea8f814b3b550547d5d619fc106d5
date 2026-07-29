"""
forge_data_tagger.py — Universal Data Tagging & Naming Convention Engine
==========================================================================
Make data hygiene a PROACTIVE HABIT for the Forge.
Every piece of data collected gets tagged with metadata automatically.

Convention: [PREFIX]_[DOMAIN]_[TYPE]_[SLUG]_[DATE].[ext]

Prefixes:
  SKL_  — Skills (L3 knowledge)
  FND_  — Findings (agent discoveries)
  TKL_  — Token logs (usage tracking)
  SPRT_ — Sprints (iteration reports)
  AGT_  — Agents (personas)
  STT_  — State files (runtime)
  SCR_  — Scripts (tools)
  VLT_  — Vault notes (Obsidian)
  RPO_  — External repos
  RPT_  — Reports (benchmarks, audits)
  CFG_  — Configuration files
  LOG_  — Execution logs

Auto-tagging:
  Every file written by the Forge gets:
  1. Correct prefix in filename
  2. Metadata header (JSON frontmatter for .md, _meta key for .json)
  3. Tags array for searchability
  4. Source traceability (agent, session, task)

Usage:
    from forge_agents.forge_data_tagger import get_tagger
    tagger = get_tagger()
    
    # Auto-tag on write
    tagger.tag_file(path, data_type="skill", domain="security", source="agent_x")
    
    # Audit all data
    report = tagger.audit_all()
    
    # Fix naming
    tagger.fix_naming(dry_run=False)
"""

from __future__ import annotations
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("DataTagger")

FORGE_ROOT = Path(__file__).parent.parent.parent

# ─── Naming Convention Map ───────────────────────────────────────────────────

PREFIX_MAP = {
    "skill": "SKL",
    "finding": "FND",
    "token_log": "TKL",
    "sprint": "SPRT",
    "agent": "AGT",
    "state": "STT",
    "script": "SCR",
    "vault": "VLT",
    "repo": "RPO",
    "report": "RPT",
    "config": "CFG",
    "log": "LOG",
}

DOMAIN_MAP = {
    "security": "sec",
    "audit": "sec",
    "build": "dev",
    "code": "dev",
    "research": "res",
    "marketing": "mkt",
    "landing": "mkt",
    "data": "dat",
    "scraping": "dat",
    "optimization": "opt",
    "token": "opt",
    "forge": "frg",
    "agent": "frg",
    "general": "gen",
    "rag": "rag",
    "cache": "cac",
    "llm": "llm",
    "ui": "ui",
    "dashboard": "ui",
}


def slugify(text: str, max_len: int = 30) -> str:
    """Clean slug for filenames."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text[:max_len].strip('_')


def infer_domain(text: str) -> str:
    """Infer domain from text content."""
    text_lower = text.lower()
    for keyword, domain in DOMAIN_MAP.items():
        if keyword in text_lower:
            return domain
    return "gen"


@dataclass
class DataTag:
    """Metadata tag for any Forge data."""
    prefix: str
    domain: str
    data_type: str
    slug: str
    date: str
    source: str = ""
    session_id: str = ""
    task: str = ""
    tags: list[str] = field(default_factory=list)
    version: int = 1

    def to_filename(self, ext: str = "json") -> str:
        """Generate compliant filename."""
        base = f"{self.prefix}_{self.domain}_{self.data_type}_{self.slug}"
        if self.version > 1:
            base += f"_v{self.version}"
        return f"{base}_{self.date}.{ext}"

    def to_metadata(self) -> dict:
        """Generate metadata dict for embedding in file."""
        return {
            "_tag": {
                "prefix": self.prefix,
                "domain": self.domain,
                "data_type": self.data_type,
                "slug": self.slug,
                "date": self.date,
                "source": self.source,
                "session_id": self.session_id,
                "task": self.task[:200] if self.task else "",
                "tags": self.tags,
                "version": self.version,
                "tagged_at": datetime.now().isoformat(),
            }
        }


class ForgeDataTagger:
    """Universal data tagging engine."""

    def __init__(self):
        self._convention_log: list[dict] = []

    def create_tag(
        self,
        data_type: str,
        name: str = "",
        content: str = "",
        domain: str = "",
        source: str = "",
        session_id: str = "",
        task: str = "",
        tags: list[str] = None,
    ) -> DataTag:
        """Create a DataTag for new data."""
        prefix = PREFIX_MAP.get(data_type, "UNK")
        if not domain:
            domain = infer_domain(name + " " + content)
        slug = slugify(name or content[:50] or "unnamed")
        date = datetime.now().strftime("%Y%m%d")

        return DataTag(
            prefix=prefix,
            domain=domain,
            data_type=data_type,
            slug=slug,
            date=date,
            source=source,
            session_id=session_id,
            task=task,
            tags=tags or [],
        )

    def tag_file(self, path: Path, data_type: str, **kwargs) -> Path:
        """
        Tag a file with metadata. Returns the (possibly renamed) path.
        
        For .json files: adds _meta key
        For .md files: adds YAML frontmatter
        """
        path = Path(path)
        if not path.exists():
            return path

        tag = self.create_tag(data_type=data_type, name=path.stem, **kwargs)

        # Add metadata to file content
        if path.suffix == ".json":
            self._tag_json(path, tag)
        elif path.suffix == ".md":
            self._tag_markdown(path, tag)

        # Rename if not compliant
        if not self._is_compliant(path.name, data_type):
            new_name = tag.to_filename(path.suffix.lstrip('.'))
            new_path = path.parent / new_name
            counter = 2
            while new_path.exists() and new_path != path:
                tag.version = counter
                new_name = tag.to_filename(path.suffix.lstrip('.'))
                new_path = path.parent / new_name
                counter += 1

            if new_path != path:
                path.rename(new_path)
                self._convention_log.append({
                    "old": path.name,
                    "new": new_name,
                    "type": data_type,
                    "timestamp": datetime.now().isoformat(),
                })
                logger.info(f"[Tagger] {path.name} → {new_name}")
                return new_path

        return path

    def _tag_json(self, path: Path, tag: DataTag):
        """Add _meta key to JSON file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                data["_meta"] = tag.to_metadata()["_tag"]
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[Tagger] Failed to tag JSON {path.name}: {e}")

    def _tag_markdown(self, path: Path, tag: DataTag):
        """Add YAML frontmatter to markdown file."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if content.startswith("---"):
                return  # Already has frontmatter

            meta = tag.to_metadata()["_tag"]
            frontmatter = f"""---
prefix: {meta['prefix']}
domain: {meta['domain']}
type: {meta['data_type']}
slug: {meta['slug']}
date: {meta['date']}
source: {meta['source']}
tags: [{', '.join(meta['tags'])}]
tagged_at: {meta['tagged_at']}
---

"""
            path.write_text(frontmatter + content, encoding="utf-8")
        except Exception as e:
            logger.debug(f"[Tagger] Failed to tag MD {path.name}: {e}")

    def _is_compliant(self, filename: str, data_type: str) -> bool:
        """Check if filename follows convention."""
        prefix = PREFIX_MAP.get(data_type, "UNK")
        return filename.startswith(f"{prefix}_")

    def audit_all(self) -> dict:
        """Audit all data in the Forge for compliance."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "directories": {},
            "total_files": 0,
            "compliant": 0,
            "non_compliant": 0,
            "missing_metadata": 0,
        }

        # Audit each directory
        dirs_to_audit = [
            ("07_KNOWLEDGE_BASE/skills", "skill"),
            ("06_FINDINGS/confirmed", "finding"),
            ("06_FINDINGS/pending", "finding"),
            ("08_LOGS/tokens", "token_log"),
            ("08_LOGS/sprints", "sprint"),
            ("02_AGENTS", "agent"),
            ("05_STATE", "state"),
            ("scripts", "script"),
            ("vault", "vault"),
        ]

        for dir_rel, data_type in dirs_to_audit:
            dir_path = FORGE_ROOT / dir_rel
            if not dir_path.exists():
                continue

            dir_report = {
                "total": 0,
                "compliant": 0,
                "non_compliant": [],
                "missing_meta": [],
            }

            for f in dir_path.rglob("*"):
                if f.is_dir():
                    continue
                if f.name in (".gitkeep", "__init__.py", "AGENTS.md"):
                    continue

                dir_report["total"] += 1
                report["total_files"] += 1

                prefix = PREFIX_MAP.get(data_type, "UNK")
                if f.name.startswith(f"{prefix}_"):
                    dir_report["compliant"] += 1
                    report["compliant"] += 1
                else:
                    dir_report["non_compliant"].append(f.name)
                    report["non_compliant"] += 1

                # Check metadata
                if f.suffix == ".json":
                    try:
                        d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                        if isinstance(d, dict) and "_meta" not in d:
                            dir_report["missing_meta"].append(f.name)
                            report["missing_metadata"] += 1
                    except:
                        pass

            report["directories"][dir_rel] = dir_report

        return report

    def fix_naming(self, dry_run: bool = False) -> dict:
        """Fix all non-compliant filenames."""
        results = {"renamed": 0, "errors": []}

        # Fix skills
        skills_dir = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
        if skills_dir.exists():
            for f in skills_dir.glob("*.json"):
                if not f.name.startswith("SKL_"):
                    try:
                        self.tag_file(f, data_type="skill", dry_run=dry_run)
                        results["renamed"] += 1
                    except Exception as e:
                        results["errors"].append(f"{f.name}: {e}")

        # Fix findings
        for subdir in ("confirmed", "pending"):
            findings_dir = FORGE_ROOT / "06_FINDINGS" / subdir
            if findings_dir.exists():
                for f in findings_dir.glob("*.json"):
                    if not f.name.startswith("FND_") and f.name != "FINDING_TEMPLATE.json":
                        try:
                            self.tag_file(f, data_type="finding", dry_run=dry_run)
                            results["renamed"] += 1
                        except Exception as e:
                            results["errors"].append(f"{f.name}: {e}")

        return results


# Singleton
_instance: ForgeDataTagger | None = None


def get_tagger() -> ForgeDataTagger:
    global _instance
    if _instance is None:
        _instance = ForgeDataTagger()
    return _instance
