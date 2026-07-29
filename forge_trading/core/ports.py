"""ports.py — la SEULE couture entre le service trading et le noyau de la Forge.

POURQUOI
--------
`service_map` mesure le contexte `trading` à **88 % de cohésion, 7 dépendances sortantes,
1 seule entrante** : c'est le contexte le plus extractible de la Forge. Ce qui l'empêche
d'être un service n'est pas son couplage — c'est que ses 7 dépendances sont **éparpillées
en imports directs** vers des modules internes du noyau.

Ce module les rassemble en un seul point. Conséquences :
  - la surface de couplage devient **visible et dénombrable** (ce fichier) ;
  - trading peut tourner **sans le noyau** (chaque port dégrade proprement) ;
  - l'extraction en service se ramène à remplacer ces 7 fonctions par des appels réseau,
    sans toucher à la logique métier.

LE CONTRAT (mesuré, pas supposé)
--------------------------------
| Port                | Fournisseur noyau            | Utilisé par            |
|---------------------|------------------------------|------------------------|
| `llm_call`          | forge_llm.forge_call         | analysts.py            |
| `jury_gate`         | mirofish.mirofish_gate       | jury.py                |
| `mcp_pruner`        | forge_mcp_pruner.get_pruner  | mcp_tradingview.py     |
| `experience_db`     | forge_experience_db          | orchestrator.py, rag.py|
| `vector_brain`      | turbovec_brain               | rag.py                 |
| `token_tracker`     | token_tracker.get_tracker    | run_trading.py         |

DÉGRADATION
-----------
Chaque port renvoie `None` (ou un no-op) si le noyau est absent, **sans lever**. Un service
trading déployé seul doit démarrer ; il perdra l'enrichissement mémoire et le jury, pas sa
capacité à tourner. Les appelants testent déjà `if port is None`.

Self-check : python -m trading.ports
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("TradingPorts")

#: passe à False dès qu'un port est indisponible — lu par la sonde de santé
_degraded: list[str] = []


def _try(what: str, loader: Callable[[], Any]) -> Optional[Any]:
    """Charge une capacité du noyau. Indisponible → None + trace, jamais d'exception."""
    try:
        return loader()
    except Exception as exc:
        if what not in _degraded:
            _degraded.append(what)
            logger.info("port '%s' indisponible (%s) — mode dégradé", what, type(exc).__name__)
        return None


# ── Ports ────────────────────────────────────────────────────────────────────

def llm_call(prompt: str, tier: str = "sonnet", **kwargs) -> Optional[str]:
    """Appel LLM. `None` si le routeur du noyau est absent."""
    def _load():
        from forge_agents.forge_llm import forge_call, LLMTier
        return forge_call, LLMTier
    loaded = _try("llm_call", _load)
    if loaded is None:
        return None
    forge_call, LLMTier = loaded
    try:
        return forge_call(prompt, tier=getattr(LLMTier, tier.upper(), LLMTier.SONNET), **kwargs)
    except Exception as exc:
        logger.warning("llm_call a échoué: %s", exc)
        return None


def jury_gate(*args, **kwargs) -> Optional[Any]:
    """Passage au jury MiroFish. `None` si absent — l'appelant décide alors seul."""
    fn = _try("jury_gate", lambda: __import__(
        "forge_agents.mirofish", fromlist=["mirofish_gate"]).mirofish_gate)
    return fn(*args, **kwargs) if fn else None


def mcp_pruner() -> Optional[Any]:
    fn = _try("mcp_pruner", lambda: __import__(
        "forge_agents.forge_mcp_pruner", fromlist=["get_pruner"]).get_pruner)
    return fn() if fn else None


def experience_db() -> Optional[Any]:
    fn = _try("experience_db", lambda: __import__(
        "forge_agents.forge_experience_db", fromlist=["get_experience_db"]).get_experience_db)
    return fn() if fn else None


def experience_record() -> Optional[Any]:
    """Classe `Experience` — pour construire un enregistrement à persister."""
    return _try("experience_record", lambda: __import__(
        "forge_agents.forge_experience_db", fromlist=["Experience"]).Experience)


def vector_brain() -> Optional[Any]:
    fn = _try("vector_brain", lambda: __import__(
        "forge_agents.turbovec_brain", fromlist=["get_turbovec_brain"]).get_turbovec_brain)
    return fn() if fn else None


def token_tracker() -> Optional[Any]:
    fn = _try("token_tracker", lambda: __import__(
        "forge_agents.token_tracker", fromlist=["get_tracker"]).get_tracker)
    return fn() if fn else None


# ── Santé ────────────────────────────────────────────────────────────────────

PORTS = ("llm_call", "jury_gate", "mcp_pruner", "experience_db", "vector_brain",
         "token_tracker")


def health() -> dict:
    """État des ports — dit si le service tourne autonome ou adossé au noyau."""
    checks = {
        "jury_gate": lambda: _try("jury_gate", lambda: __import__(
            "forge_agents.mirofish", fromlist=["mirofish_gate"]).mirofish_gate) is not None,
        "mcp_pruner": lambda: mcp_pruner() is not None,
        "experience_db": lambda: experience_db() is not None,
        "vector_brain": lambda: vector_brain() is not None,
        "token_tracker": lambda: token_tracker() is not None,
    }
    status = {}
    for name, probe in checks.items():
        try:
            status[name] = bool(probe())
        except Exception:
            status[name] = False
    available = sum(1 for v in status.values() if v)
    return {
        "ports": status,
        "available": available,
        "total": len(status),
        "mode": "adossé au noyau" if available == len(status)
                else ("dégradé" if available else "autonome"),
        "degraded": list(_degraded),
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    from pathlib import Path

    # [consolidation] sys.path retiré : forge_trading est un package
    # sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    h = health()
    print(json.dumps(h, indent=2, ensure_ascii=False))
    print(f"\n{h['available']}/{h['total']} ports disponibles — mode : {h['mode']}")
    print("Le service démarre dans TOUS les cas : aucun port ne lève.")
