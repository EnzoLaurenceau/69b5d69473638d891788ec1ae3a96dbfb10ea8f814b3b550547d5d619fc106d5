"""
auto_complexification.py — Algorithme d'auto-complexification comme conditional edge LangGraph.

Après chaque agent, le routeur décide :
  LEVEL_UP   → quality_delta > 0.10 pendant min_cycles_before_levelup cycles
  ROLLBACK   → régression > regression_tolerance
  CONTINUE   → normal, retour orchestrateur
  END        → tâche complète et qualité suffisante
"""

from __future__ import annotations
from pathlib import Path
import json

from .forge_state import ForgeState, Level
import logging

logger = logging.getLogger(__name__)

# ── Config depuis 01_ORCHESTRATOR/config.json ────────────────────────────────

def _load_config() -> dict:
    cfg_path = Path(__file__).parent.parent.parent / "01_ORCHESTRATOR" / "config.json"
    if cfg_path.exists():
        return json.load(open(cfg_path, encoding="utf-8"))
    return {}

CFG = _load_config()
THRESHOLDS = CFG.get("thresholds", {})

QUALITY_GAIN_THRESHOLD = THRESHOLDS.get("level_up_quality_gain", 0.10)
REGRESSION_TOLERANCE   = THRESHOLDS.get("quality_regression_tolerance", 0.05)
MIN_CYCLES_LEVELUP     = THRESHOLDS.get("min_cycles_before_levelup", 3)
KILL_BELOW             = THRESHOLDS.get("finding_kill_below", 5.0)

LEVEL_ORDER: list[Level] = ["L1", "L2", "L3", "L4"]


# ── NODE : calcule delta et flags ────────────────────────────────────────────

def auto_complexification_node(state: ForgeState) -> dict:
    """
    Node auto-complexification : compare qualité cycle N vs N-1,
    met à jour should_level_up / should_rollback, et ajuste le level.
    """
    verdict = state.get("jury_verdict") or {}
    current_quality = verdict.get("consensus", 0.5)

    history = list(state.get("quality_history", []))
    history.append(current_quality)

    # Calcul delta
    if len(history) >= 2:
        delta = history[-1] - history[-2]
    else:
        delta = 0.0

    # LEVEL_UP ?
    should_level_up = False
    current_level = state.get("level", "L1")
    new_level = current_level

    if delta > QUALITY_GAIN_THRESHOLD and len(history) >= MIN_CYCLES_LEVELUP:
        # Vérifie que les derniers cycles sont tous positifs
        recent = history[-MIN_CYCLES_LEVELUP:]
        if all(recent[i+1] > recent[i] for i in range(len(recent)-1)):
            should_level_up = True
            idx = LEVEL_ORDER.index(current_level)
            if idx < len(LEVEL_ORDER) - 1:
                new_level = LEVEL_ORDER[idx + 1]

    # ROLLBACK ?
    should_rollback = False
    rollback_reason = ""

    # Détection de gaming depuis le state ou delta fortement négatif
    gaming_detected = state.get("reward_gaming_detected", False)
    if gaming_detected:
        should_rollback = True
        rollback_reason = f"reward_gaming_detected cycle={state.get('cycle',0)}"
    elif delta < -REGRESSION_TOLERANCE and len(history) >= 2:
        should_rollback = True
        rollback_reason = f"quality_drop={delta:.3f} cycle={state.get('cycle',0)}"

    # NMP → Event Stream dashboard (audit ticket 1 : tous les nodes émettent)
    try:
        from .agent_nodes import _nmp_emit
        _nmp_emit("EXEC", "AUTO_COMPLEX", new_level,
                  f"delta={delta:.3f} level_up={should_level_up} rollback={should_rollback}")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Kill findings sous le seuil
    findings = list(state.get("findings", []))
    for f in findings:
        if f.get("score", 10) < KILL_BELOW and f.get("status") != "killed":
            f["status"] = "killed"

    updates = {
        "quality_history": history,
        "quality_delta": round(delta, 4),
        "should_level_up": should_level_up,
        "should_rollback": should_rollback,
        "rollback_reason": rollback_reason,
        "level": new_level,
        "findings": findings,
    }

    # Log caveman
    from .forge_state import CavemanMsg
    log = list(state.get("caveman_log", []))
    # ponytail: CavemanMsg=NMPPacket=str pipe-format VERB|SOURCE|OBJECT|PAYLOAD (not a ctor).
    if should_level_up:
        log.append(f"EVOLVE|AUTO_COMPLEX|level={current_level}→{new_level}|quality_gain={delta:.3f}")
    elif should_rollback:
        log.append(f"ROLLBACK|AUTO_COMPLEX|cycle={state.get('cycle',0)}|{rollback_reason}")
    else:
        log.append(f"STABLE|AUTO_COMPLEX|quality={current_quality:.3f}|delta={delta:.3f}")
    updates["caveman_log"] = log

    return updates


# ── CONDITIONAL EDGE : après auto_complexification ────────────────────────────

def route_after_complexification(state: ForgeState) -> str:
    """
    Conditional edge après auto_complexification_node.
    Retourne le nom du prochain node.
    """
    if state.get("should_rollback"):
        # Rollback → revenir à l'agent précédent sans avancer
        return "orchestrator"

    if state.get("task_complete"):
        return "__end__"

    return "orchestrator"


# ── CONDITIONAL EDGE : après neuro_symbolic_verification ─────────────────

def route_after_verification(state: ForgeState) -> str:
    """
    Après neuro_symbolic_verification, passe par anti_hallucination.
    """
    return "anti_hallucination"


# ── CONDITIONAL EDGE : après anti_hallucination ─────────────────────────

def route_after_hallucination_check(state: ForgeState) -> str:
    """
    Après anti_hallucination :
      - réponse fiable → auto_complexification
      - non fiable, budget de retry restant → re-run agent (correction)
      - non fiable après MAX_REVISION_ATTEMPTS OU aveu d'ignorance → escalade HUMAINE
        (la Forge DIT qu'elle ne sait pas au lieu de boucler / inventer).
    """
    from .forge_spine import should_escalate
    escalate, _ = should_escalate(state)
    if escalate:
        return "escalate_human"
    if state.get("needs_revision"):
        return "dynamic_agent"  # retry avec corrections (budget non épuisé)
    return "auto_complexification"


# ── CONDITIONAL EDGE : routeur principal depuis orchestrateur ─────────────────

def route_from_orchestrator(state: ForgeState) -> str:
    """
    Conditional edge depuis orchestrator_node.
    Route vers generate_blueprint (spec-first) ou la fin.
    """
    next_agent = state.get("next_agent", "dynamic_agent")
    if next_agent == "__end__":
        return "__end__"
    
    # Route to ZSL analysis if cybersecurity task
    task = state.get("task", "").lower()
    if any(keyword in task for keyword in ["security", "vulnerability", "ctf", "bounty", "exploit", "hack"]):
        return "zsl_analysis"
    
    return "generate_blueprint"


# ── CONDITIONAL EDGE : après un agent → vers auto_complexification ou end ─────

def route_after_agent(state: ForgeState) -> str:
    """
    Après un agent node, passe toujours par auto_complexification.
    Sauf si erreur critique.
    """
    if state.get("error"):
        return "__end__"
    
    # Route to verification if response exists
    if state.get("current_response"):
        return "neuro_symbolic_verification"
    
    return "auto_complexification"
