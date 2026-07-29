"""
oss_saas.py — Catalogue de SaaS open-source (toolworks-dev/open-source-saas)
=============================================================================
Même patron que research/public_apis.py.
Parse la liste GitHub → catalogue JSON → turbovec agent="SAAS".

Usage :
    from tools.catalog import oss_saas
    oss_saas.fetch_and_index()         # peuple turbovec + catalogue (1x)
    hits = oss_saas.search("CRM")      # SaaS OSS à adapter
    saas = oss_saas.get("twenty")      # {name, url, category, description}
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

README_URL = "https://raw.githubusercontent.com/toolworks-dev/open-source-saas/main/README.md"
CATALOG = Path(__file__).resolve().parent / "oss_saas_catalog.json"

_ROW = re.compile(
    r"^\|\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)\s*\|"
    r"\s*(?P<desc>[^|]*?)\s*\|"
)
_LIST_ROW = re.compile(
    r"^\d+\.\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)\s*-\s*(?P<desc>.*)$"
)
_SECTION = re.compile(r"^#{1,3}\s+(?P<cat>.+?)\s*$")


def _fetch() -> str:
    import urllib.request
    with urllib.request.urlopen(README_URL, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def parse(markdown: str) -> list[dict]:
    items, category = [], "Uncategorized"
    for line in markdown.splitlines():
        line = line.strip()
        sec = _SECTION.match(line)
        if sec:
            category = sec.group("cat").strip()
            continue
        m = _ROW.match(line)
        if not m:
            m = _LIST_ROW.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if name.lower() in ("name", "project", "tool"):
            continue
        
        desc = m.group("desc").strip()
        if desc.endswith("."):
            desc = desc[:-1].strip()
            
        items.append({
            "name": name,
            "url": m.group("url").strip(),
            "description": desc,
            "category": category,
        })
        
    # Append Dify as a core repository source in the process
    items.append({
        "name": "Dify",
        "url": "https://github.com/langgenius/dify",
        "description": "Plateforme de dev d'apps LLM (chatbots, assistants, RAG, agents) prête prod. Produit des 'SaaS bot' / 'ai system' livrables.",
        "category": "AI & Machine Learning"
    })
    return items


def fetch_and_index() -> list[dict]:
    """Télécharge, parse, indexe turbovec + écrit oss_saas_catalog.json."""
    md = _fetch()
    items = parse(md)
    CATALOG.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    indexed = 0
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain
        brain = get_turbovec_brain()
        for item in items:
            text = (
                f"OSS SaaS: {item['name']} | {item['category']} | "
                f"{item['description']} | {item['url']}"
            )
            brain.store(text, agent="SAAS", score=7.0)
            indexed += 1
    except Exception as e:
        print(f"Error indexing in turbovec: {e}")
    print(f"oss_saas: {len(items)} SaaS OSS indexés ({indexed} in turbovec) → {CATALOG.name}")
    return items


def search(query: str) -> list[dict]:
    """Cherche par nom, description ou catégorie."""
    if not CATALOG.exists():
        fetch_and_index()
    items = json.loads(CATALOG.read_text(encoding="utf-8"))
    q = query.lower()
    return [
        i for i in items
        if q in (i.get("name", "") + i.get("description", "") + i.get("category", "")).lower()
    ]


def get(name: str) -> dict | None:
    if not CATALOG.exists():
        return None
    items = json.loads(CATALOG.read_text(encoding="utf-8"))
    return next((i for i in items if name.lower() in i["name"].lower()), None)


if __name__ == "__main__":
    fetch_and_index()
    hits = search("CRM")
    print(f"search('CRM') → {len(hits)} résultats")
    for h in hits[:3]:
        print(f"  [{h['category']}] {h['name']}: {h['description'][:60]}")
