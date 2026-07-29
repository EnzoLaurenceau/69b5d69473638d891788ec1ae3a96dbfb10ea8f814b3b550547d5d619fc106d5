"""forge_sprint.py — Moteur de sprints agiles (ticket E1-04)
===========================================================
Le backlog (forge_backlog.py) porte le PLAN complet. Ce module porte le RYTHME :
sprint courant, vélocité mesurée, burndown en temps réel, replanification auto.

DEUX DÉCISIONS D'ARCHI
-----------------------
1. **Un sprint est une FENÊTRE sur le backlog, pas une copie.** Les tâches sont
   assignées par `task_ids`, pas dupliquées. L'état reste dans `tasks`. Quand
   le backlog change, le sprint le reflète immédiatement.
2. **La replanification est automatique et traçable.** Quand une tâche glisse
   (son `actual_days` dépasse l'estimé ou elle est repoussée au sprint suivant),
   le sprint recalcule sa charge restante et propose un plan B. L'ancien plan
   n'est pas écrasé — il est archivé dans `plan_history`.

SURFACE UTILE
  - `SprintPlan.plan(tasks, capacity)` → assignation optimale
  - `SprintPlan.velocity(sprint_id)` → vélocité mesurée
  - `SprintPlan.burndown(sprint_id)` → snapshot quotidien
  - `SprintPlan.replanify(sprint_id)` → ajustement auto

Vérification : `python -m forge_agents.forge_sprint` (auto-test).
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

SPRINT_TABLE = "sprints"

#: États d'un sprint.
SPRINT_STATES: tuple[str, ...] = ("planning", "active", "completed", "cancelled")

#: Jours ouvrables par semaine (pour convertir effort_days en jours calendaires).
WORK_DAYS_PER_WEEK = 5

#: Durée par défaut d'un sprint (jours ouvrables).
DEFAULT_SPRINT_DAYS = 5


def _fail(msg: str) -> None:
    raise ValueError(f"[forge_sprint] {msg}")


# ── Modèle Sprint ────────────────────────────────────────────────────────────

class Sprint:
    """Un sprint = une timebox de travail avec capacité mesurée."""

    _PROPS = {
        "id":             (str, "", "TEXT PRIMARY KEY"),
        "name":           (str, "", "TEXT"),
        "state":          (str, "planning", "TEXT"),
        "task_ids":       (list, None, "JSONB"),
        "capacity_days":  ((int, float), 0.0, "REAL"),
        "start_ts":       ((int, float), 0.0, "DOUBLE PRECISION"),
        "end_ts":         ((int, float), 0.0, "DOUBLE PRECISION"),
        "actual_end_ts":  ((int, float), 0.0, "DOUBLE PRECISION"),
        "plan_history":   (list, None, "JSONB"),
        "notes":          (str, "", "TEXT"),
        "created_at":     ((int, float), 0.0, "DOUBLE PRECISION"),
        "updated_at":     ((int, float), 0.0, "DOUBLE PRECISION"),
    }
    _LIST_PROPS = ("task_ids", "plan_history")

    def __init__(self, **fields: Any):
        for name, (_, default, _) in self._PROPS.items():
            val = fields.get(name, default)
            if name in self._LIST_PROPS:
                val = list(val) if val else []
            setattr(self, name, val)

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self._PROPS}

    @classmethod
    def from_dict(cls, row: dict) -> "Sprint":
        out = dict(row)
        for key in cls._LIST_PROPS:
            val = out.get(key)
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (ValueError, TypeError):
                    val = []
            out[key] = list(val) if isinstance(val, (list, tuple)) else []
        for key in ("capacity_days", "start_ts", "end_ts", "actual_end_ts",
                     "created_at", "updated_at"):
            try:
                out[key] = float(out.get(key) or 0.0)
            except (TypeError, ValueError):
                out[key] = 0.0
        return cls(**{k: out.get(k) for k in cls._PROPS})


# ── Moteur de sprints ────────────────────────────────────────────────────────

class SprintEngine:
    """Gestion des sprints, vélocité, burndown, replanification.

    Persisté dans la table `sprints` via `forge_db`. Une instance = une vue
    sur le store, sans cache mémoire (même convention que `Backlog`).
    """

    SCAN_LIMIT = 5000

    def __init__(self, db: Any = None, backlog: Any = None):
        self._db = db
        self._backlog = backlog

    @property
    def db(self):
        if self._db is None:
            from .forge_db import get_db
            self._db = get_db()
        return self._db

    @property
    def backlog(self):
        if self._backlog is None:
            from .forge_backlog import get_backlog
            self._backlog = get_backlog()
        return self._backlog

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create(self, sprint_id: str, name: str, task_ids: list[str],
               capacity_days: float = 0.0, start_ts: float = 0.0,
               duration_days: int = DEFAULT_SPRINT_DAYS,
               notes: str = "") -> Sprint:
        """Crée un sprint. Si `capacity_days` est 0, dérive des tâches assignées."""
        now = time.time()
        start = start_ts or now

        # Validation des task_ids
        all_tasks = {t["id"]: t for t in self.backlog.all()}
        unknown = [tid for tid in task_ids if tid not in all_tasks]
        if unknown:
            _fail(f"tâches inconnues : {unknown}")

        # Capacité auto si non fournie : somme des effort_days des tâches
        if capacity_days <= 0:
            capacity_days = sum(
                all_tasks[tid]["effort_days"] for tid in task_ids
                if tid in all_tasks
            )

        sprint = Sprint(
            id=sprint_id,
            name=name,
            state="planning",
            task_ids=task_ids,
            capacity_days=round(capacity_days, 2),
            start_ts=start,
            end_ts=start + duration_days * 86400,  # secondes
            created_at=now,
            updated_at=now,
            notes=notes,
        )
        self._save(sprint)
        return sprint

    def activate(self, sprint_id: str) -> Sprint:
        """Passe un sprint en 'active'. Un seul sprint peut être actif."""
        sprint = self.get(sprint_id)
        if not sprint:
            _fail(f"sprint inconnu : {sprint_id}")
        if sprint.state == "active":
            return sprint

        # Archiver tout sprint actif
        for s in self.all():
            if s.state == "active" and s.id != sprint_id:
                self._save(Sprint(**{**s.to_dict(), "state": "completed",
                                     "actual_end_ts": time.time(),
                                     "updated_at": time.time()}))

        sprint.state = "active"
        sprint.updated_at = time.time()
        self._save(sprint)
        return sprint

    def complete(self, sprint_id: str) -> Sprint:
        sprint = self.require(sprint_id)
        sprint.state = "completed"
        sprint.actual_end_ts = time.time()
        sprint.updated_at = time.time()
        self._save(sprint)
        return sprint

    def get(self, sprint_id: str) -> Optional[Sprint]:
        for s in self.all():
            if s.id == sprint_id:
                return s
        return None

    def require(self, sprint_id: str) -> Sprint:
        s = self.get(sprint_id)
        if s is None:
            _fail(f"sprint inconnu : {sprint_id}")
        return s  # type: ignore[return-value]

    def all(self) -> list[Sprint]:
        rows = self.db.deep_query(SPRINT_TABLE, None, limit=self.SCAN_LIMIT) or []
        return [Sprint.from_dict(r) for r in rows]

    def active(self) -> Optional[Sprint]:
        for s in self.all():
            if s.state == "active":
                return s
        return None

    def _save(self, sprint: Sprint) -> None:
        d = sprint.to_dict()
        d["updated_at"] = time.time()
        self.db.deep_insert(SPRINT_TABLE, d)

    # ── Vélocité ──────────────────────────────────────────────────────────────

    def velocity(self, sprint_id: str) -> dict:
        """Vélocité mesurée : tâches/jour, effort_days/jour, % complété.

        Utilise `start_ts` et `time.now()` pour calculer les jours écoulés.
        Si le sprint n'a pas commencé, retourne 0.
        """
        sprint = self.require(sprint_id)
        tasks = [t for t in self.backlog.all() if t["id"] in sprint.task_ids]
        total_tasks = len(tasks)
        done_tasks = sum(1 for t in tasks if t["state"] == "done")
        total_effort = sum(t["effort_days"] for t in tasks)
        done_effort = sum(t["effort_days"] for t in tasks if t["state"] == "done")
        actual_effort = sum(t["actual_days"] for t in tasks if t["state"] == "done")

        # Jours écoulés (en jours ouvrables)
        if sprint.start_ts > 0:
            elapsed_s = time.time() - sprint.start_ts
            elapsed_days = max(1.0, elapsed_s / 86400)
        else:
            elapsed_days = 0.0

        tasks_per_day = done_tasks / elapsed_days if elapsed_days > 0 else 0
        effort_per_day = done_effort / elapsed_days if elapsed_days > 0 else 0

        # Prédiction de fin
        remaining_tasks = total_tasks - done_tasks
        remaining_effort = total_effort - done_effort
        if tasks_per_day > 0:
            predicted_days_left = remaining_tasks / tasks_per_day
        elif effort_per_day > 0:
            predicted_days_left = remaining_effort / effort_per_day
        else:
            predicted_days_left = float("inf")

        return {
            "sprint_id": sprint_id,
            "state": sprint.state,
            "total_tasks": total_tasks,
            "done_tasks": done_tasks,
            "pct_done": round(100 * done_tasks / total_tasks, 1) if total_tasks else 0,
            "total_effort_days": round(total_effort, 2),
            "done_effort_days": round(done_effort, 2),
            "actual_effort_days": round(actual_effort, 2),
            "elapsed_days": round(elapsed_days, 1),
            "tasks_per_day": round(tasks_per_day, 2),
            "effort_per_day": round(effort_per_day, 2),
            "remaining_tasks": remaining_tasks,
            "remaining_effort_days": round(remaining_effort, 2),
            "predicted_days_left": round(predicted_days_left, 1) if predicted_days_left != float("inf") else None,
            "capacity_days": sprint.capacity_days,
            "on_track": remaining_effort <= sprint.capacity_days if sprint.capacity_days > 0 else None,
        }

    # ── Burndown ──────────────────────────────────────────────────────────────

    def burndown(self, sprint_id: str) -> dict:
        """Snapshot burndown : effort restant par jour.

        Reconstruit à partir des timestamps de complétion des tâches.
        Pour un vrai graph, X = jours, Y = effort restant.
        """
        sprint = self.require(sprint_id)
        tasks = [t for t in self.backlog.all() if t["id"] in sprint.task_ids]
        total_effort = sum(t["effort_days"] for t in tasks)

        # Jour 0 = start_ts
        if sprint.start_ts <= 0:
            return {"sprint_id": sprint_id, "total_effort": total_effort,
                    "snapshots": [], "current_remaining": total_effort}

        # Trier les tâches terminées par date de complétion
        completed = sorted(
            [(t["effort_days"], t["completed_at"]) for t in tasks
             if t["state"] == "done" and t["completed_at"] > 0],
            key=lambda x: x[1]
        )

        snapshots = [{"day": 0, "remaining": round(total_effort, 2)}]
        running = total_effort
        for effort, completed_at in completed:
            day = max(1, int((completed_at - sprint.start_ts) / 86400) + 1)
            running -= effort
            snapshots.append({"day": day, "remaining": round(max(0, running), 2)})

        # Effort restant courant
        remaining = sum(t["effort_days"] for t in tasks if t["state"] != "done")

        return {
            "sprint_id": sprint_id,
            "total_effort": round(total_effort, 2),
            "current_remaining": round(remaining, 2),
            "snapshots": snapshots,
            "ideal_burn_rate": round(total_effort / max(sprint.capacity_days, 1), 2),
        }

    # ── Replanification ──────────────────────────────────────────────────────

    def replanify(self, sprint_id: str) -> dict:
        """Quand le sprint dérape : propose un plan B.

        - Calcule les tâches restantes et leur effort.
        - Si la capacité restante est insuffisante, propose de :
          1. Réduire le scope (retirer les tâches à plus grande marge).
          2. Étendre le sprint (jours supplémentaires).
          3. Scinder (reporter au sprint suivant).
        - Archive l'ancien plan dans `plan_history`.
        """
        sprint = self.require(sprint_id)
        vel = self.velocity(sprint_id)
        tasks = [t for t in self.backlog.all() if t["id"] in sprint.task_ids]

        remaining_tasks = [t for t in tasks if t["state"] not in ("done", "cancelled")]
        remaining_effort = sum(t["effort_days"] for t in remaining_tasks)

        # Jours restants dans le sprint
        if sprint.end_ts > 0:
            days_left_s = max(0, sprint.end_ts - time.time())
            days_left = days_left_s / 86400
        else:
            days_left = sprint.capacity_days

        # Capacité restante (basée sur la vélocité mesurée)
        effort_per_day = vel.get("effort_per_day", 0)
        if effort_per_day > 0:
            capacity_left = effort_per_day * days_left
        else:
            # Pas de vélocité mesurée — utiliser la capacité totale
            capacity_left = sprint.capacity_days - vel.get("done_effort_days", 0)

        # Glissement
        overflow = remaining_effort - capacity_left
        plan = {
            "sprint_id": sprint_id,
            "remaining_tasks": len(remaining_tasks),
            "remaining_effort_days": round(remaining_effort, 2),
            "days_left": round(days_left, 1),
            "capacity_left": round(capacity_left, 2),
            "overflow_days": round(max(0, overflow), 2),
            "on_track": overflow <= 0,
        }

        if overflow > 0:
            # Trier par marge (slack) décroissante — les plus reportables d'abord
            cp = self.backlog.critical_path(remaining=True)
            slack_map = cp.get("schedule", {})

            def sort_key(t: dict) -> float:
                s = slack_map.get(t["id"], {}).get("slack", 0)
                return -s  # marge décroissante = reportable d'abord

            sorted_tasks = sorted(remaining_tasks, key=sort_key)

            # Plan B : retirer les tâches les plus marginales
            removable = []
            remaining_capacity = capacity_left
            must_keep = []
            for t in sorted_tasks:
                if t["effort_days"] <= remaining_capacity:
                    remaining_capacity -= t["effort_days"]
                    must_keep.append(t["id"])
                else:
                    removable.append(t["id"])

            plan["plan_b"] = {
                "action": "réduire scope",
                "keep": must_keep,
                "defer": removable,
                "defer_effort": round(sum(
                    t["effort_days"] for t in sorted_tasks if t["id"] in removable
                ), 2),
            }
            plan["alternatives"] = [
                f"étendre de {round(overflow / max(effort_per_day, 0.5), 1)} jours",
                f"reporter {len(removable)} tâche(s) au sprint suivant",
            ]

        # Archiver le plan actuel
        sprint.plan_history.append({
            "timestamp": time.time(),
            "velocity": vel,
            "replan": plan,
        })
        sprint.updated_at = time.time()
        self._save(sprint)

        return plan

    # ── Planification ─────────────────────────────────────────────────────────

    def plan_from_backlog(self, sprint_id: str, name: str,
                          max_days: float = 0.0,
                          priority_epic: str = "") -> dict:
        """Crée un sprint en sélectionnant automatiquement les tâches prêtes.

        Sélectionne parmi les `ready()` du backlog, dans l'ordre topologique,
        jusqu'à remplir `max_days` (ou tout prendre si 0).
        Si `priority_epic` est donné, les tâches de cet epic passent en premier.
        """
        ready = self.backlog.ready()
        if priority_epic:
            prio = [t for t in ready if t["epic"] == priority_epic]
            rest = [t for t in ready if t["epic"] != priority_epic]
            ready = prio + rest

        # Ordre topologique pour respecter les dépendances
        try:
            topo = self.backlog.topological_order(ready)
            topo_index = {tid: i for i, tid in enumerate(topo)}
            ready.sort(key=lambda t: topo_index.get(t["id"], 999))
        except ValueError:
            # Cycle — garder l'ordre par epic/id
            ready.sort(key=lambda t: (t["epic"], t["id"]))

        selected = []
        total_days = 0.0
        for t in ready:
            effort = t["effort_days"]
            if max_days > 0 and total_days + effort > max_days:
                continue
            selected.append(t["id"])
            total_days += effort

        if not selected:
            return {"created": False, "reason": "Aucune tâche prête", "task_ids": []}

        sprint = self.create(sprint_id, name, selected,
                             capacity_days=max_days or total_days)
        return {
            "created": True,
            "sprint_id": sprint_id,
            "task_ids": selected,
            "total_effort_days": round(total_days, 2),
            "task_count": len(selected),
        }

    # ── Rendu ─────────────────────────────────────────────────────────────────

    def render(self, sprint_id: str) -> str:
        """Rendu texte d'un sprint (lisible en session)."""
        vel = self.velocity(sprint_id)
        bd = self.burndown(sprint_id)
        lines = [
            f"Sprint {sprint_id} — {vel['state']}",
            f"  tâches: {vel['done_tasks']}/{vel['total_tasks']} ({vel['pct_done']:.0f}%)",
            f"  effort: {vel['done_effort_days']:.1f}/{vel['total_effort_days']:.1f}j "
            f"(réel: {vel['actual_effort_days']:.1f}j)",
            f"  vélocité: {vel['tasks_per_day']:.1f} tâches/j, "
            f"{vel['effort_per_day']:.1f}j/j",
            f"  restant: {vel['remaining_effort_days']:.1f}j "
            f"({vel['remaining_tasks']} tâches)",
        ]
        if vel["predicted_days_left"] is not None:
            lines.append(f"  prédiction fin: {vel['predicted_days_left']:.0f}j")
        if vel["on_track"] is not None:
            lines.append(f"  {'✅ en bonne voie' if vel['on_track'] else '⚠️ en retard'}")
        if bd["current_remaining"] > 0:
            lines.append(f"  burndown: {bd['current_remaining']:.1f}j restantes, "
                         f"taux idéal: {bd['ideal_burn_rate']:.1f}j/j")
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: Optional[SprintEngine] = None


def get_sprint_engine() -> SprintEngine:
    global _engine
    if _engine is None:
        _engine = SprintEngine()
    return _engine


if __name__ == "__main__":
    print("=== forge_sprint.py — auto-test ===")
    print(f"Sprint states: {SPRINT_STATES}")
    # Test Sprint model
    s = Sprint(id="test-1", name="Test Sprint", task_ids=["E1-01", "E1-02"],
               capacity_days=5.0, start_ts=time.time() - 86400 * 2)
    d = s.to_dict()
    print(f"Sprint.to_dict: {len(d)} champs, state={d['state']}")
    s2 = Sprint.from_dict(d)
    print(f"Round-trip: id={s2.id}, tasks={s2.task_ids}, cap={s2.capacity_days}")
    print("OK — SprintEngine prêt (nécessite forge_db pour persister)")
