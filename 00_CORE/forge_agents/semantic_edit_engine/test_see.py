"""test_see.py — vérification du Semantic Edit Engine (MCPT).

Objectif de la suite : prouver que, sur des cas variés, le moteur produit un plan
STRICTEMENT moins coûteux qu'une réécriture, et que ce plan reproduit EXACTEMENT
la cible. Aucun cas n'est hardcodé dans le moteur.

    python 00_CORE/forge_agents/semantic_edit_engine/test_see.py
"""

import sys
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "00_CORE"))

from forge_agents.semantic_edit_engine import (  # noqa: E402
    SymbolResolver,
    PatchScorer,
    EditMetrics,
    get_patch_optimizer,
)
from forge_agents.semantic_edit_engine.edit_primitives import (  # noqa: E402
    InsertAfter,
    Replace,
    DeleteRange,
    EditError,
    derive_ops,
)

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        FAILURES.append(label)


# ── Cas d'édition réels (nom, original, cible, symbole) ───────────────────────
CASES = [
    (
        "ajout condition",
        "def guard(user):\n    if user:\n        return allow()\n    return deny()\n",
        "def guard(user):\n    if user and user.is_active:\n        return allow()\n    return deny()\n",
        "guard",
    ),
    (
        "ajout parametre",
        "def fetch(url):\n    return client.get(url)\n",
        "def fetch(url, timeout=30):\n    return client.get(url, timeout=timeout)\n",
        "fetch",
    ),
    (
        "ajout import",
        "import os\n\n\ndef run():\n    return os.getcwd()\n",
        "import os\nimport sys\n\n\ndef run():\n    return os.getcwd()\n",
        "",
    ),
    (
        "suppression ligne morte",
        "def run():\n    debug = True\n    return 1\n",
        "def run():\n    return 1\n",
        "run",
    ),
    (
        "renommage local",
        "def total(items):\n    s = 0\n    for i in items:\n        s += i\n    return s\n",
        "def total(items):\n    acc = 0\n    for i in items:\n        acc += i\n    return acc\n",
        "total",
    ),
]


def test_primitives():
    print("\n[1] Primitives")
    src = "if (user) {"
    check(
        InsertAfter(anchor="user", text=" && user.isActive").apply(src) == "if (user && user.isActive) {",
        "InsertAfter insere sans detruire",
    )
    check(Replace(anchor="user", replacement="u").apply(src) == "if (u) {", "Replace remplace 1 occurrence")
    check(DeleteRange(start=0, end=3).apply(src) == "(user) {", "DeleteRange supprime l'intervalle")
    try:
        InsertAfter(anchor="absent", text="x").apply(src)
        check(False, "ancre absente leve EditError")
    except EditError:
        check(True, "ancre absente leve EditError")


def test_minimal_cost():
    print("\n[2] Cout minimal — le plan gagnant bat la reecriture")
    opt = get_patch_optimizer()
    for name, orig, target, symbol in CASES:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(orig)
            tmp = Path(fh.name)
        try:
            cands = opt.candidates(orig, target, tmp, symbol or "file")
            check(bool(cands), f"{name}: au moins un plan")
            if not cands:
                continue
            best = cands[0]
            check(best.plan.apply(orig) == target, f"{name}: le plan reproduit la cible")
            rewrite_cost = len(target)
            check(
                best.emit_cost < rewrite_cost,
                f"{name}: emit={best.emit_cost} < reecriture={rewrite_cost}",
            )
            check(
                all(best.mcpt_cost <= c.mcpt_cost for c in cands),
                f"{name}: le gagnant est bien le moins couteux ({best.strategy.value})",
            )
        finally:
            tmp.unlink(missing_ok=True)


def test_no_hardcoded_case():
    print("\n[3] Aucun cas hardcode")
    orig = "def a():\n    return 1\n"
    target = "def a():\n    return 2\n"
    plans = derive_ops(orig, target, symbol="a")
    check(bool(plans) and plans[0].apply(orig) == target, "cas jamais vu par le moteur: traite")


def test_symbol_resolution():
    print("\n[4] Resolution de symbole")
    target = SymbolResolver().resolve("test_symbol_resolution", Path(__file__))
    check(target is not None and target.name == "test_symbol_resolution", "symbole resolu dans ce fichier")


def test_scoring_and_metrics():
    print("\n[5] Scoring & metriques")
    scorer = PatchScorer()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write("x = 1\n")
        tmp = Path(fh.name)
    try:
        good = scorer.score("x = 1\n", "x = 2\n", tmp)
        broken = scorer.score("x = 1\n", "x = (\n", tmp)
        check(good.compilation == 1.0, "code valide -> compilation 1.0")
        check(broken.compilation == 0.0, "code invalide -> compilation 0.0")
        check(good.global_score > broken.global_score, "le patch sain score plus haut")
        check(EditMetrics.zero().token_savings == 0.0, "EditMetrics.zero() neutre")
    finally:
        tmp.unlink(missing_ok=True)


def test_semantic_safety():
    print("\n[6] Semantic safety")
    from forge_agents.semantic_edit_engine.semantic_safety import check_safety

    base = "import os\n\n\ndef f(a):\n    return os.sep + a\n"
    cases = [
        ("patch sain", "import os\n\n\ndef f(a):\n    return os.sep + a + '!'\n", False),
        ("API supprimee", "import os\n\n\ndef g(a):\n    return os.sep + a\n", True),
        ("ref pendante", "import os\n\n\ndef f(a):\n    return os.sep + a + nope\n", True),
        ("import retire mais utilise", "def f(a):\n    return os.sep + a\n", True),
        ("syntaxe cassee", "import os\n\n\ndef f(a):\n    return (\n", True),
    ]
    for label, modified, expect_block in cases:
        rep = check_safety(base, modified, Path("demo.py"))
        check(rep.blocked == expect_block, f"{label}: blocked={rep.blocked} (attendu {expect_block})")

    sig = check_safety(base, "import os\n\n\ndef f(a, b=1):\n    return os.sep + a\n", Path("demo.py"))
    check(not sig.blocked and any(i.check == "api_changed" for i in sig.issues),
          "changement de signature = WARN, pas BLOCK")


def test_patch_review_degradation():
    print("\n[7] Revue statique — degradation gracieuse")
    from forge_agents.semantic_edit_engine.patch_review import review_patch

    old = "def f():\n    return 1\n"
    rep = review_patch(old, "def f():\n    return 1 + nope\n", Path("demo.py"))
    check(rep.blocked and rep.blocked_by_safety, "regression semantique -> bloque")
    clean = review_patch(old, "def f():\n    return 2\n", Path("demo.py"))
    check(not clean.blocked, "patch sain -> passe")
    check(isinstance(clean.tools_skipped, list), "outils absents reportes, jamais fatals")


def test_impact_gate_degradation():
    print("\n[8] Gate impact — jamais bloquant si indisponible")
    from forge_agents.semantic_edit_engine.impact_gate import check_impact

    rep = check_impact("")
    check(not rep.available and not rep.blocked, "symbole vide -> indisponible, non bloquant")
    ghost = check_impact("symbole_totalement_inexistant_xyz")
    check(not ghost.blocked, "symbole inconnu -> non bloquant")


def test_pipeline():
    print("\n[9] Pipeline complet")
    import tempfile
    from forge_agents.semantic_edit_engine.edit_pipeline import run_edit

    src = "def guard(user):\n    if user:\n        return 1\n    return 0\n"
    good = "def guard(user):\n    if user and user.active:\n        return 1\n    return 0\n"
    bad = "def guard(user):\n    return missing_helper(user)\n"

    def with_tmp(fn):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(src)
            tmp = Path(fh.name)
        try:
            return fn(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    check(with_tmp(lambda p: run_edit(p, target_name="guard", modified_code=good).status) == "planned",
          "dry-run sain -> planned")
    check(with_tmp(lambda p: run_edit(p, target_name="guard", modified_code=bad).status) == "blocked_review",
          "patch cassé -> blocked_review")
    check(with_tmp(lambda p: p.read_text(encoding="utf-8") == src if run_edit(
        p, target_name="guard", modified_code=good).status == "planned" else False),
          "dry-run n'ecrit rien")

    def applied(p):
        res = run_edit(p, target_name="guard", modified_code=good, apply=True)
        return res.status == "applied" and "user.active" in p.read_text(encoding="utf-8")
    check(with_tmp(applied), "apply -> fichier reellement patche")

    def rollback_on_red(p):
        res = run_edit(p, target_name="guard", modified_code=good, apply=True,
                       test_cmd="python -c \"import sys; sys.exit(1)\"")
        return res.status == "tests_failed" and res.rolled_back and p.read_text(encoding="utf-8") == src
    check(with_tmp(rollback_on_red), "tests rouges -> rollback, fichier restaure")

    def no_plan(p):
        return run_edit(p, target_name="guard", modified_code=src).status == "no_plan"
    check(with_tmp(no_plan), "cible identique -> no_plan")


if __name__ == "__main__":
    test_primitives()
    test_minimal_cost()
    test_no_hardcoded_case()
    test_symbol_resolution()
    test_scoring_and_metrics()
    test_semantic_safety()
    test_patch_review_degradation()
    test_impact_gate_degradation()
    test_pipeline()
    print("\n" + ("ALL TESTS PASSED" if not FAILURES else f"{len(FAILURES)} FAILURE(S): {FAILURES}"))
    raise SystemExit(1 if FAILURES else 0)
