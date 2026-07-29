# FORGE_AUDIT_REPORT — Audit complet de La Forge

*Généré le 2026-07-23. Analyse froide, basée sur les données disponibles dans le dépôt et des prix externes recherchés le jour de génération. Ce rapport sépare systématiquement ce qui est **mesuré** (fichier source cité) de ce qui est **estimé** (méthode et hypothèse citées) et de ce qui est **manquant** (décrit, jamais inventé). Détail complet dans les 11 fichiers JSON et 2 rapports Markdown compagnons de ce dossier.*

## 1. Ce qui existe réellement

La Forge est un système d'orchestration d'agents construit autour de LangGraph/LangChain, avec un registre interne de **161 composants** (62 outils, 61 agents, 38 skills — mesuré, `05_STATE/system_registry/`), **275 fichiers Python** et **~70 000 lignes de code** dans le cœur du projet (mesuré, hors dépôts vendored). Le tout a été construit par **un seul auteur** en **37 jours** (2026-06-16 → 2026-07-22, 30 commits, 488 301 lignes ajoutées / 28 934 supprimées — mesuré, `git log`).

Le système route les tâches vers un mélange de : Claude (via abonnement, pas d'API pay-per-token selon la politique documentée dans `CLAUDE.md`), un abonnement forfaitaire **MiMo** (~17€/mois, **non confirmé**), un gateway **DS2API/deepseek-v4** (455 appels sur 520 mesurés, 0$ facturé), et des API gratuites (Groq, Google AI Studio/Gemini). Un agent de code autonome (**OpenHands**, déployé le 2026-07-18) peut écrire du code sans jamais faire transiter le résultat par le contexte Claude.

Une CI déterministe et gratuite existe (`ci.yml` : compilation, tests, vérification de propriété d'état) — point positif mesuré, rare d'être aussi explicitement anti-token-waste.

## 2. Ce que les données disent sur la performance

**Un seul vrai A/B existe** (site vitrine statique "Café Bastoche") — voir `naive_vs_forge.json` pour le détail complet. Résultat honnête, pas favorable par défaut à la Forge :

- **Claude direct** : 1 passe, 8 430 tokens, ~0,39$, site livré et fonctionnel, 100% de succès (1/1).
- **Forge autonome (série complète, pas seulement le run gagnant)** : 526 839 tokens (4,1× plus que Claude direct), 0$ facturé au token, **1 succès sur 15 tentatives (6,7%)**, avec 3 bugs bloquants découverts et corrigés en cours de route.
- Le run gagnant seul livre 6,2× plus de lignes (2 183 vs 351) — mais ce chiffre seul, sorti du contexte des 14 échecs qui l'ont précédé, serait trompeur. C'est explicitement le piège que ce pack a été conçu pour éviter.

**Conclusion honnête sur cette unique tâche mesurée** : la Forge démontre un mécanisme réel (jury anti-hallucination actif, génération déportée hors du contexte Claude cher) mais ne prouve pas encore une fiabilité de livraison supérieure à Claude seul sur une tâche simple. Aucune donnée n'existe pour une tâche applicative réelle (repo avec tests) — c'est le trou le plus important de ce pack, avec un protocole déjà rédigé pour le combler (`08_LOGS/benchmark_pack/README.md` §4).

## 3. Ce que les données disent sur le coût

Le coût mesuré total sur la fenêtre 2026-05-26 → 2026-07-18 (53 jours) est de **294,98$**, concentré à **99,87%** sur le provider `claude_code`. Clarification importante et non triviale : ce chiffre est une valeur **notionnelle** calculée par le tracker interne au tarif catalogue — la politique du projet (`CLAUDE.md`) est de consommer Claude via un **abonnement forfaitaire**, pas au token. Le coût réel out-of-pocket dépend du plan actif (Pro 20$/mois, Max 5x 100$/mois, ou Max 20x 200$/mois — non identifiable depuis les logs locaux, prix recherchés le 2026-07-23).

Le poste dominant en volume de tokens est le **cache-read** (~96% du volume sur l'échantillon de sessions détaillé disponible), pas l'input frais — toute simulation qui l'ignorerait serait fausse d'un ordre de grandeur. Le fichier `api_cost_simulation.json` applique ce correctif et projette 4 scénarios (actuel, 2x, 10x, 100x) sur 7 modèles de 4 fournisseurs, avec prix de marché recherchés le jour de génération (sources citées dans le fichier).

## 4. Infrastructure GPU — n'existe pas actuellement

La Forge n'utilise **aucun GPU aujourd'hui** — tout est API/abonnement ou CPU local (Nexus VFS "zéro GPU par conception"). `gpu_infrastructure_model.json` détaille 5 scénarios prospectifs (API seule, VPS+API, GPU à la demande, GPU permanent, hybride) avec des prix de marché recherchés (A100 ~1$/h, H100 ~2$/h, serveur GPU dédié Hetzner ~184€/mois). **Aucun de ces scénarios n'est recommandé par ce rapport** : la décision dépend d'abord de la confirmation du quota MiMo réel (voir §6).

## 5. Risques techniques identifiés (détail dans `technical_risk_report.md`)

Par ordre de sévérité (jugement qualitatif) :

1. **Dépendance MiMo non contractualisée** — fournisseur unique, prix/quota non confirmés, fallback instable documenté.
2. **Bus factor** — 100% des commits par un seul auteur.
3. **Tier Anthropic direct cassé** — `ANTHROPIC_API_KEY` absente, échec d'authentification mesuré, le routage réel ne correspond pas au routage documenté.
4. **Pipeline autonome peu fiable** — 1 succès sur 15 sur le seul échantillon mesuré.
5. **Couverture de tests étroite** — 7 suites pytest réelles sur 275 fichiers, avec un bug historique documenté (tests qui ne vérifiaient rien) désormais corrigé.
6. **Angle mort du garde-fou anti-hallucination** — recall de 20% seulement sur les cas "hors scope" (échantillon faible, n=21, mais signal cohérent).

## 6. Ce qui manque pour un devis ou une décision d'investissement fiable

Ce rapport refuse délibérément d'inventer les chiffres suivants — ils sont `null` avec description dans les fichiers JSON correspondants :

- **Facture MiMo réelle** (montant et quota confirmés) — bloque toute décision de scaling ou d'investissement GPU.
- **Plan d'abonnement Claude actif** (Pro/Max 5x/Max 20x) — bloque le calcul du coût fixe réel.
- **Temps humain économisé ou dépensé** — non instrumenté nulle part dans le projet ; bloque tout calcul de ROI ou de valeur horaire.
- **Volume de tokens par tâche/nœud individualisé** — agrégé actuellement, empêche d'arbitrer objectivement un investissement GPU ciblé (ex. sur `patch_optimizer`, qui domine `forge_agent_metrics.csv` à 89,8% des lignes).
- **Test de charge multi-utilisateur réel** — `05_STATE/tenants/` existe en amorce mais n'est prouvé nulle part en charge.
- **A/B applicatif réel** (repo avec tests) — protocole déjà écrit, jamais exécuté.

## 7. Recommandation de méthode (pas de recommandation d'investissement)

Ce rapport ne recommande **aucun montant d'investissement** (GPU, infra dédiée, contrat volume) tant que les 6 éléments manquants du §6 ne sont pas comblés — en particulier la confirmation MiMo, qui conditionne directement la rentabilité de toute alternative. Le détail des actions pour combler ces manques, classées par horizon et effort, est dans `roadmap_recommendations.md` (top 5 : confirmer MiMo, corriger la clé Anthropic, lancer le vrai A/B applicatif, corriger l'angle mort anti-hallucination, arbitrer le niveau de supervision du pipeline autonome).

## 8. Sommaire des fichiers du pack

| Fichier | Contenu | Nature dominante |
|---|---|---|
| `system_inventory.json` | 161 composants + infra/fournisseurs externes | mesuré + documenté |
| `usage_history.json` | Sessions, tokens, période couverte | mesuré (échantillon) |
| `naive_vs_forge.json` | Le seul vrai A/B (Café Bastoche) + protocole non exécuté | mesuré + proposition |
| `context_efficiency.json` | Volume brut tool calls, compression non mesurable en détail | mesuré + limites explicites |
| `routing_analysis.json` | Coût/appels par modèle, alternatives moins chères | mesuré + estimé |
| `quality_metrics.json` | Éval anti-hallucination, échecs de tests, CI | mesuré |
| `productivity_metrics.json` | Commits, lignes, bus factor | mesuré |
| `api_cost_simulation.json` | 4 scénarios × 7 modèles × 4 fournisseurs | mesuré (base) + estimé (prix) |
| `gpu_infrastructure_model.json` | 5 scénarios prospectifs API/VPS/GPU | estimé (prospectif, rien n'existe encore) |
| `economic_model.json` | ROI par profil — volontairement non chiffré faute de données | estimé + manques explicites |
| `scaling_projection.json` | Projection 10/100/1000 utilisateurs | estimé (linéaire naïf) |
| `technical_risk_report.md` | 9 risques détaillés et sourcés | mesuré + jugement |
| `roadmap_recommendations.md` | Actions classées par horizon/priorité | recommandation |
# Rapport de dette technique et de risques — La Forge

*Généré le 2026-07-23. Toute affirmation ci-dessous est sourcée. Les jugements de sévérité sont des évaluations qualitatives de l'auditeur, explicitement marquées comme telles — pas des mesures.*

## 1. Bus factor — risque humain (mesuré)

Les 30 commits du dépôt principal proviennent à 100% d'un seul auteur (`Leviantan07`), sur une fenêtre de 37 jours (2026-06-16 → 2026-07-22). Aucune revue de code par un tiers n'est visible dans l'historique git. Source : `git log`.

**Sévérité (jugement) : élevée.** Un projet de cette taille (275 fichiers Python mesurés dans le cœur, ~70 000 lignes, 161 composants enregistrés dans le registre interne) reposant sur une seule personne signifie qu'un indisponibilité de cette personne bloque toute évolution, correction de bug ou compréhension fine de l'architecture. Ce n'est pas propre à la Forge — c'est la situation par défaut de tout projet solo — mais elle mérite d'être nommée avant tout devis d'investissement.

## 2. Dépendance MiMo — fournisseur unique non contractualisé (documenté)

Le backend LLM principal des workers routés (`hermes`) est un abonnement forfaitaire MiMo dont le montant (~17€/mois) et le quota (~11 milliards de tokens/mois, mécanisme de round-up par appel) sont **explicitement qualifiés de non confirmés** par la documentation interne du projet (`08_LOGS/benchmark_pack/README.md`, `case_study_cafe_bastoche.md`). Aucune facture réelle n'a été produite dans les fichiers consultés.

De plus, le même document indique que brancher d'autres API gratuites en secours du routeur MiMo est **possible mais instable** ("le routeur devient par moments inutilisable").

**Sévérité (jugement) : élevée.** C'est un point unique de défaillance (single point of failure) sur lequel repose la quasi-totalité du volume de tokens de la Forge (559,7M tokens mesurés côté `hermes` sur la période, contre 0,38$ de coût facturé) — sans confirmation contractuelle de ce que ce forfait couvre réellement. Toute décision d'investissement (GPU, scaling) qui suppose la continuité de ce forfait est construite sur une hypothèse non vérifiée.

## 3. Tier Anthropic direct non fonctionnel (mesuré)

`test_results_FINAL.json` montre un échec réel et récent : le tier "haiku" retourne `FAILED` avec l'erreur `Could not resolve authentication method` — confirmé par l'absence de `ANTHROPIC_API_KEY` dans `.env` (explicitement noté dans `token_comparison_cafe_bastoche/measures/forge_autonomous_debug.md`).

Conséquence mesurée sur le cas Café Bastoche : les 4 modèles planifiés par le tracker de tokens pour la génération (Gemini, Groq, Haiku, Sonnet) **n'ont jamais été appelés** — tout retombe sur `ds2api-deepseek-v4`, seul backend réellement fonctionnel dans ce run, avec des effets de bord observés (troncature de sortie ~1k tokens, protocole de sortie qui varie à chaque run).

**Sévérité (jugement) : moyenne à élevée selon l'usage visé.** Si le tier Claude direct fait partie du plan de routage documenté (`CLAUDE_ROUTING.md`, `MODEL_ROUTING.md`), son indisponibilité de fait rend ce plan trompeur : la Forge route déjà 100% vers le fallback sans que cela soit un choix délibéré.

## 4. Fiabilité du pipeline autonome — 1 succès sur 15 (mesuré)

La seule vraie étude A/B disponible (`case_study_cafe_bastoche.md`) montre que le pipeline 100% autonome (OpenHands + MiMo, sans intervention Claude sur le code) a nécessité **14 runs en échec avant le premier succès**, avec 3 bugs bloquants latents dans des modules "V6 non testés" (`openviking.py`, `forge_graph.py`, `auto_complexification.py`) découverts uniquement à l'usage.

**Sévérité (jugement) : élevée pour tout usage en production sans supervision.** Un taux de succès de 6,7% sur cet échantillon (n=15, une seule tâche) ne permet aucune généralisation statistique fiable, mais c'est le seul chiffre mesuré disponible — et il est défavorable à l'autonomie complète en l'état.

## 5. Couverture de tests réelle très restreinte (mesuré)

`pytest.ini` ne déclare que **7 suites de tests réelles** comme valides (`00_CORE/forge_agents/semantic_edit_engine/test_see.py`, `test_versioning.py`, `test_forge_data_scientist.py`, `forge_trading/tests/test_surface.py`, `test_strategy_behaviour.py`, `test_forge_systems.py`, `test_state_isolation.py`) sur un cœur de code de 275 fichiers Python. Les autres fichiers `test_*.py` présents à la racine du dépôt sont explicitement documentés comme des scripts de smoke-test (effets de bord réseau/import) et non des tests pytest valides.

Le fichier documente aussi un bug historique réel : 5 tests restaient "verts" sans jamais vérifier quoi que ce soit (`return` au lieu d'`assert`, ignoré silencieusement par pytest) — corrigé via `filterwarnings = error::pytest.PytestReturnNotNoneWarning`. C'est un signal positif (le bug a été trouvé et corrigé avec un garde-fou permanent) mais aussi un signal que la suite de tests a longtemps donné une fausse impression de santé.

**Sévérité (jugement) : moyenne.** La CI (`.github/workflows/ci.yml`) est réelle, déterministe et gratuite (compilation + tests + vérification de propriété d'état) — c'est un point positif mesuré — mais son périmètre de test reste étroit par rapport à la taille du code.

## 6. Angle mort du garde-fou anti-hallucination (mesuré)

`00_CORE/forge_agents/eval_report.json` (corpus de 205 cas) montre une accuracy globale de 92,2%, mais cette moyenne masque une hétérogénéité forte : 100% d'accuracy sur les cas "in scope" (n=184) contre seulement 23,8% sur les cas "out of scope" (n=21, rappel de seulement 20%, soit 16 faux négatifs sur 20).

**Sévérité (jugement) : moyenne, mais à surveiller.** L'échantillon "out of scope" est petit (n=21), donc l'incertitude statistique est large, mais la direction du signal (le garde-fou rate 4 cas "hors scope" sur 5) est cohérente et mesurée, pas une anomalie isolée.

## 7. Complexité de la pile technique (documenté)

`requirements.txt` fait apparaître une pile large : LangGraph/LangChain, Postgres+pgvector, Redis, Anthropic SDK, Google Generative AI, scrapling, crawl4ai, Nexus VFS (`nexus-ai-fs`, `turbovec`), OpenHands (Docker), N8N, RTK (binaire Rust vendored), tree-sitter, FastAPI/Uvicorn. Le registre interne recense 161 composants (62 outils, 61 agents, 38 skills) avec 135 relations de dépendance.

**Sévérité (jugement) : moyenne à élevée, proportionnelle au bus factor (risque #1).** Une pile aussi large maintenue par une seule personne augmente le risque qu'une partie du système devienne un "code mort documenté" difficile à faire évoluer sans regénérer un contexte complet — ce que confirme indirectement le fait que 3 bugs bloquants dormaient dans des modules "V6 non testés" avant d'être découverts par un test ad hoc.

## 8. Hygiène du dépôt — points positifs mesurés

- `.env`, `.env.*` sont correctement exclus du contrôle de version (`.gitignore`), avec `!.env.example` conservé — bonne pratique confirmée, pas de fuite de secret détectée dans le suivi git.
- La CI ne consomme aucun token LLM (0$ de coût, déterministe) — conception saine.
- Un fichier volumineux (`tg-bot-workflow.zip`, 63 Mo) est committé à la racine du dépôt — alourdit inutilement le dépôt git sans bloquer son fonctionnement (risque mineur, jugement).

## 9. Ce qui n'a pas pu être évalué (absence de données, pas absence de risque)

- Sécurité applicative (dépendances vulnérables, secrets dans le code applicatif au-delà de `.env`, exposition réseau) : `pip-audit` est appelé en CI mais son résultat n'a pas été consulté dans le cadre de cet audit — à vérifier séparément.
- Charge/performance sous usage concurrent réel (plusieurs utilisateurs simultanés) : aucune donnée, `05_STATE/tenants/` existe mais n'est pas prouvé en charge.
- Conformité légale (RGPD, mentions légales des sites produits) : `CLAUDE.md` mentionne des gates légaux (SIRET, hébergeur, médiateur) mais leur application effective n'a pas été auditée ici.
# Roadmap de recommandations — La Forge

*Classement par horizon. Pour chaque item : difficulté, coût, gain attendu, priorité. Les gains sont qualifiés "mesuré" quand ils corrigent un fait constaté dans ce dépôt, "estimé" sinon.*

## A. Gains rapides (jours, faible effort)

### A1. Confirmer le prix et le quota réels de l'abonnement MiMo
- **Constat** : ~17€/mois et ~11Md tokens/mois sont non confirmés dans toute la documentation interne consultée.
- **Difficulté** : très faible (une facture à demander/relire).
- **Coût** : nul.
- **Gain attendu** : élimine la plus grosse incertitude de tout ce pack — chaque simulation de coût et de scaling dépend de ce chiffre.
- **Priorité : CRITIQUE.**

### A2. Configurer `ANTHROPIC_API_KEY` (ou clarifier que ce tier est volontairement désactivé)
- **Constat mesuré** : `test_results_FINAL.json` montre un échec d'authentification réel ; le tier Haiku/Claude direct planifié par le routeur n'est jamais atteint.
- **Difficulté** : très faible.
- **Coût** : dépend du volume qui y serait routé (à chiffrer une fois la clé active, via `forge_llm_calls.csv`).
- **Gain attendu** : le routage réel correspond enfin au routage documenté ; évite de découvrir la panne en production.
- **Priorité : haute.**

### A3. Nettoyer le dépôt des fichiers volumineux non essentiels
- **Constat** : `tg-bot-workflow.zip` (63 Mo) committé à la racine.
- **Difficulté** : faible (git filter-repo ou simple suppression + `.gitignore`).
- **Coût** : nul.
- **Gain attendu** : dépôt plus léger à cloner/sauvegarder.
- **Priorité : basse.**

### A4. Ajouter les chemins de fichiers au ledger `tool_calls.csv`
- **Constat** : sans les chemins, impossible de dériver "fichiers lus / modifiés" avec précision (mentionné comme limite explicite dans le README benchmark_pack).
- **Difficulté** : faible (modifier `export_benchmark_pack.py` et l'instrumentation amont).
- **Coût** : nul.
- **Gain attendu** : débloque une mesure demandée par cet audit (fichiers lus/modifiés) actuellement à `null`.
- **Priorité : moyenne.**

## B. Optimisations importantes (semaines, effort modéré)

### B1. Exécuter le protocole A/B applicatif proposé (déjà rédigé, jamais lancé)
- **Constat** : le seul vrai A/B existant porte sur un site statique simple ; aucune donnée n'existe sur une tâche applicative réelle (repo Django, tests qui passent/échouent).
- **Difficulté** : moyenne (protocole déjà écrit dans `08_LOGS/benchmark_pack/README.md` §4, 3 runs par bras, worktree isolé).
- **Coût estimé** : quelques heures machine + ~5-15$ d'API sur le bras "Claude naïf" (estimation du pack source).
- **Gain attendu** : remplace une extrapolation à 1 point de données par une vraie mesure généralisable — condition nécessaire avant tout devis basé sur "le gain Forge" pour du code applicatif.
- **Priorité : haute.**

### B2. Fiabiliser le pipeline autonome avant tout usage sans supervision
- **Constat mesuré** : 1 succès sur 15 tentatives sur le seul cas mesuré, 3 bugs bloquants trouvés a posteriori dans des modules non testés.
- **Difficulté** : moyenne à élevée (dépend des bugs restants, non tous inventoriés).
- **Coût** : temps d'ingénierie (non chiffrable ici, pas de mesure de temps humain).
- **Gain attendu (estimé)** : faire passer le taux de succès mesuré de ~7% à un niveau exploitable en production ; actuellement, tout usage autonome doit être supervisé.
- **Priorité : haute si l'autonomie complète est un objectif produit ; basse si le mode "Claude guidé" (bras B rescue) suffit.**

### B3. Combler l'angle mort du garde-fou anti-hallucination sur les cas "out of scope"
- **Constat mesuré** : recall de 20% seulement sur 21 cas "out of scope" (eval_report.json).
- **Difficulté** : moyenne (élargir le corpus d'éval — 21 cas est un échantillon faible — puis retravailler la classification "out of scope").
- **Coût** : temps d'ingénierie + coût d'éval (faible, pas de LLM cher nécessaire pour un corpus de test).
- **Gain attendu (estimé)** : réduit le risque que le jury laisse passer des sorties hors-scope non désirées.
- **Priorité : moyenne.**

### B4. Étendre la couverture de tests pytest au-delà des 7 suites actuelles
- **Constat mesuré** : 7 suites réelles sur 275 fichiers Python du cœur.
- **Difficulté** : élevée (volume de travail proportionnel au code non couvert).
- **Coût** : temps d'ingénierie important.
- **Gain attendu (estimé)** : réduit le risque de régressions silencieuses, en particulier dans les modules "V6" qui ont déjà montré des bugs latents.
- **Priorité : moyenne — à prioriser sur les modules les plus utilisés (`edit_pipeline`/`patch_optimizer`, 89,8% des lignes de `forge_agent_metrics.csv`) plutôt qu'une couverture uniforme.**

### B5. Réduire le risque de bus factor
- **Constat mesuré** : 100% des commits par un seul auteur.
- **Difficulté** : dépend de la solution retenue (documentation, onboarding d'un second contributeur, ou accepter le risque en connaissance de cause).
- **Coût** : variable.
- **Gain attendu (estimé)** : continuité du projet en cas d'indisponibilité du mainteneur actuel.
- **Priorité : moyenne — à arbitrer selon les ambitions du projet (outil personnel vs produit à plusieurs mainteneurs).**

## C. Investissements long terme (mois, effort élevé)

### C1. Décider de l'infrastructure GPU seulement après avoir mesuré le volume réel par tâche
- **Constat** : aucune donnée de volume par type de tâche n'existe pour arbitrer objectivement API/VPS/GPU à la demande/GPU permanent/hybride (voir `gpu_infrastructure_model.json`).
- **Difficulté** : élevée (nécessite d'abord l'instrumentation fine des coûts par nœud/tâche).
- **Coût** : variable selon le scénario retenu (0€ pour "API uniquement" à ~184€/mois pour un GPU dédié Hetzner, estimation recherchée).
- **Gain attendu (estimé)** : évite un investissement GPU prématuré tant que le forfait MiMo actuel absorbe le volume — ou au contraire, objective le moment où l'investissement devient rentable.
- **Priorité : basse tant que A1 (confirmation MiMo) n'est pas fait — cette décision dépend directement de A1.**

### C2. Construire une vraie observabilité de charge multi-utilisateur
- **Constat** : `05_STATE/tenants/` existe mais aucune preuve de test en charge concurrente.
- **Difficulté** : élevée.
- **Coût** : variable.
- **Gain attendu (estimé)** : condition nécessaire avant tout scaling au-delà d'un usage personnel (voir `scaling_projection.json`, scénarios 100 et 1000 utilisateurs).
- **Priorité : basse — à traiter seulement si un objectif multi-utilisateur est confirmé.**

### C3. Contractualiser (ou remplacer) la dépendance MiMo
- **Constat** : fournisseur unique, conditions non contractuelles confirmées, instabilité documentée des fallbacks.
- **Difficulté** : élevée (négociation fournisseur ou migration vers un backend alternatif).
- **Coût** : variable.
- **Gain attendu (estimé)** : élimine le point unique de défaillance identifié en risque #2 du `technical_risk_report.md`.
- **Priorité : haute si la Forge doit servir une charge de production critique ; basse pour un usage exploratoire personnel.**

## Résumé priorisé (top 5 à traiter en premier)

1. **A1** — Confirmer prix/quota MiMo réels (débloque toutes les autres décisions financières).
2. **A2** — Corriger ou clarifier l'absence d'`ANTHROPIC_API_KEY`.
3. **B1** — Lancer le protocole A/B applicatif déjà rédigé (transforme une extrapolation en mesure).
4. **B3** — Combler l'angle mort out-of-scope du garde-fou anti-hallucination.
5. **B2** — Décider un niveau de supervision cohérent avec le taux de succès mesuré (1/15) du pipeline autonome.
{
  "meta": {
    "generated_at": "2026-07-22T22:15:25.229423Z",
    "sources": [
      "05_STATE/system_registry/{nodes,edges,capabilities}.json (mesuré, registre interne de la Forge)",
      "requirements.txt (documenté)",
      ".env (noms de clés uniquement, aucune valeur lue)",
      "test_results_FINAL.json (mesuré)",
      "token_comparison_cafe_bastoche/measures/forge_autonomous_debug.md (documenté)"
    ],
    "methodology": "Les 161 entrées de 'components' sont une extraction directe et complète du registre interne de composants de la Forge (05_STATE/system_registry). Les entrées de 'infrastructure_not_in_registry' sont des services/dépendances réels mais absents de ce registre — reconstruits depuis requirements.txt, .env et la documentation. cost_monthly=null partout où aucune facture ou grille tarifaire fixe n'a pu être établie depuis les fichiers du dépôt.",
    "limitations": [
      "Le registre (161 nœuds) ne contient pas de champ 'purpose'/description humaine rempli — 'purpose' est reconstruit à partir de la liste de capabilities associée, peut être imprécis.",
      "cost_monthly est quasi systématiquement null : la Forge fonctionne sur abonnements forfaitaires (Claude, MiMo) et API gratuites (Groq, Gemini free tier), pas sur des coûts par composant individualisés."
    ]
  },
  "summary": {
    "total_registered_components": 161,
    "by_type": {
      "agent": 61,
      "tool": 62,
      "skill": 38
    },
    "by_status": {
      "reference": 2,
      "planned": 1,
      "ready": 31,
      "active": 127
    },
    "total_dependency_edges": 135,
    "total_capabilities_declared": 14,
    "total_registered_code_size_bytes": 1436825,
    "core_python_files_measured": 275,
    "core_python_loc_measured": 69880,
    "core_python_loc_scope": "00_CORE + 01_ORCHESTRATOR + 02_AGENTS + forge_agents(racine) + forge_trading + 03_JURY + 04_GRAPHIFY + 09_WEB + scripts (exclut dépôts vendored : nexus, cvelistV5-main, AsyncHerald, RecursiveMAS, node_modules)"
  },
  "components": [
    {
      "component": "a2a_protocol",
      "type": "agent",
      "purpose": "mcp_integration, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 2677,
      "file_path": "00_CORE\\forge_agents\\a2a_protocol.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "adaptive_rag",
      "type": "agent",
      "purpose": "llm_routing, graph_operations, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "dataset_rag",
        "graphify_checkpointer",
        "openviking",
        "token_tracker"
      ],
      "cost_monthly": null,
      "size_bytes": 9731,
      "file_path": "00_CORE\\forge_agents\\adaptive_rag.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "agency_personas",
      "type": "agent",
      "purpose": "verification, llm_routing, graph_operations, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "forge_db_fallback"
      ],
      "cost_monthly": null,
      "size_bytes": 7173,
      "file_path": "00_CORE\\forge_agents\\agency_personas.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "agent_nodes",
      "type": "agent",
      "purpose": "scraping, llm_routing, graph_operations, embeddings, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "a2a_protocol",
        "adaptive_rag",
        "ail_protocol",
        "anti_hallucination",
        "bbril_pipeline",
        "dataset_rag",
        "evomap_evolve",
        "fallow_guard",
        "forge_llm",
        "forge_state",
        "graphify_checkpointer",
        "harness_engine",
        "kb_manager",
        "lmcache_integration",
        "mirofish",
        "multi_source_brain",
        "nanomachine",
        "neuro_symbolic_guard",
        "nmp_encoder",
        "openviking",
        "ponytail",
        "prompt_architect",
        "scraping_hook",
        "scrapling_connector",
        "token_tracker",
        "tool_batcher",
        "turbovec_brain",
        "zsl_cyber"
      ],
      "cost_monthly": null,
      "size_bytes": 47060,
      "file_path": "00_CORE\\forge_agents\\agent_nodes.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "agent_skills_patterns",
      "type": "agent",
      "purpose": "verification, orchestration, deployment, testing, monitoring",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "anti_hallucination"
      ],
      "cost_monthly": null,
      "size_bytes": 18941,
      "file_path": "00_CORE\\forge_agents\\agent_skills_patterns.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "agent_topology",
      "type": "agent",
      "purpose": "verification, rag, orchestration, deployment, testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4162,
      "file_path": "00_CORE\\forge_agents\\agent_topology.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "ail_protocol",
      "type": "agent",
      "purpose": "llm_routing, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes"
      ],
      "cost_monthly": null,
      "size_bytes": 5036,
      "file_path": "00_CORE\\forge_agents\\ail_protocol.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "anti_hallucination",
      "type": "agent",
      "purpose": "verification",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 21680,
      "file_path": "00_CORE\\forge_agents\\anti_hallucination.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "auto_complexification",
      "type": "agent",
      "purpose": "graph_operations, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "anti_hallucination",
        "forge_state"
      ],
      "cost_monthly": null,
      "size_bytes": 6840,
      "file_path": "00_CORE\\forge_agents\\auto_complexification.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "bbril_pipeline",
      "type": "agent",
      "purpose": "memory, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "nexus_bridge",
        "ponytail"
      ],
      "cost_monthly": null,
      "size_bytes": 22337,
      "file_path": "00_CORE\\forge_agents\\bbril_pipeline.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "cervelet",
      "type": "agent",
      "purpose": "llm_routing",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "forge_llm"
      ],
      "cost_monthly": null,
      "size_bytes": 17226,
      "file_path": "00_CORE\\forge_agents\\cervelet.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "dataset_rag",
      "type": "agent",
      "purpose": "caching, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "adaptive_rag"
      ],
      "cost_monthly": null,
      "size_bytes": 26540,
      "file_path": "00_CORE\\forge_agents\\dataset_rag.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "decepticon_adapter",
      "type": "agent",
      "purpose": "llm_routing",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_llm",
        "ponytail"
      ],
      "cost_monthly": null,
      "size_bytes": 15014,
      "file_path": "00_CORE\\forge_agents\\decepticon_adapter.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "design_assets",
      "type": "agent",
      "purpose": "orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 25102,
      "file_path": "00_CORE\\forge_agents\\design_assets.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "evomap_evolve",
      "type": "agent",
      "purpose": "graph_operations",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4580,
      "file_path": "00_CORE\\forge_agents\\evomap_evolve.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "fallow_guard",
      "type": "agent",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3241,
      "file_path": "00_CORE\\forge_agents\\fallow_guard.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "finetune_pipeline",
      "type": "agent",
      "purpose": "orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "adaptive_rag"
      ],
      "cost_monthly": null,
      "size_bytes": 19750,
      "file_path": "00_CORE\\forge_agents\\finetune_pipeline.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_cache_orchestrator",
      "type": "agent",
      "purpose": "kernel_extraction, mcp_integration, memory, graph_operations, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "forge_kernel",
        "forge_lazy",
        "forge_shared_brain",
        "turbovec_brain"
      ],
      "cost_monthly": null,
      "size_bytes": 15801,
      "file_path": "00_CORE\\forge_agents\\forge_cache_orchestrator.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_checkpoint_engine",
      "type": "agent",
      "purpose": "kernel_extraction, graph_operations, caching, rag, orchestration, testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_graph",
        "graphify_checkpointer",
        "nexus_bridge"
      ],
      "cost_monthly": null,
      "size_bytes": 11229,
      "file_path": "00_CORE\\forge_agents\\forge_checkpoint_engine.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_db",
      "type": "agent",
      "purpose": "graph_operations, caching, embeddings",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db_fallback",
        "semantic_cache"
      ],
      "cost_monthly": null,
      "size_bytes": 21933,
      "file_path": "00_CORE\\forge_agents\\forge_db.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_db_fallback",
      "type": "agent",
      "purpose": "graph_operations, caching",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "semantic_cache"
      ],
      "cost_monthly": null,
      "size_bytes": 6357,
      "file_path": "00_CORE\\forge_agents\\forge_db_fallback.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_event_bus",
      "type": "agent",
      "purpose": "kernel_extraction, mcp_integration, verification, caching, orchestration, monitoring",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11088,
      "file_path": "00_CORE\\forge_agents\\forge_event_bus.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_execution_logger",
      "type": "agent",
      "purpose": "kernel_extraction, graph_operations, caching",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7315,
      "file_path": "00_CORE\\forge_agents\\forge_execution_logger.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_experience_db",
      "type": "agent",
      "purpose": "kernel_extraction, verification, rag",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_llm"
      ],
      "cost_monthly": null,
      "size_bytes": 12950,
      "file_path": "00_CORE\\forge_agents\\forge_experience_db.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_fingerprint",
      "type": "agent",
      "purpose": "llm_routing, caching, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "cervelet",
        "forge_llm"
      ],
      "cost_monthly": null,
      "size_bytes": 12326,
      "file_path": "00_CORE\\forge_agents\\forge_fingerprint.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_graph",
      "type": "agent",
      "purpose": "kernel_extraction, memory, verification, graph_operations, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "anti_hallucination",
        "auto_complexification",
        "forge_cache_orchestrator",
        "forge_checkpoint_engine",
        "forge_db",
        "forge_event_bus",
        "forge_experience_db",
        "forge_kernel",
        "forge_lazy",
        "forge_meta",
        "forge_self_heal",
        "forge_shared_brain",
        "forge_state",
        "graphify_checkpointer",
        "harness_engine"
      ],
      "cost_monthly": null,
      "size_bytes": 23287,
      "file_path": "00_CORE\\forge_agents\\forge_graph.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_kernel",
      "type": "agent",
      "purpose": "kernel_extraction, verification, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11107,
      "file_path": "00_CORE\\forge_agents\\forge_kernel.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_lazy",
      "type": "agent",
      "purpose": "caching",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 9374,
      "file_path": "00_CORE\\forge_agents\\forge_lazy.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_llm",
      "type": "agent",
      "purpose": "llm_routing, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "auto_complexification",
        "cervelet",
        "forge_fingerprint",
        "inference_patch",
        "mirofish",
        "nanomachine",
        "openviking",
        "ponytail",
        "semantic_cache",
        "token_tracker"
      ],
      "cost_monthly": null,
      "size_bytes": 51092,
      "file_path": "00_CORE\\forge_agents\\forge_llm.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_mcp_pruner",
      "type": "agent",
      "purpose": "mcp_integration, llm_routing",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_experience_db"
      ],
      "cost_monthly": null,
      "size_bytes": 10068,
      "file_path": "00_CORE\\forge_agents\\forge_mcp_pruner.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_meta",
      "type": "agent",
      "purpose": "memory, verification, orchestration, monitoring",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11902,
      "file_path": "00_CORE\\forge_agents\\forge_meta.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_no_mistakes",
      "type": "agent",
      "purpose": "rag, orchestration, testing, monitoring",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 17941,
      "file_path": "00_CORE\\forge_agents\\forge_no_mistakes.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_self_heal",
      "type": "agent",
      "purpose": "verification, deployment, testing, monitoring",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11508,
      "file_path": "00_CORE\\forge_agents\\forge_self_heal.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_shared_brain",
      "type": "agent",
      "purpose": "kernel_extraction, mcp_integration, memory, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_kernel"
      ],
      "cost_monthly": null,
      "size_bytes": 19466,
      "file_path": "00_CORE\\forge_agents\\forge_shared_brain.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_state",
      "type": "agent",
      "purpose": "memory, graph_operations, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "auto_complexification",
        "forge_kernel",
        "mirofish",
        "nanomachine"
      ],
      "cost_monthly": null,
      "size_bytes": 11245,
      "file_path": "00_CORE\\forge_agents\\forge_state.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "forge_system_registry",
      "type": "agent",
      "purpose": "mcp_integration, memory, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 10691,
      "file_path": "00_CORE\\forge_agents\\forge_system_registry.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "gen_games",
      "type": "agent",
      "purpose": "llm_routing, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7329,
      "file_path": "00_CORE\\forge_agents\\gen_games.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "graphify_checkpointer",
      "type": "agent",
      "purpose": "memory, graph_operations, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "nexus_bridge",
        "nmp_encoder"
      ],
      "cost_monthly": null,
      "size_bytes": 5127,
      "file_path": "00_CORE\\forge_agents\\graphify_checkpointer.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "harness_engine",
      "type": "agent",
      "purpose": "graph_operations, deployment, testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 42426,
      "file_path": "00_CORE\\forge_agents\\harness_engine.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "inference_patch",
      "type": "agent",
      "purpose": "memory, llm_routing, caching, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_llm"
      ],
      "cost_monthly": null,
      "size_bytes": 17100,
      "file_path": "00_CORE\\forge_agents\\inference_patch.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "kb_manager",
      "type": "agent",
      "purpose": "memory, graph_operations, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "finetune_pipeline",
        "mirofish"
      ],
      "cost_monthly": null,
      "size_bytes": 16999,
      "file_path": "00_CORE\\forge_agents\\kb_manager.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "lmcache_integration",
      "type": "agent",
      "purpose": "llm_routing, caching, rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "mirofish",
        "zsl_cyber"
      ],
      "cost_monthly": null,
      "size_bytes": 10392,
      "file_path": "00_CORE\\forge_agents\\lmcache_integration.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "mirofish",
      "type": "agent",
      "purpose": "rag, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_llm",
        "openviking"
      ],
      "cost_monthly": null,
      "size_bytes": 20274,
      "file_path": "00_CORE\\forge_agents\\mirofish.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "multi_source_brain",
      "type": "agent",
      "purpose": "orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_llm",
        "graphify_checkpointer",
        "nanomachine"
      ],
      "cost_monthly": null,
      "size_bytes": 10141,
      "file_path": "00_CORE\\forge_agents\\multi_source_brain.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "nanomachine",
      "type": "agent",
      "purpose": "orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "forge_graph",
        "forge_state",
        "turbovec_brain"
      ],
      "cost_monthly": null,
      "size_bytes": 11876,
      "file_path": "00_CORE\\forge_agents\\nanomachine.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "neuro_symbolic_guard",
      "type": "agent",
      "purpose": "verification, rag",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 19556,
      "file_path": "00_CORE\\forge_agents\\neuro_symbolic_guard.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "nexus_bridge",
      "type": "agent",
      "purpose": "memory, graph_operations, caching, embeddings, rag, testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "forge_state",
        "graphify_checkpointer",
        "openviking",
        "ponytail",
        "semantic_cache"
      ],
      "cost_monthly": null,
      "size_bytes": 10045,
      "file_path": "00_CORE\\forge_agents\\nexus_bridge.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "nmp_encoder",
      "type": "agent",
      "purpose": "graph_operations, orchestration, testing, monitoring",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 6297,
      "file_path": "00_CORE\\forge_agents\\nmp_encoder.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "openviking",
      "type": "agent",
      "purpose": "memory",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "nexus_bridge"
      ],
      "cost_monthly": null,
      "size_bytes": 1207,
      "file_path": "00_CORE\\forge_agents\\openviking.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "opt_out_manager",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/opt_out_manager.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "pentest_datasets",
      "type": "agent",
      "purpose": "testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 15751,
      "file_path": "00_CORE\\forge_agents\\pentest_datasets.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "ponytail",
      "type": "agent",
      "purpose": "llm_routing, orchestration, testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 2261,
      "file_path": "00_CORE\\forge_agents\\ponytail.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "prompt_architect",
      "type": "agent",
      "purpose": "mcp_integration, llm_routing, graph_operations, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "forge_llm",
        "openviking"
      ],
      "cost_monthly": null,
      "size_bytes": 10466,
      "file_path": "00_CORE\\forge_agents\\prompt_architect.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "rag_anything",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/rag_anything.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research_enrichment",
      "type": "agent",
      "purpose": "mcp_integration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 20534,
      "file_path": "00_CORE\\forge_agents\\research_enrichment.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "reverse_engineering",
      "type": "agent",
      "purpose": "graph_operations, testing",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 25080,
      "file_path": "00_CORE\\forge_agents\\reverse_engineering.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "scraping_hook",
      "type": "agent",
      "purpose": "scraping, llm_routing, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "scrapling_connector"
      ],
      "cost_monthly": null,
      "size_bytes": 3595,
      "file_path": "00_CORE\\forge_agents\\scraping_hook.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "scrapling_connector",
      "type": "agent",
      "purpose": "scraping, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 8011,
      "file_path": "00_CORE\\forge_agents\\scrapling_connector.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "semantic_cache",
      "type": "agent",
      "purpose": "memory, caching",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_db",
        "nexus_bridge",
        "ponytail"
      ],
      "cost_monthly": null,
      "size_bytes": 3467,
      "file_path": "00_CORE\\forge_agents\\semantic_cache.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "token_tracker",
      "type": "agent",
      "purpose": "llm_routing",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "cervelet",
        "forge_llm"
      ],
      "cost_monthly": null,
      "size_bytes": 21831,
      "file_path": "00_CORE\\forge_agents\\token_tracker.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "tool_batcher",
      "type": "agent",
      "purpose": "graph_operations, orchestration",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "agent_nodes",
        "token_tracker"
      ],
      "cost_monthly": null,
      "size_bytes": 6464,
      "file_path": "00_CORE\\forge_agents\\tool_batcher.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "turbovec_brain",
      "type": "agent",
      "purpose": "llm_routing, embeddings",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_state",
        "nexus_bridge"
      ],
      "cost_monthly": null,
      "size_bytes": 11295,
      "file_path": "00_CORE\\forge_agents\\turbovec_brain.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "zsl_cyber",
      "type": "agent",
      "purpose": "embeddings",
      "technology": "Python",
      "status": "active",
      "dependencies": [
        "forge_state",
        "reverse_engineering"
      ],
      "cost_monthly": null,
      "size_bytes": 17601,
      "file_path": "00_CORE\\forge_agents\\zsl_cyber.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "twenty_crm",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/crm/twenty_crm.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "app_catalog",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/catalog/app_catalog.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "openhands",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/dev/openhands.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "langflow",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/ai_workflows/langflow.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "dify",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/ai_workflows/dify.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "coolify",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/delivery/coolify.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "browser_use",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/automation/browser_use.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "stirling_pdf",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/documents/stirling_pdf.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research_sources",
      "type": "tool",
      "purpose": null,
      "technology": null,
      "status": "reference",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "n/a",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "awesome_public_datasets",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "reference",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/turbovec_brain.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "prompt_master",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/prompting/prompt_master.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "mcpify",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/mcp/mcpify.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "public_apis",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/research/public_apis.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "osint_arsenal",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/research/osint_arsenal.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "lmcache",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/lmcache_integration.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "agent_skills",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/agent_skills_patterns.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "svgdoodles",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/design_assets.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "footer_design",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/design_assets.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "design_kb",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/ui/design_kb.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "open_gen_ai",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/generative_media/open_gen_ai.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "opencut",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/generative_media/opencut.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "hyperframes",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/generative_media/hyperframes.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "apptension_saas_boilerplate",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/product_bricks/saas_starters/apptension.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "oss_saas",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/catalog/oss_saas.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "founders_kit",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/research/founders_kit.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "video_rag",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "planned",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/research/video_rag.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "whatsapp_agent",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/outreach/whatsapp_agent.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "snapchat_ads",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/outreach/snapchat_ads.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "metorial",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/mcp/metorial.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "repowise",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/mcp/repowise.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "cashclaw",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "tools/money/cashclaw.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "no_mistakes",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "ready",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 0,
      "file_path": "forge_agents/forge_no_mistakes.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "automation/browser_use",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4257,
      "file_path": "00_CORE\\tools\\automation\\browser_use.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "catalog/app_catalog",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4307,
      "file_path": "00_CORE\\tools\\catalog\\app_catalog.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "catalog/oss_saas",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4213,
      "file_path": "00_CORE\\tools\\catalog\\oss_saas.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "delivery/coolify",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4665,
      "file_path": "00_CORE\\tools\\delivery\\coolify.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "dev/openhands",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 15904,
      "file_path": "00_CORE\\tools\\dev\\openhands.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "mcp/mcpify",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 6649,
      "file_path": "00_CORE\\tools\\mcp\\mcpify.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "mcp/metorial",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 2742,
      "file_path": "00_CORE\\tools\\mcp\\metorial.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "mcp/repowise",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 2321,
      "file_path": "00_CORE\\tools\\mcp\\repowise.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "money/cashclaw",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11957,
      "file_path": "00_CORE\\tools\\money\\cashclaw.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "outreach/snapchat_ads",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7787,
      "file_path": "00_CORE\\tools\\outreach\\snapchat_ads.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "outreach/whatsapp_agent",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 5520,
      "file_path": "00_CORE\\tools\\outreach\\whatsapp_agent.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "prompting/prompt_master",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7150,
      "file_path": "00_CORE\\tools\\prompting\\prompt_master.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research/founders_kit",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3502,
      "file_path": "00_CORE\\tools\\research\\founders_kit.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research/money_scope",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4071,
      "file_path": "00_CORE\\tools\\research\\money_scope.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research/open_osint",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3479,
      "file_path": "00_CORE\\tools\\research\\open_osint.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research/osint_arsenal",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 12327,
      "file_path": "00_CORE\\tools\\research\\osint_arsenal.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research/public_apis",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 6018,
      "file_path": "00_CORE\\tools\\research\\public_apis.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "research/video_rag",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3688,
      "file_path": "00_CORE\\tools\\research\\video_rag.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/ai_workflows/dify",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3907,
      "file_path": "00_CORE\\tools\\product_bricks\\ai_workflows\\dify.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/ai_workflows/langflow",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4500,
      "file_path": "00_CORE\\tools\\product_bricks\\ai_workflows\\langflow.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/crm/twenty_crm",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 5181,
      "file_path": "00_CORE\\tools\\product_bricks\\crm\\twenty_crm.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/documents/stirling_pdf",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 5508,
      "file_path": "00_CORE\\tools\\product_bricks\\documents\\stirling_pdf.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/generative_media/hyperframes",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 9562,
      "file_path": "00_CORE\\tools\\product_bricks\\generative_media\\hyperframes.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/generative_media/opencut",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 2247,
      "file_path": "00_CORE\\tools\\product_bricks\\generative_media\\opencut.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/generative_media/open_gen_ai",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3990,
      "file_path": "00_CORE\\tools\\product_bricks\\generative_media\\open_gen_ai.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/saas_starters/apptension",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 1889,
      "file_path": "00_CORE\\tools\\product_bricks\\saas_starters\\apptension.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/ui/design_kb",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 8359,
      "file_path": "00_CORE\\tools\\product_bricks\\ui\\design_kb.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "product_bricks/ui/shadcn_caller",
      "type": "tool",
      "purpose": null,
      "technology": "Python",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 1247,
      "file_path": "00_CORE\\tools\\product_bricks\\ui\\shadcn_caller.py",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:adapt",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 10141,
      "file_path": "00_CORE\\impeccable\\reference\\adapt.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:animate",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 10359,
      "file_path": "00_CORE\\impeccable\\reference\\animate.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:audit",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 6602,
      "file_path": "00_CORE\\impeccable\\reference\\audit.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:bolder",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 6464,
      "file_path": "00_CORE\\impeccable\\reference\\bolder.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:brand",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11958,
      "file_path": "00_CORE\\impeccable\\reference\\brand.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:clarify",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 10663,
      "file_path": "00_CORE\\impeccable\\reference\\clarify.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:codex",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7019,
      "file_path": "00_CORE\\impeccable\\reference\\codex.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:cognitive-load",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4796,
      "file_path": "00_CORE\\impeccable\\reference\\cognitive-load.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:color-and-contrast",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 5769,
      "file_path": "00_CORE\\impeccable\\reference\\color-and-contrast.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:colorize",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 13461,
      "file_path": "00_CORE\\impeccable\\reference\\colorize.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:craft",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11961,
      "file_path": "00_CORE\\impeccable\\reference\\craft.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:critique",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 38755,
      "file_path": "00_CORE\\impeccable\\reference\\critique.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:delight",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 9720,
      "file_path": "00_CORE\\impeccable\\reference\\delight.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:distill",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 5633,
      "file_path": "00_CORE\\impeccable\\reference\\distill.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:document",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 27825,
      "file_path": "00_CORE\\impeccable\\reference\\document.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:extract",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3307,
      "file_path": "00_CORE\\impeccable\\reference\\extract.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:harden",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 8611,
      "file_path": "00_CORE\\impeccable\\reference\\harden.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:heuristics-scoring",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 8775,
      "file_path": "00_CORE\\impeccable\\reference\\heuristics-scoring.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:hooks",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7479,
      "file_path": "00_CORE\\impeccable\\reference\\hooks.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:init",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 12563,
      "file_path": "00_CORE\\impeccable\\reference\\init.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:interaction-design",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 6575,
      "file_path": "00_CORE\\impeccable\\reference\\interaction-design.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:layout",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 8692,
      "file_path": "00_CORE\\impeccable\\reference\\layout.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:live",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 59666,
      "file_path": "00_CORE\\impeccable\\reference\\live.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:motion-design",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 5784,
      "file_path": "00_CORE\\impeccable\\reference\\motion-design.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:onboard",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7757,
      "file_path": "00_CORE\\impeccable\\reference\\onboard.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:optimize",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7616,
      "file_path": "00_CORE\\impeccable\\reference\\optimize.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:overdrive",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 9015,
      "file_path": "00_CORE\\impeccable\\reference\\overdrive.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:personas",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 7104,
      "file_path": "00_CORE\\impeccable\\reference\\personas.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:polish",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 12938,
      "file_path": "00_CORE\\impeccable\\reference\\polish.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:product",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4763,
      "file_path": "00_CORE\\impeccable\\reference\\product.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:quieter",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4804,
      "file_path": "00_CORE\\impeccable\\reference\\quieter.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:responsive-design",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3461,
      "file_path": "00_CORE\\impeccable\\reference\\responsive-design.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:shape",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 11343,
      "file_path": "00_CORE\\impeccable\\reference\\shape.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:spatial-design",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 3538,
      "file_path": "00_CORE\\impeccable\\reference\\spatial-design.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:teach",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 9178,
      "file_path": "00_CORE\\impeccable\\reference\\teach.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:typeset",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 14293,
      "file_path": "00_CORE\\impeccable\\reference\\typeset.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:typography",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 8269,
      "file_path": "00_CORE\\impeccable\\reference\\typography.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    },
    {
      "component": "skill:ux-writing",
      "type": "skill",
      "purpose": null,
      "technology": null,
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "size_bytes": 4326,
      "file_path": "00_CORE\\impeccable\\reference\\ux-writing.md",
      "source": "measured — 05_STATE/system_registry/nodes.json + edges.json"
    }
  ],
  "infrastructure_not_in_registry": [
    {
      "component": "PostgreSQL + pgvector",
      "type": "database",
      "purpose": "Store unifié état/mémoire (optiforge), embeddings vectoriels",
      "technology": "PostgreSQL, pgvector",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "source": "documented — requirements.txt (psycopg, pgvector), CLAUDE.md",
      "notes": "Coût mensuel dépend de l'hébergement choisi (self-host VPS vs managé) — non mesurable depuis le dépôt."
    },
    {
      "component": "Redis",
      "type": "database",
      "purpose": "Cache / store rapide, checkpoint secours LangGraph",
      "technology": "Redis",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "source": "documented — requirements.txt, .env (REDIS_URL présent)",
      "notes": null
    },
    {
      "component": "LangGraph / LangChain",
      "type": "framework",
      "purpose": "Orchestration des graphes d'agents, checkpointing",
      "technology": "langgraph>=0.2.0, langchain-core>=0.3.0",
      "status": "active",
      "dependencies": [],
      "cost_monthly": 0,
      "source": "documented — requirements.txt",
      "notes": "Open source, coût licence nul. Coût réel = infra qui l'exécute."
    },
    {
      "component": "LangSmith",
      "type": "observability",
      "purpose": "Tracing des appels LLM (@traced sur forge_call)",
      "technology": "langsmith>=0.1.0",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "source": "documented — requirements.txt, .env (LANGSMITH_TRACING/API_KEY/PROJECT présents)",
      "notes": "Plan tarifaire (gratuit vs payant) non identifiable depuis le dépôt — champ manquant : voir missing_data dans le rapport final."
    },
    {
      "component": "MiMo (abonnement forfaitaire)",
      "type": "llm_provider",
      "purpose": "Backend LLM principal des workers routés (hermes), facturation forfaitaire",
      "technology": "API OpenAI-compatible (MIMO_OPENAI_URL) + Anthropic-compatible (MIMO_ANTHROPIC_URL)",
      "status": "active",
      "dependencies": [],
      "cost_monthly": 17,
      "source": "estimation documentée — 08_LOGS/benchmark_pack/README.md et case_study_cafe_bastoche.md citent '~17€/mois fixe' comme info remontée par l'utilisateur, PAS une facture vérifiée",
      "notes": "MONTANT NON CONFIRMÉ. Le quota mensuel annoncé (~11 milliards de tokens, mécanisme de round-up par appel) est explicitement non confirmé dans les logs sources. Demander la facture MiMo réelle avant de baser un devis dessus."
    },
    {
      "component": "DS2API (gateway deepseek-v4)",
      "type": "llm_provider",
      "purpose": "Gateway vers deepseek-v4, modèle le plus utilisé côté workers (455/520 appels observés)",
      "technology": "API custom (.env: DS2API_BASE, DS2API_KEY, DS2API_MODEL, DS2API_HEAVY_MODEL, DS2API_PRO_MODEL)",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "source": "documented — .env keys présentes, forge_llm_calls.csv montre cost_usd=0.0 pour tous les appels ds2api-deepseek-v4",
      "notes": "cost_usd=0.0 dans les logs ne garantit pas la gratuité de ce gateway spécifique — clarifier le modèle de facturation DS2API."
    },
    {
      "component": "Groq (Llama 4 Scout)",
      "type": "llm_provider",
      "purpose": "Fallback LLM gratuit (tier FREE)",
      "technology": "API Groq",
      "status": "active",
      "dependencies": [],
      "cost_monthly": 0,
      "source": "documented — .env (GROQ_API_KEY), requirements.txt notes 'FREE LLM providers'",
      "notes": "Free tier avec limites de rate non quantifiées ici."
    },
    {
      "component": "Google AI Studio (Gemini)",
      "type": "llm_provider",
      "purpose": "Backend Antigravity (33 appels observés, tous 'Gemini 3.5 Flash')",
      "technology": "google-generativeai SDK",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "source": "documented — .env (GOOGLE_AI_STUDIO_KEY), forge_llm_calls.csv",
      "notes": "cost_usd non renseigné dans les logs pour ce provider (colonne vide) — voir quality caveat."
    },
    {
      "component": "Anthropic API directe",
      "type": "llm_provider",
      "purpose": "Tier HAIKU/Claude prévu par le routeur mais non fonctionnel",
      "technology": "anthropic SDK >=0.40.0",
      "status": "broken — non configuré",
      "dependencies": [],
      "cost_monthly": 0,
      "source": "mesuré — test_results_FINAL.json : haiku status=FAILED, erreur 'Could not resolve authentication method'",
      "notes": "AUCUNE ANTHROPIC_API_KEY dans .env (confirmé par token_comparison_cafe_bastoche/measures/forge_autonomous_debug.md). Le tier Haiku planifié par le routeur n'est jamais réellement appelé — voir technical_risk_report.md."
    },
    {
      "component": "OpenHands (agent de code autonome)",
      "type": "tool",
      "purpose": "Exécuteur de code autonome en sandbox Docker, backend du build sans intervention Claude",
      "technology": "ghcr.io/all-hands-ai/openhands:0.54 + runtime:0.54-nikolaik, piloté via LLM_API_KEY/LLM_BASE_URL (MiMo)",
      "status": "active (déployé 2026-07-18)",
      "dependencies": [
        "MiMo (abonnement forfaitaire)"
      ],
      "cost_monthly": null,
      "source": "documented — token_comparison_cafe_bastoche/measures/forge_autonomous_debug.md",
      "notes": "Coût additionnel = coût MiMo déjà compté séparément + coût Docker/CPU local (non mesuré)."
    },
    {
      "component": "Nexus VFS (nexus-ai-fs, turbovec)",
      "type": "storage",
      "purpose": "Système de fichiers virtuel + index vectoriel 4-bit local (zéro GPU), remplace openviking/graphify_checkpointer/semantic_cache JSON",
      "technology": "nexus-ai-fs>=0.1.0, turbovec>=0.1.0",
      "status": "active",
      "dependencies": [],
      "cost_monthly": 0,
      "source": "documented — requirements.txt",
      "notes": "Local, zéro GPU par conception — pas de coût cloud direct."
    },
    {
      "component": "RTK (Rust Token Killer)",
      "type": "tool",
      "purpose": "Compression de la sortie des commandes (60-90% annoncé) avant ingestion LLM",
      "technology": "Binaire Rust (C:/Users/Enzo/.cargo/bin/rtk.exe), wrapper 00_CORE/tools/rtk.py",
      "status": "active",
      "dependencies": [],
      "cost_monthly": 0,
      "source": "documented — CLAUDE.md, 00_CORE/rtk/ (source vendored)",
      "notes": "Le ratio 60-90% est une annonce du projet RTK (rtk-ai/rtk), PAS une mesure locale — voir context_efficiency.json pour ce qui est réellement mesurable depuis tool_calls.csv."
    },
    {
      "component": "GitNexus",
      "type": "tool",
      "purpose": "Index de code (symboles, relations, flux d'exécution) pour navigation/impact analysis",
      "technology": ".gitnexus/ (index local)",
      "status": "active",
      "dependencies": [],
      "cost_monthly": 0,
      "source": "mesuré — index déclaré : 83150 symboles, 111561 relations, 300 flux d'exécution (system prompt CLAUDE Code)",
      "notes": "Local, pas de coût cloud."
    },
    {
      "component": "N8N",
      "type": "tool",
      "purpose": "Automatisation de workflows",
      "technology": ".env (N8N_API_KEY), 00_CORE/n8n/",
      "status": "active",
      "dependencies": [],
      "cost_monthly": null,
      "source": "documented — .env, forge_n8n.py",
      "notes": null
    },
    {
      "component": "Docker / Docker Desktop (WSL2)",
      "type": "infra",
      "purpose": "Sandbox d'exécution pour OpenHands runtime",
      "technology": "Docker",
      "status": "active",
      "dependencies": [
        "OpenHands (agent de code autonome)"
      ],
      "cost_monthly": 0,
      "source": "documented — forge_autonomous_debug.md (docker.sock, SANDBOX_VOLUMES)",
      "notes": "Exécuté en local sur la machine de l'utilisateur — pas de coût cloud direct, coût = ressources machine locale (non mesuré)."
    }
  ],
  "external_vendored_repos": [
    {
      "component": "nexus",
      "type": "vendored_repo",
      "purpose": "Nexus VFS (dépôt git imbriqué, .git propre)",
      "note": "Non inclus dans les stats git log du dépôt principal (gitlink séparé)."
    },
    {
      "component": "AsyncHerald",
      "type": "vendored_repo",
      "purpose": "Système Herald (grading/audit), dépôt git imbriqué"
    },
    {
      "component": "RecursiveMAS",
      "type": "vendored_repo",
      "purpose": "Non documenté dans les fichiers lus — nom explicite seulement"
    },
    {
      "component": "cvelistV5-main",
      "type": "vendored_repo",
      "purpose": "Base CVE (CVE List v5), données publiques MITRE, utilisée par bountyhunter/OSINT"
    }
  ],
  "named_agent_personas_02_AGENTS": [
    "audit_agent",
    "closer_pro",
    "critic",
    "founder_ceo",
    "legal_officer",
    "marketing_digital",
    "prompt_engineer",
    "research",
    "scraper",
    "senior_dev"
  ]
}
{
  "meta": {
    "generated_at": "2026-07-22T22:15:25.229423Z",
    "sources": [
      "08_LOGS/benchmark_pack/case_study_cafe_bastoche.md (mesuré — seul vrai A/B même-tâche existant)",
      "token_comparison_cafe_bastoche/measures/{estimate_A,estimate_B,comparison_report,forge_autonomous_debug}.md (mesuré + estimations a priori documentées)",
      "08_LOGS/tokens/cafe_bastoche_*.json (logs bruts des 15 runs de la série autonome)"
    ],
    "critical_warning": "Il n'existe qu'UNE SEULE tâche avec un vrai A/B comparatif mesuré (site vitrine statique Café Bastoche). Il n'existe AUCUNE tâche applicative comparée (repo réel, tests qui passent/échouent). Toute généralisation au-delà de cette unique tâche est une extrapolation, pas une mesure — elle est marquée comme telle ci-dessous. Un protocole pour un vrai A/B applicatif est proposé mais NON EXÉCUTÉ (voir 'proposed_untested_protocol')."
  },
  "tasks": [
    {
      "task": "cafe_bastoche_site — générer un site vitrine responsive (index.html+style.css+app.js, 6 sections, carte Leaflet/OSM, thème clair/sombre)",
      "task_type": "mesuré — vrai A/B, fichiers livrés conservés sur disque (diffables)",
      "arms": {
        "A_claude_direct": {
          "description": "Claude écrit le code directement dans son contexte, 1 passe, aucun outil Forge.",
          "status": "succès",
          "llm_calls": 1,
          "tokens_input": 4000,
          "tokens_output": 4430,
          "tokens_total": 8430,
          "cost_usd": 0.39,
          "cost_usd_source": "mesuré — tarif Opus appliqué aux tokens réels du fichier livré",
          "lines_delivered": 351,
          "weight_delivered_kb": 17.7,
          "hallucination_guard_passes": 0,
          "invented_facts": 0,
          "files_read": null,
          "files_read_missing_reason": "non tracé dans ce case study (pas de ledger de chemins pour ce run).",
          "duration_wallclock": null,
          "duration_missing_reason": "temps humain/horloge non instrumenté pour ce run (confirmé non mesuré par le pack source).",
          "result": "site livré et vérifié dans un navigateur"
        },
        "B_forge_rescue_claude_guided": {
          "description": "Claude suit le blueprint Forge (guidé), même contexte Claude que A + squelette Forge.",
          "status": "succès",
          "llm_calls": 1,
          "tokens_input": null,
          "tokens_output": null,
          "tokens_note": "inclus dans les mêmes chiffres que A (même contexte Claude) selon le pack source — non décomposé séparément.",
          "cost_usd": 0.39,
          "cost_usd_source": "identique à A selon le pack source (même contexte Claude)",
          "lines_delivered": 540,
          "weight_delivered_kb": 24.8,
          "hallucination_guard_passes": 0,
          "invented_facts": 0,
          "result": "site livré (rescue), sert de comparaison visuelle seulement — son coût n'est pas compté dans les chiffres 'Forge autonome' ci-dessous"
        },
        "B_forge_autonomous_winning_run_oh1": {
          "description": "Agent autonome (OpenHands + MiMo), 0 intervention Claude sur le code — SEUL le run gagnant après 14 échecs.",
          "status": "succès (au 15e essai)",
          "llm_calls": 13,
          "tokens_input": 6428,
          "tokens_output": 6361,
          "tokens_total": 12789,
          "cost_usd": 0.0,
          "cost_usd_note": "0 ligne API facturée au token — coût réel = quote-part de l'abonnement forfaitaire MiMo (~17€/mois, NON CONFIRMÉ), pas un coût marginal nul.",
          "lines_delivered": 2183,
          "weight_delivered_kb": 65.7,
          "hallucination_guard_passes": 1,
          "hallucination_guard_result": "placeholders anti-hallucination respectés (44 placeholders vs 23 pour A)",
          "invented_facts": 0,
          "result": "site complet, 6 sections, carte Leaflet+CartoDB opérationnelle (4 tuiles), 0 erreur console"
        },
        "B_forge_autonomous_full_series_honest_cost": {
          "description": "LE VRAI COÛT du bras autonome : les 14 runs d'échec qui ont précédé le run gagnant oh1, + oh1 lui-même. C'est la métrique que le pack source désigne explicitement comme la colonne 'Gain' honnête, pas le run gagnant seul.",
          "status": "1 succès sur 15 tentatives",
          "runs_total": 15,
          "runs_failed": 14,
          "runs_succeeded": 1,
          "llm_calls_total": 344,
          "tokens_input_total": 281298,
          "tokens_output_total": 245541,
          "tokens_total": 526839,
          "cost_usd": 0.0,
          "cost_usd_note": "idem run gagnant — 0 $ facturé au token, coût réel = forfait MiMo amorti sur l'ensemble de la série, pas 0.",
          "one_time_engineering_cost_not_in_tokens": "3 bugs bloquants dans des modules V6 non testés ont dû être corrigés par Claude (openviking.py, forge_graph.py, auto_complexification.py) pour rendre le pipeline autonome fonctionnel — ce temps de debug Claude n'est PAS mesuré en tokens dans ce pack. C'est un coût d'ingénierie ponctuel (non récurrent), pas un coût par run.",
          "result": "Le pipeline autonome n'a atteint la fiabilité qu'après correction de 3 bugs latents ; le taux de succès observé sur cet échantillon est 1/15 (6.7%)."
        }
      },
      "gain_analysis": {
        "cost_api_gain_pct": 100,
        "cost_api_gain_note": "0 $ facturé au token (Forge, tous runs) vs 0.39 $ (Claude direct, 1 run) — mais ce 0$ est un coût marginal, pas un coût réel (voir forfait MiMo non confirmé).",
        "raw_tokens_consumed_ratio": "4.1x PLUS de tokens bruts côté Forge autonome série complète (526839) que côté Claude direct (8430) pour livrer 1 site — la Forge ne réduit PAS le volume brut de tokens sur cette tâche, elle déplace la charge vers un forfait fixe.",
        "reliability_winner": "Claude direct (succès 1/1, 100%) vs Forge autonome (succès 1/15, 6.7%) sur cet échantillon.",
        "lines_delivered_ratio": "6.2x plus de lignes livrées par le run gagnant Forge autonome (2183) vs Claude direct (351) — mais lignes ≠ qualité/valeur, pas de jugement humain qualitatif disponible dans ce pack.",
        "hallucination_mechanism": "Le jury anti-hallucination de la Forge a un mécanisme actif et vérifié (a réellement rejeté une sortie faible, consensus 0.55 → REVISE, sur un run antérieur B4) — mais aucune réduction du taux d'hallucination n'est mesurée en A/B (0 fait inventé des deux côtés sur cette tâche simple).",
        "verdict_from_source_report": "« Sur cette tâche et cet état du code, la Forge prouve son intérêt structurel (coût nul + off-context + garde-fous jury) mais échoue à livrer de façon fiable en autonome sans correctifs préalables. Claude direct reste plus rapide et plus fiable pour un one-shot simple. »"
      }
    }
  ],
  "proposed_untested_protocol": {
    "status": "PROPOSÉ, NON EXÉCUTÉ — à valider avant lancement",
    "task_candidate": "Ajouter l'authentification OAuth GitHub sur un repo Django réel (~40 fichiers) OU 'corriger les tests cassés' (succès = suite verte, mesurable sans jugement humain)",
    "arm_A": "Session Claude Code neuve, CLAUDE.md minimal, aucun hook/compression/mémoire/routing/skills",
    "arm_B": "CLAUDE_forge.md complet, hooks actifs, routing multi-modèles, compression, mémoire, édition incrémentale",
    "controls": "3 runs par bras, même commit de départ, même heure de la journée, worktree git isolé par run",
    "estimated_cost_to_run": "quelques heures machine, ~5-15 $ d'API sur le bras A (estimation du pack source, non mesurée)",
    "why_not_run_yet": "Nécessite validation utilisateur du choix de tâche + ajout des chemins de fichiers au ledger tool_calls (actuellement absents)."
  }
}
{
  "meta": {
    "generated_at": "2026-07-22T22:15:25.229423Z",
    "sources": [
      "08_LOGS/benchmark_pack/aggregates.json (mesuré — coût réel constaté, $294.98 sur la fenêtre LLM 2026-05-26 -> 2026-07-18, 53 jours)",
      "08_LOGS/benchmark_pack/sessions.csv (mesuré — répartition input/output/cache_read/cache_creation sur échantillon de 15 sessions, utilisée comme proxy de répartition pour les scénarios)"
    ],
    "pricing_source": "Recherche web 2026-07-23 : finout.io, cloudzero.com, metacto.com, benchlm.ai, aifreeapi.com, morphllm.com (agrégateurs de pricing tiers, pas les pages officielles directement citées) — à re-vérifier sur anthropic.com/pricing, openai.com/pricing, ai.google.dev/pricing, platform.deepseek.com avant tout devis contractuel.",
    "critical_caveat": "Le poste dominant mesuré est le cache-read (~96% du volume de tokens sur l'échantillon de 15 sessions), PAS l'input frais. Chaque scénario applique le tarif cache-read réduit (~10% de l'input, convention Anthropic) là où le fournisseur le propose ; pour Google/DeepSeek(pro) où aucune règle de cache-read n'a été confirmée par la recherche, le cache est conservativement traité comme de l'input plein tarif (coût donc SURESTIMÉ pour ces lignes, signalé explicitement par provider ci-dessous).",
    "methodology": "1) Le coût mesuré actuel de $294.98/53j = $5.57/jour sert de base de volume. 2) La répartition in/out/cache_read/cache_creation est fixée à celle observée sur les 15 sessions (échantillon, pas exhaustif). 3) Le volume de tokens journalier implicite est dérivé du coût mesuré via le pricing Anthropic (le provider réellement utilisé côté claude_code, qui porte 99.9% du coût mesuré). 4) Ce volume est ensuite multiplié par 1x/2x/10x/100x et reproje té sur chaque fournisseur candidat."
  },
  "measured_baseline": {
    "total_cost_usd": 294.9759,
    "window_days": 53,
    "daily_cost_usd": 5.57,
    "cost_concentration": "99.87% du coût mesuré ($294.60 / $294.98) provient du provider claude_code (aggregates.json) — les workers routés (hermes, forge) pèsent <0.5% du coût malgré un volume de tokens brut comparable ou supérieur.",
    "important_clarification": "CLAUDE.md stipule explicitement que Claude est consommé via ABONNEMENT forfaitaire, jamais en pay-per-token API. Le champ cost_usd=294.60 des logs claude_code est donc une valeur NOTIONNELLE (coût équivalent calculé au tarif catalogue par le tracker interne, probablement token_tracker.py), PAS une facture réelle. Le coût réel out-of-pocket pour Claude = le prix fixe de l'abonnement (Pro $20/mois, Max 5x $100/mois, ou Max 20x $200/mois selon le plan actif — NON IDENTIFIABLE depuis les logs locaux, à confirmer par l'utilisateur), indépendant du volume consommé jusqu'à la limite du plan."
  },
  "implied_daily_token_volume_at_anthropic_pricing": {
    "note": "Reconstruction du volume journalier moyen de tokens (in/out/cache) qui, au tarif Opus 4.8 catalogue, produirait le coût journalier mesuré — sert de base aux scénarios de scaling.",
    "daily_input_tokens": 2290,
    "daily_output_tokens": 29388,
    "daily_cache_read_tokens": 6789171,
    "daily_cache_creation_tokens": 284968,
    "scale_factor_k_vs_15_session_sample": 0.012
  },
  "scenarios": {
    "current_measured": {
      "volume_multiplier": 1,
      "daily": {
        "anthropic:claude-opus-4.8": 5.57,
        "anthropic:claude-sonnet-4.6": 3.34,
        "anthropic:claude-haiku-4.5": 1.11,
        "openai:gpt-5.5": 5.71,
        "openai:gpt-5.6-terra": 2.86,
        "openai:gpt-5.6-luna": 1.14,
        "google:gemini-3.1-pro": 14.51,
        "google:gemini-3.5-flash": 10.88,
        "google:gemini-3.1-flash-lite": 1.81,
        "deepseek:deepseek-v4-flash": 0.07,
        "deepseek:deepseek-v4-pro": 3.1
      },
      "monthly_30d": {
        "anthropic:claude-opus-4.8": 166.97,
        "anthropic:claude-sonnet-4.6": 100.18,
        "anthropic:claude-haiku-4.5": 33.39,
        "openai:gpt-5.5": 171.38,
        "openai:gpt-5.6-terra": 85.69,
        "openai:gpt-5.6-luna": 34.28,
        "google:gemini-3.1-pro": 435.17,
        "google:gemini-3.5-flash": 326.37,
        "google:gemini-3.1-flash-lite": 54.4,
        "deepseek:deepseek-v4-flash": 2.02,
        "deepseek:deepseek-v4-pro": 93.11
      },
      "annual_365d": {
        "anthropic:claude-opus-4.8": 2031.44,
        "anthropic:claude-sonnet-4.6": 1218.86,
        "anthropic:claude-haiku-4.5": 406.29,
        "openai:gpt-5.5": 2085.07,
        "openai:gpt-5.6-terra": 1042.54,
        "openai:gpt-5.6-luna": 417.01,
        "google:gemini-3.1-pro": 5294.51,
        "google:gemini-3.5-flash": 3970.89,
        "google:gemini-3.1-flash-lite": 661.81,
        "deepseek:deepseek-v4-flash": 24.62,
        "deepseek:deepseek-v4-pro": 1132.89
      }
    },
    "2x": {
      "volume_multiplier": 2,
      "daily": {
        "anthropic:claude-opus-4.8": 11.13,
        "anthropic:claude-sonnet-4.6": 6.68,
        "anthropic:claude-haiku-4.5": 2.23,
        "openai:gpt-5.5": 11.43,
        "openai:gpt-5.6-terra": 5.71,
        "openai:gpt-5.6-luna": 2.29,
        "google:gemini-3.1-pro": 29.01,
        "google:gemini-3.5-flash": 21.76,
        "google:gemini-3.1-flash-lite": 3.63,
        "deepseek:deepseek-v4-flash": 0.13,
        "deepseek:deepseek-v4-pro": 6.21
      },
      "monthly_30d": {
        "anthropic:claude-opus-4.8": 333.93,
        "anthropic:claude-sonnet-4.6": 200.36,
        "anthropic:claude-haiku-4.5": 66.79,
        "openai:gpt-5.5": 342.75,
        "openai:gpt-5.6-terra": 171.38,
        "openai:gpt-5.6-luna": 68.55,
        "google:gemini-3.1-pro": 870.33,
        "google:gemini-3.5-flash": 652.75,
        "google:gemini-3.1-flash-lite": 108.79,
        "deepseek:deepseek-v4-flash": 4.05,
        "deepseek:deepseek-v4-pro": 186.23
      },
      "annual_365d": {
        "anthropic:claude-opus-4.8": 4062.88,
        "anthropic:claude-sonnet-4.6": 2437.73,
        "anthropic:claude-haiku-4.5": 812.58,
        "openai:gpt-5.5": 4170.14,
        "openai:gpt-5.6-terra": 2085.07,
        "openai:gpt-5.6-luna": 834.03,
        "google:gemini-3.1-pro": 10589.03,
        "google:gemini-3.5-flash": 7941.77,
        "google:gemini-3.1-flash-lite": 1323.63,
        "deepseek:deepseek-v4-flash": 49.24,
        "deepseek:deepseek-v4-pro": 2265.78
      }
    },
    "10x": {
      "volume_multiplier": 10,
      "daily": {
        "anthropic:claude-opus-4.8": 55.66,
        "anthropic:claude-sonnet-4.6": 33.39,
        "anthropic:claude-haiku-4.5": 11.13,
        "openai:gpt-5.5": 57.13,
        "openai:gpt-5.6-terra": 28.56,
        "openai:gpt-5.6-luna": 11.43,
        "google:gemini-3.1-pro": 145.06,
        "google:gemini-3.5-flash": 108.79,
        "google:gemini-3.1-flash-lite": 18.13,
        "deepseek:deepseek-v4-flash": 0.67,
        "deepseek:deepseek-v4-pro": 31.04
      },
      "monthly_30d": {
        "anthropic:claude-opus-4.8": 1669.67,
        "anthropic:claude-sonnet-4.6": 1001.8,
        "anthropic:claude-haiku-4.5": 333.93,
        "openai:gpt-5.5": 1713.76,
        "openai:gpt-5.6-terra": 856.88,
        "openai:gpt-5.6-luna": 342.75,
        "google:gemini-3.1-pro": 4351.66,
        "google:gemini-3.5-flash": 3263.74,
        "google:gemini-3.1-flash-lite": 543.96,
        "deepseek:deepseek-v4-flash": 20.24,
        "deepseek:deepseek-v4-pro": 931.14
      },
      "annual_365d": {
        "anthropic:claude-opus-4.8": 20314.38,
        "anthropic:claude-sonnet-4.6": 12188.63,
        "anthropic:claude-haiku-4.5": 4062.88,
        "openai:gpt-5.5": 20850.72,
        "openai:gpt-5.6-terra": 10425.36,
        "openai:gpt-5.6-luna": 4170.14,
        "google:gemini-3.1-pro": 52945.14,
        "google:gemini-3.5-flash": 39708.85,
        "google:gemini-3.1-flash-lite": 6618.14,
        "deepseek:deepseek-v4-flash": 246.21,
        "deepseek:deepseek-v4-pro": 11328.92
      }
    },
    "100x": {
      "volume_multiplier": 100,
      "daily": {
        "anthropic:claude-opus-4.8": 556.56,
        "anthropic:claude-sonnet-4.6": 333.93,
        "anthropic:claude-haiku-4.5": 111.31,
        "openai:gpt-5.5": 571.25,
        "openai:gpt-5.6-terra": 285.63,
        "openai:gpt-5.6-luna": 114.25,
        "google:gemini-3.1-pro": 1450.55,
        "google:gemini-3.5-flash": 1087.91,
        "google:gemini-3.1-flash-lite": 181.32,
        "deepseek:deepseek-v4-flash": 6.75,
        "deepseek:deepseek-v4-pro": 310.38
      },
      "monthly_30d": {
        "anthropic:claude-opus-4.8": 16696.75,
        "anthropic:claude-sonnet-4.6": 10018.05,
        "anthropic:claude-haiku-4.5": 3339.35,
        "openai:gpt-5.5": 17137.57,
        "openai:gpt-5.6-terra": 8568.79,
        "openai:gpt-5.6-luna": 3427.51,
        "google:gemini-3.1-pro": 43516.55,
        "google:gemini-3.5-flash": 32637.41,
        "google:gemini-3.1-flash-lite": 5439.57,
        "deepseek:deepseek-v4-flash": 202.36,
        "deepseek:deepseek-v4-pro": 9311.44
      },
      "annual_365d": {
        "anthropic:claude-opus-4.8": 203143.78,
        "anthropic:claude-sonnet-4.6": 121886.27,
        "anthropic:claude-haiku-4.5": 40628.76,
        "openai:gpt-5.5": 208507.15,
        "openai:gpt-5.6-terra": 104253.58,
        "openai:gpt-5.6-luna": 41701.43,
        "google:gemini-3.1-pro": 529451.39,
        "google:gemini-3.5-flash": 397088.54,
        "google:gemini-3.1-flash-lite": 66181.42,
        "deepseek:deepseek-v4-flash": 2462.09,
        "deepseek:deepseek-v4-pro": 113289.22
      }
    }
  },
  "fixed_subscription_alternative": {
    "claude_subscription_plans_2026": {
      "pro": {
        "usd_per_month": 20,
        "source": "recherche web 2026-07-23 (screenapp.io, appscribed.com, duet.so — agrégateurs, à revérifier sur claude.com/pricing)"
      },
      "max_5x": {
        "usd_per_month": 100
      },
      "max_20x": {
        "usd_per_month": 200
      },
      "current_plan_active": null,
      "current_plan_missing_description": "Non observable depuis les logs locaux — l'utilisateur doit confirmer quel plan est actif pour calculer le coût réel fixe."
    },
    "mimo_subscription": {
      "eur_per_month": 17,
      "confirmed": false,
      "note": "Chiffre remonté dans la documentation interne (case_study_cafe_bastoche.md), explicitement qualifié de NON CONFIRMÉ. Demander la facture MiMo réelle avant tout devis."
    },
    "interpretation": "Si le volume actuel (et même x10) reste sous les plafonds des abonnements Claude/MiMo, le coût réel out-of-pocket est FIXE et bien plus bas que les simulations pay-per-token ci-dessus, qui ne représentent qu'un coût notionnel/de référence. Les simulations pay-per-token deviennent pertinentes surtout au scénario 100x, où le volume dépasserait probablement tout plafond d'abonnement forfaitaire et forcerait un passage à une facturation API réelle ou à une infra dédiée (voir gpu_infrastructure_model.json)."
  }
}