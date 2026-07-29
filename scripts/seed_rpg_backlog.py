"""
seed_rpg_backlog.py — injecte le plan RPG dans le backlog persistant (option A).

CE QUE FAIT CE SCRIPT
---------------------
1. **Lit** `07_REPORTS/AUDIT_APTITUDE_RPG.md` et en extrait les tickets. Il ne les
   retranscrit pas : les 40 tickets des epics E1→E6 sont parsés depuis les
   tableaux Markdown, les 14 tickets d'E7→E10 depuis leurs lignes en prose.
   Retranscrire à la main aurait introduit une dérive silencieuse entre le plan
   et le board le jour où l'audit bouge.
2. **Écrit** dans la table `tasks` (`forge_backlog`, ticket E1-01) — c'est la
   SOURCE DE VÉRITÉ.
3. **Projette** une vue kanban vers `05_STATE/kanban/board_rpg.json`.

DEUX CHOIX QUI ENGAGENT, ASSUMÉS ICI
------------------------------------
- **`board_rpg.json`, PAS `board.json`.** `05_STATE/kanban/board.json` est occupé
  par le board du Sprint 6j ouvert le 2026-07-25. L'écraser aurait détruit un
  sprint en cours pour installer un plan à 139 jours. Deux boards coexistent donc,
  et `kanban.py` n'en lit qu'un (`board.json`) — cf. AVERTISSEMENT ci-dessous.
- **Ré-exécuter ne perd PAS l'avancement.** L'audit est propriétaire du *plan*
  (titre, epic, effort, complexité, dépendances) ; la Forge est propriétaire de
  la *progression* (état, session, réel, retries, artefacts). Un re-seed rafraîchit
  le premier et préserve le second. `--force` remet tout à plat, explicitement.

⚠️ AVERTISSEMENT DE CÂBLAGE (ne pas le découvrir plus tard)
------------------------------------------------------------
`kanban.py` lit `state_path("kanban/board.json")` et l'API `/v1/orchestrator/board`
lit ce même nom AVEC tenant (`05_STATE/tenants/<id>/kanban/board.json`). Le board
RPG écrit ici s'appelle `board_rpg.json` : **il n'est donc lu ni par `kanban.py`
ni par la console aujourd'hui.** C'est délibéré — le brancher est le ticket E1-06,
et le faire maintenant exigerait de trancher la cohabitation des deux boards.
La source de vérité interrogeable dès maintenant est la table `tasks`, pas ce JSON.

Usage :
    python scripts/seed_rpg_backlog.py --dry-run   # montre sans écrire
    python scripts/seed_rpg_backlog.py
    python scripts/seed_rpg_backlog.py --force     # écrase aussi la progression
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

from forge_agents.forge_backlog import Backlog, get_backlog  # noqa: E402
from forge_agents.forge_store import state_path  # noqa: E402

AUDIT = FORGE_ROOT / "07_REPORTS" / "AUDIT_APTITUDE_RPG.md"
BOARD_NAME = "kanban/board_rpg.json"

#: Champs que l'audit possède. Tout le reste appartient à l'exécution.
PLAN_FIELDS = ("epic", "title", "effort_days", "complexity", "depends_on",
               "provenance", "notes")

#: Dépendances énoncées au niveau de l'EPIC pour E7→E10 (l'audit ne descend pas
#: au ticket sur ces epics). On reporte ce qu'il dit, on n'invente pas plus fin.
_EPIC_DEPS: dict[str, list[str]] = {
    "E7": ["E2-01"],            # « dépend de E2 »
    "E8": ["E2-01", "E7-01"],   # « dépend de E2 + E7 »
    "E9": ["E2-01"],            # « dépend de E2 »
    "E10": ["E8-01"],           # « dépend de E8 »
}

_ROW = re.compile(r"^\|\s*(E\d+-\d+)\s*\|")
_PROSE = re.compile(r"`(E\d+-\d+)`\s*(.+?)\s*(\d+(?:[.,]\d+)?)\s*j(?=\s*(?:·|—|$))")


def _clean(cell: str) -> str:
    return cell.replace("**", "").replace("*", "").strip()


def _deps(cell: str) -> list[str]:
    cell = _clean(cell)
    if not cell or cell in {"—", "-", "–"}:
        return []
    return [d.strip() for d in cell.replace(";", ",").split(",") if d.strip()]


def parse_audit(text: str) -> list[dict]:
    """Extrait les tickets de l'audit. Lève si une ligne de tableau est malformée."""
    tasks: dict[str, dict] = {}

    # ── Tableaux : | ID | titre | N j | déps | complexité |
    for lineno, line in enumerate(text.splitlines(), 1):
        if not _ROW.match(line):
            continue
        cells = [c for c in line.split("|")]
        if len(cells) != 7:
            raise ValueError(
                f"AUDIT ligne {lineno} : {len(cells) - 2} colonnes au lieu de 5 — "
                f"un titre contient probablement un « | ». Corriger l'audit "
                f"plutôt que deviner ici.\n  {line.strip()}")
        _, tid, title, effort, deps, cx, _ = cells
        tid = _clean(tid)
        effort_m = re.search(r"(\d+(?:[.,]\d+)?)", effort)
        cx = _clean(cx).upper()
        tasks[tid] = {
            "id": tid,
            "epic": tid.split("-")[0],
            "title": _clean(title)[:300],
            "effort_days": float(effort_m.group(1).replace(",", ".")) if effort_m else 0.0,
            "depends_on": _deps(deps),
            "complexity": cx if cx in ("S", "M", "H") else "M",
            "provenance": f"AUDIT_APTITUDE_RPG.md:{lineno} (tableau)",
        }

    # ── Prose : `E7-01` intitulé 4 j · `E7-02` ...
    for lineno, line in enumerate(text.splitlines(), 1):
        for tid, title, effort in _PROSE.findall(line):
            if tid in tasks:
                continue
            epic = tid.split("-")[0]
            tasks[tid] = {
                "id": tid,
                "epic": epic,
                "title": _clean(title)[:300],
                "effort_days": float(effort.replace(",", ".")),
                "depends_on": list(_EPIC_DEPS.get(epic, [])),
                "complexity": "M",
                "provenance": f"AUDIT_APTITUDE_RPG.md:{lineno} (prose)",
                "notes": "Dépendance au niveau de l'epic et complexité non "
                         "spécifiées au ticket par l'audit — défaut appliqué.",
            }

    # ── E11 : l'audit REFUSE de le décomposer (« à ne pas planifier maintenant »).
    # On pose un jalon unique plutôt que d'inventer 6 tickets qui n'existent pas.
    if "EPIC E11" in text and "E11-01" not in tasks:
        tasks["E11-01"] = {
            "id": "E11-01",
            "epic": "E11",
            "title": "SHIP — bandes-annonces, Steam, succès, patch notes, i18n, doublage",
            "effort_days": 12.0,
            "depends_on": [],
            "complexity": "M",
            "provenance": "AUDIT_APTITUDE_RPG.md (E11, non décomposé)",
            "notes": "JALON, pas un ticket. L'audit dit « à ne pas planifier "
                     "maintenant » : à décomposer après le vertical slice.",
        }

    return [tasks[k] for k in sorted(tasks, key=_sort_key)]


def _sort_key(tid: str) -> tuple[int, int]:
    epic, num = tid.split("-")
    return int(epic[1:]), int(num)


def seed(backlog: Backlog, tasks: list[dict], force: bool = False) -> dict:
    """Injecte le plan. Préserve la progression existante sauf si `force`."""
    existing = {t["id"]: t for t in backlog.all()}
    rows, kept = [], 0
    for t in tasks:
        prior = existing.get(t["id"])
        if prior and not force:
            merged = {**prior, **{k: v for k, v in t.items() if k in PLAN_FIELDS}}
            merged["id"] = t["id"]
            if prior["state"] != "pending" or prior["retries"]:
                kept += 1
            rows.append(merged)
        else:
            rows.append(t)
    backlog.upsert_many(rows)
    return {"injectés": len(rows), "progression_préservée": kept,
            "déjà_présents": len(set(existing) & {t["id"] for t in tasks})}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    ap.add_argument("--force", action="store_true",
                    help="réinitialise aussi l'état/le réel des tâches existantes")
    args = ap.parse_args()

    if not AUDIT.exists():
        print(f"ERREUR : audit introuvable — {AUDIT}")
        return 1

    tasks = parse_audit(AUDIT.read_text(encoding="utf-8"))
    epics = sorted({t["epic"] for t in tasks}, key=lambda e: int(e[1:]))
    total = sum(t["effort_days"] for t in tasks)
    print(f"Audit lu : {len(tasks)} tickets · {len(epics)} epics · {total:.0f} j-Forge")
    for e in epics:
        sub = [t for t in tasks if t["epic"] == e]
        print(f"  {e:<4} {len(sub):>2} tickets  {sum(x['effort_days'] for x in sub):>5.0f} j")

    if args.dry_run:
        print("\n--dry-run : rien n'a été écrit.")
        print(json.dumps(tasks[:3], ensure_ascii=False, indent=2)[:900])
        return 0

    backlog = get_backlog()
    report = seed(backlog, tasks, force=args.force)
    print(f"\nBacklog : {report}")

    board_path = state_path(BOARD_NAME)
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board = backlog.to_kanban_board("Plan RPG — AUDIT_APTITUDE_RPG.md")
    board_path.write_text(json.dumps(board, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"Vue kanban : {board_path}")
    print(f"  (⚠️ non lue par kanban.py ni /v1/orchestrator/board — cf. docstring, E1-06)")

    print()
    print(backlog.render())
    rep = backlog.validate()
    if rep["cycles"]:
        print(f"\n⚠️ CYCLES DÉTECTÉS : {rep['cycles']}")
        return 1
    if rep["dangling_dependencies"]:
        print(f"\n⚠️ dépendances orphelines : {rep['dangling_dependencies']}")
    print(f"\nPrenables maintenant ({len(rep['ready'])}) : {', '.join(rep['ready'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
