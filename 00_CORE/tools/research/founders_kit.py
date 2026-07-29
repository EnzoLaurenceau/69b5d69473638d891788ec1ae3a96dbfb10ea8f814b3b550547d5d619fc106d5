"""
founders_kit.py — Playbooks founders (avinash201199/founders-kit)
==================================================================
Parse les ressources/playbooks founders → turbovec agent="FOUNDER".
L'orchestrateur-CEO et l'agent MARKET consultent ces playbooks
(pricing, GTM, launch, scale) pour rendre les produits vendables.

Usage :
    from tools.research import founders_kit
    founders_kit.fetch_and_index()
    hits = founders_kit.search("pricing strategy")
    item = founders_kit.get("GTM")
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

README_URL = "https://raw.githubusercontent.com/avinash201199/founders-kit/main/README.md"
CATALOG = Path(__file__).resolve().parent / "founders_kit_catalog.json"

_LINK = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)")
_SECTION = re.compile(r"^#{1,3}\s+(?P<title>.+)$")


def _fetch() -> str:
    import urllib.request
    with urllib.request.urlopen(README_URL, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


_BADGE_HOSTS = ("img.shields.io", "badge", "githubusercontent.com")
_IMG_EXT = (".svg", ".png", ".gif", ".jpg", ".jpeg")


def _is_junk(title: str, url: str) -> bool:
    """Skip image/badge links (GitHub shields, etc.) and empty titles."""
    if not title or title.startswith("!"):
        return True
    low = url.lower()
    return low.endswith(_IMG_EXT) or any(h in low for h in _BADGE_HOSTS)


def parse(markdown: str) -> list[dict]:
    items, section, seen = [], "General", set()
    for line in markdown.splitlines():
        sec = _SECTION.match(line)
        if sec:
            section = sec.group("title").strip()
            continue
        for m in _LINK.finditer(line):
            title, url = m.group("title").strip(), m.group("url").strip()
            if url in seen or _is_junk(title, url):
                continue
            seen.add(url)
            items.append({"title": title, "url": url, "category": section})
    return items


def fetch_and_index() -> list[dict]:
    md = _fetch()
    items = parse(md)
    CATALOG.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain
        brain = get_turbovec_brain()
        for item in items:
            text = f"Founder resource: {item['title']} | category: {item['category']} | {item['url']}"
            brain.store(text, agent="FOUNDER", metadata={"title": item["title"], "url": item["url"]})
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    print(f"founders_kit: {len(items)} ressources indexées → {CATALOG.name}")
    return items


def search(query: str) -> list[dict]:
    if not CATALOG.exists():
        fetch_and_index()
    items = json.loads(CATALOG.read_text(encoding="utf-8"))
    q = query.lower()
    return [i for i in items if q in (i["title"] + i["category"]).lower()]


def get(keyword: str) -> dict | None:
    if not CATALOG.exists():
        return None
    items = json.loads(CATALOG.read_text(encoding="utf-8"))
    return next((i for i in items if keyword.lower() in i["title"].lower()), None)


if __name__ == "__main__":
    fetch_and_index()
    hits = search("pricing")
    print(f"search('pricing') → {len(hits)} résultats")
    for h in hits[:3]:
        print(f"  [{h['category']}] {h['title']}")
