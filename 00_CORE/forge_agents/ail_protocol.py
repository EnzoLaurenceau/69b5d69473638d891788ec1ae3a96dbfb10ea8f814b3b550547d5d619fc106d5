"""
ail_protocol.py — AIL (Agent Inter-Lingo)
===========================================
Format de communication ULTRA-COMPACT entre agents/sub-agents de la
Forge (cf. CLAUDE.md — "ECONOMISER AU MAX").

Principe :
  - Tous les échanges INTERMÉDIAIRES entre IA (agent_output d'un cycle,
    findings stockés, handoffs orchestrateur <-> agent dynamique) sont
    produits en AIL : une grammaire à base de codes courts, sans
    phrases, sans politesse, sans markdown.
  - Le LANGAGE NATUREL (français) n'est généré QU'UNE SEULE FOIS :
    au moment de présenter le résultat final à l'utilisateur
    (_print_result / post_mortem). Le décodage AIL -> français est
    100% déterministe (dictionnaire), donc ZÉRO appel LLM
    supplémentaire pour traduire.

Grammaire AIL (une ligne = un message/finding) :
  VERBE|cle1=val1,cle2=val2,...|score

  - VERBE  : code court en MAJUSCULES (voir AIL_VERBS ; les codes
             inconnus sont affichés tels quels au décodage — extensible
             librement par les agents dynamiques générés à la volée).
  - cle=val : paires clé=valeur séparées par des virgules. Valeurs
             courtes (<60 car.), pas de virgules à l'intérieur (';' à
             la place).
  - score  : optionnel, nombre (ex: score de confiance/qualité).

Exemple :
  FND|n=PromptFlow,p=app_ia,st=niche_créateurs|8.2
  -> décodé : "a trouvé : nom=PromptFlow, produit=app_ia, stratégie=niche_créateurs (score=8.2)"

Intégration (agent_nodes.py) :
  - dynamic_agent_node() ajoute AIL_SYSTEM_SUFFIX au system_prompt de
    CHAQUE agent dynamique -> sortie intermédiaire en AIL.
  - run_forge.py (_print_result) appelle decode_block()/decode_line()
    UNIQUEMENT sur le contenu affiché à l'utilisateur final.
"""

from __future__ import annotations

import re

# ── Dictionnaires de décodage (déterministe, zéro LLM) ──────────────────────

AIL_VERBS = {
    "SCN": "a analysé",
    "FND": "a trouvé",
    "REC": "recommande",
    "RSK": "signale un risque",
    "PLN": "propose un plan",
    "ACT": "propose l'action",
    "DON": "a terminé",
    "ERR": "a rencontré une erreur",
    "SCR": "a scrapé",
    "GEN": "a généré",
}

AIL_KEYS = {
    "n": "nom", "p": "produit", "s": "score", "st": "stratégie",
    "src": "source", "ct": "contenu", "url": "url", "tk": "tokens",
    "niche": "niche", "agt": "agent", "cx": "complexité",
}

AIL_LINE_RE = re.compile(r'^\s*([A-Z]{2,5})\|([^|]*)\|?\s*([\d.]*)\s*$')

# ── Suffixe injecté dans le system prompt des agents dynamiques ─────────────

AIL_SYSTEM_SUFFIX = (
    "\n\n--- PROTOCOLE AIL (Agent Inter-Lingo) — OBLIGATOIRE ---\n"
    "Cette sortie est un échange INTERNE entre agents, PAS la réponse "
    "finale à l'utilisateur. Réponds UNIQUEMENT en AIL, format compact, "
    "UNE LIGNE PAR ÉLÉMENT (finding/recommandation/risque/action) :\n"
    "  VERBE|cle1=val1,cle2=val2|score\n"
    "Verbes dispo (ou invente un code court en MAJUSCULES si besoin) :\n"
    "  SCN=analyse FND=trouvaille REC=recommandation RSK=risque "
    "PLN=plan ACT=action DON=terminé ERR=erreur GEN=génération\n"
    "INTERDIT : phrases complètes, politesse, markdown, listes à puces. "
    "Valeurs courtes (<60 caractères), pas de virgule dans une valeur "
    "(utilise ';'). Une ligne AIL par information distincte."
)


# ── Décodage (utilisé UNIQUEMENT pour la présentation finale) ───────────────

def decode_line(line: str) -> str:
    """Décode UNE ligne AIL en français lisible. Best-effort, déterministe."""
    line = line.strip()
    if not line:
        return ""
    m = AIL_LINE_RE.match(line)
    if not m:
        return line  # pas du AIL reconnu -> affiché tel quel
    verb_code, kv_raw, score = m.groups()
    verb = AIL_VERBS.get(verb_code, verb_code)
    parts = []
    for kv in kv_raw.split(","):
        kv = kv.strip()
        if not kv or "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        key = AIL_KEYS.get(k.strip(), k.strip())
        parts.append(f"{key}={v.strip()}")
    detail = ", ".join(parts)
    suffix = f" (score={score})" if score else ""
    out = f"{verb}"
    if detail:
        out += f" : {detail}"
    return out + suffix


def decode_block(text: str, bullet: str = "- ") -> str:
    """Décode un bloc multi-lignes AIL en texte français lisible (une puce/ligne)."""
    if not text:
        return ""
    out_lines = []
    for raw in text.splitlines():
        decoded = decode_line(raw)
        if decoded:
            out_lines.append(f"{bullet}{decoded}")
    return "\n".join(out_lines)


def is_ail(text: str) -> bool:
    """Heuristique : ce texte ressemble-t-il majoritairement à de l'AIL ?"""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return False
    hits = sum(1 for l in lines if AIL_LINE_RE.match(l))
    return hits >= max(1, len(lines) // 2)
