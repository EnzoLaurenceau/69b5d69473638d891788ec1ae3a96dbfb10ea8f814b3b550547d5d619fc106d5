# 📜 HistoGPT — Historique des Interactions LLM

> Journal de bord de toutes les interactions avec les LLMs.
> Ce qui a marché, ce qui a foiré, les patterns à réutiliser ou éviter.
> Source: sessions Hermes, DeepSeek chats, forge_call logs.

## 🎯 Objectif

Tracker l'évolution de l'utilisation des LLMs pour:
- Identifier les patterns efficaces
- Éviter de répéter les erreurs
- Optimiser les prompts au fil du temps
- Comprendre les forces/faiblesses de chaque modèle

## 📊 Modèles Utilisés

| Modèle | Provider | Usage | Force | Faiblesse |
|--------|----------|-------|-------|-----------|
| hermes-3-llama-3.1-405b | Nous Research | Forge principale | Raisonnement, code | Lent, coûteux |
| mimo-v2.5-pro | Xiaomi | Sessions Hermes | Rapide, gratuit | Moins profond |
| deepseek-v4-flash | DeepSeek (ds2api) | Tâches simples | Gratuit, rapide | Limité |
| deepseek-v4-pro | DeepSeek (ds2api) | Tâches complexes | Raisonnement avancé | Rate limit |
| claude-sonnet-4 | Anthropic | Code, architecture | Précision, structure | Payant |
| claude-haiku | Anthropic | Tâches légères | Ultra-rapide | Simple |

## 📈 Statistiques Globales

> Mis à jour automatiquement par le token tracker

| Métrique | Valeur |
|----------|--------|
| Sessions totales | — |
| Tokens utilisés | — |
| Coût estimé | — |
| Tâches complétées | — |
| Score moyen | — |

## 📝 Journal des Interactions

### Format d'Entrée

```markdown
## [Date] — Titre de la session

**Modèle**: deepseek-v4-pro
**Tâche**: description courte
**Tokens**: input/output
**Durée**: Xmin
**Score**: X/10

### Ce qui a marché
- Point 1
- Point 2

### Ce qui a foiré
- Point 1
- Point 2

### Leçons
- Leçon 1
- Leçon 2

### Prompt efficace
```
prompt qui a bien marché
```

#interaction #modèle #succès #échec
```

---

### 2026-07-17 — Activation Forge + Agent Tracker

**Modèle**: mimo-v2.5-pro
**Tâche**: Implémenter agent tracker + vault Obsidian + dashboard
**Tokens**: ~15K
**Durée**: ~10min
**Score**: 9/10

#### Ce qui a marché
- Architecture agent_tracker.py avec NMP encoding
- Vault structure complète avec templates
- Dashboard integration avec "open in new tab"
- GitNexus → vault sync script

#### Ce qui a foiré
- Rien de majeur

#### Leçons
- Toujours py_compile après chaque fichier
- Les vault markdown = connaissance persistante, pas contexte éphémère
- Agent tracker = feedback loop pour améliorer les prompts

#### Prompt efficace
```
si jamais j'effectue une tache impliquant plusieurs agent je veux avoir la possibilité de tracker a la fin de la tache si chaque agent a bien fais ce qu'il devait faire
```
→ Clair, spécifique, orienté résultat

---

### 2026-06-18 — Intégration DS2API

**Modèle**: mimo-v2.5-pro
**Tâche**: Intégrer ds2api comme provider LLM principal
**Tokens**: ~50K
**Durée**: ~30min
**Score**: 8/10

#### Ce qui a marché
- Bootstrap automatique au premier forge_call
- Rate limiting conservateur (6 req/min)
- Fallback chain: ds2api → backup → error

#### Ce qui a foiré
- OpenViking import cassé après refactor
- 00_CORE/__init__.py manquant
- autonomous_monitor.py import nmp_encoder path

#### Leçons
- Toujours vérifier les imports après refactor
- Les packages Python ont besoin de __init__.py
- sys.path.insert pour les imports relatifs

---

### 2026-06-16 — OptiForge Activation

**Modèle**: mimo-v2.5-pro
**Tâche**: Activer le profil forge avec OptiForge
**Tokens**: ~140K (avant transfer)
**Durée**: ~2h
**Score**: 7/10

#### Ce qui a marché
- Session transfer brief
- Tool index seed
- Caveman mode

#### Ce qui a foiré
- 140K tokens brûlés avant de réaliser le ceiling
- Fichiers JSON pas en NMP
- Stale task logs causant boucle infinie

#### Leçons
- TOUJOURS reset les task logs au démarrage
- NMP pour les JSON = 70-80% d'économie
- Le ceiling existe pour une raison

---

## 🔧 Patterns Efficaces

### 1. Caveman Mode
```
Fragments. Pas de phrases complètes.
Zéro filler. Direct au but.
→ Économie: ~40% de tokens
```

### 2. NMP Protocol
```
ACTION|SOURCE|TARGET|PAYLOAD
→ Économie: 70-80% vs verbose français
```

### 3. Stateless One-Shot
```
Chaque appel LLM = atomique
State → JSON, pas dans le contexte
→ Pas d'accumulation de contexte
```

### 4. Tool Index Lookup
```
Avant chaque tâche: python tool_index.py lookup "..."
Si outil indexé trouvé → l'utiliser
→ Économie: 30-90% selon l'outil
```

### 5. Map-Reduce
```
Tâche > 65K → forge_dispatcher.py découpe
Chaque sous-tâche = session fraîche
→ Pas de contexte accumulé
```

## ❌ Anti-Patterns

### 1. Verbose French entre agents
```
❌ "J'ai analysé le programme et j'ai trouvé..."
✅ "INIT|ORCHESTRATOR|analysis|target=program_X"
```

### 2. Lire des fichiers entiers
```
❌ read_file(path)  # tout le fichier
✅ read_file(path, offset=100, limit=50)  # ciblé
```

### 3. Garder l'état dans le contexte
```
❌ "Souviens-toi que dans l'étape précédente..."
✅ Écrire dans 05_STATE/*.json, lire au besoin
```

### 4. Ignorer le tool index
```
❌ Coder from scratch
✅ python tool_index.py lookup "..." → réutiliser
```

### 5. Dépasser le ceiling
```
❌ Continuer à 60K tokens
✅ Générer brief + /new
```

## 📊 Métriques par Modèle

### Efficacité (tokens/tâche)
| Modèle | Petite | Moyenne | Grosse |
|--------|--------|---------|--------|
| mimo-v2.5-pro | 2K | 10K | 30K |
| deepseek-v4-flash | 1K | 5K | 15K |
| deepseek-v4-pro | 3K | 15K | 45K |
| claude-sonnet-4 | 2K | 8K | 25K |

### Qualité (score moyen)
| Modèle | Code | Analyse | Créatif |
|--------|------|---------|---------|
| mimo-v2.5-pro | 7.5 | 8.0 | 7.0 |
| deepseek-v4-pro | 8.5 | 9.0 | 8.0 |
| claude-sonnet-4 | 9.0 | 8.5 | 7.5 |

## 🎯 Objectifs d'Optimisation

- [ ] Réduire tokens moyens par tâche de 20%
- [ ] Atteindre 80% de tâches avec score ≥ 8/10
- [ ] Zéro dépassement de ceiling
- [ ] 100% des JSON en NMP
- [ ] Tool index lookup avant chaque tâche

## 🔗 Liens

- [[../forge/index|Forge Index]]
- [[../agents/index|Agent Performance]]
- [[../personal/deepseek-notes|DeepSeek Notes]]
- [[nmp-protocol|NMP Protocol]]

#histoGPT #interaction #optimization #llm
