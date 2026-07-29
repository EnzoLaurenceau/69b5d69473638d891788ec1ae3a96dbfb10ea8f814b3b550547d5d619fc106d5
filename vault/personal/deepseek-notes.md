# 💬 DeepSeek Chat Notes

> Conversations avec DeepSeek. Extraits, idées, réflexions.
> DeepSeek est mon LLM personnel (gratuit via web chat).

## 📌 Pourquoi DeepSeek

- **Gratuit** via web chat (pas d'API payante)
- **Raisonnement** niveau Sonnet pour les tâches complexes
- **Vitesse** excellente pour les tâches simples
- **ds2api** intégré à la Forge comme provider principal

## 📝 Notes par Sujet

### Code & Développement
> Extraits de conversations sur le code, architectures, debugging.

```
[Sujet]
Date: YYYY-MM-DD
Contexte: ...
Réponse DeepSeek: ...
Mes notes: ...
```

### Idées & Créativité
> Brainstorming, idées de projets, réflexions personnelles.

```
[Sujet]
Date: YYYY-MM-DD
Idée: ...
Développement: ...
```

### Apprentissage
> Concepts appris, tutoriels, explications.

```
[Concept]
Date: YYYY-MM-DD
Explication: ...
Ma compréhension: ...
```

## 🔧 Intégration avec la Forge

DeepSeek est intégré via **ds2api** (proxy web → API OpenAI-compatible):
- **Provider principal** dans forge_llm.py
- **Rate limit**: 6 req/min, burst 2
- **Modèles**: deepseek-v4-flash (simple), deepseek-v4-pro (complex)
- **Bootstrap automatique** au premier forge_call()

```bash
# Vérifier que ds2api tourne
curl -s http://localhost:5001/healthz

# Lister les modèles disponibles
curl -s http://localhost:5001/v1/models
```

## 📋 Template de Note

```markdown
## [Titre de la conversation]

**Date**: YYYY-MM-DD
**Sujet**: ...
**Modèle**: deepseek-v4-flash / deepseek-v4-pro

### Contexte
Ce que j'ai demandé...

### Réponse DeepSeek
Ce qu'il a répondu...

### Mes Notes
Ce que j'en retiens...
- Point clé 1
- Point clé 2

### Actions
- [ ] Action 1
- [ ] Action 2

#deepseek #idée #action
```

## 🔗 Liens
- [[index|Retour Personnel]]
- [[../forge/index|Forge Index]]
- [[../personal/deepseek-prompts|Prompts Utiles]]
