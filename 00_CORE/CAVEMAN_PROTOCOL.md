# CAVEMAN PROTOCOL — Format inter-agents

## Syntaxe
```
<AGENT_ID> <VERB> <OBJECT> [key=value ...]
```

## Budget par émetteur

| Émetteur              | Max tokens | Format        |
|-----------------------|-----------|---------------|
| Orchestrateur → Agent | 150       | caveman       |
| Agent → Orchestrateur | 200       | caveman       |
| Agent ↔ Agent         | 100       | caveman pur   |
| Jury → Orchestrateur  | 300       | caveman + list|
| Algo → Tous           | 150       | caveman       |
| Système → User        | 1 ligne   | prose courte  |

## Exemples valides
```
SCRAPER DONE sources=47 nodes=312 tokens_saved=68x
RESEARCH FOUND insight=f-042 confidence=0.87 graph_node=n-107
CRITIC KILL finding=f-019 reason="source_quality<3"
JURY VERDICT top3=[f-042,f-017,f-091] consensus=0.82
ALGO EVOLVE rule=skip_layer3_if_confidence>0.9 delta_tokens=-340
ORCH CYCLE_END #3 findings=8 budget_used=62% next=auto
```

## Règles
- CAVEMAN ON dès début de session
- CAVEMAN OFF uniquement pour rapport final user
- Jamais de prose dans les messages inter-agents
- Jamais de raw output dans le contexte principal
- **FINOPS : Interdiction absolue de courtoisie ("Bonjour", "Voici"). 0 token inutile.**
- **FINOPS : Output strictement typé (JSON ou structure Caveman brute).**
- **FINOPS : Préfixes standards obligatoires : [REQ], [ACK], [RES], [ERR].**
