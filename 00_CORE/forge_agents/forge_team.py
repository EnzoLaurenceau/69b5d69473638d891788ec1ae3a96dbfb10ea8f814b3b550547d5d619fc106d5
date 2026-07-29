"""
forge_team.py — Exécution HYBRIDE en équipe d'experts pour La Forge.
====================================================================
L'orchestrateur DÉCOMPOSE chaque task en micro-tasks et affecte UN expert dédié
par micro-task. Chaque expert EXÉCUTE sa micro-task, en voyant les résultats des
micro-tasks précédentes (interaction par contexte partagé). Un lead synthétise
les sorties en une réponse finale.

Un expert conçu à la volée qui produit un résultat bien noté est promu au
roster KB (KB-SKILL-*.json) → rappelable au prochain match. Le roster grossit
tout seul (de plus en plus d'experts ultra-spécialisés).

Ne réinvente RIEN — réutilise :
  - kb_manager.lookup / add_skill_from_finding → rappel + croissance du roster
  - forge_prompt_architect      → conception JIT d'un expert ULTRA (si nouveau)
  - forge_call (FREE tier)       → exécution des experts + synthèse

Topologie LangGraph inchangée : tout se passe DANS dynamic_agent_node (le lead
= synthétiseur qui pilote le pipeline d'experts).

NMP: TOOL|INDEX|forge_team|savings=0|pattern=one expert per micro-task pipeline|approach=decompose + dedicated expert per micro-task + KB auto-persist
"""

from __future__ import annotations
import re
import logging
from types import SimpleNamespace
from typing import Optional

log = logging.getLogger("forge_team")

# ── Réglages (ponytail : bornés, à relever seulement si un vrai besoin le montre)
MAX_MICRO_TASKS   = 6     # nb max de micro-tasks (= experts) par task
PERSIST_SCORE_MIN = 7.0   # expert conçu promu au roster KB si score >= ce seuil
KB_RECALL_THRESH  = 0.60  # rappel roster plus permissif que le lookup orchestrateur (0.75)

_STOP = frozenset({
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "en", "pour", "avec",
    "sur", "dans", "au", "aux", "the", "a", "an", "of", "to", "and", "for", "with",
    "que", "qui", "est", "ce", "sa", "son", "ses", "il", "elle", "on", "par", "plus",
})


def _seed_name(desc: str) -> str:
    """Nom de spécialiste dérivé des mots-clés d'un micro-step (heuristique 0-token)."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", desc.lower())
             if len(w) > 2 and w not in _STOP]
    key = "_".join(w.capitalize() for w in words[:2]) or "Specialist"
    return f"Expert_{key}"


# Fallback déterministe : découpe par phases logiques (phrases + connecteurs),
# PAS par budget tokens. Utilisé si la décomposition sémantique LLM échoue.
_PHASE_RE = re.compile(
    r"[.!?;\n]+|\b(?:puis|ensuite|enfin|alors|then|and then|apr[eè]s)\b", re.IGNORECASE)


def _semantic_decompose(task: str) -> list[str]:
    """
    Décomposition SÉMANTIQUE en micro-tasks atomiques via LLM (FREE tier).
    Sépare finement même une phrase unique complexe. Retourne [] si échec →
    l'appelant retombe sur le split regex déterministe.
    """
    from .forge_llm import forge_call, LLMTier
    prompt = (
        "Décompose cette demande en micro-tasks ATOMIQUES : chacune = UNE action "
        "précise exécutable par UN seul expert spécialisé. Une micro-task par "
        "ligne, préfixée '- '. Pas de numéros, pas de sous-étapes, pas de blabla. "
        "Si la demande est déjà atomique, renvoie une seule ligne.\n\n"
        f"Demande : {task}"
    )
    try:
        out = forge_call(prompt, tier=LLMTier.HAIKU, max_tokens=400,
                         task_type="fast_extraction")
    except Exception as e:  # pragma: no cover - best effort
        log.warning("semantic decompose fail: %s", e)
        return []
    missions = []
    for line in (out or "").splitlines():
        line = line.strip().lstrip("-*•").strip()
        line = re.sub(r"^\d+[.)]\s*", "", line).strip()
        if len(line) > 4:
            missions.append(line)
    return missions[:MAX_MICRO_TASKS]


def assemble_team(task: str, lead_name: str, semantic: bool = True) -> dict:
    """
    Décompose la task en micro-tasks et affecte UN expert dédié à chacune.

    Décomposition SÉMANTIQUE via LLM (FREE) par défaut ; fallback sur un split
    regex déterministe (phrases/connecteurs) si le LLM échoue ou renvoie < 2
    micro-tasks. `semantic=False` force le fallback (utilisé par le self-check,
    zéro LLM).

    Retourne {lead, specialists:[{name, mission}]} où chaque `specialist` EST
    l'expert d'UNE micro-task. Le prompt ULTRA de l'expert n'est conçu (JIT) ou
    rappelé du roster qu'au moment de l'exécution. {} si la task n'a qu'une seule
    micro-task (le lead l'exécute seul, comportement historique).
    """
    missions = _semantic_decompose(task) if semantic else []
    if len(missions) < 2:  # LLM off/échec/atomique → split déterministe
        missions = [p.strip() for p in _PHASE_RE.split(task or "") if p and p.strip()]

    specialists, seen = [], set()
    for desc in missions:
        # micro-task trop maigre (< 2 mots signifiants) → ignorée
        if len([w for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", desc.lower())
                if len(w) > 2 and w not in _STOP]) < 2:
            continue
        name = _seed_name(desc)
        if name in seen:
            continue
        seen.add(name)
        specialists.append({"name": name, "mission": desc[:200]})
        if len(specialists) >= MAX_MICRO_TASKS:
            break

    # Une seule micro-task = pas d'équipe, le lead suffit (ponytail).
    if len(specialists) < 2:
        return {}
    return {"lead": lead_name, "specialists": specialists}


def resolve_expert(name: str, mission: str, ctx: str, task: str) -> dict:
    """
    Résout un expert : roster KB → conception JIT (marqué pour persistance).
    Retourne {name, prompt, source, designed}.
    """
    # 1. Rappel roster KB (l'expert existe peut-être déjà)
    try:
        from .kb_manager import get_kb_manager
        skill = get_kb_manager().lookup(f"{name} {mission}", threshold=KB_RECALL_THRESH)
    except Exception:
        skill = None
    if skill:
        return {"name": skill.get("name", name), "prompt": skill.get("prompt", ""),
                "source": "kb", "designed": False}

    # 2. Conception JIT d'un expert ULTRA via le prompt architect
    try:
        from .prompt_architect import forge_prompt_architect
        arch = forge_prompt_architect(
            task=mission or task, context=ctx[:2000],
            dynamic_agent_name=name,
            draft_prompt=f"Tu es {name}, ultra-spécialisé sur : {mission}",
            history="",
        )
        return {"name": arch.get("dynamic_agent_name", name),
                "prompt": arch.get("ultra_prompt", ""),
                "source": "designed", "designed": True}
    except Exception as e:
        log.warning("design fail %s: %s", name, e)
        return {"name": name,
                "prompt": f"Tu es {name}, un expert ultra-spécialisé. Mission : {mission}. Réponds précis, sans blabla.",
                "source": "fallback", "designed": True}


def call_expert(expert: dict, question: str, ctx: str) -> tuple[str, float]:
    """Exécute un spécialiste (HAIKU tier) et retourne (réponse, score)."""
    from .forge_llm import forge_call, forge_score, LLMTier
    ans = forge_call(
        f"{question}\n\nContexte:\n{ctx[:1500]}",
        system=expert.get("prompt", ""),
        tier=LLMTier.HAIKU, max_tokens=800, task_type="generate",
    )
    try:
        score = float(forge_score(ans, question))
    except Exception:
        score = 7.0
    return ans, score


def _maybe_persist(expert: dict, answer: str, score: float) -> Optional[str]:
    """Promeut un expert CONÇU et bien noté au roster KB. No-op sinon."""
    if not expert.get("designed") or score < PERSIST_SCORE_MIN:
        return None
    try:
        from .kb_manager import get_kb_manager
        finding = {
            "title": expert["name"],
            "content": expert.get("prompt") or answer,
            "agent": expert["name"],
            "score": score,
        }
        verdict = SimpleNamespace(consensus=score / 10.0, fallback_used=False)
        return get_kb_manager().add_skill_from_finding(finding, verdict)
    except Exception as e:  # pragma: no cover - best effort
        log.warning("persist fail %s: %s", expert.get("name"), e)
        return None


def run_team(lead_name: str, lead_prompt: str, task: str, ctx: str,
             team: dict) -> tuple[str, list]:
    """
    Pipeline : UN expert dédié EXÉCUTE chaque micro-task, puis le lead synthétise.

    Chaque expert voit les résultats des micro-tasks précédentes (interaction par
    contexte partagé). Expert conçu JIT + bien noté → promu au roster KB.
    Retourne (réponse_finale, nmp_log) — nmp_log = lignes caveman à agréger.
    """
    from .forge_llm import forge_call, LLMTier

    specialists = team.get("specialists", [])
    logs: list = [f"NMP|TEAM|{lead_name}|pipeline|micro_tasks={len(specialists)}"]
    shared = ""        # sorties accumulées des micro-tasks précédentes
    results: list = []

    for i, spec in enumerate(specialists, 1):
        name, mission = spec["name"], spec.get("mission", "")
        expert = resolve_expert(name, mission, ctx, task)
        sub_ctx = ctx
        if shared:
            sub_ctx += "\n\n--- Résultats des micro-tasks précédentes ---\n" + shared
        ans, score = call_expert(expert, mission, sub_ctx)
        skill_id = _maybe_persist(expert, ans, score)
        logs.append(
            f"NMP|TEAM|{lead_name}|MICRO{i}|{expert['name']}|{expert['source']}|score={score:.1f}"
            + (f"|persist={skill_id}" if skill_id else "")
        )
        results.append({"expert": expert["name"], "mission": mission, "output": ans, "score": score})
        shared += f"\n[{expert['name']} — {mission[:60]}]\n{ans[:600]}\n"

    # Une seule micro-task exécutée → pas de synthèse nécessaire.
    if len(results) == 1:
        return results[0]["output"], logs

    synth_prompt = (
        f"Task globale : {task}\n\n"
        "Résultats de chaque micro-task, produits par des experts dédiés :\n\n"
        + "\n\n".join(f"### {r['expert']} — {r['mission'][:80]}\n{r['output'][:800]}"
                      for r in results)
        + "\n\nSynthétise en UNE réponse finale cohérente. Élimine les redites, "
          "garde toute l'info utile."
    )
    final = forge_call(synth_prompt, system=lead_prompt, tier=LLMTier.HAIKU,
                       max_tokens=1500, task_type="generate")
    logs.append(f"NMP|TEAM|{lead_name}|SYNTHESIZE|experts={len(results)}")
    return final, logs


# ── Self-check (ponytail : une vérif runnable sur la logique non triviale) ──────
def _demo() -> None:
    # nom de graine déterministe, sans stopwords
    assert _seed_name("le audit de securite du site") == "Expert_Audit_Securite", _seed_name("le audit de securite du site")

    # assemble_team (fallback déterministe) : task mono-micro-task → lead seul
    assert assemble_team("ping", "Lead", semantic=False) == {}

    # task multi-phrase → 1 expert par micro-task, noms distincts
    t = ("Scanne les sous-domaines de la cible. "
         "Ensuite audite la sécurité des endpoints. "
         "Enfin rédige un rapport de synthèse.")
    team = assemble_team(t, "Lead_Recon", semantic=False)
    assert team and team["lead"] == "Lead_Recon", team
    assert len(team["specialists"]) == 3, team
    assert len({s["name"] for s in team["specialists"]}) == 3, "noms non uniques"

    # décomposition SÉMANTIQUE (forge_call stubbé) : découpe une phrase unique
    import forge_agents.forge_llm as fl
    _o = fl.forge_call
    fl.forge_call = lambda *a, **k: ("- enumerer les buckets S3 publics\n"
                                     "- tester chaque bucket en lecture\n"
                                     "- rapporter les fuites")
    try:
        st = assemble_team("audite le stockage cloud de la cible", "Lead_Cloud")
    finally:
        fl.forge_call = _o
    assert st and len(st["specialists"]) == 3, st
    assert st["specialists"][0]["mission"] == "enumerer les buckets S3 publics", st

    # pipeline : UN expert exécute CHAQUE micro-task (stubs, zéro LLM)
    import forge_agents.forge_team as ft
    calls = []
    ft.resolve_expert = lambda name, mission, ctx, task: {
        "name": name, "prompt": f"P:{mission}", "source": "stub", "designed": False}
    def _fake_call(expert, mission, ctx):
        calls.append((expert["name"], "précédentes" in ctx))  # 2e+ voit les résultats précédents
        return f"out:{mission[:20]}", 8.0
    ft.call_expert = _fake_call
    # synthèse stub → renvoie le nb d'experts vus
    import forge_agents.forge_llm as fl
    _orig = fl.forge_call
    fl.forge_call = lambda *a, **k: "FINAL_SYNTHESIS"
    try:
        final, logs = ft.run_team("Lead_Recon", "lead-sys", t, "CTX", team)
    finally:
        fl.forge_call = _orig
    assert len(calls) == 3, f"attendu 1 expert/micro-task, eu {len(calls)}"
    assert calls[0][1] is False and calls[1][1] is True, "contexte partagé non propagé"
    assert final == "FINAL_SYNTHESIS", final
    micro_logs = [l for l in logs if "|MICRO" in l]
    assert len(micro_logs) == 3, micro_logs

    print("forge_team self-check OK ->",
          [s["name"] for s in team["specialists"]], "| pipeline experts:", len(calls))


if __name__ == "__main__":
    _demo()
