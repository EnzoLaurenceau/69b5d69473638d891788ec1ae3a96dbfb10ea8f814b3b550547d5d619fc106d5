# Bibliothèque d'outils Forge (`00_CORE/tools/`)

> Encapsulation d'outils open-source en wrappers réutilisables (règle CLAUDE.md #5).
> Manifeste machine : [`registry.json`](registry.json). Les agents le lisent pour savoir quoi est dispo et quand l'utiliser.

## Structure sémantique (le chemin = la fonction)
```
tools/
├── dev/                      le développeur (exécution du code)
│   └── openhands.py
├── product_bricks/           briques pour produits shipped
│   ├── ai_workflows/         flows IA visuels & apps LLM
│   │   ├── langflow.py       (workflow IA visuel + RAG)        ⏳ planned
│   │   └── dify.py           (SaaS bot / app LLM complète)     ⏳ planned
│   ├── crm/twenty_crm.py     CRM par projet
│   ├── documents/            stirling_pdf (PDF)                ⏳ planned
│   ├── ui/                   design KB (UI sur-mesure par marque)
│   │   ├── design_kb.py      catalogue sources + brand_kit()   ✅ ready
│   │   └── shadcn_caller.py  npx shadcn (si choisi)            ✅ ready
│   ├── generative_media/     image/vidéo self-host
│   │   ├── open_gen_ai.py    200+ modèles (Flux/Kling/Veo)     ⏳ planned
│   │   ├── opencut.py        montage vidéo                     ⏳ planned
│   │   └── hyperframes.py    HTML→MP4 (ads 9:16 + explainers)  ✅ ready
│   └── saas_starters/        scaffolds SaaS livrables
│       └── apptension.py     saas-boilerplate (React+Django)   ⏳ planned
├── delivery/                 coolify (mise en prod)            ⏳ planned
├── prompting/prompt_master.py        optimisation de prompts
├── mcp/                      MCP : registry → metorial → mcpify
│   ├── mcpify.py             génération auto de MCP   (configs → mcp/generated/)
│   ├── metorial.py           hub 1200+ intégrations            ⏳ planned
│   └── repowise.py           ADR auto + git analytics          ⏳ planned
├── automation/               browser_use (QA web)             ⏳ planned
├── money/                     couche revenu autonome (earn)
│   └── cashclaw.py            agent freelance HYRVE+Stripe      ✅ ready
├── research/                 research_sources + founders_kit
│   ├── public_apis.py        ~1562 APIs publiques              ✅ ready
│   └── founders_kit.py       playbooks founders (turbovec)     ✅ ready
└── catalog/                  catalogues
    ├── app_catalog.py        templates IA/RAG                  ✅ ready
    └── oss_saas.py           SaaS open-source à cloner         ✅ ready

# Assets UI concrets + personnalité de marque → forge_agents/design_assets.py
#   (footer.design, svgdoodles, Fontshare, UIColors palette, Park UI)
# Infra inférence → forge_agents/lmcache_integration.py (KV cache)
# Gouvernance SDLC → forge_agents/agent_skills_patterns.py (gates)
```
Chaque sous-paquet a un `__init__.py` qui décrit sa catégorie + ses outils ready/planned.
Tout est indexé (turbovec + GitNexus) pour la recherche sémantique.

## 1. Twenty CRM — `product_bricks/crm/twenty_crm.py`
CRM open-source (alternative Salesforce), self-host Docker, API GraphQL. Sert à provisionner **un CRM précis par projet**.

```python
from tools.product_bricks.crm import twenty_crm
twenty_crm.prepare("client_boulangerie", port=3001)   # écrit mvp_output/<projet>/crm/{docker-compose.yml,.env}
twenty_crm.up("client_boulangerie")                    # docker compose up -d (instance isolée)
twenty_crm.health("http://localhost:3001")
# Data model sur mesure via GraphQL :
twenty_crm.graphql("http://localhost:3001", token, mutation_create_object, vars)
twenty_crm.down("client_boulangerie")
```
Pré-requis : Docker. Chaque projet = nom + port dédiés (instances isolées).

**⚠️ Licence AGPL-3.0** (+ fichiers `@license Enterprise` = commercial).
Pour **vendre/héberger** un CRM client :
- Tu peux (AGPL l'autorise) **mais** tu dois offrir le **code source modifié** aux utilisateurs du service réseau.
- **Ne livre jamais** les fichiers marqués `@license Enterprise` sans licence commerciale Twenty.

## 2. Catalogue d'apps — `app_catalog.py`
Index de [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) (100+ apps IA/RAG runnable). Modèles **vendables** à cloner / combiner / adapter, ou inspiration pour un besoin inédit.

```python
from tools.catalog import app_catalog
app_catalog.refresh()                       # construit le cache {catégorie: [apps]}
app_catalog.categories()                    # 10 catégories
app_catalog.search("customer support")      # trouve les templates proches d'un besoin
app_catalog.fetch_app_readme(cat, app)      # README d'UNE app, à la demande (pas de bulk)
```
Respecte la règle #1 : **scrape → index → query on-demand**, jamais de dump brut.

**⚠️ Revente** : repo Apache-2.0, mais chaque sous-app a ses propres dépendances → **vérifier leurs licences** avant de vendre un dérivé.

## 3. Stack production-ready (optiforge) — quel outil pour quel produit

Outils externes enregistrés dans `registry.json` (`status: planned` = à déployer au 1er besoin, wrapper créé à ce moment-là, pas avant — YAGNI).

| Produit demandé | Outil(s) | Rôle |
|---|---|---|
| **Code (tout produit)** | **OpenHands** | **Remplace le développeur** : écrit/édite le code, lance les tests, itère. L'orchestrateur délègue le BUILD ici au lieu de générer le code lui-même. |
| Workflow IA / RAG | Langflow | Builder visuel de flows + RAG (remplace openrag). |
| SaaS bot / chatbot / ai system | Dify | App LLM complète (UI + back-office), plus « produit fini » que Langflow. |
| Website / landing page | `website-builder` skill → **Coolify** | Build puis déploiement prod (URL + HTTPS). |
| Déploiement (tout) | Coolify | PaaS self-host, critère « production ready ». |
| QA web / scraping interactif | browser-use | Teste les sites générés, scrape les sites JS/login. |
| Feature PDF (facture, rapport) | Stirling-PDF | Brique PDF, jamais coder la manip à la main. |
| Market / research | research-4 + RabbitResearch (+ firecrawl/semrush) | Croiser ≥2 sources avant décision. |

OpenHands = **développeur** ; Coolify = **déploiement** ; les autres = briques produit.
Règle #5 : on n'invente pas, on appelle ces outils.

### Gros projet → FLOTTE d'OpenHands (méthode DevOps + kanban)
Pour un gros projet, on n'appelle pas UN dev : on découpe en tickets et on lance une **flotte**, un dev OpenHands par ticket.

```python
from tools.dev import openhands
tickets = [
  {"name":"API",  "description":"...", "files":["api.py"],  "depends_on":[]},
  {"name":"UI",   "description":"...", "files":["ui.py"],   "depends_on":[]},
  {"name":"Wire", "description":"...", "files":["main.py"], "depends_on":["T001_xxxx","T002_xxxx"]},
]
openhands.dispatch_project("Build SaaS X", tickets, max_parallel=3)
```
Ou en 2 temps : `decomposer.py --subtasks-json tickets.json` (→ kanban) puis `python tools/dev/openhands.py fleet --parallel 3`.

L'ordonnanceur : ne lance un ticket que si ses `depends_on` sont `done`, jamais deux devs sur les mêmes `files`, écrit chaque résultat dans `forge_dispatch/results/<id>.json`, passe le ticket `done`/`blocked`. Board = `05_STATE/kanban/board.json` (source de vérité).
Self-check : `python 00_CORE/tools/dev/openhands.py demo`.

## 3bis. Prompt Optimizer — méthode prompt-master

L'agent qui optimise les prompts utilise la méthode [prompt-master](https://github.com/nidhinjs/prompt-master) (pipeline 7 étapes, 9 dimensions d'intention, techniques sûres, audit tokens « every word load-bearing »). Wrapper : `00_CORE/tools/prompting/prompt_master.py`.

```python
from tools.prompting import prompt_master
prompt_master.optimize(raw, target_tool="claude")  # pipeline complet (LLM free-tier)
prompt_master.optimize_local(raw)                   # audit tokens déterministe (0 token)
prompt_master.audit_flags(raw)                      # anti-patterns détectés sans LLM
```

Intégrations actives dans la Forge :
- `prompt_architect.py` (Prompt Architect) — méthode injectée dans son system-prompt + `optimize_local` en post-audit du `ultra_prompt`.
- `nanomachine.py` (réflexe NMP `OPT`) — `optimize_local` (zéro token).

Self-check : `python 00_CORE/tools/prompting/prompt_master.py demo`.

## 3ter. MCP manquant → en générer un (mcpify)

Règle : besoin d'un logiciel/CLI/API pour automatiser une tâche **et aucun MCP dispo** → on en **génère un** avec [mcpify](https://github.com/camel-ai/mcpify) (détection AST/LLM → config MCP → serveur, zéro modif du code source). Vérifier d'abord les MCP existants (`mcp-registry`).

```python
from tools.mcp import mcpify
cfg = mcpify.ensure_mcp("https://github.com/user/some-cli", name="some_cli")  # clone+génère
print(mcpify.register_hint("some_cli"))          # comment lancer/brancher le MCP
# mcpify serve mcp/generated/some_cli.json --mode stdio
```

Défaut `strategy="ast"` (statique, aucune clé). `openai`/`camel` = détection LLM (clé requise). Configs générées : `00_CORE/tools/mcp/generated/`.
Self-check : `python 00_CORE/tools/mcp/mcpify.py demo`. Déploiement : `pip install mcpify`.

## 3quater. APIs publiques — index appelable (`research/public_apis.py`)

~1562 APIs publiques ([public-apis](https://github.com/public-apis/public-apis), 51 catégories) indexées dans turbovec + `research/public_apis_catalog.json`. Un agent trouve une API et l'appelle au lieu de réinventer.

```python
from tools.research import public_apis
public_apis.fetch_and_index()              # 1× : peuple turbovec (agent="API") + catalogue
public_apis.search("image OCR")            # APIs pertinentes
public_apis.get("Open-Meteo")              # {url, auth, https, cors, category, description}
```
GitNexus indexe le **code** de ce module ; la **liste d'APIs** vit dans turbovec (base de recherche données). Self-check : `python 00_CORE/tools/research/public_apis.py demo`.

## 4. Datasets — protocole obligatoire

Source à consulter EN PLUS des sources actuelles : [awesome-public-datasets](https://github.com/awesomedata/awesome-public-datasets).

```
1. CHERCHER un dataset existant (awesome-public-datasets + sources actuelles).
2. PRÉVENIR le user AVANT tout téléchargement : quels datasets + POURQUOI.
3. Après accord → télécharger.
4. INGÉRER via turbovec :
     from forge_agents.turbovec_brain import get_turbovec_brain
     get_turbovec_brain().store(chunk, agent="DATASET")
   → base Token-ID (PostgreSQL+Redis) primaire, sinon GitNexus.
5. JAMAIS de dump brut du dataset dans le contexte (règle Forge #1).
```

Catalogue datasets pentest existant : `00_CORE/forge_agents/pentest_datasets.py`.

## Workflow MVP Factory (usage combiné)
1. Besoin client → `app_catalog.search(besoin)` → shortlist de templates.
2. `fetch_app_readme()` sur les candidats → choisir / combiner / adapter.
3. Si le projet a besoin d'un CRM → `twenty_crm.prepare()/up()` + schéma GraphQL sur mesure.
4. Vérifier licences (AGPL Twenty + deps des sous-apps) avant livraison/vente.

## Ajouter un outil
1. Écrire le wrapper `00_CORE/tools/<id>.py` (sous-process/HTTP, jamais d'exception propagée).
2. Ajouter l'entrée dans `registry.json` (purpose, when_to_use, license, license_caveat).
3. Réindexer GitNexus : `node .gitnexus/run.cjs analyze` (depuis `.claude/`).

---

## 5. LMCache — KV Cache Optimization (`forge_agents/lmcache_integration.py`)

[LMCache](https://github.com/lmcache/lmcache) : GPU-optimized KV cache engine. Middleware entre la forge et vLLM/SGLang. **Priorité CRITICAL** pour l'inférence self-hosted.

```python
from forge_agents.lmcache_integration import create_forge_cache, estimate_savings

cache = create_forge_cache()  # pre-registers core forge agents
cache.register_agent_persona("custom_agent", "You are...")  # prefix caching
cache.cache_rag_context("doc_hash_abc", token_count=2000)   # CacheGen RAG
cache.multi_agent_share("scraper", "research")              # share KV blocks
print(cache.get_stats())       # hit_rate, entries, tokens cached
print(estimate_savings(cache)) # $USD saved, TTFT reduction %
```

**Capacités clés :**
- **Prefix caching** → system prompts agents cachés, TTFT -60-80%
- **Non-prefix KV reuse** → agents traitant le même doc = 0 re-prefill
- **Tiered storage** → GPU VRAM → CPU DRAM → disque SSD (auto-promotion/demotion)
- **CacheGen** → compression KV pour RAG, stockage disque viable
- **CacheBlend** → merge blocks non-contigus à l'inférence

## 6. Agent Skills SDLC — Governance (`forge_agents/agent_skills_patterns.py`)

Patterns [agent-skills](https://github.com/addyosmani/agent-skills) (Addy Osmani). Lifecycle **Define → Plan → Build → Verify → Review → Ship** avec anti-rationalization.

```python
from forge_agents.agent_skills_patterns import create_forge_skill_router, get_quality_gates

router = create_forge_skill_router()
skill = router.detect_stage("build the API endpoint")  # → BUILD stage
ok, reason = router.enforce_order(skill.stage)           # enforce stage ordering
warnings = router.check_anti_rationalizations(skill.stage, agent_output)
gates = get_quality_gates()  # exit criteria per stage → align with MiroFish jury
```

**Slash commands :** `/spec`, `/plan`, `/build`, `/test`, `/review`, `/ship`.
**Anti-rationalization :** détecte quand un agent tente de couper les coins (ex: "too simple to need a spec") et enforce le process.
**Quality gates :** exit criteria par stage, alignés avec les scoring dimensions de MiroFish (03_JURY).

## 7. SVG Doodles — Design Assets (`forge_agents/design_assets.py`)

200+ éléments SVG hand-drawn de [svgdoodles.com](https://svgdoodles.com). <3KB chaque, inline-ready.

```python
from forge_agents.design_assets import inject_doodle, get_doodles_by_category, SVGCategory

svg = inject_doodle("arrow_curved", color="#6366f1")  # inline SVG
svg = inject_doodle("underline_wavy", color="#f472b6") # wavy underline
arrows = get_doodles_by_category(SVGCategory.ARROWS)   # all arrow doodles
```

**Catégories :** arrows, circles, blobs, lines, highlights, rectangles, underlines, stars, brackets, scribbles.

## 8. Footer.design — Footer Patterns (`forge_agents/design_assets.py`)

Patterns footer curatés de [footer.design](https://footer.design). HTML+CSS ready-to-use.

```python
from forge_agents.design_assets import get_footer_pattern, generate_footer_html, FooterStyle, FooterIndustry

patterns = get_footer_pattern(style=FooterStyle.MEGA, industry=FooterIndustry.SAAS)
html = generate_footer_html("saas_mega", brand_name="MonProduit", primary_color="#8b5cf6")
```

**Patterns disponibles :** saas_mega, startup_minimal, agency_branded, ecommerce_trust, fintech_gradient.
**Styles :** minimal, mega, cta, branded, newsletter, social, dark, gradient.

## 9. Design KB — UI sur-mesure par marque (`product_bricks/ui/design_kb.py`)

**Pas de lib UI imposée.** Base de données interrogeable des sources UI + couche personnalité de marque. Chaque site reflète SA marque, jamais un template générique.

```python
from tools.product_bricks.ui import design_kb

design_kb.build()                              # indexe les sources (turbovec agent="UI")
sources = design_kb.search("SaaS minimal React")  # sources adaptées au mood/type/tech
# → l'agent interroge Refero (150K écrans réels) AVANT de choisir
kit = design_kb.brand_kit("#F7A711", ["Satoshi"])  # PERSONNALITÉ : palette+footer+doodles à la couleur de marque
```

Sources cataloguées : shadcn, 21st.dev, componentry.fun, themefisher, tailwind_ui, daisyui, refero, footer.design, svgdoodles.
`brand_kit()` délègue à `forge_agents/design_assets.py` (palette UIColors depuis 1 couleur, footer au nom du client, doodles colorisés). Self-check : `python design_kb.py`.

> Workflow produit : `search(mood,type)` → choisir sources → interroger Refero → `brand_kit(hex,fonts)` → UI propre à la marque. shadcn dispo via `shadcn_caller.py` SI l'agent le choisit (pas par défaut).

## 10. Génération média — image/vidéo (`product_bricks/generative_media/`)

```python
from tools.product_bricks.generative_media import open_gen_ai, opencut
open_gen_ai.deploy(project); open_gen_ai.up(project)   # 200+ modèles self-host
img = open_gen_ai.generate_image("hero bakery", "flux-schnell", "hero.png")
vid = open_gen_ai.generate_video("product demo", "kling-v1", "demo.mp4")
opencut.deploy(project); opencut.up(project)           # montage (piloter via browser_use)

from tools.product_bricks.generative_media import hyperframes
proj = hyperframes.init("videos/snap_room1")            # Node>=22 + FFmpeg
hyperframes.add_media(proj, "room.mp4", "logo.png")     # TES assets réels
hyperframes.write_composition(proj, hyperframes.snap_ad_hotel(
    headline="Flash Sale -50%", subline="Ce soir • 1-2 nuits",
    cta="Réserver sur Telegram", media_file="room.mp4"))
out = hyperframes.render(proj)                           # → output.mp4
```
Docker requis pour open_gen_ai/opencut. ⚠️ licence par modèle pour open_gen_ai avant revente.

### OpenGenAI vs HyperFrames — quel outil pour quel cas
| Critère | open_gen_ai | hyperframes |
|---|---|---|
| Nature | IA générative (diffusion) | HTML→MP4 (compositeur déterministe) |
| Contrôle structure | faible (prompt→aléatoire) | total (frame-accurate, brandé) |
| Source du contenu | créé de zéro par l'IA | TES photos/vidéos + texte + transitions |
| Prérequis | Docker | Node≥22 + FFmpeg (pas de Docker) |
| Cas funnel hôtel | générer ambiance/background si pas de média | **Snap ads 9:16 + explainers** (cas par défaut) |
→ Règle : média réel dispo → **hyperframes**. Besoin de créer du visuel ex-nihilo → open_gen_ai.
Templates métier prêts : `snap_ad_hotel(...)`, `explainer_service(...)`.

## 11. Scaffolds & catalogue SaaS (`saas_starters/` + `catalog/oss_saas.py`)

```python
from tools.product_bricks.saas_starters import apptension
dest = apptension.scaffold("mon_saas", mvp_output)  # React+Django+AWS — OpenHands continue dessus
from tools.catalog import oss_saas
oss_saas.fetch_and_index(); oss_saas.search("CRM")  # SaaS OSS à cloner/adapter (turbovec agent="SAAS")
```
⚠️ Vérifier LICENSE apptension + chaque SaaS OSS avant revente.

## 12. Founders Kit — playbooks GTM/pricing (`research/founders_kit.py`)

```python
from tools.research import founders_kit
founders_kit.fetch_and_index()          # turbovec agent="FOUNDER"
founders_kit.search("pricing strategy") # consulté par orchestrateur-CEO + MARKET
```
Rend les produits **vendables** : pricing, GTM, launch, scale.

## 13. MCP — règle de résolution (`mcp/metorial.py`, `mcp/repowise.py`)

Ordre mis à jour : **mcp-registry → metorial → mcpify** (générer en dernier recours).

```python
from tools.mcp import metorial, repowise
metorial.search("stripe")               # hub 1200+ intégrations AVANT de générer
metorial.connect("stripe", project)     # config MCP
repowise.get_adr(repo)                  # ADR auto depuis git (gap GitNexus)
repowise.get_analytics(repo)            # churn/velocity/hotspots (gap GitNexus)
```
Repowise = 2 features gap UNIQUEMENT. Dead code/health/impact → Herald+GitNexus (ne pas dupliquer).

## 15. CashClaw — couche revenu autonome (`money/cashclaw.py`)

[CashClaw](https://github.com/ertugrulakben/cashclaw) (MIT) transforme un agent en **business freelance** : il prend des missions sur la marketplace **HYRVE AI**, les livre, et encaisse via **Stripe**. C'est la couche qui fait **gagner** de l'argent à la Forge en autonomie.

**Runtime-agnostique.** Le CLI `cashclaw` est un binaire Node lancé depuis n'importe quel dossier ; les `SKILL.md` vont dans le dossier skills que l'agent scanne (standard [Agent Skills](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/skills.md)). Marche avec **Hermes**, **Gemini CLI** (`.gemini/skills/`) et **Antigravity** (`.agents/skills/`). `.agents/skills/` (`agent="standard"`) est lu par Gemini CLI **et** Antigravity → 1 drop, 2 runtimes. Câblage :
```
HYRVE (missions) ──► cashclaw CLI ──► agent exécute la skill ──► livrable ──► cashclaw deliver ──► Stripe encaisse
                                  Guard = cost cap + recursion kill + tool firewall
```

```python
from tools.money import cashclaw
cashclaw.ensure()                          # npm i -g cashclaw
cashclaw.setup()                           # config Stripe+HYRVE (env) + guard init + auto-accept OFF
cashclaw.wire_agent("hermes")              # ou "gemini" / "antigravity" / "standard"
cashclaw.gigs()                            # missions dispo (lecture libre)
cashclaw.delivery_hint("seo_audit")        # quel outil Forge produit le livrable
cashclaw.accept(gig_id, approve=True)      # HITL
cashclaw.deliver(gig_id, "deliverables/", approve=True)
cashclaw.withdraw(50, approve=True)        # HITL — sortie d'argent
```

**⚠️ HITL non négociable (blueprint Forge).** `accept` / `deliver` / `complete` / `withdraw` exigent `approve=True` ; sinon l'appel renvoie `{"gated": True}` et **n'exécute rien**. `auto-accept` reste **OFF** par défaut — pas d'auto-confirmation d'argent. Guard fournit le garde-fou cost-cap si l'autonomie totale est activée explicitement.

**Bridge livraison** : chaque skill CashClaw est mappée à l'outil Forge qui fait le vrai travail (SEO→Semrush, content→`forge_call` FREE, scraping→browser_use, invoicing→Stirling-PDF, etc. — voir `FORGE_DELIVERY`). Hermes lit la SKILL.md, la Forge fournit la capacité.

**Choix du runtime.** Hermes & Gemini CLI = agents headless → parfaits pour la boucle autonome (réveil → poll HYRVE → livre → dort). Antigravity = IDE agentique (Agent Manager) → possible mais plus supervisé/interactif, moins adapté à un daemon de revenu non-surveillé. Le gate HITL + Guard sont dans le wrapper, donc indépendants du runtime.

Clés env (via `.env`/nopeek) : `STRIPE_API_KEY`, `HYRVE_API_KEY`. Override : `HERMES_HOME` / `HERMES_SKILLS_DIR`, ou `wire_agent(agent, skills_dir=...)`.
Self-check : `python 00_CORE/tools/money/cashclaw.py` (vérifie que le gate HITL bloque withdraw/accept/deliver sans approve).

## 14. Ressources externes — Index centralisé

Toutes les ressources externes sont indexées dans `07_KNOWLEDGE_BASE/external_resources.json` (format NMP).
L'index fournit : URL, type, priorité, capabilities, module forge, use cases.
