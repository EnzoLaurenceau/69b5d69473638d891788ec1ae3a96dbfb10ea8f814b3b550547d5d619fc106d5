# 🔄 LangGraph — Pipeline Principal

> State machine qui orchestre tous les agents de la Forge.

## Architecture

```
User Task
  → orchestrator_node (budget estimation)
  → dynamic_agent_node (agent creation)
    → adaptive_rag (context)
    → forge_call (LLM)
    → mirofish (jury)
  → post_mortem_node (evaluation)
  → memory_pruner_node (cleanup)
```

## Nodes

| Node | Rôle | Fichier |
|------|------|---------|
| orchestrator_node | Budget, plan selection | agent_nodes.py |
| dynamic_agent_node | Création d'agent dynamique | agent_nodes.py |
| post_mortem_node | Évaluation post-tâche | agent_nodes.py |
| memory_pruner_node | Nettoyage mémoire | agent_nodes.py |
| zsl_analysis_node | Analyse sécurité (si tâche sécurité) | agent_nodes.py |
| neuro_symbolic_verification_node | Vérification logique | agent_nodes.py |
| anti_hallucination_node | Prévention hallucinations | agent_nodes.py |

## ForgeState

```python
class ForgeState(TypedDict):
    task: str                    # Description de la tâche
    findings: list[Finding]      # Trouvailles confirmées
    quality: float               # Score qualité (0-10)
    cycles: int                  # Nombre de cycles
    agents_used: list[str]       # Agents utilisés
    current_agent: str           # Agent actif
    budget_remaining: int        # Tokens restants
    # ... autres champs
```

## Cycle Universel

Chaque node suit ce cycle:
```
[ESTIMATE] → [INIT/Graphify] → [EXECUTE] → [JURY MiroFish] → [STORE/Graphify] → [AUTO-COMPLEXIFICATION] → [REPORT] → [POST-MORTEM]
```

## Routage LLM

```python
# forge_llm.py
from .forge_llm import forge_call, LLMTier

# Tier 0: Cache (0 tokens)
# Tier 1: ds2api (gratuit)
# Tier 2: Backup provider
# Tier 3: Anthropic direct (payant)

result = forge_call(tier=LLMTier.FREE, prompt="...")
```

## Exécution

```bash
# Lancer une tâche
python run_forge.py --task "build landing page" --cycles 5

# Voir le statut
python run_forge.py --status

# Historique
python run_forge.py --history

# Quiet mode (JSON only)
python run_forge.py --task "analyze" --quiet
```

## Fichiers

- `00_CORE/forge_agents/forge_graph.py` — ForgeRunner, state machine
- `00_CORE/forge_agents/agent_nodes.py` — Tous les nodes
- `00_CORE/forge_agents/forge_state.py` — ForgeState, Finding
- `00_CORE/forge_agents/forge_llm.py` — Routage LLM
- `run_forge.py` — CLI entry point

## 🔗 Liens
- [[../forge/index|Forge Index]]
- [[cervelet|Cervelet]]
- [[nmp-protocol|NMP Protocol]]
- [[../agents/index|Agent Performance]]
