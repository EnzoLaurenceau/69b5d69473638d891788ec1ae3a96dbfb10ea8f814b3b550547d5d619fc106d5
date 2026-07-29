# Nebius Partner Cookbook — patterns à intégrer (standard Forge)

Source : github.com/nebius/nebius-partner-cookbook (MIT). Recettes FastAPI **production-shaped**
+ **Nebius AI Studio** (inférence LLM OpenAI-compatible, bon marché → marges sur produits vendables).

## Intégration faite
- **Inférence Nebius** branchée dans le router : `forge_llm.py` → `FREE_DIRECT` (1ʳᵉ position).
  Clé `NEBIUS_API_KEY`, modèle réglable `NEBIUS_MODEL`. Base : `https://api.studio.nebius.com/v1`.
  → Tout `forge_call(tier=FREE)` peut router sur Nebius (cheap, OpenAI-compat).

## La séquence 10 recettes → quoi prendre pour la Forge
Chaque recette enseigne 1 concept production. Mapping vers nos composants (ne pas réinventer) :

| # | Recette | Concept | Déjà dans la Forge / à lifter |
|---|---------|---------|-------------------------------|
| 01 | first-agent | FastAPI + **SSE streaming** (status/token/done) | streaming à ajouter aux bots (UX temps réel) |
| 02 | pinecone-nexus | RAG domaine | `rag_service.py` (Qdrant) / turbovec |
| 03 | tavily | grounding temps réel | `mcp-omnisearch` / Tavily déjà dispo |
| 04 | langchain-langgraph | orchestration agents | **LangGraph** `00_CORE/langgraph/` |
| 05 | short-term-memory | thread memory | `forge_db.py` (Redis) |
| 06 | long-term-memory-postgres | user memory | `forge_db.py` (PG+pgvector) |
| 07 | observability-langsmith | logs structurés + traces | `token_tracker.py` + **à compléter : request_id + JSON logs** |
| 08 | **guardrails** | anti-hallucination, scope, I/O validation | `neuro_symbolic_guard.py` / `anti_hallucination.py` + guardrail bot |
| 09 | actions-mcp-stripe | actions via MCP (paiement) | `tools/mcp/` — Stripe MCP si paiement carte un jour |
| 10 | snowglobe | **simulation/test avant prod** | tester les bots sur conversations simulées |

## "Production-shaped" = checklist (complète le blueprint SaaS AI chatbot)
À appliquer à tout agent/bot vendable :
- [ ] Type hints partout + Pydantic sur chaque boundary
- [ ] **Logs JSON structurés avec request_id**
- [ ] Métriques Prometheus + `/health` + `/metrics`
- [ ] Rate limiting, CORS, security headers, **graceful shutdown**
- [ ] Dockerfile multi-stage + déploiement 1 commande (→ Coolify)
- [ ] Tests qui passent sans réseau (mocks)
- [ ] **Guardrails** sur entrée ET sortie (recette #08)
- [ ] SSE streaming pour l'UX (recette #01)

## Règle Forge
Construire un agent/SaaS vendable → suivre `saas_ai_chatbot.md` (archi 5 couches) **+** cette
checklist production-shaped. Inférence par défaut : Nebius (cheap) via `forge_llm` free-tier.
