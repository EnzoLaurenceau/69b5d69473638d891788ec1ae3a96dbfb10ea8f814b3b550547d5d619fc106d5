"""debt_priority.py — classe les findings de dette par IMPACT RÉEL, pas par sévérité déclarée.

Un `except: pass` dans un script jetable et le même dans `forge_llm.py` (importé par tout le
noyau) n'ont pas la même valeur de correction. Ce module croise :

    findings (05_STATE/swarm_audit.json)  ×  blast radius (graphe de dépendances inverse)

POURQUOI PAS GITNEXUS
---------------------
`gitnexus impact <symbole>` est la source d'autorité, mais mesuré à **89 s par appel** sur ce
dépôt (chargement d'un index de 885 Mo) — soit >2 h pour les ~100 fichiers concernés, et il ne
résout pas tous les symboles. On calcule donc le blast radius nous-mêmes : parcours AST du
corpus déjà scopé, 0 token, < 5 s. C'est un PROXY assumé (voir §Limites), pas l'équivalent exact.

Score = poids(sévérité) × poids(catégorie) × (1 + log2(1 + dépendants))

CLI :
    python 00_CORE/forge_agents/debt_priority.py
    python 00_CORE/forge_agents/debt_priority.py --top 30
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("DebtPriority")

FORGE_ROOT = Path(__file__).resolve().parents[2]


def AUDIT_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("swarm_audit.json")


def OUT_JSON() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("debt_priority.json")


OUT_MD = FORGE_ROOT / "07_REPORTS" / "DEBT_PRIORITY.md"

# Un défaut qui fait ÉCHOUER silencieusement pèse plus qu'un module mort.
SEVERITY_W = {"CRITICAL": 10.0, "HIGH": 6.0, "MEDIUM": 3.0, "LOW": 1.0}
CATEGORY_W = {
    "security": 1.6, "silent-failure": 1.4, "bug": 1.3, "correctness-risk": 1.2,
    "config-risk": 1.0, "duplication": 0.7, "dead-code": 0.5, "complexity": 0.6,
}


def _module_keys(rel: Path) -> set:
    """Clés sous lesquelles ce fichier peut être importé ailleurs."""
    parts = rel.with_suffix("").parts
    keys = {parts[-1]}
    if len(parts) >= 2:
        keys.add(".".join(parts[-2:]))
    if parts[-1] == "__init__" and len(parts) >= 2:
        keys.add(parts[-2])
    return keys


def _imports_of(tree: ast.AST) -> set:
    """Modules importés, réduits à leurs composants (pour matcher les clés ci-dessus)."""
    out: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[-1])
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.add(node.module.split(".")[-1])
                out.add(node.module)
            for a in node.names:          # `from pkg import module`
                out.add(a.name)
    return out


def _defined_symbols(tree: ast.AST) -> set:
    return {n.name for n in ast.iter_child_nodes(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not n.name.startswith("_")}


def _used_identifiers(text: str) -> set:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text))


def build_blast_graph() -> dict:
    """Dépendants par fichier : combien d'autres fichiers l'importent ou citent ses symboles."""
    from .tech_debt import collect_files

    files = collect_files(include_vendored=False)
    parsed: dict[str, dict] = {}
    for abs_p, rel, _zone in files:
        if abs_p.suffix.lower() not in {".py", ".pyi"}:
            continue
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        parsed[rel.as_posix()] = {
            "keys": _module_keys(rel),
            "imports": _imports_of(tree),
            "symbols": _defined_symbols(tree),
            "idents": _used_identifiers(text),
        }

    # Arêtes UNIQUEMENT par import. Un repli « identifiant partagé » avait été tenté :
    # il matchait des noms courants (`configure`, `run`, `deploy`…) et attribuait 222
    # dépendants à un outil feuille. Trop bruyant pour valoir mieux que rien — supprimé.
    importers: dict[str, set] = defaultdict(set)
    for src, a in parsed.items():
        for tgt, b in parsed.items():
            if src != tgt and (a["imports"] & b["keys"]):
                importers[tgt].add(src)

    return {f: {"dependents": len(importers.get(f, ())),
                "dependent_files": sorted(importers.get(f, ()))[:8]}
            for f in parsed}


def prioritize(audit_path: Path = AUDIT_PATH()) -> dict:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    blast = build_blast_graph()

    ranked = []
    for f in audit.get("findings", []):
        b = blast.get(f["file"], {"dependents": 0, "dependent_files": []})
        dep = b["dependents"]
        score = (SEVERITY_W.get(f["severity"], 1.0)
                 * CATEGORY_W.get(f["category"], 1.0)
                 * (1.0 + math.log2(1 + dep)))
        ranked.append({**f, "dependents": dep, "dependent_files": b["dependent_files"],
                       "priority": round(score, 2)})
    ranked.sort(key=lambda x: -x["priority"])

    by_file: dict[str, dict] = defaultdict(lambda: {"findings": 0, "priority": 0.0, "dependents": 0})
    for r in ranked:
        e = by_file[r["file"]]
        e["findings"] += 1
        e["priority"] = round(e["priority"] + r["priority"], 2)
        e["dependents"] = r["dependents"]

    hotspots = sorted(({"file": k, **v} for k, v in by_file.items()),
                      key=lambda x: -x["priority"])

    return {
        "source_audit": str(audit_path),
        "method": "graphe de dépendances inverse déterministe (proxy du blast radius ; "
                  "gitnexus impact mesuré à 89 s/appel, inutilisable à cette échelle)",
        "weights": {"severity": SEVERITY_W, "category": CATEGORY_W},
        "total_findings": len(ranked),
        "findings": ranked,
        "hotspots": hotspots,
    }


def render_md(report: dict, top: int = 25) -> str:
    L = ["# Dette technique — priorisée par impact", "",
         f"> Source : `{Path(report['source_audit']).name}` · {report['total_findings']} findings",
         f"> Méthode : {report['method']}", "",
         "`priorité = poids(sévérité) × poids(catégorie) × (1 + log2(1 + dépendants))`", "",
         "## Fichiers les plus rentables à corriger", "",
         "| # | Fichier | Priorité | Findings | Dépendants |", "|---|---|---|---|---|"]
    for i, h in enumerate(report["hotspots"][:15], 1):
        L.append(f"| {i} | `{h['file']}` | {h['priority']:.0f} | {h['findings']} | {h['dependents']} |")
    L += ["", f"## Top {top} findings individuels", "",
          "| # | Prio | Sév. | Cat. | Emplacement | Défaut |", "|---|---|---|---|---|---|"]
    for i, f in enumerate(report["findings"][:top], 1):
        title = f["title"].replace("|", "/")[:88]
        L.append(f"| {i} | {f['priority']:.1f} | {f['severity']} | {f['category']} | "
                 f"`{f['file']}:{f['line']}` | {title} |")
    L += ["", "## Limites assumées", "",
          "- Le blast radius est un **proxy** (imports + références de symboles), pas le graphe",
          "  d'appels exact de GitNexus — écarté ici pour cause de latence (89 s/appel).",
          "- Les findings viennent de MiMo : groundés (le code cité existe) et filtrés des",
          "  artefacts de découpage, mais **non vérifiés un par un**. Priorité haute = à",
          "  regarder en premier, pas « défaut prouvé ».",
          "- Les poids sont des hypothèses explicites, ajustables en tête de `debt_priority.py`."]
    return "\n".join(L)


def _main() -> int:
    ap = argparse.ArgumentParser(description="Priorise la dette par impact")
    ap.add_argument("--audit", default=str(AUDIT_PATH()))
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    report = prioritize(Path(args.audit))
    OUT_JSON().write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_md(report, args.top), encoding="utf-8")

    print(f"{report['total_findings']} findings priorisés")
    print(f"\n{'#':<3}{'prio':>7}  {'sév':<9}{'dép':>5}  fichier")
    for i, h in enumerate(report["hotspots"][:12], 1):
        print(f"{i:<3}{h['priority']:>7.0f}  {'':<9}{h['dependents']:>5}  {h['file']}")
    print(f"\nTop 5 findings :")
    for f in report["findings"][:5]:
        print(f"  [{f['priority']:.1f}] {f['severity']:<8} {f['file']}:{f['line']} — {f['title'][:70]}")
    print(f"\n-> {OUT_JSON()}\n-> {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
