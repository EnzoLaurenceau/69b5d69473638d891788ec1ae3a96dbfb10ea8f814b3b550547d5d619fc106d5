"""Legal compliance gate — RÈGLE LÉGALE forge.

Scanne un livrable généré et vérifie la présence des artefacts juridiques
obligatoires. Blueprint source de vérité : 00_CORE/blueprints/legal_compliance.md.

Usage forge:
    from forge_agents.legal_compliance import legal_check
    r = legal_check("mvp_output/mon_site", product_type="ecommerce")
    r["deliver_ready"]  # False => DELIVER BLOQUÉ

CLI:
    python 00_CORE/forge_agents/legal_compliance.py <path> [website|ecommerce|saas|chatbot|email]
    (types combinables: "saas,chatbot"; sans argument: self-check)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# ponytail: heuristiques mots-clés, pas un avocat — upgrade = audit LLM MiroFish
# (persona Legal_Officer, blueprint checklist) quand le gate statique passe.

SCAN_EXT = {".html", ".htm", ".md", ".markdown", ".txt", ".jsx", ".tsx",
            ".vue", ".svelte", ".php", ".js", ".ts", ".py"}
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__",
             "dist", "build", ".next", "vendor", "coverage"}
MAX_FILES = 3000

# (id, description, regex, critical)
COMMON = [
    ("legal_notice", "Mentions légales / legal notice / impressum",
     r"mentions?\s+l[ée]gales?|legal\s+notice|impressum", True),
    ("privacy", "Politique de confidentialité (RGPD art. 12-14)",
     r"politique\s+de\s+confidentialit|privacy\s+policy|protection\s+des\s+donn[ée]es", True),
    ("cookies", "Bandeau/politique cookies (consentement préalable)",
     r"cookie", True),
    ("host_info", "Hébergeur identifié (LCEN art. 6)",
     r"h[ée]berg(eur|ement|é)|hosted\s+by|hosting\s+provider", True),
    ("contact", "Contact éditeur (email)",
     r"[\w.+-]+@[\w-]+(\.[\w-]+)+", True),
    ("gdpr_rights", "Droits RGPD (accès, rectification, effacement…)",
     r"droit\s+d.{0,2}acc[èe]s|right\s+(of|to)\s+access|rectification|effacement|erasure", True),
    ("accessibility", "Accessibilité WCAG/RGAA/EAA mentionnée",
     r"accessibilit[ée]|accessibility|WCAG|RGAA", False),
]

BY_TYPE = {
    "website": [],
    "landing": [],
    "ecommerce": [
        ("cgv", "CGV accessibles avant commande",
         r"conditions\s+g[ée]n[ée]rales\s+de\s+vente|\bCGV\b|terms\s+of\s+sale", True),
        ("retract", "Droit de rétractation 14 jours (UE 2011/83)",
         r"r[ée]tractation|withdrawal", True),
        ("prix_ttc", "Prix TTC / taxes incluses",
         r"\bTTC\b|taxes?\s+incluses?|tax(es)?\s+included|TVA\s+incluse|VAT\s+included", True),
        ("mediation", "Médiation conso + plateforme ODR",
         r"m[ée]diat(eur|ion)|ec\.europa\.eu/consumers/odr", True),
        ("garanties", "Garanties légales (conformité 2 ans)",
         r"garantie\s+l[ée]gale|conformit[ée]|legal\s+guarantee", True),
        ("payment_btn", "Bouton « commande avec obligation de paiement »",
         r"obligation\s+de\s+paiement|obligation\s+to\s+pay", True),
    ],
    "saas": [
        ("cgu", "CGU / Terms of service",
         r"conditions\s+g[ée]n[ée]rales\s+d.{0,2}utilisation|\bCGU\b|terms\s+of\s+(service|use)", True),
        ("dpa", "DPA / sous-traitants (RGPD art. 28)",
         r"data\s+processing\s+agreement|sous-?traitan|subprocessor|\bDPA\b", False),
        ("delete_account", "Suppression de compte self-service",
         r"suppr\w*\s+\w{0,10}\s*compte|delete\s+\w{0,10}\s*account", False),
    ],
    "chatbot": [
        ("ai_disclosure", "Transparence IA (AI Act) : l'utilisateur sait que c'est une IA",
         r"assistant\s+(virtuel|IA)|intelligence\s+artificielle|\bAI\s+(assistant|chatbot)\b|powered\s+by\s+AI", True),
        ("ai_disclaimer", "Disclaimer : pas un conseil médical/juridique/financier",
         r"ne\s+constituent?\s+pas\s+un\s+(avis|conseil)|not\s+(legal|medical|financial)\s+advice", False),
    ],
    "email": [
        ("unsubscribe", "Lien de désinscription 1 clic (CAN-SPAM/RGPD/CASL)",
         r"d[ée]sinscri|d[ée]sabonn|unsubscribe|opt-?out", True),
        ("postal_addr", "Adresse postale physique de l'expéditeur (CAN-SPAM)",
         r"\b(rue|avenue|boulevard|street|st\.|ave\.|road)\b", False),
    ],
}

# (id, description, regex) — présence = violation bloquante
VIOLATIONS = [
    ("local_storage", "localStorage/sessionStorage interdits (règle forge n°4 + privacy)",
     r"localStorage|sessionStorage"),
    ("todo_legal", "Placeholder légal non rempli (TODO-LEGAL)",
     r"TODO-LEGAL"),
]


def _collect(root: Path) -> list[tuple[Path, str]]:
    corpus = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if len(corpus) >= MAX_FILES:
                return corpus
            p = Path(dirpath) / fn
            if p.suffix.lower() not in SCAN_EXT:
                continue
            try:
                corpus.append((p, p.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    return corpus


def legal_check(project_path: str | Path, product_type: str = "website") -> dict:
    """Retourne {grade, passed, missing, violations, deliver_ready}.

    deliver_ready=False => DELIVER BLOQUÉ (critique manquante ou violation).
    """
    root = Path(project_path)
    if not root.exists():
        return {"error": f"path not found: {root}", "deliver_ready": False}

    types = [t.strip().lower() for t in str(product_type).split(",") if t.strip()]
    checks, seen = list(COMMON), set()
    for t in types:
        checks += BY_TYPE.get(t, [])
    checks = [c for c in checks if not (c[0] in seen or seen.add(c[0]))]

    corpus = _collect(root)
    blob = "\n".join(t for _, t in corpus)

    passed, missing = [], []
    for cid, desc, pat, critical in checks:
        if re.search(pat, blob, re.IGNORECASE):
            passed.append(cid)
        else:
            missing.append({"id": cid, "desc": desc, "critical": critical})

    violations = []
    for vid, desc, pat in VIOLATIONS:
        hits = sorted({str(p.relative_to(root)) for p, t in corpus if re.search(pat, t)})
        if hits:
            violations.append({"id": vid, "desc": desc, "files": hits[:10]})

    crit_missing = [m for m in missing if m["critical"]]
    total_crit = sum(1 for c in checks if c[3]) or 1
    score = 100.0 * (total_crit - len(crit_missing)) / total_crit
    if violations:
        score = min(score, 50.0)
    grade = ("A" if score >= 100 and not missing else "B" if score >= 90
             else "C" if score >= 70 else "D" if score >= 50 else "F")

    return {
        "product_type": "+".join(types) or "website",
        "files_scanned": len(corpus),
        "grade": grade,
        "score": round(score, 1),
        "passed": passed,
        "missing": missing,
        "violations": violations,
        "deliver_ready": not crit_missing and not violations,
    }


def demo() -> None:
    """Self-check: un livrable conforme passe, un non conforme bloque."""
    import tempfile

    good = """
    <footer>Mentions légales — © Boutique Exemple SARL, capital 10 000 €.
    Hébergeur : OVH SAS, 2 rue Kellermann, 59100 Roubaix, +33 9 72 10 10 07.
    Contact : contact@boutique-exemple.fr — Accessibilité : conforme WCAG 2.1 AA.
    Politique de confidentialité : droit d'accès, de rectification, d'effacement,
    de portabilité et d'opposition (réclamation CNIL). Gestion des cookies :
    consentement préalable, refus en 1 clic.
    CGV — Conditions générales de vente : prix TTC, droit de rétractation de 14 jours,
    garantie légale de conformité de 2 ans. Bouton : commande avec obligation de paiement.
    Médiation de la consommation : CM2C — https://ec.europa.eu/consumers/odr</footer>
    """
    bad = "<h1>Hello</h1><script>localStorage.setItem('cart','x')</script>"

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "good").mkdir()
        (Path(tmp) / "bad").mkdir()
        (Path(tmp) / "good" / "index.html").write_text(good, encoding="utf-8")
        (Path(tmp) / "bad" / "index.html").write_text(bad, encoding="utf-8")

        r1 = legal_check(Path(tmp) / "good", "ecommerce")
        assert r1["deliver_ready"], f"good site should pass: {r1}"
        assert r1["grade"] in ("A", "B"), r1["grade"]

        r2 = legal_check(Path(tmp) / "bad", "website")
        assert not r2["deliver_ready"], "bad site must be blocked"
        assert any(v["id"] == "local_storage" for v in r2["violations"])
        assert any(m["id"] == "legal_notice" for m in r2["missing"])

    print("legal_compliance self-check OK (good=deliver_ready, bad=blocked)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        demo()
    else:
        result = legal_check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "website")
        print(json.dumps(result, indent=2, ensure_ascii=True))
        sys.exit(0 if result.get("deliver_ready") else 1)
