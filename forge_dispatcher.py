"""
forge_dispatcher.py — Multi-Session Task Dispatcher
=====================================================
Daemon système qui découpe les grosses tâches en sous-tâches
et les distribue sur des sessions Hermes indépendantes.

Architecture:
  1. Recoit une tâche (via fichier, stdin, ou CLI)
  2. Estime les tokens nécessaires
  3. Si > 65K: décompose en sous-tâches atomiques
  4. Lance chaque sous-tâche dans une session Hermes fraîche
     via `hermes chat -q "<subtask>" --profile forge -Q`
  5. Collecte les résultats
  6. Agrège et livre le résultat final

Usage:
  # Tâche directe
  python forge_dispatcher.py --task "Analyse le codebase et refactor X"

  # Tâche depuis fichier
  python forge_dispatcher.py --task-file brief.md

  # Tâche depuis le transfer brief d'une session
  python forge_dispatcher.py --from-brief session-transfer/briefs/xxx.md

  # Dry run (montre le split sans exécuter)
  python forge_dispatcher.py --task "..." --dry-run

  # Mode daemon (écoute un répertoire de tâches)
  python forge_dispatcher.py --daemon
"""

import json
import os
import sys
import time
import datetime
import subprocess
import hashlib
import re
from pathlib import Path

FORGE_ROOT = Path(__file__).parent
STATE_DIR = FORGE_ROOT / "05_STATE"
DISPATCH_DIR = STATE_DIR / "dispatcher"
DISPATCH_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_DIR = DISPATCH_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

QUEUE_DIR = DISPATCH_DIR / "queue"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

LOGS_DIR = FORGE_ROOT / "08_LOGS" / "dispatcher"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

CEILING = 65_000
SUBTASK_CEILING = 50_000  # marge de sécurité par sous-tâche
CHUNK_MAX_TOKENS = 45_000  # tokens max par chunk de sous-tâche
CHARS_PER_TOKEN = 4  # estimation conservative
HERMES_CMD = "hermes"
PROFILE = "forge"


def estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens dans un texte."""
    return len(text) // CHARS_PER_TOKEN


def decompose_task(task: str, context: str = "") -> list[dict]:
    """
    Décompose une tâche en sous-tâches atomiques.
    Utilise la logique heuristique + NMP.
    """
    lines = task.strip().split("\n")
    total_chars = len(task) + len(context)
    est_tokens = estimate_tokens(task + context)

    if est_tokens <= SUBTASK_CEILING:
        # Tient dans une seule session
        return [{
            "id": "task_0",
            "description": task,
            "context": context,
            "estimated_tokens": est_tokens,
            "priority": 1,
        }]

    # Découpage intelligent
    subtasks = []

    # Stratégie 1: Découper par sections/logical blocks
    sections = _split_by_sections(task)

    if len(sections) > 1:
        for i, section in enumerate(sections):
            section_tokens = estimate_tokens(section)
            if section_tokens > CHUNK_MAX_TOKENS:
                # Sous-section trop grosse → découper davantage
                chunks = _force_chunk(section, CHUNK_MAX_TOKENS)
                for j, chunk in enumerate(chunks):
                    subtasks.append({
                        "id": f"task_{i}_{j}",
                        "description": chunk,
                        "context": context if i == 0 else "",  # contexte seulement pour le premier
                        "estimated_tokens": estimate_tokens(chunk),
                        "priority": i + 1,
                    })
            else:
                subtasks.append({
                    "id": f"task_{i}",
                    "description": section,
                    "context": context if i == 0 else "",
                    "estimated_tokens": section_tokens,
                    "priority": i + 1,
                })
    else:
        # Pas de sections logiques → force chunk
        chunks = _force_chunk(task, CHUNK_MAX_TOKENS)
        for i, chunk in enumerate(chunks):
            subtasks.append({
                "id": f"task_{i}",
                "description": chunk,
                "context": context if i == 0 else "",
                "estimated_tokens": estimate_tokens(chunk),
                "priority": i + 1,
            })

    return subtasks


def _split_by_sections(text: str) -> list[str]:
    """Découpe par headers markdown, listes, ou blocs logiques."""
    # Essayer de split par headers markdown
    sections = re.split(r'\n(?=#{1,3}\s)', text)
    if len(sections) > 1:
        return [s.strip() for s in sections if s.strip()]

    # Essayer par double newline (paragraphes)
    sections = re.split(r'\n\n+', text)
    if len(sections) > 2:
        # Regrouper les petits paragraphes
        merged = []
        current = ""
        for s in sections:
            if estimate_tokens(current + s) > CHUNK_MAX_TOKENS:
                if current:
                    merged.append(current.strip())
                current = s
            else:
                current += "\n\n" + s
        if current:
            merged.append(current.strip())
        return merged

    return [text]


def _force_chunk(text: str, max_tokens: int) -> list[str]:
    """Force le découpage en chunks de taille max."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    chunks = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line

    if current:
        chunks.append(current.strip())

    return chunks if chunks else [text]


def execute_subtask(subtask: dict, session_tag: str = "") -> dict:
    """Exécute une sous-tâche dans une session Hermes fraîche."""
    task_id = subtask["id"]
    description = subtask["description"]
    context = subtask.get("context", "")

    # Construire le prompt complet
    if context:
        prompt = f"CONTEXTE:\n{context}\n\nTÂCHE:\n{description}"
    else:
        prompt = description

    # Tag de session pour traçabilité
    tag = session_tag or f"forge-dispatch-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    session_name = f"{tag}-{task_id}"

    print(f"  🚀 [{task_id}] Launching session: {session_name}")
    print(f"      Est. tokens: {subtask['estimated_tokens']:,}")

    # Construire la commande hermes
    cmd = [
        HERMES_CMD, "chat",
        "-q", prompt,
        "--profile", PROFILE,
        "-Q",  # quiet mode
        "--source", "forge_dispatcher",
        "--max-turns", "50",
    ]

    result = {
        "task_id": task_id,
        "session_name": session_name,
        "status": "pending",
        "output": "",
        "error": "",
        "started_at": datetime.datetime.now().isoformat(),
        "tokens_estimated": subtask["estimated_tokens"],
    }

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max par sous-tâche
            cwd=str(FORGE_ROOT),
        )

        result["output"] = proc.stdout
        result["error"] = proc.stderr if proc.returncode != 0 else ""
        result["status"] = "done" if proc.returncode == 0 else "error"
        result["exit_code"] = proc.returncode
        result["finished_at"] = datetime.datetime.now().isoformat()

        # Sauvegarder le résultat
        result_file = RESULTS_DIR / f"{session_name}.json"
        result_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        status_icon = "✅" if result["status"] == "done" else "❌"
        print(f"  {status_icon} [{task_id}] {result['status']} — {len(result['output'])} chars output")

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = "Subtask exceeded 600s timeout"
        result["finished_at"] = datetime.datetime.now().isoformat()
        print(f"  ⏰ [{task_id}] TIMEOUT")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["finished_at"] = datetime.datetime.now().isoformat()
        print(f"  ❌ [{task_id}] ERROR: {e}")

    return result


def dispatch(task: str, context: str = "", dry_run: bool = False) -> dict:
    """
    Pipeline complet: décompose → exécute → agrège.
    """
    dispatch_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    est_total = estimate_tokens(task + context)

    print(f"{'='*60}")
    print(f"FORGE DISPATCHER — {dispatch_id}")
    print(f"{'='*60}")
    print(f"Task size: {len(task):,} chars (~{est_total:,} tokens)")
    print(f"Ceiling: {CEILING:,} tokens")
    print()

    # Décomposer
    subtasks = decompose_task(task, context)
    print(f"📋 Decomposed into {len(subtasks)} subtask(s):")
    for st in subtasks:
        print(f"   [{st['id']}] ~{st['estimated_tokens']:,} tokens — {st['description'][:80]}...")
    print()

    if dry_run:
        print("🔍 DRY RUN — not executing")
        return {
            "dispatch_id": dispatch_id,
            "subtasks": subtasks,
            "dry_run": True,
        }

    # Exécuter chaque sous-tâche
    results = []
    for st in subtasks:
        result = execute_subtask(st, session_tag=f"forge-{dispatch_id}")
        results.append(result)

    # Agréger
    successful = [r for r in results if r["status"] == "done"]
    failed = [r for r in results if r["status"] != "done"]

    # Compiler le résultat final
    aggregated_output = "\n\n---\n\n".join(
        f"### Subtask {r['task_id']}\n{r['output']}"
        for r in successful
    )

    dispatch_result = {
        "dispatch_id": dispatch_id,
        "total_subtasks": len(subtasks),
        "successful": len(successful),
        "failed": len(failed),
        "results": results,
        "aggregated_output": aggregated_output,
        "completed_at": datetime.datetime.now().isoformat(),
    }

    # Sauvegarder le rapport
    report_file = LOGS_DIR / f"dispatch_{dispatch_id}.json"
    report_file.write_text(json.dumps(dispatch_result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"DISPATCH COMPLETE — {dispatch_id}")
    print(f"{'='*60}")
    print(f"✅ Successful: {len(successful)}/{len(subtasks)}")
    if failed:
        print(f"❌ Failed: {len(failed)}")
        for r in failed:
            print(f"   [{r['task_id']}] {r['status']}: {r['error'][:100]}")
    print(f"📄 Report: {report_file}")

    return dispatch_result


def dispatch_from_brief(brief_path: str) -> dict:
    """Dispatch depuis un transfer brief."""
    brief = Path(brief_path).read_text(encoding="utf-8")
    return dispatch(task=brief, context="Resume this transfer brief across sessions.")


def dispatch_from_file(task_file: str) -> dict:
    """Dispatch depuis un fichier de tâche."""
    content = Path(task_file).read_text(encoding="utf-8")
    return dispatch(task=content)


def daemon_mode():
    """
    Mode daemon: écoute le répertoire queue/ pour de nouvelles tâches.
    Format: fichier .json avec {"task": "...", "context": "..."}
    """
    print(f"🚀 Forge Dispatcher Daemon started")
    print(f"   Queue: {QUEUE_DIR}")
    print(f"   Results: {RESULTS_DIR}")
    print(f"   Ceiling: {CEILING:,} tokens")
    print()

    processed = set()

    while True:
        for task_file in sorted(QUEUE_DIR.glob("*.json")):
            if task_file.name in processed:
                continue

            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                print(f"\n📥 New task: {task_file.name}")

                result = dispatch(
                    task=data.get("task", ""),
                    context=data.get("context", ""),
                    dry_run=data.get("dry_run", False),
                )

                # Marquer comme traité
                task_file.rename(task_file.with_suffix(".done"))
                processed.add(task_file.name)

                # Sauvegarder le résultat avec le même nom
                result_file = QUEUE_DIR / f"{task_file.stem}.result.json"
                result_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

            except Exception as e:
                print(f"❌ Error processing {task_file.name}: {e}")
                processed.add(task_file.name)

        time.sleep(5)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Forge Multi-Session Dispatcher")
    parser.add_argument("--task", help="Task description")
    parser.add_argument("--task-file", help="Task from file")
    parser.add_argument("--from-brief", help="Dispatch from transfer brief")
    parser.add_argument("--context", default="", help="Additional context")
    parser.add_argument("--dry-run", action="store_true", help="Show decomposition only")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode (watch queue/)")
    args = parser.parse_args()

    if args.daemon:
        daemon_mode()
    elif args.from_brief:
        dispatch_from_brief(args.from_brief)
    elif args.task_file:
        dispatch_from_file(args.task_file)
    elif args.task:
        dispatch(args.task, args.context, args.dry_run)
    else:
        parser.print_help()
