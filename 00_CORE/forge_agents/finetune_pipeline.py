"""
finetune_pipeline.py — Fine-Tuning Pipeline Manager pour la Forge
==================================================================
Gère l'ingestion, la validation, et la préparation de TOUS les datasets
de fine-tuning de la Forge. Point d'entrée unique pour alimenter
n'importe quel framework de fine-tuning (Axolotl, Unsloth, LLaMA-Factory).

Architecture :
  07_KNOWLEDGE_BASE/datasets/
    ├── claude_mythos_25k/     → Downloaded & converted
    ├── forge_experience/      → Auto-generated from Forge execution logs
    └── custom/                → User-added datasets

Ce module :
  1. Scanne tous les datasets disponibles dans 07_KNOWLEDGE_BASE/datasets/
  2. Valide la qualité (format, doublons, longueur min/max)
  3. Fusionne en un dataset unifié prêt pour fine-tuning
  4. Exporte en format cible (ChatML par défaut)

Usage :
  from forge_agents.finetune_pipeline import get_finetune_pipeline
  pipe = get_finetune_pipeline()
  pipe.prepare(output_format="chatml", max_samples=10000)
"""

from __future__ import annotations

import json
import hashlib
import logging
import datetime
from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("FinetunePipeline")

FORGE_ROOT = Path(__file__).parent.parent.parent


def _kb_base() -> Path:
    """Base des datasets fine-tuning. Cloisonnée par tenant (W5-03c) quand il y en a un
    — le dataset est construit sur les expériences du client, donc lui appartient. Sans
    tenant en contexte → base KB historique (07_KNOWLEDGE_BASE) pour l'usage opérateur."""
    try:
        from .forge_tenant import current_tenant_or_none
        from . import forge_store
    except Exception:
        return FORGE_ROOT / "07_KNOWLEDGE_BASE"
    if current_tenant_or_none() is not None:
        return forge_store.tenant_dir() / "07_KNOWLEDGE_BASE"
    return FORGE_ROOT / "07_KNOWLEDGE_BASE"


def _datasets_root() -> Path:
    return _kb_base() / "datasets"


def _ft_output() -> Path:
    return _kb_base() / "finetune_ready"

OutputFormat = Literal["chatml", "sharegpt", "alpaca"]


# ─── DATA QUALITY ────────────────────────────────────────────────────────────

@dataclass
class QualityReport:
    """Report from dataset quality validation."""
    total_rows: int = 0
    valid_rows: int = 0
    duplicates: int = 0
    too_short: int = 0
    too_long: int = 0
    empty_fields: int = 0
    format_errors: int = 0

    @property
    def quality_score(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.valid_rows / self.total_rows

    def summary(self) -> str:
        return (
            f"Quality: {self.quality_score:.1%} "
            f"({self.valid_rows}/{self.total_rows} valid, "
            f"{self.duplicates} dupes, {self.too_short} short, "
            f"{self.too_long} long, {self.empty_fields} empty)"
        )


@dataclass
class DatasetEntry:
    """Metadata for a registered dataset."""
    id: str
    name: str
    path: Path
    rows: int = 0
    format: str = "chatml"
    quality: Optional[QualityReport] = None
    status: str = "pending"  # pending | validated | merged | error


# ─── PIPELINE ────────────────────────────────────────────────────────────────

class FinetunePipeline:
    """
    Central pipeline for all fine-tuning data in the Forge.
    Scans, validates, merges, and exports datasets.
    """

    def __init__(self):
        self._datasets: list[DatasetEntry] = []
        self._seen_hashes: set[str] = set()
        _datasets_root().mkdir(parents=True, exist_ok=True)
        _ft_output().mkdir(parents=True, exist_ok=True)

    # ── SCAN ──────────────────────────────────────────────────────────────────

    def scan_datasets(self) -> list[DatasetEntry]:
        """Scan all dataset directories in 07_KNOWLEDGE_BASE/datasets/."""
        self._datasets = []

        datasets_root = _datasets_root()
        if not datasets_root.exists():
            return self._datasets
        for dataset_dir in datasets_root.iterdir():
            if not dataset_dir.is_dir():
                continue

            # Look for known formats
            for fmt in ("chatml", "sharegpt", "alpaca", "raw"):
                jsonl_path = dataset_dir / f"{fmt}.jsonl"
                if jsonl_path.exists():
                    rows = sum(1 for _ in open(jsonl_path, "r", encoding="utf-8"))
                    entry = DatasetEntry(
                        id=dataset_dir.name,
                        name=dataset_dir.name.replace("_", " ").title(),
                        path=jsonl_path,
                        rows=rows,
                        format=fmt,
                        status="pending",
                    )
                    self._datasets.append(entry)
                    logger.info(f"Found dataset: {entry.id} ({fmt}, {rows} rows)")
                    break  # Prefer first found format

        # Also check for forge_experience auto-generated data
        exp_dir = _datasets_root() / "forge_experience"
        if exp_dir.exists():
            for jsonl_file in exp_dir.glob("*.jsonl"):
                rows = sum(1 for _ in open(jsonl_file, "r", encoding="utf-8"))
                self._datasets.append(DatasetEntry(
                    id=f"forge_exp_{jsonl_file.stem}",
                    name=f"Forge Experience ({jsonl_file.stem})",
                    path=jsonl_file,
                    rows=rows,
                    format="chatml",
                    status="pending",
                ))

        return self._datasets

    # ── VALIDATE ──────────────────────────────────────────────────────────────

    def validate_dataset(self, entry: DatasetEntry,
                         min_len: int = 20,
                         max_len: int = 32000) -> QualityReport:
        """
        Validate a dataset for fine-tuning quality.
        Checks: format, duplicates, content length, empty fields.
        """
        report = QualityReport()
        # Use a LOCAL hash set for validation — never pollute self._seen_hashes
        # which is reserved for the merge/dedup phase in prepare().
        local_hashes: set[str] = set()

        with open(entry.path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                report.total_rows += 1

                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    report.format_errors += 1
                    continue

                # Extract messages based on format
                messages = self._extract_messages(row, entry.format)
                if not messages:
                    report.empty_fields += 1
                    continue

                # Content length check
                total_content = " ".join(m.get("content", "") for m in messages)
                if len(total_content) < min_len:
                    report.too_short += 1
                    continue
                if len(total_content) > max_len:
                    report.too_long += 1
                    continue

                # Duplicate check (hash-based, LOCAL to this dataset)
                content_hash = hashlib.md5(total_content.encode()).hexdigest()
                if content_hash in local_hashes:
                    report.duplicates += 1
                    continue
                local_hashes.add(content_hash)

                report.valid_rows += 1

        entry.quality = report
        # Low threshold: datasets with natural near-duplicates are still valid
        entry.status = "validated" if report.quality_score >= 0.1 else "error"
        logger.info(f"[{entry.id}] {report.summary()}")
        return report

    # ── MERGE & EXPORT ────────────────────────────────────────────────────────

    def prepare(self, output_format: OutputFormat = "chatml",
                max_samples: Optional[int] = None,
                include_forge_experience: bool = True) -> Path:
        """
        Full pipeline: scan → validate → merge → export.
        Returns path to the merged output file.
        """
        ft_output = _ft_output()
        # 1. Scan
        self.scan_datasets()
        if not self._datasets:
            logger.warning("No datasets found in 07_KNOWLEDGE_BASE/datasets/")
            return ft_output

        # 2. Validate all
        for entry in self._datasets:
            if not include_forge_experience and entry.id.startswith("forge_exp_"):
                continue
            self.validate_dataset(entry)

        # 3. Merge validated datasets
        valid_entries = [e for e in self._datasets if e.status == "validated"]
        if not valid_entries:
            logger.error("No valid datasets after validation!")
            return ft_output

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = ft_output / f"forge_ft_{output_format}_{timestamp}.jsonl"

        total_written = 0
        self._seen_hashes.clear()  # Reset for dedup

        with open(output_path, "w", encoding="utf-8") as fout:
            for entry in valid_entries:
                with open(entry.path, "r", encoding="utf-8") as fin:
                    for line in fin:
                        if max_samples and total_written >= max_samples:
                            break

                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        messages = self._extract_messages(row, entry.format)
                        if not messages or len(messages) < 2:
                            continue

                        # Dedup
                        content = " ".join(m.get("content", "") for m in messages)
                        h = hashlib.md5(content.encode()).hexdigest()
                        if h in self._seen_hashes:
                            continue
                        self._seen_hashes.add(h)

                        # Convert to target format
                        converted = self._convert_row(messages, output_format)
                        if converted:
                            fout.write(json.dumps(converted, ensure_ascii=False) + "\n")
                            total_written += 1

                if max_samples and total_written >= max_samples:
                    break

        # 4. Save manifest
        manifest = {
            "created_at": datetime.datetime.now().isoformat(),
            "output_format": output_format,
            "output_path": str(output_path),
            "total_rows": total_written,
            "source_datasets": [
                {
                    "id": e.id,
                    "rows": e.rows,
                    "quality": asdict(e.quality) if e.quality else None,
                }
                for e in valid_entries
            ],
        }
        manifest_path = ft_output / f"manifest_{timestamp}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        logger.info(f"Fine-tuning data ready: {total_written} rows → {output_path}")
        logger.info(f"Manifest: {manifest_path}")

        # 5. Print summary
        print("\n" + "=" * 60)
        print("  FORGE FINE-TUNING PIPELINE — COMPLETE")
        print("=" * 60)
        print(f"  Format:       {output_format}")
        print(f"  Total rows:   {total_written}")
        print(f"  Output:       {output_path}")
        print(f"  Manifest:     {manifest_path}")
        print(f"  Sources:      {len(valid_entries)} datasets")
        for e in valid_entries:
            qs = e.quality.quality_score if e.quality else 0
            print(f"    • {e.id}: {e.rows} rows (quality={qs:.0%})")
        print("=" * 60)

        return output_path

    # ── FORGE EXPERIENCE GENERATOR ────────────────────────────────────────────

    def generate_forge_experience(self) -> int:
        """
        Auto-generate fine-tuning data from Forge execution history.
        Sources:
          - 06_FINDINGS/ (confirmed findings = good completions)
          - 05_STATE/adaptive_rag_log.jsonl (task→context→strategy patterns)
          - 07_KNOWLEDGE_BASE/skills/ (KB-SKILL-*.json = validated skills)
          - 08_LOGS/ (successful execution traces)
        
        This creates proprietary training data unique to YOUR Forge instance.
        """
        exp_dir = _datasets_root() / "forge_experience"
        exp_dir.mkdir(parents=True, exist_ok=True)
        output_path = exp_dir / "forge_experience.jsonl"

        count = 0

        with open(output_path, "w", encoding="utf-8") as fout:
            # 1. KB Skills → instruction/response pairs
            skills_dir = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
            if skills_dir.exists():
                for skill_file in skills_dir.glob("KB-SKILL-*.json"):
                    try:
                        skill = json.loads(skill_file.read_text(encoding="utf-8"))
                        if skill.get("status") == "active":
                            messages = [
                                {"role": "system", "content": "You are an expert AI assistant trained by the Forge multi-agent system."},
                                {"role": "user", "content": f"Execute this task: {skill.get('name', '')}. Keywords: {', '.join(skill.get('trigger_keywords', []))}"},
                                {"role": "assistant", "content": skill.get("prompt", "")},
                            ]
                            fout.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
                            count += 1
                    except Exception:
                        continue

            # 2. Confirmed findings → high-quality completions
            findings_dir = FORGE_ROOT / "06_FINDINGS" / "confirmed"
            if findings_dir.exists():
                for finding_file in findings_dir.glob("*.json"):
                    try:
                        finding = json.loads(finding_file.read_text(encoding="utf-8"))
                        if finding.get("score", 0) >= 7.5:
                            messages = [
                                {"role": "system", "content": "You are an expert AI assistant. Provide detailed, high-quality analysis."},
                                {"role": "user", "content": f"Analyze: {finding.get('agent', '')} task context"},
                                {"role": "assistant", "content": finding.get("content", "")},
                            ]
                            fout.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
                            count += 1
                    except Exception:
                        continue

            # 3. Patterns → expert reasoning examples
            patterns_dir = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "patterns"
            if patterns_dir.exists():
                for pat_file in patterns_dir.glob("KB-PAT-*.json"):
                    try:
                        pat = json.loads(pat_file.read_text(encoding="utf-8"))
                        messages = [
                            {"role": "system", "content": "You are a meta-AI system that learns from successful patterns."},
                            {"role": "user", "content": "What is a proven pattern for this type of task?"},
                            {"role": "assistant", "content": pat.get("content", "")},
                        ]
                        fout.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
                        count += 1
                    except Exception:
                        continue

        logger.info(f"Forge experience: {count} entries → {output_path}")
        return count

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _extract_messages(self, row: dict, fmt: str) -> list[dict]:
        """Extract messages from a row in the given format."""
        if fmt == "chatml":
            return row.get("messages", [])
        elif fmt == "sharegpt":
            convs = row.get("conversations", [])
            return [
                {"role": {"human": "user", "gpt": "assistant", "system": "system"}.get(c.get("from", ""), c.get("from", "")),
                 "content": c.get("value", "")}
                for c in convs
            ]
        elif fmt == "alpaca":
            msgs = []
            if row.get("instruction"):
                user_content = row["instruction"]
                if row.get("input"):
                    user_content += "\n\n" + row["input"]
                msgs.append({"role": "user", "content": user_content})
            if row.get("output"):
                msgs.append({"role": "assistant", "content": row["output"]})
            return msgs
        elif fmt == "raw":
            # Try auto-detect
            if "messages" in row:
                return row["messages"]
            if "conversations" in row:
                return self._extract_messages(row, "sharegpt")
            if "instruction" in row or "prompt" in row:
                return self._extract_messages(row, "alpaca")
        return []

    def _convert_row(self, messages: list[dict], target_format: OutputFormat) -> Optional[dict]:
        """Convert a list of messages to the target format."""
        if target_format == "chatml":
            return {"messages": messages}
        elif target_format == "sharegpt":
            convs = [
                {"from": {"user": "human", "assistant": "gpt", "system": "system"}.get(m["role"], m["role"]),
                 "value": m["content"]}
                for m in messages
            ]
            return {"conversations": convs}
        elif target_format == "alpaca":
            instruction = ""
            output = ""
            for m in messages:
                if m["role"] == "user" and not instruction:
                    instruction = m["content"]
                elif m["role"] == "assistant" and not output:
                    output = m["content"]
            if instruction and output:
                return {"instruction": instruction, "input": "", "output": output}
        return None


# ─── Singleton ───────────────────────────────────────────────────────────────

_pipeline: Optional[FinetunePipeline] = None


def get_finetune_pipeline() -> FinetunePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = FinetunePipeline()
    return _pipeline


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Forge Fine-Tuning Pipeline")
    parser.add_argument("--format", choices=["chatml", "sharegpt", "alpaca"],
                        default="chatml")
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--generate-experience", action="store_true",
                        help="Also generate fine-tuning data from Forge execution history")
    args = parser.parse_args()

    pipe = get_finetune_pipeline()

    if args.generate_experience:
        pipe.generate_forge_experience()

    pipe.prepare(output_format=args.format, max_samples=args.max_samples)
