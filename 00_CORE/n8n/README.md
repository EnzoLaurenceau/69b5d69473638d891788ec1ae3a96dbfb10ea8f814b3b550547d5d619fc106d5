# 00_CORE/n8n — Plateforme workflows Forge (n8n community)

n8n = **l'endroit unique** pour tout workflow / agent / automation de la Forge.
Chaque workflow est **observable** (métriques unifiées) et **éditable**
(éditeur visuel n8n + JSON versionné git).

Implémente l'architecture RAG + KAG + Agentique (article "Blending RAG, KAG,
and Agentic workflows") : récupérer (RAG) → connecter dans le graphe (KAG) →
arbitrer les conflits (judge) → agir et re-nourrir la boucle (agentique).

## Démarrage

```powershell
# 1. n8n (UI sur http://localhost:5678)
docker compose -f 00_CORE/n8n/docker-compose.yml up -d

# 2. Gateway Forge (expose forge_call / RAG / KAG / judge / metrics à n8n)
pip install fastapi uvicorn requests
python forge_n8n.py gateway                # port 7788

# 3. Premier lancement n8n : créer le owner, puis Settings → n8n API →
#    créer une clé → l'ajouter dans .env racine : N8N_API_KEY=...

# 4. Importer les workflows versionnés
python forge_n8n.py import
```

> Trois formes équivalentes, au choix (toutes vérifiées depuis la racine) :
> `python forge_n8n.py <cmd>` (recommandé — ajoute `metrics` et `gateway`),
> `python -m forge_agents.n8n_bridge <cmd>`, ou
> `python 00_CORE/forge_agents/n8n_bridge.py <cmd>`.
> Commandes du bridge : `status` · `import` · `export` · `sync`.
>
> Le `-m` depuis la racine fonctionne grâce au shim `forge_agents/__init__.py`
> (racine) qui redirige `__path__` vers `00_CORE/forge_agents/` — pas de copie,
> pas de `PYTHONPATH` à positionner. Source de vérité inchangée : `00_CORE/`.

## Composants

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` | n8n self-hosted, exécutions conservées 14 j, télémétrie OFF |
| `forge_gateway.py` | FastAPI :7788 — `/llm` `/rag` `/kag` `/blend` `/judge` `/feedback` `/metrics/*` |
| `workflows/*.json` | Workflows versionnés git (source de vérité diffable) |
| `../forge_agents/knowledge_blender.py` | Boucle RAG→KAG→arbitrage→feedback |
| `../forge_agents/forge_metrics.py` | Ledger observabilité `05_STATE/forge_metrics.jsonl` |
| `../forge_agents/n8n_bridge.py` | Client API n8n : export/import git, exécutions → métriques |

## Observabilité (contrat)

Chaque appel passant par le gateway émet un record JSONL :
`tokens_in / tokens_out / tokens_inference / latency_ms /
hallucination_score / hallucination_verdict / cost_usd / ok / error`
groupé par `(workflow, agent, node)`.

- Résumé CLI : `python -m forge_agents.forge_metrics`
- API : `GET :7788/metrics/summary` (p50/p95 latence, taux d'erreur, hallu moyenne)
- **Grafana** : dashboard *Forge — Workflows & Agents* (localhost:3000, uid
  `forge-workflows`). Le gateway expose `GET :7788/metrics` au format Prometheus
  (`forge_wf_*`, labels `workflow`/`agent`) ; job `forge_gateway` ajouté dans
  `09_WEB/observability/prometheus.yml`. Panneaux : tokens in/out/inference,
  latence p50/p95, hallucination moyenne, conflits RAG↔KAG, taux d'erreur, coût.
- Niveau workflow n8n : `python -m forge_agents.n8n_bridge sync`
  (durées bout-en-bout + échecs des exécutions n8n → même ledger)
- Le workflow `forge_observability_report` alerte toutes les heures si
  err>20 %, p95>30 s, hallucination<0.7 ou conflits KAG détectés.

## Éditabilité (cycle de vie d'un workflow)

1. Éditer visuellement dans n8n (localhost:5678) **ou** éditer le JSON dans `workflows/`.
2. `python -m forge_agents.n8n_bridge export` → n8n → git (diff reviewable).
3. `python -m forge_agents.n8n_bridge import` → git → n8n (create/update par nom).
4. Commit. Le JSON est la source de vérité ; n8n est la surface d'édition/exécution.

## Workflows fournis

- **Forge — Blend RAG+KAG+Agentic** : webhook `POST /webhook/forge-blend`
  `{query}` → blend → détection conflits → réponse LLM groundée → feedback
  graphe → réponse JSON avec audit complet.
- **Forge — Rapport observabilité horaire** : cron → `/metrics/summary` →
  détection anomalies → node Notifier (à brancher sur Gmail/Telegram).

## Étendre

Reproduire le moteur complet (Workflow A/B/C) : plan node-par-node déjà écrit
dans `07_REPORTS/FORGE_PIPELINE_N8N.md`. Tout nouveau workflow DOIT appeler le
gateway (jamais un LLM en direct) pour rester dans le contrat d'observabilité.
