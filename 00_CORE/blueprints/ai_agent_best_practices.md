# AI Agent Best Practices — Blueprint transversal Forge
> Règles par défaut pour TOUT système agent/RAG/API généré par la Forge.
> Chargé via CLAUDE.md → actif à chaque session Claude (même abonnement simple).

## 0. Structure repo production-AI (défaut d'archi app IA)
Découpage type (adapter, ne pas tout créer d'office — YAGNI) :
```
app/{main,config,models}  components/{retriever,reranker}  services/{rag_pipeline,semantic_cache,conversation,query_rewriter,query_router}
prompts/{templates,registry}  agents/{grader,decomposer,adaptive_router,tools/*}  security/{input_guard,content_filter,output_filter}
evaluation/{golden_dataset,offline_eval,online_monitor}  observability/{tracer,feedback,cost_tracker}
```
Aligné blueprint 5 couches + microservices. Prompts VERSIONNÉS + hot-swappable (registry). Frontend containerisé à part.

## 1. RAG — 12 piliers (checklist avant de livrer tout RAG)
embeddings · vector DB (turbovec/Qdrant) · semantic search · chunking (~300 tok) · **re-ranking** (cross-encoder) ·
**hybrid search** (BM25 + vecteurs) · metadata filter · context window · **hallucination guard** (préférer "je ne sais pas") ·
**grounding** (citer sources réelles) · data drift (refresh sources) · knowledge graph (GitNexus/graphify).
HyDE quand la query est courte/ambiguë : LLM génère doc hypothétique → embed → retrieve.
Self-correcting retrieval : document_grader note la pertinence des chunks avant génération.

## 2. Eval — LLM-as-a-Judge (obligatoire, complète MiroFish/Herald)
Juge ancré : query + contexte + réponse référence + grille claire. Métriques structurées :
faithfulness · correctness · relevance · completeness · safety.
Fiabilité : multi-juges (vote majorité), cas low-confidence → humain. Valider juge vs humain (Cohen κ / Spearman / F1).
Golden set + offline eval + online monitor, historique tracké. Juge LLM = tier FREE (jamais Claude direct sur le contenu).

## 3. Sécurité agent — 3 couches guard (non négociable)
input_guard (injection prompt, jailbreak, PII entrée) → content_filter (pendant) → output_filter (fuite secrets, PII sortie).
S'empile sur neuro_symbolic_guard existant. HITL sur toute action fort enjeu (cf. règle HITL CLAUDE.md).

## 4. API / temps réel — choisir le bon transport
REST (défaut CRUD) · GraphQL (champs précis, 1 endpoint) · gRPC (interne haute perf) ·
WebSocket (full-duplex) · **SSE (server→client streaming — défaut pour stream tokens LLM)** · Webhooks (event, +secret, async).
Temps réel : polling < long-polling < SSE < WebSocket. Pas de polling si SSE/WS possible.
Bonnes pratiques API TOUJOURS : rate limiting (429) · versioning (v1/v2) · auth token signé (JWT Bearer) ·
**idempotency** (retry sûr, clé idempotence sur paiement) · pagination (limit/offset) · caching (ETag/304).

## 5. Observabilité + coût (défaut prod)
Tracing par étape (LangSmith sur forge_call déjà là) · capture feedback utilisateur · **cost_tracker par étape**
(complète token_tracker). Semantic cache avant tout appel LLM (forge_fingerprint).

## Gate
Système agent/RAG livré sans : re-ranking OU hallucination guard OU grounding OU 3 guards sécurité OU eval judge
→ PAS DELIVER-ready. S'ajoute aux gates Herald(≥B) + legal + MiroFish.
