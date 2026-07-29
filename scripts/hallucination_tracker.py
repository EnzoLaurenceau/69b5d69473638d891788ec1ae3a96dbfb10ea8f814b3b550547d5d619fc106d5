#!/usr/bin/env python
"""
hallucination_tracker.py — Zero-Tolerance Hallucination Auditing System
========================================================================

Intégré au dashboard Forge (7777). Tracking en temps réel.
Balance: +$20 par hallucination réelle, -$30 par fausse accusation.
Objectif: $1,000,000,000 en 6 mois.
"""

import json
import time
from datetime import datetime
from pathlib import Path

BOUNTY_FILE = Path(__file__).resolve().parents[1] / "05_STATE" / "hallucination_bounty.json"


def _load():
    if BOUNTY_FILE.exists():
        return json.loads(BOUNTY_FILE.read_text(encoding="utf-8"))
    return {
        "system": "Hallucination Bounty Tracker",
        "started_at": "2026-07-18T04:46:00",
        "deadline": "2027-01-18T04:46:00",
        "objective_usd": 1_000_000_000,
        "balance_usd": 0,
        "stats": {"real_hallucinations_caught": 0, "false_accusations": 0,
                  "total_earned": 0, "total_lost": 0, "net_balance": 0},
        "log": [],
        "rules": {"reward_per_hallucination": 20, "penalty_per_false_positive": 30}
    }


def _save(data):
    BOUNTY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def report_hallucination(evidence: str, source: str, context: str = ""):
    """Report a real hallucination found. +$20."""
    data = _load()
    data["stats"]["real_hallucinations_caught"] += 1
    data["stats"]["total_earned"] += 20
    data["balance_usd"] = data["stats"]["total_earned"] - data["stats"]["total_lost"]
    data["log"].append({
        "type": "caught",
        "amount": 20,
        "evidence": evidence,
        "source": source,
        "context": context,
        "timestamp": datetime.now().isoformat(),
        "balance_after": data["balance_usd"]
    })
    _save(data)
    print(f"[BOUNTY] +$20 | Balance: ${data['balance_usd']:,} | {evidence[:80]}")
    return data


def report_false_positive(reason: str, original_claim: str):
    """Report a false accusation. -$30."""
    data = _load()
    data["stats"]["false_accusations"] += 1
    data["stats"]["total_lost"] += 30
    data["balance_usd"] = data["stats"]["total_earned"] - data["stats"]["total_lost"]
    data["log"].append({
        "type": "false_positive",
        "amount": -30,
        "reason": reason,
        "original_claim": original_claim,
        "timestamp": datetime.now().isoformat(),
        "balance_after": data["balance_usd"]
    })
    _save(data)
    print(f"[PENALTY] -$30 | Balance: ${data['balance_usd']:,} | {reason[:80]}")
    return data


def status():
    """Print current bounty status."""
    data = _load()
    s = data["stats"]
    balance = data["balance_usd"]
    objective = data["objective_usd"]
    progress = (balance / objective * 100) if objective > 0 else 0
    
    started = datetime.fromisoformat(data["started_at"])
    deadline = datetime.fromisoformat(data["deadline"])
    now = datetime.now()
    days_left = (deadline - now).days
    days_elapsed = (now - started).days or 1
    
    rate_per_day = balance / days_elapsed if days_elapsed > 0 else 0
    needed_per_day = (objective - balance) / max(days_left, 1)
    
    print("=" * 60)
    print("HALLUCINATION BOUNTY TRACKER")
    print("=" * 60)
    print(f"  Balance:        ${balance:>15,}")
    print(f"  Objectif:       ${objective:>15,}")
    print(f"  Progression:    {progress:.8f}%")
    print(f"  Jours restants: {days_left}")
    print()
    print(f"  Hallucinations attrapées:  {s['real_hallucinations_caught']}")
    print(f"  Fausse accusations:        {s['false_accusations']}")
    print(f"  Total gagné:               ${s['total_earned']:,}")
    print(f"  Total perdu:               ${s['total_lost']:,}")
    print()
    print(f"  Taux actuel:    ${rate_per_day:,.0f}/jour")
    print(f"  Besoin:         ${needed_per_day:,.0f}/jour")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        status()
    elif len(sys.argv) > 1 and sys.argv[1] == "catch":
        evidence = sys.argv[2] if len(sys.argv) > 2 else "manual catch"
        source = sys.argv[3] if len(sys.argv) > 3 else "unknown"
        report_hallucination(evidence, source)
    elif len(sys.argv) > 1 and sys.argv[1] == "penalty":
        reason = sys.argv[2] if len(sys.argv) > 2 else "false positive"
        original = sys.argv[3] if len(sys.argv) > 3 else ""
        report_false_positive(reason, original)
    else:
        status()
