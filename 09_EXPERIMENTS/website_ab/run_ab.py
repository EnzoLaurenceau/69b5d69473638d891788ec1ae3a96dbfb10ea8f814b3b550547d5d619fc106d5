#!/usr/bin/env python3
"""
run_ab.py — harness A/B "site web", tracé LangSmith.
====================================================
Même brief, même protocole d'écriture, même dossier de sortie.
SEUL le cerveau change :

  --arm nu     → Claude nu (anthropic SDK wrappé LangSmith), 0 règle forge.
                 Projet LangSmith: ab-website-nu
  --arm forge  → forge_orchestrate (recrute un expert) + forge_call (RTK/cache/
                 tiers/nano). Projet LangSmith: ab-website-forge

Protocole fichier (identique aux 2 bras, c'est de la plomberie, pas un indice
métier). L'agent répond avec 0..n blocs puis <<<DONE>>> :

  <<<FILE index.html>>>
  ...contenu...
  <<<END>>>

Usage :
  python run_ab.py --arm nu
  python run_ab.py --arm forge
  python run_ab.py --arm nu --model claude-sonnet-5 --max-steps 12

Prérequis .env (racine forge) : ANTHROPIC_API_KEY, LANGSMITH_TRACING=true,
LANGSMITH_API_KEY. Sans clé LangSmith → tourne quand même, sans trace.
"""
from __future__ import annotations
import argparse, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORGE_ROOT = HERE.parents[1]          # 09_EXPERIMENTS/website_ab -> racine
BRIEF = (HERE / "BRIEF.md").read_text(encoding="utf-8")

# Protocole commun aux 2 bras (plomberie neutre — aucun indice sur les tâches implicites)
PROTOCOL = (
    "Tu produis un site web complet en écrivant des fichiers. Pour CHAQUE fichier :\n"
    "<<<FILE chemin/relatif.ext>>>\n<contenu intégral>\n<<<END>>>\n"
    "Écris autant de fichiers que nécessaire (tu peux en écrire plusieurs par message). "
    "Quand le site est terminé et livrable, réponds UNIQUEMENT <<<DONE>>>.\n"
    "Ne mets aucun commentaire hors des blocs FILE."
)
FILE_RE = re.compile(r"<<<FILE\s+(.+?)>>>\r?\n(.*?)\r?\n<<<END>>>", re.S)


def _load_dotenv() -> None:
    for env_path in (FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _write_files(text: str, out_dir: Path) -> list[str]:
    written = []
    for rel, content in FILE_RE.findall(text):
        rel = rel.strip().lstrip("/\\")
        dest = (out_dir / rel).resolve()
        if out_dir.resolve() not in dest.parents and dest != out_dir.resolve():
            continue  # ponytail: garde-fou path-traversal, on ignore hors du build dir
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel)
    return written


# ── BRAIN: NU ────────────────────────────────────────────────────────────────
def brain_nu(model: str):
    os.environ["LANGSMITH_PROJECT"] = "ab-website-nu"
    os.environ["LANGCHAIN_PROJECT"] = "ab-website-nu"
    from anthropic import Anthropic
    try:
        from langsmith.wrappers import wrap_anthropic
        client = wrap_anthropic(Anthropic())
    except Exception:
        client = Anthropic()          # pas de langsmith → sans trace, on continue
    system = "Tu es développeur web. Réalise le site demandé par le client.\n\n" + PROTOCOL

    def step(history: list[dict]) -> str:
        r = client.messages.create(model=model, max_tokens=8000, system=system, messages=history)
        return "".join(b.text for b in r.content if b.type == "text")
    return step


# ── BRAIN: FORGE ─────────────────────────────────────────────────────────────
def brain_forge():
    os.environ["LANGSMITH_PROJECT"] = "ab-website-forge"
    os.environ["LANGCHAIN_PROJECT"] = "ab-website-forge"
    sys.path.insert(0, str(FORGE_ROOT))
    sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
    from forge_agents.forge_llm import forge_call, forge_orchestrate, LLMTier

    # Le forge "recrute" un expert dédié pour la tâche (comportement CEO).
    plan = forge_orchestrate(task="Créer le site web du client", context=BRIEF)
    expert = plan.get("dynamic_prompt") or "Tu es un développeur web senior."
    system = expert + "\n\n" + PROTOCOL

    def step(history: list[dict]) -> str:
        convo = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in history)
        return forge_call(convo, tier=LLMTier.SONNET, system=system, max_tokens=8000,
                          task_type="build", node="ab_website", nano_mode=False,
                          show_tokens=False)
    return step


def run(arm: str, model: str, max_steps: int) -> Path:
    _load_dotenv()
    os.environ.setdefault("LANGSMITH_TRACING", os.environ.get("LANGSMITH_TRACING", "true"))
    out_dir = HERE / "builds" / arm
    out_dir.mkdir(parents=True, exist_ok=True)

    step = brain_nu(model) if arm == "nu" else brain_forge()
    history = [{"role": "user", "content": f"BRIEF CLIENT:\n\n{BRIEF}\n\n{PROTOCOL}"}]

    all_written: list[str] = []
    for i in range(max_steps):
        reply = step(history)
        history.append({"role": "assistant", "content": reply})
        written = _write_files(reply, out_dir)
        all_written += written
        done = "<<<DONE>>>" in reply
        print(f"[{arm}] step {i+1}: {len(written)} fichier(s) {'| DONE' if done else ''}")
        if done and all_written:
            break
        history.append({"role": "user",
                        "content": (f"Fichiers écrits: {written or 'aucun'}. "
                                    "Continue le site, ou réponds <<<DONE>>> s'il est complet et livrable.")})

    print(f"[{arm}] terminé — {len(all_written)} fichiers dans {out_dir}")
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["nu", "forge"], required=True)
    ap.add_argument("--model", default="claude-sonnet-5",
                    help="Bras nu: modèle Claude. Aligne-le sur le tier SONNET du forge pour une compa propre.")
    ap.add_argument("--max-steps", type=int, default=12)
    args = ap.parse_args()
    run(args.arm, args.model, args.max_steps)
