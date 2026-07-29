# TOKEN BUDGET — Configuration par phase

## Répartition par défaut (100% du budget)

| Phase       | % Budget | Usage                          |
|-------------|---------|-------------------------------|
| Scraping    | 40%     | ctx_batch_execute, fetch       |
| Research    | 20%     | graphify_query, synthesis      |
| Critic      | 10%     | scoring, kill decisions        |
| Jury        | 15%     | MiroFish personas × rounds     |
| Algo/Verify | 15%     | regression check, evolution    |

## Graphify — économies réelles

| Mode                | Tokens/req | vs fichiers bruts |
|---------------------|-----------|-------------------|
| graphify_query      | ~700      | 71.5x moins       |
| graphify wiki page  | ~1 200    | 40x moins         |
| graphify explain    | ~300      | 150x moins        |
| Fichiers bruts      | ~50 000   | baseline          |

## Règle absolue
Ne jamais passer de fichier brut à un agent.
Toujours : indexer d'abord → requêter ensuite.
