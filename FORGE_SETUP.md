# ⚡ FORGE — Guide d'installation complète
> Recréer le Super Agent Forge sur une nouvelle machine, from scratch.
> Vérifié sur l'état réel du dépôt (2026-06-17).

---

## 1. Prérequis système

| Outil | Version min | Installation |
|-------|-------------|--------------|
| Python | 3.11+ | python.org |
| Node.js | 20+ | nodejs.org |
| Docker Desktop | dernière | docker.com |
| Git | any | git-scm.com |
| Claude Code CLI | dernière | `npm i -g @anthropic-ai/claude-code` |

---

## 2. Copier / cloner la Forge

Option A — copier le dossier `.claude` existant (recommandé) :
```
# Depuis la machine source :
# Zipper C:\Users\Enzo\Documents\MODELS\.claude
# Transférer l'archive → extraire sur la nouvelle machine à l'endroit voulu
# Ex : C:\Users\<ami>\Documents\MODELS\.claude
```

Option B — dépôt Git (si la Forge est versionnée) :
```powershell
git clone <ton-repo-forge> "C:\Users\<ami>\Documents\MODELS\.claude"
```

---

## 3. Dépendances Python

> **Pas de venv** — la Forge installe tout en global (comme sur la machine source).
> Si tu veux isoler, crée un venv AVANT d'installer, mais c'est optionnel.

```powershell
cd "C:\Users\<ami>\Documents\MODELS\.claude"

pip install -r requirements.txt

# Scrapling (fetchers furtifs — scraping JS/login)
pip install "scrapling[fetchers]"
scrapling install
```

### Versions réelles installées (ref machine source)

| Package | Version |
|---------|---------|
| `nexus-ai-fs` | 0.9.26 |
| `nexus-fs` | 0.4.7 |
| `turbovec` | 0.8.0 |
| `langgraph` | 1.2.2 |
| `anthropic` | 0.105.0 |
| `redis` | 8.0.0 |
| `psycopg` | 3.2.13 |

---

## 4. Clés API — fichier `.env`

> **Pas de `.env.example`** — créer `.env` directement à la racine.

```dotenv
# === OBLIGATOIRES ===
ANTHROPIC_API_KEY=sk-ant-...          # console.anthropic.com

# === TIER 0 — GRATUIT (priorité max) ===
GOOGLE_AI_STUDIO_KEY=AIzaSy...        # aistudio.google.com (Gemini 2.5 Flash)
GROQ_API_KEY=gsk_...                  # console.groq.com (Llama 4 — 30M tokens/j gratuit)
CEREBRAS_API_KEY=...                  # cloud.cerebras.ai (ultra-rapide, gratuit)
NEBIUS_API_KEY=...                    # studio.nebius.ai (inférence pas chère)

# === OPTIONNELS (selon besoins) ===
# FIRECRAWL_API_KEY — SUPPRIMÉ. Remplacé par crawl4ai (local, gratuit).
TAVILY_API_KEY=tvly-...               # tavily.com (mcp-omnisearch)
RTK_API_KEY=sk-rtk-...               # proxy RTK local si installé
```

Cascade dans `forge_llm.py` (TIER 0 → ... → OPUS) :
```
FREE : Gemini Flash → Groq Llama4 → Cerebras → OpenRouter free
HAIKU: claude-haiku-4-5
SONNET: claude-sonnet-4-6
OPUS : claude-opus-4-8 + extended thinking
```

---

## 5. Infrastructure — PG + Redis (Docker)

```powershell
cd "C:\Users\<ami>\Documents\MODELS\.claude\00_CORE\db"
docker compose up -d
```

Vérification :
```powershell
python run_forge.py --db-status     # redis UP / postgres UP
```

Si Docker absent → bascule **MODE SECOURS automatique** (LangGraph SQLite + `graph.json`).
Aucune action requise.

---

## 6. Bootstrap (une seule fois)

```powershell
python run_forge.py --bootstrap
```

Ordre d'exécution :
1. Démarre Docker si dispo
2. Lève PG + Redis, applique le schéma
3. Installe les deps manquantes
4. Rejoue le WAL (idempotent — sans danger si vide)
5. Initialise turbovec (index vectoriel 4-bit, zéro GPU)

---

## 7. Nexus — couche mémoire unifiée (IMPLÉMENTÉ)

> `nexus_bridge.py` est le composant central. Il remplace 3 anciens modules :

| Remplacé | Par Nexus |
|----------|-----------|
| `openviking.py` — context retrieval | `nexus hybrid search` |
| `semantic_cache.py` — dédup | `nexus CAS automatique` |
| `graphify_checkpointer.py` — checkpoints | `nexus VFS /checkpoints/` |

Nexus fonctionne **embarqué** (zero daemon externe) — démarre dans le process Python avec `data_dir=./nexus-data`. Si `nexus-ai-fs` absent → fallback JSON/SQLite transparent.

**Namespaces VFS actifs :**
```
/memory/       → knowledge graph (remplace graph.json)
/checkpoints/  → LangGraph state
/turbovec/     → état 4-bit index
/findings/     → findings confirmés
/state/        → checkpoint.json session
```

---

## 8. Claude Code — configuration

### 8a. Lancer Claude Code dans le dossier Forge

```powershell
cd "C:\Users\<ami>\Documents\MODELS\.claude"
claude
```

`CLAUDE.md` local lu automatiquement → toutes les règles Forge actives dès l'ouverture.

### 8b. Skills critiques

Dans une session Claude Code :
```
/setup-cowork
```
Ou vérifier manuellement :
```
ponytail        → efficacité (lazy senior dev mode)
graphify        → /graphify input → knowledge graph
context-mode    → protection du contexte window
```

### 8c. Sécurité clés API (nopeek)

```powershell
npx nopeek init
nopeek set ANTHROPIC_API_KEY sk-ant-...
# répéter pour chaque clé sensible
```

---

## 9. Vérification complète

```powershell
python run_forge.py --status         # niveau / cycle / findings
python run_forge.py --resume         # reprend depuis dernier checkpoint
```

Test end-to-end (doit utiliser TIER 0, pas Claude) :
```powershell
python run_forge.py --task "test : dis bonjour en caveman"
```

Index code (optionnel mais recommandé) :
```powershell
npx gitnexus analyze                 # indexe les ~3000 symboles de la Forge
```

---

## 10. Structure des dossiers (réelle)

```
.claude/
├── 00_CORE/
│   ├── forge_agents/   → 60+ modules : forge_llm, forge_db, forge_graph,
│   │                     nexus_bridge, turbovec_brain, mirofish,
│   │                     anti_hallucination, token_tracker, cervelet...
│   ├── blueprints/     → saas_ai_chatbot.md, agentic_production_blueprint.md,
│   │                     nebius_cookbook_patterns.md
│   ├── db/             → docker-compose.yml
│   └── tools/          → registry.json, TOOLS.md, mcp/, product_bricks/,
│                          prompting/, research/, automation/
├── 03_JURY/            → personas MiroFish + verdicts
├── 04_GRAPHIFY/        → graph.json (mémoire collective)
├── 05_STATE/           → checkpoint.json (état actif)
├── 06_FINDINGS/        → confirmed / pending / killed
├── 08_LOGS/            → logs cycles + token tracker
├── AsyncHerald/        → audit sécurité Rust (Herald)
├── nexus-data/         → données Nexus VFS (auto-créé au bootstrap)
├── CLAUDE.md           → instructions maîtres (lues à chaque session)
├── FORGE.md            → carte de navigation
├── run_forge.py        → point d'entrée principal
└── requirements.txt    → deps Python
```

---

## 11. Cheatsheet — commandes du quotidien

```powershell
# Tâche
python run_forge.py --task "market scan niche IA créateurs"
python run_forge.py --task "build landing page SaaS" --desc "dark theme violet" --cycles 5

# Navigation
python run_forge.py --status         # dernier checkpoint
python run_forge.py --resume         # reprendre depuis checkpoint

# Herald (audit sécurité — Docker requis)
cd AsyncHerald
docker build -t herald .
docker run -p 3001:80 --env-file .env herald

# Analytics tokens
npx ccrecall sync

# Fin de session
/reflect    (dans Claude Code — extrait les learnings → Graphify)
```

---

## 12. LLM Router — qui paye quoi

| Tier | Provider | Coût | Tâches mappées |
|------|----------|------|----------------|
| FREE | Gemini Flash / Groq / Cerebras / Nebius | ~0 | score, summarize, extract, classify, coding, jury MiroFish |
| HAIKU | claude-haiku-4-5 | bas | write_email, write_post, generate |
| SONNET | claude-sonnet-4-6 | moyen | market_scan, research, build, close |
| OPUS | claude-opus-4-8 | élevé | orchestrate, critique, audit, plan |

**Règle** : 80% des appels restent en FREE. Claude = dernier recours.

---

## 13. Blueprints à lire avant tout projet

| Fichier | Quand |
|---------|-------|
| `00_CORE/blueprints/saas_ai_chatbot.md` | Tout projet SaaS/chatbot |
| `00_CORE/blueprints/agentic_production_blueprint.md` | Archi 5 couches + HITL |
| `00_CORE/blueprints/nebius_cookbook_patterns.md` | Patterns prod (streaming/guardrails) |

---

> **Règle absolue n°1** : jamais de fichier brut dans le contexte.
> Toujours : scrape → `graphify_index()` → `graphify_query()` → agent.
