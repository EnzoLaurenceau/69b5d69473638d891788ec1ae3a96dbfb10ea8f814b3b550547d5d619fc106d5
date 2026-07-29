"""
download_forge_datasets.py — Multi-Dataset Downloader & Fine-Tuning Formatter
===============================================================================
Télécharge N datasets HuggingFace en batch et les convertit en formats
fine-tuning multiples pour la Forge.

Usage :
  python scripts/download_forge_datasets.py
  python scripts/download_forge_datasets.py --datasets "ginigen-ai/Metacognition-Bench" "CodeDevX/Vibe-Coding-Instruct"
  python scripts/download_forge_datasets.py --format chatml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent
DATASETS_ROOT = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "datasets"

# ─── Default datasets to download ────────────────────────────────────────────

DEFAULT_DATASETS = [
    {
        "id": "ginigen-ai/Metacognition-Bench",
        "slug": "metacognition_bench",
        "description": "Metacognition benchmark - self-reflection and reasoning",
    },
    {
        "id": "CodeDevX/Vibe-Coding-Instruct",
        "slug": "vibe_coding_instruct",
        "description": "Coding instruction dataset for vibe-coding style",
    },
]


# ─── INSTALL DEPENDENCIES ────────────────────────────────────────────────────

def _ensure_deps():
    for pkg in ("datasets", "huggingface_hub"):
        try:
            __import__(pkg)
        except ImportError:
            log.info(f"Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


# ─── COLUMN DETECTION & MESSAGE EXTRACTION ───────────────────────────────────

def _detect_columns(row: dict) -> dict:
    mapping = {}
    for key in ("instruction", "prompt", "question", "input", "query", "problem"):
        if key in row:
            mapping["instruction"] = key
            break
    for key in ("output", "response", "answer", "completion", "solution", "reply"):
        if key in row:
            mapping["output"] = key
            break
    for key in ("input", "context"):
        if key in row and key != mapping.get("instruction"):
            mapping["context"] = key
            break
    for key in ("conversations", "messages", "chat", "dialogue"):
        if key in row:
            mapping["conversations"] = key
            break
    for key in ("system", "system_prompt", "system_message"):
        if key in row:
            mapping["system"] = key
            break
    return mapping


def _extract_messages(row: dict, col_map: dict) -> list[dict]:
    # Native conversations
    if "conversations" in col_map:
        convs = row.get(col_map["conversations"], [])
        if isinstance(convs, list) and len(convs) > 0:
            messages = []
            for c in convs:
                if isinstance(c, dict):
                    role = c.get("role", c.get("from", "user"))
                    content = c.get("content", c.get("value", c.get("text", "")))
                    if role in ("human", "user", "Human"):
                        role = "user"
                    elif role in ("gpt", "assistant", "bot", "model", "Assistant", "GPT"):
                        role = "assistant"
                    elif role in ("system", "System"):
                        role = "system"
                    if content:
                        messages.append({"role": role, "content": str(content)})
            if messages:
                return messages

    messages = []
    if "system" in col_map:
        sys_msg = row.get(col_map["system"], "")
        if sys_msg:
            messages.append({"role": "system", "content": str(sys_msg)})

    instruction = row.get(col_map.get("instruction", ""), "")
    context = row.get(col_map.get("context", ""), "")
    if isinstance(instruction, list):
        instruction = " ".join(str(x) for x in instruction)
    if isinstance(context, list):
        context = " ".join(str(x) for x in context)
    if context and context != instruction:
        user_content = f"{instruction}\n\n{context}"
    else:
        user_content = str(instruction) if instruction else ""
    if user_content:
        messages.append({"role": "user", "content": user_content})

    output = row.get(col_map.get("output", ""), "")
    if isinstance(output, list):
        output = " ".join(str(x) for x in output)
    if output:
        messages.append({"role": "assistant", "content": str(output)})

    return messages


# ─── DOWNLOAD & CONVERT ─────────────────────────────────────────────────────

def download_and_convert(dataset_id: str, slug: str, output_dir: Path) -> dict:
    """Download a single dataset and convert to all formats."""
    _ensure_deps()
    from datasets import load_dataset

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw.jsonl"
    
    log.info(f"{'='*60}")
    log.info(f"Downloading: {dataset_id}")
    log.info(f"{'='*60}")

    # Try multiple split names
    ds = None
    for split in ("train", "test", "validation", "all"):
        try:
            ds = load_dataset(dataset_id, split=split, trust_remote_code=True)
            log.info(f"Loaded split '{split}': {len(ds)} rows, columns={ds.column_names}")
            break
        except Exception as e:
            if "split" in str(e).lower() or "Unknown split" in str(e):
                continue
            # Try without split
            try:
                ds_dict = load_dataset(dataset_id, trust_remote_code=True)
                # Get first available split
                first_split = list(ds_dict.keys())[0]
                ds = ds_dict[first_split]
                log.info(f"Loaded split '{first_split}': {len(ds)} rows, columns={ds.column_names}")
                break
            except Exception as e2:
                log.error(f"Failed to load {dataset_id}: {e2}")
                return {"error": str(e2), "dataset_id": dataset_id}

    if ds is None:
        return {"error": "Could not load any split", "dataset_id": dataset_id}

    # Dump raw
    with open(raw_path, "w", encoding="utf-8") as f:
        for row in ds:
            # Convert non-serializable types
            clean_row = {}
            for k, v in row.items():
                try:
                    json.dumps(v)
                    clean_row[k] = v
                except (TypeError, ValueError):
                    clean_row[k] = str(v)
            f.write(json.dumps(clean_row, ensure_ascii=False) + "\n")

    log.info(f"Raw saved: {raw_path} ({raw_path.stat().st_size / 1_000_000:.1f} MB)")

    # Detect columns from first row
    with open(raw_path, "r", encoding="utf-8") as f:
        first_row = json.loads(f.readline())
    col_map = _detect_columns(first_row)
    log.info(f"Columns: {list(first_row.keys())}")
    log.info(f"Mapping: {col_map}")

    # Convert to ChatML
    chatml_path = output_dir / "chatml.jsonl"
    chatml_count = 0
    with open(raw_path, "r", encoding="utf-8") as fin, \
         open(chatml_path, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            messages = _extract_messages(row, col_map)
            if len(messages) >= 2:
                fout.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
                chatml_count += 1

    # Convert to ShareGPT
    sharegpt_path = output_dir / "sharegpt.jsonl"
    sgpt_count = 0
    with open(raw_path, "r", encoding="utf-8") as fin, \
         open(sharegpt_path, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            messages = _extract_messages(row, col_map)
            if len(messages) >= 2:
                conversations = [
                    {"from": {"user": "human", "assistant": "gpt", "system": "system"}.get(m["role"], m["role"]),
                     "value": m["content"]}
                    for m in messages
                ]
                fout.write(json.dumps({"conversations": conversations}, ensure_ascii=False) + "\n")
                sgpt_count += 1

    # Convert to Alpaca
    alpaca_path = output_dir / "alpaca.jsonl"
    alp_count = 0
    with open(raw_path, "r", encoding="utf-8") as fin, \
         open(alpaca_path, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            messages = _extract_messages(row, col_map)
            instruction = ""
            output_text = ""
            for m in messages:
                if m["role"] == "user" and not instruction:
                    instruction = m["content"]
                elif m["role"] == "assistant" and not output_text:
                    output_text = m["content"]
            if instruction and output_text:
                fout.write(json.dumps({"instruction": instruction, "input": "", "output": output_text},
                                       ensure_ascii=False) + "\n")
                alp_count += 1

    meta = {
        "dataset_id": dataset_id,
        "slug": slug,
        "rows": len(ds),
        "columns": ds.column_names,
        "column_mapping": col_map,
        "raw_path": str(raw_path),
        "size_bytes": raw_path.stat().st_size,
        "chatml_count": chatml_count,
        "sharegpt_count": sgpt_count,
        "alpaca_count": alp_count,
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info(f"  ChatML:   {chatml_count} conversations")
    log.info(f"  ShareGPT: {sgpt_count} conversations")
    log.info(f"  Alpaca:   {alp_count} entries")

    return meta


# ─── KB REGISTRATION ─────────────────────────────────────────────────────────

def register_all_in_kb(results: list[dict]) -> None:
    """Register all downloaded datasets in the Forge KB index."""
    kb_index_path = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "index.json"
    try:
        index = json.loads(kb_index_path.read_text(encoding="utf-8"))
    except Exception:
        index = {}

    datasets = index.setdefault("datasets", [])

    for meta in results:
        if "error" in meta:
            continue
        slug = meta.get("slug", meta.get("dataset_id", "unknown"))
        # Remove old entry
        datasets[:] = [d for d in datasets if d.get("id") != slug]
        datasets.append({
            "id": slug,
            "name": meta.get("dataset_id", slug),
            "source": meta.get("dataset_id", ""),
            "rows": meta.get("rows", 0),
            "columns": meta.get("columns", []),
            "chatml_count": meta.get("chatml_count", 0),
            "path": str(DATASETS_ROOT / slug),
            "formats": ["raw", "chatml", "sharegpt", "alpaca"],
            "purpose": "fine-tuning",
            "status": "ready",
        })

    kb_index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"KB index updated with {len([r for r in results if 'error' not in r])} datasets")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download multiple HF datasets for Forge fine-tuning")
    parser.add_argument("--datasets", nargs="*", help="HF dataset IDs to download (overrides defaults)")
    args = parser.parse_args()

    if args.datasets:
        dataset_list = [
            {"id": d, "slug": d.split("/")[-1].lower().replace("-", "_"), "description": "user-specified"}
            for d in args.datasets
        ]
    else:
        dataset_list = DEFAULT_DATASETS

    results = []
    for ds_info in dataset_list:
        ds_id = ds_info["id"]
        slug = ds_info["slug"]
        output_dir = DATASETS_ROOT / slug
        try:
            meta = download_and_convert(ds_id, slug, output_dir)
            results.append(meta)
        except Exception as e:
            log.error(f"FAILED {ds_id}: {e}")
            traceback.print_exc()
            results.append({"error": str(e), "dataset_id": ds_id})

    # Register in KB
    register_all_in_kb(results)

    # Summary
    print("\n" + "=" * 70)
    print("  FORGE MULTI-DATASET DOWNLOAD — COMPLETE")
    print("=" * 70)
    for meta in results:
        if "error" in meta:
            print(f"  ❌ {meta.get('dataset_id', '?')}: {meta['error'][:80]}")
        else:
            print(f"  ✅ {meta['dataset_id']}")
            print(f"     Rows: {meta['rows']}  ChatML: {meta['chatml_count']}  "
                  f"ShareGPT: {meta['sharegpt_count']}  Alpaca: {meta['alpaca_count']}")
            print(f"     Size: {meta['size_bytes'] / 1_000_000:.1f} MB  → {DATASETS_ROOT / meta['slug']}")
    print("=" * 70)
    print("\n  Run the fine-tuning pipeline to merge all:")
    print("    python -c \"from forge_agents.finetune_pipeline import FinetunePipeline; "
          "p = FinetunePipeline(); p.generate_forge_experience(); p.prepare()\"")
    print()


if __name__ == "__main__":
    main()
