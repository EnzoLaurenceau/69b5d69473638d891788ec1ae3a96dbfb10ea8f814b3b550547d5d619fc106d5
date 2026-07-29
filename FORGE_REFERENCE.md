# FORGE_REFERENCE.md — chargé À LA DEMANDE (jamais auto-load)
> Ce fichier n'est PAS lu automatiquement. Claude le lit UNIQUEMENT quand un
> trigger de l'index CLAUDE.md se déclenche. Contenu = règles complètes, verbatim.
> Naviguer par ancre : chercher le titre `##` correspondant.

## Index des triggers
| Trigger (ce que tu fais) | Section à lire ici |
|---|---|
| Construire chatbot IA / archi SaaS AI | `BLUEPRINT SaaS AI Chatbot` |
| Construire agent / RAG / API | `BLUEPRINT AI Agent Best Practices` |
| Créer site/landing/ecommerce/SaaS/bot/email/workflow | `RÈGLE LÉGALE` |
| Démarrer / reprendre une session | `INIT SESSION` · `Reprendre une session` |
| Écrire/débugger du code forge (mémoire, graph, agents) | `Mémoire` · `V6 NOMENCLATURE` · `LangGraph Meta-Agent` |
| Choisir un modèle / router LLM | `LLM Router` · `LLM BACKEND MiMo` · `OBSERVABILITÉ LangSmith` |
| Setup initial clés/env | `Setup clés API` · `nopeek` |
| Tâche OSINT / bug bounty / pentest | `Bug Bounty & OSINT` · `OSINT Arsenal` |
| Projet e-commerce (600€/mois) | `ORCHESTRATEUR E-COMMERCE` |
| Transformer portfolio → MVP livrable | `PORTFOLIO → MVP FACTORY` · `Herald` |
| Livrer un produit prod-ready | `STACK PRODUCTION-READY` · `Herald` |
| Télécharger/ingérer un dataset | `DATASETS` |
| Optimiser un prompt | `PROMPT OPTIMIZER` |
| Un MCP manque | `MCP MANQUANT` |
| Concevoir l'UI d'un site/SaaS | `UI & DESIGN` |
| Besoin d'une API/donnée externe | `APIs PUBLIQUES` |
| Fin de session (capturer learnings) | `reflect` · `ccrecall` |
| Audit sécurité / score livraison | `Herald` |
| Urgence (graph/sqlite/budget) | `Urgences` |
| Comprendre les plugins toolkit | `claude-code-toolkit` · `deslop` |

---

## BLUEPRINT SaaS AI Chatbot
```
TOUT chatbot IA + TOUTE archi SaaS AI générés par la Forge suivent le blueprint 5 couches :
  00_CORE/blueprints/saas_ai_chatbot.md
Couches : Présentation/Intégration → API Gateway+RateLimit → Microservices/Orchestration(LangGraph)
          → Data&AI (turbovec/Qdrant + forge_db PG+Redis + forge_llm router) → Infra/Observabilité(Coolify).
Non négociable : multi-tenant (tenant_id isolé DB+vector), webhook async+secret, clients lazy+once-guard,
                 dégradation gracieuse, app stateless (state PG+Redis) → scalable horizontal, pas de localStorage.
Réf vivante : tg-bot-workflow-v2/. Checklist conformité avant DELIVER dans le blueprint.
Compléments : 00_CORE/blueprints/nebius_cookbook_patterns.md (production-shaped + inférence Nebius),
              00_CORE/blueprints/agentic_production_blueprint.md (5 couches Artiquare + HITL).
RÈGLE HITL : toute action à fort enjeu (paiement, booking, envoi externe, suppression) DOIT
             passer par un gate humain (approve/reject). Pas d'auto-confirmation d'argent.
```

## BLUEPRINT AI Agent Best Practices (RAG/agent/API/eval)
```
TOUT système agent / RAG / API généré par la Forge applique :
  00_CORE/blueprints/ai_agent_best_practices.md
Actif dès qu'on construit un agent, un RAG, ou une API — même en session Claude simple.
Non négociable avant DELIVER :
  RAG   → re-ranking + hybrid search + hallucination guard + grounding (citer sources) ; HyDE si query ambiguë.
  Eval  → LLM-as-a-Judge ancré (faithfulness/correctness/relevance/completeness/safety), tier FREE, complète MiroFish/Herald.
  Sécu  → 3 couches guard (input → content → output) par-dessus neuro_symbolic_guard.
  API   → SSE défaut pour streaming LLM ; rate-limit + versioning + auth JWT + idempotency + pagination + cache ETag.
  Obs   → tracing par étape (LangSmith) + cost_tracker + semantic cache avant appel LLM.
Gate : agent/RAG livré sans re-ranking OU hallucination guard OU grounding OU 3 guards OU eval judge → PAS DELIVER.
```

## RÈGLE LÉGALE — CONFORMITÉ JURIDIQUE MAXIMALE (toute création, tout pays)
```
TOUTE création forge (site, landing, e-commerce, SaaS, bot, email, workflow) applique :
  00_CORE/blueprints/legal_compliance.md
Principe : PLUS STRICT DÉNOMINATEUR COMMUN — UE (RGPD/ePrivacy/DSA/CRD+Omnibus/EAA/AI Act)
+ FR (LCEN/CNIL/code conso) + US (CCPA/CAN-SPAM/COPPA/ADA) + CA (PIPEDA/CASL) + UK.
Juridiction cliente inconnue → baseline complet, sans exception.
Concret : footer légal complet sur CHAQUE page (éditeur, SIRET, hébergeur, contact),
mentions légales + privacy + cookies (consentement AVANT dépôt) ; e-commerce → CGV,
rétractation 14 j, prix TTC, médiation+ODR, « obligation de paiement » ; SaaS → CGU+DPA ;
chatbot → transparence IA (AI Act) + disclaimers ; emails → opt-in exprès + désinscription
1 clic + adresse postale.
GATE (bloquant, comme Herald < C) :
  from forge_agents.legal_compliance import legal_check
  legal_check(path, product_type)["deliver_ready"] == False → PAS de DELIVER.
Séquence MVP : S6.5 LEGAL CHECK (après S6 RE-AUDIT, avant S7 MIROFISH).
  → state['legal_grade'] injecté au jury (persona Legal_Officer) ; grade < B → -2.0 pts.
Données légales client (SIRET, hébergeur, médiateur…) manquantes → DEMANDER au user,
ne JAMAIS inventer ; placeholder TODO-LEGAL restant = blocage automatique.
⚠️ Baseline maximale ≠ immunité : le risque juridique zéro n'existe pas. Fort enjeu
(santé, finance, mineurs, données sensibles, professions réglementées) → validation
avocat humaine obligatoire avant prod.
```

## OBSERVABILITÉ LLM — LangSmith (smith.langchain.com)
```
forge_call() est tracé via @traced (00_CORE/forge_agents/forge_observability.py) →
TOUT appel LLM (tous providers/tiers) + auto-trace LangGraph. Activer : .env
LANGSMITH_TRACING=true + LANGSMITH_API_KEY=lsv2_... (Settings→API Keys). No-op si off.
⚠️ tracing logge prompts+réponses au cloud → OFF si jailbreak/prompts sensibles.
```

## LLM BACKEND — MiMo v2.5-pro interne (round-up 1K → BATCH)
```
MiMo (00_CORE/forge_agents/forge_mimo.py) = backend interne prioritaire de la
cascade FREE si MIMO_API_KEY présente. Endpoint OpenAI-compat .../v1, modèle EXACT
= mimo-v2.5-pro. Facturation ROUND-UP au bloc 1000 : chaque appel arrondi au
millier supérieur. RÈGLE : pour N petites tâches répétées, utiliser
forge_mimo.MimoBatcher (coalesce N prompts en 1 appel numéroté ###N###) → 1 round-up
au lieu de N. Ne JAMAIS spammer des micro-appels MiMo isolés.
```

## INIT SESSION (L0 — toujours en premier)
```bash
# 0. BOOTSTRAP AUTONOME — toute IA appliquant ce profil DOIT lancer ceci en premier.
#    Active la stack seule : démarre le daemon Docker si besoin, lève PG+Redis,
#    applique le schéma, installe les deps manquantes, rejoue le WAL.
#    Idempotent. Si Docker absent/indispo → bascule MODE SECOURS (SQLite) sans bloquer.
#    L'utilisateur n'a RIEN à lancer manuellement.
python run_forge.py --bootstrap
python run_forge.py --db-status        # redis/postgres up|down + WAL en attente

# 1. Charger l'état
cat 05_STATE/checkpoint.json

# 2. Charger le contexte graphify
# graphify query "last_session findings_pending next_focus"

# 3. CAVEMAN ON — tous les échanges internes en caveman

# 4. LangGraph — vérifier que le graph est opérationnel
#    python run_forge.py --status        # affiche niveau/cycle/findings
#    python run_forge.py --resume        # reprendre tâche interrompue
#    python run_forge.py --task "..."    # lancer nouvelle tâche
```

## Mémoire — store unifié PG+Redis (optiforge)
```
Primaire : PostgreSQL(pgvector) + Redis  →  00_CORE/forge_agents/forge_db.py (get_db)
Secours  : LangGraph SQLite + graph.json + gitnexus (warm standby, dual-write + WAL)
Bootstrap: python run_forge.py --bootstrap   (ou scripts/forge_bootstrap.py)
Migration: python run_forge.py --migrate     (legacy → PG+Redis, archive 09_ARCHIVE/)
Routage  : Cervelet/Token-ID résout en réflexe SANS LangGraph (route_request → sinon ESCALATE)
Infra    : docker compose -f 00_CORE/db/docker-compose.yml up -d
```

## V6 NOMENCLATURE — noms concept (spec) → fichiers réels
```
Les specs (optiforge.md / UPGRADE V6.md) utilisent des noms ≠ du code. Un Claude
à froid (CLAUDE.md + index GitNexus) les voit comme "inconnus". Carte :
  BigSet  → forge_agents/forge_experience_db.py  (Experience/WorkflowScore/ComponentHealth
            → 05_STATE/experience_db.json). "BigSet" n'existe QUE dans les specs, pas le code.
  Hermes  → modèle nousresearch/hermes-3-llama-3.1-405b:free dans forge_llm.py
            (tiers claude_opus/sonnet/security) — PAS un module.
  Mimo    → mimo_token_tracker.py + scripts/pipeline_runner_mimo.py (métriques run/token).
  V6 batch (UNTRACKED, hors index) : forge_experience_db, forge_self_heal, forge_visualizer,
    forge_event_bus, forge_execution_logger, forge_kernel, forge_lazy, forge_meta,
    forge_mcp_pruner, forge_shared_brain, forge_system_registry, forge_no_mistakes,
    forge_dashboard.html. → committer + `node .gitnexus/run.cjs analyze` pour les rendre visibles.
```

## LangGraph — Meta-Agent Factory (Architecture Dynamique)
```
Package  : 00_CORE/forge_agents/  (PAS 00_CORE/langgraph/ — ce package n'existe pas)
Concept  : La Forge ne possède PLUS de rôles statiques. L'orchestrateur reçoit une tâche, 
           décompose en sous-tâches, et génère dynamiquement l'expert parfait (Prompt + Nom)
           à la volée (ex: Senior_Data_Scientist, Stripe_Integrator) avant de l'exécuter.
Modules  :
  forge_state.py           → ForgeState (TypedDict partagé entre tous les nœuds)
  forge_graph.py           → StateGraph complet (orchestrator → dynamic_agent → auto_complexification)
  agent_nodes.py           → 2 nœuds métier : orchestrator_node et dynamic_agent_node
  mirofish_subgraph.py     → Jury MiroFish comme sous-graphe LangGraph (évaluation du code)
  auto_complexification.py → Nœud de leveling automatique (L1→L4)
  graphify_checkpointer.py → Bridge Graphify ↔ LangGraph (CLI + fallback JSON)
  __init__.py              → Exports propres du package

CLI      : python run_forge.py --task <tâche> [--cycles N] [--session ID]
Persist  : SQLite → 04_GRAPHIFY/forge_checkpoints.db
           JSON   → 05_STATE/checkpoint.json (lisible par Claude)
```

## Structure de la forge
Voir FORGE.md pour l'arborescence complète.

## Reprendre une session interrompue
```bash
cat 05_STATE/checkpoint.json          # niveau, cycle, règles
cat 08_LOGS/cycles/cycle-XXX.log      # dernier log
python run_forge.py --status          # résumé visuel
python run_forge.py --resume          # reprendre depuis checkpoint LangGraph
# graphify query "session_interrupted pending_tasks"
```

## Urgences
- Graph corrompu → `graphify . --update --mode deep`
- Jury indisponible → CRITIC double pass (voir 03_JURY/config.json)
- Budget épuisé → ORCH EMERGENCY_STOP → sauvegarder dans 06_FINDINGS/pending/
- SQLite corrompu → supprimer `04_GRAPHIFY/forge_checkpoints.db`, relancer avec `--no-sqlite`

## ORCHESTRATEUR E-COMMERCE
Voir `01_ORCHESTRATOR/ECOM_ORCHESTRATOR.md`
Quota cible : 600€/mois | Shopify + Semrush MCPs
Démarrer par : BOOT CHECK → MARKET SCAN → PRODUCT HUNT → BUILD → LAUNCH

## LLM Router — Hiérarchie de coût
```
Fichier : 00_CORE/forge_agents/forge_llm.py
⚠️ PAS d'API Anthropic au token. Les tiers "Claude" ci-dessous = via l'ABONNEMENT
   (Claude Code orchestrateur), pas des appels forge_call automatisés. Les appels
   automatisés restent tier FREE (Nebius/Gemini/Groq/Cerebras/MiMo).

TIER 0 — GRATUIT / TRÈS BON MARCHÉ (priorité)
  Nebius AI Studio  → clé NEBIUS_API_KEY (inférence OpenAI-compat cheap → marges produits vendables)
  Gemini 2.5 Flash  → clé GOOGLE_AI_STUDIO_KEY dans .env
  Groq Llama 4      → clé GROQ_API_KEY dans .env (console.groq.com)
  Cerebras Llama 3.3→ clé CEREBRAS_API_KEY dans .env (cloud.cerebras.ai)
  → Usages : scoring, résumé, formatage, extraction, classification, inférence produit
  → Patterns prod (guardrails/observability/streaming) : 00_CORE/blueprints/nebius_cookbook_patterns.md

TIER 1 — Claude Haiku 4.5
  → Usages : génération d'emails, posts, templates

TIER 2 — Claude Sonnet 4.5
  → Usages : market scan, research, build, close

TIER 3 — Claude Opus 4.6 + extended thinking
  → Usages : orchestration, critique, jury final, audit

API dans le code :
  from forge_agents.forge_llm import forge_call, forge_score, LLMTier
  result = forge_call("...", tier=LLMTier.FREE)       # gratuit
  result = forge_call("...", task_type="market_scan") # auto-routing
  score  = forge_score("output text", "critères")     # 0.0–10.0
```

## Setup clés API (à faire une fois)
```bash
# 1. Copier .env.example → .env et remplir (tier FREE uniquement — PAS d'API Anthropic) :
#    GROQ_API_KEY       → console.groq.com (gratuit, 30M tokens/jour)
#    CEREBRAS_API_KEY   → cloud.cerebras.ai (gratuit, ultra-rapide)
#    GOOGLE_AI_STUDIO_KEY → déjà remplie dans .env
#    MIMO_API_KEY       → backend interne (cascade FREE)

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Lancer la forge
python run_forge.py --task "market_scan niche IA créateurs"
```

## Outils évalués et décisions
```
mem0        → NON maintenant. Graphify suffit pour les findings.
              Réévaluer en L3 si mémoire sémantique cross-sessions requise.

GitNexus    → OPTIONNEL. Indexe le codebase de la forge (MCP 16 outils).
              Installer si les agents font du code-heavy refactoring.
              npx gitnexus analyze (depuis .claude/)

freellmapi  → CONCEPT RETENU, approche différente.
              On utilise les APIs gratuites directement (Gemini/Groq/Cerebras)
              via forge_llm.py — plus simple que le proxy Node.js local.
```

## OpenViking — Couche mémoire sémantique
```
Fichier : 00_CORE/forge_agents/openviking.py

OpenViking RÉCUPÈRE, Graphify STOCKE. Les deux travaillent ensemble.
  graph.json ← graphify_index()       (écriture par les agents)
  VikingContext ← get_viking().retrieve_context()  (lecture avant chaque LLM)

Stratégies de scoring :
  keyword_score (50%) + recency (30%) + task_affinity (20%)
  Filtre KILL_BELOW=4.5 — exclut les noeuds de mauvaise qualité

Injecté automatiquement dans forge_call() si use_openviking=True.
Dans agent_nodes, _base_init() combine les deux :
  [Graphify] texte brut des règles/expériences passées
  [OpenViking] top-5 noeuds les plus pertinents
  [Findings] résumé des findings confirmés
```

## claude-code-toolkit — Intégrations actives
```
Source : github.com/spences10/claude-code-toolkit
Install : /plugin marketplace add spences10/claude-code-toolkit

Plugins retenus et leur rôle dans la Forge :

┌─────────────────────┬────────────────────────────────────────────────────────┐
│ Plugin/Skill        │ Rôle dans la Forge                                     │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ analytics/ccrecall  │ Sync transcripts Claude → SQLite                       │
│                     │ Complète token_tracker.py avec historique sessions      │
│                     │ npx ccrecall sync → 08_LOGS/ccrecall.db                │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ toolkit-skills/     │ Déclenché APRÈS chaque session forge                   │
│ reflect             │ Extrait les learnings → indexe dans Graphify           │
│                     │ Remplace la saisie manuelle de findings                │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ devops-skills/      │ Critère MiroFish supplémentaire :                      │
│ deslop              │ "Est-ce que cet output sent l'AI-slop ?"               │
│                     │ Pénalité -1.5 pts si patterns détectés                 │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ mcp-essentials/     │ Remplace Semrush (payant) pour MARKET agent            │
│ mcp-omnisearch      │ Tavily + Kagi + GitHub + Perplexity unifiés            │
│                     │ Ajouter clé dans .env : TAVILY_API_KEY                 │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ claude-workflow/    │ Pattern pour les agents BUILDER et MARKET :            │
│ structured-rpi      │ Research → Plan → Implement avec phase gates           │
│                     │ Chaque étape = checkpoint Graphify                     │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ nopeek              │ URGENT : sécurise les clés API dans .env               │
│                     │ npx nopeek init → wraps bash output                    │
│                     │ Hook PreToolUse → redact secrets automatiquement       │
└─────────────────────┴────────────────────────────────────────────────────────┘

Plugins NON retenus (hors scope Forge) :
  dev-environment  → terminal/worktree (setup perso, pas forge)
  dev-practices/tdd → tests unitaires (pas prioritaire)
  ci-debug-workflow → CI/CD (pas de pipeline forge actuellement)
```

## RTK — Compression output terminal (REMPLACE chop, actif) [détail]
```
Binaire : C:/Users/Enzo/.cargo/bin/rtk.exe (rtk 0.42.2) — source vendored 00_CORE/rtk
          build : cargo build --release --manifest-path 00_CORE/rtk/Cargo.toml
Économie : 60-90% de tokens sur les outputs CLI (git, docker, npm, pytest, kubectl…)
           mesuré : `git status` 785 → 268 chars (-66%). Stats : `rtk gain`.

Intégration : PreToolUse hook Bash dans ~/.claude/settings.json
  → wrapper ~/.claude/hooks/pretooluse-bash.ps1 (chaîne context-mode + RTK)
  → `rtk hook claude` réécrit chaque commande Bash en "rtk <cmd>" avant exécution
  → chop RETIRÉ de la chaîne (RTK fait le même job, en mieux/plus rapide).

Note : Bash PreToolUse retiré des plugins context-mode (les deux hooks.json)
  pour éviter le bug CC #15897 (duplicate PreToolUse outputs). Le wrapper
  appelle pretooluse.mjs de context-mode en premier, puis `rtk hook claude`.

Interne forge (Python) : 00_CORE/tools/rtk.py → rtk_run(cmd) pour toute commande
  dont la sortie nourrit un LLM. RTK s'empile AVEC context-mode + fingerprint cache
  (ne remplace aucune autre optim tokens — cf. RÈGLE N°0).

Scraping forge : NE PAS utiliser le skill firecrawl-scrape.
  Utiliser scraping_hook.py → scrapling_connector.py (Scrapling + crawl4ai fallback).
```

## Bug Bounty & OSINT — Outils intégrés
```
┌─────────────────────┬────────────────────────────────────────────────────────┐
│ Outil               │ Rôle                                                   │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ MoneyScope          │ Scope discovery : agrège les scopes payants de         │
│ (WSL bash)          │ H1/Bugcrowd/YesWeHack/Intigriti/Federacy/Hackenproof   │
│                     │ Wrapper : 00_CORE/tools/research/money_scope.py        │
│                     │ Usage : get_scope("a") → domains.txt + tlds.txt        │
│                     │ Dépendances WSL : jq + haktldextract (go)              │
├─────────────────────┼────────────────────────────────────────────────────────┤
│ OpenOSINT           │ Agent OSINT AI-powered (18 outils) :                   │
│ (pip + MCP)         │ email · username · breach · IP · WHOIS · subdomain     │
│                     │ Shodan · VirusTotal · Censys · AbuseIPDB · GitHub      │
│                     │ DNS · phone · paste · dorks · URL scraping             │
│                     │ MCP enregistré → 18 outils dispo nativement en session │
│                     │ Wrapper : 00_CORE/tools/research/open_osint.py         │
│                     │ CLI direct : openosint email foo@bar.com --json        │
│                     │ Web UI    : openosint web (localhost:8080)              │
│                     │ Clés API  : SHODAN_API_KEY, VIRUSTOTAL_API_KEY, etc.   │
└─────────────────────┴────────────────────────────────────────────────────────┘

Workflow bug bounty type :
  1. money_scope.get_scope("yhi")   → scope YesWeHack+H1+Intigriti
  2. openosint domain <target>      → DNS + subdomain enum
  3. openosint shodan <target>      → services exposés
  4. openosint virustotal <target>  → réputation
  5. Rapport auto-généré (PDF + Markdown)
```

## OSINT Arsenal — routage outil (awesome-osint-arsenal, 1361 outils / 118 cat.)
```
Source : github.com/rawfilejson/awesome-osint-arsenal | Wrapper : 00_CORE/tools/research/osint_arsenal.py
Catalogue interrogeable (osint_arsenal_catalog.json). On NE clone PAS les 751 outils.

RÈGLE — toute tâche OSINT (recherche username/email/phone/domain/face/biz/geo, etc.) :
  from tools.research import osint_arsenal
  hit = osint_arsenal.pick("<la tâche en clair>")
  → si hit["wired"] : APPELER le wrapper existant (OpenOSINT / hackingtool / scripts CYW).
    JAMAIS réinstaller un outil câblé = latence inutile (exigence anti-redondance).
  → sinon : hit["install"] / hit["link"] pour brancher le nouvel outil.
  osint_arsenal.search("...") pour le top-k brut ; .categories() pour explorer.

Priorité de résolution OSINT : OpenOSINT (18 MCP) / hackingtool → SI manque → arsenal.pick().
Régénérer le catalogue : python 00_CORE/tools/research/osint_arsenal.py index
```

## nopeek — Setup immédiat (clés en clair dans .env)
```bash
# 1. Initialiser nopeek
npx nopeek init

# 2. Enregistrer les clés sensibles (tier FREE — pas d'API Anthropic)
nopeek set RTK_API_KEY sk-rtk-...
nopeek set GOOGLE_AI_STUDIO_KEY AIzaSy...
nopeek set GROQ_API_KEY gsk_...
nopeek set FIRECRAWL_API_KEY fc-...

# 3. Remplacer les valeurs dans .env par des références
# Les valeurs réelles ne seront jamais exposées dans les logs/transcripts
```

## ccrecall — Token analytics étendu
```bash
# Sync quotidien des transcripts Claude → SQLite
npx ccrecall sync

# Requêtes utiles :
# Token usage aujourd'hui par modèle
# Sessions les plus coûteuses
# Recherche dans l'historique des sessions forge
# Base : 08_LOGS/ccrecall.db (complète token_tracker.py)
```

## reflect — Extraction automatique de learnings
```
À déclencher en FIN DE SESSION :
  /reflect → analyse la session → propose des learnings
           → Claude valide → indexe dans Graphify via graphify_index()

Remplace : la saisie manuelle de findings dans 06_FINDINGS/
Avantage : capture ce qu'on oublie de noter manuellement
```

## deslop — Critère anti-slop pour MiroFish
```
Patterns détectés (pénalité automatique dans le score) :
  - "Certainly!" / "Of course!" / "Great question!"
  - Listes à puces excessives sans substance
  - Répétition du contexte avant de répondre
  - Hedging excessif ("it's worth noting that", "it's important to...")
  - Structure identique dans chaque réponse

Intégration MiroFish : persona "Slop_Detector" poids 0.8
  → si output score deslop > 3 patterns → pénalité -1.5 pts sur verdict final
```

## PORTFOLIO → MVP FACTORY — Prompt maître (contexte séparé)
```
Objectif : transformer les projets du portfolio en MVPs 100% livrables,
du plus léger au plus lourd en tokens estimés.

Répertoires source : portfolio_structure/TOP_PICKS/ + portfolio_structure/projets/
Répertoire output  : mvp_output/{nom_projet}/
Exclusions         : node_modules, .git, cache, __pycache__, bin, obj

Règle absolue : TOKEN ESTIMATE affiché AVANT chaque séquence projet.
Contenu généré    → RTK FREE tier (jamais dans contexte Claude)
Claude            → orchestration + validation uniquement
```

## STACK PRODUCTION-READY (optiforge) — produits vendables
```
Source : optiforge.txt | Manifeste : 00_CORE/tools/registry.json | Doc : 00_CORE/tools/TOOLS.md
But : forge prête à livrer des produits prod-ready (SaaS, bot, workflow, ai system, website, landing page).
Règle #5 (DO NOT INVENT) : on appelle ces outils, on ne réécrit pas leur logique.
status:planned = wrapper créé au 1er besoin (YAGNI), pas avant.

  OpenHands  → REMPLACE LE DÉVELOPPEUR. Toute étape IMPLEMENT/BUILD : l'orchestrateur
               délègue le code à OpenHands (sandbox sur mvp_output/<projet>/) au lieu de
               générer le code lui-même. Branché sur le router Forge (RTK/free) pour le code.
               GROS PROJET → pas 1 dev mais une FLOTTE (méthode DevOps) : decomposer.py
               découpe en tickets kanban, openhands.run_fleet() lance N devs en parallèle
               (1/ticket, respecte depends_on + scope fichiers). Cf. tools/TOOLS.md §3.
  Coolify    → DÉPLOIEMENT prod (URL+HTTPS) de tout livrable. Étape DELIVER.
  Dify       → SaaS bot / chatbot / assistant métier (app LLM complète).
  Langflow   → workflow IA + RAG (remplace openrag).
  browser-use→ QA des sites générés + scraping interactif (JS/login).
  Stirling-PDF→ toute feature PDF (facture, rapport, contrat signé).
  research-4 + RabbitResearch → sources MARKET/RESEARCH (croiser ≥2 sources).

Carte produit→outil complète : TOOLS.md §3.
```

## DATASETS — protocole (optiforge)
```
Source en plus des actuelles : github.com/awesomedata/awesome-public-datasets
  1. Chercher un dataset existant.
  2. PRÉVENIR le user AVANT téléchargement : quels datasets + POURQUOI.
  3. Après accord → télécharger.
  4. INGÉRER via turbovec → base Token-ID (PG+Redis) primaire, sinon GitNexus :
       from forge_agents.turbovec_brain import get_turbovec_brain
       get_turbovec_brain().store(chunk, agent="DATASET")
  5. JAMAIS de dump brut du dataset dans le contexte (règle #1).
Catalogue pentest : 00_CORE/forge_agents/pentest_datasets.py
```

## PROMPT OPTIMIZER — méthode prompt-master (optiforge)
```
L'agent qui optimise les prompts utilise la méthode prompt-master
(github.com/nidhinjs/prompt-master) : pipeline 7 étapes, 9 dimensions d'intention,
techniques sûres (role/few-shot/XML/grounding/memory), audit tokens
« chaque mot porte du poids » (load-bearing, plus net jamais plus long).
  Wrapper : 00_CORE/tools/prompting/prompt_master.py
    optimize()       → pipeline complet (LLM free-tier)
    optimize_local() → audit tokens déterministe (0 token, réflexe)
  Actif dans : prompt_architect.py (system-prompt + post-audit ultra_prompt)
               nanomachine.py (réflexe NMP OPT)
```

## MCP MANQUANT → RÉSOUDRE PUIS GÉNÉRER (optiforge)
```
Ordre de résolution OBLIGATOIRE (ne génère qu'en dernier recours) :
  1. mcp-registry / connecteurs         → un MCP existe déjà ?
  2. metorial (hub 1200+ intégrations)   → une intégration existe dans le hub ?
       from tools.mcp import metorial
       metorial.search("<service>")              # cherche l'intégration
       metorial.connect("<service>", project)    # génère la config MCP
  3. mcpify (générer)                    → SEULEMENT si rien ci-dessus :
       from tools.mcp import mcpify
       mcpify.ensure_mcp("<repo-url-ou-chemin>", name="<nom>")  # clone+détecte+config
       mcpify.register_hint("<nom>")                            # comment brancher
       Détection AST par défaut (zéro clé). Configs → 00_CORE/tools/mcp/generated/.
  Wrappers : 00_CORE/tools/mcp/{metorial,mcpify,repowise}.py

Code intelligence (repowise) : 2 features gap UNIQUEMENT —
  repowise.get_adr(repo) (ADR auto depuis git) + repowise.get_analytics(repo)
  (churn/velocity/hotspots). Dead code/health/impact → Herald+GitNexus (NE PAS dupliquer).
```

## UI & DESIGN — sur-mesure par marque, JAMAIS de défaut (optiforge)
```
RÈGLE : aucun framework/template UI imposé par défaut. Chaque site/landing/SaaS
généré doit refléter LA MARQUE et LE BESOIN du client — propre, unique, pas générique.

Base de données des éléments qui optimisent un site (interrogeable) :
  from tools.product_bricks.ui import design_kb
  design_kb.build()                              # indexe sources (turbovec agent="UI")
  design_kb.search("SaaS minimal bold")          # sources adaptées (mood/type/tech)
    sources : shadcn, 21st.dev, componentry.fun, themefisher, tailwind_ui,
              daisyui, refero, footer.design, svgdoodles
  → INTERROGER Refero (150K écrans réels) AVANT de choisir (research-first)

Personnalité de marque (ce qui rend le site PROPRE au client) :
  kit = design_kb.brand_kit("#F7A711", ["Satoshi"])   # délègue à design_assets.py
    → palette UIColors depuis la couleur de marque, footer au nom du client,
      doodles SVG colorisés, fonts, composants Park UI thémés
  Assets concrets : 00_CORE/forge_agents/design_assets.py
    (footer.design, svgdoodles, Fontshare, UIColors, Park UI)

Workflow : search(mood,type) → Refero research → choisir sources → brand_kit(hex,fonts)
           → l'agent UI compose quelque chose d'UNIQUE à la marque.
shadcn dispo via tools/product_bricks/ui/shadcn_caller.py SI l'agent le choisit (pas auto).

Génération média à l'image de la marque (image/vidéo self-host) :
  tools/product_bricks/generative_media/{open_gen_ai,opencut}.py
```

## APIs PUBLIQUES — index appelable (optiforge)
```
~1562 APIs publiques (public-apis/public-apis) indexées dans turbovec (agent="API")
+ catalogue 00_CORE/tools/research/public_apis_catalog.json.
Une tâche a besoin d'une donnée/service externe (météo, FX, OCR, géo, finance...) :
  from tools.research import public_apis
  public_apis.search("weather forecast")   # trouve l'API
  public_apis.get("Open-Meteo")            # {url, auth, https, category, ...}
  → l'agent appelle l'URL selon son auth (au lieu de réinventer / chercher le web).
Re-sync : public_apis.fetch_and_index().
```

## ORCHESTRATEUR = CEO + agents auto-optimisés (optiforge)
```
CEO : l'orchestrateur (forge_orchestrate) n'exécute JAMAIS. Il décide QUI recruter
      pour QUELLE tâche. Si l'expert n'existe pas après décomposition → il le CONÇOIT
      (forge_prompt_architect, prompt système 10 sections), jamais de bricolage généraliste.
OPTIM/APPEL : après CHAQUE exécution d'agent (dynamic_agent_node), boost_node compresse
      l'expérience → AGENTS.md + .cursorrules + turbovec. L'agent s'améliore à chaque appel ;
      le boost est réinjecté au prochain spawn.
```

## Herald — Audit sécurité complet (AUDIT_AGENT)
```
Repo    : .claude/AsyncHerald/
Stack   : Rust + Axum + PostgreSQL + Tree-sitter
Modes   : API locale (Docker) | API cloud (app.itsasync.fr/herald)

Catégories analysées :
  🔴 SECURITY   → SQL injection, XSS, secrets exposés, path traversal,
                   ReDoS, crypto flaws (CWE/OWASP mappés)
  🟡 QUALITY    → dead code, duplication, cyclomatic complexity
  🔵 ARCH       → dépendances circulaires, orphans, module graphs
  ⚪ STYLE      → naming conventions, formatting

Grades : A+ → F (pondérés par catégorie)
Export : SARIF (VSCode/IntelliJ/GitHub), PDF Typst, PlantUML

Démarrage rapide (Docker) :
  cd .claude/AsyncHerald
  cp .env.example .env  # remplir DATABASE_URL + JWT_SECRET
  docker build -t herald .
  docker run -p 3001:80 --env-file .env herald

Appel API local (analyse fichiers) :
  curl -X POST http://localhost:3001/analyze/local \
    -H "Content-Type: application/json" \
    -d '{"files": [{"path": "app.js", "content": "..."}]}'

Appel API cloud (repo GitHub public) :
  curl -X POST https://app.itsasync.fr/herald/analyze \
    -H "Content-Type: application/json" \
    -d '{"repo_url": "https://github.com/user/repo"}'
```

### Herald dans le workflow MVP Factory — position
```
S1. ESTIMATE
S2. AUDIT HERALD  ← NOUVEAU (avant toute implémentation)
    → grade actuel du projet tel quel
    → liste des issues critiques (severity: HIGH/CRITICAL)
    → score sécurité brut
S3. PLAN          ← inclut maintenant les fixes Herald
S4. ⏸ WAIT
S5. IMPLEMENT     ← fixe les issues Herald en priorité
S6. RE-AUDIT      ← Herald re-run après implémentation
    → grade final doit être ≥ B pour livraison
S7. MIROFISH      ← reçoit le grade Herald comme input supplémentaire
S8. DELIVER       ← LIVRABLE.md inclut rapport Herald
S9. ACTUAL
```

### Herald — règles de blocage automatique
```
Grade Herald < C  → projet bloqué, ne peut pas aller en TOP_PICKS
Issues CRITICAL   → fix obligatoire avant MiroFish
Secrets exposés   → fix immédiat + rotation des clés recommandée
Score sécurité    → pondération +15% dans le score MiroFish final
```

### Herald — intégration MiroFish
```python
# Dans run_jury(), le herald_grade est injecté dans le ForgeState
# avant d'appeler les personas :

state['herald_grade'] = 'B+'           # ex: résultat Herald
state['herald_issues'] = 3             # nb issues non critiques restantes
state['herald_security_score'] = 82    # sur 100

# Persona Expert reçoit ce contexte automatiquement
# Pénalité si grade < B : -2.0 pts sur verdict final
# Bonus si grade A/A+ : +1.0 pt
```

### herald_audit() — fonction forge
```python
# Dans agent_nodes.py — AUDIT_AGENT
from forge_agents.forge_llm import forge_call, LLMTier

def herald_audit(project_path: str, mode: str = "local") -> dict:
    """
    Lance Herald sur un projet et retourne le résumé structuré.
    mode: 'local' (Docker) | 'cloud' (app.itsasync.fr)
    """
    if mode == "cloud":
        # Appel API cloud pour repos GitHub
        url = "https://app.itsasync.fr/herald/analyze"
    else:
        # Appel API locale (Docker requis)
        url = "http://localhost:3001/analyze/local"

    # Résumé via OpenRouter FREE (pas Claude)
    summary_prompt = f"""
    Analyse ce rapport Herald et retourne en JSON :
    {{"grade": "...", "critical_issues": [...], "security_score": N,
      "top_fixes": ["fix 1", "fix 2", "fix 3"], "livrable_ready": true/false}}
    """
    summary = forge_call(summary_prompt, tier=LLMTier.FREE, task_type="fast_extraction")
    return summary
```

### Herald — critère de livraison MVP
```
Ajouter dans chaque séquence projet du mvp_sequencer.md :
  | Grade Herald actuel | Grade Herald cible | Issues critiques |
  |----|----|-----|
  | D  | B  | 3 CRITICAL, 7 HIGH |

Critère de livraison MVP :
  ✅ Grade Herald ≥ B
  ✅ 0 issues CRITICAL
  ✅ Score sécurité ≥ 70/100
```
