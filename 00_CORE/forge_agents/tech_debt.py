"""tech_debt.py — mesure déterministe de la dette technique + découpage en zones.

Contexte d'échelle (mesuré le 2026-07-22) : le dépôt fait 11,52 Go / 384 386 fichiers,
mais **93 % du compte est de la donnée** (`cvelistV5-main` = 356 021 fichiers CVE) et
**50 % des octets** sont des datasets (`07_KNOWLEDGE_BASE`). La surface de code réelle
est de ~4 010 fichiers / 41,5 Mo. Un scanner qui fait `walk(ROOT)` ne finit jamais ;
celui-ci est **piloté par un scope déclaré** et parcourt la surface utile en < 1 s.

Deux passes, aucune n'appelle de LLM :
  1. par fichier — AST Python (stdlib) : taille, complexité, imports morts, pièges
  2. par corpus  — duplication exacte de corps de fonctions, symboles non référencés

La sortie sert à deux choses :
  - `05_STATE/tech_debt.json` — l'inventaire chiffré
  - `plan_zones()` — le découpage en chunks équilibrés, pour un examen parallèle

Ce module MESURE. Il ne juge pas : un score élevé signale « à regarder », pas « à
réparer ». Le jugement est l'étape suivante (agents), la priorisation vient du
croisement avec le blast radius GitNexus (W3-03).

CLI :
    python 00_CORE/forge_agents/tech_debt.py            # scan + rapport
    python 00_CORE/forge_agents/tech_debt.py --all      # inclut le code vendored
    python 00_CORE/forge_agents/tech_debt.py --zones 10 # découpage en 10 chunks
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("TechDebt")

FORGE_ROOT = Path(__file__).resolve().parents[2]


def OUT_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("tech_debt.json")


# ═══════════════════════════════════════════════════════════════════════════════
# SCOPE — la décision de conception centrale (cf. docstring)
# ═══════════════════════════════════════════════════════════════════════════════

#: jamais descendus : données, index, artefacts, environnements
EXCLUDE_DIRS = {
    ".git", ".gitnexus", ".nexus", "__pycache__", "node_modules", "venv", ".venv",
    "env", "site-packages", "dist", "build", "target", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "parse-cache", "parsedfile-cache", ".next", ".cache", "coverage",
    "cvelistV5-main",        # 356 021 fichiers de CVE — donnée, pas code
    "07_KNOWLEDGE_BASE",     # 5,73 Go de datasets
    "nexus-data", "vault", "09_ARCHIVE", "graphify-out",
}

EXCLUDE_FILE_RE = re.compile(r"\.min\.(js|css)$|\.bundle\.js$|_pb2\.py$|\.generated\.")

CODE_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".rs": "rust", ".go": "go", ".java": "java", ".sh": "shell", ".ps1": "powershell",
}

#: Zones de scan. `vendored=True` → code tiers : mesuré mais hors périmètre de dette
#: par défaut (le noyer avec le nôtre masquerait les 415 fichiers de 00_CORE sous
#: 3 200 fichiers qu'on ne maintient pas).
ZONES: list[dict] = [
    {"name": "core.agents",    "paths": ["00_CORE/forge_agents"],                    "vendored": False},
    {"name": "core.tools",     "paths": ["00_CORE/tools", "00_CORE/blueprints"],     "vendored": False},
    {"name": "core.misc",      "paths": ["00_CORE"], "exclude_sub": ["forge_agents", "tools", "rtk", "blueprints",
                                                                     "L1B3RT4S", "G0DM0D3", "forge_jailbreak"],
                                                                                     "vendored": False},
    {"name": "pipeline",       "paths": ["01_ORCHESTRATOR", "02_AGENTS", "03_JURY", "04_GRAPHIFY"], "vendored": False},
    {"name": "state.runtime",  "paths": ["05_STATE", "06_FINDINGS", "08_LOGS"],      "vendored": False},
    {"name": "web",            "paths": ["09_WEB", "site_forge"],                    "vendored": False},
    # `forge_trading/` = service consolidé (W5-03g). `10_TRADING` ne contient plus que
    # des données/logs ; il reste listé pour ne pas rendre un dépôt non migré invisible.
    {"name": "trading",        "paths": ["forge_trading", "10_TRADING"],             "vendored": False},
    {"name": "scripts.root",   "paths": ["scripts", "."],                            "vendored": False},
    {"name": "experiments",    "paths": ["09_EXPERIMENTS", "projects", "demo_partna", "mvp_output"], "vendored": False},
    {"name": "herald",         "paths": ["AsyncHerald"],                             "vendored": False},
    {"name": "workflows.bots", "paths": ["tg-bot-workflow", "tg-bot-workflow-v2"],   "vendored": False},
    {"name": "skills.own",     "paths": ["skills"], "exclude_sub": ["hexstrike-ai"], "vendored": False},
    # ── vendored ──────────────────────────────────────────────────────────────
    {"name": "vendor.nexus",     "paths": ["nexus"],                "vendored": True},
    {"name": "vendor.rtk",       "paths": ["00_CORE/rtk"],          "vendored": True},
    {"name": "vendor.hexstrike", "paths": ["skills/hexstrike-ai"],  "vendored": True},
    {"name": "vendor.recursive", "paths": ["RecursiveMAS", "impeccable", "ds2api"], "vendored": True},
]

# ═══════════════════════════════════════════════════════════════════════════════
# SEUILS — explicites, discutables, pas cachés dans le code
# ═══════════════════════════════════════════════════════════════════════════════

T_FILE_SLOC = 500        # au-delà : fichier trop gros
T_FUNC_SLOC = 60         # au-delà : fonction trop longue
T_COMPLEXITY = 12        # McCabe approximé
T_DUP_SLOC = 8           # taille min d'un corps pour compter comme duplication

WEIGHTS = {
    "size": 1.0, "func_len": 1.5, "complexity": 2.0, "unused_import": 1.0,
    "bare_except": 3.0, "silent_except": 4.0, "todo": 0.5, "duplication": 2.5,
    "unreferenced": 1.5, "print": 0.3, "syntax_error": 10.0,
}


@dataclass
class FileDebt:
    path: str = ""
    zone: str = ""
    language: str = "unknown"
    vendored: bool = False
    sloc: int = 0
    bytes: int = 0
    functions: int = 0
    max_func_sloc: int = 0
    max_complexity: int = 0
    complex_functions: list = field(default_factory=list)
    long_functions: list = field(default_factory=list)
    unused_imports: list = field(default_factory=list)
    todos: int = 0
    bare_excepts: int = 0
    silent_excepts: int = 0
    prints: int = 0
    duplicated_blocks: list = field(default_factory=list)
    unreferenced_symbols: list = field(default_factory=list)
    parse_error: str = ""
    score: float = 0.0
    issues: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# PASSE 1 — par fichier
# ═══════════════════════════════════════════════════════════════════════════════

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|TBD)\b")


def _sloc(text: str, comment_prefix: str = "#") -> int:
    """Lignes significatives : ni vides, ni commentaires de ligne."""
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith(comment_prefix):
            n += 1
    return n


def _complexity(node: ast.AST) -> int:
    """McCabe approximé : 1 + points de décision."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                              ast.With, ast.AsyncWith, ast.Assert)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.IfExp):
            score += 1
        elif isinstance(child, (ast.comprehension,)):
            score += 1 + len(child.ifs)
        elif isinstance(child, ast.Match):
            score += len(child.cases)
    return score


def _func_sloc(node: ast.AST, lines: list) -> int:
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    return _sloc("\n".join(lines[start:end]))


def _module_imports(tree: ast.AST) -> dict:
    """Nom lié → module d'origine, pour les imports de premier niveau uniquement.

    `from __future__ import ...` est exclu : ce n'est pas un import de symbole mais une
    directive de compilation. Le compter donnerait « annotations inutilisé » sur presque
    tous les fichiers du dépôt — un faux positif de masse.
    """
    out = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module == "__future__":
                continue  # relatif = souvent une ré-exportation ; __future__ = directive
            for alias in node.names:
                if alias.name == "*":
                    continue
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}" if node.module else alias.name
    return out


def _imported_symbol_names(tree: ast.AST) -> set:
    """Tous les noms qu'un fichier importe — y compris relatifs.

    Indispensable au comptage de références croisées : `from a import ForgeDB` est un
    nœud `alias`, pas un `Name`. Sans cela, tout symbole utilisé uniquement via import
    depuis un autre module paraîtrait « jamais référencé ».
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.name)
                    if alias.asname:
                        names.add(alias.asname)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.update(alias.name.split("."))
    return names


def _used_names(tree: ast.AST) -> set:
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    return used


def _string_mentions(text: str, names: set) -> set:
    """Noms cités dans des chaînes (`__all__`, getattr, imports dynamiques)."""
    found = set()
    for name in names:
        if re.search(rf"[\"']{re.escape(name)}[\"']", text):
            found.add(name)
    return found


def scan_python(path: Path, text: str, debt: FileDebt) -> dict | None:
    """Remplit `debt` et retourne l'index de symboles du fichier (pour la passe 2)."""
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        debt.parse_error = f"{type(exc).__name__}: {exc}"
        debt.issues.append(f"ne parse pas ({debt.parse_error})")
        return None

    defined: dict = {}
    bodies: list = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            debt.functions += 1
            fs = _func_sloc(node, lines)
            cx = _complexity(node)
            debt.max_func_sloc = max(debt.max_func_sloc, fs)
            debt.max_complexity = max(debt.max_complexity, cx)
            if fs > T_FUNC_SLOC:
                debt.long_functions.append({"name": node.name, "sloc": fs, "line": node.lineno})
            if cx > T_COMPLEXITY:
                debt.complex_functions.append({"name": node.name, "complexity": cx, "line": node.lineno})
            if fs >= T_DUP_SLOC:
                body_src = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                bodies.append((hashlib.sha1(body_src.encode()).hexdigest()[:16], node.name, node.lineno, fs))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                debt.bare_excepts += 1
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                debt.silent_excepts += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            debt.prints += 1

    for node in ast.iter_child_nodes(tree):
        name = getattr(node, "name", None)
        if name and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Un symbole décoré est très souvent appelé par un framework (@app.route,
            # @click.command, @pytest.fixture, @tool…) : invisible au graphe d'appels.
            if getattr(node, "decorator_list", None):
                continue
            defined[name] = node.lineno

    # imports jamais utilisés — hors __init__.py (ré-export) et hors mentions en chaîne
    if path.name != "__init__.py":
        imports = _module_imports(tree)
        used = _used_names(tree)
        candidates = {n for n in imports if n not in used and not n.startswith("_")}
        debt.unused_imports = sorted(candidates - _string_mentions(text, candidates))

    debt.todos = len(_TODO_RE.findall(text))
    used = _used_names(tree) | _imported_symbol_names(tree) | _string_mentions(text, set(defined))
    return {"defined": defined, "used": used, "bodies": bodies}


def scan_generic(text: str, debt: FileDebt, comment_prefix: str = "//") -> None:
    """Langages non-Python : métriques de ligne uniquement, sans faux-semblant d'AST."""
    debt.todos = len(_TODO_RE.findall(text))
    debt.issues.append(f"analyse superficielle ({debt.language} — pas d'AST)")


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def score_file(d: FileDebt) -> float:
    s = 0.0
    if d.parse_error:
        s += WEIGHTS["syntax_error"] * 10
    if d.sloc > T_FILE_SLOC:
        s += WEIGHTS["size"] * (d.sloc - T_FILE_SLOC) / 100.0
    for f in d.long_functions:
        s += WEIGHTS["func_len"] * (f["sloc"] - T_FUNC_SLOC) / 20.0
    for f in d.complex_functions:
        s += WEIGHTS["complexity"] * (f["complexity"] - T_COMPLEXITY) / 5.0
    s += WEIGHTS["unused_import"] * len(d.unused_imports)
    s += WEIGHTS["bare_except"] * d.bare_excepts
    s += WEIGHTS["silent_except"] * d.silent_excepts
    s += WEIGHTS["todo"] * d.todos
    s += WEIGHTS["duplication"] * len(d.duplicated_blocks)
    s += WEIGHTS["unreferenced"] * len(d.unreferenced_symbols)
    s += WEIGHTS["print"] * d.prints
    return round(s, 2)


def describe_issues(d: FileDebt) -> list:
    out = list(d.issues)
    if d.sloc > T_FILE_SLOC:
        out.append(f"fichier trop gros: {d.sloc} SLOC (seuil {T_FILE_SLOC})")
    if d.long_functions:
        w = max(d.long_functions, key=lambda f: f["sloc"])
        out.append(f"{len(d.long_functions)} fonction(s) > {T_FUNC_SLOC} SLOC (pire: {w['name']} @{w['line']}, {w['sloc']})")
    if d.complex_functions:
        w = max(d.complex_functions, key=lambda f: f["complexity"])
        out.append(f"{len(d.complex_functions)} fonction(s) complexe(s) (pire: {w['name']} @{w['line']}, McCabe {w['complexity']})")
    if d.unused_imports:
        out.append(f"{len(d.unused_imports)} import(s) inutilisé(s): {', '.join(d.unused_imports[:6])}")
    if d.silent_excepts:
        out.append(f"{d.silent_excepts} `except: pass` — échec silencieux")
    if d.bare_excepts:
        out.append(f"{d.bare_excepts} `except:` nu")
    if d.duplicated_blocks:
        out.append(f"{len(d.duplicated_blocks)} corps de fonction dupliqué(s) ailleurs")
    if d.unreferenced_symbols:
        out.append(f"{len(d.unreferenced_symbols)} symbole(s) public(s) sans référence trouvée: {', '.join(d.unreferenced_symbols[:6])}")
    if d.todos:
        out.append(f"{d.todos} marqueur(s) TODO/FIXME/HACK")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════════

def _zone_of(rel: Path) -> dict | None:
    """Première zone dont un `path` préfixe le fichier, en respectant `exclude_sub`."""
    parts = rel.as_posix()
    best = None
    best_len = -1
    for zone in ZONES:
        for p in zone["paths"]:
            prefix = "" if p == "." else p
            if prefix and not parts.startswith(prefix + "/"):
                continue
            if not prefix and "/" in parts:
                continue  # "." = fichiers de la racine seulement
            sub = parts[len(prefix) + 1:] if prefix else parts
            if any(sub.startswith(x + "/") or sub == x for x in zone.get("exclude_sub", [])):
                continue
            if len(prefix) > best_len:
                best, best_len = zone, len(prefix)
    return best


def collect_files(include_vendored: bool = False) -> list:
    """Parcours scopé. Retourne [(Path absolu, Path relatif, zone)]."""
    out = []
    for dp, dn, fn in os.walk(FORGE_ROOT):
        dn[:] = [d for d in dn if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if ext not in CODE_EXT or EXCLUDE_FILE_RE.search(f):
                continue
            abs_p = Path(dp) / f
            rel = abs_p.relative_to(FORGE_ROOT)
            zone = _zone_of(rel)
            if zone is None:
                continue
            if zone["vendored"] and not include_vendored:
                continue
            out.append((abs_p, rel, zone))
    return out


def scan(include_vendored: bool = False) -> dict:
    """Scan complet, deux passes. Aucun appel LLM."""
    started = time.time()
    files = collect_files(include_vendored)
    debts: list = []
    index: dict = {}
    body_map: dict = defaultdict(list)

    for abs_p, rel, zone in files:
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("lecture KO %s: %s", rel, exc)
            continue
        lang = CODE_EXT[abs_p.suffix.lower()]
        d = FileDebt(path=rel.as_posix(), zone=zone["name"], language=lang,
                     vendored=zone["vendored"], bytes=len(text.encode("utf-8", "ignore")))
        d.sloc = _sloc(text, "#" if lang in {"python", "shell", "powershell"} else "//")
        if lang == "python":
            info = scan_python(abs_p, text, d)
            if info:
                index[d.path] = info
                for h, name, line, fs in info["bodies"]:
                    body_map[h].append((d.path, name, line, fs))
        else:
            scan_generic(text, d)
        debts.append(d)

    by_path = {d.path: d for d in debts}

    # ── PASSE 2a — duplication exacte de corps de fonctions ───────────────────
    dup_groups = 0
    for h, occurrences in body_map.items():
        if len(occurrences) < 2:
            continue
        dup_groups += 1
        for path, name, line, fs in occurrences:
            others = [f"{p}:{n}" for p, n, _l, _s in occurrences if p != path or n != name]
            by_path[path].duplicated_blocks.append({"function": name, "line": line, "sloc": fs,
                                                    "also_in": others[:4]})

    # ── PASSE 2b — symboles publics jamais référencés ailleurs ────────────────
    # Heuristique assumée : un symbole peut être appelé dynamiquement, via MCP, en
    # entrée CLI ou par un test hors scope. On dit « sans référence trouvée », pas « mort ».
    ENTRY = {"main", "run", "handler", "lambda_handler", "app", "cli", "setup", "test"}
    all_used = Counter()
    for info in index.values():
        for name in info["used"]:
            all_used[name] += 1
    for path, info in index.items():
        d = by_path[path]
        if d.vendored or path.endswith("__init__.py") or "test" in Path(path).name.lower():
            continue
        for name in info["defined"]:
            if name.startswith("_") or name in ENTRY or name.lower().startswith("test"):
                continue
            # `all_used` compte les RÉFÉRENCES (Name load, import, mention en chaîne).
            # Une définition n'y contribue pas : 0 = aucune référence trouvée nulle part.
            if all_used[name] == 0:
                d.unreferenced_symbols.append(name)

    for d in debts:
        d.score = score_file(d)
        d.issues = describe_issues(d)

    debts.sort(key=lambda x: -x.score)
    elapsed = time.time() - started

    zone_stats: dict = defaultdict(lambda: {"files": 0, "sloc": 0, "score": 0.0, "vendored": False})
    for d in debts:
        z = zone_stats[d.zone]
        z["files"] += 1
        z["sloc"] += d.sloc
        z["score"] = round(z["score"] + d.score, 2)
        z["vendored"] = d.vendored

    return {
        "generated_at": time.time(),
        "root": str(FORGE_ROOT),
        "include_vendored": include_vendored,
        "elapsed_s": round(elapsed, 2),
        "totals": {
            "files": len(debts),
            "sloc": sum(d.sloc for d in debts),
            "score": round(sum(d.score for d in debts), 2),
            "parse_errors": sum(1 for d in debts if d.parse_error),
            "duplicate_groups": dup_groups,
            "unreferenced_symbols": sum(len(d.unreferenced_symbols) for d in debts),
            "silent_excepts": sum(d.silent_excepts for d in debts),
            "bare_excepts": sum(d.bare_excepts for d in debts),
            "todos": sum(d.todos for d in debts),
        },
        "thresholds": {"file_sloc": T_FILE_SLOC, "func_sloc": T_FUNC_SLOC,
                       "complexity": T_COMPLEXITY, "dup_sloc": T_DUP_SLOC},
        "weights": WEIGHTS,
        "zones": {k: v for k, v in sorted(zone_stats.items(), key=lambda kv: -kv[1]["score"])},
        "files": [asdict(d) for d in debts],
    }


def plan_zones(report: dict, max_chunks: int = 12, top_per_chunk: int = 12) -> list:
    """Découpe le rapport en chunks équilibrés — l'unité de travail d'un examen parallèle.

    Équilibrage par score de dette cumulé, pas par nombre de fichiers : une zone de
    5 fichiers pourris coûte plus cher à examiner que 50 fichiers propres.
    """
    by_zone: dict = defaultdict(list)
    for f in report["files"]:
        if f["score"] > 0:
            by_zone[f["zone"]].append(f)

    def as_target(f: dict) -> dict:
        return {"path": f["path"], "score": f["score"], "sloc": f["sloc"], "issues": f["issues"]}

    def make_chunk(name: str, files: list, sub_path: str = "") -> dict:
        files = sorted(files, key=lambda f: -f["score"])
        return {
            "zone": name,
            "sub_path": sub_path,
            "vendored": files[0]["vendored"],
            "files_total": len(files),
            "sloc_total": sum(f["sloc"] for f in files),
            "score_total": round(sum(f["score"] for f in files), 2),
            "score_covered": round(sum(f["score"] for f in files[:top_per_chunk]), 2),
            "targets": [as_target(f) for f in files[:top_per_chunk]],
        }

    # Budget global : on couvre les `max_chunks * top_per_chunk` pires fichiers.
    # Une zone plate (98 fichiers dans un même dossier) ne se scinde pas par dossier —
    # on tranche donc par rang de score, ce qui garantit que chaque chunk est homogène
    # en gravité et qu'aucun fichier retenu n'est perdu.
    ranked = sorted((f for files in by_zone.values() for f in files), key=lambda f: -f["score"])
    total_score = sum(f["score"] for f in ranked) or 1.0
    budget = max_chunks * top_per_chunk
    selected, remainder = ranked[:budget], ranked[budget:]

    grouped: dict = defaultdict(list)
    for f in selected:
        grouped[f["zone"]].append(f)

    out: list = []
    for zone, files in sorted(grouped.items(), key=lambda kv: -sum(f["score"] for f in kv[1])):
        files.sort(key=lambda f: -f["score"])
        slices = [files[i:i + top_per_chunk] for i in range(0, len(files), top_per_chunk)]
        for i, sl in enumerate(slices, start=1):
            name = zone if len(slices) == 1 else f"{zone}#{i}"
            folders = sorted({str(Path(f["path"]).parent).replace("\\", "/") for f in sl})
            out.append(make_chunk(name, sl, sub_path=folders[0] if len(folders) == 1 else ""))

    out.sort(key=lambda c: -c["score_total"])
    dropped = out[max_chunks:]
    out = out[:max_chunks]

    covered = sum(c["score_total"] for c in out)
    report["coverage"] = {
        "chunks": len(out),
        "files_covered": sum(c["files_total"] for c in out),
        "files_with_debt": len(ranked),
        "score_covered": round(covered, 2),
        "score_total": round(total_score, 2),
        "score_covered_pct": round(100 * covered / total_score, 1),
        # Rien n'est tronqué en silence : ce qui sort du budget est nommé.
        "not_covered": {
            "files": len(remainder) + sum(c["files_total"] for c in dropped),
            "score": round(sum(f["score"] for f in remainder)
                           + sum(c["score_total"] for c in dropped), 2),
            "dropped_chunks": [c["zone"] for c in dropped],
        },
    }
    if report["coverage"]["not_covered"]["files"]:
        logger.warning("hors budget: %(files)d fichier(s), score %(score).0f",
                       report["coverage"]["not_covered"])
    return out


def _main() -> int:
    ap = argparse.ArgumentParser(description="Scan de dette technique scopé")
    ap.add_argument("--all", action="store_true", help="inclut le code vendored")
    ap.add_argument("--zones", type=int, default=12, help="nombre max de chunks")
    ap.add_argument("--top", type=int, default=12, help="fichiers par chunk")
    ap.add_argument("--out", default=str(OUT_PATH()))
    args = ap.parse_args()

    report = scan(include_vendored=args.all)
    report["chunks"] = plan_zones(report, args.zones, args.top)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    t = report["totals"]
    print(f"SCAN {t['files']:,} fichiers / {t['sloc']:,} SLOC en {report['elapsed_s']}s "
          f"(vendored={'oui' if args.all else 'non'})")
    print(f"Score de dette total: {t['score']:,.0f}")
    print(f"  parse errors={t['parse_errors']}  dup_groups={t['duplicate_groups']}  "
          f"except:pass={t['silent_excepts']}  except nu={t['bare_excepts']}  "
          f"non référencés={t['unreferenced_symbols']}  TODO={t['todos']}")
    print(f"\n{'zone':<22}{'fichiers':>10}{'SLOC':>10}{'score':>12}")
    for name, z in report["zones"].items():
        print(f"{name:<22}{z['files']:>10,}{z['sloc']:>10,}{z['score']:>12,.0f}")
    print(f"\nTOP 12 fichiers:")
    for f in report["files"][:12]:
        print(f"  {f['score']:>7.1f}  {f['path']}")
        for issue in f["issues"][:2]:
            print(f"           · {issue}")
    cov = report["coverage"]
    print(f"\n{len(report['chunks'])} chunks -> {out}")
    print(f"couverture: {cov['files_covered']}/{cov['files_with_debt']} fichiers, "
          f"{cov['score_covered']:,.0f}/{cov['score_total']:,.0f} de score ({cov['score_covered_pct']}%)")
    if cov["not_covered"]["files"]:
        print(f"NON COUVERT: {cov['not_covered']['files']} fichier(s), score {cov['not_covered']['score']:,.0f}")
    for c in report["chunks"]:
        print(f"  {c['zone']:<24} score={c['score_total']:>8,.0f}  fichiers={c['files_total']:>4}  "
              f"{c['sub_path'] or '(multi-dossiers)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
