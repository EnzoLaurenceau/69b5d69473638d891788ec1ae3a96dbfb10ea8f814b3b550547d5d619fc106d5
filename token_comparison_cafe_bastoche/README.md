# Test comparatif de tokens — Café Bastoche (Ixelles)

Objectif : quantifier l'optimisation tokens, la précision anti-hallucination et le
gain de « réflexion » de **La Forge** vs **Claude basique**, sur une même tâche.

## Tâche unique (identique aux 2 versions)
> Générer un site web responsive, design ultra-moderne, pour le **Café Bastoche** à **Ixelles** (Bruxelles).

## Les 2 bras de l'expérience

| | Version A — SANS Forge | Version B — AVEC Forge |
|---|---|---|
| Règles suivies | `claude_baseline.md` (Claude par défaut, minimal) | `CLAUDE.md` de la Forge (blueprint, délégation, jury) |
| Qui écrit le code | Claude directement dans son contexte | Experts dynamiques via `forge_call` (tier FREE/Haiku) |
| Observabilité | LangSmith (log manuel du run) | LangSmith auto (`@traced` sur `forge_call`) |
| Anti-hallucination | aucune passe dédiée | jury MiroFish + audit Herald |
| Sortie | `site_A_sans_forge/` | `site_B_avec_forge/` |

## Protocole
1. **PLAN** (ce doc).
2. **ESTIMATE** avant chaque bras → `measures/estimate_A.md`, `measures/estimate_B.md`.
3. **RUN A** : Claude écrit le site en direct (chemin coûteux = baseline).
4. **RUN B** : `python run_forge.py --task "..."` (après `--bootstrap` / `--db-status`).
5. **FACT-CHECK** : tokens réels des 2 bras + traces LangSmith → `measures/comparison_report.md`.

## Métrique clé
Ce qui est mesuré, ce n'est pas « qui écrit le plus beau site », mais :
- **Tokens contexte Claude** (tier cher) consommés par bras.
- **% de génération déportée** sur modèles FREE/cheap (Forge).
- **Écart estimate → actual** (précision de la prévision = anti-dérive).
- **Passes anti-hallucination** appliquées (0 vs jury+audit).

## Note honnêteté données
Le Café Bastoche : coordonnées/horaires réels non vérifiés → toutes les données
factuelles du site sont marquées `data-placeholder` et à confirmer par le client.
C'est volontaire : ne pas inventer de fait = partie de ce qu'on mesure.
