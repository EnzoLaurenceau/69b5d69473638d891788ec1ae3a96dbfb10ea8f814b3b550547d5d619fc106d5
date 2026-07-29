"""
adaptive_rag.py — RAG Adaptatif pour la Forge
================================================
Implémente le pattern "Adaptive RAG" (cf. github.com/Danielskry/Awesome-RAG,
section Architecture Patterns : Adaptive RAG / Active RAG / SEAKR / DRAGIN) :
avant d'injecter du contexte dans un prompt, on évalue la COMPLEXITÉ de la
tâche et on choisit la stratégie de retrieval LA MOINS CHÈRE qui reste
suffisamment précise.

Objectif (cf. CLAUDE.md — "ECONOMISER AU MAX") :
  - Réduire les tokens INPUT (contexte injecté) ET donc les tokens OUTPUT
    (un prompt plus court -> une réponse plus ciblée, moins de bruit à
    reformuler par le modèle).
  - Ne jamais sacrifier la précision sur les tâches qui en ont vraiment besoin
    (orchestration, build, market_scan, audit) — ces tâches restent en FULL.

Stratégies (du moins cher au plus cher) :
  NONE      -> aucun retrieval. Prompt nu. Tâches triviales : formatage,
              renommage, traduction courte, classification simple.
  LIGHT     -> uniquement get_findings_context() tronqué (~300 chars).
              Tâches courtes qui bénéficient d'un rappel des décisions
              déjà prises mais n'ont pas besoin du graphe complet.
  STANDARD  -> OpenViking seul (keyword+recency+affinity), top_k réduit (3),
              MAX_CHARS réduit (~600). Tâches de génération moyennes.
  FULL      -> Graphify + OpenViking (top_k=5) + findings (comportement
              actuel, ~1200+ chars). Réservé aux tâches complexes/critiques
              (orchestration, build, market_scan, audit, plan_selection)
              et au cycle 1 (pas encore d'historique pertinent à élaguer).

Classification 100% heuristique (ZÉRO appel LLM supplémentaire — un appel de
routing coûterait plus que ce qu'il économise) :
  - mots-clés "lourds"  -> +poids vers FULL
  - mots-clés "légers"  -> +poids vers NONE/LIGHT
  - longueur de la tâche
  - nom de l'agent (ORCH, AUDIT, PLAN_SELECTION -> toujours FULL)
  - cycle courant (cycle 1 -> FULL par défaut, rien à élaguer encore)

Chaque décision est journalisée dans 05_STATE/adaptive_rag_log.jsonl pour
nourrir la future boucle TokenMetric (cf. PLAN_ARCHITECTURE_V2_GITNEXUS.md,
phase 5) : on pourra a posteriori corréler stratégie choisie <-> score du
finding <-> tokens réellement consommés, et ajuster les seuils automatiquement.

Usage (dans agent_nodes.py) :
  from .adaptive_rag import get_adaptive_context
  ctx, meta = get_adaptive_context(state, agent_name)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Literal

from .graphify_checkpointer import graphify_query
from .openviking import get_viking
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("AdaptiveRAG")

FORGE_ROOT = Path(__file__).parent.parent.parent


def LOG_PATH() -> "Path":
    """Chemin cloisonné par tenant (W5-03a)."""
    return state_path("adaptive_rag_log.jsonl")


Strategy = Literal["NONE", "LIGHT", "STANDARD", "OPTIMIZED", "FULL"]

# Agents qui nécessitent TOUJOURS le contexte complet (décisions structurantes)
ALWAYS_FULL_AGENTS = {
    "orch", "orchestrator", "audit", "audit_agent",
    "plan_selection", "market", "market_agent",
}

# Mots-clés indiquant une tâche structurante / à fort enjeu -> tirent vers FULL
HEAVY_KEYWORDS = (
    "market_scan", "architecture", "build", "plan", "audit", "stratégie",
    "strategy", "clone", "research", "orchestrat", "design", "schema",
    "migration", "sécurité", "security",
)

# Mots-clés indiquant une tâche mécanique / à faible enjeu -> tirent vers NONE/LIGHT
LIGHT_KEYWORDS = (
    "formate", "format", "résume", "resume", "traduis", "traduction",
    "renomme", "rename", "titre", "title", "liste", "list", "classif",
    "reformule", "court", "summary",
    "nice", "nicely", "simple", "quick", "fast",
)

# Mots-clés indiquant une tâche de recherche/contexte -> tirent vers OPTIMIZED
OPTIMIZED_KEYWORDS = (
    "recherche", "research", "contexte", "rag", "embedding", "similar",
    "analogie", "analogy", "compar", "référence", "reference",
    "documentation", "doc", "exemple", "example",
)

# Tailles de contexte par stratégie
STRATEGY_PARAMS = {
    "NONE":      {"top_k": 0, "max_chars_viking": 0,   "max_chars_findings": 0,   "use_graphify": False, "use_dataset_rag": False, "use_rag_optimized": False},
    "LIGHT":     {"top_k": 0, "max_chars_viking": 0,   "max_chars_findings": 300, "use_graphify": False, "use_dataset_rag": False, "use_rag_optimized": False},
    "STANDARD":  {"top_k": 3, "max_chars_viking": 600, "max_chars_findings": 500, "use_graphify": False, "use_dataset_rag": True,  "use_rag_optimized": False},
    "OPTIMIZED": {"top_k": 3, "max_chars_viking": 600, "max_chars_findings": 500, "use_graphify": False, "use_dataset_rag": True,  "use_rag_optimized": True},
    "FULL":      {"top_k": 5, "max_chars_viking": 1200,"max_chars_findings": 800, "use_graphify": True,  "use_dataset_rag": True,  "use_rag_optimized": False},
}


def classify_strategy(task: str, agent_name: str, cycle: int) -> Strategy:
    """
    Détermine la stratégie de retrieval la moins chère et suffisamment
    précise pour cette tâche, sans appel LLM.
    """
    agent_l = (agent_name or "").lower()
    task_l = (task or "").lower()

    # 1. Agents critiques -> toujours FULL (décisions structurantes,
    #    une réponse imprécise coûte plus cher en cycles supplémentaires)
    if any(a in agent_l for a in ALWAYS_FULL_AGENTS):
        return "FULL"

    # 2. Cycle 1 -> rien d'utile à élaguer encore, on part en FULL pour
    #    laisser l'agent dynamique s'orienter correctement une seule fois
    if cycle <= 1:
        return "FULL"

    # 3. Score heuristique : heavy keywords +1 chacun, light keywords -1 chacun
    score = 0
    for kw in HEAVY_KEYWORDS:
        if kw in task_l:
            score += 1
    for kw in LIGHT_KEYWORDS:
        if kw in task_l:
            score -= 1

    # 4. Longueur de la tâche : tâches longues/détaillées = plus de contexte utile
    if len(task_l) > 120:
        score += 1
    elif len(task_l) < 20:
        score -= 1

    # 5. Mapping score -> stratégie
    # Ajustement : résumés/traductions courtes -> LIGHT (pas NONE)
    has_summary = any(kw in task_l for kw in ("résume", "resume", "summary", "traduis", "traduction"))
    # OPTIMIZED : tâches de recherche/contexte qui bénéficient du RAG hybride
    has_optimized = any(kw in task_l for kw in OPTIMIZED_KEYWORDS)
    if score <= -2 and not has_summary:
        return "NONE"
    elif score <= -1:
        return "LIGHT"
    elif score <= 0 and has_optimized:
        return "OPTIMIZED"
    elif score <= 1:
        return "STANDARD"
    else:
        return "FULL"


def _log_decision(agent_name: str, task: str, cycle: int, strategy: Strategy,
                   ctx_chars: int) -> None:
    """Journalise la décision pour la future boucle TokenMetric (best-effort)."""
    try:
        LOG_PATH().parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "agent": agent_name,
            "task": task[:120],
            "cycle": cycle,
            "strategy": strategy,
            "ctx_chars": ctx_chars,
            "est_tokens": round(ctx_chars / 4),
        }
        with open(LOG_PATH(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[AdaptiveRAG] log_decision échoué (non-bloquant): {e}")


def get_adaptive_context(state: dict, agent_name: str) -> tuple[str, dict]:
    """
    Remplacement adaptatif de _base_init() : construit le contexte le moins
    coûteux possible pour cette tâche, sans perdre en précision sur les
    tâches qui en ont besoin.

    Returns:
        (context_str, meta) — meta contient la stratégie choisie et une
        estimation de tokens, utile pour le caveman_log / token_tracker.
    """
    task = state.get("current_task", "")
    cycle = state.get("cycle", 0)
    strategy = classify_strategy(task, agent_name, cycle)
    params = STRATEGY_PARAMS[strategy]

    if strategy == "NONE":
        ctx = "(aucun contexte injecté — tâche triviale, stratégie NONE)"
        _log_decision(agent_name, task, cycle, strategy, 0)
        return ctx, {"strategy": strategy, "est_tokens": 0}

    viking = get_viking()
    parts = []

    # findings (toutes les stratégies sauf NONE)
    if params["max_chars_findings"] > 0:
        findings_ctx = viking.get_findings_context(max_chars=params["max_chars_findings"])
        if findings_ctx:
            parts.append(findings_ctx)

    # OpenViking (STANDARD et FULL)
    if params["top_k"] > 0:
        viking_ctx = viking.retrieve_context(
            query=f"{agent_name} {task}", task_type=task, top_k=params["top_k"]
        )
        if viking_ctx and not viking_ctx.is_fallback:
            content = viking_ctx.content
            if params["max_chars_viking"] and len(content) > params["max_chars_viking"]:
                content = content[: params["max_chars_viking"]]
            parts.append("[OpenViking]\n" + content)

    # Graphify (FULL uniquement — le plus coûteux)
    if params["use_graphify"]:
        query = f"agent={agent_name} last_session task={task}"
        graph_ctx = graphify_query(query)
        if graph_ctx:
            parts.append("[Graphify]\n" + graph_ctx)

    # DatasetRAG — few-shot examples from downloaded datasets (STANDARD + FULL)
    # Injecte des exemples pertinents de claude_mythos, vibe_coding, metacognition
    # directement dans le contexte agent pour améliorer la qualité des réponses.
    if params.get("use_dataset_rag"):
        try:
            from .dataset_rag import get_dataset_rag
            ds_rag = get_dataset_rag()
            ds_top_k = 3 if strategy == "FULL" else 2
            ds_max_chars = 1500 if strategy == "FULL" else 800
            ds_ctx = ds_rag.retrieve_for_context(
                query=f"{agent_name} {task}",
                top_k=ds_top_k,
                max_chars=ds_max_chars,
            )
            if ds_ctx:
                parts.append(ds_ctx)
        except Exception as e:
            logger.debug(f"[AdaptiveRAG] DatasetRAG skip: {e}")

    context = "\n\n".join(parts) if parts else "(aucun contexte disponible)"

    # OPTIMIZED : RAG hybride BM25+vectoriel+reranker (si disponible)
    if params.get("use_rag_optimized"):
        try:
            from .forge_rag_optimized import get_rag_optimized
            rag = get_rag_optimized()
            candidates = rag.search_hybrid(task, top_k=20)
            if candidates:
                reranked = rag.rerank(task, candidates, top_k=5)
                rag_ctx = "\n---\n".join(c.text for c in reranked)
                parts.append("[RAG Hybrid BM25+Vector+Reranker]\n" + rag_ctx[:1200])
                context = "\n\n".join(parts)
        except Exception as e:
            logger.debug(f"[AdaptiveRAG] RAG Optimized skip: {e}")

    meta = {"strategy": strategy, "est_tokens": round(len(context) / 4),
            "dataset_rag": params.get("use_dataset_rag", False),
            "rag_optimized": params.get("use_rag_optimized", False)}
    _log_decision(agent_name, task, cycle, strategy, len(context))
    return context, meta
