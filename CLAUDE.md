# CLAUDE.md — Super Agent Forge
> Lu automatiquement à chaque session. CORE uniquement (toujours actif).
> Détail situationnel/référence → **FORGE_REFERENCE.md** (chargé à la demande, cf. index bas de page).

## 🎯 RÈGLE N°0 — TOUT MESSAGE USER = TÂCHE FORGE
```
CHAQUE message du user est traité comme une TÂCHE pour la Forge, peu importe ce
qui est demandé (question, ordre, remarque, debug, idée…). La Forge est ACTIVE
pour TOUTES les demandes — jamais en veille.

Flux par défaut pour tout message :
  1. Le message = current_task → orchestrateur (forge_orchestrate).
  2. Décomposition en micro-tasks → 1 expert dédié / micro-task (forge_team).
  3. Optimisation tokens SYSTÉMATIQUE et CUMULÉE (ne jamais en sauter une) :
     - RTK (Rust Token Killer) sur TOUTE sortie de commande (hook global + tools.rtk.rtk_run)
     - context-mode (ctx_execute/ctx_search) pour tout output > 20 lignes
     - fingerprint/semantic cache (forge_fingerprint), MimoBatcher, TOKEN ESTIMATE avant/après
  4. Claude = moteur LLM par défaut (cf. LLM PRIORITY).
Exception : une demande triviale conversationnelle peut être répondue directement, mais
l'optimisation tokens (RTK + context-mode) reste TOUJOURS active.
```

## 🚨 RÈGLE ANTI-DÉRIVE — Claude ne génère PAS de contenu long
```
INTERDIT dans le contexte Claude :
  - Écrire un ebook, article, ou tout texte > 200 mots directement
  - Générer des templates, scripts, ou blocs de code > 50 lignes directement
  - Rédiger des séquences emails, posts, landing pages directement

OBLIGATOIRE à la place :
  1. Afficher TOKEN ESTIMATE avant toute tâche
  2. Appeler forge_call(prompt) ou run_forge.py (MiMo payant)
  3. RTK (https://github.com/rtk-ai/rtk) compresse les sorties commandes
  4. Claude lit et valide seulement le résultat (50-100 tokens max)

Règle du pouce : si ça prend plus de 3 messages, ça doit passer par la Forge.
```

## ⚡ RÈGLE ABSOLUE — TOKEN BUDGET (appliquée à CHAQUE tâche)
```
AVANT toute exécution → afficher le TOKEN ESTIMATE :
  from forge_agents.token_tracker import get_tracker
  t = get_tracker(); t.estimate_budget(task); print(t.render_estimate_table())

APRÈS exécution → afficher le TOKEN ACTUAL + POST-MORTEM :
  print(t.render_actual_table())
  for r in t.generate_recommendations(): print(r)
  print(f"EFFICIENCY SCORE: {t.efficiency_score()}/100")
  t.generate_final_report()   # → 08_LOGS/tokens/

Automatique dans run_forge.py. Sessions Claude interactives : get_tracker() manuel.
```

## 🔑 LLM PRIORITY — CLAUDE = ABONNEMENT, JAMAIS d'API AU TOKEN
```
Moteur de raisonnement/orchestration = Claude via l'ABONNEMENT (cette session
Claude Code EST l'orchestrateur). PAS d'API Anthropic pay-as-you-go — aucune clé
ANTHROPIC_API_KEY, jamais de facturation au token, sous aucun prétexte.

Appels LLM automatisés (forge_call) → MiMo (payant, 17€/mois) :
  MiMo seul — plus de cascade gratuite (Gemini/Groq/Cerebras supprimés).
  Génération lourde = MiMo (règle ANTI-DÉRIVE). Claude Code (abonnement) =
  raisonnement + validation seuls.
Détail routeur/tiers → FORGE_REFERENCE.md#LLM-Router.
```

## ⚡ RTK = RUST TOKEN KILLER (compression, PAS un LLM)
```
RTK (https://www.rtk-ai.app | rtk-ai/rtk) N'EST PAS un routeur/proxy LLM.
C'est un binaire Rust qui COMPRESSE la sortie des commandes (ls/cat/grep/git/
tests/docker…) de 60-90 % AVANT qu'elle n'entre dans le contexte LLM.
Binaire : C:/Users/Enzo/.cargo/bin/rtk.exe (source vendored 00_CORE/rtk).
Wrapper Python : 00_CORE/tools/rtk.py → rtk_run(cmd). Hook global Bash actif.
Interne forge : toute commande dont la sortie nourrit un LLM passe par rtk_run().
Scraping forge : PAS firecrawl-scrape → scraping_hook.py → scrapling_connector.py.
Détail intégration/hooks → FORGE_REFERENCE.md#RTK-détail.
```

## 🧱 RÈGLE ARCHI — MICROSERVICES PAR DÉFAUT (jamais monolithe)
```
TOUTE création de logiciel/code par la Forge vise une archi MICROSERVICES :
services découplés, 1 responsabilité/service, contrats API explicites (REST/gRPC/events),
app stateless (état PG+Redis) → scalable horizontal, chaque service dockerisable +
déployable indépendamment (Coolify) + observable. Découpage par bounded context métier.
Exception YAGNI (ponytail) : un vrai script/outil jetable n'a pas à être éclaté.
Aligné blueprint 5 couches (FORGE_REFERENCE.md#BLUEPRINT-SaaS).
```

## DOX — AGENTS.md hierarchy (agent0ai/dox)
```
Avant toute édition : lire AGENTS.md (racine) puis le AGENTS.md du/des
dossier(s) cible(s) (chaîne root→target). Chaque dossier majeur a son
AGENTS.md (Purpose/Ownership/Local Contracts/Work Guidance/Verification).
Après toute édition significative : mettre à jour le AGENTS.md le plus
proche (et parents/enfants affectés). Index complet → AGENTS.md "Child DOX Index".
```

## Règle d'édition — SEE obligatoire
```
TOUTE modification de code passe par le SEE (Semantic Edit Engine).
NE JAMAIS réécrire un fichier entier ou une fonction entière quand
seulement quelques mots changent. Utiliser :

  from tools.see_edit import apply_minimal_edit
  res = apply_minimal_edit("fichier.py", target_name="symbole",
                           modified_code=code_cible, dry_run=False)

Ou en CLI :
  python 00_CORE/tools/see_edit.py <fichier> --target <symbole> --new <fichier_cible> [--apply]

Le SEE dérive un plan de coût minimal (Replace/InsertAfter/DeleteRange),
applique transactionnellement (rollback si ça ne compile plus), et logue
les métriques. Réécrire directement = suppression de lignes + perte de contexte.
```

## Règle absolue n°1
Jamais de fichier brut dans le contexte.
Toujours : scrape → graphify_index() → graphify_query() → agent.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **.claude** (83150 symbols, 111561 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/.claude/context` | Codebase overview, check index freshness |
| `gitnexus://repo/.claude/clusters` | All functional areas |
| `gitnexus://repo/.claude/processes` | All execution flows |
| `gitnexus://repo/.claude/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## 🎯 OPTIMISATIONS FABLE 5 (CORE BEHAVIOR)
```
Ces règles héritent de l'alignement de Claude Mythos/Fable 5 et s'appliquent GLOBABLEMENT à tout agent de La Forge.

1. ARTIFACTS & STANDALONE OUTPUTS
   - Pour tout output >10 lignes (code, rapport, UI, etc.), CRÉER UN FICHIER. Ne jamais cracher de longs blocs dans le chat.
   - Les outputs longs (>100 lignes) doivent être générés itérativement.
   - Toujours COMPRESSER la réponse verbale : fournir le chemin du fichier sans post-ambules interminables pour minimiser l'usage des tokens.

2. COMPÉTENCES (SKILLS) AVANT L'ACTION
   - Avant de générer du code/document, l'agent DOIT toujours lire les `SKILL.md` associés à la tâche s'ils existent, afin de capter les contraintes sans polluer le prompt.

3. RECHERCHE & COPYRIGHT (Agents Scrapers/Researchers)
   - Limite STRICTE de 1 citation/source max (15 mots max). C'est une VIOLATION SÉVÈRE de dépasser cela.
   - Toujours reformuler.
   - Prioriser la recherche web pour les entités ou statuts sujets à des changements récents, ne pas se baser uniquement sur la mémoire interne.

4. PERSISTANCE DES DONNÉES & MCP
   - Interdiction d'utiliser `localStorage`/`sessionStorage` dans les applications web générées (cela ne marche pas dans les environnements isolés IA).
   - Utiliser systématiquement l'index GitNexus ou la persistance standard de La Forge (SQLite, Graphify) à la place.
   - Être proactif : si un outil/application MCP est disponible pour une tâche, l'invoquer ou le suggérer directement au lieu de faire une recherche web générique.

5. DÉLÉGATION OPEN SOURCE (DO NOT INVENT)
   - "Ne plus penser, juste appeler." Avant de raisonner pour générer une logique complexe ou un algorithme sur-mesure, l'agent DOIT rechercher de manière proactive un outil tiers, un dépôt GitHub, ou un package existant qui fait déjà le travail.
   - Privilégier la recherche standard sur le web/GitHub pour repérer ces outils afin d'économiser les tokens.
   - Une fois l'outil trouvé, l'encapsuler dans un **micro-script réutilisable** appelable à volonté (bibliothèque de wrappers plutôt que réinventer la roue).
   - OBLIGATOIRE : dès qu'un nouveau script est créé ou un outil externe encapsulé, lancer `npx gitnexus analyze` pour mettre l'index à jour.

6. PERSONNALISATION DES CHATBOTS CLIENTS
   - Persona, tonalité et réponses pré-programmées calibrés pour le client (ex. trilingue pour La Charlotte Royale, vocabulaire du fournil).
   - Le chatbot parle automatiquement la langue sélectionnée (accueil, placeholders, boutons d'aide, détection de mots-clés adaptés à la langue active).

7. CARTOGRAPHIE INTERACTIVE (OPENSTREETMAP)
   - Si un site affiche l'adresse/coordonnées d'un commerce → carte interactive OpenStreetMap (Leaflet.js, tuiles CartoDB Voyager de préférence).
```

---

## 📂 CHARGEMENT À LA DEMANDE — FORGE_REFERENCE.md
`FORGE_REFERENCE.md` n'est PAS auto-chargé. **Lis-le (section pertinente) DÈS qu'un trigger ci-dessous se déclenche.**

| Trigger | Lire dans FORGE_REFERENCE.md |
|---|---|
| Construire chatbot IA / archi SaaS AI | `BLUEPRINT SaaS AI Chatbot` |
| Construire agent / RAG / API | `BLUEPRINT AI Agent Best Practices` |
| Créer site/landing/ecommerce/SaaS/bot/email/workflow | `RÈGLE LÉGALE` |
| Démarrer / reprendre une session | `INIT SESSION` · `Reprendre une session` |
| Coder/débugger le core forge (mémoire, graph, agents) | `Mémoire` · `V6 NOMENCLATURE` · `LangGraph Meta-Agent` |
| Choisir modèle / router LLM / tracer | `LLM Router` · `LLM BACKEND MiMo` · `OBSERVABILITÉ LangSmith` |
| Setup initial clés/env | `Setup clés API` · `nopeek` |
| Tâche OSINT / bug bounty / pentest | `Bug Bounty & OSINT` · `OSINT Arsenal` |
| Projet e-commerce (600€/mois) | `ORCHESTRATEUR E-COMMERCE` |
| Portfolio → MVP livrable / produit prod-ready | `PORTFOLIO → MVP FACTORY` · `STACK PRODUCTION-READY` · `Herald` |
| Dataset (download/ingest) | `DATASETS` |
| Optimiser un prompt | `PROMPT OPTIMIZER` |
| Un MCP manque | `MCP MANQUANT` |
| Concevoir l'UI d'un site/SaaS | `UI & DESIGN` |
| Besoin API/donnée externe | `APIs PUBLIQUES` |
| Fin de session (learnings) | `reflect` · `ccrecall` |
| Audit sécurité / score livraison | `Herald` |
| Urgence (graph/sqlite/budget) | `Urgences` |

### ⛔ GATES BLOQUANTS (réflexe même avant de charger le détail)
- **Créer un site/produit/email** → `legal_check(path, product_type)["deliver_ready"]` doit être True. False = **PAS DELIVER**. (détail → RÈGLE LÉGALE)
- **Agent / RAG livré** → interdit sans re-ranking + hallucination guard + grounding + 3 guards + eval judge. (détail → BLUEPRINT AI Agent)
- **Livrer un MVP** → Herald grade **≥ B**, 0 issue CRITICAL, score sécu ≥ 70. Grade < C = bloqué. (détail → Herald)
- **Action fort enjeu (paiement/booking/envoi externe/suppression)** → gate humain HITL approve/reject. Pas d'auto-confirmation d'argent.
- **Données légales client manquantes (SIRET/hébergeur/médiateur)** → DEMANDER, jamais inventer. Placeholder TODO-LEGAL = blocage.
