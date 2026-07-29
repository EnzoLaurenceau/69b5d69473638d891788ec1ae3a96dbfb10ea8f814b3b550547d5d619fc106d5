"""state_ownership.py — qui a le droit d'écrire dans `05_STATE`, et sous quel régime.

POURQUOI CE FICHIER EXISTE (W5-03a)
-----------------------------------
Le blueprint multi-tenant disait « migrer les 59 écrivains ». Mesuré ici : **64 fichiers,
213 sites d'écriture**. Les migrer en bloc était le plan ; c'était le mauvais plan. Une
grande partie de cet état n'appartient à aucun client — le catalogue d'outils de la Forge,
le registre des tenants lui-même, la version du runtime. Le cloisonner serait faux
(chaque tenant aurait son propre registre de tenants), pas seulement inutile.

La vraie question n'est donc pas « comment migrer 64 modules » mais **« à qui appartient
cet état ? »**. Elle se tranche une fois par module, et la réponse est ici, en clair.

LES TROIS RÉGIMES
-----------------
- `tenant`   — dérivé du travail d'un utilisateur (ses tâches, ses prompts, son dépôt,
               ses coûts). DOIT passer par `forge_store` (`put/append`) ou au minimum par
               `forge_store.state_path()`. C'est ce qui fuite entre clients si on l'oublie.
- `platform` — propriété de l'installation, identique pour tous, sans donnée utilisateur
               (catalogue d'outils, registre d'identité, quotas, config providers).
               Reste GLOBAL **volontairement** : le cloisonner casserait la fonction.
- `exempt`   — archive, tests, migrations ponctuelles, outillage lancé à la main par
               l'opérateur. Hors du chemin des requêtes : pas de risque inter-clients.

LE CLIQUET
----------
`--check` échoue si un écrivain d'état apparaît sans décision, ou si un module classé
`tenant` n'utilise toujours pas `forge_store`. La liste ne peut donc que se réduire :
un nouveau module non classé casse la CI le jour où il est écrit, pas six mois après.

    python 00_CORE/tools/state_ownership.py            # rapport
    python 00_CORE/tools/state_ownership.py --check    # porte CI
    python 00_CORE/tools/state_ownership.py --json     # 05_STATE/state_ownership.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]

#: `.claude/worktrees/*` : un worktree git est une COPIE complète du dépôt. Le scanner y
#: retrouvait les 73 mêmes modules sous un autre chemin, tous « non classés » — la porte
#: cassait sur des doublons, pas sur du code neuf. Même raison que `.git`.
SKIP_DIRS = ("node_modules", ".venv", "venv", "_extracted", "site-packages",
             "\\rtk\\", "/rtk/", "\\nexus\\", "/nexus/", "AsyncHerald", ".git",
             "graphify-out", "__pycache__", "\\worktrees\\", "/worktrees/")

WRITE_RE = re.compile(
    r"write_text|json\.dump|open\([^)]*['\"][wa]\+?['\"]|\.write\(|shutil\.copy|os\.replace"
)

#: Décision par module. `(régime, raison)`. La raison n'est pas décorative : c'est elle
#: qu'on relira le jour où quelqu'un voudra reclasser un module.
DECISIONS: dict[str, tuple[str, str]] = {
    # ── tenant : dérivé du travail d'un utilisateur ────────────────────────────────
    "00_CORE/forge_agents/forge_metrics.py":            ("tenant", "coût/latence par tâche du client"),
    "00_CORE/forge_agents/adaptive_rag.py":             ("tenant", "journal des requêtes RAG du client"),
    "00_CORE/forge_agents/agent_tracker.py":            ("tenant", "tâche courante + historique du client"),
    "00_CORE/forge_agents/agent_nodes.py":              ("tenant", "trace d'exécution live du client"),
    "00_CORE/forge_agents/tool_call_ledger.py":         ("tenant", "appels d'outils du client (audit)"),
    "00_CORE/forge_agents/forge_experience_db.py":      ("tenant", "expériences apprises sur le dépôt du client"),
    "00_CORE/forge_agents/forge_fingerprint.py":        ("tenant", "empreintes de prompts du client (cache)"),
    "00_CORE/forge_agents/forge_cache_orchestrator.py": ("tenant", "générations mises en cache = contenu client"),
    "00_CORE/forge_agents/forge_checkpoint_engine.py":  ("tenant", "checkpoints de session du client"),
    "00_CORE/forge_agents/forge_execution_logger.py":   ("tenant", "logs d'exécution par run du client"),
    "00_CORE/forge_agents/forge_self_heal.py":          ("tenant", "réparations sur le code du client"),
    "00_CORE/forge_agents/forge_no_mistakes.py":        ("tenant", "preuves collectées sur le run du client"),
    "00_CORE/forge_agents/forge_spine.py":              ("tenant", "file HITL : questions posées à CE client"),
    "00_CORE/forge_agents/forge_meta.py":               ("tenant", "état méta de la boucle du client"),
    "00_CORE/forge_agents/forge_graph.py":              ("tenant", "checkpoint LangGraph du run du client"),
    "00_CORE/forge_agents/graphify_checkpointer.py":    ("tenant", "progression d'indexation du dépôt client"),
    "00_CORE/forge_agents/memory_pruner.py":            ("tenant", "élague le graphe mémoire du client"),
    "00_CORE/forge_agents/sync_history.py":             ("tenant", "transcript de session du client"),
    "00_CORE/forge_agents/token_sprint_tracker.py":     ("tenant", "consommation de tokens du client"),
    "00_CORE/forge_agents/hallucination_compare.py":    ("tenant", "événements d'hallucination sur ses runs"),
    "00_CORE/forge_agents/hallucination_judge.py":      ("tenant", "escalades d'hallucination de ses runs"),
    "00_CORE/forge_agents/semantic_edit_engine/patch_memory.py": ("tenant", "patchs appliqués au code client"),
    "00_CORE/forge_agents/tech_debt.py":                ("tenant", "inventaire de dette DU dépôt client"),
    "00_CORE/forge_agents/debt_priority.py":            ("tenant", "priorisation de la dette du client"),
    "00_CORE/forge_agents/forge_swarm.py":              ("tenant", "audit du code du client"),
    "00_CORE/forge_agents/forge_health.py":             ("tenant", "santé du dépôt du client"),
    "00_CORE/forge_agents/forge_claude_health.py":      ("platform", "statut Claude CLI — installation-wide, pas par client"),
    "00_CORE/forge_agents/forge_data_scientist.py":     ("tenant", "rapport dérivé des métriques du client"),
    "00_CORE/forge_agents/finetune_pipeline.py":        ("tenant", "dataset construit sur ses expériences"),
    "00_CORE/forge_agents/n8n_bridge.py":               ("tenant", "curseur de synchro de SES workflows"),
    "00_CORE/forge_agents/nexus_bridge.py":             ("tenant", "graphe de code du dépôt client"),
    "00_CORE/forge_agents/world_gdd.py":                ("tenant", "GDD = le monde du client, rendu en document"),
    "00_CORE/forge_agents/world_canon.py":              ("tenant", "canon source, index de citations, gate copyright = propriété intellectuelle du monde du client"),
    "00_CORE/forge_dispatch/kanban.py":                 ("tenant", "board = les tâches du client"),
    "00_CORE/forge_dispatch/decomposer.py":             ("tenant", "écrit le board du client"),

    # ── platform : propriété de l'installation, pas d'un client ────────────────────
    "00_CORE/forge_agents/forge_identity.py":       ("platform", "registre des tenants — DOIT être hors tenant, sinon chacun édite ses droits"),
    "00_CORE/forge_agents/forge_quota.py":          ("platform", "limites — hors espace tenant sinon falsifiables"),
    "00_CORE/forge_agents/mimo_budget.py":          ("platform", "plan d'abonnement MiMo — partagé par tous les tenants ; par tenant, chacun croirait avoir les 11 Md"),
    "00_CORE/forge_agents/forge_store.py":          ("platform", "c'est le magasin lui-même"),
    "00_CORE/forge_agents/forge_system_registry.py":("platform", "capacités de la Forge, identiques pour tous"),
    "00_CORE/forge_agents/forge_chat_provider.py":  ("platform", "config providers LLM de l'installation"),
    "00_CORE/forge_agents/forge_versioning.py":     ("platform", "version du runtime"),
    "00_CORE/forge_agents/forge_mcp_pruner.py":     ("platform", "registre MCP de l'installation"),
    "00_CORE/forge_agents/forge_reuse_engine.py":   ("platform", "catalogue d'outils réutilisables"),
    "00_CORE/forge_agents/auto_tool_generator.py":  ("platform", "génère des outils du catalogue"),
    "00_CORE/forge_agents/forge_search_engine.py":  ("platform", "index de la doc du dépôt Forge"),
    "00_CORE/forge_agents/forge_data_tagger.py":    ("platform", "gabarits et AGENTS.md du dépôt Forge"),
    "00_CORE/forge_agents/service_map.py":          ("platform", "carte des bounded contexts du dépôt Forge"),
    "tool_index.py":                                ("platform", "catalogue d'outils de l'installation"),

    # ── exempt : hors chemin des requêtes ──────────────────────────────────────────
    "09_WEB/server.py":            ("exempt", "résout le tenant par requête (W5-03b) puis délègue"),
    "run_forge.py":                ("exempt", "entrée CLI opérateur : pose le scope, n'est pas dedans"),
    "forge_dispatcher.py":         ("exempt", "entrée CLI opérateur"),
    "session_transfer.py":         ("exempt", "outil opérateur, hors requête"),
    "00_CORE/test_aaos_wave.py":            ("exempt", "test"),
    "00_CORE/forge_agents/test_rag_benchmark.py": ("exempt", "test"),
    "test_mimo_budget.py":                  ("exempt", "test : écrit un ledger jetable sous tmp_path, jamais le vrai"),
    "test_phase3_isolation.py":             ("exempt", "test d'isolation multi-tenant (écrit via forge_store sous des tenants jetables, nettoie derrière)"),
    "00_CORE/tools/see_edit.py":            ("exempt", "outillage dev"),
    "00_CORE/tools/fix_hardcoded_paths.py": ("exempt", "outillage dev ponctuel"),
    "00_CORE/tools/dev/openhands.py":       ("exempt", "outillage dev"),
    "09_ARCHIVE/dashboard_legacy/dashboard_server.py": ("exempt", "archive, non exécutée"),
    "09_ARCHIVE/semantic_compressor.py":    ("exempt", "archive, non exécutée"),
    "scripts/migrate_to_pg.py":             ("exempt", "migration ponctuelle opérateur"),
    "scripts/forge_data_migration.py":      ("exempt", "migration ponctuelle opérateur"),
    "scripts/enforce_naming_convention.py": ("exempt", "outillage dépôt"),
    "scripts/daily_token_report.py":        ("exempt", "rapport opérateur, machine locale"),
    "scripts/recursive_optimizer.py":       ("exempt", "daemon opérateur, machine locale"),
    "scripts/forge_memory_warmup.py":       ("exempt", "daemon opérateur, machine locale"),
    "scripts/forge_telemetry_daemon.py":    ("exempt", "daemon opérateur, machine locale"),
    "scripts/hermes_session_tracker.py":    ("exempt", "daemon opérateur, machine locale"),
    "scripts/hallucination_tracker.py":     ("exempt", "outil opérateur, machine locale"),
    "scripts/_fix_sprint_timestamps.py":    ("exempt", "correctif ponctuel opérateur sur sqlite local"),
    "scripts/claude_session_watchdog.py":   ("exempt", "daemon opérateur, machine locale"),
    "scripts/seed_local.py":                ("exempt", "provisioning tenant local (opérateur), hors requête — pose l'identité, n'écrit pas d'état client"),
    "scripts/smoke_run.py":                 ("exempt", "smoke test bout-en-bout opérateur, lancé à la main"),
    "scripts/seed_rpg_backlog.py":          ("exempt", "seeder opérateur lancé à la main, hors requête — aucune donnée client : le board RPG est le plan de la Forge elle-même (nature 'platform', identique pour tous), projeté depuis la table `tasks`"),
    "00_CORE/tools/state_ownership.py":       ("exempt", "ce fichier"),
    "00_CORE/tools/migrate_state_writers.py": ("exempt", "outil de migration, lancé à la main"),
    "00_CORE/tools/export_benchmark_pack.py": ("exempt", "export ponctuel opérateur"),

    # ── platform : pipelines d'agrégation vers le graphe Kuzu ─────────────────────
    #    Le graphe Kuzu (04_GRAPHIFY/kuzu_graph/) est un asset platform non cloisonné
    #    par tenant — graph_db.py le gère via un chemin global unique. Ces deux outils
    #    sont les PIPELINES qui l'alimentent : ils lisent des sources d'origine tenant
    #    (experience_db, forge_metrics, tool_call_ledger, agent_tracker, hallucination,
    #    kanban, tech_debt) depuis le 05_STATE GLOBAL et les projettent dans le graphe.
    #    Classer 'exempt' serait faux (c'est un chemin inter-tenants actif).
    #    Classer 'tenant' imposerait forge_store + cloisonnement par tenant, ce qui
    #    détruirait la fonction : le graphe sert des requêtes cross-cutting (neural map,
    #    health graph, knowledge queries) et DOIT être unique.
    #    Dépendance connue : le graphe contient des données d'origine tenant — si un
    #    jour on ajoute une interface de requête par tenant, il faudra filtrer.
    "00_CORE/tools/living_graph_sync.py":    ("platform", "agrégateur quotidien 10 sources → graphe Kuzu (platform) — lit experience_db, forge_metrics, tool_call_ledger, agent_tracker, hallucination_events + findings/kanban depuis 05_STATE global ; le graphe 04_GRAPHIFY/kuzu_graph/ est non cloisonné par design (graph_db.py est déjà platform)"),
    "00_CORE/tools/full_graph_connect.py":   ("platform", "connecteur complet orphelins + ingestion sources → graphe Kuzu (platform) — lit kanban, tech_debt, resources, catalog, skills depuis 05_STATE/07_KB/global paths ; même graphe 04_GRAPHIFY/kuzu_graph/ non cloisonné"),
}

#: Modules `tenant` que l'outil ne sait pas migrer mécaniquement : chemin construit
#: dynamiquement, état porté par une instance, ou base SQLite. Chacun demande une décision
#: — d'où la liste explicite plutôt qu'un seuil. Le cliquet interdit qu'elle s'allonge :
#: elle ne peut que se vider.
#:
#: W5-03c (Phase 3) : les 8 derniers modules ont été migrés à la main, chacun selon sa
#: contrainte (accesseurs paresseux résolus À L'APPEL via `forge_store.state_path` /
#: `tenant_dir`, avec repli GLOBAL historique quand aucun tenant n'est en contexte).
#: La liste est désormais VIDE : `--check` passe sans allowlist. Ne la ré-alimente pas —
#: un nouveau module `tenant` doit passer par `forge_store` dès son écriture.
PENDING_ALLOWLIST: dict[str, str] = {}


def scan(root: Path = FORGE_ROOT) -> dict[str, dict]:
    """Trouve les modules qui écrivent dans `05_STATE` et joint leur décision."""
    found: dict[str, dict] = {}
    for p in root.rglob("*.py"):
        s = str(p)
        if any(x in s for x in SKIP_DIRS):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Un module migré ne contient plus « 05_STATE » — il appelle `state_path`. Sans
        # ce second critère, réussir la migration ferait disparaître le module du rapport,
        # et le compteur « migrés » retomberait à zéro en récompense du travail fait.
        if not WRITE_RE.search(txt):
            continue
        if "05_STATE" not in txt and "state_path" not in txt and "forge_store" not in txt:
            continue
        rel = p.relative_to(root).as_posix()
        regime, reason = DECISIONS.get(rel, ("UNCLASSIFIED", ""))
        found[rel] = {
            "regime": regime,
            "reason": reason,
            "write_sites": len(WRITE_RE.findall(txt)),
            "uses_store": "forge_store" in txt,
        }
    return found


def report(found: dict[str, dict]) -> dict:
    by = {}
    for rel, d in found.items():
        by.setdefault(d["regime"], []).append(rel)
    tenant = by.get("tenant", [])
    migrated = [r for r in tenant if found[r]["uses_store"]]
    return {
        "writers": len(found),
        "write_sites": sum(d["write_sites"] for d in found.values()),
        "by_regime": {k: len(v) for k, v in sorted(by.items())},
        "tenant_total": len(tenant),
        "tenant_migrated": len(migrated),
        "tenant_pending": sorted(set(tenant) - set(migrated)),
        "unclassified": sorted(by.get("UNCLASSIFIED", [])),
        # une décision est périmée quand son fichier a disparu du dépôt — pas quand le
        # module a été migré (il reste dans le scan via `state_path`)
        "stale_decisions": sorted(r for r in DECISIONS if not (FORGE_ROOT / r).exists()),
        "unexpected_pending": sorted(set(tenant) - set(migrated) - set(PENDING_ALLOWLIST)),
        "allowlist_cleared": sorted(set(PENDING_ALLOWLIST) & set(migrated)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="porte CI : échoue si non classé ou non migré")
    ap.add_argument("--json", action="store_true", help="écrit 05_STATE/state_ownership.json")
    args = ap.parse_args()

    found = scan()
    rep = report(found)

    print(f"écrivains d'état : {rep['writers']}  ({rep['write_sites']} sites d'écriture)")
    for regime, n in rep["by_regime"].items():
        print(f"  {regime:14s} {n}")
    print(f"tenant migrés    : {rep['tenant_migrated']}/{rep['tenant_total']}")
    for rel in rep["tenant_pending"]:
        why = PENDING_ALLOWLIST.get(rel, "NON PRÉVU — le cliquet va casser")
        print(f"  À MIGRER  {rel}  ({why})")
    for rel in rep["unclassified"]:
        print(f"  NON CLASSÉ  {rel}  -> ajouter une décision dans DECISIONS")
    for rel in rep["stale_decisions"]:
        print(f"  décision orpheline (fichier disparu) : {rel}")
    for rel in rep["allowlist_cleared"]:
        print(f"  migré : retirer de PENDING_ALLOWLIST -> {rel}")

    if args.json:
        out = FORGE_ROOT / "05_STATE" / "state_ownership.json"
        out.write_text(json.dumps({"summary": rep, "modules": found}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"-> {out}")

    if args.check:
        # Le cliquet ne demande pas la perfection, il interdit la régression : aucun
        # écrivain non classé, aucun `tenant` non migré hors de la liste connue.
        bad = rep["unclassified"] + rep["unexpected_pending"] + rep["allowlist_cleared"]
        print("\nPORTE " + ("ÉCHEC" if bad else "OK") +
              f"  (non classés {len(rep['unclassified'])}, "
              f"tenant non migrés hors liste {len(rep['unexpected_pending'])}, "
              f"liste à nettoyer {len(rep['allowlist_cleared'])})")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
