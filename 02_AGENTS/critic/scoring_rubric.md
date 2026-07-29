# CRITIC SCORING RUBRIC

## Critères (chacun /10, moyenne finale)

| Critère         | 0-3               | 4-6                  | 7-10               |
|-----------------|-------------------|----------------------|---------------------|
| source_quality  | Blog anonyme, X   | Medium, Reddit ciblé | arxiv, GitHub, docs |
| recency         | < 2022            | 2022-2023            | 2024-2026           |
| relevance       | Hors sujet        | Partiellement lié    | Directement utile   |
| contradictions  | Contredit >2 srcs | Contredit 1 src      | Cohérent            |
| actionability   | Théorique pur     | Semi-actionnable     | Directement utilisable |

## Décision
- Score < 5.0 → KILL (ne pas indexer)
- Score 5.0-6.9 → PENDING (jury décide)
- Score ≥ 7.0 → CONFIRMED (pré-validé avant jury)

## Caveman output
```
CRITIC CHECK finding=<id> score=<0-10> kill=<true/false> reason="<1 phrase>"
CRITIC DONE alive=<N> killed=<N> avg_score=<score>
```
