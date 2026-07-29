# CLAUDE.md — Portfolio MVP Factory

## Règles absolues
- TOKEN ESTIMATE affiché AVANT chaque séquence projet, sans exception
- Contenu généré (code, copy, docs) → OpenRouter FREE tier via forge_call()
- Claude orchestre uniquement — jamais de génération > 50 lignes en contexte
- Une séquence = un projet = un thread LangGraph isolé
- Jamais deux séquences en parallèle sans confirmation utilisateur

## Modèle & effort
Model   : claude-haiku-4-5 (séquences légères) / claude-sonnet-4-5 (debug complexe)
Effort  : LOW → MEDIUM selon complexité projet
Thinking: OFF par défaut / ON uniquement si architecture ambiguë

## Répertoires
src  : portfolio_structure/TOP_PICKS/
       portfolio_structure/projets/
dst  : mvp_output/{nom_projet}/
       mvp_output/{nom_projet}/LIVRABLE.md
excl : node_modules, .git, __pycache__, bin, obj, cache

## Stacks supportés
React | PHP | Django | .NET | HTML/CSS | Design-only

## Définition MVP livrable
Un projet est 100% livrable si :
  ✅ Il tourne sans erreur (npm start / php -S / python manage.py runserver)
  ✅ Il a un README avec instructions d'installation
  ✅ Il a une page d'accueil ou point d'entrée fonctionnel
  ✅ Aucune dépendance manquante non résolue
  ✅ Grade Herald ≥ B + 0 issues CRITICAL
  ✅ Score MiroFish final ≥ 7.0

## Workflow global

### ÉTAPE 0 — Inventaire et tri (UNE SEULE FOIS)
1. SCAN    → indexer tous les projets dans TOP_PICKS/ + projets/
2. ESTIMATE→ pour chaque projet, calculer TOKEN ESTIMATE de mise en MVP
             Critères : nb fichiers, lignes manquantes, stack, état actuel
3. TRI     → classer du plus léger au plus lourd (tokens croissants)
4. PLAN    → générer docs/mvp_sequencer.md :
             | # | Projet | Stack | État | Est. tokens | Grade Herald initial | Priorité |
5. ⏸ WAIT → confirmation de l'ordre par l'utilisateur

### ÉTAPE N — Séquence projet (répétée pour chaque projet)

  S1. ESTIMATE   → afficher tableau tokens estimés pour CE projet
  S2. AUDIT      → Herald audit (mode cloud si repo GitHub, sinon local Docker)
                   → grade actuel, issues CRITICAL/HIGH, score sécurité
  S3. PLAN       → générer mvp_output/{projet}/PLAN.md
                   → liste actions + fixes Herald obligatoires en tête
  S4. ⏸ WAIT    → validation utilisateur
  S5. IMPLEMENT  → expert dynamique généré sur mesure (voir ci-dessous)
                   → fixes Herald en priorité absolue
                   → complétions via OpenRouter FREE tier
  S6. RE-AUDIT   → Herald re-run → grade final doit être ≥ B
                   → si < B → retour S5 automatiquement
  S7. MIROFISH   → jury 9 personas avec grade Herald injecté dans le state
                   → Security_Herald (poids 1.5) + Slop_Detector (poids 0.8)
                   → score ≥ 7.0 requis
  S8. DELIVER    → générer mvp_output/{projet}/LIVRABLE.md
                   Contenu : score MiroFish, grade Herald, checklist,
                   commande de lancement, fixes appliqués
  S9. ACTUAL     → TOKEN ACTUAL vs ESTIMATE + efficiency score

## Expert dynamique — cœur du système
Pour chaque projet, la Forge génère l'expert idéal à la volée :
  React  → "Tu es un Senior React/Next.js Developer spécialisé SaaS B2B..."
  PHP    → "Tu es un PHP Backend Engineer expert Laravel/Symfony..."
  Django → "Tu es un Django Full-Stack Developer avec expérience MVP..."
  .NET   → "Tu es un C# .NET Engineer expert ASP.NET Core..."
  HTML   → "Tu es un Frontend Developer expert UI/UX conversion..."

Pas de rôles fixes — l'expert est créé sur mesure pour le stack, l'objectif
et les issues Herald détectées.

## Règles de blocage Herald
  Grade < C     → projet bloqué, ne peut pas aller en TOP_PICKS
  Issues CRITICAL → fix obligatoire avant MiroFish
  Secrets exposés → fix immédiat + alerte utilisateur
  Score sécurité pondéré +15% dans score MiroFish final

## Anti-patterns à éviter
  ❌ Modifier plusieurs projets en même temps
  ❌ Générer du code directement dans le contexte Claude
  ❌ Passer à la séquence suivante sans LIVRABLE.md validé
  ❌ Sauter l'étape ESTIMATE ou AUDIT Herald
  ❌ Approuver un livrable avec issues CRITICAL ouvertes
