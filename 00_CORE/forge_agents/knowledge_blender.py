"""knowledge_blender — boucle RAG + KAG + Agentique (article Medium
"Blending RAG, KAG, and Agentic workflows", Saswati Panda, 2025).

Cycle continu :
  1. RAG    — récupérer l'information actuelle (rag_anything / turbovec)
  2. KAG    — connecter dans le graphe de connaissances (graph_db Kùzu / graphify)
  3. CONFLIT— si RAG et KAG divergent → arbitrage hallucination_judge
  4. AGENT  — contexte fusionné + provenance injectés dans la boucle agentique
              (forge_graph via `context`), le résultat re-nourrit le graphe.

Garde-fous de l'article, implémentés :
  - Data quality  : chaque source porte provenance + score ; sources sans
                    provenance = UNVERIFIABLE, jamais présentées comme fait.
  - Conflits      : stratégie explicite `resolve_conflicts` (judge arbitre,
                    verdict CONTRADICTED → l'affirmation est marquée, pas tue
                    silencieusement).
  - Oversight     : audit trail complet par étape → forge_metrics (latence,
                    tokens, verdicts) + retour `audit` détaillé.

Usage :
    from forge_agents.knowledge_blender import blend
    result = blend("comment X interagit avec Y ?")
    result["context"]    # contexte groundé prêt pour le prompt agent
    result["conflicts"]  # divergences RAG↔KAG arbitrées
    result["audit"]      # trace complète (sources, verdicts, latences)
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

if __package__ in (None, ""):  # lancé comme script → rendre 00_CORE importable
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from forge_agents.forge_metrics import observe, record
import logging

logger = logging.getLogger(__name__)

WORKFLOW = "blend_rag_kag"


# ---------------------------------------------------------------- RAG stage

def rag_retrieve(query: str, k: int = 5) -> list[dict]:
    """Étape RAG : documents actuels, chacun avec provenance."""
    with observe(workflow=WORKFLOW, agent="rag_retrieve", kind="rag") as m:
        try:
            from forge_agents.rag_anything import get_rag
            hits = get_rag().search_docs(query, k=k) or []
        except Exception as e:
            m.meta["fallback"] = str(e)
            hits = []
        docs = []
        for h in hits:
            docs.append({
                "text": h.get("text") or h.get("content") or str(h),
                "source": h.get("source") or h.get("doc_id") or h.get("file") or "unknown",
                "score": h.get("score"),
                "origin": "rag",
            })
        m.meta["hits"] = len(docs)
        return docs


# ---------------------------------------------------------------- KAG stage

_STOPWORDS = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou",
              "the", "a", "an", "of", "and", "or", "in", "on", "for", "to",
              "comment", "pourquoi", "quel", "quelle", "how", "why", "what"}


def extract_entities(query: str, use_llm: bool = True) -> list[str]:
    """Entités candidates pour interroger le graphe. LLM (HAIKU) si dispo,
    sinon heuristique mots significatifs."""
    if use_llm:
        try:
            from forge_agents.forge_llm import forge_call, LLMTier
            out = forge_call(
                f"Extrait les entités (noms propres, concepts techniques) de : "
                f"{query!r}. Réponds UNIQUEMENT par une liste séparée par des "
                f"virgules, max 6 entités.",
                tier=LLMTier.HAIKU, task_type="extract", max_tokens=100,
                node="blender_extract", show_tokens=False,
                # on parse une liste séparée par virgules : le protocole nano
                # (COMMAND|ARG) casserait le format, et l'enrichissement
                # OpenViking n'apporte rien sur une extraction d'entités.
                nano_mode=False, use_openviking=False,
            )
            text = out.get("text", out) if isinstance(out, dict) else str(out)
            ents = [e.strip() for e in text.split(",") if e.strip()]
            if ents:
                return ents[:6]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    words = re.findall(r"[A-Za-zÀ-ÿ0-9_\-]{3,}", query)
    return [w for w in words if w.lower() not in _STOPWORDS][:6]


def kag_expand(entities: list[str], hops: int = 2, limit: int = 10) -> list[dict]:
    """Étape KAG : relations structurées autour des entités."""
    with observe(workflow=WORKFLOW, agent="kag_expand", kind="kag") as m:
        facts: list[dict] = []
        try:
            from forge_agents.graph_db import get_graph_db
            db = get_graph_db()
            for ent in entities:
                for rel in (db.query_related(ent, hops=hops, limit=limit) or []):
                    facts.append({
                        "entity": ent,
                        "relation": rel,
                        "text": _relation_to_text(ent, rel),
                        "origin": "kag",
                    })
        except Exception as e:
            m.meta["fallback"] = str(e)
        m.meta["entities"] = entities
        m.meta["facts"] = len(facts)
        return facts


def _relation_to_text(entity: str, rel: dict) -> str:
    parts = [f"{entity}"]
    for key in ("edge_type", "relation", "type"):
        if rel.get(key):
            parts.append(f"—{rel[key]}→")
            break
    for key in ("name", "title", "key", "target", "node"):
        if rel.get(key):
            parts.append(str(rel[key]))
            break
    ctx = rel.get("context") or rel.get("rationale") or ""
    return " ".join(parts) + (f" ({ctx})" if ctx else "")


# ------------------------------------------------------- conflict resolution

def resolve_conflicts(rag_docs: list[dict], kag_facts: list[dict],
                      use_judge: bool = True) -> list[dict]:
    """Stratégie de conflit RAG↔KAG (point 'Resolve conflicts' de l'article).

    Pour chaque fait KAG, on vérifie s'il est soutenu/contredit par l'évidence
    RAG via hallucination_judge. Retourne les faits annotés :
    SUPPORTED / CONTRADICTED / UNVERIFIABLE (jamais de suppression muette).
    """
    if not kag_facts:
        return []
    evidence = "\n".join(d["text"][:500] for d in rag_docs)[:4000]
    annotated: list[dict] = []
    for fact in kag_facts:
        verdict, confidence = "UNVERIFIABLE", None
        if use_judge and evidence.strip():
            with observe(workflow=WORKFLOW, agent="conflict_judge",
                         kind="judge") as m:
                try:
                    from forge_agents.hallucination_judge import judge
                    res = judge(claim=fact["text"], evidence=evidence) or {}
                    verdict = str(res.get("verdict", "UNVERIFIABLE")).upper()
                    confidence = res.get("confidence")
                except Exception as e:
                    m.meta["judge_error"] = str(e)
                m.hallucination_verdict = verdict
                if isinstance(confidence, (int, float)):
                    m.hallucination_score = float(confidence)
        annotated.append({**fact, "verdict": verdict, "confidence": confidence})
    return annotated


# ------------------------------------------------------------- blended loop

def blend(query: str, k: int = 5, hops: int = 2, use_llm: bool = True,
          use_judge: bool = True) -> dict:
    """Boucle complète RAG → KAG → arbitrage → contexte agent + audit."""
    t0 = time.perf_counter()

    rag_docs = rag_retrieve(query, k=k)
    entities = extract_entities(query, use_llm=use_llm)
    kag_facts = kag_expand(entities, hops=hops)
    resolved = resolve_conflicts(rag_docs, kag_facts, use_judge=use_judge)

    supported = [f for f in resolved if f["verdict"] == "SUPPORTED"]
    contradicted = [f for f in resolved if f["verdict"] == "CONTRADICTED"]
    unverifiable = [f for f in resolved if f["verdict"] not in
                    ("SUPPORTED", "CONTRADICTED")]

    ctx_lines = ["## Évidence documentaire (RAG)"]
    for d in rag_docs:
        ctx_lines.append(f"- [{d['source']}] {d['text'][:300]}")
    ctx_lines.append("## Relations vérifiées (KAG, soutenues par l'évidence)")
    ctx_lines += [f"- {f['text']}" for f in supported]
    if unverifiable:
        ctx_lines.append("## Relations non vérifiées (à ne PAS affirmer comme fait)")
        ctx_lines += [f"- {f['text']}" for f in unverifiable]
    if contradicted:
        ctx_lines.append("## ⚠️ Conflits RAG↔KAG (graphe contredit par l'évidence)")
        ctx_lines += [f"- {f['text']}" for f in contradicted]
    context = "\n".join(ctx_lines)

    audit = {
        "query": query,
        "entities": entities,
        "rag_docs": len(rag_docs),
        "kag_facts": len(kag_facts),
        "supported": len(supported),
        "contradicted": len(contradicted),
        "unverifiable": len(unverifiable),
        "sources": sorted({d["source"] for d in rag_docs}),
        "total_ms": int((time.perf_counter() - t0) * 1000),
    }
    record(kind="workflow", workflow=WORKFLOW, agent="blend",
           latency_ms=audit["total_ms"], meta=audit)

    return {"context": context, "rag": rag_docs, "kag": resolved,
            "conflicts": contradicted, "audit": audit}


def feedback(query: str, answer: str, session_id: str = "") -> None:
    """Étape agentique retour : le résultat re-nourrit le graphe (mémoire
    épisodique) — boucle continue de l'article."""
    with observe(workflow=WORKFLOW, agent="feedback", kind="kag") as m:
        try:
            from forge_agents.graph_db import get_graph_db
            db = get_graph_db()
            mem_id = f"blend_{int(time.time())}"
            db.add_memory(
                mem_id, summary=f"Q: {query[:200]} → A: {answer[:400]}",
                memory_type="episodic", agent="knowledge_blender",
            )
            # PRODUCED_BY : lie le MemoryNode à son agent → plus d'orphelin
            try:
                db.create_edge("PRODUCED_BY", "MemoryNode", mem_id,
                               "Agent", "knowledge_blender",
                               context="feedback_loop")
            except Exception as edge_exc:
                logger.debug("PRODUCED_BY edge skipped: %s", edge_exc)
            m.meta["mem_id"] = mem_id
        except Exception as e:
            m.meta["error"] = str(e)


if __name__ == "__main__":
    import json as _json
    import sys
    q = " ".join(sys.argv[1:]) or "forge orchestrator token budget"
    res = blend(q, use_llm=False, use_judge=False)
    print(_json.dumps(res["audit"], indent=2, ensure_ascii=False))
    print(res["context"][:1500])
