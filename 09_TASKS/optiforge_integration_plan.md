# Plan d'implémentation — vague optiforge "shippable & vendable" (2026-06-16)

> **Statut : ✅ EXÉCUTÉ (2026-06-16).** 25 tools dans registry.json. Wrappers ready : design_kb (+brand_kit), oss_saas (101), founders_kit (611). planned : open_gen_ai, opencut, apptension, metorial, repowise. UI = pas de défaut (design KB + brand_kit). repowise = 2 features gap. external_resources.json réparé + 8 entrées. Détails → memory [[forge-external-tools]].
>
> _Historique : ce plan était initialement "PLAN SEULEMENT" pour session Sonnet._
> Contexte d'origine : intégrer 13 ressources dans la Forge pour rendre les produits
> (SaaS, bot, website, landing, app) vraiment **shippables et vendables**.

## Principes (hérités de la session Opus)
1. **Réutiliser la structure sémantique** `00_CORE/tools/` (chemin = fonction). Voir `tools/registry.json` clé `structure` + `TOOLS.md`.
2. **Conventions de statut** : `ready` (wrapper écrit + self-check), `planned` (wrapper au 1er besoin — YAGNI), `reference` (doc seulement, pas de wrapper).
3. **DO NOT INVENT (règle #5)** : on encapsule/appelle ces outils, on ne réécrit pas leur logique.
4. **Indexation** : données/listes/playbooks → **turbovec** (base de recherche), pas GitNexus (qui indexe le code). Chaque nouveau module → `node .gitnexus/run.cjs analyze`.
5. Chaque item : self-check runnable + entrée `registry.json` + `__init__.py` de catégorie.

## Identité vérifiée + destination dans la Forge

| # | Ressource | Ce que c'est | Maison Forge | Type | Statut | Prio |
|---|---|---|---|---|---|---|
| 1 | **anil-matcha/open-generative-ai** | Studio image+vidéo self-host, 200+ modèles (Flux, Kling, Sora, Veo), MIT | `tools/product_bricks/generative_media/open_gen_ai.py` | wrapper service (docker) | planned | **★ HAUTE** |
| 2 | **OpenCut-app/opencut** | Éditeur vidéo web open-source (alt. CapCut) | `tools/product_bricks/generative_media/opencut.py` | wrapper (automatiser montages) | planned | haute |
| 3 | **shadcn/ui** | Lib composants React (Tailwind+Radix, copy-paste) | `tools/product_bricks/ui/` (source dans le design KB) | catalogue/source dans design KB | reference | moyenne |
| 4 | **21st.dev/community/components** | Composants UI communautaires + Magic MCP | `tools/product_bricks/ui/` + MCP `21st Magic` | MCP + catalogue | reference→planned | moyenne |
| 5 | **componentry.fun** | Collection de composants UI (confirmer au build) | `tools/product_bricks/ui/` | catalogue/reference | reference | basse |
| 6 | **themefisher react templates** | Templates de sites React (free/premium) | `tools/catalog/` (templates web) | catalogue | reference | moyenne |
| 7 | **referodesign/refero_skill** | Skill design IA + Refero MCP (150K écrans d'apps réelles) | `~/.claude/skills/` + Refero MCP | **skill + MCP** | ready | **★ HAUTE** |
| 8 | **apptension/saas-boilerplate** | Stack SaaS open-source (React+Django+AWS) | `tools/product_bricks/saas_starters/apptension.py` | scaffold clone-on-need | planned | haute |
| 9 | **toolworks-dev/open-source-saas** | Liste curée de SaaS open-source vérifiés | `tools/catalog/oss_saas.py` + turbovec | indexeur (comme public_apis) | ready | moyenne |
| 10 | **avinash201199/founders-kit** | Playbooks/ressources founders (build/launch/scale) | turbovec `agent="FOUNDER"` | indexeur connaissance | ready | moyenne |
| 11 | **metorial/metorial** | Hub d'intégrations : connecte tout modèle à 1200+ intégrations (MCP/CLI/API) | `tools/mcp/metorial.py` | connecteur MCP gateway | planned | **★ HAUTE** |
| 12 | **repowise-dev/repowise** | 2 gaps réels vs Forge actuelle : ADR auto-gen + git analytics (churn/velocity/hotspots). Dead code/health → Herald+GitNexus couvrent déjà. | `tools/mcp/repowise.py` (thin wrapper ciblé ADR + analytics) | wrapper ciblé (2 features) | planned (partiel) | moyenne |
| 13 | **10x.app** | App builder commercial (SaaS fermé) | — | reference/inspiration | reference | basse |

---

## Détail par catégorie (étapes Sonnet)

### A. UI & Design — design KB sur-mesure (★ cœur de la demande)
Nouveau sous-paquet `tools/product_bricks/ui/` = **design knowledge base** interrogeable, PAS de lib imposée.

**Principe** : chaque produit génère son UI depuis le KB en fonction de la marque/besoin, pas depuis un template.
L'orchestrateur appelle `ui_kb.search(brand_mood, product_type)` → liste de sources pertinentes → compose une UI propre au projet.

- **design KB `ui/design_kb.py`** — indexe toutes les sources UI dans turbovec (`agent="UI"`) avec tags : `style` (minimal/bold/playful), `type` (SaaS/landing/ecom), `tech` (React/vanilla), `licence`. `search(mood, type)` retourne les sources adaptées. La sélection finale appartient à l'agent (pas automatique).
- **shadcn (#3)** — source dans le KB (composants React copy-paste). Un `ui/shadcn_caller.py` encapsule `npx shadcn add` si l'agent décide de l'utiliser.
- **refero (#7)** — **skill + MCP** : l'agent design interroge 150K écrans réels (research-first) AVANT de choisir les composants. Entrée obligatoire dans le workflow design. `git clone https://github.com/referodesign/refero_skill ~/.claude/skills/refero`.
- **21st.dev (#4)** — source dans le KB + Magic MCP connecté (génération à la demande).
- **componentry.fun (#5)** + **themefisher (#6)** — sources dans le KB, vérifier licences au build.

> Règle produit : l'orchestrateur **recherche** dans le design KB + **interroge Refero** → construit une UI qui reflète la marque. Zéro défaut imposé.

### B. Médias génératifs — image/vidéo (★ ultra important pour SaaS builder, #1/#2)
Nouveau sous-paquet `tools/product_bricks/generative_media/`.

- **open_gen_ai (#1)** — `generative_media/open_gen_ai.py` : wrapper service docker self-host (200+ modèles image+vidéo). `generate_image(prompt, model)` / `generate_video(prompt, model)` via son API. Brick pour TOUT produit nécessitant de la génération média (SaaS de contenu, assets marketing). deploy: docker. **À déployer en priorité.**
- **opencut (#2)** — `generative_media/opencut.py` : automatiser les **montages vidéo** (assembler clips, sous-titres, export). Wrapper sur son moteur (web/API). Sert le pipeline "génère média → monte → exporte". planned.

### C. Scaffolds & catalogues SaaS — *shippable* (#8/#9/#10)
- **apptension saas-boilerplate (#8)** — `tools/product_bricks/saas_starters/apptension.py` : `scaffold(project)` clone le boilerplate (auth, paiements, multi-tenant React+Django+AWS) → base d'un SaaS livrable. clone-on-need. Aligner avec OpenHands (le dev part de ce scaffold). ⚠️ vérifier licence avant revente.
- **oss_saas (#9)** — `tools/catalog/oss_saas.py` : indexeur (même patron que `research/public_apis.py`) → parse la liste, écrit `oss_saas_catalog.json`, indexe turbovec `agent="SAAS"`. `search(besoin)` → trouver un SaaS OSS à cloner/adapter. ready.
- **10x.app (#10)** — reference seule : entrée `registry.json` (inspiration workflow app-builder), pas d'intégration (SaaS fermé).

### D. MCP & intelligence de code (#11/#12)
- **metorial (#11)** — `tools/mcp/metorial.py` : connecteur au hub (1200+ intégrations MCP/CLI/API). **Modifie la règle MCP** : ordre de résolution = `mcp-registry` → **metorial** (intégration existante ?) → **mcpify** (générer en dernier recours). Mettre à jour la section "MCP MANQUANT" de `CLAUDE.md` + `tools/mcp/__init__.py`. ★ haute.
- **repowise (#12)** — 2 features non couvertes : **ADR auto-gen** (décisions archi depuis git) + **git analytics** (churn/velocity/hotspots). Dead code/health → Herald+GitNexus couvrent déjà, skip. `tools/mcp/repowise.py` : thin wrapper sur ces 2 endpoints spécifiques. planned (partiel).

### E. Connaissance founders — *vendable* (#10 founders-kit)
- **founders-kit (#10 dans liste, ligne 10 du tableau)** — indexeur `tools/research/founders_kit.py` (ou réutiliser un script générique) : parse les playbooks → turbovec `agent="FOUNDER"`. L'**orchestrateur-CEO** et l'agent MARKET consultent ces playbooks (pricing, GTM, launch) pour rendre les produits vendables. ready.

---

## Ordre de build recommandé (Sonnet)
1. **★ open_gen_ai** (#1) + **shadcn** (#3) + **refero skill+MCP** (#7) — impact produit immédiat (média + UI pro + design research).
2. **metorial** (#11) — rebrancher la règle MCP (intégration existante avant génération).
3. **saas-boilerplate** (#8) + **oss_saas catalog** (#9) — scaffolds SaaS livrables.
4. **opencut** (#2) — automatisation montage vidéo.
5. **founders-kit** (#10) — index connaissance GTM/pricing.
6. **21st.dev / componentry / themefisher** (#4/#5/#6) — sources UI complémentaires.
7. **repowise** (#12) éval, **10x.app** (#13) reference — derniers, faible prio.

## À faire à CHAQUE item (checklist)
- [ ] Wrapper dans le bon sous-paquet + `__init__.py` mis à jour.
- [ ] Entrée `tools/registry.json` (+ clé `structure` si nouveau sous-paquet).
- [ ] Self-check runnable (`demo`) + section `TOOLS.md`.
- [ ] Indexation turbovec si données/liste (catalogues, playbooks).
- [ ] `node .gitnexus/run.cjs analyze` (indexer le nouveau code).
- [ ] Note dans `CLAUDE.md` si ça change un comportement (UI par défaut, règle MCP).

## Décisions ouvertes (à trancher au build)
- **Nouveaux sous-paquets** : `product_bricks/ui`, `product_bricks/generative_media`, `product_bricks/saas_starters`. OK ? (cohérent avec l'existant.)
- **shadcn comme défaut UI imposé** → ❌ TRANCHÉ : pas de défaut. Design KB interrogeable, UI sur-mesure par marque.
- **repowise vs GitNexus** → ❌ TRANCHÉ : garder GitNexus+Herald. Repowise : thin wrapper 2 features gap (ADR + git analytics).
- Licences à vérifier avant **revente** : saas-boilerplate, templates themefisher, modèles derrière open-generative-ai.
```
