# ARCHITECTURE — AGENT WORKFLOW SYSTEM v1.0

## Couches

```
USER MESSAGE
     │
     ▼
[L1] ORCHESTRATEUR          ← 01_ORCHESTRATOR/config.json
     │  caveman (≤150 tok)
     ├──► [L2] SCRAPER       ← 02_AGENTS/scraper/
     ├──► [L2] RESEARCH      ← 02_AGENTS/research/
     ├──► [L2] CRITIC        ← 02_AGENTS/critic/
     │
     ▼
[L3] MIROFISH JURY          ← 03_JURY/personas.json
     │  caveman (≤200 tok/persona)
     ▼
[L0] GRAPHIFY GRAPH         ← 04_GRAPHIFY/graph.json
     │  71.5x compression
     ▼
[ALGO] AUTO-COMPLEXIFICATION ← 05_STATE/checkpoint.json
```

## Niveaux de complexité

| Niveau | Débloqué | Agents | Sources | Jury |
|--------|----------|--------|---------|------|
| L1 BASIC | Toujours | Scraper+Research+Critic | 4 | 3 personas |
| L2 INTERMEDIATE | 3 cycles stables | + Sub-orch | 8 | 5 personas |
| L3 ADVANCED | L2 quality_gain×2 | + Specialist/domaine | récursif | 7 personas |
| L4 EXPERT | findings≥10 + ratio≥50x | Swarm parallèle | illimité | full MiroFish |

## Flux de données (token-first)

```
Scraping brut → graphify_index() → 04_GRAPHIFY/
                                        ↓
                              graphify_query() → agents
                                        ↓
                              06_FINDINGS/ (confirmed/pending/killed)
```
