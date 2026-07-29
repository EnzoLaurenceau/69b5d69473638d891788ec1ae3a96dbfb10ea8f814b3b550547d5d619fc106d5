# AGENTS.md — 00_CORE/n8n

## Purpose
Plateforme workflow unique de la Forge (n8n community self-hosted) + gateway
HTTP qui expose les fonctions Forge aux workflows avec observabilité obligatoire.

## Ownership
- `docker-compose.yml` — déploiement n8n (port 5678, volume n8n_data)
- `forge_gateway.py` — micro-service FastAPI :7788 (1 responsabilité : HTTP ⇄ Forge + métriques)
- `workflows/*.json` — workflows versionnés (source de vérité git)

Modules frères (00_CORE/forge_agents/) : `knowledge_blender.py`,
`forge_metrics.py`, `n8n_bridge.py`.

## Local Contracts
- Tout appel LLM/RAG/KAG depuis n8n passe par le gateway — JAMAIS d'appel LLM
  direct depuis un node n8n (sinon aucune métrique tokens/hallucination).
- Chaque endpoint gateway émet un record `forge_metrics` (JSONL append-only,
  `05_STATE/forge_metrics.jsonl`). Nouveau endpoint = `with observe(...)` obligatoire.
- `GET /metrics` (port 7788) = exposition Prometheus, scrapée par `forge-prometheus`
  (job `forge_gateway`) et affichée dans Grafana (uid `forge-workflows`).
  Nouvelle métrique dans `summary()` → l'ajouter à `_PROM_METRICS` sinon elle
  n'apparaît pas dans les dashboards.
- Workflows : match par `name` entre git et n8n (import = create/update par nom).
  Renommer un workflow = nouveau workflow côté import.
- Secrets : credentials dans n8n Credentials ou `.env` racine (N8N_API_KEY),
  jamais dans les JSON de `workflows/`.
- Depuis un container n8n, le gateway = `http://host.docker.internal:7788`.
- `forge_call` depuis le gateway : `nano_mode=False` (défaut de `/llm`). Le
  NANO_SYSTEM_PROMPT est un protocole inter-agents (`COMMAND|ARG1|…`) ; injecté
  dans une réponse destinée à un humain ou à un webhook, il pollue la sortie et
  le modèle le lit comme une tentative d'injection. `nano_mode=True` uniquement
  pour un appel sous-agent interne dont on parse le format nano.
- Même règle pour tout parsing de format libre (ex. `extract_entities` attend
  une liste séparée par virgules) : `nano_mode=False`.

## Work Guidance
- Nouveau workflow : partir de `forge_blend_rag_kag.json` comme modèle
  (webhook → gateway → IF → respond), l'éditer dans l'UI, puis `n8n_bridge export`.
- Plan complet du moteur Forge en n8n : `07_REPORTS/FORGE_PIPELINE_N8N.md`.

## Work Guidance (suite)
- **Piège cache** : `forge_call` passe par le cache sémantique. Après un
  changement de prompt/system, une requête identique peut renvoyer l'ANCIENNE
  réponse. Pour valider un correctif de prompt, utiliser une requête inédite.

## Verification
```powershell
python forge_n8n.py status    # n8n up + clé API + liste workflows
python forge_n8n.py import    # workflows git → n8n
python forge_n8n.py export    # n8n → git (réutilise le fichier existant)
python forge_n8n.py sync      # exécutions n8n → forge_metrics
python forge_n8n.py metrics   # table agrégats observabilité
python forge_n8n.py gateway   # démarre le gateway :7788
```
Depuis la racine, les trois formes marchent :
`python forge_n8n.py <cmd>` · `python -m forge_agents.n8n_bridge <cmd>` ·
`python 00_CORE/forge_agents/n8n_bridge.py <cmd>`.
`forge_n8n.py` injecte `00_CORE` dans `sys.path` (comme `run_forge.py`) et ajoute
`metrics`/`gateway`. Le `-m` marche via le shim `forge_agents/__init__.py` à la
racine, qui redirige `__path__` vers `00_CORE/forge_agents/` et rejoue le vrai
`__init__` (mêmes objets exportés — vérifié : `fa.get_db is forge_db.get_db`).
**Ne jamais mettre de code métier dans ce shim** : la source de vérité reste
`00_CORE/forge_agents/`.
