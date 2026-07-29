"""
forge_spine.py — Colonne vertébrale de la Forge (refacto ciblé).
================================================================
Unifie 3 choses dispersées SANS réécrire les modules existants.
Voir 00_CORE/blueprints/refacto_spine.md.

  1. CACHE + BATCH (tokens)
     - cache_get/cache_set : 1 facade sur fingerprint(exact) + semantic(fuzzy).
       Le cache est DÉJÀ universel via forge_call ; cette facade sert les appelants
       hors forge_call et centralise la logique (1 lookup, 1 store).
     - batch_call : coalesce N micro-prompts en 1 appel (MimoBatcher) → 1 round-up
       au lieu de N. Le vrai manque tokens : le batching n'était pas exposé.

  2. HONNÊTETÉ + ESCALADE HUMAINE (HITL) — le vrai manque
     - is_unknown / UNKNOWN : le modèle DIT qu'il ne sait pas au lieu d'inventer.
     - should_escalate : incertitude persistante → humain, pas de boucle infinie.
     - escalate_to_human : écrit la question dans 05_STATE/human_queue.json.

  3. DELIVER GATE (règles) — 1 choke-point avant livraison
     - deliver_gate : legal_check (+ herald advisory). Échec → livraison bloquée.

Aucun nouveau cache/juge : on appelle l'existant. ponytail.
"""
from __future__ import annotations
import json, time, uuid, logging
from pathlib import Path
from typing import Optional, Any
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("ForgeSpine")

FORGE_ROOT  = Path(__file__).parent.parent.parent
STATE_DIR   = FORGE_ROOT / "05_STATE"
HUMAN_QUEUE = state_path("human_queue.json")

# ── Seuils (tunables) ─────────────────────────────────────────────────
UNKNOWN               = "UNKNOWN:"   # forge_call/agent renvoie "UNKNOWN:<raison>"
CONFIDENCE_MIN        = 0.35         # sous ce niveau → escalade humaine
MAX_REVISION_ATTEMPTS = 2           # retries hallucination avant escalade humaine


# ══════════════════════════════════════════════════════════════════════
# 2. HONNÊTETÉ — dire "je ne sais pas" + appeler un humain (priorité user)
# ══════════════════════════════════════════════════════════════════════

def is_unknown(text: Any) -> bool:
    """True si la sortie est un aveu d'ignorance (sentinelle UNKNOWN:)."""
    return isinstance(text, str) and text.lstrip().startswith(UNKNOWN)


def should_escalate(state: dict) -> tuple[bool, str]:
    """
    Décide si la Forge doit s'arrêter et appeler un humain plutôt que boucler
    ou inventer. Retourne (escalate, raison).
    """
    resp = state.get("current_response") or state.get("agent_output") or ""
    if is_unknown(resp):
        return True, f"aveu d'ignorance: {resp.lstrip()[len(UNKNOWN):][:120]}"

    if state.get("needs_revision"):
        attempts = int(state.get("revision_attempts", 0))
        if attempts >= MAX_REVISION_ATTEMPTS:
            return True, (f"réponse non fiable après {attempts} tentatives "
                          f"({state.get('revision_reason', 'hallucination')})")

    conf = state.get("confidence", state.get("meta_confidence", 1.0))
    risk = state.get("meta_risk", 0.0)
    if conf < CONFIDENCE_MIN and risk >= 0.5:
        return True, f"confiance {conf:.0%} < {CONFIDENCE_MIN:.0%} sur tâche à risque"

    return False, ""


def escalate_to_human(question: str, context: Optional[dict] = None,
                      task: str = "") -> dict:
    """
    Écrit une demande d'aide humaine dans 05_STATE/human_queue.json (liste append).
    Ne bloque JAMAIS le process (I/O best-effort). Retourne {id, question, ...}.
    L'humain répond en éditant status/answer ; le prochain run relit la queue.

    ponytail: file-queue simple. Upgrade path = LangGraph interrupt() + reprise
    par Command(resume=...) quand ForgeRunner saura gérer les interruptions.
    """
    entry = {
        "id": "H-" + uuid.uuid4().hex[:8],
        "ts": time.time(),
        "task": task,
        "question": question,
        "context": context or {},
        "status": "pending",   # pending → answered (humain écrit "answer")
        "answer": "",
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        queue = []
        if HUMAN_QUEUE.exists():
            try:
                queue = json.loads(HUMAN_QUEUE.read_text(encoding="utf-8")) or []
            except Exception:
                queue = []
        queue.append(entry)
        HUMAN_QUEUE.write_text(json.dumps(queue[-200:], ensure_ascii=False, indent=2),
                               encoding="utf-8")
        logger.info(f"[SPINE] ESCALATE_HUMAN {entry['id']} — {question[:80]}")
    except Exception as e:
        logger.warning(f"[SPINE] escalate write failed: {e}")
    return entry


def pending_human() -> list[dict]:
    """Retourne les demandes humaines non répondues (pour dashboard / reprise)."""
    if not HUMAN_QUEUE.exists():
        return []
    try:
        q = json.loads(HUMAN_QUEUE.read_text(encoding="utf-8")) or []
        return [e for e in q if e.get("status") == "pending"]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
# 3. DELIVER GATE — 1 choke-point : la Forge respecte ses blueprints
# ══════════════════════════════════════════════════════════════════════

def deliver_gate(target_dir, product_type: str = "website",
                 with_herald: bool = False) -> dict:
    """
    Vérifie qu'un livrable respecte les règles AVANT livraison.
      - legal_check (bloquant) : mentions légales, RGPD, footer… (legal_compliance.py)
      - herald (advisory)      : grade sécurité, best-effort, ne bloque pas si infra down
    Retourne {deliver_ready: bool, grade, reason, checks}.
    """
    checks: dict = {}
    reasons: list[str] = []
    deliver_ready = True
    grade = "?"

    # ── Legal (bloquant) ──────────────────────────────────────────────
    try:
        from .legal_compliance import legal_check
        legal = legal_check(str(target_dir), product_type)
        checks["legal"] = legal
        grade = legal.get("grade", "?")
        if not legal.get("deliver_ready", False):
            deliver_ready = False
            miss = ", ".join(legal.get("missing", [])[:3]) or "conformité incomplète"
            reasons.append(f"legal:{grade} ({miss})")
    except Exception as e:
        # Pas de legal_check dispo → on NE prétend PAS que c'est conforme.
        deliver_ready = False
        reasons.append(f"legal:indisponible ({e.__class__.__name__})")
        checks["legal"] = {"error": str(e)}

    # ── Herald (advisory) ─────────────────────────────────────────────
    if with_herald:
        try:
            from .agent_nodes import herald_audit  # type: ignore
            h = herald_audit(str(target_dir))
            checks["herald"] = h
            hg = (h or {}).get("grade", "")
            if hg and hg[:1] in ("D", "F"):
                reasons.append(f"herald:{hg}")  # advisory: signalé, non bloquant
        except Exception as e:
            checks["herald"] = {"skipped": str(e)[:60]}

    return {
        "deliver_ready": deliver_ready,
        "grade": grade,
        "reason": " | ".join(reasons),
        "checks": checks,
    }


# ══════════════════════════════════════════════════════════════════════
# 1. CACHE FACADE — 1 lookup / 1 store (dédupe fingerprint + semantic)
# ══════════════════════════════════════════════════════════════════════

def cache_get(prompt: str, system: str = "", tier: str = "",
              task_type: str = "") -> tuple[Optional[str], str]:
    """Cherche un résultat caché. Retourne (result|None, source)."""
    # a) fingerprint exact (prompt+system+tier+task)
    try:
        from .forge_fingerprint import (get_fingerprint_store, make_fingerprint,
                                         fingerprint_enabled)
        if fingerprint_enabled():
            fp = make_fingerprint(prompt, system, tier, task_type)
            hit = get_fingerprint_store().check(fp)
            if hit is not None:
                return hit.get("result"), "fingerprint"
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    # b) semantic fuzzy (tâches code)
    try:
        from .semantic_cache import get_cache
        e = get_cache().lookup(prompt)
        if e:
            return e.result, "semantic"
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return None, ""


def cache_set(prompt: str, result: str, system: str = "", tier: str = "",
              task_type: str = "") -> None:
    """Stocke un résultat dans les deux caches (best-effort)."""
    if is_unknown(result):
        return  # ne jamais cacher un aveu d'ignorance
    try:
        from .forge_fingerprint import (get_fingerprint_store, make_fingerprint,
                                         fingerprint_enabled)
        if fingerprint_enabled():
            fp = make_fingerprint(prompt, system, tier, task_type)
            get_fingerprint_store().record(fp, result=result, provider=tier,
                                           task=prompt[:200], task_type=task_type)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    try:
        from .semantic_cache import get_cache
        get_cache().store(prompt, f"forge_spine:{task_type}", "0-0", result, 0.0)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


# ══════════════════════════════════════════════════════════════════════
# 1bis. BATCH — coalesce N micro-appels → 1 (le vrai manque tokens)
# ══════════════════════════════════════════════════════════════════════

def batch_call(prompts: list[str], system: str = "",
               max_tokens_per_item: int = 400) -> list[str]:
    """
    Exécute N prompts en 1 appel quand c'est rentable (MimoBatcher, round-up 1K).
    Dégradation gracieuse : pas de MiMo → forge_call séquentiel. Ordre préservé.
    Utiliser depuis les nœuds qui bouclent sur des micro-tâches identiques.
    """
    import os
    if not prompts:
        return []
    if os.environ.get("MIMO_API_KEY") and len(prompts) > 1:
        try:
            from .forge_mimo import MimoBatcher, _est_tokens
            # S-07 : vérifier le budget AVANT de dépenser
            from .mimo_budget import check as budget_check, BudgetExceeded
            est_in = sum(_est_tokens(p + system) for p in prompts)
            est_out = len(prompts) * max_tokens_per_item
            budget_check(est_in + est_out)

            b = MimoBatcher(system=system, max_items=max(len(prompts), 20))
            for p in prompts:
                b.add(p)
            return b.flush(max_tokens_per_item=max_tokens_per_item)
        except BudgetExceeded:
            raise  # ne pas dégrader : le budget est épuisé
        except Exception as e:
            logger.debug(f"[SPINE] batch→mimo fail, fallback séquentiel: {e}")
    # Fallback séquentiel (cache déjà universel via forge_call)
    from .forge_llm import forge_call, LLMTier
    return [forge_call(p, tier=LLMTier.HAIKU, system=system,
                       max_tokens=max_tokens_per_item, show_tokens=False)
            for p in prompts]


# ══════════════════════════════════════════════════════════════════════
# Self-check (ponytail: 1 test runnable, pas de framework)
# ══════════════════════════════════════════════════════════════════════

def _selfcheck() -> None:
    # honnêteté
    assert is_unknown("UNKNOWN: pas de source")           , "is_unknown UNKNOWN raté"
    assert not is_unknown("voici la réponse")             , "is_unknown faux positif"

    esc, why = should_escalate({"current_response": "UNKNOWN: X"})
    assert esc and "ignorance" in why                      , "escalate on UNKNOWN raté"

    esc, _ = should_escalate({"needs_revision": True, "revision_attempts": MAX_REVISION_ATTEMPTS})
    assert esc                                             , "escalate on retries épuisés raté"

    esc, _ = should_escalate({"needs_revision": True, "revision_attempts": 0})
    assert not esc                                        , "escalate prématurée (retry restant)"

    esc, _ = should_escalate({"current_response": "ok", "confidence": 1.0})
    assert not esc                                        , "escalate faux positif"

    # cache ne stocke pas un UNKNOWN
    before = HUMAN_QUEUE.exists()
    cache_set("p", "UNKNOWN: rien", task_type="test")     # no-op attendu (pas d'assert dur)

    # deliver_gate : chemin inexistant → NON deliver_ready (on n'invente pas la conformité)
    g = deliver_gate(FORGE_ROOT / "does_not_exist_xyz")
    assert g["deliver_ready"] is False                    , "deliver_gate doit bloquer sur legal KO"

    # escalate écrit bien dans la queue
    e = escalate_to_human("test question", {"k": "v"}, task="selfcheck")
    assert e["id"].startswith("H-") and e["status"] == "pending", "escalate entry malformée"
    assert any(x["id"] == e["id"] for x in pending_human()), "escalate pas dans pending"

    print("forge_spine self-check OK — honnêteté + deliver_gate + cache facade")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selfcheck()
