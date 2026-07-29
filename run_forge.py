#!/usr/bin/env python3
"""
run_forge.py — Super Agent Forge CLI entry point
================================================
Usage:
  python run_forge.py --task niche_scan
  python run_forge.py --task "build landing page for PromptFlow" --desc "dark theme, purple/blue" --cycles 5
  python run_forge.py --status          # affiche le dernier checkpoint
  python run_forge.py --history         # affiche l'historique du cycle courant
  python run_forge.py --resume          # reprend depuis le dernier checkpoint
  python run_forge.py --task "..." --quiet   # affiche uniquement le résultat final en JSON

Options:
  --task TEXT        Description courte de la tâche (obligatoire sauf --status/--history/--resume)
  --desc TEXT        Description longue de la tâche [défaut: identique à --task]
  --cycles INT       Nombre max de cycles LangGraph [défaut: 10]
  --session TEXT     ID de session (pour persistence SQLite) [défaut: auto-généré]
  --no-sqlite        Désactiver la persistence SQLite (mode stateless)
  --status           Afficher le dernier checkpoint et quitter
  --history          Afficher l'historique complet du runner et quitter
  --resume           Reprendre depuis le dernier checkpoint (même session_id)
  --quiet, -q        Mode silencieux : supprime toutes les bannières/tables
                     (estimate, post-mortem, status) et n'affiche que le
                     résultat final sous forme de JSON compact sur stdout.
                     Les logs complets restent écrits dans 08_LOGS/.
                     → économie massive de tokens output (cf. CLAUDE.md).
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent
sys.path.insert(0, str(FORGE_ROOT))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

# Console Windows cp1252 → UTF-8 (box-drawing/emoji des bannières/tables)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

try:
    from forge_agents.ail_protocol import decode_block, decode_line
except ImportError:
    # Fallback no-op si le module n'est pas encore en place
    def decode_block(text, bullet="- "):
        return "\n".join(f"{bullet}{l}" for l in (text or "").splitlines() if l.strip())

    def decode_line(text):
        return text


def cmd_status(quiet: bool = False):
    checkpoint_path = FORGE_ROOT / "05_STATE" / "checkpoint.json"
    if not checkpoint_path.exists():
        if quiet:
            print(json.dumps({"error": "no_checkpoint"}))
        else:
            print("❌ Aucun checkpoint trouvé. Lance d'abord une tâche.")
        sys.exit(1)
    with open(checkpoint_path) as f:
        cp = json.load(f)

    findings = cp.get("findings", [])
    confirmed = [f for f in findings if f.get("status") == "confirmed"]
    quality = cp.get("quality_history", [])

    if quiet:
        print(json.dumps({
            "session_id": cp.get("session_id", "N/A"),
            "level": cp.get("level", "L1"),
            "cycle": cp.get("cycle", 0),
            "current_agent": cp.get("current_agent", "N/A"),
            "task": cp.get("task", "N/A"),
            "saved_at": cp.get("saved_at", "N/A"),
            "findings_confirmed": len(confirmed),
            "findings_total": len(findings),
            "quality_last": quality[-1] if quality else None,
            "quality_avg": (sum(quality) / len(quality)) if quality else None,
        }, ensure_ascii=False))
        return

    print("\n╔══════════════════════════════════════╗")
    print("║     SUPER AGENT FORGE — STATUS       ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Session   : {cp.get('session_id', 'N/A')}")
    print(f"  Niveau    : {cp.get('level', 'L1')}")
    print(f"  Cycle     : {cp.get('cycle', 0)}")
    print(f"  Agent actif : {cp.get('current_agent', 'N/A')}")
    print(f"  Tâche     : {cp.get('task', 'N/A')}")
    print(f"  Sauvegardé : {cp.get('saved_at', 'N/A')}")
    print(f"  Findings  : {len(confirmed)} confirmés / {len(findings)} total")
    if quality:
        print(f"  Qualité   : {quality[-1]:.2f} (last) | {sum(quality)/len(quality):.2f} (avg)")
    print()


def cmd_history(runner, quiet: bool = False):
    history = runner.get_history()
    if not history:
        if quiet:
            print(json.dumps({"history": []}))
        else:
            print("Aucun historique disponible.")
        return

    if quiet:
        out = [{
            "saved_at": s.get("saved_at", "?"),
            "cycle": s.get("cycle", 0),
            "agent": s.get("current_agent", "?"),
            "quality_last": (s.get("quality_history") or [None])[-1],
        } for s in history]
        print(json.dumps({"history": out}, ensure_ascii=False))
        return

    print(f"\n{'='*60}")
    print(f"HISTORIQUE — {len(history)} états")
    print(f"{'='*60}")
    for i, state in enumerate(history):
        ts = state.get("saved_at", "?")
        cycle = state.get("cycle", 0)
        agent = state.get("current_agent", "?")
        quality = state.get("quality_history", [])
        q_str = f" | Q={quality[-1]:.2f}" if quality else ""
        print(f"  [{i:02d}] {ts}  cycle={cycle}  agent={agent}{q_str}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Super Agent Forge — LangGraph CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--task", type=str, help="Description courte de la tâche")
    parser.add_argument("--desc", type=str, help="Description longue [défaut: identique à --task]")
    parser.add_argument("--cycles", type=int, default=10, help="Nombre max de cycles [défaut: 10]")
    parser.add_argument("--session", type=str, help="ID de session [défaut: auto-généré]")
    parser.add_argument("--no-sqlite", action="store_true", help="Désactiver SQLite")
    parser.add_argument("--status", action="store_true", help="Afficher le dernier checkpoint")
    parser.add_argument("--db-status", action="store_true",
                         help="Santé du store unifié PG+Redis (+ WAL en attente)")
    parser.add_argument("--bootstrap", action="store_true",
                         help="Activer la stack (Docker daemon + PG+Redis + deps) automatiquement")
    parser.add_argument("--migrate", action="store_true",
                         help="Migrer les stores legacy → PG+Redis (optiforge)")
    parser.add_argument("--purge-legacy", action="store_true",
                         help="Avec --migrate : supprimer les fichiers legacy au lieu d'archiver")
    parser.add_argument("--history", action="store_true", help="Afficher l'historique")
    parser.add_argument("--resume", action="store_true", help="Reprendre depuis le dernier checkpoint")
    parser.add_argument("--quiet", "-q", action="store_true",
                         help="Mode silencieux : uniquement le résultat final en JSON")
    parser.add_argument("--warmup", action="store_true",
                         help="Warm-up complet des 5 couches mémoire (L0→L4)")
    parser.add_argument("--warmup-dry", action="store_true",
                         help="Warm-up en mode simulation (dry-run)")
    parser.add_argument("--evolve", action="store_true",
                         help="evomap LOCAL-ONLY: solidify les apprentissages (validateur OFF, pas de sync/publish)")
    parser.add_argument("--dashboard", action="store_true",
                         help="Démarrer le dashboard Forge (http://localhost:7420)")
    parser.add_argument("--dashboard-port", type=int, default=7420,
                         help="Port du dashboard [défaut: 7420]")
    args = parser.parse_args()
    quiet = args.quiet

    # ─── DASHBOARD ──────────────────────────────────────────────────
    # Le dashboard est un projet standalone, séparé du Forge
    # — cf. 09_TASKS/dashboard_mvp_plan.md section 0.
    # Emplacement : $DASHBOARD_ROOT, sinon un frère du dossier MODELS/ (pas de
    # chemin absolu en dur : ni portable, ni sans fuite du nom d'utilisateur).
    if getattr(args, "dashboard", False):
        import os as _os, subprocess as _sp
        port = getattr(args, "dashboard_port", 7420)
        backend = Path(_os.environ.get(
            "DASHBOARD_ROOT", Path(__file__).resolve().parents[2] / "DASHBOARD")) / "backend"
        if not backend.exists():
            print(f"  DASHBOARD introuvable: {backend}")
            return
        env = {**_os.environ, "DASHBOARD_PORT": str(port)}
        print(f"\n  Forge Dashboard (standalone) → http://localhost:{port}\n")
        _sp.run([sys.executable, "-m", "uvicorn", "dashboard_server:app",
                 "--host", "0.0.0.0", "--port", str(port)],
                cwd=str(backend), env=env)
        return

    # ─── EVOMAP evolve (local-only, opt-in) ─────────────────────────
    if getattr(args, "evolve", False):
        import os as _os
        _os.environ["FORGE_EVOLVE"] = "1"          # active le hook in-graph (post_mortem)
        if not (args.task or args.resume):          # mode standalone : evolve puis sortie
            try:
                sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
                from forge_agents.evomap_evolve import evolve as _evolve
                res = _evolve(subcommand="solidify", intent="optimize")
                print(json.dumps(res, ensure_ascii=False) if quiet
                      else f"\n🧬 EVOMAP evolve (local-only) → {res}\n")
            except Exception as e:
                print(json.dumps({"error": str(e)}) if quiet else f"❌ evomap evolve: {e}")
            return

    # ─── STATUS only ────────────────────────────────────────────────
    if args.status:
        cmd_status(quiet=quiet)
        return

    # ─── DB STATUS (store unifié PG+Redis) ──────────────────────────
    if args.db_status:
        try:
            from forge_agents.forge_db import get_db
            h = get_db().health()
            if quiet:
                print(json.dumps(h, ensure_ascii=False))
            else:
                print(f"\n  Store unifié (optiforge)")
                print(f"  redis      : {h['redis']}")
                print(f"  postgres   : {h['postgres']}")
                print(f"  mode       : {h['fallback']}")
                print(f"  WAL pending: {h['wal_pending']}\n")
        except Exception as e:
            print(json.dumps({"error": str(e)}) if quiet else f"❌ forge_db: {e}")
        return

    # ─── WARMUP complet (5 couches mémoire L0→L4) ────────────────────
    if getattr(args, "warmup", False) or getattr(args, "warmup_dry", False):
        try:
            sys.path.insert(0, str(FORGE_ROOT / "scripts"))
            from forge_memory_warmup import run_warmup
            dry = getattr(args, "warmup_dry", False)
            summary = run_warmup(dry_run=dry)
            if quiet:
                print(json.dumps(summary, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"error": str(e)}) if quiet else f"❌ warmup: {e}")
        return

    # ─── BOOTSTRAP (Docker + PG+Redis + deps, autonome) ─────────────
    if args.bootstrap:
        try:
            sys.path.insert(0, str(FORGE_ROOT / "scripts"))
            from forge_bootstrap import bootstrap
            bootstrap(install_deps=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}) if quiet else f"❌ bootstrap: {e}")
        return

    # ─── MIGRATION legacy → PG+Redis ────────────────────────────────
    if args.migrate:
        try:
            sys.path.insert(0, str(FORGE_ROOT / "scripts"))
            from migrate_to_pg import run_migration
            run_migration(dry=False, purge=args.purge_legacy)
        except Exception as e:
            print(json.dumps({"error": str(e)}) if quiet else f"❌ migration: {e}")
        return

    # ─── Import ForgeRunner (lazy, après sys.path setup) ────────────
    try:
        sys.path.insert(0, str(FORGE_ROOT / '00_CORE'))
        from forge_agents.forge_graph import ForgeRunner
    except ImportError as e:
        if quiet:
            print(json.dumps({"error": f"import_error: {e}"}))
        else:
            print(f"❌ Import error: {e}")
            print("   → Installe les dépendances: pip install -r requirements.txt")
        sys.exit(1)

    # ─── HISTORY only ───────────────────────────────────────────────
    if args.history:
        # besoin d'un runner pour get_history — on utilise le dernier session_id
        checkpoint_path = FORGE_ROOT / "05_STATE" / "checkpoint.json"
        session_id = None
        if checkpoint_path.exists():
            with open(checkpoint_path) as f:
                cp = json.load(f)
            session_id = cp.get("session_id")
        runner = ForgeRunner(
            session_id=session_id or "history_read",
            use_sqlite=not args.no_sqlite
        )
        cmd_history(runner, quiet=quiet)
        return

    # ─── RESUME ─────────────────────────────────────────────────────
    if args.resume:
        checkpoint_path = FORGE_ROOT / "05_STATE" / "checkpoint.json"
        if not checkpoint_path.exists():
            if quiet:
                print(json.dumps({"error": "no_checkpoint"}))
            else:
                print("❌ Aucun checkpoint à reprendre.")
            sys.exit(1)
        with open(checkpoint_path) as f:
            cp = json.load(f)
        session_id = cp.get("session_id", args.session)
        task = cp.get("task", "continue")
        task_desc = cp.get("task_desc", task)

        if not quiet:
            print(f"\n🔄 RESUME session={session_id} | task={task}")

        runner = ForgeRunner(session_id=session_id, use_sqlite=not args.no_sqlite)

        # TOKEN ESTIMATE
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))
        try:
            from forge_agents.token_tracker import get_tracker
            tracker = get_tracker()
            tracker.reset_session(session_id, task)
            tracker.estimate_budget(task)
            if not quiet:
                print(tracker.render_estimate_table())
                print()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        result = runner.run_task(task=task, task_desc=task_desc, max_cycles=args.cycles,
                                   quiet=quiet)

        # TOKEN ACTUAL
        try:
            from forge_agents.token_tracker import get_tracker
            tracker = get_tracker()
            if not quiet:
                print(tracker.render_actual_table())
                recs = tracker.generate_recommendations()
                for r in recs: print(r)
                print(f"\n📈 EFFICIENCY SCORE: {tracker.efficiency_score()}/100")
            tracker.generate_final_report()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        _print_result(result, quiet=quiet)
        return

    # ─── NORMAL RUN ─────────────────────────────────────────────────
    if not args.task:
        parser.print_help()
        print("\n❌ --task est obligatoire (ou utilise --status / --history / --resume)")
        sys.exit(1)

    task = args.task
    task_desc = args.desc or task
    session_id = args.session or f"forge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # ─── Routage Token-ID EN AMONT (optiforge two-tier) ─────────────
    # Si la tâche est un signal Token-ID résolu par réflexe Cervelet (Redis),
    # on répond SANS démarrer LangGraph (= ralentissement évité).
    try:
        from forge_agents.cervelet import route_request, ESCALATE
        routed = route_request(task)
        if routed != ESCALATE:
            if quiet:
                print(json.dumps({"reflex": True, "result": routed}, ensure_ascii=False))
            else:
                print(f"\n⚡ RÉFLEXE CERVELET (LangGraph court-circuité)\n   {routed}\n")
            return
    except Exception as e:
        if not quiet:
            print(f"   (routage Token-ID indisponible: {e})")

    if not quiet:
        print(f"\n🚀 SUPER AGENT FORGE")
        print(f"   Task     : {task}")
        print(f"   Session  : {session_id}")
        print(f"   Max cycles: {args.cycles}")
        print(f"   SQLite   : {'OFF' if args.no_sqlite else 'ON'}")
        print()

    runner = ForgeRunner(session_id=session_id, use_sqlite=not args.no_sqlite)
    try:
        result = runner.run_task(task=task, task_desc=task_desc, max_cycles=args.cycles,
                                   quiet=quiet)

        # TOKEN ACTUAL (affichage réclamé — supprimé en mode --quiet)
        try:
            from forge_agents.token_tracker import get_tracker
            tracker = get_tracker()
            if not quiet:
                print(tracker.render_actual_table())
                recs = tracker.generate_recommendations()
                for r in recs: print(r)
                print(f"\n📈 EFFICIENCY SCORE: {tracker.efficiency_score()}/100")
            tracker.generate_final_report()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        _print_result(result, quiet=quiet)
    finally:
        try:
            if "00_CORE.forge_agents.forge_graph" in sys.modules:
                sys.modules["00_CORE.forge_agents.forge_graph"].conn.close()
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


def _print_result(result: dict, quiet: bool = False):
    findings = result.get("findings", [])
    confirmed = [f for f in findings if f.get("status") == "confirmed"]
    analysis = result.get("token_analysis", {})

    if quiet:
        compact = {
            "success": bool(result.get("success")),
            "cycles_run": result.get("cycles_run", 0),
            "level": result.get("level", "L1"),
            "findings_confirmed": len(confirmed),
            "findings_total": len(findings),
            "error": result.get("error"),
            "top_findings": [
                {
                    "score": f.get("score", 0),
                    "agent": f.get("agent", "?"),
                    # Décodage AIL -> français : SEULE traduction en langage
                    # naturel de toute la session, faite ici, à la présentation
                    # finale (zéro appel LLM, dictionnaire déterministe).
                    "title": decode_line(f.get("title", f.get("content", "")))[:120],
                }
                for f in confirmed[:5]
            ],
            "efficiency_score": analysis.get("efficiency_score"),
            "savings_usd": analysis.get("savings_usd", 0),
            "log_path": analysis.get("log_path", ""),
        }
        print(json.dumps(compact, ensure_ascii=False))
        return

    print("\n╔══════════════════════════════════════╗")
    print("║          FORGE — RÉSULTAT            ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Statut  : {'✅ SUCCÈS' if result.get('success') else '❌ ÉCHEC'}")
    print(f"  Cycles  : {result.get('cycles_run', 0)}")
    print(f"  Niveau  : {result.get('level', 'L1')}")
    print(f"  Findings : {len(confirmed)} confirmés / {len(findings)} total")
    if result.get("error"):
        print(f"  Erreur  : {result['error']}")
    print()

    # Affiche les findings confirmés
    # NOTE: les findings sont stockés en AIL (Agent Inter-Lingo, format
    # ultra-compact inter-agents — cf. ail_protocol.py). Le décodage en
    # français a lieu UNIQUEMENT ici, à la présentation finale, via un
    # dictionnaire déterministe (zéro appel LLM supplémentaire).
    if confirmed:
        print("── Findings confirmés ──────────────────")
        for f in confirmed[:5]:
            score = f.get("score", 0)
            title = decode_line(f.get("title", f.get("content", ""))[:120])
            agent = f.get("agent", "?")
            print(f"  [{score:.1f}] [{agent}] {title}")
        if len(confirmed) > 5:
            print(f"  ... et {len(confirmed)-5} autres")
        print()

    # Caveman log (derniers 5)
    caveman = result.get("caveman_log", [])
    if caveman:
        print("── Caveman log (derniers 5) ────────────")
        for msg in caveman[-5:]:
            print(f"  {msg.get('sender','?')} {msg.get('verb','?')} {msg.get('object','?')}")
        print()

    # Token analysis (post-mortem)
    if analysis:
        print("── Token Post-Mortem ───────────────────")
        print(f"  Efficiency Score : {analysis.get('efficiency_score', '?')}/100")
        savings = analysis.get("savings_usd", 0)
        if savings > 0:
            print(f"  Savings          : ${savings:.4f}")
        elif savings < 0:
            print(f"  Over-budget      : ${abs(savings):.4f}")
        recs = analysis.get("recommendations", [])
        if recs:
            print(f"  Recommandations  : {len(recs)}")
            for r in recs[:3]:
                print(f"    {r}")
        log_path = analysis.get("log_path", "")
        if log_path:
            print(f"  Log file         : {log_path}")
        print()


if __name__ == "__main__":
    main()
