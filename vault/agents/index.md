# 🤖 Agents — Performance Index

> Suivi de chaque agent. Historique, scores, prompt adjustments.
> Source: `05_STATE/agent_tracker/`

## 📊 Dashboard

| Agent | Score Moyen | Tendance | Dernière Tâche |
|-------|-------------|----------|----------------|
| senior_dev | — | — | — |
| marketing_digital | — | — | — |
| closer_pro | — | — | — |
| audit_agent | — | — | — |
| founder_ceo | — | — | — |
| research | — | — | — |

> Ce tableau est mis à jour automatiquement par `agent_tracker.py`

## 🔧 Commandes

```bash
# Démarrer le tracking d'une tâche
python 00_CORE/forge_agents/agent_tracker.py start --task "description" --agents senior_dev marketing

# Logger une invocation
python 00_CORE/forge_agents/agent_tracker.py log \
  --agent senior_dev --task "write CSS" \
  --expected "responsive CSS" --actual "main.css written" \
  --score 8.5 --tokens 1200

# Terminer et générer le rapport
python 00_CORE/forge_agents/agent_tracker.py end

# Voir l'historique d'un agent
python 00_CORE/forge_agents/agent_tracker.py history --agent senior_dev

# Voir les ajustements de prompt
python 00_CORE/forge_agents/agent_tracker.py adjust --agent senior_dev

# Générer le contexte à injecter dans le prompt
python 00_CORE/forge_agents/agent_tracker.py inject --agent senior_dev
```

## 📈 Métriques Clés

- **Score**: 0-10, qualité de la production
- **Completion Rate**: % de tâches excellentes ou bonnes
- **Tendance**: improving / stable / declining
- **Token Efficiency**: tokens moyens par invocation

## 🎯 Prompt Adjustments

Quand un agent score < 6.0, le tracker génère automatiquement des ajustements:
- Instructions de précision
- Vérifications de fichiers
- Consignes d'économie de tokens

Ces ajustements sont injectés dans les prompts futurs via `get_agent_context()`.

## 📂 Fichiers

- `05_STATE/agent_tracker/current_task.json` — Tâche en cours
- `05_STATE/agent_tracker/history.json` — Historique (50 dernières tâches)
- `05_STATE/agent_tracker/prompt_adjustments.json` — Ajustements par agent

## 🔗 Liens
- [[../forge/index|Forge Index]]
- [[../forge/prompt-architect|Prompt Architect]]
- [[../forge/harness-engine|Harness Engine]]
