"""
forge_task_ledger.py — Mesure unifiée PAR TÂCHE (ticket E6-01)
==============================================================
Le backlog (`forge_backlog`, E1-01) sait ce qui était *estimé*. Il ne savait rien
du *réel* : `actual_days` et `actual_tokens` restaient à zéro parce que rien ne
les remplissait. Ce module est ce quelque chose.

CE QU'IL N'EST PAS
------------------
**Ce n'est pas un nouveau système de métriques.** `forge_metrics` enregistre déjà
l'événement (provider, modèle, tokens_in/out, coût, latence, ok/erreur) et
`agent_tracker` enregistre déjà l'invocation d'agent (score, outils, durée). Les
réécrire aurait produit un troisième chiffre divergent. Ce module ajoute la seule
couche qui manquait : **l'agrégation par ticket du backlog, et le retour vers le
backlog**. Un événement porte désormais `task_id` (`MetricRecord.task_id`) ; tout
le reste est de la somme.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.forge_task_ledger import task_run

    with task_run("E6-01", session="ma-session") as run:
        ...                                  # le travail
        run.artifact("00_CORE/forge_agents/forge_task_ledger.py")

À la sortie : durée mesurée, tokens et coût agrégés depuis `forge_metrics` pour
ce `task_id`, succès/échec déduit de l'exception, artefacts enregistrés — puis
`complete()` ou `block()` sur le backlog. Rien à saisir à la main.

TROIS DÉCISIONS
---------------
1. **La durée mesurée est du temps d'horloge, convertie en jours-Forge par
   `HOURS_PER_DAY`.** Un « jour-Forge » de l'audit n'est pas 24 h ; le facteur est
   explicite et configurable (`FORGE_HOURS_PER_DAY`) plutôt que caché dans une
   division. Sans ça, comparer `actual_days` à `effort_days` n'a aucun sens.
2. **Un échec n'écrase pas l'estimation, il incrémente `retries` et bloque.** Une
   tâche qui a planté a quand même consommé du temps et des tokens : ils sont
   enregistrés. Perdre la mesure d'un échec, c'est perdre exactement la donnée
   dont E1-03 a besoin pour apprendre que ce type de tâche dérape.
3. **Le score qualité est PORTÉ, pas CALCULÉ ICI.** Aucune formule maison dans
   ce module : la normalisation 0-100 par type d'artefact est le ticket E6-02
   (`artifact_quality.py`), branché en option — `task_run(..., autoscore=True)`
   note les artefacts déclarés. Sans ce drapeau, et sans `quality=` explicite,
   le champ reste `None` : un trou visible plutôt qu'un chiffre inventé.

Vérification : `python -m forge_agents.forge_task_ledger`
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

#: Un « jour-Forge » de l'audit ≈ une journée de travail, pas 24 h.
HOURS_PER_DAY: float = float(os.environ.get("FORGE_HOURS_PER_DAY", "8"))

#: `kind` des événements émis par ce module (les autres restent llm/rag/kag/...).
KIND = "task"


def _metrics():
    from . import forge_metrics
    return forge_metrics


def _backlog():
    from .forge_backlog import get_backlog
    return get_backlog()


def _score_artifacts(paths: list[str], world_id: str = ""
                     ) -> tuple[Optional[float], dict]:
    """Note les artefacts déclarés via E6-02 — `(score, détail)`, `(None, {})`
    si rien n'est notable ou si le module est indisponible.

    Import paresseux : le ledger ne dépend pas du scoreur pour enregistrer une
    durée. Et un scoreur en panne rend le champ VIDE, jamais 0 — un zéro
    inventé condamnerait un livrable qu'on n'a pas su mesurer.
    """
    try:
        from .artifact_quality import score_artifacts
        result = score_artifacts(paths, world_id)
    except Exception as exc:  # noqa: BLE001
        return None, {"error": f"{type(exc).__name__}: {exc}"[:120]}
    if result["score"] is None:
        return None, {"scored": 0, "unscored": result["unscored"][:20]}
    return result["score"], {"grade": result["grade"],
                             "confidence": result["confidence"],
                             "scored": result["scored"],
                             "artifacts": result["artifacts"],
                             "by_kind": result["by_kind"],
                             "unscored": result["unscored"][:20]}


# ── Agrégation ────────────────────────────────────────────────────────────────

def events_for(task_id: str, since_ts: float = 0.0, limit: int = 20000) -> list[dict]:
    """Événements `forge_metrics` portant ce `task_id`.

    Les lignes écrites avant E6-01 n'ont pas le champ : elles sont simplement
    absentes du résultat, jamais comptées à tort dans une autre tâche.
    """
    return [e for e in _metrics().load_records(limit=limit, since_ts=since_ts)
            if e.get("task_id") == task_id]


def aggregate(task_id: str, since_ts: float = 0.0) -> dict:
    """Le relevé unifié d'un ticket : durée, tokens, coût, modèles, échecs.

    Somme des événements, sans re-mesurer : la source de vérité reste le ledger
    `forge_metrics`. Deux appels donnent le même résultat.
    """
    events = events_for(task_id, since_ts)
    work = [e for e in events if e.get("kind") != KIND]        # le travail
    runs = [e for e in events if e.get("kind") == KIND]        # les passages

    tokens_in = sum(int(e.get("tokens_in") or 0) for e in events)
    tokens_out = sum(int(e.get("tokens_out") or 0) for e in events)
    latency = sum(int(e.get("latency_ms") or 0) for e in runs) or \
        sum(int(e.get("latency_ms") or 0) for e in events)
    models = sorted({e.get("model") or "" for e in work} - {""})
    providers = sorted({e.get("provider") or "" for e in work} - {""})
    failures = [e for e in events if e.get("ok") is False]
    qualities = [e["meta"]["quality"] for e in events
                 if isinstance(e.get("meta"), dict)
                 and isinstance(e["meta"].get("quality"), (int, float))]

    return {
        "task_id": task_id,
        "events": len(events),
        "runs": len(runs),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "cost_usd": round(sum(float(e.get("cost_usd") or 0.0) for e in events), 6),
        "duration_ms": latency,
        "duration_days": round(latency / 1000 / 3600 / HOURS_PER_DAY, 4),
        "models": models,
        "providers": providers,
        "ok": not failures,
        "failures": len(failures),
        "errors": [e.get("error", "") for e in failures if e.get("error")][:5],
        # E6-02 remplira ceci ; tant qu'il n'existe pas, le trou est visible.
        "quality": round(sum(qualities) / len(qualities), 2) if qualities else None,
    }


def sync_backlog(task_id: str) -> dict:
    """Reporte le mesuré dans le backlog (`actual_days`, `actual_tokens`).

    **AFFECTE, n'additionne pas.** L'agrégat porte déjà TOUS les événements du
    ticket : additionner à ce qui est en base compterait deux fois dès le second
    passage. Écrire la somme totale rend l'opération idempotente — on peut
    resynchroniser autant qu'on veut. (Un `+=` sur fenêtre temporelle a été
    essayé puis retiré : les fenêtres se chevauchaient, un test l'a attrapé.)

    N'invente rien : sans événement enregistré, les champs restent à zéro. Un
    zéro qui vient d'une absence de mesure est honnête ; un chiffre plausible
    ne le serait pas.
    """
    agg = aggregate(task_id)
    bl = _backlog()
    task = bl.require(task_id)
    if agg["events"]:
        bl.upsert(**{**task,
                     "actual_days": agg["duration_days"],
                     "actual_tokens": agg["tokens_total"]})
    return agg


def claimed_start(task_id: str) -> float:
    """Horodatage (epoch) auquel la tâche a été PRISE, ou 0.0 si jamais prise.

    `claim()` écrit déjà `started_at` en base depuis E1-01 ; personne ne le
    relisait. C'est ce qui manquait pour mesurer un ticket qui ne tient pas dans
    un seul processus :

        with task_run("E2-06", claim=False,
                      started_at=claimed_start("E2-06")) as run:
            run.artifact(...)

    Renvoie 0.0 plutôt que `time.time()` quand la tâche n'a pas été prise :
    `task_run` retombe alors sur `perf_counter()`, et une mesure absente reste
    une mesure absente — jamais une durée nulle déguisée en mesure.
    """
    return float(_backlog().require(task_id).get("started_at") or 0.0)


def variance(task_id: str) -> dict:
    """Écart estimé / réel — la matière première d'E1-03 (estimation apprenante)."""
    t = _backlog().require(task_id)
    est, real = float(t["effort_days"]), float(t["actual_days"])
    return {
        "task_id": task_id,
        "effort_days": est,
        "actual_days": real,
        # « mesuré » ≠ « a duré des jours » : une tâche courte mesure 0,0 jour et
        # reste parfaitement mesurée. Se fier au seul `actual_days` classerait
        # tout travail de moins d'une minute comme non mesuré.
        "measured": real > 0 or int(t["actual_tokens"]) > 0,
        "variance_days": round(real - est, 4),
        "variance_pct": round(100 * (real - est) / est, 1) if est else None,
    }


def epic_costs() -> dict[str, dict]:
    """Coût et tokens par epic — la base du dashboard E6-03."""
    out: dict[str, dict] = {}
    for t in _backlog().all():
        agg = aggregate(t["id"])
        e = out.setdefault(t["epic"] or "?", {
            "tasks": 0, "measured": 0, "cost_usd": 0.0, "tokens": 0, "failures": 0})
        e["tasks"] += 1
        e["measured"] += 1 if agg["events"] else 0
        e["cost_usd"] = round(e["cost_usd"] + agg["cost_usd"], 6)
        e["tokens"] += agg["tokens_total"]
        e["failures"] += agg["failures"]
    return dict(sorted(out.items()))


def coverage() -> dict:
    """Quelle part du backlog est réellement MESURÉE.

    Le chiffre qui dit si ce module sert à quelque chose. Un backlog à 0 % de
    couverture rend E1-03 (estimation apprenante) inopérant, quel que soit le
    soin mis à l'écrire.
    """
    tasks = _backlog().all()
    done = [t for t in tasks if t["state"] == "done"]
    measured = [t for t in done if t["actual_days"] > 0 or t["actual_tokens"] > 0]
    return {
        "tasks": len(tasks),
        "done": len(done),
        "done_measured": len(measured),
        "pct_done_measured": round(100 * len(measured) / len(done), 1) if done else 0.0,
        "unmeasured": sorted(t["id"] for t in done if t not in measured),
    }


# ── Enregistrement d'un passage ───────────────────────────────────────────────

class task_run:
    """Context manager : mesure un passage de travail sur un ticket du backlog.

        with task_run("E6-01", session="s") as run:
            run.artifact("chemin/produit.py")

    À l'entrée : `claim()` sur le backlog (donc LÈVE si une dépendance est
    ouverte — on ne mesure pas un travail qui n'aurait pas dû commencer).
    À la sortie : émet l'événement, agrège, reporte dans le backlog, puis
    `complete()` si tout s'est bien passé, `block()` + `bump_retry()` sinon.
    """

    def __init__(self, task_id: str, session: str = "", assignee: str = "",
                 claim: bool = True, complete: bool = True,
                 quality: Optional[float] = None,
                 started_at: Optional[float] = None,
                 autoscore: bool = False, world_id: str = "", **meta: Any):
        self.task_id = task_id
        self.session = session or f"run-{int(time.time())}"
        self.assignee = assignee
        self._claim = claim
        self._complete = complete
        self.quality = quality
        # E6-02 : `quality` restait vide faute de formule. `autoscore=True` la
        # fait CALCULER depuis les artefacts déclarés (`artifact_quality`), sans
        # rien changer par défaut — un score fourni à la main n'est jamais
        # écrasé, et un lot non notable laisse le champ vide plutôt qu'à 0.
        self.autoscore = autoscore
        self.world_id = world_id
        # Un ticket réel s'étale sur des heures, des dizaines d'appels et
        # plusieurs processus : `perf_counter()` ne mesure que le dernier bloc
        # `with`, soit une durée juste mais SANS RAPPORT avec le ticket. C'est
        # la raison mécanique pour laquelle `coverage()` est resté à 0 % sur
        # cinq tickets. Fourni — typiquement `claimed_start(task_id)` —
        # `started_at` fait mesurer le temps d'horloge depuis la PRISE réelle.
        self.started_at = float(started_at) if started_at else 0.0
        self.meta = dict(meta)
        self.artifacts: list[str] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.ok = True
        self.error = ""
        self._t0 = 0.0
        self._since = 0.0
        self.aggregate: dict = {}

    def artifact(self, *paths: str) -> "task_run":
        """Déclare un artefact produit. Chaînable."""
        for p in paths:
            if p and p not in self.artifacts:
                self.artifacts.append(str(p))
        return self

    def __enter__(self) -> "task_run":
        self._t0 = time.perf_counter()
        self._since = time.time()
        if self._claim:
            _backlog().claim(self.task_id, self.session, self.assignee)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        latency = int(((time.time() - self.started_at) if self.started_at
                       else (time.perf_counter() - self._t0)) * 1000)
        self.ok = exc is None
        if exc is not None:
            self.error = f"{exc_type.__name__}: {exc}"

        meta = dict(self.meta)
        meta["artifacts"] = list(self.artifacts)
        if self.quality is None and self.autoscore and self.artifacts:
            self.quality, quality_detail = _score_artifacts(self.artifacts,
                                                            self.world_id)
            if quality_detail:
                meta["quality_detail"] = quality_detail
        if self.quality is not None:
            meta["quality"] = self.quality

        _metrics().record(
            kind=KIND, task_id=self.task_id, agent=self.assignee or "forge",
            workflow=f"backlog:{self.task_id}", latency_ms=latency,
            tokens_in=self.tokens_in, tokens_out=self.tokens_out,
            cost_usd=self.cost_usd, ok=self.ok, error=self.error, meta=meta)

        agg = sync_backlog(self.task_id)
        self.aggregate = agg

        if self._complete:
            bl = _backlog()
            task = bl.require(self.task_id)
            merged = task["artifacts"] + [a for a in self.artifacts
                                          if a not in task["artifacts"]]
            if self.ok:
                bl.complete(self.task_id,
                            actual_days=task["actual_days"],
                            actual_tokens=task["actual_tokens"],
                            artifacts=merged)
            else:
                bl.upsert(**{**bl.require(self.task_id), "artifacts": merged})
                bl.block(self.task_id, self.error[:400])
                bl.bump_retry(self.task_id)
        return False  # ne masque jamais l'exception


def render_report() -> str:
    """Rendu texte : couverture de mesure + coût par epic."""
    cov = coverage()
    lines = [f"Mesure par tâche — {cov['done_measured']}/{cov['done']} tâches faites "
             f"mesurées ({cov['pct_done_measured']} %)"]
    if cov["unmeasured"]:
        lines.append(f"  non mesurées : {', '.join(cov['unmeasured'])}")
    for epic, e in epic_costs().items():
        if not e["measured"]:
            continue
        lines.append(f"  {epic:<4} {e['measured']}/{e['tasks']} mesurées · "
                     f"{e['tokens']:>9,} tok · {e['cost_usd']:.4f} $ · "
                     f"{e['failures']} échec(s)")
    return "\n".join(lines)


if __name__ == "__main__":  # auto-test — n'écrit rien dans le backlog
    print(f"HOURS_PER_DAY = {HOURS_PER_DAY}")
    print(render_report())
