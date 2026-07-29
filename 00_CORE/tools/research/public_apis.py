"""
public_apis.py — Index de TOUTES les APIs publiques (public-apis/public-apis).
==============================================================================
Source : https://github.com/public-apis/public-apis

But : indexer ~1400 APIs publiques dans la base de recherche de la Forge pour que
les agents en trouvent UNE et l'appellent quand une tâche en a besoin (météo, FX,
géo, OCR, finance, etc.) — au lieu de réinventer ou de chercher sur le web.

Note catégorie (comme pour HelixDB) : GitNexus indexe le CODE, pas des données
arbitraires. La base de RECHERCHE de données de la Forge = turbovec (Token-ID).
On indexe donc les APIs dans turbovec + un catalogue JSON ; GitNexus indexera ce
module .py (le code), pas la liste d'APIs.

Usage agent :
    from tools.research import public_apis
    public_apis.fetch_and_index()                 # 1× : peuple turbovec + catalogue
    hits = public_apis.search("weather forecast")  # trouve l'API adaptée
    api  = public_apis.get("Open-Meteo")           # {name,url,auth,https,cors,category,description}
    # puis l'agent appelle api['url'] (requests / MCP) selon api['auth'].
"""
from __future__ import annotations

import os
import re
import json
import sys
from pathlib import Path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

README_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"
CATALOG = Path(__file__).resolve().parent / "public_apis_catalog.json"

# Ligne de table : | [Name](url) | Description | Auth | HTTPS | CORS |
_ROW = re.compile(
    r"^\|\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)\s*\|"
    r"\s*(?P<desc>.*?)\s*\|\s*(?P<auth>.*?)\s*\|\s*(?P<https>.*?)\s*\|\s*(?P<cors>.*?)\s*\|\s*$"
)
_CATEGORY = re.compile(r"^###\s+(?P<cat>.+?)\s*$")


def parse(markdown: str) -> list[dict]:
    """Parse le README public-apis → liste d'entrées structurées."""
    apis, category = [], "Uncategorized"
    for line in markdown.splitlines():
        cat = _CATEGORY.match(line)
        if cat:
            category = cat.group("cat").strip()
            continue
        m = _ROW.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if name.lower() == "api":  # ligne d'en-tête
            continue
        apis.append({
            "name": name,
            "url": m.group("url").strip(),
            "description": m.group("desc").strip(),
            "auth": (m.group("auth").strip().strip("`") or "No"),
            "https": m.group("https").strip(),
            "cors": m.group("cors").strip(),
            "category": category,
        })
    return apis


def fetch_and_index(index_turbovec: bool = True) -> dict:
    """Télécharge le README, parse, écrit le catalogue JSON, indexe dans turbovec."""
    import requests
    md = requests.get(README_URL, timeout=30).text
    apis = parse(md)
    CATALOG.write_text(json.dumps(apis, indent=2, ensure_ascii=False), encoding="utf-8")

    indexed = 0
    if index_turbovec:
        try:
            from forge_agents.turbovec_brain import get_turbovec_brain
            brain = get_turbovec_brain()
            for a in apis:
                txt = (f"[API {a['name']}] category={a['category']} auth={a['auth']} "
                       f"https={a['https']} cors={a['cors']} — {a['description']} → {a['url']}")
                brain.store(txt, agent="API", score=7.0)
                indexed += 1
        except Exception as e:
            return {"apis": len(apis), "catalog": str(CATALOG), "turbovec_indexed": 0,
                    "turbovec_error": repr(e)[:160]}
    return {"apis": len(apis), "catalog": str(CATALOG),
            "categories": len({a["category"] for a in apis}), "turbovec_indexed": indexed}


def _load_catalog() -> list[dict]:
    if CATALOG.exists():
        return json.loads(CATALOG.read_text(encoding="utf-8"))
    return []


def search(query: str, k: int = 8) -> list[dict]:
    """Trouve les APIs les plus pertinentes (turbovec si dispo, sinon scan catalogue)."""
    cat = _load_catalog()
    if not cat:
        return []
    terms = [t for t in re.split(r"\W+", query.lower()) if t]

    def score(a: dict) -> int:
        blob = f"{a['name']} {a['description']} {a['category']}".lower()
        return sum(blob.count(t) for t in terms)

    ranked = sorted(cat, key=score, reverse=True)
    return [a for a in ranked if score(a) > 0][:k]


def get(name: str) -> dict | None:
    name_l = name.lower()
    for a in _load_catalog():
        if a["name"].lower() == name_l:
            return a
    return None


def categories() -> list[str]:
    return sorted({a["category"] for a in _load_catalog()})


def demo():
    """ponytail: vérif runnable du parseur (offline, sample inline)."""
    sample = (
        "### Weather\n"
        "| API | Description | Auth | HTTPS | CORS |\n"
        "|---|---|---|---|---|\n"
        "| [Open-Meteo](https://open-meteo.com/) | Global weather forecast | No | Yes | Yes |\n"
        "### Finance\n"
        "| [Frankfurter](https://www.frankfurter.app/docs/) | Exchange rates | No | Yes | Yes |\n"
    )
    apis = parse(sample)
    assert len(apis) == 2, apis
    assert apis[0]["name"] == "Open-Meteo" and apis[0]["category"] == "Weather", apis[0]
    assert apis[1]["category"] == "Finance" and apis[1]["url"].startswith("https://"), apis[1]
    print("public_apis.demo OK |", [(a["name"], a["category"]) for a in apis])


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "demo"
    if cmd == "demo":
        demo()
    elif cmd == "index":
        print(fetch_and_index())
    elif cmd == "search" and len(a) > 1:
        for x in search(" ".join(a[1:])):
            print(f"  {x['name']:24} [{x['category']}] auth={x['auth']} -> {x['url']}")
    elif cmd == "categories":
        print(", ".join(categories()))
    else:
        print("Usage: public_apis.py [demo | index | search <q> | categories]")
