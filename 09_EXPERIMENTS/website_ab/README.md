# Cas d'étude A/B — Autonomie sur la création de site web

**Question testée :** jusqu'où un agent, **avec** vs **sans** forge, va-t-il de lui-même
sur les tâches jamais demandées mais attendues d'un vrai site (RGPD, SEO, a11y,
carte, responsive…) — les deux bras tracés par LangSmith.

## Design

| | Bras **NU** | Bras **FORGE** |
|---|---|---|
| Cerveau | Claude nu (SDK anthropic) | `forge_orchestrate` (recrute un expert) + `forge_call` (RTK/cache/tiers/nano) |
| Règles | aucune (0 CLAUDE.md, 0 gate) | pile LLM forge réelle |
| Projet LangSmith | `ab-website-nu` | `ab-website-forge` |
| Entrée | `BRIEF.md` (identique) | `BRIEF.md` (identique) |
| Sortie | `builds/nu/` | `builds/forge/` |

Le **protocole d'écriture de fichiers est identique** aux deux bras — c'est de la
plomberie neutre, pas un indice métier. Seul le cerveau diffère. C'est ça qui rend
la compa honnête.

Le **brief est volontairement sous-spécifié** : il donne l'adresse, les horaires, le
tél/mail et demande "réserver un créneau". Il ne dit **rien** du reste. Tout le reste
= le test d'autonomie.

## Ce qu'on mesure

- **Coût / effort** (LangSmith) : tokens in/out, latence, coût, nb d'appels.
- **Autonomie** (`grade.py`, déterministe, 0 LLM) : score /100 sur 16 tâches
  **implicites** — pondérées. Extrait :
  - fort poids : RGPD/mentions légales (4), SEO meta (3), responsive (3), carte OSM (3)
  - moyen : dark mode, OpenGraph, alt img, labels form, validation form, 404, consentement cookies
  - faible : favicon, `lang`, robots/sitemap, HTML sémantique, pas de localStorage
  - *(les items EXPLICITES — NAP, formulaire de réservation — sont vérifiés en sanity mais ne comptent PAS dans l'autonomie)*

## Lancer

```powershell
# 0. self-check du grader (aucune clé requise)
python grade.py --demo

# 1. les deux bras (nécessite ANTHROPIC_API_KEY + LANGSMITH_* dans la racine .env)
python run_ab.py --arm nu
python run_ab.py --arm forge

# 2. scorer l'autonomie de chaque build
python grade.py builds/nu
python grade.py builds/forge

# 3. tableau comparatif (LangSmith + autonomie)
python pull_metrics.py --since 2h
```

Pour une compa **propre**, aligne `--model` du bras nu sur le modèle réel du tier
`SONNET` du forge (cf. `00_CORE/forge_agents/forge_llm.py`).

## Limite assumée (v1)

Le bras forge exerce la **pile LLM du forge** (routeur, tiers, RTK, cache, expert
recruté), pas le **graphe LangGraph complet** ni les gates bloquants (legal_check,
Herald). Si tu veux tester la machine entière, lance en plus :
`python ../../run_forge.py --task "site web L'Atelier Roue Libre" --desc "$(cat BRIEF.md)"`
et compare — mais le forge est orienté *findings*, il n'écrit pas forcément les
fichiers du site, d'où ce harness symétrique par défaut.

## Interpréter

- `autonomy(forge) >> autonomy(nu)` à coût comparable → la forge pousse l'agent vers
  le "vrai site" sans qu'on le demande. C'est la thèse.
- `autonomy` proche mais `tokens(forge) < tokens(nu)` → l'apport forge est surtout
  l'efficience tokens, pas l'autonomie.
- `autonomy(nu)` déjà haut → Claude nu est déjà bon élève ; l'écart forge est ailleurs.
