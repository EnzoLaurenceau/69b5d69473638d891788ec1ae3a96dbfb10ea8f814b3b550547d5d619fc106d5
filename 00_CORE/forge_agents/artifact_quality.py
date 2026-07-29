"""
artifact_quality.py — Score qualité normalisé 0-100 par artefact (ticket E6-02)
==============================================================================
E6-01 a posé la mesure par tâche : durée, tokens, coût, succès/échec — et un
champ `quality` volontairement laissé **vide**, parce qu'inventer une formule
maison à cet endroit aurait rendu ce ticket-ci impossible à faire proprement.
Ce module est ce qui remplit ce champ : un score 0-100 par artefact produit,
comparable d'un type à l'autre, et qui refuse de noter ce qu'il n'a pas mesuré.

QUATRE TYPES, QUATRE JEUX DE SONDES
-----------------------------------
`code` (.py, .js, .ts…) · `asset` (.png, .svg…) · `audio` (.wav, .ogg…) ·
`narrative` (.md, .txt…). Une extension inconnue n'est **pas** rangée d'office
dans le type le plus proche : elle ressort `unknown`, sans score. Deviner le
type, c'est fabriquer la note qui suit.

CE QU'IL N'EST PAS
------------------
**Ce n'est pas un second Harness.** `harness_engine` porte déjà la doctrine
anti-slop et anti-secrets de la Forge ; ses détecteurs sont appelés ici tels
quels (`_check_no_secrets`, `_check_no_ai_slop`, `_check_error_handling`,
`_check_no_print`). Les réécrire aurait produit deux vérités divergentes sur
« ce qu'est un secret en dur ».

**Ce n'est pas un appel LLM.** Toutes les sondes sont déterministes et
gratuites : deux exécutions sur le même fichier rendent le même chiffre, et
noter un livrable ne coûte pas un token. Un juge LLM (`ai_agent_kit.judge`)
reste possible en surcouche pour le narratif ; il n'entre pas dans ce score,
sinon la note deviendrait payante, non reproductible, et non comparable entre
deux exécutions.

CE QUE LA SONDE A TROUVÉ — ET QUI DICTE TOUTE L'ARCHITECTURE
------------------------------------------------------------
Avant d'écrire une ligne, `HarnessEngine.validate(CODE, …)` a été exécuté
contre un vrai fichier. Ce qu'il renvoie :

    CODE score: 100.0   passed: True
       syntax_check          passed=True :: 1 files compile OK
       lint_flake8           passed=True :: flake8 clean          ← flake8 ABSENT
       type_hints            passed=True :: No implementation (passed by default)
       docstrings            passed=True :: No implementation (passed by default)
       tests_exist           passed=True :: No implementation (passed by default)
       no_hardcoded_secrets  passed=True :: No implementation (passed by default)
       no_print_statements   passed=True :: No implementation (passed by default)
       error_handling        passed=True :: No implementation (passed by default)
       imports_sorted        passed=True :: isort check (placeholder)
       no_ai_slop            passed=True :: No implementation (passed by default)

Un **PNG** validé comme du CODE renvoie lui aussi **100**. Un type sans gate
(`DOCUMENT`) renvoie **100 avec zéro gate exécutée**. Autrement dit : le seul
chiffre de qualité qui existait dans la Forge valait 100 pour à peu près
n'importe quoi. Trois causes distinctes, toutes constatées, pas déduites :

1. les gates déclarent `check="check_no_secrets"` et le répartiteur cherche
   `_check_{check}` → `_check_check_no_secrets`, qui n'existe pas ; l'absence
   d'implémentation vaut **succès par défaut**. Huit gates sur dix, dont trois
   `critical`, ne s'exécutaient jamais (corrigé dans `_run_gate`, cf. §Fix) ;
2. `flake8` absent : `python -m flake8` sort en code ≠ 0 avec une sortie vide,
   que la gate lit comme « 0 erreur » → « flake8 clean » ;
3. une gate qui ne filtre que les `.py` renvoie « succès » sur un lot qui n'en
   contient aucun — un succès qui ne dit rien.

D'où la règle centrale de ce module : **un critère non mesuré n'est jamais un
critère réussi.** Il vaut `None`, il sort du dénominateur, et il apparaît dans
`confidence`. Un score de 100 sur 30 % de confiance dit ce qu'il est ; un 100
plein sur des sondes muettes est un mensonge.

LA NORMALISATION, EN UNE LIGNE
------------------------------
    score = 100 × Σ(poids × valeur) / Σ(poids)      sur les seuls critères MESURÉS
    confidence = Σ(poids mesurés) / Σ(poids déclarés)

Renormaliser sur le mesuré est ce qui rend les quatre types comparables : un
`.wav` dont on ne sait lire que l'en-tête et un `.py` passé au crible sont notés
sur leur propre base, et c'est `confidence` — pas le score — qui dit lequel des
deux a été réellement ausculté. Les poids reprennent l'échelle de gravité du
Harness (critical 3 · high 2 · medium 1 · low 0,5), pour qu'un score de code
reste commensurable avec le sien.

Aucun critère mesuré → `score is None`. Jamais 0, jamais 100 : l'absence de
mesure n'est ni un échec ni une réussite.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.artifact_quality import score_artifact, score_artifacts

    q = score_artifact("00_CORE/forge_agents/world_kg.py")
    q.score, q.grade, q.confidence          # 74.2, 'B', 0.83
    print(q.render())                        # le détail critère par critère

    score_artifacts(["a.py", "hero.png"])   # agrégat + moyenne par type

Et branché sur E6-01 — c'est ce qui remplit le champ resté vide :

    with task_run("E6-02", autoscore=True) as run:
        run.artifact("00_CORE/forge_agents/artifact_quality.py")

Vérification : `python -m forge_agents.artifact_quality <chemins…>`
"""

from __future__ import annotations

import ast
import math
import os
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ── Types d'artefacts ─────────────────────────────────────────────────────────

CODE = "code"
ASSET = "asset"
AUDIO = "audio"
NARRATIVE = "narrative"
UNKNOWN = "unknown"

KINDS = (CODE, ASSET, AUDIO, NARRATIVE)

#: Extension → type. Volontairement fermé : ce qui n'y est pas ressort `unknown`
#: plutôt que d'être rapproché du type « qui lui ressemble le plus ».
EXTENSIONS: dict[str, str] = {
    **{e: CODE for e in (".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go",
                         ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs",
                         ".rb", ".php", ".sh", ".sql", ".lua", ".gd")},
    **{e: ASSET for e in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
                          ".tga", ".svg",
                          # Game asset formats (E3-01)
                          ".fbx", ".obj", ".gltf", ".glb", ".blend", ".dae",
                          ".3ds", ".stl", ".psd", ".tiff", ".aseprite", ".ase",
                          ".bvh", ".anim", ".shader", ".hlsl", ".glsl",
                          ".vfx", ".vfxgraph", ".particle")},
    **{e: AUDIO for e in (".wav", ".mp3", ".ogg", ".flac", ".aiff", ".m4a")},
    **{e: NARRATIVE for e in (".md", ".markdown", ".txt", ".rst")},
}

#: Poids = échelle de gravité du Harness, pour rester commensurable avec elle.
CRITICAL, HIGH, MEDIUM, LOW = 3.0, 2.0, 1.0, 0.5

#: Plafond appliqué dès qu'une sonde `blocking` échoue : l'artefact ne peut pas
#: servir, quelles que soient ses autres qualités. Juste sous le plancher du C.
CAP_BLOCKED = 49.0

#: Sondes dont l'échec veut dire « inutilisable », pas « perfectible ».
#: `no_secrets` et `no_slop` n'en font PAS partie : ce sont des fautes graves —
#: les poids les sanctionnent — pas des artefacts hors service. Confondre les
#: deux ferait tomber à 49 tout fichier contenant le mot « placeholder » dans
#: un commentaire, ce module compris.
BLOCKING = frozenset({"syntax", "readable", "not_blank", "not_silent",
                      "container", "no_placeholder"})

#: Même échelle A-F que `herald_audit` (agent_nodes.py). Dupliquée à dessein :
#: l'importer tirerait tout LangGraph dans un module qui note des fichiers.
GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "A"), (70.0, "B"), (50.0, "C"), (30.0, "D"), (0.0, "F"))

#: En-têtes magiques — un `.wav` qui est en fait une page d'erreur HTML est un
#: mode d'échec réel des pipelines génératifs, pas une hypothèse d'école.
MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    ".webp": (b"RIFF",),
    ".wav": (b"RIFF",),
    ".ogg": (b"OggS",),
    ".flac": (b"fLaC",),
    ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
}

#: Mots majuscules trop courants pour désigner une entité de monde. Sans ce
#: filtre, tout début de phrase deviendrait un « nom propre inconnu du monde ».
_NAME_STOP = {
    "le", "la", "les", "un", "une", "des", "du", "de", "au", "aux", "ce",
    "cet", "cette", "ces", "son", "sa", "ses", "leur", "leurs", "il", "elle",
    "ils", "elles", "on", "nous", "vous", "je", "tu", "mais", "car", "donc",
    "or", "ni", "et", "ou", "dans", "pour", "par", "sur", "sous", "avec",
    "sans", "chez", "vers", "quand", "comme", "puis", "alors", "ainsi",
    "cependant", "toutefois", "enfin", "voici", "voilà", "chaque", "tout",
    "toute", "tous", "toutes", "aucun", "aucune", "plus", "moins", "très",
    "the", "a", "an", "this", "that", "these", "those", "it", "he", "she",
    "they", "we", "you", "i", "but", "and", "or", "so", "then", "when",
    "while", "with", "without", "for", "from", "into", "there", "here",
    "each", "every", "all", "none", "more", "less", "very", "lundi", "mardi",
    "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "janvier",
    "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

_NAME_RE = re.compile(
    r"\b[A-ZÀ-ÞŒ][a-zà-öø-ÿœ'’\-]{2,}(?:\s+[A-ZÀ-ÞŒ][a-zà-öø-ÿœ'’\-]{2,})*")
_CODE_BLOCK_RE = re.compile(r"```.*?```|`[^`]*`", re.S)
_URL_RE = re.compile(r"https?://\S+|\[[^\]]*\]\([^)]*\)")
_SENTENCE_RE = re.compile(r"[^.!?…\n]+")

#: Trous béants : ce qui reste d'un gabarit NON REMPLI. Le critère porté par ce
#: motif est `blocking` — il plafonne la note — donc sa précision compte autant
#: que sa portée. Premier jet trop large : `\bplaceholder\b` et `\bTODO\b` nus
#: faisaient tomber à 49 tout document qui PARLE de ces marqueurs, à commencer
#: par le AGENTS.md et le handoff de ce ticket. Un marqueur résiduel est un
#: marqueur EN POSITION (`TODO:`, `<placeholder>`), pas un mot en prose.
_PLACEHOLDER_RE = re.compile(
    r"lorem ipsum|\bTODO\s*[:\-—]|^\s*[-*]?\s*TODO\b|\bTBD\b|\bFIXME\s*[:\-—]|"
    r"[<\[{]\s*(?:placeholder|à compléter|to ?fill)\s*[>\]}]|\bcoming soon\b",
    re.IGNORECASE | re.MULTILINE)


# ── Structures ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Criterion:
    """Un critère mesuré (`value` ∈ [0,1]) ou NON mesuré (`value is None`).

    La distinction est tout le module : un critère non mesuré sort du calcul au
    lieu d'être compté comme réussi. C'est exactement l'erreur qui fait qu'un
    PNG validé comme du code obtient 100 dans le Harness.

    `blocking` marque les sondes dont l'échec signifie « l'artefact ne peut pas
    servir » — pas « il est perfectible ». Il se déduit du NOM (`BLOCKING`) :
    porté par chaque appel, le drapeau finit tôt ou tard oublié sur une branche,
    et c'est la branche oubliée qui rend un livrable cassé présentable.
    """
    name: str
    weight: float
    value: Optional[float]
    detail: str = ""

    @property
    def measured(self) -> bool:
        return self.value is not None

    @property
    def blocking(self) -> bool:
        return self.name in BLOCKING


@dataclass
class Quality:
    """La note d'un artefact, et de quoi la contester ligne par ligne."""
    path: str
    kind: str
    score: Optional[float]
    grade: str
    confidence: float
    criteria: list[Criterion] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "kind": self.kind, "score": self.score,
            "grade": self.grade, "confidence": self.confidence,
            "note": self.note,
            "criteria": [{"name": c.name, "weight": c.weight,
                          "value": c.value, "detail": c.detail}
                         for c in self.criteria],
        }

    def render(self) -> str:
        head = (f"{self.path} [{self.kind}] "
                f"{'—' if self.score is None else f'{self.score:.1f}/100'} "
                f"{self.grade} · confiance {self.confidence:.0%}")
        lines = [head] + [
            f"   {c.name:<18} p={c.weight:<4} "
            f"{'non mesuré' if c.value is None else f'{c.value:>5.2f}'}  {c.detail}"
            for c in self.criteria]
        if self.note:
            lines.append(f"   → {self.note}")
        return "\n".join(lines)


def grade_of(score: Optional[float]) -> str:
    """Score → lettre. `None` → `'?'` : une note absente n'est pas un F.

    Un F dit « mauvais », `?` dit « pas mesuré ». Les confondre pousse à
    remplacer un livrable correct qu'on n'a simplement pas su ausculter.
    """
    if score is None:
        return "?"
    for floor, letter in GRADE_BANDS:
        if score >= floor:
            return letter
    return "F"


def classify(path: str | os.PathLike) -> str:
    """Chemin → type d'artefact, `unknown` si l'extension n'est pas déclarée."""
    return EXTENSIONS.get(Path(str(path)).suffix.lower(), UNKNOWN)


def _normalize(criteria: list[Criterion]) -> tuple[Optional[float], float]:
    """(score 0-100 sur les critères mesurés, confiance) — cf. §NORMALISATION.

    Un critère `blocking` à 0 PLAFONNE le score à `CAP_BLOCKED`. Sans ce
    plafond, une pondération pourtant correcte donne des notes absurdes : un
    WAV entièrement silencieux — inutilisable — sortait à **76,9/100 (B)**,
    parce que « lisible », « durée saine », « 44,1 kHz », « pas de saturation »
    et « en-tête conforme » sont tous vrais d'un silence. Le plafond dit ce que
    la moyenne ne peut pas dire : certains défauts ne se compensent pas.

    Plafond à 49 — juste sous le plancher du C — pour rester aligné sur la
    porte de livraison de la Forge (grade < C = bloqué, cf. `Herald`).
    """
    total = sum(c.weight for c in criteria)
    done = [c for c in criteria if c.measured]
    weight = sum(c.weight for c in done)
    if not weight:
        return None, 0.0
    score = 100.0 * sum(c.weight * float(c.value) for c in done) / weight
    if any(c.blocking and c.value == 0.0 for c in done):
        score = min(score, CAP_BLOCKED)
    return round(score, 1), round(weight / total, 3) if total else 0.0


def _band(value: float, low: float, high: float) -> float:
    """Rampe linéaire bornée : ≤low → 0, ≥high → 1 (ou l'inverse si low>high)."""
    if low == high:
        return 1.0 if value >= high else 0.0
    v = (value - low) / (high - low)
    return max(0.0, min(1.0, v))


def _read_text(path: Path, limit: int = 2_000_000) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


# ── CODE ──────────────────────────────────────────────────────────────────────

#: Détails EXACTS par lesquels le Harness annonce qu'il n'a rien regardé.
#: Comparés strictement, jamais par sous-chaîne : le détail d'un échec contient
#: le texte trouvé DANS le fichier, et « placeholder » fait justement partie des
#: motifs anti-slop. Un `in detail` transformait donc une vraie détection —
#: « AI slop detected: 'placeholder' » — en « sonde indisponible », c'est-à-dire
#: en critère non mesuré, c'est-à-dire en note plus haute. Constaté sur le
#: fichier de tests de ce module même.
_MUTE_EXACT = frozenset({"No implementation (passed by default)", "No Python files"})


def _is_mute(detail: str) -> bool:
    """Le Harness a-t-il répondu sans rien mesurer ?"""
    return (detail in _MUTE_EXACT
            or detail.endswith("(placeholder)")
            or detail.endswith("(skipped)"))


def _harness_gate(method: str, path: Path, *, severity: str = "high"):
    """Appelle un détecteur du Harness DIRECTEMENT, sans passer par `_run_gate`.

    Les détecteurs de `harness_engine` sont bons ; c'est leur répartiteur qui
    les rendait inatteignables (cf. §SONDE). On les appelle par leur nom réel,
    ce qui reste vrai que le répartiteur soit corrigé ou non — ce module ne
    dépend pas d'un correctif situé dans un autre fichier.

    Renvoie `(passed, detail)` ou `None` si le Harness est indisponible : une
    dépendance manquante rend le critère NON mesuré, jamais réussi.
    """
    try:
        from .harness_engine import HarnessEngine, QualityGate
        gate = QualityGate(name=method, description="", severity=severity,
                           check=method, threshold=0)
        fn = getattr(HarnessEngine(), method, None)
        if fn is None:
            return None
        res = fn(gate, [str(path)], None)
        detail = (res.details or "").strip().replace("\n", " ")[:110]
        if _is_mute(detail):
            return None
        return bool(res.passed), detail
    except Exception as exc:  # noqa: BLE001 — indisponible = non mesuré
        return None


def _public_defs(tree: ast.AST) -> list[ast.AST]:
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not n.name.startswith("_")]


def _has_test_file(path: Path) -> bool:
    """Un test existe-t-il pour ce fichier ? (même dossier, racine, tests/)

    Le Harness ne regarde que le dossier du fichier ; dans cette Forge les
    tests vivent à la RACINE (`test_world_kg.py`, `test_forge_backlog.py`…),
    donc ce critère y répondait toujours « absent ». Un critère qui répond
    toujours la même chose ne mesure rien.
    """
    name = f"test_{path.stem}.py"
    roots = [path.parent, path.parent / "tests"]
    here = path.resolve()
    for _ in range(6):                       # remonte jusqu'à la racine du dépôt
        here = here.parent
        roots += [here, here / "tests"]
        if (here / ".git").exists():
            break
    return any((r / name).exists() for r in roots)


def _code_criteria(path: Path) -> tuple[list[Criterion], str]:
    text = _read_text(path)
    is_py = path.suffix.lower() == ".py"
    out: list[Criterion] = []
    note = ""

    # 1. Syntaxe — `ast.parse`, PAS le `python -m py_compile` du Harness : le
    #    `python` du PATH n'est pas l'interpréteur du projet (constat du handoff
    #    E2-06 §4.4), et un sous-processus absent ferait ÉCHOUER une gate
    #    critique sur un fichier parfaitement valide.
    tree: Optional[ast.AST] = None
    if is_py:
        try:
            tree = ast.parse(text)
            out.append(Criterion("syntax", CRITICAL, 1.0, "AST parsé"))
        except SyntaxError as e:
            out.append(Criterion("syntax", CRITICAL, 0.0,
                                 f"ligne {e.lineno}: {e.msg}"))
    else:
        out.append(Criterion("syntax", CRITICAL, None,
                             f"aucun analyseur pour {path.suffix or '(sans extension)'}"))

    # 2-4. Détecteurs du Harness (secrets, slop, gestion d'erreur, print).
    for crit, weight, method, py_only in (
            ("no_secrets", CRITICAL, "_check_no_secrets", False),
            ("no_slop", CRITICAL, "_check_no_ai_slop", False),
            ("error_handling", HIGH, "_check_error_handling", True),
            ("no_print", MEDIUM, "_check_no_print", True)):
        if py_only and not is_py:
            out.append(Criterion(crit, weight, None, "sonde réservée au Python"))
            continue
        res = _harness_gate(method, path)
        if res is None:
            out.append(Criterion(crit, weight, None, "détecteur Harness indisponible"))
        else:
            passed, detail = res
            out.append(Criterion(crit, weight, 1.0 if passed else 0.0, detail))

    # 5. Tests — gradué, pas binaire : un fichier sans test n'est pas un fichier
    #    cassé, c'est un fichier moins sûr.
    if is_py and not path.name.startswith("test_"):
        has = _has_test_file(path)
        out.append(Criterion("tests_exist", HIGH, 1.0 if has else 0.0,
                             f"test_{path.stem}.py {'trouvé' if has else 'absent'}"))
    else:
        out.append(Criterion("tests_exist", HIGH, None,
                             "fichier de test, ou langage hors périmètre"))

    # 6-7. Couverture docstrings / annotations — mesurées par AST et GRADUÉES.
    #      Le Harness bascule à un seuil fixe (>10 manquants) : sur un gros
    #      fichier le seuil est franchi d'office, sur un petit jamais. Un seuil
    #      ne normalise pas ; une proportion, si.
    if tree is not None:
        pub = _public_defs(tree)
        if pub:
            documented = sum(1 for n in pub if ast.get_docstring(n))
            out.append(Criterion("docstrings", MEDIUM, documented / len(pub),
                                 f"{documented}/{len(pub)} symboles publics documentés"))
            funcs = [n for n in pub
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if path.name.startswith("test_"):
                # Personne n'annote `def test_x(tmp_path)`. Mesurer ça revient à
                # poser une question dont la réponse est connue d'avance — le
                # même défaut que « chercher les tests uniquement à côté du
                # fichier ». Les docstrings, elles, restent mesurées : dans
                # cette Forge elles disent ce que le test verrouille.
                out.append(Criterion("type_hints", MEDIUM, None,
                                     "fichier de tests : annotations non pertinentes"))
            elif funcs:
                typed = sum(1 for f in funcs if _is_typed(f))
                out.append(Criterion("type_hints", MEDIUM, typed / len(funcs),
                                     f"{typed}/{len(funcs)} fonctions annotées"))
            else:
                out.append(Criterion("type_hints", MEDIUM, None,
                                     "aucune fonction publique"))
        else:
            out.append(Criterion("docstrings", MEDIUM, None, "aucun symbole public"))
            out.append(Criterion("type_hints", MEDIUM, None, "aucun symbole public"))
    else:
        out.append(Criterion("docstrings", MEDIUM, None, "AST indisponible"))
        out.append(Criterion("type_hints", MEDIUM, None, "AST indisponible"))

    # 8. Lint — mesuré SEULEMENT si le linter est réellement installé. La gate
    #    `lint_flake8` du Harness annonce « flake8 clean » alors que flake8 est
    #    absent de cet environnement : sortie vide lue comme « 0 erreur ».
    out.append(_lint_criterion(path, is_py))

    if not is_py:
        note = ("langage non-Python : seules les sondes textuelles s'appliquent "
                "(cf. confiance)")
    return out, note


def _is_typed(fn: ast.AST) -> bool:
    """Fonction publique annotée : retour + tous les arguments hors self/cls."""
    args = [a for a in list(fn.args.args) + list(fn.args.kwonlyargs)
            if a.arg not in ("self", "cls")]
    return fn.returns is not None and all(a.annotation is not None for a in args)


def _lint_criterion(path: Path, is_py: bool) -> Criterion:
    if not is_py:
        return Criterion("lint", HIGH, None, "linter réservé au Python")
    import importlib.util
    import subprocess
    import sys
    tool = next((t for t in ("ruff", "flake8")
                 if importlib.util.find_spec(t) is not None), None)
    if tool is None:
        return Criterion("lint", HIGH, None, "ni ruff ni flake8 installés")
    cmd = ([sys.executable, "-m", "ruff", "check", "--quiet", str(path)] if tool == "ruff"
           else [sys.executable, "-m", "flake8", "--max-line-length=120",
                 "--extend-ignore=E501,W503", str(path)])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return Criterion("lint", HIGH, None, f"{tool} injoignable: {type(exc).__name__}")
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    # 0 alerte → 1,0 ; 1 alerte pour 100 lignes → 0. Rapporté à la taille du
    # fichier, sinon un module de 2 000 lignes est condamné d'avance.
    loc = max(1, len(_read_text(path).splitlines()))
    density = len(lines) / loc * 100
    return Criterion("lint", HIGH, 1.0 - _band(density, 0.0, 1.0),
                     f"{tool}: {len(lines)} alerte(s) / {loc} lignes")


# ── ASSET ─────────────────────────────────────────────────────────────────────

def _magic_criterion(path: Path) -> Criterion:
    """Le contenu correspond-il à l'extension ? (une page d'erreur nommée .png)"""
    expected = MAGIC.get(path.suffix.lower())
    if not expected:
        return Criterion("container", MEDIUM, None, "aucune signature connue")
    try:
        head = path.open("rb").read(16)
    except OSError as exc:
        return Criterion("container", MEDIUM, 0.0, f"illisible: {exc.strerror}")
    ok = any(head.startswith(sig) for sig in expected)
    return Criterion("container", MEDIUM, 1.0 if ok else 0.0,
                     f"en-tête {head[:8]!r}" if not ok else "en-tête conforme")


def _svg_criteria(path: Path) -> list[Criterion]:
    import xml.etree.ElementTree as ET
    text = _read_text(path, 500_000)
    try:
        root = ET.fromstring(text)
        out = [Criterion("readable", CRITICAL, 1.0, "XML parsé")]
    except ET.ParseError as e:
        return [Criterion("readable", CRITICAL, 0.0, str(e)[:80]),
                Criterion("not_blank", CRITICAL, None, "non parsé"),
                Criterion("dimensions", HIGH, None, "non parsé"),
                Criterion("weight", MEDIUM, None, "non parsé")]
    drawn = [e for e in root.iter()
             if e.tag.split("}")[-1] in ("path", "rect", "circle", "ellipse",
                                         "polygon", "polyline", "line", "text",
                                         "image", "use")]
    out.append(Criterion("not_blank", CRITICAL, 1.0 if drawn else 0.0,
                         f"{len(drawn)} élément(s) dessiné(s)"))
    has_box = bool(root.get("viewBox") or (root.get("width") and root.get("height")))
    out.append(Criterion("dimensions", HIGH, 1.0 if has_box else 0.0,
                         "viewBox/width+height" if has_box else "aucune dimension déclarée"))
    out.append(Criterion("weight", MEDIUM, None, "poids non pertinent en vectoriel"))
    return out


def _asset_criteria(path: Path) -> tuple[list[Criterion], str]:
    if path.suffix.lower() == ".svg":
        return _svg_criteria(path) + [_magic_criterion(path)], ""

    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return ([Criterion("readable", CRITICAL, None, "Pillow absent"),
                 Criterion("not_blank", CRITICAL, None, "Pillow absent"),
                 Criterion("dimensions", HIGH, None, "Pillow absent"),
                 Criterion("alpha", MEDIUM, None, "Pillow absent"),
                 Criterion("weight", MEDIUM, None, "Pillow absent"),
                 _magic_criterion(path)],
                "Pillow absent : seule la signature de fichier a été vérifiée")

    out: list[Criterion] = []
    try:
        with Image.open(path) as probe:
            probe.verify()                       # verify() invalide l'objet…
        img = Image.open(path)
        img.load()                               # …d'où la relecture
    except Exception as exc:  # noqa: BLE001
        return ([Criterion("readable", CRITICAL, 0.0, f"{type(exc).__name__}: {exc}"[:90]),
                 Criterion("not_blank", CRITICAL, None, "image non ouverte"),
                 Criterion("dimensions", HIGH, None, "image non ouverte"),
                 Criterion("alpha", MEDIUM, None, "image non ouverte"),
                 Criterion("weight", MEDIUM, None, "image non ouverte"),
                 _magic_criterion(path)], "")

    w, h = img.size
    out.append(Criterion("readable", CRITICAL, 1.0, f"{img.mode} {w}×{h}"))

    # Uniforme = rendu raté (transparent, noir plein) : le mode d'échec le plus
    # courant d'une chaîne d'assets, et invisible à toute vérification de format.
    extrema = img.convert("RGBA").getextrema()
    flat = all(lo == hi for lo, hi in extrema)
    out.append(Criterion("not_blank", CRITICAL, 0.0 if flat else 1.0,
                         "image uniforme (rendu vide ?)" if flat else "contenu non uniforme"))

    small, big = min(w, h), max(w, h)
    dim = 1.0 if small >= 16 and big <= 8192 else (
        0.5 if small >= 8 and big <= 16384 else 0.0)
    out.append(Criterion("dimensions", HIGH, dim, f"{w}×{h}"))

    if "A" in img.getbands():
        alpha = img.getchannel("A")
        lo, hi = alpha.getextrema()
        opaque = hi > 0
        out.append(Criterion("alpha", MEDIUM, 1.0 if opaque else 0.0,
                             "entièrement transparent" if not opaque
                             else f"alpha {lo}-{hi}"))
    else:
        out.append(Criterion("alpha", MEDIUM, None, "aucun canal alpha"))

    # Octets par pixel : ≤1 = compressé correctement, ≥4 = brut non optimisé.
    bpp = path.stat().st_size / max(1, w * h)
    out.append(Criterion("weight", MEDIUM, 1.0 - _band(bpp, 1.0, 4.0),
                         f"{bpp:.2f} octet/pixel"))
    out.append(_magic_criterion(path))
    img.close()
    return out, ""


# ── AUDIO ─────────────────────────────────────────────────────────────────────

def _audio_criteria(path: Path) -> tuple[list[Criterion], str]:
    unmeasured = lambda why: [  # noqa: E731
        Criterion("readable", CRITICAL, None, why),
        Criterion("not_silent", CRITICAL, None, why),
        Criterion("no_clipping", HIGH, None, why),
        Criterion("duration", HIGH, None, why),
        Criterion("sample_rate", MEDIUM, None, why),
        Criterion("dc_offset", MEDIUM, None, why)]

    if path.suffix.lower() != ".wav":
        # Pas de dépendance audio dans cette Forge (mutagen/soundfile absents).
        # Un `.ogg` ressort donc noté sur sa seule signature, avec une confiance
        # basse qui l'annonce — plutôt qu'un score plein sur rien.
        return (unmeasured(f"{path.suffix} illisible sans dépendance audio")
                + [_magic_criterion(path)],
                "format non-WAV : seule la signature a été vérifiée")

    try:
        with wave.open(str(path), "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.getnframes()
            raw = w.readframes(min(frames, rate * 60))   # 60 s suffisent à juger
    except Exception as exc:  # noqa: BLE001
        return ([Criterion("readable", CRITICAL, 0.0, f"{type(exc).__name__}: {exc}"[:90])]
                + unmeasured("WAV non ouvert")[1:] + [_magic_criterion(path)], "")

    out = [Criterion("readable", CRITICAL, 1.0,
                     f"{channels}ch {width * 8}bit {rate}Hz {frames}f")]
    seconds = frames / rate if rate else 0.0
    out.append(Criterion("duration", HIGH,
                         1.0 if 0.05 <= seconds <= 1800 else 0.0,
                         f"{seconds:.2f} s"))
    out.append(Criterion("sample_rate", MEDIUM,
                         1.0 if rate >= 44100 else 0.6 if rate >= 22050
                         else 0.3 if rate >= 16000 else 0.0, f"{rate} Hz"))

    peak, clipped, mean = _pcm_stats(raw, width)
    if peak is None:
        why = f"échantillons {width * 8} bits non décodés"
        out += [Criterion("not_silent", CRITICAL, None, why),
                Criterion("no_clipping", HIGH, None, why),
                Criterion("dc_offset", MEDIUM, None, why)]
    else:
        full = float(2 ** (width * 8 - 1))
        ratio = peak / full
        db = 20 * math.log10(ratio) if ratio > 0 else -999.0
        out.append(Criterion("not_silent", CRITICAL, 1.0 if ratio > 0.01 else 0.0,
                             "silence" if ratio <= 0.01 else f"crête {db:.1f} dBFS"))
        out.append(Criterion("no_clipping", HIGH, 1.0 - _band(clipped, 0.0, 0.01),
                             f"{clipped:.3%} d'échantillons à pleine échelle"))
        out.append(Criterion("dc_offset", MEDIUM,
                             1.0 - _band(abs(mean) / full, 0.001, 0.05),
                             f"offset continu {abs(mean) / full:.4f}"))
    out.append(_magic_criterion(path))
    return out, ""


def _pcm_stats(raw: bytes, width: int) -> tuple[Optional[float], float, float]:
    """(crête, proportion d'échantillons saturés, moyenne) — `None` si non décodé.

    16 bits couvre ce que produisent les chaînes audio de la Forge ; 8 et 32
    bits ressortent NON MESURÉS plutôt que convertis à la louche.
    """
    if width != 2 or not raw:
        return None, 0.0, 0.0
    import array
    samples = array.array("h")
    samples.frombytes(raw[:len(raw) - (len(raw) % 2)])
    if not samples:
        return None, 0.0, 0.0
    peak = float(max(abs(min(samples)), abs(max(samples))))
    clipped = sum(1 for s in samples if abs(s) >= 32767) / len(samples)
    return peak, clipped, sum(samples) / len(samples)


# ── NARRATIVE ─────────────────────────────────────────────────────────────────

def _narrative_criteria(path: Path, world_id: str = "") -> tuple[list[Criterion], str]:
    text = _read_text(path, 400_000)
    prose = _URL_RE.sub(" ", _CODE_BLOCK_RE.sub(" ", text))
    words = prose.split()
    out: list[Criterion] = []

    # Substance — gradué : 50 mots = fragment, 300 = texte tenu.
    out.append(Criterion("substance", CRITICAL, _band(len(words), 50, 300),
                         f"{len(words)} mots"))

    holes = _PLACEHOLDER_RE.findall(prose)
    out.append(Criterion("no_placeholder", CRITICAL, 0.0 if holes else 1.0,
                         f"{len(holes)} marqueur(s) : {sorted(set(holes))[:3]}"
                         if holes else "aucun gabarit résiduel"))

    # Répétition littérale : la panne la plus visible d'un texte généré.
    sentences = [s.strip().lower() for s in _SENTENCE_RE.findall(prose)
                 if len(s.strip()) > 30]
    if len(sentences) >= 5:
        dup = 1 - len(set(sentences)) / len(sentences)
        out.append(Criterion("no_repetition", HIGH, 1.0 - _band(dup, 0.0, 0.3),
                             f"{dup:.1%} de phrases dupliquées"))
    else:
        out.append(Criterion("no_repetition", HIGH, None,
                             "moins de 5 phrases : mesure sans valeur"))

    headings = len(re.findall(r"^#{1,6}\s+\S", text, re.M))
    paragraphs = len([p for p in re.split(r"\n\s*\n", prose) if p.strip()])
    out.append(Criterion("structure", MEDIUM,
                         1.0 if headings and paragraphs >= 2
                         else 0.5 if paragraphs >= 2 else 0.0,
                         f"{headings} titre(s), {paragraphs} paragraphe(s)"))

    # Tics de style : la doctrine anti-slop du Harness, poids MOINDRE qu'un
    # gabarit résiduel — un tic est un défaut de forme, un « TODO » est un trou.
    res = _harness_gate("_check_no_ai_slop", path, severity="medium")
    out.append(Criterion("no_slop", MEDIUM,
                         None if res is None else (1.0 if res[0] else 0.0),
                         "détecteur Harness indisponible" if res is None else res[1]))

    out.append(_grounding_criterion(prose, world_id))
    note = ("" if world_id else
            "aucun monde fourni : l'ancrage narratif n'a pas été mesuré "
            "(passer world_id=…)")
    return out, note


def _world_names(world_id: str) -> set[str]:
    """Index des noms et alias du World-KG (E2-01), sous forme sluggée.

    Un index construit une fois vaut mieux que `resolve()` par candidat : ce
    dernier balaie tous les nœuds du label dès que le nom n'est pas une clé
    exacte. Ici : une passe, puis des comparaisons d'ensemble.
    """
    from .world_kg import WORLD_NODE_TABLES, get_world_kg, slugify, split_aliases
    kg = get_world_kg(world_id)
    names: set[str] = set()
    for label in WORLD_NODE_TABLES:
        for node in kg.all_nodes(label, limit=5000):
            raw = node.get("name") or ""
            if raw:
                names.add(slugify(raw))
            for alias in split_aliases(node.get("aliases")):
                names.add(slugify(alias))
    return {n for n in names if n}


def _grounding_criterion(prose: str, world_id: str) -> Criterion:
    """Les noms propres du texte existent-ils dans le monde ?

    C'est LE critère qui distingue un texte de jeu d'un texte bien écrit : un
    PNJ inventé en cours de rédaction est indétectable au style et fatal à la
    cohérence. Non mesuré tant qu'aucun monde n'est fourni — noter l'ancrage
    d'un texte sans monde de référence reviendrait à sanctionner tout nom propre.
    """
    if not world_id:
        return Criterion("grounded", CRITICAL, None, "aucun monde fourni")
    try:
        known = _world_names(world_id)
    except Exception as exc:  # noqa: BLE001
        return Criterion("grounded", CRITICAL, None,
                         f"World-KG indisponible: {type(exc).__name__}")
    if not known:
        return Criterion("grounded", CRITICAL, None,
                         f"monde « {world_id} » vide : rien à quoi s'ancrer")

    from .world_kg import slugify
    candidates = {m.strip() for m in _NAME_RE.findall(prose)}
    candidates = {c for c in candidates
                  if c.lower() not in _NAME_STOP and len(slugify(c)) > 2}
    if len(candidates) < 3:
        return Criterion("grounded", CRITICAL, None,
                         f"{len(candidates)} nom(s) propre(s) : trop peu pour mesurer")
    unknown = sorted(c for c in candidates if slugify(c) not in known)
    ratio = 1 - len(unknown) / len(candidates)
    detail = f"{len(candidates) - len(unknown)}/{len(candidates)} ancrés"
    if unknown:
        detail += f" · hors monde : {', '.join(unknown[:4])}"
    return Criterion("grounded", CRITICAL, ratio, detail)


# ── API publique ──────────────────────────────────────────────────────────────

_SCORERS = {CODE: _code_criteria, ASSET: _asset_criteria, AUDIO: _audio_criteria}


def score_artifact(path: str | os.PathLike, world_id: str = "") -> Quality:
    """Note un artefact 0-100 selon son type. `score is None` = non mesurable.

    `world_id` n'a d'effet que sur le narratif : il branche l'ancrage sur le
    World-KG d'E2-01. Sans lui, ce critère sort NON mesuré (et la confiance
    baisse d'autant) au lieu d'être deviné.
    """
    p = Path(str(path))
    kind = classify(p)
    if kind == UNKNOWN:
        return Quality(str(path), UNKNOWN, None, "?", 0.0, [],
                       f"extension {p.suffix or '(aucune)'} hors des 4 types du ticket")
    if not p.exists():
        return Quality(str(path), kind, None, "?", 0.0, [],
                       "fichier introuvable — un artefact déclaré mais absent "
                       "n'est pas un artefact de mauvaise qualité, c'est un trou")
    if p.is_dir():
        return Quality(str(path), kind, None, "?", 0.0, [], "chemin = dossier")

    if kind == NARRATIVE:
        criteria, note = _narrative_criteria(p, world_id)
    else:
        criteria, note = _SCORERS[kind](p)
    score, confidence = _normalize(criteria)
    return Quality(str(path), kind, score, grade_of(score), confidence, criteria, note)


def score_artifacts(paths, world_id: str = "") -> dict[str, Any]:
    """Note un lot. Moyenne d'ensemble + moyenne par type + liste des non notés.

    La moyenne est **non pondérée par la confiance** : un artefact noté sur peu
    de sondes pèse autant qu'un autre. Pondérer par la confiance ferait taire
    les artefacts les moins auscultés — exactement ceux qu'il faut regarder.
    Le nombre d'artefacts non notés est rendu à côté du chiffre, pas dissous.
    """
    qualities = [score_artifact(p, world_id) for p in paths]
    scored = [q for q in qualities if q.score is not None]
    by_kind: dict[str, dict] = {}
    for q in qualities:
        slot = by_kind.setdefault(q.kind, {"count": 0, "scored": 0, "score": None,
                                           "_sum": 0.0})
        slot["count"] += 1
        if q.score is not None:
            slot["scored"] += 1
            slot["_sum"] += q.score
    for slot in by_kind.values():
        slot["score"] = (round(slot["_sum"] / slot["scored"], 1)
                         if slot["scored"] else None)
        slot.pop("_sum")
    overall = round(sum(q.score for q in scored) / len(scored), 1) if scored else None
    return {
        "score": overall,
        "grade": grade_of(overall),
        "confidence": (round(sum(q.confidence for q in scored) / len(scored), 3)
                       if scored else 0.0),
        "artifacts": len(qualities),
        "scored": len(scored),
        "unscored": [q.path for q in qualities if q.score is None],
        "by_kind": dict(sorted(by_kind.items())),
        "details": [q.as_dict() for q in qualities],
    }


def quality_of(paths, world_id: str = "") -> Optional[float]:
    """Le seul chiffre dont E6-01 a besoin : la note du lot, ou `None`."""
    return score_artifacts(paths, world_id)["score"] if paths else None


def render(paths, world_id: str = "") -> str:
    """Rapport texte d'un lot — c'est ce qu'affiche `python -m …`."""
    result = score_artifacts(paths, world_id)
    overall = result["score"]
    verdict = "aucune mesure" if overall is None else f"{overall}/100 {result['grade']}"
    lines = [f"Qualité des artefacts — {verdict} "
             f"· {result['scored']}/{result['artifacts']} notés "
             f"· confiance {result['confidence']:.0%}"]
    for kind, slot in result["by_kind"].items():
        mean = "—" if slot["score"] is None else f"{slot['score']:.1f}/100"
        lines.append(f"  {kind:<10} {slot['scored']}/{slot['count']} notés · {mean}")
    for detail in result["details"]:
        q = Quality(detail["path"], detail["kind"], detail["score"], detail["grade"],
                    detail["confidence"],
                    [Criterion(c["name"], c["weight"], c["value"], c["detail"])
                     for c in detail["criteria"]], detail["note"])
        lines.append(q.render())
    return "\n".join(lines)


if __name__ == "__main__":  # auto-vérification / CLI
    import sys
    targets = sys.argv[1:] or [__file__]
    print(render(targets, world_id=os.environ.get("FORGE_WORLD_ID", "")))
