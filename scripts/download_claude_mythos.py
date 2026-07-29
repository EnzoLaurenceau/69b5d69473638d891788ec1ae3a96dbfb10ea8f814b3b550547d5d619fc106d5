"""
download_claude_mythos.py — Dataset Downloader & Fine-Tuning Formatter
========================================================================
Télécharge WithinUsAI/claude_mythos_distilled_25k depuis HuggingFace
et le convertit en formats fine-tuning multiples.

Formats de sortie :
  - chatml.jsonl       → ChatML (OpenAI / Axolotl / Unsloth)
  - sharegpt.jsonl     → ShareGPT (LLaMA-Factory)
  - alpaca.jsonl       → Alpaca (Stanford format)
  - raw.jsonl          → Dump brut du dataset

Usage :
  python scripts/download_claude_mythos.py
  python scripts/download_claude_mythos.py --format chatml
  python scripts/download_claude_mythos.py --output-dir ./my_data
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "datasets" / "claude_mythos_25k"
DATASET_ID = "WithinUsAI/claude_mythos_distilled_25k"


# ─── INSTALL DEPENDENCIES ────────────────────────────────────────────────────

def _ensure_deps():
    """Install datasets + huggingface_hub if missing."""
    for pkg in ("datasets", "huggingface_hub"):
        try:
            __import__(pkg)
        except ImportError:
            log.info(f"Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


# ─── DOWNLOAD ────────────────────────────────────────────────────────────────

def download_dataset(output_dir: Path) -> dict:
    """
    Download the dataset using the `datasets` library.
    Returns metadata dict with row count, columns, etc.
    """
    _ensure_deps()
    from datasets import load_dataset

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw.jsonl"

    log.info(f"Downloading {DATASET_ID} from HuggingFace...")
    
    try:
        ds = load_dataset(DATASET_ID, split="train")
    except Exception as e:
        log.error(f"datasets lib failed: {e}")
        log.info("Trying huggingface-cli fallback...")
        hf_cache = output_dir / "_hf_cache"
        subprocess.run(
            ["huggingface-cli", "download", DATASET_ID,
             "--repo-type", "dataset", "--local-dir", str(hf_cache)],
            check=True
        )
        # Try loading from local cache
        ds = load_dataset(str(hf_cache), split="train")

    # Dump raw
    log.info(f"Dataset loaded: {len(ds)} rows, columns={ds.column_names}")
    with open(raw_path, "w", encoding="utf-8") as f:
        for row in ds:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    meta = {
        "dataset_id": DATASET_ID,
        "rows": len(ds),
        "columns": ds.column_names,
        "raw_path": str(raw_path),
        "size_bytes": raw_path.stat().st_size,
    }

    # Save metadata
    (output_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info(f"Raw dataset saved to {raw_path} ({meta['size_bytes'] / 1_000_000:.1f} MB)")
    return meta


# ─── FORMAT CONVERTERS ───────────────────────────────────────────────────────

def _detect_columns(row: dict) -> dict:
    """
    Auto-detect column mapping from the dataset.
    Supports common HF dataset schemas.
    """
    mapping = {}

    # Instruction/input/output (Alpaca-style)
    for key in ("instruction", "prompt", "question", "input"):
        if key in row:
            mapping["instruction"] = key
            break

    for key in ("output", "response", "answer", "completion"):
        if key in row:
            mapping["output"] = key
            break

    # Context/input field
    for key in ("input", "context"):
        if key in row and key != mapping.get("instruction"):
            mapping["context"] = key
            break

    # Conversations field (ShareGPT-native)
    for key in ("conversations", "messages", "chat"):
        if key in row:
            mapping["conversations"] = key
            break

    # System prompt
    for key in ("system", "system_prompt", "system_message"):
        if key in row:
            mapping["system"] = key
            break

    return mapping


def _extract_messages(row: dict, col_map: dict) -> list[dict]:
    """
    Extract a list of {role, content} messages from a row,
    regardless of source format.
    """
    # If dataset has native conversations
    if "conversations" in col_map:
        convs = row.get(col_map["conversations"], [])
        if isinstance(convs, list) and len(convs) > 0:
            messages = []
            for c in convs:
                if isinstance(c, dict):
                    role = c.get("role", c.get("from", "user"))
                    content = c.get("content", c.get("value", ""))
                    # Normalize roles
                    if role in ("human", "user"):
                        role = "user"
                    elif role in ("gpt", "assistant", "bot", "model"):
                        role = "assistant"
                    elif role in ("system",):
                        role = "system"
                    messages.append({"role": role, "content": content})
            return messages

    # Instruction/output format
    messages = []

    # System message if present
    if "system" in col_map:
        sys_msg = row.get(col_map["system"], "")
        if sys_msg:
            messages.append({"role": "system", "content": sys_msg})

    # User message
    instruction = row.get(col_map.get("instruction", ""), "")
    context = row.get(col_map.get("context", ""), "")
    if context and context != instruction:
        user_content = f"{instruction}\n\n{context}"
    else:
        user_content = instruction
    if user_content:
        messages.append({"role": "user", "content": user_content})

    # Assistant response
    output = row.get(col_map.get("output", ""), "")
    if output:
        messages.append({"role": "assistant", "content": output})

    return messages


def convert_to_chatml(raw_path: Path, output_path: Path) -> int:
    """
    Convert to ChatML format (OpenAI fine-tuning / Axolotl / Unsloth).
    Format: {"messages": [{"role": "...", "content": "..."}]}
    """
    count = 0
    col_map = None

    with open(raw_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            if col_map is None:
                col_map = _detect_columns(row)
                log.info(f"Column mapping: {col_map}")

            messages = _extract_messages(row, col_map)
            if len(messages) >= 2:  # At least user + assistant
                fout.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
                count += 1

    log.info(f"ChatML: {count} conversations → {output_path}")
    return count


def convert_to_sharegpt(raw_path: Path, output_path: Path) -> int:
    """
    Convert to ShareGPT format (LLaMA-Factory).
    Format: {"conversations": [{"from": "human/gpt", "value": "..."}]}
    """
    count = 0
    col_map = None

    with open(raw_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            if col_map is None:
                col_map = _detect_columns(row)

            messages = _extract_messages(row, col_map)
            if len(messages) >= 2:
                conversations = []
                for m in messages:
                    from_field = {"user": "human", "assistant": "gpt", "system": "system"}.get(
                        m["role"], m["role"]
                    )
                    conversations.append({"from": from_field, "value": m["content"]})
                fout.write(json.dumps({"conversations": conversations}, ensure_ascii=False) + "\n")
                count += 1

    log.info(f"ShareGPT: {count} conversations → {output_path}")
    return count


def convert_to_alpaca(raw_path: Path, output_path: Path) -> int:
    """
    Convert to Alpaca format (Stanford).
    Format: {"instruction": "...", "input": "...", "output": "..."}
    """
    count = 0
    col_map = None

    with open(raw_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            if col_map is None:
                col_map = _detect_columns(row)

            messages = _extract_messages(row, col_map)

            # Extract instruction (first user msg) and output (first assistant msg)
            instruction = ""
            input_text = ""
            output_text = ""

            for m in messages:
                if m["role"] == "user" and not instruction:
                    instruction = m["content"]
                elif m["role"] == "assistant" and not output_text:
                    output_text = m["content"]

            if instruction and output_text:
                entry = {
                    "instruction": instruction,
                    "input": input_text,
                    "output": output_text,
                }
                fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1

    log.info(f"Alpaca: {count} entries → {output_path}")
    return count


# ─── FORGE KB INTEGRATION ────────────────────────────────────────────────────

def register_in_forge_kb(output_dir: Path, meta: dict) -> None:
    """
    Register the dataset in the Forge Knowledge Base index.
    Creates a dataset entry in 07_KNOWLEDGE_BASE/index.json.
    """
    kb_index_path = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "index.json"
    if not kb_index_path.exists():
        return

    try:
        index = json.loads(kb_index_path.read_text(encoding="utf-8"))
    except Exception:
        index = {}

    # Add datasets section
    datasets = index.setdefault("datasets", [])

    # Check if already registered
    if any(d.get("id") == "claude_mythos_25k" for d in datasets):
        log.info("Dataset already registered in KB index, updating...")
        datasets[:] = [d for d in datasets if d.get("id") != "claude_mythos_25k"]

    datasets.append({
        "id": "claude_mythos_25k",
        "name": "Claude Mythos Distilled 25k",
        "source": DATASET_ID,
        "rows": meta["rows"],
        "columns": meta["columns"],
        "path": str(output_dir),
        "formats": ["raw", "chatml", "sharegpt", "alpaca"],
        "purpose": "fine-tuning",
        "status": "ready",
    })

    kb_index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Dataset registered in Forge KB index ✓")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download & format claude_mythos_distilled_25k")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Output directory for dataset files")
    parser.add_argument("--format", choices=["all", "chatml", "sharegpt", "alpaca"],
                        default="all", help="Output format(s) to generate")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip download, only convert existing raw.jsonl")
    args = parser.parse_args()

    output_dir = args.output_dir
    raw_path = output_dir / "raw.jsonl"

    # 1. Download
    if not args.skip_download:
        meta = download_dataset(output_dir)
    else:
        if not raw_path.exists():
            log.error(f"raw.jsonl not found at {raw_path}")
            sys.exit(1)
        meta_path = output_dir / "metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    # 2. Convert
    fmt = args.format
    results = {}

    if fmt in ("all", "chatml"):
        results["chatml"] = convert_to_chatml(raw_path, output_dir / "chatml.jsonl")

    if fmt in ("all", "sharegpt"):
        results["sharegpt"] = convert_to_sharegpt(raw_path, output_dir / "sharegpt.jsonl")

    if fmt in ("all", "alpaca"):
        results["alpaca"] = convert_to_alpaca(raw_path, output_dir / "alpaca.jsonl")

    # 3. Register in Forge KB
    register_in_forge_kb(output_dir, meta)

    # 4. Summary
    print("\n" + "=" * 60)
    print("  CLAUDE MYTHOS 25K — FINE-TUNING DATA READY")
    print("=" * 60)
    print(f"  Source:     {DATASET_ID}")
    print(f"  Rows:       {meta.get('rows', '?')}")
    print(f"  Output:     {output_dir}")
    for fmt_name, count in results.items():
        path = output_dir / f"{fmt_name}.jsonl"
        size_mb = path.stat().st_size / 1_000_000 if path.exists() else 0
        print(f"  {fmt_name:12s} {count:>6} entries  ({size_mb:.1f} MB)")
    print("=" * 60)
    print("\n  Next steps:")
    print("    • Axolotl/Unsloth : use chatml.jsonl")
    print("    • LLaMA-Factory   : use sharegpt.jsonl")
    print("    • Stanford Alpaca : use alpaca.jsonl")
    print("    • Custom pipeline : use raw.jsonl")
    print()


if __name__ == "__main__":
    main()
