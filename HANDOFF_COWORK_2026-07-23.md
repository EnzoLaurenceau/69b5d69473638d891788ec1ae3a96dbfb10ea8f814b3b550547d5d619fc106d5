# HANDOFF — Reprise Forge par Claude Code

> Généré le 2026-07-23 depuis Cowork. À lire par Claude Code sur le portable Windows
> (`C:\Users\Jack\Documents\LaForge`) pour continuer vers un produit 100% shippable.
> Objectif d'Enzo : faire de la Forge une plateforme d'exécution d'agents shippable à 100%.

---

## 1. Contexte

La Forge locale (tour à la maison) a exporté tout le nécessaire vers le repo git privé
`https://github.com/Leviantan07/forge-core.git` (branche `master`).
Ce dossier `LaForge` était un **snapshot partiel du 22 juin** (49 fichiers). Il a été
**réaligné sur la version récente du repo (22–23 juillet, 684 fichiers)**.

Règle appliquée en cas de conflit : **priorité aux données les plus récentes** (donc le repo gagne).

---

## 2. ✅ Ce qui a DÉJÀ été fait (par Cowork)

1. **Clone du repo privé** `forge-core` (le `GITHUB_TOKEN` du `.env` a dû être élargi :
   il manquait la permission *Contents* — c'est corrigé).
2. **Réalignement de `LaForge` sur le repo** : `.git` installé, dossier = vrai clone git,
   HEAD = `b0a480b` (« chore(repo): rendre la Forge clonable — .gitmodules, état runtime hors git »).
   - Les 31 fichiers de code communs qui différaient ont été remplacés par la version **juillet** (plus récente).
   - Tout le nouveau contenu du repo a été ajouté (02_AGENTS, 03_JURY, 06_FINDINGS, 07_*, 09_*, 10_TRADING, forge_trading, scripts/, vault/, etc.).
3. **Préservé (non touché)** :
   - `.env` et `.env.txt` (secrets, ignorés par git).
   - État runtime local : `05_STATE/**`, `04_GRAPHIFY/checkpoints.db` (le repo les exclut volontairement).
4. **Supprimés** (décision validée par Enzo — retirés dans la version récente de la tour) :
   - `forge_init.py`, `verify.py` (aucun équivalent dans le repo)
   - `install.py` (remplacé par `FORGE_INSTALL.md` + `scripts/`)
   - `setup.bat` (remplacé par `FORGE_SETUP.md` + `start_forge_*.bat`)
   - `00_CORE/forge_agents/forge_dashboard.html` et `forge_visualizer.py`
     (déplacés dans `09_ARCHIVE/dashboard_legacy/` côté repo — ancienne place vidée).
5. **Fix technique** : `git config core.filemode false` (le montage Windows faisait
   apparaître 665 fichiers « modifiés » alors que seul le bit d'exécution changeait — zéro diff de contenu).
6. **Contrôle qualité** : les **291 fichiers Python** (hors vendor/submodules) **compilent sans erreur de syntaxe**.

### État git actuel
- Working tree propre. Seul fichier non suivi : `.claude/settings.json` (config locale).
- Branche `master`, clone **shallow (depth 1)** → pas d'historique complet.

---

## 3. ⛔ Ce qu'il RESTE à faire (à exécuter sur le portable Windows)

Ces étapes n'ont **pas** pu être faites depuis le sandbox Cowork (Python 3.10 sans
Postgres/Redis, et la Forge tourne sur Windows). Ordre recommandé :

### 3.1 Environnement
- [ ] Vérifier **Python ≥ 3.11** (`python --version`). Requis par le projet.
- [ ] `.env` déjà présent — vérifier que les clés nécessaires sont remplies :
      `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` / `CEREBRAS_API_KEY` (Tier 0 gratuit),
      `LANGSMITH_API_KEY`, `GITHUB_TOKEN`, `XIAOMI_API_KEY` + endpoint.
- [ ] (Optionnel) Postgres + Redis pour le store optiforge ; sinon fallback SQLite.

### 3.2 Dépendances
```bash
pip install -r requirements.txt
pip install "scrapling[fetchers]"      # puis: scrapling install
pip install crawl4ai                    # puis: crawl4ai-setup  (installe playwright)
```
> Versions **épinglées** (`==`) dans `requirements.txt`. Si une version n'est pas dispo,
> la corriger dans un commit dédié (avec tests), pas à la volée.

### 3.3 Sous-modules (7, actuellement vides)
Infra (à initialiser) :
```bash
git submodule update --init 00_CORE/rtk nexus AsyncHerald 07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills
```
Offensifs / jailbreak — **décision d'Enzo requise** (non initialisés par défaut) :
`00_CORE/L1B3RT4S`, `00_CORE/G0DM0D3`, `skills/hexstrike-ai`.

> Le clone est shallow. Pour l'historique complet :
> `git fetch --unshallow` (télécharge tout l'historique).

### 3.4 Tests (suite définie dans `pytest.ini`)
```bash
pytest
```
Cibles saines déclarées :
`00_CORE/forge_agents/semantic_edit_engine/test_see.py`,
`00_CORE/forge_agents/test_versioning.py`,
`00_CORE/forge_agents/test_forge_data_scientist.py`,
`forge_trading/tests/test_surface.py`,
`forge_trading/tests/test_strategy_behaviour.py`,
`test_forge_systems.py`, `test_state_isolation.py`, `test_graph_db_escaping.py`.
- [ ] Faire passer la suite au vert. Corriger les imports/deps manquants qui apparaissent.

### 3.5 Smoke run
```bash
python run_forge.py            # démarrage de la Forge
# ou dashboard :
start_forge_dashboard.bat
```
- [ ] Vérifier démarrage sans exception, dashboard accessible, un agent s'exécute de bout en bout.

### 3.6 Finitions shippable
- [ ] Lancer l'audit sécurité mentionné : `python 00_CORE/tools/security_audit.py`.
- [ ] Vérifier la CI : `.github/workflows/ci.yml`.
- [ ] Recréer un `verify.py` si un check de santé unifié est souhaité (l'ancien a été supprimé).
- [ ] Commiter + push une fois vert (le token a désormais les droits).

---

## 4. Périmètre / limite

Aide OK sur toute l'ingénierie légitime : packaging, install, tests, bugs, CI, doc, perf.
Hors périmètre : développer/améliorer des capacités de jailbreak (L1B3RT4S, G0DM0D3) ou
d'exploitation offensive hors scope explicitement autorisé.

---

## 5. Résumé arbo (top-level actuel)

`00_CORE 01_ORCHESTRATOR 02_AGENTS 03_JURY 04_GRAPHIFY 05_STATE(runtime) 06_FINDINGS
07_KNOWLEDGE_BASE 07_REPORTS 09_ARCHIVE 09_EXPERIMENTS 09_TASKS 09_WEB 10_TRADING
forge_agents forge_trading scripts vault site_forge demo_partna nexus AsyncHerald`
+ docs (`FORGE*.md`, `CLAUDE.md`, `AGENTS.md`, `POSITIONING.md`, …)
+ runners (`run_forge.py`, `run_trading.py`, `forge_dispatcher.py`, `start_*.bat`).
