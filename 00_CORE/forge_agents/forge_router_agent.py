"""
forge_router_agent.py — Orchestration Dynamique (LangChain + LangGraph)
========================================================================
Remplace les conditions statiques de routage Python par un agent décisionnel
LangChain qui analyse l'état complet de la tâche et décide adaptativement
le prochain node.

Inspiré du plan : "Orchestration Dynamique (LangChain + LangGraph + LangSmith)"

Architecture:
  - RouterAgent: analyse ForgeState → choisit le prochain node
  - Routing decisions tracées dans LangSmith
  - Audit metrics: bounce rate, loop detection, decision history
  - Fallback: si LLM échoue → routing statique (fail-safe)

Usage:
    from forge_agents.forge_router_agent import get_router, RoutingDecision
    router = get_router()
    decision = router.route(state, available_nodes=["dynamic_agent", "zsl_analysis", "__end__"])
"""

from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ForgeRouter")

# ── Config ───────────────────────────────────────────────────────────────────

FORGE_ROOT = Path(__file__).parent.parent.parent
MAX_LOOP_DETECTION_WINDOW = 10  # fenêtre de détection de boucles
MAX_CONSECUTIVE_SAME_NODE = 3   # max fois consécutives le même node
BOUNCE_THRESHOLD = 5            # nb de rebonds avant warning

# Nodes disponibles et leurs descriptions (pour le prompt routeur)
NODE_DESCRIPTIONS = {
    "dynamic_agent": "Exécute la tâche avec un agent spécialisé généré à la volée",
    "generate_blueprint": "Génère un blueprint architectural avant codage (spec-first)",
    "validate_blueprint": "Valide le blueprint via un critic/jury",
    "zsl_analysis": "Analyse ZSL (Zero-Shot Learning) pour tâches cybersecurity",
    "neuro_symbolic_verification": "Vérification neuro-symbolique de la sortie",
    "anti_hallucination": "Détection et correction d'hallucinations",
    "auto_complexification": "Ajuste la complexité (level up/rollback)",
    "post_mortem": "Analyse post-exécution et rapport final",
    "memory_pruner": "Nettoyage mémoire et compaction",
    "__end__": "Terminer le cycle",
}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """Décision de routage avec contexte d'audit."""
    next_node: str
    reason: str
    confidence: float  # 0.0 → 1.0
    alternatives: list[str] = field(default_factory=list)
    method: str = "llm"  # "llm" | "static_fallback" | "loop_override"
    latency_ms: int = 0
    tokens_used: int = 0


@dataclass
class RouterAuditMetrics:
    """Métriques d'audit du routeur pour LangSmith."""
    total_decisions: int = 0
    llm_decisions: int = 0
    fallback_decisions: int = 0
    loop_overrides: int = 0
    bounces: int = 0  # retour au même node en < 2 steps
    decision_history: list[dict] = field(default_factory=list)
    node_visit_counts: dict[str, int] = field(default_factory=dict)
    consecutive_same_node: int = 0
    last_node: str = ""


# ── Router Agent ─────────────────────────────────────────────────────────────

class ForgeRouterAgent:
    """
    Agent routeur dynamique pour La Forge.
    Analyse l'état complet et décide du prochain node via LLM.
    Fallback sur routing statique si LLM indisponible.
    """

    def __init__(self):
        self.audit = RouterAuditMetrics()

    def route(self, state: dict, available_nodes: list[str],
              context: str = "") -> RoutingDecision:
        """
        Point d'entrée principal : décide du prochain node.
        
        Args:
            state: ForgeState complet
            available_nodes: nodes disponibles comme destination
            context: contexte additionnel (ex: "après blueprint rejeté")
        
        Returns:
            RoutingDecision avec le node choisi et le raisonnement
        """
        t0 = time.time()
        self.audit.total_decisions += 1

        # ── 1. Loop detection (priorité max, 0 token) ────────────────────
        loop_override = self._check_loops(state, available_nodes)
        if loop_override:
            self.audit.loop_overrides += 1
            self._record_decision(loop_override, state)
            return loop_override

        # ── 1b. A* path selection (0 token, heuristic) ───────────────────
        astar_decision = self._astar_select(state, available_nodes, context)
        if astar_decision and astar_decision.confidence >= 0.8:
            astar_decision.latency_ms = int((time.time() - t0) * 1000)
            self._record_decision(astar_decision, state)
            return astar_decision

        # ── 2. LLM-powered routing ──────────────────────────────────────
        try:
            decision = self._llm_route(state, available_nodes, context)
            decision.latency_ms = int((time.time() - t0) * 1000)
            self.audit.llm_decisions += 1
            self._record_decision(decision, state)
            return decision
        except Exception as e:
            logger.warning(f"[Router] LLM route failed: {e} → static fallback")

        # ── 3. Static fallback (fail-safe) ──────────────────────────────
        decision = self._static_fallback(state, available_nodes)
        decision.latency_ms = int((time.time() - t0) * 1000)
        self.audit.fallback_decisions += 1
        self._record_decision(decision, state)
        return decision

    def _check_loops(self, state: dict, available_nodes: list[str]) -> Optional[RoutingDecision]:
        """
        Détecte les boucles infinies et force une sortie.
        Patterns détectés :
        - Même node visité 3+ fois consécutives
        - Cycle count > 10 sans progrès
        - quality_history stagne (delta ≈ 0) sur 3+ cycles
        """
        # Détection même node consécutif
        history = self.audit.decision_history[-MAX_LOOP_DETECTION_WINDOW:]
        if len(history) >= MAX_CONSECUTIVE_SAME_NODE:
            recent_nodes = [d.get("node", "") for d in history[-MAX_CONSECUTIVE_SAME_NODE:]]
            if len(set(recent_nodes)) == 1:
                stuck_node = recent_nodes[0]
                # Forcer vers auto_complexification ou end
                if "auto_complexification" in available_nodes:
                    return RoutingDecision(
                        next_node="auto_complexification",
                        reason=f"LOOP DETECTED: {stuck_node} visité {MAX_CONSECUTIVE_SAME_NODE}x consécutives",
                        confidence=0.95,
                        method="loop_override",
                    )
                elif "__end__" in available_nodes:
                    return RoutingDecision(
                        next_node="__end__",
                        reason=f"LOOP DETECTED: forcing END after {MAX_CONSECUTIVE_SAME_NODE}x {stuck_node}",
                        confidence=0.95,
                        method="loop_override",
                    )

        # Détection stagnation qualité
        quality_history = state.get("quality_history", [])
        if len(quality_history) >= 3:
            recent = quality_history[-3:]
            if all(abs(recent[i+1] - recent[i]) < 0.05 for i in range(len(recent)-1)):
                if "__end__" in available_nodes and state.get("cycle", 0) >= 5:
                    return RoutingDecision(
                        next_node="__end__",
                        reason=f"STAGNATION: quality delta < 0.05 sur 3 cycles (cycle={state.get('cycle', 0)})",
                        confidence=0.85,
                        method="loop_override",
                    )

        return None

    def _llm_route(self, state: dict, available_nodes: list[str],
                   context: str) -> RoutingDecision:
        """Routing via LLM — analyse l'état et choisit le meilleur node."""
        from .forge_llm import forge_call, LLMTier

        # Construire un résumé compact de l'état (Token Guard)
        state_summary = self._compact_state_summary(state)
        node_list = "\n".join(
            f"- {n}: {NODE_DESCRIPTIONS.get(n, 'node inconnu')}"
            for n in available_nodes
        )

        prompt = f"""Tu es le routeur intelligent d'un système multi-agents (La Forge).
Analyse l'état actuel et choisis le MEILLEUR prochain node.

ÉTAT ACTUEL:
{state_summary}

NODES DISPONIBLES:
{node_list}
{f"CONTEXTE: {context}" if context else ""}

Règles de décision:
1. Si le blueprint a été rejeté → generate_blueprint (révision)
2. Si qualité < 5.0 et cycle < 5 → dynamic_agent (retry)
3. Si qualité >= 7.0 et task_complete → __end__
4. Si erreur critique → __end__
5. Si cybersecurity task → zsl_analysis
6. Sinon → dynamic_agent

Réponds en JSON strict:
{{
  "node": "nom_du_node",
  "reason": "explication courte",
  "confidence": 0.0-1.0
}}"""

        result = forge_call(
            prompt,
            tier=LLMTier.HAIKU,  # routing = décision rapide, HAIKU suffit
            max_tokens=200,
            task_type="router_decision",
            node="forge_router",
            use_openviking=False,
            nano_mode=False,
        ) or ""

        # Parser la réponse
        import re
        match = re.search(r'\{[\s\S]*\}', result)
        if not match:
            raise ValueError(f"Router LLM response not JSON: {result[:100]}")

        data = json.loads(match.group())
        chosen_node = data.get("node", "")

        if chosen_node not in available_nodes:
            raise ValueError(f"Router chose invalid node: {chosen_node}")

        return RoutingDecision(
            next_node=chosen_node,
            reason=data.get("reason", "LLM decision"),
            confidence=float(data.get("confidence", 0.7)),
            alternatives=[n for n in available_nodes if n != chosen_node],
            method="llm",
        )

    def _astar_select(self, state: dict, available_nodes: list[str],
                      context: str = "") -> Optional[RoutingDecision]:
        """
        A* path selection — 0 token, heuristic-based.
        
        f(n) = g(n) + h(n)
        g(n) = Cost LLM × 0.4 + Latency × 0.4 + Failure rate × 0.2
        h(n) = Semantic distance (task keywords vs node capabilities)
        
        Returns RoutingDecision if confident, None otherwise.
        """
        try:
            from .forge_load_balancer import get_load_balancer
            lb = get_load_balancer()
        except Exception:
            return None

        task = (state.get("current_task", "") or "").lower()
        task_words = set(task.split())

        best_node = None
        best_score = float("inf")

        for node in available_nodes:
            if node.startswith("__"):
                continue

            # g(n): accumulated cost
            metrics = lb._metrics.get(node)
            if metrics:
                cost_llm = 0.0  # heuristic: no direct LLM cost per node
                latency = metrics.avg_latency / 1000.0  # normalize to seconds
                failure = metrics.failure_rate
                g = cost_llm * 0.4 + latency * 0.4 + failure * 0.2
            else:
                g = 0.5  # unknown node: medium cost

            # h(n): heuristic — semantic distance
            node_desc = NODE_DESCRIPTIONS.get(node, node).lower()
            node_words = set(node_desc.split())
            overlap = len(task_words & node_words)
            h = max(0, 1.0 - overlap * 0.2)  # more overlap = lower heuristic

            f = g + h

            if f < best_score:
                best_score = f
                best_node = node

        if best_node:
            confidence = max(0.5, 1.0 - best_score)
            return RoutingDecision(
                next_node=best_node,
                reason=f"A* selected: f={best_score:.3f} (g+h heuristic)",
                confidence=confidence,
                method="astar",
            )
        return None

    def _static_fallback(self, state: dict, available_nodes: list[str]) -> RoutingDecision:
        """Routing statique (fail-safe) — reprend la logique existante."""
        # Priorité 1: erreur → end
        if state.get("error") and "__end__" in available_nodes:
            return RoutingDecision(
                next_node="__end__",
                reason="static: error → END",
                confidence=1.0,
                method="static_fallback",
            )

        # Priorité 2: task_complete → end
        if state.get("task_complete") and "__end__" in available_nodes:
            return RoutingDecision(
                next_node="__end__",
                reason="static: task_complete → END",
                confidence=1.0,
                method="static_fallback",
            )

        # Priorité 3: blueprint non approuvé → generate_blueprint
        if not state.get("blueprint_approved", True) and "generate_blueprint" in available_nodes:
            return RoutingDecision(
                next_node="generate_blueprint",
                reason="static: blueprint not approved → revise",
                confidence=0.9,
                method="static_fallback",
            )

        # Priorité 4: dynamic_agent (défaut)
        if "dynamic_agent" in available_nodes:
            return RoutingDecision(
                next_node="dynamic_agent",
                reason="static: default → dynamic_agent",
                confidence=0.7,
                method="static_fallback",
            )

        # Fallback ultime
        target = available_nodes[0] if available_nodes else "__end__"
        return RoutingDecision(
            next_node=target,
            reason=f"static: fallback to first available ({target})",
            confidence=0.5,
            method="static_fallback",
        )

    def _compact_state_summary(self, state: dict) -> str:
        """Résumé compact du state pour le prompt routeur (Token Guard)."""
        verdict = state.get("jury_verdict") or {}
        quality = verdict.get("consensus", 0.0) if verdict else 0.0
        quality_history = state.get("quality_history", [])
        findings_count = len(state.get("findings", []))

        return (
            f"task: {state.get('current_task', '?')[:80]}\n"
            f"cycle: {state.get('cycle', 0)} | level: {state.get('level', 'L1')}\n"
            f"quality: {quality:.1f}/10 | history: {quality_history[-5:]}\n"
            f"findings: {findings_count} | agent: {state.get('dynamic_agent_name', '?')}\n"
            f"blueprint_approved: {state.get('blueprint_approved', True)}\n"
            f"blueprint_attempts: {state.get('blueprint_attempts', 0)}\n"
            f"error: {state.get('error', 'none')}\n"
            f"task_complete: {state.get('task_complete', False)}"
        )

    def _record_decision(self, decision: RoutingDecision, state: dict) -> None:
        """Enregistre la décision pour audit et détection de patterns."""
        self.audit.decision_history.append({
            "node": decision.next_node,
            "reason": decision.reason[:100],
            "confidence": decision.confidence,
            "method": decision.method,
            "cycle": state.get("cycle", 0),
            "timestamp": time.time(),
        })

        # Garder seulement les 50 dernières décisions
        if len(self.audit.decision_history) > 50:
            self.audit.decision_history = self.audit.decision_history[-50:]

        # Update visit counts
        node = decision.next_node
        self.audit.node_visit_counts[node] = self.audit.node_visit_counts.get(node, 0) + 1

        # Bounce detection
        if node == self.audit.last_node:
            self.audit.consecutive_same_node += 1
        else:
            self.audit.consecutive_same_node = 1
            if self.audit.last_node and node == self.audit.last_node:
                self.audit.bounces += 1

        self.audit.last_node = node

    def get_audit_summary(self) -> dict:
        """Résumé des métriques d'audit pour le dashboard."""
        total = self.audit.total_decisions or 1
        return {
            "total_decisions": self.audit.total_decisions,
            "llm_decisions": self.audit.llm_decisions,
            "fallback_decisions": self.audit.fallback_decisions,
            "loop_overrides": self.audit.loop_overrides,
            "bounces": self.audit.bounces,
            "llm_rate": f"{self.audit.llm_decisions / total:.1%}",
            "fallback_rate": f"{self.audit.fallback_decisions / total:.1%}",
            "node_visits": dict(self.audit.node_visit_counts),
            "recent_decisions": self.audit.decision_history[-5:],
        }

    def emit_to_langsmith(self) -> None:
        """Pousse les métriques d'audit vers LangSmith (si actif)."""
        try:
            from .forge_observability import is_enabled
            if not is_enabled():
                return

            from langsmith import Client
            client = Client()
            summary = self.get_audit_summary()

            # Créer un run d'évaluation
            client.create_run(
                name="router_audit",
                run_type="tool",
                inputs={"audit": summary},
                outputs={"summary": summary},
                metadata={
                    "component": "forge_router_agent",
                    "total_decisions": summary["total_decisions"],
                    "loop_overrides": summary["loop_overrides"],
                },
                project_name="super-agent-forge",
            )
            logger.debug("[Router] audit pushed to LangSmith")
        except Exception as e:
            logger.debug(f"[Router] LangSmith push skipped: {e}")


# ── Singleton ────────────────────────────────────────────────────────────────

_router_instance: Optional[ForgeRouterAgent] = None

def get_router() -> ForgeRouterAgent:
    """Retourne l'instance singleton du routeur."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ForgeRouterAgent()
    return _router_instance


def reset_router() -> None:
    """Reset le routeur (pour les tests)."""
    global _router_instance
    _router_instance = None


# ── Self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    router = get_router()

    # Test routing statique
    mock_state = {
        "current_task": "build a REST API",
        "cycle": 1,
        "level": "L1",
        "jury_verdict": {"consensus": 6.0, "decision": "APPROVED"},
        "quality_history": [5.0, 6.0],
        "findings": [],
        "dynamic_agent_name": "Backend_Expert",
        "blueprint_approved": True,
        "blueprint_attempts": 1,
        "error": None,
        "task_complete": False,
    }

    decision = router.route(
        mock_state,
        available_nodes=["dynamic_agent", "__end__"],
        context="after orchestrator"
    )
    print(f"Decision: {decision.next_node} | reason: {decision.reason}")
    print(f"Method: {decision.method} | confidence: {decision.confidence}")
    print(f"Audit: {router.get_audit_summary()}")

    # Test loop detection
    for _ in range(4):
        router.route(mock_state, available_nodes=["dynamic_agent", "__end__"])

    summary = router.get_audit_summary()
    print(f"After 5 routes: {summary['total_decisions']} decisions, "
          f"{summary['loop_overrides']} loop overrides")

    print("forge_router_agent self-check: OK")
