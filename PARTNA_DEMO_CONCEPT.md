# Démo Forge pour Partna — concept + CTA + inventaire réel

> Lié à [PARTNA_PITCH_PLAN.md](PARTNA_PITCH_PLAN.md). La démo EST l'arme de vente.
> Tout ce qui suit est tiré des modules réels de `00_CORE/forge_agents/` (90 fichiers lus),
> pas d'une brochure. Rien d'inventé.

---

## 1. Le principe de la démo — une seule idée, imparable

Partna écrit noir sur blanc sur son site : *« Pas des promesses. Des résultats
mesurés chez un vrai client. »* Donc la démo n'impressionne pas — elle **mesure,
en direct, devant eux**.

### Format : split-screen, même tâche, deux fois, compteur live

Écran coupé en deux. **Même tâche métier des deux côtés** — et pas n'importe
laquelle : *« Fais-moi le point du mois »*, l'exemple exact de leur propre page
d'accueil (CRM + campagnes + facturation + emails).

| Gauche — Agent naïf | Droite — La Forge |
|---|---|
| 1 seul modèle cher (Opus/Sonnet sur tout) | Router par type de tâche (trie→Haiku, raisonne→Sonnet, gratuit quand possible) |
| Contexte brut injecté tel quel | RTK compresse la sortie outils avant le contexte |
| Chaque appel repart de zéro | Fingerprint cache : tâche déjà vue → 0 appel LLM |
| Handoffs verbeux entre agents | AIL/NMP : langage inter-agent ultra-compact |

En bas, **un compteur qui monte en temps réel** : tokens in / out, coût $,
latence. À la fin, un seul chiffre géant : **le delta**.

### Le coup de grâce : le bouton « Relancer »

On relance la même tâche. Côté gauche : même coût, ça repaie tout. Côté Forge :
**quasi-instantané, quasi-gratuit** (fingerprint cache hit). C'est le moment
« waouh » — mais un waouh *chiffré*, celui qu'ils respectent. À l'échelle de
leur portefeuille clients, chaque workflow répété = économie récurrente.

### Ce que la démo prouve, sans le dire
- On ne remplace pas OpenClaw. On rend chaque appel moins cher **sous** OpenClaw.
- Le client final ne voit aucune différence — même résultat, même canal.
- La marge par client de Partna monte.

---

## 2. Storyboard (3 min chrono)

1. **0:00–0:20** — « Voici votre exemple de homepage, le point du mois. Je le
   lance des deux côtés en même temps. » Lancement simultané.
2. **0:20–1:30** — Les deux tournent. Compteur visible. Gauche grimpe vite,
   droite grimpe lentement (appels gratuits + cache). Narration : ce qui se
   passe à droite (routing, RTK, fingerprint) en 1 phrase chacun.
3. **1:30–2:00** — Résultats identiques affichés côte à côte (même qualité).
   Delta coût affiché en grand.
4. **2:00–2:40** — Bouton **Relancer**. Droite = instantané ≈ 0 €. « Ça, c'est
   ce qui se passe quand un client répète un workflow 50 fois par mois. »
5. **2:40–3:00** — CTA (section 4).

---

## 3. Inventaire réel de la Forge — 7 piliers

> Regroupé par valeur, pas par ordre alphabétique. Chaque ligne = un module réel.

### Pilier 1 — Réduction du coût d'inférence (le pilier « argent »)
- **forge_llm** — router unifié, hiérarchie de coût 4 tiers : gratuit (Gemini/Groq/Cerebras + OpenRouter free) → Haiku → Sonnet → Opus, auto-routing par `task_type`.
- **inference_patch** — prompt cache (KV des system prompts), response cache, compression de prompt, routing vers le provider le plus rapide, batching.
- **lmcache_integration** — KV cache persistant + stockage en tiers pour l'inférence multi-agent (~80 % d'économie visée).
- **forge_fingerprint** — empreinte d'exécution `hash(task+context+tier+version)` → zero-redundancy gate : même empreinte dans le TTL = **0 appel LLM**. + déduplication de contexte.
- **semantic_cache** — SimHash + cache sémantique vers Nexus CAS.
- **forge_mimo** — batch coalescer conscient du round-up : N petits prompts → 1 seul appel facturé.
- **cervelet** — couche réflexe : un Token-ID ancré renvoie le résultat sans appel LLM (0 token).
- **turbovec_brain** — index sémantique quantisé 4-bit, embeddings par hash (pas de LLM), compaction de session sous le plafond 65k tokens.
- **adaptive_rag** — choisit la stratégie de retrieval la moins chère qui reste assez précise, selon la complexité de la tâche.
- **RTK** (binaire Rust externe) — compresse la sortie des commandes de 60–90 % avant le contexte. **Mesuré : `git status` 785 → 268 caractères (−66 %).**
- **ail_protocol / nmp_encoder / nanomachine** — langage inter-agent ultra-compact ; le langage naturel n'est généré **qu'une fois**, à la sortie finale.
- **forge_mcp_pruner** — détecte les outils MCP inutilisés et recommande le pruning (moins d'outils = moins de contexte).
- **forge_lazy** — ne fait que le minimum de travail nécessaire pour atteindre la confiance cible.
- **token_tracker** — devis avant / réel après / post-mortem + score d'efficacité.

### Pilier 2 — Observabilité & contrôle (le pilier « confiance »)
- **forge_observability** — tracing LangSmith central sur `forge_call` (point de passage unique de TOUS les appels LLM, tous providers/tiers), dégradation gracieuse si pas de clé.
- **forge_event_bus** — événements temps réel : `NODE_EXECUTED`, `MCP_CACHE_HIT/MISS`, `HALLUCINATION_DETECTED`, `OPTIMIZATION_SUGGESTED`…
- **forge_execution_logger** — traces d'exécution persistées en JSON (debug, analyse, visualisation).
- **token_tracker** — comptabilité par modèle : input/output/coût/latence.
- **Dashboard 7777** — dashboard temps réel (collecte 24/7, multi-providers).

### Pilier 3 — Recherche hybride & retrieval
- **forge_rag_optimized** — 8 features : BM25 + vecteur + **hybride (BM25·0.4 + vecteur·0.6)** + reranker cross-encoder (Top-20→Top-5) + chunking sémantique + dédup SimHash + index hiérarchique (doc/section/chunk) + partition par domaine.
- **forge_search_engine** — full-text + filtres métadonnées + recherche à facettes + similarité + recherche temporelle (récent/stale/expiré).
- **openviking / multi_source_brain** — mémoire sémantique + hiérarchie de sources (HuggingFace → GitHub → Kaggle → web).
- **adaptive_rag / turbovec_brain** — (cf. pilier 1).

### Pilier 4 — Édition sémantique de code (SEE) *Phase 1 livrée*
- **Tree-sitter** comme AST universel : Python, TS/JS, Go, Rust, Java, C/C++.
- **SymbolResolver** — résolution de symboles avec fallback regex.
- **SemanticPatchOptimizer** — patch multi-stratégie.
- **PatchScorer** — notation du patch sur 6 critères pondérés.
- **AutoRollback** — édition transactionnelle (rollback si le patch casse).
- **EditMetrics** — 18 métriques d'édition.
- **IntelligentContextWindow** — fenêtre de contexte ciblée autour du symbole.
- **PatchMemory** — mémoire des patchs via Graphify.

### Pilier 5 — Fiabilité & garde-fous qualité (colle à leur « satisfait ou remboursé »)
- **mirofish** — jury multi-personas (gates : kb_intake, plan_selection, token_optimization), toujours en tier gratuit.
- **anti_hallucination** — semantic gravity + chain-of-verification + limites d'itération.
- **neuro_symbolic_guard** — IA explicable + prévention d'hallucination (Logic Tensor Networks, DeepProbLog…).
- **forge_no_mistakes** — quality gate.
- **legal_compliance** — gate juridique (RGPD/AI Act/CNIL…), bloquant si non conforme.
- **Herald** — audit sécurité (SQLi, XSS, secrets, path traversal…), grade A+→F, bloquant si < C.
- **forge_self_heal** — détecte composants cassés/redondants → merge / remove / replace / optimize.

### Pilier 6 — Orchestration multi-agents (le moteur)
- **forge_graph** (LangGraph) — orchestrateur → agent dynamique → auto-complexification.
- **forge_team** — équipe hybride : 1 expert dédié par micro-task, roster qui grossit tout seul (les bons experts sont promus en KB, rappelables ensuite).
- **prompt_architect** — génère un system prompt en 10 sections pour tout expert créé à la volée.
- **forge_router_agent** — routage décisionnel dynamique (LangChain), décisions tracées.
- **auto_complexification** — leveling automatique L1→L4 selon le delta de qualité.
- **auto_tool_generator** — tâche répétée 3+ fois → génère un outil local et l'enregistre.
- **agent_topology / a2a_protocol / agent_skills_patterns** — topologies et protocoles d'agents.

### Pilier 7 — Auto-amélioration / méta
- **forge_meta** — agent permanent qui observe et optimise **le système lui-même**.
- **forge_experience_db** (ex-« BigSet ») — stocke les expériences d'exécution réelles → flywheel.
- **boost_node** — après chaque agent, compresse l'expérience → AGENTS.md / .cursorrules / turbovec, réinjectée au prochain spawn.
- **evomap_evolve** — pont d'auto-amélioration (local-only).
- **finetune_pipeline** — gestionnaire de fine-tuning.

---

## 4. Le CTA — fort, à faible friction, calqué sur leur propre méthode

Partna vend avec un **audit gratuit** et une garantie **satisfait ou remboursé
dès le premier mois**. On leur renvoie leur propre logique :

> **« Donne-moi un seul de tes workflows OpenClaw. Je te le renvoie sous 72h avec
> le coût d'inférence réel avant/après, chiffré, sur ton vrai use case. Si je ne
> réduis pas la facture, tu ne me dois rien. »**

Pourquoi ça marche :
- **Zéro risque pour eux** — miroir exact de leur « satisfait ou remboursé ».
- **Mesuré, pas promis** — exactement ce qu'ils disent exiger.
- **Scopé** — un seul workflow, pas « refais ton archi ». Terrain qu'ils maîtrisent.
- **Ça les met en position de juge** — comme leurs propres clients jugent « sur la livraison réelle, pas sur une promesse ».

### Escalade après le pilote (si le chiffre est bon)
- Soit **% des économies mesurées** sur 6–12 mois (risque quasi nul, aligné garantie).
- Soit **forfait mensuel** greffé sur leur abonnement client existant.

---

## 5. Ce qu'il faut décider avant de produire la démo

- **Le chiffre du delta** : à mesurer sur une vraie tâche instrumentée avec
  `token_tracker`, pas à inventer. Le RTK −66 % est déjà solide comme teaser.
- **Le canal de la démo** : vidéo courte (comme leurs propres démos « série »)
  vs. démo live en visio de 45 min (comme leur audit).
- **Le workflow-cible** : reprendre « le point du mois » (homepage) ou le tri
  d'emails / réponse SAV (autres exemples de leur site).

## Prochaine action possible
Construire le mockup split-screen (page HTML autonome, compteur live animé) —
utilisable en vidéo ou en partage direct. À faire seulement si tu valides le
concept split-screen ci-dessus.
