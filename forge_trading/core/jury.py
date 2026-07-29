"""
jury.py — comparaison d'avis → consensus (le "MiroFish" du trading).

Agrège les Opinion des analystes : accord directionnel pondéré + VETO du risk manager.
Optionnellement passe la thèse consolidée par la gate MiroFish (best-effort, no-op si KO).
Déterministe sur les votes (0 token) — les tokens sont dépensés UNE fois par analyste.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .smc_engine import Setup
from .analysts import Opinion, run_all


@dataclass
class Verdict:
    decision: str                 # APPROVE | REVISE | REJECT
    side: str                     # LONG | SHORT | FLAT (consensus)
    consensus: float              # 0..1 accord pondéré
    avg_score: float              # 0..10
    vetoed: bool
    opinions: list[Opinion] = field(default_factory=list)
    note: str = ""


def aggregate(setup: Setup, opinions: list[Opinion]) -> Verdict:
    want = setup.side.upper()
    wsum = sum(o.weight for o in opinions) or 1.0
    agree = sum(o.weight for o in opinions if o.vote == want) / wsum
    avg_score = sum(o.score * o.weight for o in opinions) / wsum

    risk = next((o for o in opinions if o.role == "RISK"), None)
    vetoed = bool(risk and risk.vote == "FLAT" and risk.score >= 5.0)

    if vetoed:
        decision = "REJECT"
    elif agree >= 0.6 and avg_score >= 6.0:
        decision = "APPROVE"
    elif agree >= 0.45:
        decision = "REVISE"
    else:
        decision = "REJECT"

    side = want if decision == "APPROVE" else "FLAT"
    note = "risk VETO" if vetoed else f"{agree:.0%} d'accord, score {avg_score:.1f}/10"
    return Verdict(decision, side, round(agree, 2), round(avg_score, 1), vetoed, opinions, note)


def _mirofish_gate(setup: Setup, verdict: Verdict) -> str:
    """Passe adversariale optionnelle via MiroFish (réutilise l'infra). Best-effort."""
    try:
        from forge_agents.mirofish import mirofish_gate
        plans = [{"id": o.role, "content": f"{o.vote} {o.score}/10 {o.reason}"} for o in verdict.opinions]
        mv = mirofish_gate("plan_selection", plans=plans, task_desc=f"setup {setup.pair} {setup.side}")
        return f"MiroFish={mv.decision}"
    except Exception:
        return ""


def run_jury(setup: Setup, market: dict, use_mirofish: bool = True) -> Verdict:
    opinions = run_all(setup, market)
    verdict = aggregate(setup, opinions)
    if use_mirofish:
        mf = _mirofish_gate(setup, verdict)
        if mf:
            verdict.note += f" | {mf}"
    return verdict


def _demo():
    from .smc_engine import Setup
    s = Setup(side="long", entry=100, stop=99, tp1=101, tp2=103, confidence=0.8,
              confluences=["sweep", "OB"], rr1=1.0, pair="TEST", tf="1h")
    v = run_jury(s, {"mtf_label": "haussier aligné"}, use_mirofish=False)
    assert v.decision in {"APPROVE", "REVISE", "REJECT"}
    assert len(v.opinions) == 5
    print("jury self-check OK:", v.decision, v.side, v.note)


if __name__ == "__main__":
    _demo()
