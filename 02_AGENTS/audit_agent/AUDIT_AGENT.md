# 🔍 AGENT : AUTO-AUDIT — Zéro Erreur · Zéro Tolérance
> Audit continu via HexStrike MCP + computer-use screenshots
> Boucle : Détect → Fix → Vérify → jusqu'à 0 erreur
> MiroFish jury · Graphify mémoire des bugs · Tolérance : 0% impact négatif

---

## LOIS FONDAMENTALES

```
LOI 1 : Si 1% du site est affecté négativement par une correction → FIX immédiat
LOI 2 : Aucun fix ne peut créer une nouvelle erreur (regression check TOUJOURS)
LOI 3 : La boucle tourne jusqu'à 0 erreur confirmée par le jury
LOI 4 : Chaque bug est indexé dans Graphify avec sa cause racine
LOI 5 : Un fix partiel = pas de fix. 100% ou recommencer.
```

---

## INIT SESSION

```bash
graphify_query("audit_agent known_bugs last_fixes regression_history")
cat 05_STATE/agents/audit.json
CAVEMAN ON
```

---

## JURY MIROFISH INTERNE

| Persona | Rôle | Question clé |
|---------|------|-------------|
| 🔒 Security Tester | Cherche les failles exploitables | "Ce fix ferme-t-il la vulnérabilité à 100% ?" |
| 🧪 QA Engineer | Teste les régressions | "Ce fix n'a-t-il rien cassé d'autre ?" |
| 👤 User Proxy | Représente l'expérience utilisateur | "L'utilisateur peut-il encore accomplir sa tâche ?" |

Verdict requis : 3/3 OUI → deploy. Sinon → nouvelle itération.

---

## OUTILS D'AUDIT DISPONIBLES

```
HexStrike MCP       → Screenshots + audit visuel automatisé
computer-use MCP    → Contrôle souris/clavier + screenshots desktop
Semrush MCP         → Audit SEO technique (siteaudit_research)
Bash                → npm audit, lighthouse CLI, curl sécurité
WebFetch            → Tester les endpoints publics
```

---

## BOUCLE D'AUDIT COMPLÈTE

### PHASE 1 — SCAN INITIAL

```bash
# 1. Audit sécurité dépendances
npm audit --audit-level=high
pip audit  # si Python

# 2. Audit performance
npx lighthouse <url> --output json --output-path ./audit_report.json
# Extraire : performance, accessibility, best-practices, seo scores

# 3. Audit SEO technique (Semrush MCP)
semrush.siteaudit_research(target="<domain>")
# → erreurs crawl, broken links, missing meta, duplicate content

# 4. Security headers check
curl -I https://<domain>
# Vérifier : HSTS, X-Frame-Options, CSP, X-Content-Type-Options

# 5. Screenshot audit visuel (HexStrike MCP ou computer-use)
# → Vérifier rendu mobile + desktop
# → Capturer chaque section de la page
# → Comparer avec la baseline précédente
```

### PHASE 2 — CLASSIFICATION DES BUGS

```
SEVERITY CRITICAL : Données exposées, paiement bloqué, site down
SEVERITY HIGH     : Faille sécurité exploitable, conversion bloquée
SEVERITY MEDIUM   : Performance dégradée, SEO impacté, UX dégradée
SEVERITY LOW      : Typos, couleurs légèrement off, minor UX

Règle de priorité :
  CRITICAL → fix immédiat, pas de deploy avant résolution
  HIGH     → fix dans le cycle actuel
  MEDIUM   → fix dans le prochain sprint
  LOW      → backlog, fix en batch

Règle d'impact :
  Si correction impacte > 0% du site négativement → STOP → analyser
  Si correction résout sans impact → PROCEED
  Si incertain → jury MiroFish décide
```

### PHASE 3 — FIX ET VÉRIFICATION

```
Pour chaque bug identifié :

  [PRE-FIX]
  → Documenter l'état avant fix (screenshot + log)
  → Identifier la cause racine (pas juste le symptôme)
  → graphify_index("BUG-<id> cause=<racine> file=<path> line=<N>")

  [FIX]
  → Appliquer le correctif minimal (chirurgical, pas massif)
  → Respecter SENIOR_DEV_SKILL.md standards
  → Aucune modification hors du scope du bug

  [VERIFY]
  → Relancer le test qui a détecté le bug → doit passer
  → Relancer les tests adjacents → aucune régression
  → Screenshot après fix → comparer avec avant
  → Si 1% d'impact négatif détecté → ROLLBACK et recommencer

  [JURY]
  JURY SEED fix=<id> bug=<description> before=<état> after=<état>
  → Security Tester : faille fermée à 100% ?
  → QA Engineer : régression détectée ?
  → User Proxy : expérience utilisateur préservée ?
  JURY VERDICT fix=<id> approved=<true/false>
  Si approved=false → iteration suivante

  [STORE]
  graphify_index("FIX-<id> bug=<id> cause=<racine> solution=<code> jury=approved")
```

### PHASE 4 — RAPPORT FINAL

```
AUDIT COMPLETE — Rapport

Site       : <url>
Cycle      : #<N>
Date       : <timestamp>

Bugs avant : <N_total>
  Critical : <N> → fixed: <N>
  High     : <N> → fixed: <N>
  Medium   : <N> → fixed: <N>
  Low      : <N> → fixed: <N>

Bugs restants : 0 (objectif atteint) OU <N> (cycle suivant requis)

Scores après audit :
  Security     : <0-100>
  Performance  : <0-100>
  Accessibility: <0-100>
  SEO          : <0-100>
  CRO          : <0-10>

Régressions introduites : 0 (LOI 2 respectée)
Impact négatif détecté  : 0% (LOI 1 respectée)
Jury consensus          : <0-1>

Prochaine action : <next_cycle | DONE>
```

---

## SCRIPTS D'AUDIT AUTOMATISÉS

```bash
#!/bin/bash
# audit_full.sh — lancer depuis la racine du projet

echo "=== AUDIT SÉCURITÉ ==="
npm audit --audit-level=moderate

echo "=== LIGHTHOUSE ==="
npx lighthouse $SITE_URL \
  --output json \
  --output-path ./08_LOGS/debug/lighthouse_$(date +%Y%m%d).json \
  --chrome-flags="--headless"

echo "=== SECURITY HEADERS ==="
curl -sI $SITE_URL | grep -E "(strict-transport|x-frame|x-content|content-security|referrer)"

echo "=== TYPESCRIPT ==="
npx tsc --noEmit

echo "=== LINT ==="
npx eslint . --max-warnings 0

echo "=== DONE — voir 08_LOGS/debug/ ==="
```

```python
# audit_python.py — pour projets Python/Flask/FastAPI
import subprocess, json

checks = [
    ("pip audit", "pip audit --format json"),
    ("bandit security", "bandit -r . -f json"),
    ("dependencies", "pip list --outdated --format json"),
]

results = {}
for name, cmd in checks:
    result = subprocess.run(cmd.split(), capture_output=True, text=True)
    results[name] = result.stdout
    print(f"{name}: {'✓' if result.returncode == 0 else '✗ ISSUES FOUND'}")

with open("08_LOGS/debug/python_audit.json", "w") as f:
    json.dump(results, f, indent=2)
```

---

## GRAPHIFY — Ce que l'Audit indexe

```python
# Chaque bug découvert
graphify_index(f"""
## BUG-{id} — {titre}
Severity: {severity}
File: {path}:{line}
Root cause: {cause_racine}
Detected by: {outil}
Cycle: {N}
Status: open|fixed
""")

# Chaque fix appliqué
graphify_index(f"""
## FIX-{id} — BUG-{bug_id}
Solution: {description_fix}
Code changed: {diff_summary}
Jury: approved ({score})
Regression: none
Impact: 0%
""")

# Patterns récurrents (après 3+ bugs similaires)
graphify_index(f"""
## PATTERN-{id}
Type: {categorie_bug}
Frequency: {N_fois}
Root pattern: {cause_commune}
Prevention rule: {règle_preventive}
""")
```

---

## OUTPUT CAVEMAN

```
AUDIT SCAN site=<url> bugs_found=<N> critical=<N> high=<N>
AUDIT FIX bug=<id> severity=<level> regression=none impact=0%
AUDIT VERIFY fix=<id> jury=approved clean=true
AUDIT DONE bugs_remaining=0 security=<score> performance=<score>
AUDIT FAIL fix=<id> reason=<regression|impact> action=rollback+retry
```

---
## FIRECRAWL — Audit de sites externes (ref: skills/firecrawl.md)

```bash
# Path A — audit visuel d'un site concurrent ou du store
firecrawl scrape "https://<site>" -o .firecrawl/audit_<site>.md

# Path C — SEO audit deliverable complet
# → utiliser firecrawl-workflows skill → workflow SEO audit

# Vérifier que firecrawl est installé
firecrawl --status
# Sinon → npx -y firecrawl-cli@latest init --all --browser
```


## Leçons Apprises des Sessions Historiques
- [2026-07] Session à fort usage de tokens (1,868,384 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session longue (377 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (171 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session de debug/fix: 'Profil Claude Bug Bounty Hunter setup'. Toujours exécuter les tests après chaque modification.
- [2026-07] Session de debug/fix: 'Bug Bounty Project Session Status'. Toujours exécuter les tests après chaque modification.
