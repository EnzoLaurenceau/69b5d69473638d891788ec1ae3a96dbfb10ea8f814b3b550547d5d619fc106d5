"""
app_catalog.py — Catalogue d'apps vendables (awesome-llm-apps) pour la MVP Factory.
================================================================================
"100+ AI Agent & RAG apps you can run — clone, customize, ship." (Apache-2.0)
Repo : https://github.com/Shubhamsaboo/awesome-llm-apps

Règle Forge #1 (jamais de fichier brut dans le contexte) : scrape → index (cache
JSON) → query on-demand. Les agents cherchent un template puis n'en tirent QUE le
nécessaire (README d'UNE app) — pas de bulk dump du repo.

⚠️ REVENTE : repo Apache-2.0, mais chaque sous-app embarque ses propres deps →
  vérifier leurs licences avant de vendre un dérivé.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

REPO = "Shubhamsaboo/awesome-llm-apps"
CACHE = Path(__file__).resolve().parent / "cache" / "awesome_llm_apps_catalog.json"
FALLBACK_CATEGORIES = [
    "advanced_ai_agents", "advanced_llm_apps", "ai_agent_framework_crash_course",
    "always_on_agents", "awesome_agent_skills", "generative_ui_agents",
    "mcp_ai_agents", "rag_tutorials", "starter_ai_agents", "voice_ai_agents",
]


def _api(path: str = ""):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "forge", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _load() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8"))


def categories(refresh: bool = False) -> list[str]:
    if not refresh:
        try:
            keys = list(_load().get("categories", {}).keys())
            if keys:
                return keys
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    try:
        return [x["name"] for x in _api("")
                if x.get("type") == "dir" and not x["name"].startswith(".") and x["name"] != "docs"]
    except Exception:
        return list(FALLBACK_CATEGORIES)


def list_apps(category: str):
    """Apps (sous-dossiers) d'une catégorie — query on-demand."""
    try:
        return [x["name"] for x in _api(category) if x.get("type") == "dir"]
    except Exception as e:
        return {"error": str(e)}


def refresh() -> dict:
    """(Re)construit l'index {catégorie: [apps]} en cache JSON."""
    idx = {}
    for c in categories(refresh=True):
        apps = list_apps(c)
        idx[c] = apps if isinstance(apps, list) else []
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    data = {"repo": REPO, "categories": idx, "total": sum(len(v) for v in idx.values())}
    CACHE.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def search(keyword: str):
    """Cherche un template par mot-clé sur l'index caché (refresh() si absent)."""
    try:
        data = _load()
    except Exception:
        data = refresh()
    kw = keyword.lower()
    hits = []
    for cat, apps in data.get("categories", {}).items():
        for a in apps:
            if kw in a.lower():
                hits.append({"category": cat, "app": a,
                             "url": f"https://github.com/{REPO}/tree/main/{cat}/{a}"})
    return hits


def fetch_app_readme(category: str, app: str) -> dict:
    """README d'UNE app, à la demande (pas de bulk dump)."""
    for fn in ("README.md", "readme.md", "Readme.md"):
        try:
            raw = f"https://raw.githubusercontent.com/{REPO}/main/{category}/{app}/{fn}"
            req = urllib.request.Request(raw, headers={"User-Agent": "forge"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return {"ok": True, "category": category, "app": app,
                        "readme": r.read().decode("utf-8", "replace")[:6000]}
        except Exception:
            continue
    return {"ok": False, "error": "README introuvable"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        print(json.dumps(refresh(), indent=1, ensure_ascii=False))
    elif len(sys.argv) > 2 and sys.argv[1] == "search":
        print(json.dumps(search(sys.argv[2]), indent=1, ensure_ascii=False))
    else:
        print(json.dumps({"categories": categories()}, indent=1, ensure_ascii=False))
