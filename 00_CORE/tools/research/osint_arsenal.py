"""
osint_arsenal.py — Index appelable de l'arsenal OSINT (awesome-osint-arsenal).
==============================================================================
Source : https://github.com/rawfilejson/awesome-osint-arsenal  (751+ outils, 50 catégories)

But (même rôle que public_apis.py) : indexer le catalogue d'outils OSINT pour que
TOUTE tâche OSINT trouve LE bon outil et l'appelle — au lieu de chercher sur le web
ou de réinventer. On NE clone PAS / NE bricole PAS les 751 outils (latence inutile) :
on garde un catalogue interrogeable, et on AIGUILLE vers ce qui est déjà câblé.

ANTI-REDONDANCE (exigence latence) : chaque entrée porte un flag `wired` —
les outils déjà fournis par OpenOSINT / hackingtool / scripts CraftYourWebsite
sont marqués `wired=True`. `pick()` renvoie d'abord le wrapper existant (instantané),
et ne propose `install` QUE pour un outil non câblé.

Usage agent / script :
    from tools.research import osint_arsenal
    osint_arsenal.fetch_and_index()          # 1× : (re)génère le catalogue JSON
    hit = osint_arsenal.pick("trouver les réseaux sociaux d'un username")
    #   → {"name":"Sherlock","wired":"openosint.username", "install":..., "link":...}
    # si hit["wired"] : appeler le wrapper indiqué (pas de réinstall).
    hits = osint_arsenal.search("phone number lookup")   # top-k bruts

Catalogue : osint_arsenal_catalog.json (généré ; régénérer via `python osint_arsenal.py index`).
"""
from __future__ import annotations

import os
import re
import sys
import json
from pathlib import Path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))
README_URL = "https://raw.githubusercontent.com/rawfilejson/awesome-osint-arsenal/main/README.md"
CATALOG = Path(__file__).resolve().parent / "osint_arsenal_catalog.json"

# --- Déjà câblé dans la Forge → ne JAMAIS réinstaller (latence). nom_lower -> wrapper ---
# OpenOSINT (00_CORE/tools/research/open_osint.py, 18 outils) + hackingtool:pentest skill.
WIRED: dict[str, str] = {
    "sherlock": "openosint.username / hackingtool",
    "maigret": "openosint.username / hackingtool",
    "holehe": "openosint.email / hackingtool",
    "socialscan": "openosint.email",
    "sublist3r": "hackingtool (subdomain)",
    "subfinder": "hackingtool (subdomain)",
    "amass": "hackingtool (subdomain)",
    "theharvester": "openosint.email / hackingtool",
    "shodan": "openosint.shodan",
    "censys": "openosint (censys)",
    "virustotal": "openosint (virustotal)",
    "abuseipdb": "openosint (abuseipdb)",
    "ip2location": "openosint.ip",
    "whois": "openosint (whois)",
    "phoneinfoga": "openosint.phone / hackingtool",
    "nuclei": "hackingtool",
    "httpx": "hackingtool",
    "nmap": "hackingtool",
    "spiderfoot": "hackingtool",
    "recon-ng": "hackingtool",
    "ghunt": "openosint (google)",
    "github": "openosint.github",
    # CraftYourWebsite : déjà couvert par scripts/ (prospect biz OSINT)
    "openstreetmap": "CYW prospect_osint.py (Overpass)",
    "google maps": "CYW osint_scraper.py",
}

_CATEGORY = re.compile(r"^#{2,3}\s+(?:\d+\.\s*)?(?P<cat>.+?)\s*$")
_SEP = re.compile(r"^\|[\s:|-]+\|?\s*$")
_INSTALL = re.compile(r"`([^`]*(?:pip install|git clone|go install|apt|gem install|npm i|cargo|brew)[^`]*)`", re.I)
_MDLINK = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
_BARE_URL = re.compile(r"https?://[^\s|)]+")
# headers de table / sections non-outils à ignorer
_SKIP_NAME = {"tool", "portal", "api", "name", "service", "site", "resource", "command", "category"}
_SKIP_CAT = re.compile(r"table of contents|legal|disclaimer|contributing|note before|star history|"
                       r"install|usage|osint value|how you can help|get everything|pick just",
                       re.I)


def _clean_name(cell: str) -> str:
    s = cell.strip().strip("*").strip()
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)  # [Name](url) -> Name
    return s.strip("* ").strip()


def parse(markdown: str) -> list[dict]:
    """README arsenal → entrées structurées {name,category,description,install,link,wired}."""
    tools: list[dict] = []
    category = "Uncategorized"
    seen: set[tuple[str, str]] = set()
    for line in markdown.splitlines():
        cat = _CATEGORY.match(line)
        if cat and "|" not in line:
            category = cat.group("cat").strip()
            continue
        if not line.lstrip().startswith("|") or _SEP.match(line.strip()):
            continue
        if _SKIP_CAT.search(category):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = _clean_name(cells[0])
        if not name or name.lower() in _SKIP_NAME:
            continue
        row = " | ".join(cells)
        install = (_INSTALL.search(row) or [None, None])[1] if _INSTALL.search(row) else None
        link_m = _MDLINK.search(row) or _BARE_URL.search(row)
        link = link_m.group(1) if (link_m and link_m.re is _MDLINK) else (link_m.group(0) if link_m else None)
        # description = première cellule non-nom qui n'est ni install ni pure url
        desc = ""
        for c in cells[1:]:
            cl = c.strip()
            if cl and not _BARE_URL.fullmatch(cl) and "install" not in cl.lower() and not cl.startswith("`"):
                desc = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cl).strip("`* ")
                break
        key = (name.lower(), category)
        if key in seen:
            continue
        seen.add(key)
        tools.append({
            "name": name,
            "category": category,
            "description": desc,
            "install": install,
            "link": link,
            "wired": WIRED.get(name.lower()),
        })
    return tools


def fetch_and_index(index_turbovec: bool = False) -> dict:
    """Télécharge le README, parse, écrit le catalogue JSON. turbovec optionnel (off par défaut)."""
    import requests
    md = requests.get(README_URL, timeout=30).text
    tools = parse(md)
    CATALOG.write_text(json.dumps(tools, indent=2, ensure_ascii=False), encoding="utf-8")
    indexed = 0
    if index_turbovec:
        try:
            sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
            from forge_agents.turbovec_brain import get_turbovec_brain
            brain = get_turbovec_brain()
            for t in tools:
                txt = (f"[OSINT {t['name']}] cat={t['category']} — {t['description']} "
                       f"install={t['install']} link={t['link']} wired={t['wired']}")
                brain.store(txt, agent="OSINT", score=7.0)
                indexed += 1
        except Exception as e:  # turbovec absent → catalogue suffit
            return {"tools": len(tools), "catalog": str(CATALOG), "turbovec_indexed": 0,
                    "turbovec_error": repr(e)[:160]}
    return {"tools": len(tools), "catalog": str(CATALOG),
            "categories": len({t["category"] for t in tools}),
            "wired": sum(1 for t in tools if t["wired"]), "turbovec_indexed": indexed}


def _load() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else []


# Catalogue EN, charge de travail souvent FR (pipeline CYW) : pont de mots-clés.
# ponytail: map FR→EN minimal des termes OSINT courants ; étendre si une tâche rate.
_SYNONYMS = {
    "telephone": "phone", "téléphone": "phone", "numero": "phone", "numéro": "phone",
    "reseaux": "social media", "réseaux": "social media", "social": "social media",
    "courriel": "email", "mail": "email", "adresse": "address",
    "commerce": "business company", "entreprise": "business company",
    "societe": "company", "société": "company", "proprietaire": "owner person",
    "propriétaire": "owner person", "dirigeant": "owner person", "gerant": "owner person",
    "visage": "face", "photo": "image face", "image": "image",
    "domaine": "domain", "registre": "registry company", "geo": "geolocation",
    "localisation": "geolocation", "carte": "maps", "username": "username",
    "pseudo": "username", "utilisateur": "username",
}


def _expand(query: str) -> list[str]:
    """Termes de la requête + expansion FR→EN, dédupliqués."""
    terms: list[str] = []
    for w in (t for t in re.split(r"\W+", query.lower()) if len(t) > 1):
        terms.append(w)
        if w in _SYNONYMS:
            terms.extend(_SYNONYMS[w].split())
    return list(dict.fromkeys(terms))


def search(query: str, k: int = 8) -> list[dict]:
    """Top-k outils pertinents (scan catalogue, instantané, zéro dépendance)."""
    cat = _load()
    terms = _expand(query)
    if not (cat and terms):
        return []

    def score(t: dict) -> int:
        blob = f"{t['name']} {t['description']} {t['category']}".lower()
        # match nom/desc compte double ; catégorie boost modéré (×2, pas ×3)
        return sum(
            blob.count(term) + (2 if term in t["category"].lower() else 0) +
            (1 if term in t["description"].lower() else 0)
            for term in terms
        )

    ranked = sorted(cat, key=score, reverse=True)
    return [t for t in ranked if score(t) > 0][:k]


def pick(task: str) -> dict | None:
    """Aiguillage anti-redondance : meilleur outil pour `task`, en privilégiant le câblé."""
    hits = search(task, k=12)
    if not hits:
        return None
    hits.sort(key=lambda t: 0 if t["wired"] else 1)  # câblé d'abord (pas de réinstall)
    return hits[0]


def get(name: str) -> dict | None:
    nl = name.lower()
    return next((t for t in _load() if t["name"].lower() == nl), None)


def categories() -> list[str]:
    return sorted({t["category"] for t in _load()})


def demo():
    """ponytail: vérif runnable du parseur (offline, sample inline des vrais formats)."""
    sample = (
        "## 1. Username & Social Media OSINT\n"
        "| Tool | Description | Install / Link |\n"
        "|------|-------------|----------------|\n"
        "| **Sherlock** | Hunt usernames across networks | `pip install sherlock-project` |\n"
        "| **Blackbird** | Fast username search tool | `pip install blackbird-osint` |\n"
        "## 7. Facial Recognition & People Search\n"
        "| Tool | Description | Install / Link |\n"
        "|------|-------------|----------------|\n"
        "| **PimEyes** | Face search engine from photos | [pimeyes.com](https://pimeyes.com/) |\n"
        "## Table of Contents\n"
        "| Tool | Description | Link |\n"
        "| **Ignored** | should be skipped | x |\n"
    )
    tools = parse(sample)
    names = {t["name"]: t for t in tools}
    assert "Sherlock" in names and names["Sherlock"]["wired"], "Sherlock must be wired-flagged"
    assert names["Sherlock"]["install"].startswith("pip install"), names["Sherlock"]
    assert "PimEyes" in names and names["PimEyes"]["link"] == "https://pimeyes.com/", names.get("PimEyes")
    assert names["PimEyes"]["wired"] is None, "PimEyes not wired"
    assert "Ignored" not in names, "ToC section must be skipped"
    assert names["Blackbird"]["category"].startswith("Username"), names["Blackbird"]
    # FR→EN : "pseudo" et "réseaux" doivent s'étendre vers username / social media
    exp = _expand("pseudo sur les réseaux")
    assert "username" in exp and "social" in exp and "media" in exp, f"FR expansion failed: {exp}"
    print("osint_arsenal.demo OK |", [(t["name"], t["category"][:18], bool(t["wired"])) for t in tools],
          "| FR exp→", [w for w in exp if w in ("username", "social", "media")])


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "demo"
    if cmd == "demo":
        demo()
    elif cmd == "index":
        print(fetch_and_index(index_turbovec="--turbovec" in a))
    elif cmd == "search" and len(a) > 1:
        for x in search(" ".join(a[1:])):
            flag = f"WIRED→{x['wired']}" if x["wired"] else (x["install"] or x["link"] or "")
            print(f"  {x['name']:22} [{x['category'][:24]}] {flag}")
    elif cmd == "pick" and len(a) > 1:
        print(json.dumps(pick(" ".join(a[1:])), indent=2, ensure_ascii=False))
    elif cmd == "categories":
        print("\n".join(categories()))
    else:
        print("Usage: osint_arsenal.py [demo | index [--turbovec] | search <q> | pick <task> | categories]")
