# Routage modèles Claude — "pile poil sa tâche, rien d'overkill"

> MAJ 2026-06-16. Source de vérité : `00_CORE/forge_agents/forge_llm.py`
> (`CLAUDE_TASK_MODEL` + `claude_model_for_task()`).

## Deux couches distinctes
1. **Main d'œuvre (automatisée)** → cascade **OpenRouter gratuite** (`_call_anthropic` → free models). C'est le défaut de la Forge : *aucun appel direct à l'API Anthropic*. Zéro coût.
2. **Cerveau (Claude réel)** → quand TU utilises Claude (Claude Code / API) pour la Forge. C'est ici que le routage ci-dessous s'applique.

## Table de routage (Claude réel) — `claude_model_for_task(task_type)`

| Tâche | Modèle | $/1M (in/out) | Pourquoi |
|-------|--------|---------------|----------|
| `plan` / `implementation_plan` / `orchestrate` / `architect` / `critique` / `audit` | **claude-opus-4-8** | 5 / 25 | Raisonnement lourd. **Opus 4.8 = UNIQUEMENT le plan d'implémentation complet** + orchestration/audit. |
| `build` / `code` / `refactor` / `debug` / `research` / `market_scan` / général | **claude-sonnet-4-6** | 3 / 15 | Workhorse exécution/code/recherche. Défaut. |
| `extract` / `format` / `score` / `classify` / `summarize` / `translate` / `write_*` | **claude-haiku-4-5** | 1 / 5 | Rapide & pas cher. Pas de raisonnement requis. |
| trivial (`jury`, signaux) | **FREE** (OpenRouter) | 0 | Jamais de Claude payant. |

Défaut si inconnu : **Sonnet 4.6** (jamais Opus — pas d'overkill).

## Thinking (règles dures — cf. skill claude-api)
- **Opus 4.8 / Sonnet 4.6** : thinking **adaptatif** uniquement → `thinking={"type":"adaptive"}`. `budget_tokens` = **erreur 400**. Effort plan via `output_config={"effort":"high"}`.
- **Haiku 4.5** : pas de thinking, pas d'`effort`.
- Réservé Opus : effort `high` (défaut). `xhigh`/`max` seulement si correction > coût.

## ⚠️ Limite — auto-routing dans Claude Code
Une session Claude Code **ne change pas son propre modèle à la volée** : le modèle est choisi par l'utilisateur (`/model`) ou le harness. Donc :
- Cette politique **dit quel modèle choisir** par tâche (lisible par toi + tout chemin API).
- Pour un vrai routage automatique modèle-par-appel, il faut le chemin **API Anthropic direct** (dormant par design — la Forge route tout en gratuit). `ANTHROPIC_MODELS` + `THINKING_MODE` sont maintenant corrects si ce chemin est réactivé.
- En pratique : **Opus 4.8 pour générer le plan**, puis bascule (`/model sonnet`) pour l'implémentation, Haiku pour l'extraction/formatage.
