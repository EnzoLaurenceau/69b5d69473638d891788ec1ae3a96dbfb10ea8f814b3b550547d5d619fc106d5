# BLUEPRINT — SaaS AI Chatbot (standard Forge)

> **Portée obligatoire.** TOUT chatbot IA et TOUTE architecture SaaS AI générés par la Forge
> suivent ce blueprint 5 couches. C'est le contrat d'architecture par défaut. Un livrable qui
> dévie doit le justifier explicitement (sinon = non conforme, bloqué avant DELIVER).
>
> Référence d'implémentation vivante : `tg-bot-workflow-v2/` (bot Telegram hôtel multi-couches).

---

## Les 5 couches → composants Forge

| # | Couche | Rôle | À utiliser dans la Forge (NE pas réinventer) |
|---|--------|------|----------------------------------------------|
| 1 | **Présentation & Intégration** | widgets embarquables, webhooks omnicanal, context streaming | Widgets React/Vue ; `tools/outreach/whatsapp_agent.py`, webhook Telegram, `snapchat_ads.py` (funnel) |
| 2 | **API Gateway & Load Balancing** | auth tenant (JWT/API key), routage, **rate limiting par tenant** | FastAPI + middleware ; `services/rate_limit.py` (token bucket → Redis en multi-réplique) |
| 3 | **Microservices & Orchestration** | ingestion (crawl/parse/vectorize), orchestration agents multi-étapes | `firecrawl` (scrape/crawl), `RAG-Anything`/`rag_anything.py` (parse) ; **LangGraph** (`00_CORE/langgraph/`) pour l'orchestration |
| 4 | **Data & AI** | vector DB (RAG), state/memory, LLM providers | **turbovec** (PG+Redis primaire) ou Qdrant ; `forge_db.py` (state/memory PG+Redis) ; **`forge_llm.py`** (router multi-providers, free-tier d'abord) |
| 5 | **Infra & Observabilité** | monitoring tokens/prompts/outils, conteneurisation, CI/CD | `token_tracker.py` + `ccrecall` ; Docker Compose ; **Coolify** (`tools/delivery/coolify.py`) pour déploiement |

---

## Multi-tenant (non négociable)
- **Isolation par tenant** : `tenant_id` sur chaque ligne DB + filtre vector (payload `tenant_id` dans Qdrant/turbovec). Jamais de fuite cross-tenant.
- **Auth en entrée** : JWT/API key validé au gateway → résout `tenant_id` → route.
- **Rate limit par tenant** : empêche le monopole de ressources + les pics de facture LLM (cf. règle TOKEN BUDGET). Pattern : `services/rate_limit.py`.
- **Config par tenant** éditable sans redeploy : ex. `services/partner_sites.py` (liste éditée par l'admin via dashboard, lue par le bot).

## Scalabilité & maintenabilité (patterns appliqués, copier tels quels)
1. **Webhook = ack immédiat + traitement en background.** Ne jamais faire l'appel LLM dans le cycle de réponse du webhook (Telegram/Meta retry → réponses dupliquées). → `BackgroundTasks` puis worker dédié quand le volume monte.
2. **Validation du secret webhook** (`X-Telegram-Bot-Api-Secret-Token` / signature Meta) → rejette les POST forgés.
3. **Clients lazy-init + once-guard** : pas de round-trip d'init (ex. `ensure_collection`) à chaque message ; flag module-level ou warmup au `lifespan`.
4. **Dégradation gracieuse** : RAG/vector down ⇒ le bot répond quand même (try/except → contexte vide), jamais de 500 vers l'utilisateur.
5. **Stateless app + state externalisé** (PG+Redis) ⇒ scaling horizontal (N répliques derrière un LB). Rien de critique en mémoire process.
6. **Lazy clients sans clé ⇒ pas de crash au boot** (démarrage possible sans toutes les API keys).
7. **LLM via router** (`forge_llm.py`) : free-tier d'abord, fallback en cascade ; coût tracké.

## Observabilité minimale par chatbot
- Tokens in/out + coût par conversation (`token_tracker.py`).
- Taux de succès tool-calls + latence LLM (logs structurés).
- Feedback utilisateur + détection hallucination (RAG grounding score).
- Stockage des conversations gagnantes → RAG (`store_memory`) pour amélioration continue.

## Persistance — rappels Forge
- **JAMAIS `localStorage`/`sessionStorage`** dans le front généré (règle Fable 5 §4). State serveur (PG/Redis) uniquement.
- Mémoire sémantique : turbovec/Qdrant (jamais de dump brut en contexte, règle #1).

## Checklist conformité (avant DELIVER)
- [ ] 5 couches présentes et séparées
- [ ] `tenant_id` isolé en DB + vector
- [ ] Auth gateway + rate limit par tenant
- [ ] Webhook async + secret validé
- [ ] Clients lazy-init, once-guard, dégradation gracieuse
- [ ] App stateless (state en PG+Redis) → scalable horizontalement
- [ ] LLM via `forge_llm.py` (free-tier d'abord) + tokens trackés
- [ ] Pas de `localStorage` ; Docker Compose + cible Coolify
- [ ] Grade Herald ≥ B, 0 CRITICAL
