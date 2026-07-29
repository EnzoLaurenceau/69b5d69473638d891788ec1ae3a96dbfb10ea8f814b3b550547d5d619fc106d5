"""
openhands.py — OpenHands = LE DÉVELOPPEUR de la Forge (remplace le dev humain).
================================================================================

Deux usages :

  1. UN ticket / petite tâche   →  build(task, context)
       Appelé par agent_nodes.dynamic_agent_node pour les tâches de code.

  2. GROS PROJET (méthode DevOps) → run_fleet()
       decomposer.py découpe le projet en tickets sur le kanban
       (05_STATE/kanban/board.json), puis run_fleet() lance UNE FLOTTE
       d'OpenHands : un dev par ticket, en parallèle, chacun :
         - claim son ticket sur le kanban (verrou partagé)
         - respecte depends_on (un ticket attend ses dépendances)
         - respecte le scope fichiers (deux devs ne touchent pas les mêmes fichiers)
         - écrit son résultat dans forge_dispatch/results/<id>.json
         - passe le ticket en done (ou blocked si échec)

Flux complet gros projet :
    from tools.dev import openhands
    tickets = [
        {"name":"API",  "description":"...", "files":["api.py"],  "depends_on":[]},
        {"name":"UI",   "description":"...", "files":["ui.py"],   "depends_on":[]},
        {"name":"Wire", "description":"...", "files":["main.py"], "depends_on":["T001_xxxx","T002_xxxx"]},
    ]
    openhands.dispatch_project("Build SaaS X", tickets, max_parallel=3)

--------------------------------------------------------------------------------
DÉPLOIEMENT — ce qu'il faut faire pour activer OpenHands (status: planned)
--------------------------------------------------------------------------------
OpenHands n'est PAS lancé tant qu'aucun mode n'est configuré. Sans config,
build() lève OpenHandsUnavailable → le hook agent_nodes retombe sur le LLM.

Choisir UN mode via variables d'env (.env de la Forge) :

  # Mode Docker (recommandé) — image officielle all-hands :
  OPENHANDS_MODE=docker
  LLM_API_KEY=...                 # clé du LLM derrière OpenHands (router Forge / RTK)
  LLM_BASE_URL=...                # ex: proxy RTK local
  OPENHANDS_IMAGE=docker.all-hands.dev/all-hands-ai/openhands:latest

  # OU mode CLI (binaire openhands installé localement) :
  OPENHANDS_MODE=cli

  # OU template 100% custom (override total) :
  OPENHANDS_CMD=ma-commande -t {task_file} -d {workspace}

⚠️ La commande headless exacte dépend de TA version d'OpenHands. Les templates
ci-dessous sont des défauts raisonnables — vérifie-les contre ta version
(`openhands --help` / doc image Docker) et ajuste OPENHANDS_CMD si besoin.
Placeholders disponibles dans le template : {task_file} {workspace} {image}.

Étapes :
  1. docker pull <image>  (ou pip install openhands-ai)
  2. Remplir .env (mode + clés LLM, idéalement branché sur le proxy RTK gratuit).
  3. Tester : python 00_CORE/tools/openhands.py build "crée hello.py qui print hi"
  4. Gros projet : decomposer.py pour les tickets, puis openhands.py fleet
  5. npx gitnexus analyze  (réindexer — règle CLAUDE.md #5)
"""
from __future__ import annotations

import os
import sys
import json
import shlex
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))

# ponytail: fallback .env (comme forge_mimo._env) — le process forge ne charge pas
# dotenv, donc OPENHANDS_*/LLM_* de .env seraient invisibles sans ceci. setdefault
# only : une vraie variable d'environnement garde priorité.
for _envfile in (FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"):
    if _envfile.exists():
        for _line in _envfile.read_text(encoding="utf-8", errors="ignore").splitlines():
            _line = _line.strip()
            if _line.startswith(("OPENHANDS", "LLM_")) and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DISPATCH_DIR = FORGE_ROOT / "00_CORE" / "forge_dispatch"
RESULTS_DIR = DISPATCH_DIR / "results"
MVP_OUTPUT = FORGE_ROOT / "mvp_output"

sys.path.insert(0, str(DISPATCH_DIR))
import kanban  # noqa: E402  (claim/complete/block/check_conflicts/load/status)

# Verrou board partagé : la flotte tourne IN-PROCESS (threads), donc claim/complete
# (read-modify-write du board JSON) DOIT être atomique entre devs.
# ponytail: protège seulement la flotte in-process. Les sessions hermes hors-process
# restent racy (design d'origine) — non concerné ici.
_BOARD_LOCK = threading.Lock()


class OpenHandsUnavailable(RuntimeError):
    """OpenHands non déployé ou échec d'exécution."""


# ── Configuration / templates ────────────────────────────────────────────────
def _cmd_template() -> str | None:
    """Template de commande OpenHands selon l'env, ou None si non déployé."""
    explicit = os.environ.get("OPENHANDS_CMD")
    if explicit:
        return explicit
    mode = os.environ.get("OPENHANDS_MODE", "").lower()
    if mode == "docker":
        return (
            'docker run --rm -e LLM_API_KEY -e LLM_BASE_URL '
            '-v "{workspace}:/workspace" {image} '
            'python -m openhands.core.main -f {task_file}'
        )
    if mode == "cli":
        return 'openhands -f {task_file} -d "{workspace}"'
    return None


def is_available() -> bool:
    """True si un mode OpenHands est configuré (pas une garantie d'exécution)."""
    return _cmd_template() is not None


# ── Runner bas niveau ────────────────────────────────────────────────────────
def _engine_path(p: Path) -> str:
    """Chemin vu par le MOTEUR Docker Desktop/WSL2 (pour SANDBOX_VOLUMES : le
    runtime container est créé par le daemon, qui ne connaît pas 'C:\\...')."""
    s = str(p).replace("\\", "/")
    if len(s) > 1 and s[1] == ":":  # lecteur Windows → /run/desktop/mnt/host/<l>/
        s = "/run/desktop/mnt/host/" + s[0].lower() + s[2:]
    return s


def _subprocess_runner(tmpl: str, task: str, workspace: Path, timeout: int) -> str:
    """Écrit la tâche dans un fichier puis lance OpenHands en subprocess."""
    task_file = workspace / ".openhands_task.txt"
    task_file.write_text(task, encoding="utf-8")
    image = os.environ.get("OPENHANDS_IMAGE", "docker.all-hands.dev/all-hands-ai/openhands:latest")
    cmd = tmpl.format(task_file=str(task_file), workspace=str(workspace),
                      workspace_engine=_engine_path(workspace), image=image)
    # ponytail: shell=True car le template est fourni par l'opérateur (env de confiance),
    # pas par l'utilisateur final. Ceiling: ne jamais construire OPENHANDS_CMD depuis un input externe.
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        tail = (proc.stderr or out)[-800:]
        raise OpenHandsUnavailable(f"OpenHands exit {proc.returncode}: {tail}")
    return out


# ── API : un ticket ──────────────────────────────────────────────────────────
def build(task: str, context: str = "", workspace: str | Path | None = None,
          timeout: int = 1800, _runner=None) -> str:
    """Lance UN dev OpenHands sur UNE tâche. Retourne son output (logs/diff).

    Lève OpenHandsUnavailable si non déployé (→ le caller retombe sur le LLM).
    _runner: injectable pour les tests (signature: (tmpl, task, workspace, timeout) -> str).
    """
    tmpl = _cmd_template()
    if tmpl is None and _runner is None:
        raise OpenHandsUnavailable(
            "OpenHands non déployé. Configure OPENHANDS_MODE=docker|cli ou OPENHANDS_CMD "
            "(voir docstring tools/openhands.py)."
        )
    runner = _runner or _subprocess_runner
    ws = Path(workspace or os.environ.get("OPENHANDS_WORKSPACE") or (MVP_OUTPUT / "_scratch"))
    ws.mkdir(parents=True, exist_ok=True)
    # Inject default UI-UX Pro Max & Superpowers skills guidelines (Zero-config presets)
    superpowers_instructions = (
        "\n\n# --- SUPERPOWERS METHODOLOGY (fallow-rs/superpowers) ---\n"
        "- Follow Test-Driven Development (TDD) incrementally.\n"
        "- Create a detailed implementation plan checklist at the start of your modifications.\n"
        "- Run compilation and test checks after every minor edit. Never proceed with unverified changes.\n"
        "- Never leave empty templates or placeholder blocks. Ship complete production logic."
    )
    
    ui_ux_pro_max_instructions = (
        "\n\n# --- UI/UX PRO MAX SYSTEM (nextlevelbuilder/ui-ux-pro-max-skill) ---\n"
        "- Avoid browser default styles. Use premium layouts, subtle borders, and smooth transitions.\n"
        "- Establish responsive columns, custom border-radiuses (0.5rem - 0.75rem), and elegant spacing.\n"
        "- Define cohesive typography rules using Fontshare styles (e.g. Satoshi, Clash Display).\n"
        "- Leverage harmonious color palettes (generate 50-950 scales using UI Colors algorithm)."
    )
    
    full_task = task if not context else f"{task}\n\n# Contexte\n{context}"
    full_task += superpowers_instructions + ui_ux_pro_max_instructions
    
    return runner(tmpl or "", full_task, ws, timeout)


# ── API : un ticket du kanban ────────────────────────────────────────────────
def _project_slug(board: dict) -> str:
    raw = (board.get("parent_task") or "_scratch").lower()
    keep = [c if c.isalnum() else "_" for c in raw]
    return "".join(keep).strip("_")[:40] or "_scratch"


def run_ticket(task_id: str, session_id: str = "openhands", _runner=None) -> dict:
    """Un dev OpenHands prend UN ticket du kanban et l'exécute de bout en bout."""
    board = kanban.load()
    task = next((t for t in board["tasks"] if t["id"] == task_id), None)
    if task is None:
        return {"task_id": task_id, "status": "missing"}

    with _BOARD_LOCK:
        conflicts = kanban.check_conflicts(task_id)
        if conflicts:
            return {"task_id": task_id, "status": "skipped", "conflicts": conflicts}
        if not kanban.claim(task_id, session_id):
            return {"task_id": task_id, "status": "claim_failed"}

    desc = task["description"]
    if task.get("files"):
        desc += "\n\n# Scope — modifie UNIQUEMENT ces fichiers :\n" + "\n".join(
            f"  - {f}" for f in task["files"]
        )
    deps = task.get("depends_on", [])
    if deps:
        desc += "\n\n# Résultats des dépendances (à lire d'abord) :\n" + "\n".join(
            f"  - {RESULTS_DIR / (d + '.json')}" for d in deps
        )

    ws = MVP_OUTPUT / _project_slug(board)
    try:
        output = build(desc, workspace=ws, _runner=_runner)
    except Exception as e:  # build raté → ticket bloqué, on ne casse pas la flotte
        with _BOARD_LOCK:
            kanban.block(task_id, str(e)[:300])
        return {"task_id": task_id, "status": "blocked", "error": str(e)[:300]}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"{task_id}.json"
    result_file.write_text(
        json.dumps({"task_id": task_id, "name": task["name"], "output": output},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with _BOARD_LOCK:
        kanban.complete(task_id, str(result_file))
    return {"task_id": task_id, "status": "done", "result_file": str(result_file)}


# ── API : la flotte (méthode DevOps) ─────────────────────────────────────────
def _no_conflict_batch(ready: list[dict], limit: int) -> list[dict]:
    """Choisit jusqu'à `limit` tickets prêts dont les scopes fichiers ne se chevauchent pas."""
    chosen: list[dict] = []
    used: set[str] = set()
    for t in ready:
        files = set(t.get("files", []))
        if files and (files & used):
            continue  # collision de scope → ce ticket attend le prochain tour
        chosen.append(t)
        used |= files
        if len(chosen) >= limit:
            break
    return chosen


def run_fleet(max_parallel: int | None = None, _runner=None) -> dict:
    """Lance la flotte d'OpenHands sur le kanban courant jusqu'à épuisement.

    Ordonnanceur DevOps : à chaque tour, sélectionne les tickets PRÊTS
    (pending + depends_on tous done), sans collision de scope, et lance
    jusqu'à max_parallel devs en parallèle. Répète jusqu'à board vide.
    """
    max_parallel = max_parallel or int(os.environ.get("OPENHANDS_MAX_PARALLEL", "3"))
    results: dict[str, dict] = {}

    while True:
        board = kanban.load()
        done = {t["id"] for t in board["tasks"] if t["status"] == "done"}
        pending = [t for t in board["tasks"] if t["status"] == "pending"]
        ready = [t for t in pending if set(t.get("depends_on", [])) <= done]

        if not ready:
            if pending:  # restent des tickets mais leurs deps ne seront jamais satisfaites
                for t in pending:
                    results.setdefault(t["id"], {"task_id": t["id"], "status": "stuck_deps"})
            break

        batch = _no_conflict_batch(ready, max_parallel)
        with ThreadPoolExecutor(max_workers=max(1, len(batch))) as ex:
            futs = {ex.submit(run_ticket, t["id"], f"oh-{t['id']}", _runner): t["id"] for t in batch}
            for fu in as_completed(futs):
                r = fu.result()
                results[r["task_id"]] = r

        progressed = any(r.get("status") in ("done", "blocked") for r in results.values())
        if not progressed:  # garde-fou anti-boucle (tout skipped/claim_failed)
            break

    return {"results": results, "summary": kanban.status()}


def dispatch_project(task: str, subtasks: list[dict], max_parallel: int | None = None,
                     _runner=None) -> dict:
    """Décompose un gros projet en tickets puis lâche la flotte dessus (1 appel)."""
    import decomposer  # forge_dispatch déjà sur sys.path
    decomposer.decompose_task(task, "", subtasks)
    return run_fleet(max_parallel=max_parallel, _runner=_runner)


# ── Self-check (ponytail: une vérif runnable sur la logique non triviale) ─────
def demo():
    """Teste l'ordonnanceur de flotte avec un runner factice + board isolé."""
    import tempfile

    kanban.KANBAN_FILE = Path(tempfile.mkdtemp()) / "board.json"  # isole, ne touche pas le vrai board
    kanban.save({"tasks": [
        {"id": "T1", "name": "api", "description": "build api", "files": ["api.py"],
         "depends_on": [], "status": "pending", "assigned_session": None},
        {"id": "T2", "name": "ui", "description": "build ui", "files": ["ui.py"],
         "depends_on": [], "status": "pending", "assigned_session": None},
        {"id": "T3", "name": "wire", "description": "wire", "files": ["main.py"],
         "depends_on": ["T1", "T2"], "status": "pending", "assigned_session": None},
    ], "version": 1, "parent_task": "demo project"})

    order: list[str] = []
    lock = threading.Lock()

    def fake(_tmpl, task, _ws, _timeout):
        with lock:
            order.append(task.split("\n")[0])
        return "ok"

    res = run_fleet(max_parallel=2, _runner=fake)
    final = kanban.load()
    assert all(t["status"] == "done" for t in final["tasks"]), final
    # T3 dépend de T1+T2 → "wire" doit être exécuté en dernier
    assert order[-1].startswith("wire"), order
    print("openhands.demo OK |", {t["id"]: t["status"] for t in final["tasks"]})
    print("ordre exécution   |", order)


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "status"

    if cmd == "build" and len(args) >= 2:
        try:
            print(build(args[1]))
        except OpenHandsUnavailable as e:
            print(f"[OpenHands indispo] {e}")
    elif cmd == "ticket" and len(args) >= 2:
        print(json.dumps(run_ticket(args[1]), indent=2, ensure_ascii=False))
    elif cmd == "fleet":
        n = int(args[args.index("--parallel") + 1]) if "--parallel" in args else None
        out = run_fleet(max_parallel=n)
        print(out["summary"])
    elif cmd == "available":
        print(f"OpenHands configuré: {is_available()} (mode={os.environ.get('OPENHANDS_MODE','-')})")
    elif cmd == "demo":
        demo()
    else:
        print(kanban.status())
        print("\nUsage: openhands.py [build \"<task>\" | ticket <id> | fleet [--parallel N] | available | demo]")
