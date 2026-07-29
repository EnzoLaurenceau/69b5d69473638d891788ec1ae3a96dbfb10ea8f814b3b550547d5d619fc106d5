# AGENTS.md — 09_EXPERIMENTS/website_ab

## Purpose
Banc A/B mesurant l'**autonomie** d'un agent (avec vs sans forge) sur la création
d'un site web, tracé LangSmith. Voir `README.md`.

## Local Contracts
- `BRIEF.md` = entrée unique, identique aux 2 bras. **Ne pas y ajouter d'indices**
  sur les tâches implicites, ça invaliderait la mesure.
- Bras + projets LangSmith : `nu` → `ab-website-nu`, `forge` → `ab-website-forge`.
- `grade.py` = scoring déterministe (0 LLM). Toute tâche implicite nouvelle = un
  check pondéré ; garder `--demo` vert.
- Sorties jetables dans `builds/` (ne pas versionner les builds).

## Work Guidance
- Harness symétrique : seul le cerveau change, jamais le protocole d'écriture.
- forge = pile LLM (`forge_call`/`forge_orchestrate`), pas le graphe complet (cf. README §Limite).

## Verification
- `python grade.py --demo` (self-check grader)
- Un run réel nécessite `ANTHROPIC_API_KEY` + `LANGSMITH_*` dans la racine `.env`.
