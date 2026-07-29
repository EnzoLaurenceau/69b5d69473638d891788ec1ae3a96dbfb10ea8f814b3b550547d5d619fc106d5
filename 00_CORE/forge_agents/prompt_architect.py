"""
prompt_architect.py — Agent spécialisé : Architecte de Prompts Ultra-Complets.

Rôle dans la Forge :
  Quand l'orchestrateur ne trouve AUCUN agent/skill existant capable de traiter
  une tâche (KB lookup miss + complexity_score élevé), forge_orchestrate() produit
  un dynamic_prompt "léger". Ce module prend le relais et génère un prompt système
  ULTRA complet pour le futur agent dynamique, suivant un template structuré en
  10 sections (rôle, mission, contexte, outils, contraintes, format de sortie,
  exemples, anti-patterns, critères de succès, escalade).

Déclenchement (voir agent_nodes.orchestrator_node) :
  kb_skill is None AND complexity_score >= NO_AGENT_MATCH_THRESHOLD

Tier : OPUS (appel rare, prompt fondateur réutilisé ensuite par dynamic_agent_node
       et potentiellement promu en KB skill → vaut l'investissement de tokens).

INSTALLATION :
  Copier ce fichier dans 00_CORE/forge_agents/prompt_architect.py
  Puis voir le bloc d'intégration suggéré en bas de fichier (commentaire) pour
  brancher should_invoke_prompt_architect() dans agent_nodes.orchestrator_node().
"""

from __future__ import annotations
import json
import logging
import re
from pathlib import Path

from .forge_llm import forge_call, LLMTier

logger = logging.getLogger("prompt_architect")

FORGE_ROOT = Path(__file__).parent.parent.parent

# Seuil : au-delà, on considère qu'aucun agent actuel ne couvre la tâche
NO_AGENT_MATCH_THRESHOLD = 0.85

ULTRA_PROMPT_TEMPLATE_SECTIONS = [
    "IDENTITE_ROLE",
    "MISSION",
    "CONTEXTE_FORGE",
    "OUTILS_ET_USAGE",
    "CONTRAINTES_REGLES",
    "FORMAT_SORTIE",
    "EXEMPLES",
    "ANTI_PATTERNS",
    "CRITERES_SUCCES",
    "ESCALADE",
    "TDD_WORKFLOW",
]

_SYSTEM_PROMPT = """Tu es le PROMPT ARCHITECT de la Forge — un méta-agent dont l'unique
mission est de concevoir le prompt système PARFAIT pour un nouvel agent expert,
quand aucun agent existant ne sait traiter la tâche demandée.

Ton prompt doit suivre EXACTEMENT ces 10 sections (utilise ces titres en majuscules) :

1. IDENTITE_ROLE — qui est cet agent, son titre d'expert, son ton.
2. MISSION — objectif précis, mesurable, borné (pas de scope creep).
3. CONTEXTE_FORGE — rappelle qu'il opère dans la Forge : accès Graphify (mémoire
   long-terme), OpenViking (contexte sémantique), findings précédents, cycle
   ESTIMATE→INIT→EXECUTE→JURY→STORE→REPORT. Doit produire un output réutilisable.
4. OUTILS_ET_USAGE — liste des outils/MCP/connecteurs pertinents pour CETTE tâche
   précise, avec quand et comment les utiliser (pas de liste générique).
5. CONTRAINTES_REGLES — limites de tokens, ton, langue (français par défaut),
   règle anti-slop (pas de "Certainly!", pas de listes creuses, pas de hedging),
   et respect du TOKEN BUDGET de la Forge.
6. FORMAT_SORTIE — structure EXACTE attendue en sortie (JSON, markdown, code...),
   avec un squelette/exemple de structure vide.
7. EXEMPLES — 1 à 2 exemples few-shot input→output courts et concrets, adaptés à
   la tâche réelle.
8. ANTI_PATTERNS — 3 à 5 erreurs spécifiques à NE PAS commettre sur cette tâche.
9. CRITERES_SUCCES — definition of done, vérifiable, pour que le jury MiroFish
   puisse scorer objectivement.
10. ESCALADE — que faire si l'agent est bloqué (manque d'info, outil indisponible,
    ambiguïté) : remonter une question précise plutôt qu'inventer.
11. TDD_WORKFLOW — si la tâche produit du code, impose le cycle RED→GREEN→REFACTOR :
    écrire le test qui échoue D'ABORD, implémenter le minimum pour passer, refactoriser.
    Inclure les commandes exactes de test (pytest, jest, etc.) et les critères de passage.

Réponds STRICTEMENT en JSON avec ce schéma :
{
  "dynamic_agent_name": "Nom_Expert_Sans_Espace",
  "ultra_prompt": "<prompt système complet, 10 sections, en français>",
  "tools_required": ["outil1", "outil2"],
  "success_criteria": ["critère 1", "critère 2"],
  "reasoning": "pourquoi ce design d'agent répond à la tâche"
}

Le ultra_prompt doit être directement utilisable comme system prompt — pas de
méta-commentaire, pas de "voici le prompt :", juste le contenu final.

═══ MÉTHODE PROMPT-MASTER (github.com/nidhinjs/prompt-master) — applique-la ═══
Principe : « le meilleur prompt n'est pas le plus long, c'est celui où CHAQUE MOT
porte du poids » (load-bearing). Rends le prompt PLUS NET, jamais plus long.
1. Outil cible : adapte au modèle qui exécutera (ex : PAS de chain-of-thought pour
   un modèle de raisonnement o1/o3 ; structure XML/sections concise sinon).
2. Couvre les 9 dimensions d'intention quand pertinentes : task, input, output,
   constraints, context, audience, memory, success_criteria, examples.
3. Techniques SÛRES uniquement : role assignment, few-shot, structure, grounding
   anchors, Memory Block des faits établis. Une seule tâche par prompt.
4. Interdis l'hallucination ("cite uniquement ce dont tu es certain, sinon dis-le").
5. AUDIT TOKENS final : supprime chaque mot qui ne change PAS la sortie (filler,
   hedging, "please/just/vraiment", formules émotionnelles). Mot mort = mot coupé."""


def _get_tool_catalog_context(task: str) -> str:
    """
    Associe automatiquement les outils du catalogue à la tâche.
    Scan le system_registry et retourne les outils pertinents.
    """
    task_lower = task.lower()
    tools = []

    # Scan system_registry for tools
    registry_dir = FORGE_ROOT / "05_STATE" / "system_registry"
    nodes_file = registry_dir / "nodes.json"
    if nodes_file.exists():
        try:
            nodes = json.loads(nodes_file.read_text(encoding="utf-8"))
            for node in nodes:
                if node.get("type") == "tool":
                    name = node.get("name", "")
                    desc = node.get("description", node.get("details", ""))
                    # Match tool to task keywords
                    tool_words = set((name + " " + desc).lower().split())
                    task_words = set(task_lower.split())
                    overlap = len(tool_words & task_words)
                    if overlap > 0 or any(kw in desc.lower() for kw in task_lower.split() if len(kw) > 3):
                        tools.append(f"- {name}: {desc[:100]}")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    # Fallback: common tools
    if not tools:
        tools = [
            "- terminal: shell commands, installs, builds",
            "- file: read/write files",
            "- web_search: search the web",
            "- forge_call: LLM calls via forge routing",
        ]

    return "\n".join(tools[:10])


def forge_prompt_architect(
    task: str,
    context: str,
    dynamic_agent_name: str = "",
    draft_prompt: str = "",
    history: str = "",
    node: str = "prompt_architect",
) -> dict:
    """
    Génère un prompt système ULTRA complet pour un agent dynamique inédit.

    Args:
        task               : description de la tâche/sous-tâche
        context            : contexte Graphify/OpenViking/findings (tronqué)
        dynamic_agent_name : nom suggéré par forge_orchestrate (peut être affiné)
        draft_prompt       : dynamic_prompt léger déjà produit par forge_orchestrate
        history            : historique caveman récent

    Returns:
        dict avec dynamic_agent_name, ultra_prompt, tools_required,
        success_criteria, reasoning. Fallback sur draft_prompt si parsing échoue.
    """
    # Auto-associate tools from catalog
    tool_catalog_context = _get_tool_catalog_context(task)

    user_prompt = (
        f"TÂCHE: {task}\n\n"
        f"CONTEXTE FORGE (Graphify/OpenViking/Findings): {context[:1200]}\n\n"
        f"OUTILS DISPONIBLES DANS LE CATALOGUE:\n{tool_catalog_context}\n\n"
        f"NOM D'AGENT SUGGÉRÉ: {dynamic_agent_name or '(à déterminer)'}\n\n"
        f"PROMPT BROUILLON EXISTANT (à enrichir, pas obligatoire de le garder):\n"
        f"{draft_prompt[:600] or '(aucun)'}\n"
    )
    if history:
        user_prompt += f"\nHISTORIQUE RÉCENT: {history[:400]}"

    result = forge_call(
        user_prompt,
        tier=LLMTier.OPUS,
        system=_SYSTEM_PROMPT,
        max_tokens=2500,
        node=node,
        task_type="critique",
        use_openviking=False,
    )

    parsed = _parse_result(result, dynamic_agent_name, draft_prompt)
    # Étape 6 prompt-master : audit tokens déterministe (zéro LLM) sur le prompt final.
    try:
        from tools.prompting.prompt_master import optimize_local as _token_audit
        parsed["ultra_prompt"] = _token_audit(parsed["ultra_prompt"])
    except Exception:
        pass  # audit best-effort, ne bloque jamais la génération
    _validate_sections(parsed["ultra_prompt"])
    return parsed


def _parse_result(result: str, fallback_name: str, fallback_prompt: str) -> dict:
    try:
        match = re.search(r'\{[\s\S]*\}', result)
        if match:
            data = json.loads(match.group())
            return {
                "dynamic_agent_name": data.get("dynamic_agent_name", fallback_name) or fallback_name or "Expert_Specialise",
                "ultra_prompt": data.get("ultra_prompt", "") or fallback_prompt,
                "tools_required": data.get("tools_required", []),
                "success_criteria": data.get("success_criteria", []),
                "reasoning": data.get("reasoning", ""),
            }
    except Exception as e:
        logger.warning(f"[prompt_architect] parsing échoué: {e}")

    return {
        "dynamic_agent_name": fallback_name or "Expert_Specialise",
        "ultra_prompt": fallback_prompt or "Tu es un expert. Résous la tâche en français, de manière concise.",
        "tools_required": [],
        "success_criteria": [],
        "reasoning": "fallback: réponse non parsable",
    }


def _validate_sections(ultra_prompt: str) -> None:
    """Log un avertissement (non-bloquant) si des sections du template sont absentes."""
    missing = [s for s in ULTRA_PROMPT_TEMPLATE_SECTIONS if s not in ultra_prompt]
    if missing:
        logger.debug(f"[prompt_architect] sections manquantes dans ultra_prompt: {missing}")


def should_invoke_prompt_architect(kb_skill: dict | None, complexity_score: float) -> bool:
    """True si aucun skill KB ne matche ET la tâche dépasse le seuil de complexité."""
    return kb_skill is None and complexity_score >= NO_AGENT_MATCH_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# INTÉGRATION SUGGÉRÉE dans agent_nodes.py — orchestrator_node()
# ─────────────────────────────────────────────────────────────────────────────
#
# Ajouter l'import en haut du fichier :
#   from .prompt_architect import forge_prompt_architect, should_invoke_prompt_architect
#
# Dans orchestrator_node(), après le calcul de `decision` / `complexity_score`
# / `dynamic_name` / `dynamic_prompt`, et AVANT la gate plan_selection :
#
#   if should_invoke_prompt_architect(kb_skill, complexity_score):
#       logging.getLogger("agent_nodes").info(
#           "[PROMPT-ARCHITECT] Aucun agent existant ne couvre cette tâche "
#           f"(complexity={complexity_score:.2f}) → conception d'un agent ULTRA."
#       )
#       arch = forge_prompt_architect(
#           task=task, context=ctx,
#           dynamic_agent_name=dynamic_name,
#           draft_prompt=dynamic_prompt,
#           history=history,
#       )
#       dynamic_name   = arch["dynamic_agent_name"]
#       dynamic_prompt = arch["ultra_prompt"]
#       log.append(_caveman("ORCH", "ULTRA_AGENT_DESIGNED",
#                            f"name={dynamic_name}", tools=arch["tools_required"]))
#
# Le ultra_prompt résultant, s'il produit un finding score >= 7.5, sera
# automatiquement candidat à la promotion KB via la gate kb_intake existante
# (_run_kb_intake_gate) — il devient donc un skill réutilisable pour les
# prochaines tâches similaires.
# ─────────────────────────────────────────────────────────────────────────────
