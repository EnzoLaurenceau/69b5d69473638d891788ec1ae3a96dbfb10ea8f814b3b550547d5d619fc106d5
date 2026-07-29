"""
forge_backlog.py — Backlog persistant de la Forge (ticket E1-01)
================================================================
Le kanban historique (`00_CORE/forge_dispatch/kanban.py`) est un fichier JSON :
il sait *qui tient quoi maintenant*, mais il ne sait ni à quel epic une tâche
appartient, ni de quoi elle dépend, ni ce qu'elle a coûté par rapport à ce qui
était estimé. Autrement dit il porte le WIP, pas le plan. Ce module ajoute la
couche manquante : un **backlog typé, persistant et interrogeable**.

CE QUI EST STOCKÉ, ET OÙ
------------------------
Table `tasks` du store unifié `forge_db` :
  - Postgres up   → vraies colonnes + index (`epic`, `state`) ;
  - Postgres down → secours SQLite `04_GRAPHIFY/forge_fallback.db`, où la ligne
    est un blob JSON générique.
On n'ouvre AUCUNE base à soi : tout passe par `get_db().deep_insert/deep_query`,
donc le dual-write et le WAL de `forge_db` s'appliquent gratuitement.

TROIS DÉCISIONS D'ARCHI (ne pas les re-litiger sans lire le HANDOFF)
--------------------------------------------------------------------
1. **Le backlog ne remplace pas le kanban, il le précède.** `kanban.py` reste le
   protocole de claim inter-sessions ; `to_kanban_board()` projette le backlog
   vers son format. Le graphe de dépendances vit ici, le WIP vit là-bas.
2. **Les garde-fous LÈVENT, ils n'avertissent pas** (même doctrine que
   `world_kg.py`) : état inconnu, complexité inconnue, propriété hors whitelist,
   transition d'état illégale, auto-dépendance → `ValueError`. Un agent qui
   écrit à côté doit être bloqué, pas se croire enregistré.
3. **Une dépendance déclarée vers une tâche encore inexistante est TOLÉRÉE à
   l'écriture, mais bloque le `claim()`.** Injecter 60 tickets d'un plan impose
   des références avant-coureuses ; refuser à l'insertion rendrait l'ordre du
   batch signifiant. On paie la rigueur au moment où se tromper coûte quelque
   chose : prendre la tâche. Une dépendance inconnue n'est jamais « satisfaite ».

SURFACE UTILE AUX TICKETS SUIVANTS
----------------------------------
  - `ready()` / `dependents_of()` / `validate()` → **E1-02** (chemin critique,
    cycles) → DONE : `find_cycles()`, `topological_order()`, `critical_path()`,
    `conflicts()` sont dans ce fichier ;
  - `auto_estimate()` / `calibration_stats()` / `bulk_estimate()` /
    `estimation_report()` → **E1-03** (estimation apprenante) → DONE ;
  - `effort_days` vs `actual_days`, `est_tokens` vs `actual_tokens` → **E6-01**
    (mesure par tâche) ;
  - `retries` + `bump_retry()` + état `blocked` → **E1-05** (réaffectation) ;
  - `to_kanban_board()` → **E1-06** (vue console) et **E1-07** (`resume_project`).

Vérification : `python -m forge_agents.forge_backlog` (auto-test du schéma).
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterable, Optional

TABLE = "tasks"

#: Vocabulaire d'état. Fermé : tout le reste lève.
TASK_STATES: tuple[str, ...] = (
    "pending",      # dans le backlog, dépendances non vérifiées
    "ready",        # dépendances satisfaites, prenable
    "in_progress",  # tenue par une session
    "blocked",      # empêchée par une cause externe (≠ dépendance non faite)
    "done",
    "cancelled",
)

#: États depuis lesquels une tâche ne consomme plus de capacité.
TERMINAL_STATES: tuple[str, ...] = ("done", "cancelled")

#: Complexité telle que notée dans `07_REPORTS/AUDIT_APTITUDE_RPG.md`.
COMPLEXITIES: tuple[str, ...] = ("S", "M", "H")

#: Transitions autorisées. Une transition absente de cette table lève.
#: Lecture : depuis `k`, on peut aller vers n'importe quel élément de `v`.
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending":     ("ready", "in_progress", "blocked", "cancelled", "pending"),
    "ready":       ("in_progress", "blocked", "pending", "cancelled", "ready"),
    "in_progress": ("done", "blocked", "pending", "ready", "cancelled", "in_progress"),
    "blocked":     ("pending", "ready", "in_progress", "cancelled", "blocked"),
    # `done` → `in_progress` : la réouverture est légitime (régression trouvée
    # plus tard, E1-05). Elle est explicite, pas un effet de bord.
    "done":        ("in_progress", "pending", "done"),
    "cancelled":   ("pending", "cancelled"),
}

#: Whitelist des propriétés + type Python attendu + valeur par défaut.
#: Le DDL Postgres en est DÉRIVÉ (cf. `table_ddl()`), il n'est pas écrit à la main.
_TASK_PROPS: dict[str, tuple[type | tuple[type, ...], Any, str]] = {
    # nom              (type(s) accepté(s),        défaut,  type SQL)
    "id":              (str,                        "",     "TEXT PRIMARY KEY"),
    "epic":            (str,                        "",     "TEXT"),
    "title":           (str,                        "",     "TEXT"),
    "state":           (str,                        "pending", "TEXT"),
    "complexity":      (str,                        "M",    "TEXT"),
    "effort_days":     ((int, float),               0.0,    "REAL"),
    "actual_days":     ((int, float),               0.0,    "REAL"),
    "est_tokens":      (int,                        0,      "BIGINT"),
    "actual_tokens":   (int,                        0,      "BIGINT"),
    "assignee":        (str,                        "",     "TEXT"),
    "session_id":      (str,                        "",     "TEXT"),
    "depends_on":      (list,                       None,   "JSONB"),
    "artifacts":       (list,                       None,   "JSONB"),
    "files":           (list,                       None,   "JSONB"),
    "retries":         (int,                        0,      "INT"),
    "block_reason":    (str,                        "",     "TEXT"),
    "provenance":      (str,                        "",     "TEXT"),
    "notes":           (str,                        "",     "TEXT"),
    "created_at":      ((int, float),               0.0,    "DOUBLE PRECISION"),
    "updated_at":      ((int, float),               0.0,    "DOUBLE PRECISION"),
    "started_at":      ((int, float),               0.0,    "DOUBLE PRECISION"),
    "completed_at":    ((int, float),               0.0,    "DOUBLE PRECISION"),
}

#: Colonnes portant une liste — sérialisées en JSON côté Postgres par `_pg_upsert`,
#: mais relues telles quelles côté secours SQLite. `_coerce_row` réconcilie.
_LIST_PROPS: tuple[str, ...] = ("depends_on", "artifacts", "files")

TASK_PROPS: tuple[str, ...] = tuple(_TASK_PROPS)


# ── DDL dérivé (fonction pure : testable sans base) ───────────────────────────

def table_ddl() -> str:
    """DDL Postgres de la table `tasks`, dérivé de `_TASK_PROPS`.

    Pure et idempotente : c'est ce que `forge_db._ensure_schema` exécute. Ne
    jamais écrire ce DDL à la main ailleurs — ajouter une propriété ici suffit.
    """
    cols = ",\n            ".join(
        f"{name} {spec[2]}" for name, spec in _TASK_PROPS.items())
    return (
        "CREATE TABLE IF NOT EXISTS tasks (\n            "
        + cols
        + "\n        );\n"
        "        CREATE INDEX IF NOT EXISTS tasks_epic_idx ON tasks(epic);\n"
        "        CREATE INDEX IF NOT EXISTS tasks_state_idx ON tasks(state);"
    )


# ── Validation ────────────────────────────────────────────────────────────────

def _fail(msg: str) -> None:
    raise ValueError(f"[forge_backlog] {msg}")


def validate_task(row: dict) -> dict:
    """Normalise et valide une tâche. Lève `ValueError` au premier écart.

    Retourne un dict complet (défauts appliqués), prêt pour `deep_insert`.
    """
    if not isinstance(row, dict):
        _fail(f"une tâche doit être un dict, reçu {type(row).__name__}")

    unknown = set(row) - set(_TASK_PROPS)
    if unknown:
        _fail(f"propriété(s) hors whitelist : {sorted(unknown)} "
              f"— ajoute-les à _TASK_PROPS si elles sont légitimes")

    tid = str(row.get("id", "")).strip()
    if not tid:
        _fail("`id` est obligatoire et non vide (ex. 'E1-01')")

    out: dict[str, Any] = {}
    for name, (types, default, _sql) in _TASK_PROPS.items():
        if name in row and row[name] is not None:
            value = row[name]
            if isinstance(value, bool) and types is not bool:
                _fail(f"{tid}.{name} : booléen inattendu")
            if not isinstance(value, types):
                want = types if isinstance(types, type) else types
                _fail(f"{tid}.{name} : attendu {want}, reçu "
                      f"{type(value).__name__} ({value!r})")
            out[name] = value
        else:
            out[name] = [] if name in _LIST_PROPS else default

    out["id"] = tid

    if out["state"] not in TASK_STATES:
        _fail(f"{tid}.state='{out['state']}' hors vocabulaire {TASK_STATES}")
    if out["complexity"] not in COMPLEXITIES:
        _fail(f"{tid}.complexity='{out['complexity']}' hors vocabulaire {COMPLEXITIES}")
    if out["effort_days"] < 0 or out["actual_days"] < 0:
        _fail(f"{tid} : un effort négatif n'a pas de sens")
    if out["retries"] < 0:
        _fail(f"{tid}.retries négatif")

    deps = [str(d).strip() for d in out["depends_on"] if str(d).strip()]
    if tid in deps:
        _fail(f"{tid} dépend d'elle-même")
    if len(set(deps)) != len(deps):
        _fail(f"{tid} : dépendance dupliquée dans {deps}")
    out["depends_on"] = deps
    out["artifacts"] = [str(a) for a in out["artifacts"]]
    out["files"] = [str(f) for f in out["files"]]

    return out


def _coerce_row(row: dict) -> dict:
    """Relit une ligne venue du store (PG ou secours) vers des types Python.

    POURQUOI : Postgres rend `depends_on` en JSONB (déjà décodé par psycopg,
    parfois en str selon le driver) tandis que le secours SQLite rend le blob
    déjà décodé. Sans cette normalisation, `ready()` comparerait une liste à
    une chaîne et déclarerait tout prenable — l'échec serait silencieux.
    """
    out = dict(row)
    out.pop("dist", None)  # colonne calculée éventuelle de deep_semantic
    for key in _LIST_PROPS:
        val = out.get(key)
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except (ValueError, TypeError):
                val = []
        out[key] = list(val) if isinstance(val, (list, tuple)) else []
    for key in ("retries", "est_tokens", "actual_tokens"):
        try:
            out[key] = int(out.get(key) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    for key in ("effort_days", "actual_days", "created_at", "updated_at",
                "started_at", "completed_at"):
        try:
            out[key] = float(out.get(key) or 0.0)
        except (TypeError, ValueError):
            out[key] = 0.0
    for key in ("id", "epic", "title", "state", "complexity", "assignee",
                "session_id", "block_reason", "provenance", "notes"):
        out[key] = str(out.get(key) or "")
    return out


def can_transition(src: str, dst: str) -> bool:
    """La transition d'état `src` → `dst` est-elle autorisée ?"""
    if src not in TASK_STATES or dst not in TASK_STATES:
        return False
    return dst in _TRANSITIONS[src]


# ── Le backlog ────────────────────────────────────────────────────────────────

class Backlog:
    """Backlog persistant. Une instance = une vue sur la table `tasks`.

    Sans état en mémoire volontairement : chaque lecture retourne au store, donc
    deux sessions concurrentes voient la même chose. Le prix est un aller-retour
    par appel ; à l'échelle d'un backlog (centaines de lignes) c'est négligeable,
    et ça évite une classe de bugs de cache incohérent entre sessions.
    """

    #: Fenêtre de lecture. Le secours SQLite filtre en Python sur les
    #: `limit * 4` lignes les plus récentes (cf. `forge_db_fallback.deep_query`) :
    #: filtrer côté store tronquerait silencieusement le backlog. On lit donc
    #: large et on filtre ici.
    SCAN_LIMIT = 5000

    def __init__(self, db: Any = None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            from .forge_db import get_db
            self._db = get_db()
        return self._db

    # ── Écriture ──────────────────────────────────────────────────────────────

    def upsert(self, **fields: Any) -> dict:
        """Crée ou met à jour une tâche. Valide avant d'écrire."""
        row = validate_task(fields)
        now = time.time()
        existing = self.get(row["id"])
        row["created_at"] = existing["created_at"] if existing else now
        row["updated_at"] = now
        self.db.deep_insert(TABLE, row)
        return row

    def upsert_many(self, rows: Iterable[dict]) -> list[dict]:
        """Injection en lot. Valide TOUT le lot avant d'écrire quoi que ce soit.

        Un lot à moitié écrit est pire qu'un lot refusé : il laisse un backlog
        dont on ne sait plus s'il est complet.
        """
        batch = [validate_task(r) for r in rows]
        ids = [r["id"] for r in batch]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            _fail(f"identifiants dupliqués dans le lot : {sorted(dupes)}")
        return [self.upsert(**r) for r in batch]

    def set_state(self, task_id: str, state: str, **extra: Any) -> dict:
        """Change l'état d'une tâche en vérifiant la transition."""
        task = self.require(task_id)
        if state not in TASK_STATES:
            _fail(f"état '{state}' hors vocabulaire {TASK_STATES}")
        if not can_transition(task["state"], state):
            _fail(f"{task_id} : transition interdite {task['state']} → {state} "
                  f"(autorisées : {_TRANSITIONS[task['state']]})")
        payload = {**task, **extra, "state": state}
        return self.upsert(**{k: v for k, v in payload.items() if k in _TASK_PROPS})

    def claim(self, task_id: str, session_id: str, assignee: str = "") -> dict:
        """Prend une tâche. LÈVE si ses dépendances ne sont pas satisfaites.

        C'est le point de rigueur du module : on tolère une dépendance déclarée
        vers une tâche encore inexistante à l'écriture (injection d'un plan),
        mais jamais au moment de travailler dessus.
        """
        task = self.require(task_id)
        if task["state"] == "in_progress" and task["session_id"] not in ("", session_id):
            _fail(f"{task_id} est déjà tenue par la session {task['session_id']}")
        missing = self.unmet_dependencies(task_id)
        if missing:
            _fail(f"{task_id} : dépendances non satisfaites {missing}")
        return self.set_state(task_id, "in_progress",
                              session_id=session_id, assignee=assignee,
                              started_at=time.time())

    def complete(self, task_id: str, actual_days: float = 0.0,
                 actual_tokens: int = 0, artifacts: Optional[list] = None) -> dict:
        """Termine une tâche et enregistre le réel en face de l'estimé (E1-03/E6-01)."""
        task = self.require(task_id)
        return self.set_state(
            task_id, "done",
            actual_days=float(actual_days or task["actual_days"]),
            actual_tokens=int(actual_tokens or task["actual_tokens"]),
            artifacts=list(artifacts if artifacts is not None else task["artifacts"]),
            completed_at=time.time())

    def block(self, task_id: str, reason: str = "") -> dict:
        return self.set_state(task_id, "blocked", block_reason=str(reason))

    def bump_retry(self, task_id: str) -> dict:
        """Incrémente le compteur de reprises (adossé à E1-05)."""
        task = self.require(task_id)
        return self.upsert(**{**task, "retries": task["retries"] + 1})

    # ── Lecture ───────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        rows = self.db.deep_query(TABLE, None, limit=self.SCAN_LIMIT) or []
        return [_coerce_row(r) for r in rows]

    def get(self, task_id: str) -> Optional[dict]:
        for t in self.all():
            if t["id"] == task_id:
                return t
        return None

    def require(self, task_id: str) -> dict:
        task = self.get(task_id)
        if task is None:
            _fail(f"tâche inconnue : '{task_id}'")
        return task  # type: ignore[return-value]

    def by_state(self, state: str) -> list[dict]:
        if state not in TASK_STATES:
            _fail(f"état '{state}' hors vocabulaire {TASK_STATES}")
        return [t for t in self.all() if t["state"] == state]

    def by_epic(self, epic: str) -> list[dict]:
        return [t for t in self.all() if t["epic"] == epic]

    # ── Dépendances ───────────────────────────────────────────────────────────

    def unmet_dependencies(self, task_id: str, tasks: Optional[list] = None) -> list[str]:
        """Dépendances qui empêchent de démarrer `task_id`.

        Une dépendance INCONNUE compte comme non satisfaite : ne pas connaître
        une contrainte n'est pas la même chose que ne pas en avoir.
        """
        tasks = tasks if tasks is not None else self.all()
        index = {t["id"]: t for t in tasks}
        task = index.get(task_id)
        if task is None:
            _fail(f"tâche inconnue : '{task_id}'")
        return [d for d in task["depends_on"]                       # type: ignore[index]
                if index.get(d, {}).get("state") not in ("done", "cancelled")]

    def ready(self) -> list[dict]:
        """Tâches réellement prenables : non terminales et sans dépendance ouverte."""
        tasks = self.all()
        return [t for t in tasks
                if t["state"] in ("pending", "ready")
                and not self.unmet_dependencies(t["id"], tasks)]

    def dependents_of(self, task_id: str) -> list[str]:
        """Tâches que `task_id` débloque (blast radius planning — base d'E1-02)."""
        return sorted(t["id"] for t in self.all() if task_id in t["depends_on"])

    def find_cycles(self, tasks: Optional[list] = None) -> list[list[str]]:
        """Cycles du graphe de dépendances. Vide = DAG sain.

        DFS itérative avec pile explicite : un backlog est déclaratif, rien ne
        garantit sa profondeur, et une récursion nous ferait exploser sur un
        plan mal saisi au lieu de le signaler.
        """
        tasks = tasks if tasks is not None else self.all()
        graph = {t["id"]: [d for d in t["depends_on"] if d in {x["id"] for x in tasks}]
                 for t in tasks}
        cycles: list[list[str]] = []
        seen: set[str] = set()

        for root in sorted(graph):
            if root in seen:
                continue
            stack: list[tuple[str, list[str]]] = [(root, [root])]
            while stack:
                node, path = stack.pop()
                seen.add(node)
                for dep in graph.get(node, []):
                    if dep in path:
                        cycle = path[path.index(dep):] + [dep]
                        if cycle not in cycles:
                            cycles.append(cycle)
                        continue
                    stack.append((dep, path + [dep]))
        return cycles

    def validate(self) -> dict:
        """Diagnostic du backlog. Ne lève pas : c'est un rapport, pas un garde-fou."""
        tasks = self.all()
        ids = {t["id"] for t in tasks}
        dangling = sorted({(t["id"], d) for t in tasks
                           for d in t["depends_on"] if d not in ids})
        return {
            "tasks": len(tasks),
            "cycles": self.find_cycles(tasks),
            "dangling_dependencies": [list(x) for x in dangling],
            "ready": sorted(t["id"] for t in self.ready()),
            "by_state": {s: sum(1 for t in tasks if t["state"] == s)
                         for s in TASK_STATES},
        }

    # ── Ordonnancement / chemin critique (E1-02) ──────────────────────────────

    def _dag(self, tasks: list[dict]) -> tuple[dict, dict, dict]:
        """Index, prédécesseurs, successeurs — restreints aux tâches CONNUES.

        Une dépendance orpheline est exclue du graphe : elle n'a ni durée ni
        position, l'ordonnancer serait inventer. Elle reste signalée par
        `validate()` et bloque toujours `claim()`. L'ignorer *ici* est correct ;
        l'ignorer partout ne le serait pas.
        """
        index = {t["id"]: t for t in tasks}
        preds = {i: [d for d in index[i]["depends_on"] if d in index] for i in index}
        succs: dict[str, list[str]] = {i: [] for i in index}
        for i, deps in preds.items():
            for d in deps:
                succs[d].append(i)
        return index, preds, succs

    def topological_order(self, tasks: Optional[list] = None) -> list[str]:
        """Ordre de réalisation possible (Kahn). LÈVE s'il existe un cycle.

        Déterministe : à contrainte égale on sort les identifiants dans l'ordre,
        pour que deux exécutions donnent le même plan.
        """
        tasks = tasks if tasks is not None else self.all()
        index, preds, succs = self._dag(tasks)
        indegree = {i: len(preds[i]) for i in index}
        queue = sorted(i for i, n in indegree.items() if n == 0)
        order: list[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for s in succs[node]:
                indegree[s] -= 1
                if indegree[s] == 0:
                    queue.append(s)
            queue.sort()
        if len(order) != len(index):
            _fail(f"cycle de dépendances — ordonnancement impossible : "
                  f"{self.find_cycles(tasks)}")
        return order

    def critical_path(self, remaining: bool = False) -> dict:
        """Chemin critique (CPM) pondéré par `effort_days`.

        `remaining=False` (défaut) : le plan TEL QUE CONÇU — comparable au total
        annoncé par l'audit. `remaining=True` : les tâches terminées pèsent 0,
        c'est-à-dire ce qu'il reste vraiment à faire.

        La marge (`slack`) est ce qui rend ce calcul utile : une tâche à marge
        nulle repousse la livraison d'autant qu'elle glisse ; une tâche à marge
        de 20 jours peut attendre. Sans ça, « 139 jours » ne dit pas dans quel
        ordre les dépenser.
        """
        tasks = self.all()
        if not tasks:
            return {"duration_days": 0.0, "path": [], "critical": [], "schedule": {}}

        index, preds, succs = self._dag(tasks)
        order = self.topological_order(tasks)

        def duration(i: str) -> float:
            if remaining and index[i]["state"] in TERMINAL_STATES:
                return 0.0
            return float(index[i]["effort_days"])

        early_start, early_finish = {}, {}
        for i in order:
            early_start[i] = max((early_finish[p] for p in preds[i]), default=0.0)
            early_finish[i] = early_start[i] + duration(i)
        total = max(early_finish.values(), default=0.0)

        late_finish, late_start = {}, {}
        for i in reversed(order):
            late_finish[i] = min((late_start[s] for s in succs[i]), default=total)
            late_start[i] = late_finish[i] - duration(i)

        slack = {i: round(late_start[i] - early_start[i], 6) for i in index}
        critical = sorted(i for i in index if slack[i] <= 1e-9)

        # Une chaîne effectivement la plus longue : on remonte les prédécesseurs
        # « contraignants », ceux dont la fin au plus tôt fixe le début.
        ends = [i for i in order if abs(early_finish[i] - total) <= 1e-9]
        path: list[str] = []
        node = ends[-1] if ends else None
        while node:
            path.append(node)
            binding = [p for p in preds[node]
                       if abs(early_finish[p] - early_start[node]) <= 1e-9]
            node = sorted(binding)[0] if binding else None
        path.reverse()

        return {
            "duration_days": round(total, 2),
            "path": path,
            "critical": critical,
            "schedule": {i: {"early_start": round(early_start[i], 2),
                             "early_finish": round(early_finish[i], 2),
                             "late_start": round(late_start[i], 2),
                             "late_finish": round(late_finish[i], 2),
                             "slack": slack[i]} for i in sorted(index)},
        }

    def conflicts(self, task_id: str) -> dict:
        """Ce qui empêche de démarrer `task_id` maintenant.

        Remplace `kanban.check_conflicts`, qui ne regardait QUE le chevauchement
        de fichiers. Un chevauchement de fichiers est un conflit d'ÉCRITURE
        (deux sessions vont se marcher dessus) ; une dépendance ouverte est un
        conflit d'ORDRE (le travail n'a pas de sens encore). Les deux bloquent,
        pour des raisons différentes, et le premier ne dit rien du second —
        c'est précisément ce que la version fichier-only laissait passer.
        """
        tasks = self.all()
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task is None:
            _fail(f"tâche inconnue : '{task_id}'")
        files = set(task["files"])                       # type: ignore[index]
        overlaps = [
            {"task": t["id"], "session": t["session_id"],
             "files": sorted(files & set(t["files"]))}
            for t in tasks
            if t["id"] != task_id and t["state"] == "in_progress" and files & set(t["files"])
        ]
        unmet = self.unmet_dependencies(task_id, tasks)
        return {
            "task": task_id,
            "state": task["state"],                      # type: ignore[index]
            "blocked": bool(overlaps or unmet),
            "unmet_dependencies": unmet,
            "file_overlaps": overlaps,
        }

    # ── Estimation auto (E1-03) ─────────────────────────────────────────────────

    #: Mapping complexité → effort par défaut (jours). Sera ajusté par l'historique.
    _DEFAULT_EFFORT: dict[str, float] = {"S": 0.5, "M": 1.0, "H": 3.0}

    #: Tokens par jour (mesuré : ~48 500 tok de travail utile par session de 65K,
    #: mais les sessions RPG ont overhead moindre car pas de system prompt Forge).
    _TOKENS_PER_DAY = 48_500

    def calibration_stats(self) -> dict:
        """Analyse les tâches terminées pour calibrer les futures estimations.

        Retourne un ratio `actual/estimated` par complexité. Ratio > 1 = on
        sous-estime (il faut gonfler), ratio < 1 = on sur-estime.
        Sans historique suffisant, retourne 1.0 (pas de correction).
        """
        done = [t for t in self.all()
                if t["state"] in TERMINAL_STATES
                and t["effort_days"] > 0
                and t["actual_days"] > 0]
        if len(done) < 3:
            return {"ratios": {c: 1.0 for c in COMPLEXITIES},
                    "sample_size": len(done), "calibrated": False}

        ratios: dict[str, list[float]] = {c: [] for c in COMPLEXITIES}
        for t in done:
            ratios[t["complexity"]].append(t["actual_days"] / t["effort_days"])

        result: dict[str, float] = {}
        for c in COMPLEXITIES:
            vals = ratios[c]
            if len(vals) >= 2:
                # Médiane (robuste aux outliers) bornée à [0.3, 5.0]
                vals.sort()
                mid = vals[len(vals) // 2]
                result[c] = max(0.3, min(5.0, mid))
            else:
                result[c] = 1.0

        return {"ratios": result, "sample_size": len(done), "calibrated": True}

    def auto_estimate(self, task_row: dict) -> dict:
        """Estime `est_tokens` et `effort_days` si non fournis.

        Trois sources, par priorité décroissante :
        1. Valeurs explicites dans `task_row` (l'humain/agent a décidé).
        2. Ratio historique `actual/estimated` par complexité (E1-03).
        3. Mapping par défaut complexité → jours.

        `est_tokens` est dérivé de `effort_days` × `_TOKENS_PER_DAY` ou, si la
        description est fournie, via `estimate_task_tokens()` du décomposeur.

        Ne lève pas : c'est une estimation, pas un garde-fou. Retourne une copie
        enrichie de `task_row`.
        """
        out = dict(task_row)
        complexity = out.get("complexity", "M")
        if complexity not in COMPLEXITIES:
            complexity = "M"

        # ── effort_days ──
        has_explicit_effort = out.get("effort_days") and float(out["effort_days"]) > 0
        if not has_explicit_effort:
            base = self._DEFAULT_EFFORT.get(complexity, 1.0)
            cal = self.calibration_stats()
            ratio = cal["ratios"].get(complexity, 1.0)
            out["effort_days"] = round(base * ratio, 2)

        # ── est_tokens ──
        has_explicit_tokens = out.get("est_tokens") and int(out["est_tokens"]) > 0
        if not has_explicit_tokens:
            desc = out.get("title", "") + " " + out.get("notes", "")
            num_files = len(out.get("files", []))
            # Estimation tokens depuis la description
            desc_tokens = self._estimate_tokens_from_desc(desc, num_files)
            # Ou dérivé des jours si déjà estimés
            days_tokens = int(float(out["effort_days"]) * self._TOKENS_PER_DAY)
            out["est_tokens"] = max(desc_tokens, days_tokens)

        return out

    @staticmethod
    def _estimate_tokens_from_desc(description: str, num_files: int = 0) -> int:
        """Estimation locale des tokens (reprend la calibration de decomposer.py)."""
        CHARS_PER_TOKEN = 4
        TOOL_OVERHEAD_PER_FILE = 500
        DEBUG_OVERHEAD = 11_500
        DISPATCH_OVERHEAD = 3_300
        base = len(description) // CHARS_PER_TOKEN
        file_tokens = num_files * TOOL_OVERHEAD_PER_FILE
        return base + file_tokens + DEBUG_OVERHEAD + DISPATCH_OVERHEAD

    def bulk_estimate(self, task_ids: Optional[list[str]] = None) -> dict:
        """Applique `auto_estimate` à plusieurs tâches et persiste.

        `task_ids=None` → toutes les tâches non terminées sans estimation.
        Retourne un résumé des estimations appliquées.
        """
        tasks = self.all()
        if task_ids is not None:
            tasks = [t for t in tasks if t["id"] in task_ids]
        else:
            # Cible : pending/ready sans estimation
            tasks = [t for t in tasks
                     if t["state"] in ("pending", "ready")
                     and (t["effort_days"] <= 0 or t["est_tokens"] <= 0)]

        applied = []
        for t in tasks:
            est = self.auto_estimate(t)
            self.upsert(**est)
            applied.append({
                "id": t["id"],
                "effort_days": est["effort_days"],
                "est_tokens": est["est_tokens"],
            })
        return {"estimated": len(applied), "tasks": applied,
                "calibration": self.calibration_stats()}

    def estimation_report(self) -> dict:
        """Rapport de précision des estimations (pour E6-01)."""
        done = [t for t in self.all()
                if t["state"] in TERMINAL_STATES
                and t["effort_days"] > 0
                and t["actual_days"] > 0]
        if not done:
            return {"completed_with_data": 0, "message": "Aucune tâche terminée avec estimations ET réel"}

        diffs = []
        for t in done:
            ratio = t["actual_days"] / t["effort_days"] if t["effort_days"] else 0
            diffs.append({
                "id": t["id"], "epic": t["epic"],
                "est": t["effort_days"], "actual": t["actual_days"],
                "ratio": round(ratio, 2),
                "est_tokens": t["est_tokens"], "actual_tokens": t["actual_tokens"],
            })

        ratios = [d["ratio"] for d in diffs]
        avg_ratio = sum(ratios) / len(ratios)
        return {
            "completed_with_data": len(diffs),
            "avg_ratio": round(avg_ratio, 2),
            "bias": "sous-estimation" if avg_ratio > 1.15 else "sur-estimation" if avg_ratio < 0.85 else "calibré",
            "tasks": sorted(diffs, key=lambda x: x["id"]),
            "calibration": self.calibration_stats(),
        }

    # ── Réaffectation sur échec (E1-05) ───────────────────────────────────────

    #: Nombre maximum de tentatives avant escalation.
    MAX_RETRIES: int = 3

    def fail_task(self, task_id: str, error: str = "") -> dict:
        """Enregistre un échec : incrémente retries, passe en 'pending' ou 'blocked'.

        Politique :
        - retries < MAX_RETRIES → retour à 'pending' (reprise possible).
        - retries >= MAX_RETRIES → 'blocked' + escalation explicite.
        Retourne le diagnostic de réaffectation.
        """
        task = self.require(task_id)
        self.bump_retry(task_id)
        task = self.require(task_id)  # re-read après bump

        if task["retries"] >= self.MAX_RETRIES:
            self.block(task_id, reason=f"MAX_RETRIES ({self.MAX_RETRIES}) atteint après: {error}")
            return {
                "task_id": task_id,
                "action": "escalated",
                "retries": task["retries"],
                "error": error,
                "recommendation": "Escalade humaine requise — tâche bloquée après "
                                  f"{task['retries']} tentatives",
            }

        # Retour à pending pour reprise
        self.set_state(task_id, "pending")
        return {
            "task_id": task_id,
            "action": "retry",
            "retries": task["retries"],
            "error": error,
            "recommendation": f"Reprise possible ({task['retries']}/{self.MAX_RETRIES})",
        }

    def reassign(self, task_id: str, new_session: str,
                 new_assignee: str = "") -> dict:
        """Réaffecte une tâche à une autre session/agent.

        La tâche doit être en 'in_progress', 'blocked' ou 'pending'.
        Enregistre l'ancien assignee dans `notes` pour traçabilité.
        """
        task = self.require(task_id)
        old_assignee = task["assignee"]
        old_session = task["session_id"]

        # Transition vers 'ready' puis re-claim
        if task["state"] in ("in_progress", "blocked"):
            self.set_state(task_id, "ready")

        note = (f"réaffecté de {old_session}/{old_assignee} "
                f"→ {new_session}/{new_assignee}")
        existing_notes = task["notes"]
        combined = f"{existing_notes}\n{note}" if existing_notes else note

        return self.set_state(
            task_id, "in_progress",
            session_id=new_session,
            assignee=new_assignee,
            started_at=time.time(),
            notes=combined.strip(),
        )

    def auto_handle_failure(self, task_id: str, error: str = "",
                            candidate_sessions: Optional[list[str]] = None) -> dict:
        """Gestion automatique d'un échec : retry, réaffectation, ou escalation.

        Pipeline :
        1. `fail_task()` → incrémente retries.
        2. Si retry possible et `candidate_sessions` fourni → réaffecte au
           premier candidat (autre que la session qui a échoué).
        3. Si MAX_RETRIES atteint → escalade (blocked + raison).

        `candidate_sessions` : liste de sessions/agents disponibles. Si None,
        la tâche retourne simplement en 'pending' pour reprise manuelle.
        """
        fail_result = self.fail_task(task_id, error)

        if fail_result["action"] == "escalated":
            return fail_result

        # Re-assignment possible ?
        if candidate_sessions:
            task = self.require(task_id)
            failed_session = task["session_id"]
            for candidate in candidate_sessions:
                if candidate != failed_session:
                    reassign_result = self.reassign(task_id, candidate)
                    fail_result["action"] = "reassigned"
                    fail_result["new_session"] = candidate
                    fail_result["task"] = reassign_result
                    return fail_result

        return fail_result

    def blocked_report(self) -> dict:
        """Liste les tâches bloquées avec leur raison — pour monitoring."""
        blocked = self.by_state("blocked")
        return {
            "count": len(blocked),
            "tasks": [{
                "id": t["id"],
                "epic": t["epic"],
                "title": t["title"],
                "retries": t["retries"],
                "block_reason": t["block_reason"],
                "session_id": t["session_id"],
            } for t in blocked],
        }

    # ── Vues ──────────────────────────────────────────────────────────────────

    def epic_summary(self) -> dict[str, dict]:
        """Avancement par epic : jours estimés/réels et compte par état."""
        out: dict[str, dict] = {}
        for t in self.all():
            e = out.setdefault(t["epic"] or "?", {
                "tasks": 0, "done": 0, "effort_days": 0.0, "actual_days": 0.0})
            e["tasks"] += 1
            e["done"] += 1 if t["state"] == "done" else 0
            e["effort_days"] += t["effort_days"]
            e["actual_days"] += t["actual_days"]
        for e in out.values():
            e["pct_done"] = round(100 * e["done"] / e["tasks"], 1) if e["tasks"] else 0.0
        return dict(sorted(out.items()))

    def to_kanban_board(self, parent_task: str = "Backlog Forge") -> dict:
        """Projette le backlog au format lu par `00_CORE/forge_dispatch/kanban.py`.

        Le kanban attend `id`/`name`/`status`/`files`. Les champs propres au
        backlog (epic, dépendances, effort) sont conservés en plus : `kanban.py`
        les ignore, la console E1-06 les lira.
        """
        tasks = self.all()
        return {
            "version": 1,
            "parent_task": parent_task,
            "generated_from": "forge_backlog (table `tasks`)",
            "total_est_days": round(sum(t["effort_days"] for t in tasks), 1),
            "tasks": [{
                "id": t["id"],
                "name": t["title"],
                "status": "pending" if t["state"] == "ready" else t["state"],
                "assigned_session": t["session_id"] or None,
                "files": t["files"],
                "epic": t["epic"],
                "depends_on": t["depends_on"],
                "effort_days": t["effort_days"],
                "complexity": t["complexity"],
            } for t in sorted(tasks, key=lambda x: x["id"])],
        }

    def render(self) -> str:
        """Rendu texte compact (lisible en session, ~1 ligne par epic)."""
        rep = self.validate()
        lines = [f"Backlog — {rep['tasks']} tâches | "
                 + " ".join(f"{k}:{v}" for k, v in rep["by_state"].items() if v)]
        for epic, e in self.epic_summary().items():
            lines.append(f"  {epic:<4} {e['done']:>2}/{e['tasks']:<3} "
                         f"{e['pct_done']:>5.1f}%  {e['effort_days']:>5.1f} j estimés")
        if rep["cycles"]:
            lines.append(f"  ⚠️ CYCLES : {rep['cycles']}")
        else:
            # `render` ne doit jamais lever : le chemin critique n'est calculable
            # que sur un DAG sain, et l'absence de cycle vient d'être vérifiée.
            cp = self.critical_path(remaining=True)
            lines.append(f"  chemin critique restant : {cp['duration_days']:.0f} j "
                         f"({len(cp['path'])} tickets) → {' → '.join(cp['path'][:6])}"
                         + (" …" if len(cp["path"]) > 6 else ""))
        if rep["dangling_dependencies"]:
            lines.append(f"  ⚠️ dépendances orphelines : {len(rep['dangling_dependencies'])}")
        return "\n".join(lines)

    # ── Reprise multi-sessions (E1-07) ────────────────────────────────────────

    def resume_brief(self, session_id: str = "") -> dict:
        """Génère un brief de reprise pour une nouvelle session.

        Le brief contient :
        1. L'état global du backlog (validation + chemin critique).
        2. Les tâches en cours (tenues par `session_id` ou toutes si vide).
        3. Les tâches prêtes à prendre.
        4. Les tâches bloquées avec leur raison.
        5. Le prochain ticket recommandé (premier `ready` par ordre topologique).

        Conçu pour être consommé comme contexte de session par un agent qui
        reprend le travail après un redémarrage ou un changement de fenêtre.
        """
        tasks = self.all()
        rep = self.validate()
        cp = self.critical_path(remaining=True)

        # En cours — par session ou toutes
        in_progress = [t for t in tasks if t["state"] == "in_progress"]
        if session_id:
            my_tasks = [t for t in in_progress if t["session_id"] == session_id]
        else:
            my_tasks = in_progress

        # Prêtes
        ready = self.ready()

        # Bloquées
        blocked = [t for t in tasks if t["state"] == "blocked"]

        # Prochain recommandé : premier ready dans l'ordre topologique
        next_task = None
        if ready:
            try:
                topo = self.topological_order(ready)
                if topo:
                    next_task = topo[0]
            except ValueError:
                next_task = ready[0]["id"]

        # Épics
        epics = self.epic_summary()

        return {
            "generated_at": time.time(),
            "session_id": session_id,
            "backlog": {
                "total": rep["tasks"],
                "by_state": rep["by_state"],
                "cycles": rep["cycles"],
            },
            "critical_path": {
                "remaining_days": cp["duration_days"],
                "path": cp["path"][:10],
            },
            "my_tasks": [{
                "id": t["id"], "epic": t["epic"], "title": t["title"],
                "effort_days": t["effort_days"],
                "depends_on": t["depends_on"],
            } for t in my_tasks],
            "ready": [{
                "id": t["id"], "epic": t["epic"], "title": t["title"],
                "effort_days": t["effort_days"],
                "depends_on": t["depends_on"],
            } for t in ready[:20]],
            "blocked": [{
                "id": t["id"], "epic": t["epic"], "title": t["title"],
                "block_reason": t["block_reason"], "retries": t["retries"],
            } for t in blocked],
            "next_task": next_task,
            "epic_progress": {e: f"{d['done']}/{d['tasks']}"
                              for e, d in epics.items()},
        }

    def resume_brief_text(self, session_id: str = "") -> str:
        """Rendu texte du brief de reprise (pour injection dans un prompt)."""
        brief = self.resume_brief(session_id)
        lines = [
            "═══ REPRISE PROJET ═══",
            f"Backlog : {brief['backlog']['total']} tâches | "
            + " ".join(f"{k}:{v}" for k, v in brief["backlog"]["by_state"].items() if v),
            f"Chemin critique restant : {brief['critical_path']['remaining_days']:.0f}j",
        ]

        if brief["my_tasks"]:
            lines.append(f"\n── Tes tâches en cours ({len(brief['my_tasks'])}) ──")
            for t in brief["my_tasks"]:
                deps = f" → dépend de {t['depends_on']}" if t["depends_on"] else ""
                lines.append(f"  {t['id']} [{t['epic']}] {t['title']} ({t['effort_days']}j){deps}")

        if brief["ready"]:
            lines.append(f"\n── Tâches prêtes ({len(brief['ready'])}) ──")
            for t in brief["ready"]:
                lines.append(f"  {t['id']} [{t['epic']}] {t['title']} ({t['effort_days']}j)")

        if brief["blocked"]:
            lines.append(f"\n── Bloquées ({len(brief['blocked'])}) ──")
            for t in brief["blocked"]:
                lines.append(f"  🚫 {t['id']} [{t['epic']}] {t['title']}: {t['block_reason']}")

        if brief["next_task"]:
            lines.append(f"\n→ PROCHAIN TICKET RECOMMANDÉ : {brief['next_task']}")

        lines.append(f"\n── Progression par epic ──")
        for e, pct in brief["epic_progress"].items():
            lines.append(f"  {e}: {pct}")

        return "\n".join(lines)


_backlog: Optional[Backlog] = None


def get_backlog() -> Backlog:
    """Singleton (même convention que `get_db` / `get_world_kg`)."""
    global _backlog
    if _backlog is None:
        _backlog = Backlog()
    return _backlog


if __name__ == "__main__":  # auto-test du schéma, sans base
    print(table_ddl())
    print()
    probe = validate_task({"id": "E1-01", "epic": "E1", "title": "Schéma Task",
                           "complexity": "M", "effort_days": 2})
    print(f"validate_task OK — {len(probe)} propriétés, state={probe['state']}")
    print(f"états={TASK_STATES}")
    print(f"transitions depuis in_progress → {_TRANSITIONS['in_progress']}")
    # E1-03 : test estimation auto (sans base, mode "dry")
    print()
    bl = Backlog.__new__(Backlog)
    bl._db = None  # pas de base — on teste les méthodes pures
    est = bl.auto_estimate({"id": "E1-02", "epic": "E1", "title": "DAG de dépendances",
                            "complexity": "H"})
    print(f"auto_estimate(E1-02, H) → effort={est['effort_days']}j, tokens={est['est_tokens']}")
    est_s = bl.auto_estimate({"id": "TEST-S", "epic": "T", "title": "Small task",
                              "complexity": "S"})
    print(f"auto_estimate(TEST-S, S) → effort={est_s['effort_days']}j, tokens={est_s['est_tokens']}")
    print(f"calibration_stats → {bl.calibration_stats()}")
