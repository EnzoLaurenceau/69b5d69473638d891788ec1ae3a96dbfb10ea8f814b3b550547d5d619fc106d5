#!/usr/bin/env python3
"""
grade.py — scoring OBJECTIF de l'autonomie d'un site produit.
=============================================================
Scanne un dossier de build (HTML/CSS/JS) et vérifie, par regex déterministe,
les tâches IMPLICITES d'"un vrai site" que le brief ne demande JAMAIS
explicitement. Zéro LLM → reproductible, non subjectif.

  python grade.py builds/nu
  python grade.py builds/forge --json

Deux familles de checks :
  EXPLICIT  = demandé dans le brief (NAP, réservation)  → sanity, non compté dans l'autonomie
  IMPLICIT  = jamais demandé mais attendu d'un pro       → SCORE D'AUTONOMIE /100

Chaque check : pass=1.0 / partial=0.5 / fail=0.0, pondéré. Le score d'autonomie
est la moyenne pondérée des checks IMPLICIT uniquement.
"""
from __future__ import annotations
import re, sys, json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def _load(build_dir: Path) -> tuple[str, dict[str, str]]:
    """Retourne (tout_le_texte_concaténé_lower, {nom_fichier: contenu}). """
    files = {}
    for p in build_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".html", ".htm", ".css", ".js", ".xml", ".txt", ".webmanifest", ".json"):
            try:
                files[p.name.lower()] = p.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    blob = "\n".join(files.values())
    return blob.lower(), files


def _has(blob: str, *patterns: str) -> bool:
    return any(re.search(p, blob, re.I | re.S) for p in patterns)


# ── CHECKS ────────────────────────────────────────────────────────────────
# (key, family, weight, fn(blob, files) -> 0.0 | 0.5 | 1.0)
def _imgs_have_alt(blob, files):
    imgs = re.findall(r"<img\b[^>]*>", blob, re.I)
    if not imgs:
        return 1.0  # pas d'img → rien à reprocher (neutre haut)
    ok = sum(1 for t in imgs if re.search(r"\balt\s*=", t, re.I))
    return 1.0 if ok == len(imgs) else (0.5 if ok else 0.0)


def _inputs_have_labels(blob, files):
    inputs = re.findall(r"<(?:input|textarea|select)\b[^>]*>", blob, re.I)
    real = [t for t in inputs if not re.search(r'type\s*=\s*["\']?(hidden|submit|button)', t, re.I)]
    if not real:
        return 0.0  # aucun champ = pas de formulaire (pénalisé ailleurs aussi)
    labelled = _has(blob, r"<label", r"aria-label", r"aria-labelledby")
    return 1.0 if labelled else 0.0


CHECKS = [
    # IMPLICIT — le cœur du test d'autonomie
    ("responsive",   "implicit", 3, lambda b, f: 1.0 if (_has(b, r'name=["\']viewport["\']') and _has(b, r"@media")) else (0.5 if _has(b, r'name=["\']viewport["\']') else 0.0)),
    ("dark_mode",    "implicit", 2, lambda b, f: 1.0 if _has(b, r"prefers-color-scheme", r'data-theme', r"\.dark\b", r"theme-toggle") else 0.0),
    ("seo_meta",     "implicit", 3, lambda b, f: 1.0 if (_has(b, r"<title>") and _has(b, r'name=["\']description["\']')) else (0.5 if _has(b, r"<title>") else 0.0)),
    ("social_og",    "implicit", 2, lambda b, f: 1.0 if _has(b, r'property=["\']og:', r'name=["\']twitter:') else 0.0),
    ("favicon",      "implicit", 1, lambda b, f: 1.0 if _has(b, r'rel=["\'][^"\']*icon') else 0.0),
    ("lang_attr",    "implicit", 1, lambda b, f: 1.0 if _has(b, r"<html[^>]*\blang\s*=") else 0.0),
    ("img_alt",      "implicit", 2, _imgs_have_alt),
    ("form_labels",  "implicit", 2, _inputs_have_labels),
    ("legal_rgpd",   "implicit", 4, lambda b, f: 1.0 if _has(b, r"mentions\s+l[ée]gales", r"politique\s+de\s+confidentialit", r"rgpd", r"donn[ée]es\s+personnelles") else 0.0),
    ("cookie_privacy","implicit",2, lambda b, f: 0.0 if _has(b, r"google-analytics", r"googletagmanager", r"gtag\(", r"facebook\.net") and not _has(b, r"consent", r"cookie") else 1.0),
    ("form_validation","implicit",2, lambda b, f: 1.0 if _has(b, r"required", r"pattern\s*=", r'type\s*=\s*["\']email') else 0.0),
    ("map_osm",      "implicit", 3, lambda b, f: 1.0 if _has(b, r"openstreetmap", r"leaflet", r"cartodb", r"tile\.osm") else (0.5 if _has(b, r"maps\.google", r"<iframe[^>]+map") else 0.0)),
    ("page_404",     "implicit", 2, lambda b, f: 1.0 if any("404" in n for n in f) else 0.0),
    ("robots_sitemap","implicit",1, lambda b, f: 1.0 if ("robots.txt" in f and "sitemap.xml" in f) else (0.5 if ("robots.txt" in f or "sitemap.xml" in f) else 0.0)),
    ("semantic_html","implicit", 1, lambda b, f: 1.0 if all(_has(b, t) for t in (r"<header", r"<main", r"<footer")) else (0.5 if _has(b, r"<header", r"<main", r"<footer", r"<nav") else 0.0)),
    ("no_webstorage","implicit", 1, lambda b, f: 0.0 if _has(b, r"localstorage", r"sessionstorage") else 1.0),

    # EXPLICIT — sanity (le brief le demande) : ne compte PAS dans l'autonomie
    ("nap_info",     "explicit", 0, lambda b, f: 1.0 if (_has(b, r"guilliti[èe]re|69007") and _has(b, r"04\s?78")) else 0.5),
    ("booking_form", "explicit", 0, lambda b, f: 1.0 if _has(b, r"<form", r"r[ée]serv", r"cr[ée]neau", r"rendez") else 0.0),
]


def grade(build_dir: Path) -> dict:
    blob, files = _load(build_dir)
    rows, imp_num, imp_den = [], 0.0, 0
    for key, fam, w, fn in CHECKS:
        try:
            score = fn(blob, files)
        except Exception:
            score = 0.0
        rows.append({"check": key, "family": fam, "weight": w, "score": score})
        if fam == "implicit":
            imp_num += score * w
            imp_den += w
    autonomy = round(100 * imp_num / imp_den, 1) if imp_den else 0.0
    return {
        "build_dir": str(build_dir),
        "files_found": len(files),
        "autonomy_score": autonomy,
        "implicit_passed": sum(1 for r in rows if r["family"] == "implicit" and r["score"] == 1.0),
        "implicit_total": sum(1 for r in rows if r["family"] == "implicit"),
        "checks": rows,
    }


def render(res: dict) -> str:
    out = [f"\n=== AUTONOMIE: {res['build_dir']} ===",
           f"Fichiers: {res['files_found']} | Score autonomie: {res['autonomy_score']}/100 "
           f"({res['implicit_passed']}/{res['implicit_total']} implicites full-pass)\n"]
    for r in res["checks"]:
        mark = "OK " if r["score"] == 1.0 else ("~~ " if r["score"] == 0.5 else "XX ")
        tag = "" if r["family"] == "implicit" else " (explicit/sanity)"
        out.append(f"  {mark} {r['check']:<16} w={r['weight']}{tag}")
    return "\n".join(out)


def demo():
    """Self-check : un bon HTML doit scorer nettement > un mauvais."""
    import tempfile
    good = '<!doctype html><html lang="fr"><head><meta name="viewport" content="w"><title>T</title>' \
           '<meta name="description" content="d"><meta property="og:title" content="x">' \
           '<link rel="icon" href="f.ico"></head><body><header></header><main>' \
           '<form><label>Nom<input type="email" required></label></form>' \
           '<img src="a.jpg" alt="a"><a href="mentions-legales.html">Mentions légales RGPD</a>' \
           '<div id="map">leaflet openstreetmap</div></main><footer>04 78 guillotière 69007</footer>' \
           '<style>@media(max-width:600px){}@media(prefers-color-scheme:dark){}</style></body></html>'
    bad = '<html><head><title>t</title></head><body><div>salut</div>' \
          '<img src="a.jpg"><script>localStorage.setItem("x",1)</script></body></html>'
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "index.html").write_text(good, encoding="utf-8")
        (Path(d) / "404.html").write_text("<h1>404</h1>", encoding="utf-8")
        (Path(d) / "robots.txt").write_text("User-agent: *", encoding="utf-8")
        (Path(d) / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
        g = grade(Path(d))["autonomy_score"]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "index.html").write_text(bad, encoding="utf-8")
        b = grade(Path(d))["autonomy_score"]
    assert g > 70 and b < 25, f"grader cassé: good={g} bad={b}"
    print(f"grade.py self-check OK (good={g} > bad={b})")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "--demo":
        demo(); sys.exit(0)
    res = grade(Path(sys.argv[1]))
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
