# Blueprint Agentic Production-Grade (Artiquare) — gap analysis Forge

Source : artiquare.com/production-grade-agentic-architecture-blueprint
Thèse : « Most agents today are just loops with dreams. » L'architecture (pas l'abstraction)
est la couche manquante. Un agent prod a besoin de 5 couches sous le capot.

## Les 5 couches → état Forge

| # | Couche Artiquare | Ce qu'elle exige | Forge a déjà | Gap |
|---|------------------|------------------|--------------|-----|
| 1 | **Execution flows** | flux d'exécution structurés, routage entre agents modulaires | LangGraph (`00_CORE/langgraph/`) | ✅ couvert |
| 2 | **Agent state** | état persistant structuré (court + long terme), context objects typés | `forge_db.py` PG+Redis ; `forge_state.py` (TypedDict) | ✅ couvert |
| 3 | **Tools & interfaces** | tools typés, **contrats définis en code, pas en config** | `registry.json` (config) + wrappers | ⚠️ contrats typés (Pydantic) à généraliser |
| 4 | **Collaboration / HITL** | human-in-the-loop (interrupt/review/approve), human-on-the-loop (audit/modify/resume) | checkpoints LangGraph | 🔴 **GAP : pas de gate approve/reject explicite** |
| 5 | **Observability & Eval** | observabilité, **évaluation**, **replayability** | `token_tracker.py`, MiroFish (eval) | ⚠️ replay de run à ajouter |

## Gaps intégrés

### 🔴 GAP 1 — Human-in-the-loop (PRIORITÉ, intégré)
Capacité d'interrompre un agent avant une action à fort enjeu / irréversible, faire valider
par un humain (approve/reject), puis reprendre. Indispensable pour tout flux qui manie de
l'argent, des données régulées, ou une action externe.
- **Implémenté** : `tg-bot-workflow-v2/backend/app/services/hitl.py` (file d'approbations
  pending→approved/rejected). Le bot crée une demande d'approbation AVANT toute confirmation
  de booking / envoi d'instructions de paiement ; l'admin valide depuis le dashboard.
- **À généraliser Forge** : nœud LangGraph `human_gate` réutilisable (même contrat `request()/resolve()`).

### ⚠️ GAP 2 — Tool contracts as code (tracké)
Migrer progressivement les wrappers vers des signatures typées + Pydantic sur les boundaries
(au lieu de la seule `registry.json`). À faire au fil des nouveaux wrappers, pas de big-bang.

### ⚠️ GAP 3 — Replayability (tracké)
Enregistrer chaque run d'agent (inputs/outputs/decisions) pour rejouer un bug à l'identique.
Base existante : checkpoints Graphify + `token_tracker`. À compléter : un store de traces
rejouables (record→replay) au niveau du graph LangGraph.

## Règle Forge (ajout au standard)
Tout agent/bot qui exécute une **action à fort enjeu** (paiement, booking, envoi externe,
suppression, action régulée) **DOIT** passer par un gate HITL (`hitl.py` ou nœud `human_gate`).
Pas d'auto-confirmation d'argent. Voir aussi `saas_ai_chatbot.md` + `nebius_cookbook_patterns.md`.
