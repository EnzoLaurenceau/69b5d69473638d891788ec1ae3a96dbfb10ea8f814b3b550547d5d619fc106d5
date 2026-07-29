"""security_audit.py — audit sécurité déterministe de la Forge (0 token LLM).

Trois axes, tous vérifiables mécaniquement — aucun jugement de LLM, donc aucune
hallucination possible :

  1. SURFACE HTTP   — chaque route FastAPI appelle-t-elle réellement la garde d'auth ?
                      (une route non gardée est exposée, quelle que soit la politique)
  2. INJECTION      — shell=True, os.system, eval/exec, pickle, SQL concaténé
  3. DÉPENDANCES    — versions épinglées ? CVE connues (pip-audit si présent)

Le point 1 est le plus important : la politique d'auth peut être parfaite, si 60 routes
ne l'appellent pas, elles sont ouvertes.

CLI :
    python 00_CORE/tools/security_audit.py
    python 00_CORE/tools/security_audit.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
_CORE = str(FORGE_ROOT / "00_CORE")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

SERVER = FORGE_ROOT / "09_WEB" / "server.py"
AUTH_FN = "_check_auth"

#: routes volontairement publiques (pas de donnée sensible)
# Publiques par conception. `/metrics` = cible de scrape Prometheus : n'expose QUE des
# métriques d'ops AGRÉGÉES (cache, CPU/RAM, tokens économisés), aucune donnée tenant ;
# en prod elle n'est jointe que par Prometheus sur le réseau interne (jamais l'ingress public).
PUBLIC_OK = {"/", "/health", "/api/health", "/neural_map", "/metrics-details",
             "/vault.html", "/metrics"}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SURFACE HTTP
# ═══════════════════════════════════════════════════════════════════════════════

def _route_of(dec: ast.AST) -> tuple[str, str] | None:
    """(<méthode>, <chemin>) si le décorateur est une route FastAPI."""
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    method = dec.func.attr
    if method not in {"get", "post", "put", "delete", "patch", "websocket"}:
        return None
    if not dec.args or not isinstance(dec.args[0], ast.Constant):
        return None
    return method.upper(), str(dec.args[0].value)


def audit_http() -> dict:
    if not SERVER.exists():
        return {"error": f"{SERVER} introuvable"}
    text = SERVER.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)

    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            r = _route_of(dec)
            if not r:
                continue
            method, path = r
            body = ast.dump(node)
            guarded = f"'{AUTH_FN}'" in body or AUTH_FN in body
            # une route WebSocket gère l'auth en ligne (pas via _check_auth)
            inline = "WEB_SECRET" in body
            routes.append({
                "method": method, "path": path, "handler": node.name,
                "line": node.lineno,
                "guarded": bool(guarded or inline),
                "public_by_design": path in PUBLIC_OK,
            })

    unguarded = [r for r in routes
                 if not r["guarded"] and not r["public_by_design"]]
    return {
        "total_routes": len(routes),
        "guarded": sum(1 for r in routes if r["guarded"]),
        "public_by_design": sum(1 for r in routes if r["public_by_design"]),
        "unguarded_count": len(unguarded),
        "unguarded": sorted(unguarded, key=lambda r: r["path"])[:40],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INJECTION
# ═══════════════════════════════════════════════════════════════════════════════

INJECTION_RULES = [
    ("shell_true", re.compile(r"subprocess\.(?:run|Popen|call|check_output)\([^)]*shell\s*=\s*True"), "HIGH"),
    ("os_system", re.compile(r"\bos\.system\s*\("), "HIGH"),
    ("eval", re.compile(r"(?<![\w.])eval\s*\("), "HIGH"),
    ("exec", re.compile(r"(?<![\w.])exec\s*\("), "HIGH"),
    ("pickle_load", re.compile(r"pickle\.loads?\s*\("), "MEDIUM"),
    ("yaml_unsafe", re.compile(r"yaml\.load\s*\((?![^)]*Loader\s*=\s*yaml\.SafeLoader)"), "MEDIUM"),
    ("sql_concat", re.compile(r"(?:execute|executemany)\s*\(\s*[\"'][^\"']*[\"']\s*[+%]"), "HIGH"),
]


def _sql_fstring_sites(text: str, rel: str) -> list:
    """`execute(f"…")` SANS paramètres séparés — le seul cas réellement injectable.

    Un regex naïf signalait 33 sites dans `forge_db.py` qui interpolent des NOMS DE
    COLONNES tandis que les valeurs partent en paramètres (`cur.execute(f"…", vals)`).
    Ce n'est pas une injection. On exige donc, via AST, que l'appel n'ait qu'UN argument.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    # Variables issues d'un échappement : `name_e = _esc(name)`. Sans ce suivi, toute
    # valeur échappée puis stockée dans une variable était signalée à tort.
    escaped_vars = {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", "") in SANITIZERS
        for t in n.targets
        if isinstance(t, ast.Name)
    }

    def _covered(fv: ast.FormattedValue) -> bool:
        v = fv.value
        if isinstance(v, ast.Call) and getattr(v.func, "id", "") in SANITIZERS:
            return True
        return isinstance(v, ast.Name) and v.id in escaped_vars

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"execute", "executemany"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.JoinedStr):
            continue
        if len(node.args) > 1:      # valeurs paramétrées → sûr
            continue
        js = node.args[0]
        literal = "".join(v.value for v in js.values
                          if isinstance(v, ast.Constant) and isinstance(v.value, str))
        # DDL : un nom de table/colonne n'est JAMAIS paramétrable en SQL — hors scope injection
        if re.match(r"\s*(CREATE|ALTER|DROP)\b", literal, re.I):
            continue
        # toutes les interpolations passent par une fonction d'échappement → couvert
        interps = [v for v in js.values if isinstance(v, ast.FormattedValue)]
        if interps and all(_covered(v) for v in interps):
            continue
        out.append(f"{rel}:{node.lineno}")
    return out


#: Fonctions qui rendent une interpolation sûre. `_esc` échappe une valeur entre quotes.
#: `_num` couvre le cas que `_esc` NE couvre pas — une valeur numérique n'est pas entre
#: quotes, l'échapper ne la protège de rien. `_label` traite la structure (nom de table,
#: type d'arête) : elle n'est jamais paramétrable, la liste blanche est la seule défense.
SANITIZERS = {"_esc", "escape", "_num", "_label"}

#: Sites HIGH revus un par un et assumés. Même cliquet que `state_ownership.py` : la
#: liste borne ce qui existe, et tout site NOUVEAU fait échouer la porte. Un chiffre seul
#: ("15 HIGH tolérés") ne dirait pas lesquels, et laisserait un vrai bug se glisser dans
#: le quota d'un site corrigé.
#:
#: Coût assumé : la clé est `fichier:ligne`, donc déplacer du code fait échouer la porte
#: et oblige à re-viser la ligne. C'est bruyant, et c'est voulu — sur du HIGH, re-lire
#: coûte moins cher que laisser passer.
REVIEWED_INJECTION: dict[str, str] = {
    "00_CORE/forge_agents/graph_db.py:273":
        "add_repository SET: stars/occurrences/priority/cloned par _num, url par _esc",
    "00_CORE/forge_agents/graph_db.py:352":
        "create_edge MATCH+CREATE: from_label/to_label/edge_type/pk issus de NODE_TABLES/EDGE_TABLES "
        "(constantes module), keys par _esc, weight/ctx par _num/_esc",
    "00_CORE/forge_agents/graph_db.py:463":
        "get_orphan_nodes: label/pk issus de NODE_TABLES (constantes), pas de user input",
    "00_CORE/forge_agents/graph_db.py:483":
        "delete_node: label/pk issus de NODE_TABLES (constantes), key par _esc",
    "00_CORE/forge_agents/graph_db.py:537":
        "get_edges: from_label/to_label/edge_type/pk issus de NODE_TABLES/EDGE_TABLES "
        "(constantes module), where par _esc, max_nodes par _num",
    "00_CORE/forge_agents/graph_db.py:573":
        "get_edges: idem :537, limit par _num",
    "00_CORE/forge_agents/world_kg.py:571":
        "upsert (branche UPDATE) : `label` validé par _label contre WORLD_NODE_TABLES, "
        "`sets` n'assemble que des clés déjà refusées si hors whitelist (`unknown` lève) "
        "et des valeurs encodées par _literal, `node_id` dérivé par world_key puis _esc — "
        "rien n'y vient de l'appelant sans contrôle (même motif que graph_db.py:348)",
    "00_CORE/forge_agents/forge_db_fallback.py:128":
        "nom de table validé contre _DEEP_TABLES deux lignes plus haut ; non paramétrable en SQL",
    "00_CORE/forge_agents/knowledge_curator.py:620":
        "orphan pruning: pk issu de NODE_TABLES (constante), key par _esc",
    "00_CORE/tools/rtk.py:76":
        "shell=True EST la fonction du wrapper (replier une commande shell quand le binaire manque)",
    "00_CORE/tools/dev/openhands.py:145":
        "template fourni par l'opérateur via OPENHANDS_CMD ; plafond documenté sur place",
    "00_CORE/tools/full_graph_connect.py:167":
        "agent lookup: canon issu de agent_map (constante module), pas de user input",
    "00_CORE/tools/full_graph_connect.py:475":
        "concept lookup: debt/arch issus de debt_to_arch (constante module)",
    "00_CORE/tools/full_graph_connect.py:499":
        "concept lookup: concept/adr issus de concept_adr (constante module)",
}


def audit_injection() -> dict:
    from forge_agents.tech_debt import collect_files
    hits: dict = {k: [] for k, _r, _s in INJECTION_RULES}
    for abs_p, rel, _z in collect_files(include_vendored=False):
        if abs_p.suffix.lower() != ".py":
            continue
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, rx, _sev in INJECTION_RULES:
            for m in rx.finditer(text):
                line = text[: m.start()].count("\n") + 1
                hits[name].append(f"{rel.as_posix()}:{line}")
        hits.setdefault("sql_fstring_unparameterized", []).extend(
            _sql_fstring_sites(text, rel.as_posix()))
    sev = {k: s for k, _r, s in INJECTION_RULES}
    sev["sql_fstring_unparameterized"] = "HIGH"
    return {
        "by_rule": {k: {"severity": sev[k], "count": len(v), "sites": v[:12]}
                    for k, v in hits.items() if v},
        "total": sum(len(v) for v in hits.values()),
        "high_total": sum(len(v) for k, v in hits.items() if sev[k] == "HIGH"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DÉPENDANCES
# ═══════════════════════════════════════════════════════════════════════════════

def audit_deps() -> dict:
    req = FORGE_ROOT / "requirements.txt"
    out: dict = {"requirements_present": req.exists()}
    if req.exists():
        lines = [l.strip() for l in req.read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        pinned = [l for l in lines if re.search(r"==\s*\d", l)]
        out.update({
            "declared": len(lines),
            "pinned": len(pinned),
            "unpinned": len(lines) - len(pinned),
            "unpinned_sample": [l for l in lines if l not in pinned][:12],
        })
    tool = shutil.which("pip-audit")
    if not tool:
        out["cve_scan"] = "pip-audit absent — CVE non vérifiées (pip install pip-audit)"
        return out
    try:
        p = subprocess.run([tool, "-f", "json", "--progress-spinner", "off"],
                           capture_output=True, text=True, timeout=300, cwd=FORGE_ROOT)
        data = json.loads(p.stdout or "{}")
        vulns = [d for d in data.get("dependencies", []) if d.get("vulns")]
        out["cve_scan"] = "ok"
        out["vulnerable_packages"] = [
            {"name": d.get("name"), "version": d.get("version"),
             "ids": [v.get("id") for v in d.get("vulns", [])]} for d in vulns][:20]
        out["vulnerable_count"] = len(vulns)
    except Exception as exc:
        out["cve_scan"] = f"pip-audit a échoué: {exc}"
    return out


def run() -> dict:
    return {"http": audit_http(), "injection": audit_injection(), "deps": audit_deps()}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Audit sécurité déterministe")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="porte CI : échoue sur tout site HIGH non revu")
    args = ap.parse_args()
    r = run()
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0

    if args.check:
        sites = [s for d in r["injection"]["by_rule"].values()
                 if d["severity"] == "HIGH" for s in d["sites"]]
        nouveaux = sorted(set(sites) - set(REVIEWED_INJECTION))
        corriges = sorted(set(REVIEWED_INJECTION) - set(sites))
        for s in nouveaux:
            print(f"  NOUVEAU SITE HIGH  {s}  -> corriger, ou justifier dans REVIEWED_INJECTION")
        for s in corriges:
            print(f"  corrigé : retirer de REVIEWED_INJECTION -> {s}")
        print(f"HIGH: {len(sites)} dont {len(sites) - len(nouveaux)} revus")
        print("PORTE " + ("ÉCHEC" if (nouveaux or corriges) else "OK"))
        return 1 if (nouveaux or corriges) else 0

    h = r["http"]
    print("=== 1. SURFACE HTTP ===")
    if "error" in h:
        print("  ", h["error"])
    else:
        print(f"routes: {h['total_routes']} | gardées: {h['guarded']} | "
              f"publiques assumées: {h['public_by_design']} | NON GARDÉES: {h['unguarded_count']}")
        for u in h["unguarded"][:25]:
            print(f"   {u['method']:<10}{u['path']:<38}{u['handler']} (L{u['line']})")

    i = r["injection"]
    print(f"\n=== 2. INJECTION === total={i['total']} dont HIGH={i['high_total']}")
    for name, d in sorted(i["by_rule"].items(), key=lambda kv: -kv[1]["count"]):
        print(f"   {name:<14}{d['severity']:<7}{d['count']:>4}  ex: {d['sites'][0] if d['sites'] else ''}")

    d = r["deps"]
    print("\n=== 3. DÉPENDANCES ===")
    if d.get("requirements_present"):
        print(f"déclarées: {d['declared']} | épinglées: {d['pinned']} | NON épinglées: {d['unpinned']}")
        if d.get("unpinned_sample"):
            print("   non épinglées:", ", ".join(d["unpinned_sample"][:8]))
    else:
        print("requirements.txt absent")
    print("   CVE:", d.get("cve_scan"))
    if d.get("vulnerable_count"):
        print(f"   paquets vulnérables: {d['vulnerable_count']}")
        for v in d.get("vulnerable_packages", [])[:8]:
            print(f"     {v['name']}=={v['version']}: {', '.join(v['ids'][:3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
