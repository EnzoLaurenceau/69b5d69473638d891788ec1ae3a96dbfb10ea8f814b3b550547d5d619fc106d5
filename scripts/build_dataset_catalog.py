"""Régénère 07_KNOWLEDGE_BASE/catalog.json depuis l'arbre datasets/ + finetune_ready/.
ponytail: index cheap et queryable des corpus (vs embedder 5GB à l'aveugle).
Usage: python scripts/build_dataset_catalog.py
"""
from __future__ import annotations
import json, os, glob, datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

KB = Path(__file__).resolve().parent.parent / "07_KNOWLEDGE_BASE"


def _du(p: str) -> float:
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(p) for f in fs)
    return round(total / 1e6, 1)


def _rows(d: str) -> int | None:
    meta = os.path.join(d, "metadata.json")
    if os.path.exists(meta):
        try:
            return json.load(open(meta, encoding="utf-8")).get("rows")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    raw = os.path.join(d, "raw.jsonl")
    if os.path.exists(raw):
        return sum(1 for _ in open(raw, encoding="utf-8", errors="ignore"))
    return None


def build() -> dict:
    datasets, empty = [], []
    for d in sorted(glob.glob(str(KB / "datasets" / "*") + os.sep)):
        name = os.path.basename(d.rstrip("/\\"))
        fmts = sorted(os.path.basename(f).split(".")[0]
                      for f in glob.glob(os.path.join(d, "*.jsonl")))
        if not fmts:
            empty.append(f"datasets/{name}")
            continue
        datasets.append({"name": name, "path": f"datasets/{name}",
                         "rows": _rows(d), "size_mb": _du(d), "formats": fmts})
    ft = [{"file": os.path.basename(f),
           "rows": sum(1 for _ in open(f, encoding="utf-8", errors="ignore")),
           "size_mb": round(os.path.getsize(f) / 1e6, 1)}
          for f in sorted(glob.glob(str(KB / "finetune_ready" / "*.jsonl")))]
    return {"generated": datetime.date.today().isoformat(),
            "datasets": datasets, "empty_stubs": empty, "finetune_ready": ft}


if __name__ == "__main__":
    cat = build()
    out = KB / "catalog.json"
    out.write_text(json.dumps(cat, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"catalog: {len(cat['datasets'])} datasets, "
          f"{len(cat['finetune_ready'])} finetune files, "
          f"{len(cat['empty_stubs'])} empty stubs -> {out}")
    assert cat["datasets"], "no datasets found — wrong cwd?"
    print("CHECK PASS")
