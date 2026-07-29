"""forge_swarm.py — swarm d'agents natif MiMo (le travail sort de la session Claude).

POURQUOI
--------
Un swarm via des sous-agents Claude Opus coûte ~120K tokens CHACUN : chaque agent
charge un contexte lourd (system prompt, outils, MCP, lecture de fichiers) dans la
session facturée. C'est l'inverse de la doctrine Forge (RÈGLE ANTI-DÉRIVE : Claude
raisonne/valide, le gros du travail passe par le backend interne).

Ici, chaque « agent » = un `mimo_call` (Xiaomi MiMo 2.5-pro, backend interne facturé
au bloc round-up, hors session Claude). L'orchestration — quels fichiers, quel
découpage, quelle agrégation — est déterministe et coûte 0 token LLM. Claude ne fait
que lancer le script et lire la synthèse finale.

RÉCURSION (« sub-agents qui coûtent rien »)
-------------------------------------------
Un fichier trop gros pour un seul appel est décomposé en sous-unités (fonctions/classes
de premier niveau) ; chaque sous-unité est un `mimo_call` distinct, puis on fusionne.
Un agent MiMo engendre donc ses propres sous-agents MiMo — tous hors session Claude.

COÛT
----
MiMo facture les tokens ARRONDIS au bloc (1000). Le coût d'un run = somme des blocs
facturés, reportée telle quelle (`billed_tokens`). Aucun token n'entre dans le contexte
Claude : seul le JSON de synthèse est lu.

CLI :
    python 00_CORE/forge_agents/forge_swarm.py --chunks 05_STATE/tech_debt.json
    python 00_CORE/forge_agents/forge_swarm.py --files a.py b.py --workers 6
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("ForgeSwarm")

FORGE_ROOT = Path(__file__).resolve().parents[2]
# lancé en script (`python .../forge_swarm.py`) → le package forge_agents doit être trouvable
_CORE = str(FORGE_ROOT / "00_CORE")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def OUT_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("swarm_audit.json")


# MiMo est un modèle de raisonnement : garder les unités sous ce plafond de caractères
# pour laisser de la place au reasoning + à la réponse sans exploser le ceiling.
MAX_UNIT_CHARS = 14_000
MAX_FILE_CHARS = 44_000   # au-delà : décomposition récursive par symbole


AUDIT_SYSTEM = (
    "Tu es un ingénieur senior qui audite du code Python de production. Tu réponds "
    "UNIQUEMENT en JSON valide, sans texte autour, sans bloc markdown. Tu ne signales "
    "que des défauts OBSERVABLES dans le code fourni : bug, échec silencieux masquant une "
    "vraie erreur, code mort avéré, duplication qui va diverger, risque de config (chemin/"
    "port/clé en dur), risque de correction. Tu NE signales PAS : style, type hints, "
    "docstrings, longueur seule, 'extraire en sous-fonctions'. Si le fichier est sain, "
    "renvoie une liste vide. Mentir sur un défaut est une faute grave."
)

AUDIT_SCHEMA_HINT = (
    '{"findings":[{"line":<int>,"category":"bug|silent-failure|dead-code|duplication|'
    'config-risk|security|correctness-risk","severity":"CRITICAL|HIGH|MEDIUM|LOW",'
    '"title":"<court>","evidence":"<citation littérale du code>","fix":"<action concrète>",'
    '"effort":"S|M|L"}]}'
)


@dataclass
class Finding:
    file: str = ""
    unit: str = ""
    line: int = 0
    category: str = ""
    severity: str = "LOW"
    title: str = ""
    evidence: str = ""
    fix: str = ""
    effort: str = "M"
    grounding: str = "unverifiable"   # grounded | hallucinated | unverifiable


@dataclass
class FileAudit:
    file: str = ""
    ok: bool = True
    error: str = ""
    units: int = 1
    findings: list = field(default_factory=list)
    billed_tokens: int = 0
    #: Tokens RÉELS (in+out non arrondis). Gardé à côté du facturé : l'écart entre les
    #: deux EST le coût du round-up au bloc de 1000, et sans lui le gain d'un batching
    #: futur ne serait pas démontrable — on ne saurait pas ce qu'on payait avant (S-05).
    real_tokens: int = 0
    calls: int = 0
    latency_ms: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# DÉCOUPAGE RÉCURSIF — un fichier trop gros → sous-unités par symbole
# ═══════════════════════════════════════════════════════════════════════════════

def split_units(path: Path, text: str) -> list[tuple[str, str, int]]:
    """Retourne [(nom_unité, source, ligne_base)]. Un seul élément si le fichier tient.

    PACKING : on regroupe des symboles top-level CONTIGUS jusqu'à ~MAX_UNIT_CHARS au lieu
    d'émettre une unité par symbole. Un fichier FastAPI de 100 Ko passe ainsi de 75 unités
    minuscules (1 appel MiMo chacune, sans contexte) à ~8 unités riches — plus rapide, plus
    de contexte par appel, bien moins d'appels. Un symbole seul trop gros est re-tranché.
    """
    if len(text) <= MAX_FILE_CHARS:
        return [(path.name, text, 1)]

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _slice_by_size(path.name, text)

    lines = text.splitlines(keepends=True)
    symbols = [n for n in ast.iter_child_nodes(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    if not symbols:
        return _slice_by_size(path.name, text)

    units: list[tuple[str, str, int]] = []
    i, n = 0, len(symbols)
    while i < n:
        # 1re unité : depuis le début du fichier (imports/constantes inclus). Ensuite :
        # depuis le début du symbole courant.
        grp_start = 0 if i == 0 else symbols[i].lineno - 1
        grp_end = getattr(symbols[i], "end_lineno", grp_start + 1)
        j = i + 1
        while j < n:
            nxt_end = getattr(symbols[j], "end_lineno", grp_end)
            if sum(len(x) for x in lines[grp_start:nxt_end]) > MAX_UNIT_CHARS:
                break
            grp_end, j = nxt_end, j + 1
        src = "".join(lines[grp_start:grp_end])
        label = f"{path.name}#{grp_start + 1}"
        if len(src) > MAX_UNIT_CHARS:          # un seul symbole dépasse le plafond
            units.extend(_slice_by_size(label, src, base=grp_start + 1))
        else:
            units.append((label, src, grp_start + 1))
        i = j
    return units


def _slice_by_size(name: str, text: str, base: int = 1) -> list[tuple[str, str, int]]:
    lines = text.splitlines(keepends=True)
    out, buf, buf_start, size = [], [], base, 0
    for i, ln in enumerate(lines):
        buf.append(ln)
        size += len(ln)
        if size >= MAX_UNIT_CHARS:
            out.append((f"{name}#{buf_start}", "".join(buf), buf_start))
            buf, buf_start, size = [], base + i + 1, 0
    if buf:
        out.append((f"{name}#{buf_start}", "".join(buf), buf_start))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# UN AGENT = UN mimo_call
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> Optional[dict]:
    """MiMo peut renvoyer du reasoning + fences. On isole le 1er objet JSON valide."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    # 1er { … } équilibré
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def audit_unit(unit_name: str, source: str, line_base: int, mimo_call,
               response_text: str | None = None) -> tuple[list, dict]:
    """Audite une unité via UN appel MiMo. Retourne (findings, métriques).

    Quand ``response_text`` est fourni (appel groupé par MimoBatcher dans
    ``run_swarm``), l'appel MiMo est sauté — on pars directement la réponse.
    Les métriques retournées sont à zéro (le coût est porté par le batch).
    """
    prompt = (
        f"Audite ce code. Renvoie STRICTEMENT ce JSON (rien d'autre) :\n{AUDIT_SCHEMA_HINT}\n\n"
        f"Les numéros de ligne sont RELATIFS au début de l'extrait (1 = 1re ligne ci-dessous).\n\n"
        f"--- {unit_name} ---\n{source[:MAX_UNIT_CHARS]}"
    )
    if response_text is not None:
        # Réponse pré-calculée par le batcher — pas d'appel réseau.
        text = response_text
        m: dict = {"in": 0, "out": 0, "billed_tokens": 0, "latency_ms": 0, "calls": 0}
    else:
        # mimo-v2.5-pro est un modèle de RAISONNEMENT : le reasoning_content consomme le
        # budget AVANT d'écrire la réponse. Un budget trop court (<~5K) affame `content` à ''
        # tout en facturant le bloc. 6000 laisse la place au raisonnement + au JSON final.
        text, m = mimo_call(prompt, system=AUDIT_SYSTEM, max_tokens=6000, timeout=180)
    data = _extract_json(text)
    findings = []
    if data and isinstance(data.get("findings"), list):
        for f in data["findings"]:
            if not isinstance(f, dict):
                continue
            try:
                rel_line = int(f.get("line", 0) or 0)
            except (TypeError, ValueError):
                rel_line = 0
            findings.append(Finding(
                unit=unit_name,
                line=(line_base - 1 + rel_line) if rel_line else line_base,
                category=str(f.get("category", ""))[:40],
                severity=str(f.get("severity", "LOW")).upper()[:8],
                title=str(f.get("title", ""))[:200],
                evidence=str(f.get("evidence", ""))[:400],
                fix=str(f.get("fix", ""))[:400],
                effort=str(f.get("effort", "M")).upper()[:1] or "M",
            ))
    return findings, m


def _ground_finding(evidence: str, file_text: str, file_lines: list) -> tuple[str, int]:
    """Vérifie que le code cité en preuve EXISTE dans le fichier — garde-fou anti-hallucination.

    MiMo invente parfois la citation ET le numéro de ligne (cas réel observé : une ligne
    de dict littéral rapportée comme un appel de fonction fautif). On compare la preuve,
    espaces retirés, au fichier espaces retirés :
      - grounded     : un fragment de code cité existe → on RELOCALISE la vraie ligne
      - hallucinated : la preuve ressemble à du code mais est introuvable → à mettre en quarantaine
      - unverifiable : la preuve est de la prose (pas de code citable) → gardée mais non prouvée
    """
    packed_file = re.sub(r"\s+", "", file_text)
    had_code_candidate = False
    for cand in re.split(r"[\n;]", evidence):
        cand = cand.strip()
        core = re.sub(r"\s+", "", cand)
        if len(core) < 10 or not re.search(r"[(){}\[\]=.:]", cand):
            continue  # trop court ou pas assez « code » pour être une citation vérifiable
        had_code_candidate = True
        if core in packed_file:
            # relocalise : 1re ligne dont la version compacte contient le fragment
            for i, ln in enumerate(file_lines, 1):
                if core[:24] in re.sub(r"\s+", "", ln):
                    return "grounded", i
            return "grounded", 0
    return ("hallucinated" if had_code_candidate else "unverifiable"), 0


_ARTIFACT_TRUNCATION = re.compile(
    r"tronqu\w*|truncat\w*|incomplet\w*|incomplete|cut ?off|coup[ée]\w*|jamais de retour|"
    r"pas de return|manque la fin|fin manquante|"
    # « not completly/completely/fully defined|implemented » — fautes de frappe incluses
    r"not\s+(?:complet\w*|fully)\s+(?:defined|implemented)|"
    r"(?:fonction|method|m[ée]thode|function)\s+\w+\s+(?:non\s+)?(?:termin\w*|inachev\w*)", re.I)
_ARTIFACT_UNDEFINED = re.compile(
    r"not imported|non import\w*|undefined|not defined|non d[ée]fini\w*|manque l'import|"
    r"missing import|import manquant|jamais import\w*", re.I)


def _bound_names(text: str) -> set:
    """Tout nom lié au niveau du FICHIER : imports, defs, classes, assignations."""
    names: set = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
            names.add(node.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _refute_context_artifact(finding: Finding, parses_ok: bool, bound: set) -> str:
    """Réfute les conclusions fausses causées par le DÉCOUPAGE, pas par le code.

    MiMo n'analyse qu'une unité : il voit un fragment coupé et conclut « tronqué », ou un
    usage dont l'import vit dans une autre unité et conclut « non importé ». Le grounding
    ne l'attrape pas (le code cité existe vraiment) — seule une vérification à l'échelle du
    FICHIER le peut. Retourne la raison de réfutation, ou "" si le finding tient.
    """
    blob = f"{finding.title} {finding.evidence}"
    if parses_ok and _ARTIFACT_TRUNCATION.search(blob):
        return "artefact de découpage : le fichier parse entièrement, rien n'est tronqué"
    if _ARTIFACT_UNDEFINED.search(blob):
        for name in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", blob)):
            if name in bound:
                return f"artefact de découpage : « {name} » est bien lié/importé dans le fichier"
    return ""


def audit_file(rel_path: str, mimo_call) -> FileAudit:
    """Audite un fichier entier — 1 appel, ou N appels récursifs si trop gros."""
    audit = FileAudit(file=rel_path)
    abs_p = FORGE_ROOT / rel_path
    if not abs_p.exists():
        audit.ok = False
        audit.error = "fichier absent"
        return audit
    try:
        text = abs_p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        audit.ok = False
        audit.error = f"lecture: {exc}"
        return audit

    file_lines = text.splitlines()
    units = split_units(abs_p, text)
    audit.units = len(units)
    t0 = time.time()
    for name, src, base in units:
        try:
            findings, m = audit_unit(name, src, base, mimo_call)
        except Exception as exc:                       # un appel MiMo peut échouer
            audit.error = (audit.error + f" | {name}: {exc}").strip(" |")
            continue
        for f in findings:
            f.file = rel_path
            # grounding déterministe : la preuve doit exister dans le fichier réel
            status, true_line = _ground_finding(f.evidence, text, file_lines)
            f.grounding = status
            if true_line:
                f.line = true_line
        audit.findings.extend(findings)
        audit.billed_tokens += m.get("billed_tokens", 0)
        audit.real_tokens += m.get("in", 0) + m.get("out", 0)
        audit.calls += m.get("calls", 1)
    audit.latency_ms = int((time.time() - t0) * 1000)
    audit.ok = audit.error == "" or bool(audit.findings)
    return audit


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION — déterministe, 0 token Claude
# ═══════════════════════════════════════════════════════════════════════════════

def run_swarm(files: list[str], workers: int = 6, progress: bool = True) -> dict:
    """Parallélise à l'UNITÉ (pas au fichier) : un gros fichier découpé en N unités ne
    sérialise plus la fin du run — toutes ses unités partent dans le pool avec celles des
    autres fichiers, donc les workers restent occupés jusqu'au dernier appel.
    """
    from forge_agents.forge_mimo import mimo_call, is_available, MimoBatcher, token_block, _est_tokens
    if not is_available():
        raise RuntimeError("MIMO_API_KEY absente — configure .env avant de lancer le swarm")

    files = list(dict.fromkeys(files))  # dédup en préservant l'ordre
    started = time.time()

    # ── Pré-passe déterministe (0 token) : lire + découper chaque fichier en unités ──
    audits: dict[str, FileAudit] = {}
    file_text: dict[str, tuple[str, list]] = {}
    work: list[tuple[str, str, str, int]] = []   # (fichier, nom_unité, source, ligne_base)
    for rel in files:
        a = FileAudit(file=rel)
        abs_p = FORGE_ROOT / rel
        if not abs_p.exists():
            a.ok, a.error = False, "fichier absent"
            audits[rel] = a
            continue
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            a.ok, a.error = False, f"lecture: {exc}"
            audits[rel] = a
            continue
        units = split_units(abs_p, text)
        a.units = len(units)
        audits[rel] = a
        file_text[rel] = (text, text.splitlines())
        for name, src, base in units:
            work.append((rel, name, src, base))

    total = len(work)

    # Pré-calcul par fichier pour la réfutation d'artefacts (0 token)
    file_ctx: dict[str, tuple[bool, set]] = {}
    for rel, (text, _l) in file_text.items():
        try:
            ast.parse(text)
            parses = True
        except SyntaxError:
            parses = False
        file_ctx[rel] = (parses, _bound_names(text))

    # ── S-07 : vérifier le budget AVANT de dépenser ─────────────────────────
    # Estimation déterministe (0 token) : taille réelle des prompts + hypothèse
    # sur les réponses. `check()` lève BudgetExceeded si le plafond est atteint.
    from forge_agents.mimo_budget import check as budget_check
    est_in = sum(_est_tokens(
        f"Audite ce code. Renvoie STRICTEMENT ce JSON (rien d'autre) :\n{AUDIT_SCHEMA_HINT}\n\n"
        f"Les numéros de ligne sont RELATIFS au début de l'extrait (1 = 1re ligne ci-dessous).\n\n"
        f"--- {name} ---\n{src[:MAX_UNIT_CHARS]}" + AUDIT_SYSTEM
    ) for _, name, src, _ in work)
    est_out = len(work) * 600   # hypothèse : 600 tokens de réponse par unité
    budget_check(est_in + est_out)

    # ── S-06 : regrouper les prompts via MimoBatcher (1 round-up par batch) ──
    # Au lieu d'appeler mimo_call une fois par unité (1 round-up 1K × N), on
    # coalesce les prompts en paquets et on paie le round-up une fois par paquet.
    # Le batcher auto-flushe quand l'input accumulé atteint max_block_tokens
    # (32 blocs = 32K tokens ≈ 9 prompts de code) OU max_items (10).
    batcher = MimoBatcher(
        system=AUDIT_SYSTEM,
        max_block_tokens=token_block() * 32,
        max_items=10,
    )
    unit_meta: list[tuple[str, str, str, int]] = []   # aligné sur batch_responses
    prompts_failed: list[tuple[str, str, str, int, str]] = []  # prompts qui n'ont pas abouti

    for item in work:
        rel, name, src, base = item
        prompt = (
            f"Audite ce code. Renvoie STRICTEMENT ce JSON (rien d'autre) :\n{AUDIT_SCHEMA_HINT}\n\n"
            f"Les numéros de ligne sont RELATIFS au début de l'extrait (1 = 1re ligne ci-dessous).\n\n"
            f"--- {name} ---\n{src[:MAX_UNIT_CHARS]}"
        )
        unit_meta.append(item)
        auto_results = batcher.add(prompt)
        if auto_results:
            # Auto-flush : les résultats correspondent aux N premiers items en attente
            for i, resp_text in enumerate(auto_results):
                meta = unit_meta[i]
                if not resp_text.strip():
                    prompts_failed.append((*meta, "réponse vide"))
            unit_meta = unit_meta[len(auto_results):]

    # Flush final
    remaining = batcher.flush(max_tokens_per_item=6000)
    batch_responses = []
    for i, resp_text in enumerate(remaining):
        meta = unit_meta[i] if i < len(unit_meta) else ("?", "?", "?", 0)
        if resp_text.strip():
            batch_responses.append(resp_text)
        else:
            prompts_failed.append((*meta, "réponse vide"))
    # Aligner unit_meta sur batch_responses (seuls les non-échoués)
    unit_meta = unit_meta[:len(remaining)]
    unit_meta = [m for i, m in enumerate(unit_meta) if remaining[i].strip()]
    batch_stats = batcher.savings()

    if progress:
        logger.info("BATCHER: %d appels pour %d unités (naïf: %d appels) — %d tokens économisés",
                     batch_stats["batches"], batch_stats["items"],
                     batch_stats["items"], batch_stats["tokens_saved_vs_naive"])

    # ── Distribuer les réponses batchées et parser (déterministe, 0 token) ──
    done = 0
    for idx, resp_text in enumerate(batch_responses):
        rel, name, src, base = unit_meta[idx]
        try:
            findings, m = audit_unit(name, src, base, mimo_call, response_text=resp_text)
            err = ""
        except Exception as exc:
            findings, m, err = [], {"billed_tokens": 0, "calls": 0}, f"{name}: {exc}"
        done += 1
        if progress:
            logger.info("[%d/%d] %s — %d finding(s)%s",
                        done, total, name, len(findings),
                        f" ERR:{err}" if err else "")
        a = audits[rel]
        text, lines = file_text[rel]
        parses_ok, bound = file_ctx.get(rel, (True, set()))
        for f in findings:
            f.file = rel
            status, true_line = _ground_finding(f.evidence, text, lines)
            f.grounding = status
            if true_line:
                f.line = true_line
            if status != "hallucinated":
                reason = _refute_context_artifact(f, parses_ok, bound)
                if reason:
                    f.grounding = "context-artifact"
                    f.fix = reason
        a.findings.extend(findings)
        a.calls += 1   # 1 unité traitée (le coût réseau est dans batch_stats)
        if err:
            a.error = (a.error + f" | {err}").strip(" |")

    # Prompts échoués (réponse vide)
    for rel, name, src, base, reason in prompts_failed:
        a = audits[rel]
        a.error = (a.error + f" | {name}: {reason}").strip(" |")
        a.calls += 1

    # Attribuer les tokens facturés au batch au prorata des unités par fichier
    total_units = len(batch_responses) + len(prompts_failed)
    if total_units and batch_stats["billed_tokens"]:
        billed_per_unit = batch_stats["billed_tokens"] / total_units
        for a in audits.values():
            a.billed_tokens = int(billed_per_unit * a.units)

    for a in audits.values():
        a.ok = a.error == "" or bool(a.findings)
    audits = list(audits.values())

    raw = [asdict(f) for a in audits for f in a.findings]
    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

    # Garde-fou anti-hallucination : les findings dont la preuve n'existe pas dans le
    # code réel sont écartés en quarantaine, JAMAIS mélangés aux findings retenus.
    hallucinated = [f for f in raw if f["grounding"] == "hallucinated"]
    artifacts = [f for f in raw if f["grounding"] == "context-artifact"]
    kept = [f for f in raw if f["grounding"] not in ("hallucinated", "context-artifact")]
    kept.sort(key=lambda f: (rank.get(f["severity"], 9), f["file"]))
    hallucinated.sort(key=lambda f: (rank.get(f["severity"], 9), f["file"]))

    return {
        "engine": "mimo",
        "generated_at": time.time(),
        "elapsed_s": round(time.time() - started, 1),
        "files_audited": len(audits),
        "files_failed": sum(1 for a in audits if not a.ok),
        "total_findings": len(kept),
        "grounding": {
            "grounded": sum(1 for f in kept if f["grounding"] == "grounded"),
            "unverifiable": sum(1 for f in kept if f["grounding"] == "unverifiable"),
            "hallucinated_quarantined": len(hallucinated),
            "context_artifacts_quarantined": len(artifacts),
        },
        "by_severity": {s: sum(1 for f in kept if f["severity"] == s)
                        for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
        "cost": {**_cost_block(audits), "batcher": batch_stats},
        "findings": kept,
        "quarantine_hallucinated": hallucinated,
        "quarantine_context_artifacts": artifacts,
        "per_file": [
            {"file": a.file, "ok": a.ok, "findings": len(a.findings),
             "units": a.units, "billed_tokens": a.billed_tokens,
             "real_tokens": a.real_tokens, "error": a.error}
            for a in sorted(audits, key=lambda x: -len(x.findings))
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# S-05 — CE QUE COÛTE LE ROUND-UP (mesurer AVANT de corriger)
# ═══════════════════════════════════════════════════════════════════════════════
#
# MiMo facture par bloc de 1000 tokens, arrondi au SUPÉRIEUR, et `run_swarm` fait UN
# appel par unité de code. Une unité qui consomme réellement 1 200 in + 150 out est
# donc facturée 2 000 + 1 000 = 3 000. Le gaspillage n'est pas une intuition : c'est
# `facturé - réel`, et il faut le connaître AVANT de brancher le batcher (S-06), sinon
# « ça va mieux » ne sera jamais démontrable.

def _cost_block(audits: list) -> dict:
    """Bloc `cost` d'un run : facturé, réel, et l'écart que le round-up a coûté."""
    billed = sum(a.billed_tokens for a in audits)
    real = sum(a.real_tokens for a in audits)
    return {
        "mimo_billed_tokens": billed,
        "mimo_real_tokens": real,
        "round_up_overhead_tokens": max(0, billed - real),
        "round_up_overhead_pct": round(100 * (billed - real) / real, 1) if real else 0.0,
        "mimo_calls": sum(a.calls for a in audits),
        "claude_session_tokens": 0,   # tout le travail LLM est hors session
    }


def estimate_round_up(files: list[str], out_tokens_per_unit: int = 600,
                      batch_max_items: int = 20,
                      batch_max_block_tokens: Optional[int] = None) -> dict:
    """Ce que le round-up coûtera sur CE corpus — **sans dépenser un token**.

    Pourquoi une estimation plutôt qu'un run témoin : le run témoin est la mesure de
    référence, mais il exige `MIMO_API_KEY`. Là où la clé manque, on peut quand même
    calculer la partie déterministe — le découpage réel des vrais fichiers
    (`split_units`) et la taille réelle des prompts — et n'avoir à supposer QUE la
    longueur des réponses. Autrement dit : l'entrée est mesurée, la sortie est un
    paramètre assumé (`out_tokens_per_unit`), et le rapport dit lequel est lequel.
    Ne jamais présenter le résultat comme une facture constatée.

    `batched_*` projette le coût si les unités passaient par `MimoBatcher` (S-06). La
    projection **simule le vrai batcher**, auto-flush sur la taille compris
    (`MimoBatcher.add` vide la file dès que l'entrée en attente atteint
    `max_block_tokens`, par défaut 4 blocs). Grouper naïvement par paquets de 20 en
    ignorant cette borne donnerait un gain imaginaire : sur des unités de code, qui
    pèsent chacune plusieurs blocs, le batcher flushe après 1 ou 2 items et le round-up
    reste payé presque autant de fois.
    """
    # Import absolu : ce module tourne aussi en SCRIPT (`python .../forge_swarm.py
    # --estimate`), où il n'a pas de paquet parent. `sys.path` porte déjà `00_CORE`
    # (posé en tête de fichier), donc cette forme marche dans les deux modes.
    from forge_agents.forge_mimo import _est_tokens, round_up_tokens, token_block

    per_unit_in: list[int] = []
    skipped: list[str] = []
    for rel in dict.fromkeys(files):
        abs_p = FORGE_ROOT / rel
        if not abs_p.exists():
            skipped.append(rel)
            continue
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(rel)
            continue
        for name, src, _base in split_units(abs_p, text):
            # Le prompt réellement envoyé par `audit_unit`, reconstruit à l'identique.
            prompt = (
                f"Audite ce code. Renvoie STRICTEMENT ce JSON (rien d'autre) :\n{AUDIT_SCHEMA_HINT}\n\n"
                f"Les numéros de ligne sont RELATIFS au début de l'extrait (1 = 1re ligne ci-dessous).\n\n"
                f"--- {name} ---\n{src[:MAX_UNIT_CHARS]}"
            )
            per_unit_in.append(_est_tokens(prompt + AUDIT_SYSTEM))

    n = len(per_unit_in)
    total_in = sum(per_unit_in)
    total_out = n * max(0, out_tokens_per_unit)
    real = total_in + total_out

    # Aujourd'hui : un appel par unité, donc un round-up par unité, des deux côtés.
    naive = sum(round_up_tokens(i) + round_up_tokens(out_tokens_per_unit) for i in per_unit_in)

    # Avec le batcher : un round-up par PAQUET, les paquets étant formés comme
    # `MimoBatcher.add` les forme réellement — flush sur le nombre d'items OU sur la
    # taille d'entrée accumulée (le second l'emporte largement sur du code).
    max_block_tokens = batch_max_block_tokens or (token_block() * 4)  # défaut MimoBatcher
    groups: list[list[int]] = []
    pending: list[int] = []
    for tok in per_unit_in:
        pending.append(tok)
        if len(pending) >= max(1, batch_max_items) or sum(pending) >= max_block_tokens:
            groups.append(pending)
            pending = []
    if pending:
        groups.append(pending)

    batched = sum(round_up_tokens(sum(g)) + round_up_tokens(len(g) * out_tokens_per_unit)
                  for g in groups)

    return {
        "files": len(list(dict.fromkeys(files))) - len(skipped),
        "files_skipped": skipped,
        "units": n,
        "token_block": token_block(),
        "measured": {"in_tokens": total_in},
        "assumed": {"out_tokens_per_unit": out_tokens_per_unit, "out_tokens": total_out},
        "real_tokens": real,
        "naive_billed_tokens": naive,
        "naive_overhead_tokens": max(0, naive - real),
        "naive_overhead_pct": round(100 * (naive - real) / real, 1) if real else 0.0,
        "batched_billed_tokens": batched,
        "batched_calls": len(groups),
        "batched_items_per_call": round(n / len(groups), 1) if groups else 0,
        "batch_max_block_tokens": max_block_tokens,
        "savings_tokens": max(0, naive - batched),
        "savings_pct": round(100 * (naive - batched) / naive, 1) if naive else 0.0,
        "note": "entrée MESURÉE sur le découpage réel ; sortie ASSUMÉE — pas une facture constatée",
    }


def files_from_chunks(chunks_path: Path) -> list[str]:
    """Extrait la liste de fichiers d'un rapport tech_debt.json (chunks)."""
    data = json.loads(chunks_path.read_text(encoding="utf-8"))
    files: list[str] = []
    for c in data.get("chunks", []):
        for t in c.get("targets", []):
            files.append(t["path"])
    return files


def _main() -> int:
    ap = argparse.ArgumentParser(description="Swarm d'audit natif MiMo (hors session Claude)")
    ap.add_argument("--chunks", default=str(FORGE_ROOT / "05_STATE" / "tech_debt.json"),
                    help="rapport tech_debt.json dont on prend les fichiers")
    ap.add_argument("--files", nargs="*", help="fichiers explicites (ignore --chunks)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="n'auditer que les N premiers")
    ap.add_argument("--out", default=str(OUT_PATH()))
    ap.add_argument("--estimate", action="store_true",
                    help="chiffrer le round-up sur ce corpus SANS appeler MiMo (0 token)")
    ap.add_argument("--out-tokens", type=int, default=600,
                    help="hypothèse de longueur de réponse par unité, pour --estimate")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    files = args.files or files_from_chunks(Path(args.chunks))
    if args.limit:
        files = files[:args.limit]
    if not files:
        print("Aucun fichier à auditer.")
        return 1

    if args.estimate:
        e = estimate_round_up(files, out_tokens_per_unit=args.out_tokens)
        print(f"ROUND-UP — {e['units']} unité(s) sur {e['files']} fichier(s), "
              f"bloc de {e['token_block']}")
        print(f"  réel        : {e['real_tokens']:>12,}  "
              f"(in mesuré {e['measured']['in_tokens']:,} + out assumé {e['assumed']['out_tokens']:,})")
        print(f"  facturé     : {e['naive_billed_tokens']:>12,}  "
              f"(1 appel/unité) -> +{e['naive_overhead_tokens']:,} "
              f"soit +{e['naive_overhead_pct']}% de round-up")
        # Sensibilité au seuil d'auto-flush : c'est LUI qui décide si batcher sert à
        # quelque chose. Sans cette colonne, S-06 se déciderait à l'aveugle.
        print("  si batché, selon le seuil d'auto-flush du batcher :")
        for mult in (4, 16, 64, 256):
            b = estimate_round_up(files, out_tokens_per_unit=args.out_tokens,
                                  batch_max_block_tokens=e["token_block"] * mult)
            tag = " (défaut actuel)" if mult == 4 else ""
            print(f"    {mult:>3} blocs : {b['batched_billed_tokens']:>10,}  "
                  f"({b['batched_calls']} appels, {b['batched_items_per_call']} u/appel) "
                  f"-> {b['savings_pct']:>5}%{tag}")
        print(f"  {e['note']}")
        if e["files_skipped"]:
            print(f"  ignorés ({len(e['files_skipped'])}) : {', '.join(e['files_skipped'][:5])}")
        return 0

    print(f"SWARM MiMo — {len(files)} fichier(s), batcher MimoBatcher (S-06)")
    report = run_swarm(files, workers=args.workers)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    c = report["cost"]
    g = report["grounding"]
    b = c.get("batcher", {})
    print(f"\nTerminé en {report['elapsed_s']}s")
    print(f"Findings retenus: {report['total_findings']} "
          f"(CRIT {report['by_severity']['CRITICAL']} / HIGH {report['by_severity']['HIGH']} / "
          f"MED {report['by_severity']['MEDIUM']} / LOW {report['by_severity']['LOW']})")
    print(f"Grounding: {g['grounded']} groundés / {g['unverifiable']} non vérifiables / "
          f"{g['hallucinated_quarantined']} hallucinés en quarantaine")
    if b:
        print(f"Coût MiMo (batché): {b['billed_tokens']:,} tokens facturés "
              f"({b['batches']} batchs pour {b['items']} unités) — "
              f"économisés vs naïf: {b['tokens_saved_vs_naive']:,}")
    print(f"Coût session Claude: {c['claude_session_tokens']} tokens")
    print(f"Rapport -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
