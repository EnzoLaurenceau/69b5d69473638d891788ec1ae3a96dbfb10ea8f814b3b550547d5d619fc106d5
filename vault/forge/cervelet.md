# 🧠 Cervelet — Reflexive Routing

> Route les requêtes AVANT tout appel LLM. Si un réflexe est ancré → 0 token.

## Principe

Le cervelet (cerveau réflexif) intercepte les token-IDs avant chaque appel LLM.
Si le pattern est connu (vu ≥ 3 fois) → retourne le résultat directement.

**Gain**: 0 token LLM pour les tâches répétitives.

## Token-ID Protocol

```
Format: "<target>#<action_id>:<arg1>,<arg2>"
Exemple: "200#10:3500,1200" → target 200, SUBTRACT, 3500-1200
```

### Action Codes
| Code | Action | Exemple |
|------|--------|---------|
| 10 | SUBTRACT | 3500-1200 = 2300 |
| 11 | ADD | 3500+1200 = 4700 |
| 12 | RATIO | 3500/1200 = 2.9167 |
| 13 | CLAMP | min=0, max=v2 |

## Flux

```
Task → route_request(task)
  → Match token-ID pattern?
    → OUI + reflex_weight ≥ threshold → RÉSULTAT (0 LLM)
    → NON → ESCALATE → LangGraph pipeline
```

## Système Homéostatique

Le cervelet maintient un état interne:
- **Budget restant**: tokens LLM disponibles
- **Ratio succès**: affecte l'humeur
- **Niveau anxiété**: "Élevée" si budget < 20, "Basse" sinon
- **Survie critique**: budget < 5

### Humeurs
| Humeur | Condition | Effet |
|--------|-----------|-------|
| Créative | ratio > 0.8 | Explore plus |
| Prudente | ratio ≤ 0.8 | Conserve budget |
| Stressée | budget < 20 | Réflexes prioritaires |
| Critique | budget < 5 | Mode survie |

## Poids Synaptiques

Les réflexes se renforcent avec les succès, s'affaiblissent avec les erreurs:

```python
# Renforcer après succès
reflex.weight += 0.1 * (1 - reflex.weight)

# Affaiblir après erreur
reflex.weight *= 0.9
```

## Fichiers

- `00_CORE/forge_agents/cervelet.py` — SystèmeHoméostatique + CerveletArtificiel
- `.nexus/cervelet_state.json` — Réflexes persistés

## 🔗 Liens
- [[../forge/index|Forge Index]]
- [[nmp-protocol|NMP Protocol]]
- [[langgraph|LangGraph]]
