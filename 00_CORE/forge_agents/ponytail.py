"""
ponytail.py — Couche YAGNI (inspirée de github.com/DietrichGebert/ponytail, MIT)
================================================================================
Injecte "le dev senior le plus paresseux" dans la génération de code de la Forge :
le meilleur code est celui qu'on n'écrit pas. Appliqué au system-prompt des
tâches de code (dynamic_agent + persona senior_dev).

Usage :
    from .ponytail import yagni_suffix
    forge_call(prompt, system=base + yagni_suffix(task), ...)
"""
from __future__ import annotations

import re

# Échelle YAGNI : l'agent s'arrête au premier barreau qui tient.
PONYTAIL_YAGNI = """
[PONYTAIL — YAGNI / le meilleur code est celui qu'on n'écrit pas]
Avant d'écrire du code, arrête-toi au PREMIER barreau qui tient :
  1. Ça doit exister ?                 → non : skip (YAGNI)
  2. La stdlib le fait ?                → utilise-la
  3. Feature native de la plateforme ? → utilise-la (ex: <input type="date">)
  4. Dépendance déjà installée ?       → utilise-la
  5. Une ligne suffit ?                → une ligne
  6. Seulement alors : le minimum qui marche
Paresseux, pas négligent : validation des entrées non fiables, gestion de la
perte de données, sécurité et accessibilité ne sont JAMAIS sacrifiées.
Marque chaque raccourci d'un commentaire `ponytail:` nommant le chemin d'upgrade.
Pas de sur-ingénierie, pas d'abstraction spéculative, pas de wrapper inutile.
""".strip()

# Signaux d'une tâche de génération de code (EN + FR).
_CODE_RE = re.compile(
    r"\b(code|coder|coding|function|fonction|impl[ée]ment\w*|build|g[ée]n[ée]r\w*|generate|"
    r"script|component|composant|class(?:e)?|module|refactor\w*|debug|fix|bug|api|endpoint|"
    r"sql|query|requ[êe]te|html|css|javascript|typescript|python|react|vue|svelte|django|"
    r"flask|fastapi|node|backend|frontend|landing|webapp|feature|fonctionnalit[ée]|"
    r"unit ?test|wrapper|parser|regex|algo\w*)\b",
    re.IGNORECASE,
)


def is_code_task(task: str) -> bool:
    return bool(task and _CODE_RE.search(task))


def yagni_suffix(task: str) -> str:
    """Suffixe system-prompt YAGNI si la tâche est de la génération de code, sinon ''."""
    return ("\n\n" + PONYTAIL_YAGNI) if is_code_task(task) else ""
