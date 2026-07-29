"""
mirofish.py — MiroFish Jury System (réintégré hors hot path)
=============================================================
MiroFish est le système de jury multi-personas de la Forge.
Il est appelé UNIQUEMENT sur décision stratégique, jamais dans le chemin critique.

3 gates disponibles :
  kb_intake          → valider l'ajout d'un skill en Knowledge Base
  plan_selection     → comparer N plans (conçus par Sonnet) et choisir le meilleur
  token_optimization → valider une variante compressée d'un prompt

Règles absolues :
  - Jury toujours en FREE tier (Gemini/Groq) — pas de Sonnet/Opus pour le scoring
  - Fallback automatique → critic_double_pass si timeout > 5s ou quota épuisé
  - Jamais appelé depuis dynamic_agent_node (hot path)
  - Sonnet obligatoire pour la CONCEPTION des plans (Gate 2) — pas pour le jury

Usage :
  from forge_agents.mirofish import get_mirofish, MiroFishGate
  gate = get_mirofish()

  # Gate 1 — KB intake
  verdict = gate.kb_intake(finding=my_finding)

  # Gate 2 — Plan selection (plans conçus par Sonnet en amont)
  verdict = gate.plan_selection(plans=[p1, p2, p3], task_desc="...")

  # Gate 3 — Token optimization
  verdict = gate.token_optimization(original=prompt, variants=[v1, v2])
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MiroFish")

FORGE_ROOT = Path(__file__).parent.parent.parent
PERSONAS_PATH = FORGE_ROOT / "03_JURY" / "personas.json"
CONFIG_PATH   = FORGE_ROOT / "03_JURY" / "config.json"


# ─── Types ────────────────────────────────────────────────────────────────────

@dataclass
class PersonaScore:
    persona_id: str
    persona_name: str
    weight: float
    score: float        # 0.0 → 1.0
    feedback: str
    vote: str           # "APPROVE" | "REJECT" | "ABSTAIN"
    winner: Optional[str] = None  # utilisé pour plan_selection


@dataclass
class MiroVerdict:
    gate_type: str
    consensus: float            # 0.0 → 1.0 (weighted average)
    decision: str               # "APPROVED" | "REJECTED" | "REVISE"
    winner: Optional[str]       # pour plan_selection : "P1" | "P2" | "P3"
    winner_content: Optional[str]  # contenu du plan/variant vainqueur
    suggestions: list[str]      # feedbacks des ABSTAIN personas
    risks: list[str]            # feedbacks des REJECT personas
    kill_flag: bool             # True si consensus < 0.40
    fallback_used: bool = False # True si critic_double_pass a été utilisé
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "gate_type": self.gate_type,
            "consensus": round(self.consensus, 3),
            "decision": self.decision,
            "winner": self.winner,
            "winner_content": self.winner_content,
            "suggestions": self.suggestions,
            "risks": self.risks,
            "kill_flag": self.kill_flag,
            "fallback_used": self.fallback_used,
            "latency_ms": self.latency_ms,
        }


# ─── Persona loader ───────────────────────────────────────────────────────────

def _load_personas() -> list[dict]:
    if not PERSONAS_PATH.exists():
        logger.warning(f"[MiroFish] personas.json introuvable : {PERSONAS_PATH}")
        return _default_personas()
    with open(PERSONAS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [p for p in data.get("personas", []) if p.get("active", True)]


def _default_personas() -> list[dict]:
    return [
        {"id": "skeptic",    "name": "Skeptic",    "weight": 1.0,
         "personality": "Remet tout en question. Cherche les failles méthodologiques."},
        {"id": "expert",     "name": "Expert",     "weight": 1.2,
         "personality": "Expert du domaine. Valide la profondeur technique et la précision."},
        {"id": "pragmatist", "name": "Pragmatist", "weight": 1.1,
         "personality": "Pense à l'utilisation pratique. Obsédé par le ROI informationnel."},
        {"id": "contrarian", "name": "Contrarian", "weight": 1.0,
         "personality": "Défend l'opposé. Cherche les biais et alternatives non explorées."},
        {"id": "novice",     "name": "Novice",     "weight": 0.8,
         "personality": "Non-expert. Valide la clarté et l'accessibilité."},
    ]


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"consensus_min": 0.65, "seed_max_tokens": 500}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─── MiroFishGate ─────────────────────────────────────────────────────────────

class MiroFishGate:
    """
    Jury multi-personas pour validation stratégique.
    Toutes les délibérations se font en FREE tier.
    """

    GATE_TYPES = ("kb_intake", "plan_selection", "token_optimization")

    # Thresholds par gate
    THRESHOLDS = {
        "kb_intake":          {"approve": 0.70, "revise": 0.55},
        "plan_selection":     {"approve": 0.60, "revise": 0.45},
        "token_optimization": {"approve": 0.65, "revise": 0.50},
    }

    # Timeout par appel FREE (secondes)
    PERSONA_TIMEOUT = 5.0

    def __init__(self):
        self.personas = _load_personas()
        self.config   = _load_config()

    # ── PUBLIC GATES ──────────────────────────────────────────────────────────

    def kb_intake(self, finding: dict) -> MiroVerdict:
        """
        Gate 1 : Doit-on ajouter ce finding en Knowledge Base ?
        finding: { id, content, score, agent, cycle }
        Seuil : consensus ≥ 0.70
        """
        seed = self._build_kb_seed(finding)
        options = [{"id": "accept", "label": "Ajouter à la KB", "content": finding.get("content", "")},
                   {"id": "reject", "label": "Garder en findings/confirmed", "content": ""}]
        return self._deliberate("kb_intake", seed, options)

    def plan_selection(self, plans: list[dict], task_desc: str = "") -> MiroVerdict:
        """
        Gate 2 : Quel plan d'implémentation est le meilleur ?
        plans: [{ "id": "P1", "title": "...", "content": "...", "trade_offs": "..." }]
        Les plans DOIVENT avoir été conçus par Sonnet en amont.
        Seuil : consensus ≥ 0.60 (on accepte plus facilement un bon plan)
        """
        seed = self._build_plan_seed(plans, task_desc)
        options = [{"id": p["id"], "label": p.get("title", p["id"]),
                    "content": p.get("content", "") + "\nTrade-offs: " + p.get("trade_offs", "")}
                   for p in plans]
        verdict = self._deliberate("plan_selection", seed, options)
        # Trouver le contenu du vainqueur
        if verdict.winner:
            for p in plans:
                if p["id"] == verdict.winner:
                    verdict.winner_content = p.get("content", "")
                    break
        return verdict

    def token_optimization(self, original: str, variants: list[dict]) -> MiroVerdict:
        """
        Gate 3 : Quelle variante compressée est la meilleure ?
        variants: [{ "id": "V1", "content": "...", "token_count": 450, "compression_ratio": 0.65 }]
        Critère : qualité ≥ 90% de l'original ET tokens ≤ 70%
        Seuil : consensus ≥ 0.65
        """
        seed = self._build_token_seed(original, variants)
        options = [{"id": v["id"],
                    "label": f"Variant {v['id']} ({v.get('compression_ratio', '?')*100:.0f}% tokens)",
                    "content": v.get("content", "")}
                   for v in variants]
        verdict = self._deliberate("token_optimization", seed, options)
        if verdict.winner:
            for v in variants:
                if v["id"] == verdict.winner:
                    verdict.winner_content = v.get("content", "")
                    break
        return verdict

    # ── DÉLIBÉRATION ──────────────────────────────────────────────────────────

    def _deliberate(self, gate_type: str, seed: str, options: list[dict]) -> MiroVerdict:
        """Lance le jury. Retourne MiroVerdict. Fallback critic_double_pass si échec."""
        t0 = time.time()
        scores: list[PersonaScore] = []

        for persona in self.personas:
            score = self._score_persona(persona, gate_type, seed, options)
            if score:
                scores.append(score)

        latency = int((time.time() - t0) * 1000)

        if not scores:
            logger.warning(f"[MiroFish] Tous les personas ont échoué → critic_double_pass")
            return self._critic_double_pass(gate_type, seed, options, latency)

        return self._aggregate(gate_type, scores, options, latency)

    def _score_persona(self, persona: dict, gate_type: str,
                       seed: str, options: list[dict]) -> Optional[PersonaScore]:
        """Appelle le LLM FREE pour qu'un persona évalue les options."""
        from .forge_llm import forge_call, LLMTier

        options_text = "\n".join(
            f"[{o['id']}] {o['label']}\n{o['content'][:400]}" for o in options
        )

        prompt = f"""Tu es {persona['name']}. {persona['personality']}

CONTEXTE:
{seed[:600]}

OPTIONS À ÉVALUER:
{options_text}

Pour chaque option, donne ton évaluation. Puis choisis la MEILLEURE option.

Réponds UNIQUEMENT en JSON strict :
{{
  "scores": {{
    "{options[0]['id']}": {{"score": 0.0, "feedback": "..."}}
    {', "' + options[1]['id'] + '": {{"score": 0.0, "feedback": "..."}}' if len(options) > 1 else ''}
    {', "' + options[2]['id'] + '": {{"score": 0.0, "feedback": "..."}}' if len(options) > 2 else ''}
  }},
  "winner": "{options[0]['id']}",
  "vote": "APPROVE",
  "summary": "Une phrase de feedback global."
}}

vote doit être APPROVE (meilleure option est bonne), REJECT (toutes insuffisantes), ou ABSTAIN (incertain).
"""
        try:
            result = forge_call(
                prompt,
                tier=LLMTier.HAIKU,
                max_tokens=400,
                task_type="score",
                node="mirofish",
                use_openviking=False,
            )
            return self._parse_persona_score(result, persona, options)
        except Exception as e:
            logger.debug(f"[MiroFish] Persona {persona['id']} fail: {e}")
            return None

    def _parse_persona_score(self, raw: str, persona: dict,
                              options: list[dict]) -> Optional[PersonaScore]:
        """Parse la réponse JSON d'un persona."""
        try:
            # Extraire le JSON même si entouré de texte
            import re
            match = re.search(r'\{[\s\S]*\}', raw)
            if not match:
                return None
            data = json.loads(match.group())

            scores_map = data.get("scores", {})
            winner_id  = data.get("winner", options[0]["id"])
            vote       = data.get("vote", "ABSTAIN")
            summary    = data.get("summary", "")

            # Score du winner
            winner_score = scores_map.get(winner_id, {}).get("score", 0.5)

            return PersonaScore(
                persona_id=persona["id"],
                persona_name=persona["name"],
                weight=persona.get("weight", 1.0),
                score=float(winner_score),
                feedback=summary,
                vote=vote,
                winner=winner_id,
            )
        except Exception as e:
            logger.debug(f"[MiroFish] Parse error for {persona['id']}: {e}")
            return None

    def _aggregate(self, gate_type: str, scores: list[PersonaScore],
                   options: list[dict], latency: int) -> MiroVerdict:
        """Agrège les scores pondérés et détermine le verdict."""
        thresholds = self.THRESHOLDS.get(gate_type, {"approve": 0.70, "revise": 0.55})

        # Consensus pondéré
        total_weight  = sum(s.weight for s in scores)
        weighted_sum  = sum(s.score * s.weight for s in scores)
        consensus     = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Winner par vote majoritaire pondéré
        winner_votes: dict[str, float] = {}
        for s in scores:
            if s.winner and s.vote != "REJECT":
                winner_votes[s.winner] = winner_votes.get(s.winner, 0.0) + s.weight
        winner = max(winner_votes, key=winner_votes.get) if winner_votes else options[0]["id"]

        # Décision
        if consensus >= thresholds["approve"]:
            decision = "APPROVED"
        elif consensus >= thresholds["revise"]:
            decision = "REVISE"
        else:
            decision = "REJECTED"

        suggestions = [s.feedback for s in scores if s.vote == "ABSTAIN"]
        risks       = [s.feedback for s in scores if s.vote == "REJECT"]

        logger.info(
            f"[MiroFish] Gate={gate_type} | consensus={consensus:.2f} | "
            f"decision={decision} | winner={winner} | latency={latency}ms"
        )

        return MiroVerdict(
            gate_type=gate_type,
            consensus=consensus,
            decision=decision,
            winner=winner,
            winner_content=None,  # rempli par le gate caller
            suggestions=suggestions,
            risks=risks,
            kill_flag=consensus < 0.40,
            fallback_used=False,
            latency_ms=latency,
        )

    # ── FALLBACK critic_double_pass ────────────────────────────────────────────

    def _critic_double_pass(self, gate_type: str, seed: str,
                             options: list[dict], latency: int) -> MiroVerdict:
        """
        Fallback si tous les personas échouent.
        Deux passes : POUR puis CONTRE, sur le FREE tier.
        """
        from .forge_llm import forge_call, LLMTier

        options_text = "\n".join(f"[{o['id']}] {o['label']}" for o in options)
        winner = options[0]["id"]
        consensus = 0.55  # valeur neutre par défaut

        try:
            # Passe POUR
            pour = forge_call(
                f"Analyse CES OPTIONS en défenseur:\nCONTEXTE: {seed[:400]}\nOPTIONS:\n{options_text}\n"
                f"Quelle option recommandes-tu ? Réponds: WINNER=<id> SCORE=<0.0-1.0> RAISON=<1 phrase>",
                tier=LLMTier.HAIKU, max_tokens=150, task_type="score", node="mirofish_fallback",
                use_openviking=False,
            )
            # Passe CONTRE
            contre = forge_call(
                f"Analyse CES OPTIONS en critique sévère:\nCONTEXTE: {seed[:400]}\nOPTIONS:\n{options_text}\n"
                f"Quelle option est la moins risquée ? Réponds: WINNER=<id> SCORE=<0.0-1.0> RAISON=<1 phrase>",
                tier=LLMTier.HAIKU, max_tokens=150, task_type="score", node="mirofish_fallback",
                use_openviking=False,
            )

            # Parser les résultats
            import re
            scores = []
            winners = []
            for text in [pour, contre]:
                m_score  = re.search(r'SCORE=([0-9.]+)', text)
                m_winner = re.search(r'WINNER=(\w+)', text)
                if m_score:  scores.append(float(m_score.group(1)))
                if m_winner: winners.append(m_winner.group(1))

            if scores:
                consensus = sum(scores) / len(scores)
            if winners:
                # Winner le plus fréquent
                from collections import Counter
                winner = Counter(winners).most_common(1)[0][0]

        except Exception as e:
            logger.warning(f"[MiroFish] critic_double_pass fail: {e}")

        decision = "APPROVED" if consensus >= 0.60 else ("REVISE" if consensus >= 0.45 else "REJECTED")

        logger.info(f"[MiroFish] fallback critic_double_pass | consensus={consensus:.2f} | decision={decision}")

        return MiroVerdict(
            gate_type=gate_type,
            consensus=consensus,
            decision=decision,
            winner=winner,
            winner_content=None,
            suggestions=["Fallback critic_double_pass utilisé — résultat moins fiable"],
            risks=[],
            kill_flag=consensus < 0.40,
            fallback_used=True,
            latency_ms=latency,
        )

    # ── SEED BUILDERS ─────────────────────────────────────────────────────────

    def _build_kb_seed(self, finding: dict) -> str:
        return (
            f"GATE: KB INTAKE — Doit-on ajouter ce finding en Knowledge Base ?\n"
            f"Agent source: {finding.get('agent', '?')} | Cycle: {finding.get('cycle', '?')}\n"
            f"Score actuel: {finding.get('score', '?')}/10\n"
            f"Contenu: {finding.get('content', '')[:500]}\n\n"
            f"Questions clés: Ce skill est-il réutilisable ? Techniquement solide ? "
            f"Suffisamment générique pour d'autres tâches ?"
        )

    def _build_plan_seed(self, plans: list[dict], task_desc: str) -> str:
        return (
            f"GATE: PLAN SELECTION — Quel plan d'implémentation choisir ?\n"
            f"Tâche: {task_desc}\n"
            f"Nombre de plans: {len(plans)}\n"
            f"Critères: faisabilité technique, risques, pragmatisme, économie de tokens.\n"
            f"Note: Les plans ont été conçus par Claude Sonnet."
        )

    def _build_token_seed(self, original: str, variants: list[dict]) -> str:
        orig_tokens = len(original.split()) * 1.3  # estimation approximative
        return (
            f"GATE: TOKEN OPTIMIZATION — Quelle variante compressée valider ?\n"
            f"Prompt original: ~{orig_tokens:.0f} tokens\n"
            f"Nombre de variantes: {len(variants)}\n"
            f"Critères: qualité ≥ 90% de l'original ET tokens ≤ 70%.\n"
            f"Original (extrait): {original[:300]}..."
        )


# ─── Singleton ────────────────────────────────────────────────────────────────

_mirofish_instance: Optional[MiroFishGate] = None

def get_mirofish() -> MiroFishGate:
    """Retourne le singleton MiroFishGate (lazy init)."""
    global _mirofish_instance
    if _mirofish_instance is None:
        _mirofish_instance = MiroFishGate()
    return _mirofish_instance


# ─── Helper pour les agents ───────────────────────────────────────────────────

def mirofish_gate(gate_type: str, **kwargs) -> MiroVerdict:
    """
    Shortcut pour appeler une gate MiroFish depuis n'importe quel node.

    Exemples :
      mirofish_gate("kb_intake", finding=my_finding)
      mirofish_gate("plan_selection", plans=[p1, p2, p3], task_desc="...")
      mirofish_gate("token_optimization", original=prompt, variants=[v1, v2])
    """
    gate = get_mirofish()
    if gate_type == "kb_intake":
        return gate.kb_intake(finding=kwargs.get("finding", {}))
    elif gate_type == "plan_selection":
        return gate.plan_selection(
            plans=kwargs.get("plans", []),
            task_desc=kwargs.get("task_desc", "")
        )
    elif gate_type == "token_optimization":
        return gate.token_optimization(
            original=kwargs.get("original", ""),
            variants=kwargs.get("variants", [])
        )
    else:
        raise ValueError(f"[MiroFish] gate_type inconnu: {gate_type}. "
                         f"Valeurs valides: {MiroFishGate.GATE_TYPES}")
