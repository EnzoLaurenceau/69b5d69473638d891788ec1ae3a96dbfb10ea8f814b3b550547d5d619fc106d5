# 🕸️ Code Graph — GitNexus Index

> Visualisation du code source. Symboles, flux, dépendances.
> Source: `.gitnexus/` (SQLite)

## 🔍 Comment ça marche

GitNexus parse le code source et crée un graphe de:
- **Symboles**: fonctions, classes, variables, imports
- **Flux**: qui appelle qui, dans quel ordre
- **Dépendances**: imports, héritages, compositions

## 📊 Commandes

```bash
# Rechercher un symbole
python 00_CORE/forge_agents/nanomachine.py invoke_gitnexus "forge_call"

# Contexte d'un symbole (callers/callees)
python 00_CORE/forge_agents/nanomachine.py gitnexus_context "forge_call"

# Impact analysis (blast radius)
python 00_CORE/forge_agents/nanomachine.py gitnexus_impact "forge_call" --direction upstream
```

## 🏗️ Architecture Indexée

### forge_agents/ (00_CORE/)
| Module | Symboles Principaux | Rôle |
|--------|---------------------|------|
| agent_nodes.py | orchestrator_node, dynamic_agent_node | Orchestration LangGraph |
| forge_graph.py | ForgeRunner | State machine |
| forge_state.py | ForgeState, Finding | Types partagés |
| forge_llm.py | forge_call, LLMTier | Routage LLM |
| cervelet.py | CerveletArtificiel | Réflexes 0 tokens |
| mirofish.py | MiroFishGate | Jury multi-personas |
| harness_engine.py | HarnessEngine | Quality gates |
| adaptive_rag.py | get_adaptive_context | RAG adaptatif |
| multi_source_brain.py | MultiSourceBrainOrchestrator | Données externes |
| nanomachine.py | NMP | Protocole inter-agents |
| prompt_architect.py | forge_prompt_architect | Construction prompts |
| token_tracker.py | get_tracker | Tracking tokens |

### Flux Principal
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

## 🔗 Symboles Clés

### forge_call
- **Fichier**: forge_llm.py
- **Callers**: dynamic_agent_node, orchestrator_node, post_mortem_node
- **Callees**: _call_free, _call_anthropic, cervelet.route_request
- **Impact**: Modifier = affecter TOUS les agents

### ForgeState
- **Fichier**: forge_state.py
- **Callers**: Tous les nodes
- **Fields**: task, findings, quality, cycles, agents_used
- **Impact**: Ajouter un champ = mettre à jour initial_state()

### NMP
- **Fichier**: nanomachine.py
- **Format**: ACTION|SOURCE|TARGET|PAYLOAD
- **Used by**: Tous les agents pour communication inter-agents

## 📂 Fichiers

- `.gitnexus/` — Base SQLite du graphe
- `vault/code-graph/` — Ce dossier (notes Obsidian)

## 🔗 Liens
- [[../forge/index|Forge Index]]
- [[../forge/nmp-protocol|NMP Protocol]]
- [[../agents/index|Agent Performance]]
