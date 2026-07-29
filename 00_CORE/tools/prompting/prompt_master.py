"""
prompt_master.py — Prompt Optimizer de la Forge (méthode prompt-master).
========================================================================
Source méthode : https://github.com/nidhinjs/prompt-master (skill Claude).

L'agent « Prompt Optimizer » de la Forge (commande NMP `OPT` dans nanomachine.py,
+ optimisation des system-prompts d'agents dynamiques) UTILISE cette méthode au
lieu d'une compression naïve.

Méthode prompt-master — pipeline en 7 étapes :
  1. Détecter l'outil cible (Claude/GPT/Cursor/o1-o3/Midjourney/...) → router en silence.
  2. Extraire 9 dimensions d'intention :
       task · input · output · constraints · context · audience · memory ·
       success_criteria · examples
  3. ≤3 questions de clarification SI info critique manquante (jamais plus).
  4. Router vers le bon framework de prompt (jamais montré à l'utilisateur).
  5. Appliquer UNIQUEMENT des techniques sûres : role assignment, few-shot,
     structure XML, grounding anchors, memory block — selon le besoin.
  6. Audit d'efficacité tokens : retirer chaque mot qui ne change PAS la sortie.
  7. Livrer UN bloc propre + 1 ligne de note stratégie.

Principe : « le meilleur prompt n'est pas le plus long, c'est celui où chaque mot
porte du poids » (load-bearing). On rend PLUS NET, pas plus long.

Deux niveaux :
  optimize(prompt, ...)       → pipeline complet via LLM free-tier (router Forge).
  optimize_local(prompt)      → audit tokens déterministe SANS LLM (zéro token,
                                 utilisé par le réflexe NMP `OPT`).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

# Règles déterministes de l'étape 6 (token efficiency audit) — pas de LLM requis.
# Filler/hedging qui n'altèrent jamais la sortie → supprimés.
_FILLER = re.compile(
    r"\b(please|kindly|just|really|very|actually|basically|simply|literally|"
    r"i think|i guess|maybe|perhaps|sort of|kind of|in order to|as well|"
    r"it'?s worth noting that|it is worth noting that|it'?s important to note that|"
    r"merci de|s'?il te pla[iî]t|en fait|vraiment|juste|un peu)\b",
    re.IGNORECASE,
)
# Mots émotionnels → signalés (pattern 5 : "totally broken, fix everything").
_EMOTIONAL = re.compile(r"\b(totally|completely|everything|broken|urgent|asap|horrible|terrible)\b", re.IGNORECASE)

# Méthode encodée comme system-prompt pour le pipeline complet (étapes 1-7).
PROMPT_MASTER_SYSTEM = (
    "You are Prompt Master, a prompt optimizer. Rewrite the user's raw prompt so "
    "every word is load-bearing. Run this pipeline silently:\n"
    "1. Detect the target tool and tailor to it (e.g. NO chain-of-thought for "
    "o1/o3 reasoning models; concise XML structure for Claude/Cursor).\n"
    "2. Cover the 9 intent dimensions when present: task, input, output, "
    "constraints, context, audience, memory, success_criteria, examples.\n"
    "3. Apply ONLY safe techniques as needed: role assignment, few-shot examples, "
    "XML/section structure, grounding anchors, a Memory Block of established facts.\n"
    "4. Enforce: one task per prompt; a concrete success criterion; restate full "
    "context (never 'the thing we discussed'); forbid hallucination ('cite only "
    "what you are certain of, else say so').\n"
    "5. Token audit: strip every word that does not change the output. Sharper, not longer.\n"
    "OUTPUT: the optimized prompt ONLY — one clean block, no preamble, no explanation."
)


def optimize_local(prompt: str) -> str:
    """Étape 6 déterministe (zéro LLM, zéro token) : audit d'efficacité tokens.

    Retire le filler/hedging, normalise les espaces, déduplique les lignes.
    Ne réécrit PAS le sens — ne fait que retirer ce qui ne porte pas de poids.
    """
    if not prompt:
        return ""
    text = _FILLER.sub("", prompt)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Préserve la mise en page (1 ligne vide max) — sûr sur un prompt structuré.
    # Déduplique seulement les lignes de contenu consécutives identiques.
    out, prev, blank = [], None, 0
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            blank += 1
            if blank <= 1:
                out.append("")
            prev = None
            continue
        blank = 0
        if s.strip() == prev:
            continue
        out.append(s)
        prev = s.strip()
    return "\n".join(out).strip()


def audit_flags(prompt: str) -> list[str]:
    """Signale les anti-patterns prompt-master détectables sans LLM (info, non bloquant)."""
    flags = []
    if _EMOTIONAL.search(prompt):
        flags.append("emotional/vague wording — replace with the concrete symptom")
    # deux tâches en une (pattern 2)
    if re.search(r"\b(and|et|puis|then)\b.*\b(rewrite|explain|build|fix|réécris|explique)\b",
                 prompt, re.IGNORECASE):
        flags.append("possible multi-task prompt — split into one task per prompt")
    if "the thing we discussed" in prompt.lower() or "comme convenu" in prompt.lower():
        flags.append("implicit reference — restate the full task")
    return flags


def optimize(prompt: str, target_tool: str | None = None, tier=None) -> str:
    """Pipeline prompt-master COMPLET via LLM free-tier (router Forge).

    Fallback sur optimize_local() si le routeur LLM est indisponible (zéro token).
    Retourne le prompt optimisé seul (un bloc).
    """
    try:
        from forge_agents.forge_llm import forge_call, LLMTier
    except Exception:
        return optimize_local(prompt)  # pas de LLM → audit déterministe

    sys_prompt = PROMPT_MASTER_SYSTEM
    if target_tool:
        sys_prompt += f"\nTarget tool: {target_tool}."
    flags = audit_flags(prompt)
    user = "Raw prompt:\n" + prompt
    if flags:
        user += "\n\nKnown issues to fix:\n- " + "\n- ".join(flags)
    try:
        out = forge_call(user, system=sys_prompt, tier=(tier or LLMTier.HAIKU),
                         max_tokens=1200, task_type="generate")
        return (out or "").strip() or optimize_local(prompt)
    except Exception:
        return optimize_local(prompt)


def demo():
    """ponytail: une vérif runnable sur l'audit déterministe (logique non triviale)."""
    raw = "Please just kindly  rewrite this   function, it's totally broken, in order to fix everything"
    out = optimize_local(raw)
    assert "please" not in out.lower() and "kindly" not in out.lower(), out
    assert "in order to" not in out.lower() and "  " not in out, out
    assert "rewrite this function" in out.lower(), out
    flags = audit_flags(raw)
    assert any("emotional" in f for f in flags), flags
    print("prompt_master.demo OK | local:", repr(out))
    print("flags:", flags)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    elif len(sys.argv) > 1:
        print(optimize(" ".join(sys.argv[1:])))
    else:
        print("Usage: prompt_master.py [demo | <raw prompt to optimize>]")
