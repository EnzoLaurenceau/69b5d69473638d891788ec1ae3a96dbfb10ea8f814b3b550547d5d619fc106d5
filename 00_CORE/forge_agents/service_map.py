"""service_map.py — bounded contexts et cohésion, dérivés du graphe d'imports RÉEL.

À QUOI ÇA SERT
--------------
Un contexte n'est extractible en service que si peu d'arêtes le traversent. Extraire un
module qui appelle 55 fois l'extérieur ne crée pas un microservice mais un **monolithe
distribué** : mêmes couplages, plus la latence réseau et les pannes partielles.

Ce module mesure ça. Il ne propose pas d'architecture : il dit laquelle est possible.

    cohésion = liens_internes / (liens_internes + liens_sortants)

DÉCOUVERTE QUI A MOTIVÉ LA V2
-----------------------------
La première passe rangeait 149 modules (~40 % du code) dans « divers ». En les inspectant,
~50 venaient de `tg-bot-workflow/` — une **application cliente complète** (bot Telegram,
réservation d'hôtel) hébergée dans le dépôt de la Forge. Elle faussait toute la mesure.
Les produits tiers sont désormais isolés comme tels : ce ne sont pas des contextes de la
Forge, ce sont d'autres logiciels.

CLI :
    python -m forge_agents.service_map
    python -m forge_agents.service_map --json
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("ServiceMap")

FORGE_ROOT = Path(__file__).resolve().parents[2]

#: Produits tiers hébergés dans le dépôt — PAS des contextes de la Forge.
FOREIGN_PRODUCTS = ("tg-bot-workflow", "tg-bot-workflow-v2", "demo_partna",
                    "token_comparison_cafe_bastoche", "mvp_output", "site_forge")

#: Répertoires dont l'appartenance PRIME sur le nom de fichier, évalués en premier.
#: Sans cela, `00_CORE/trading/orchestrator.py` tombait dans « orchestration » (la règle
#: `orchestr` matchant avant `trading`) : du code trading fuyait dans l'orchestration,
#: gonflant ses liens sortants et faussant les deux cohésions à la fois.
DIR_RULES: list[tuple[str, tuple]] = [
    # Consolidé (W5-03g) : `forge_trading/` est désormais UN package à nom valide.
    # Les anciennes racines restent listées pour qu'un dépôt non migré se mesure encore.
    ("trading",             ("forge_trading/", "00_core/trading/", "10_trading/")),
    ("edition (MCPT)",      ("semantic_edit_engine/",)),
    ("outils externes",     ("00_core/tools/",)),
    ("passerelle HTTP",     ("09_web/",)),
]

#: Règles de classement, évaluées DANS L'ORDRE (la première qui matche gagne).
#: Chaque entrée : (contexte, prédicat sur le chemin en minuscules)
RULES: list[tuple[str, tuple]] = [
    ("socle multi-tenant", ("forge_tenant", "forge_store", "forge_identity", "forge_quota")),
    ("edition (MCPT)",     ("semantic_edit_engine", "see_edit", "fix_silent_failures",
                            "fix_hardcoded_paths")),
    ("securite offensive", ("zsl_cyber", "bbril_pipeline", "reverse_engineering",
                            "pentest_datasets", "openviking", "decepticon", "osint",
                            "security_audit", "nanomachine")),
    ("qualite / garde-fous", ("hallucination", "anti_halluc", "neuro_symbolic", "harness",
                              "legal_compliance", "no_mistakes", "mirofish", "guards",
                              "judge", "fallow_guard", "eval")),
    ("observabilite",      ("metric", "observab", "token_tracker", "token_sprint",
                            "telemetry", "forge_health", "tech_debt", "debt_priority",
                            "swarm", "execution_logger", "tool_call_ledger", "agent_tracker",
                            "service_map", "caveman_logger")),
    ("memoire / connaissance", ("rag", "kb_manager", "knowledge", "dataset", "graph_db",
                                "memory", "experience", "shared_brain", "cervelet",
                                "turbovec", "nmp_encoder", "graphify", "vault", "curator")),
    ("persistance",        ("forge_db", "forge_db_fallback", "helixdb", "checkpoint",
                            "versioning", "state", "nexus_bridge")),
    ("routage LLM",        ("forge_llm", "mimo", "router", "semantic_cache", "batcher",
                            "fingerprint", "inference_patch", "load_balancer", "lazy",
                            "chat_provider", "ds2api", "pxpipe", "lmcache")),
    ("orchestration",      ("forge_graph", "agent_nodes", "orchestr", "forge_team",
                            "forge_spine", "forge_kernel", "dispatch", "complexification",
                            "topology", "a2a_protocol", "ail_protocol", "meta", "self_heal",
                            "reuse_engine", "system_registry", "event_bus", "auto_tool")),
    ("data science / ML",  ("data_scientist", "finetune", "evomap", "neural_markov",
                            "prompt_architect", "agency_personas", "agent_skills")),
    ("generation de contenu", ("design_assets", "gen_games", "research_enrichment",
                               "data_tagger", "metadata_schema", "scraping", "scrapling",
                               "multi_source_brain", "mcp_pruner", "opt_out")),
    ("passerelle HTTP",    ("09_web/", "server.py", "forge_n8n", "n8n_bridge", "gateway")),
    ("trading",            ("trading", "smc_", "backtest")),
    ("outils externes",    ("00_core/tools/",)),
    ("operations / CLI",   ("scripts/", "run_forge", "run_test", "session_transfer",
                            "tool_index", "forge_dispatcher", "bootstrap")),
    ("tests",              ("test_", "_test.py")),
]


def _external_names() -> set:
    """Noms importables depuis la stdlib ou les paquets installés.

    Sert à ne PAS confondre un fichier local avec une bibliothèque du même nom.
    Calculé une fois, tolérant : si l'introspection échoue, on retombe sur la stdlib seule.
    """
    names = set(getattr(sys, "stdlib_module_names", set()))
    try:
        import site
        for root in site.getsitepackages() + [site.getusersitepackages()]:
            d = Path(root)
            if not d.is_dir():
                continue
            for entry in d.iterdir():
                n = entry.name.split("-")[0].split(".")[0]
                if n and not n.startswith("_"):
                    names.add(n)
    except Exception as exc:               # environnement exotique : stdlib suffit
        logger.debug("introspection site-packages impossible: %s", exc)
    return names


_EXTERNAL_NAMES = _external_names()


def classify(path: str) -> str:
    """Contexte d'un module. `produit: <nom>` pour un logiciel tiers hébergé ici."""
    p = path.lower()
    for prod in FOREIGN_PRODUCTS:
        if p.startswith(prod.lower() + "/"):
            return f"produit: {prod}"
    for ctx, dirs in DIR_RULES:          # le répertoire prime sur le nom de fichier
        if any(d in p for d in dirs):
            return ctx
    for ctx, needles in RULES:
        if any(n in p for n in needles):
            return ctx
    return "non classe"


def _module_keys(rel: Path) -> set:
    parts = rel.with_suffix("").parts
    keys = {parts[-1]}
    if len(parts) >= 2:
        keys.add(".".join(parts[-2:]))
    if parts[-1] == "__init__" and len(parts) >= 2:
        keys.add(parts[-2])
    return keys


def _imports_of(tree: ast.AST) -> set:
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
            for a in node.names:
                out.add(a.name)
    return out


def build() -> dict:
    """Graphe d'imports + agrégats de cohésion par contexte."""
    from .tech_debt import collect_files

    parsed: dict[str, dict] = {}
    for abs_p, rel, _z in collect_files(include_vendored=False):
        if abs_p.suffix.lower() not in {".py", ".pyi"}:
            continue
        try:
            tree = ast.parse(abs_p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        parsed[rel.as_posix()] = {"keys": _module_keys(rel), "imports": _imports_of(tree)}

    # Une clé partagée par plusieurs fichiers crée des arêtes FANTÔMES : `__init__`
    # désignait 49 fichiers, `config`/`database`/`app` plusieurs chacun. Résultat mesuré
    # avant correction : 43 liens « bot Telegram → trading », qui n'existent pas.
    # On ne garde donc que les clés identifiant UN SEUL module.
    key_owners: dict[str, list] = collections.defaultdict(list)
    for f, meta in parsed.items():
        for k in meta["keys"]:
            key_owners[k].append(f)
    unique_key = {k: v[0] for k, v in key_owners.items() if len(v) == 1}

    # Un nom de fichier local peut percuter un PAQUET TIERS : `import redis` visait le
    # paquet PyPI, pas `tg-bot-workflow/.../redis.py` — d'où 3 fausses dépendances
    # « Forge → produit client ». Idem `engine` (SQLAlchemy). On retire du graphe tout
    # nom résoluble comme module externe : un import ambigu appartient à la bibliothèque.
    for name in list(unique_key):
        if "." in name:
            continue                       # clé à 2 composants : non ambiguë
        if name in _EXTERNAL_NAMES:
            unique_key.pop(name, None)

    edges: dict[str, set] = collections.defaultdict(set)
    for src, a in parsed.items():
        for imported in a["imports"]:
            dst = unique_key.get(imported)
            if dst and dst != src:
                edges[src].add(dst)

    groups: dict[str, list] = collections.defaultdict(list)
    for f in parsed:
        groups[classify(f)].append(f)

    contexts = []
    for ctx, files in groups.items():
        fs = set(files)
        internal = sum(len(edges[f] & fs) for f in files)
        outgoing = sum(len(edges[f] - fs) for f in files)
        total = internal + outgoing
        contexts.append({
            "context": ctx, "modules": len(files),
            "internal": internal, "outgoing": outgoing,
            "cohesion": round(internal / total, 3) if total else 1.0,
            "extractable": total > 0 and (internal / total) >= 0.70 and outgoing <= 10,
        })
    contexts.sort(key=lambda c: -c["cohesion"])

    cross = collections.Counter()
    for src, dsts in edges.items():
        cs = classify(src)
        for d in dsts:
            cd = classify(d)
            if cs != cd:
                cross[(cs, cd)] += 1

    return {
        "modules_total": len(parsed),
        "contexts": contexts,
        "unclassified": sorted(groups.get("non classe", []))[:40],
        "cross_edges": [{"from": a, "to": b, "links": n} for (a, b), n in cross.most_common(12)],
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Carte des bounded contexts")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = build()
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0

    print(f"modules analysés : {r['modules_total']}\n")
    print(f"{'bounded context':<26}{'mods':>6}{'int.':>7}{'sort.':>7}{'cohésion':>10}  extractible")
    for c in r["contexts"]:
        flag = "OUI" if c["extractable"] else ""
        print(f"{c['context']:<26}{c['modules']:>6}{c['internal']:>7}{c['outgoing']:>7}"
              f"{c['cohesion']:>9.0%}  {flag}")
    unc = next((c for c in r["contexts"] if c["context"] == "non classe"), None)
    if unc:
        print(f"\nnon classés : {unc['modules']} modules")
        for f in r["unclassified"][:12]:
            print("   ", f)
    print("\ncouplages inter-contextes les plus lourds :")
    for e in r["cross_edges"][:8]:
        print(f"   {e['links']:>4}  {e['from']}  ->  {e['to']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
