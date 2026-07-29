# MODEL ROUTING — Matrice d'Optimisation FinOps

Ce fichier définit quel "Tier" de modèle doit être utilisé pour chaque agent afin de minimiser les coûts en tokens (output) et le temps de traitement, tout en maximisant la précision où c'est nécessaire.

## Définition des Tiers

- **Tier HIGH** (ex: Claude 3 Opus / Gemini 1.5 Pro) : Modèle lourd, coûteux. Raisonnement complexe, synthèses difficiles.
- **Tier MEDIUM** (ex: Claude 3.5 Sonnet / Gemini 1.5 Flash-8B) : Modèle équilibré. Très bon rapport qualité/prix pour la logique.
- **Tier LOW** (ex: Claude 3 Haiku / Gemini 1.5 Flash) : Modèle ultra-rapide et très peu cher. Parfait pour les tâches répétitives, le parsing, et les micro-décisions.

## Matrice par Sous-Agent

| Agent / Rôle | Tier Assigné | Fallback Autorisé | Justification |
|--------------|-------------|-------------------|---------------|
| **L1_ORCHESTRATOR** | MEDIUM / HIGH | Aucun | A besoin d'une vision globale, de planifier et de comprendre tout le contexte de la session. |
| **L2_SCRAPER** | LOW | MEDIUM | Tâche purement mécanique (extraction d'info, nettoyage de HTML/Markdown). Ne nécessite pas de "réflexion". |
| **L2_FORMATTING**| LOW | Aucun | Conversion de données structurées. Le modèle le moins cher suffit. |
| **L2_RESEARCH** | LOW | MEDIUM | Scan initial en LOW. Si le score de confiance de la recherche est < 0.6, fallback vers MEDIUM pour approfondir. |
| **L3_JURY_PERSONA**| LOW | Aucun | Les personas (Skeptic, Expert) ont des instructions très strictes et ne renvoient qu'un score et 1 phrase. Parfait pour un modèle LOW. |

## Règle de Fallback

Lorsqu'une tâche assignée à un modèle LOW échoue (ex: Critic score < 5, ou erreur de parsing JSON) :
1. L'Orchestrateur log l'échec dans `08_LOGS/debug/`.
2. L'Orchestrateur relance la tâche avec le modèle de Tier supérieur (MEDIUM) en lui passant l'erreur.
3. Si le MEDIUM échoue, la tâche est tuée et envoyée dans `06_FINDINGS/killed/`.

*Ne jamais commencer une tâche simple (Scraping, Formatting, Jury) avec un modèle MEDIUM ou HIGH.*
