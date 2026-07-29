"""Shim d'import — `forge_agents` vu depuis la RACINE de la Forge.

Le vrai package vit dans `00_CORE/forge_agents/`. Ce shim existe pour que les
commandes lancées depuis la racine fonctionnent sans bricoler PYTHONPATH :

    python -m forge_agents.n8n_bridge import
    python -m forge_agents.forge_metrics
    python -c "from forge_agents import get_db"

Fonctionnement : `__path__` est redirigé vers le dossier réel (les sous-modules
sont donc chargés depuis `00_CORE/forge_agents/`, sans copie ni duplication),
puis le `__init__.py` réel est exécuté ici afin que les ré-exports du package
(get_db, ForgeRunner, graphify_query…) restent strictement identiques.

Ne PAS mettre de code métier dans ce fichier : la source de vérité reste
`00_CORE/forge_agents/__init__.py`.
"""

from pathlib import Path as _Path

_REAL_PKG = _Path(__file__).resolve().parent.parent / "00_CORE" / "forge_agents"

if not _REAL_PKG.is_dir():  # pragma: no cover - garde-fou d'installation
    raise ImportError(
        f"Package réel introuvable : {_REAL_PKG}. "
        "Ce shim doit rester à la racine de la Forge, à côté de 00_CORE/."
    )

# Les sous-modules (forge_agents.X) sont résolus depuis le dossier réel.
__path__ = [str(_REAL_PKG)]

# Rejoue le vrai __init__ dans ce namespace : ses imports relatifs (`from
# .forge_state import ...`) se résolvent via __path__ ci-dessus, donc les
# symboles exportés sont les mêmes objets que par un import direct.
_init_src = _REAL_PKG / "__init__.py"
exec(compile(_init_src.read_text(encoding="utf-8"), str(_init_src), "exec"))
