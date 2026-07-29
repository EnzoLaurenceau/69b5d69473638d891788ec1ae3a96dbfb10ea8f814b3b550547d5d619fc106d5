"""
test_forge_task_ledger.py — E6-01, mesure unifiée par tâche.

Isolation : `forge_metrics.METRICS_PATH` et le backlog sont redirigés vers du
temporaire. Aucun test n'écrit dans le ledger de métriques réel ni dans la base
de secours du store — les deux vivent ailleurs et restent intacts.

Ce qui est vraiment vérifié ici : qu'un passage de travail remplit `actual_days`
et `actual_tokens` — les deux colonnes que E1-01 a livrées vides et sans
lesquelles E1-03 ne peut rien apprendre.
"""

import json
import sys
from pathlib import Path

import pytest

FORGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

from forge_agents import forge_metrics, forge_task_ledger  # noqa: E402
from forge_agents.forge_backlog import Backlog  # noqa: E402


class MemStore:
    def __init__(self):
        self.rows = {}

    def deep_insert(self, table, row):
        self.rows[row["id"]] = json.loads(json.dumps(row, default=str))

    def deep_query(self, table, filt=None, limit=50):
        return list(self.rows.values())[:limit]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Backlog + ledger métriques isolés, branchés l'un sur l'autre."""
    monkeypatch.setattr(forge_metrics, "METRICS_PATH", tmp_path / "metrics.jsonl")
    monkeypatch.setattr(forge_metrics, "_tenant_store", lambda: None)
    bl = Backlog(db=MemStore())
    monkeypatch.setattr(forge_task_ledger, "_backlog", lambda: bl)
    bl.upsert(id="E6-01", epic="E6", title="mesure", effort_days=3, complexity="M")
    bl.upsert(id="E6-02", epic="E6", title="score", effort_days=3,
              depends_on=["E6-01"])
    return bl


def test_evenement_sans_task_id_nest_jamais_compte(env):
    forge_metrics.record(kind="llm", tokens_in=999, model="mimo")       # hors tâche
    forge_metrics.record(kind="llm", task_id="E6-01", tokens_in=10, model="mimo")
    agg = forge_task_ledger.aggregate("E6-01")
    assert agg["events"] == 1 and agg["tokens_in"] == 10


def test_aggregate_somme_tokens_cout_modeles(env):
    forge_metrics.record(kind="llm", task_id="E6-01", tokens_in=100, tokens_out=50,
                         cost_usd=0.01, model="mimo", provider="mimo")
    forge_metrics.record(kind="llm", task_id="E6-01", tokens_in=200, tokens_out=25,
                         cost_usd=0.02, model="claude", provider="claude_cli")
    agg = forge_task_ledger.aggregate("E6-01")
    assert agg["tokens_total"] == 375
    assert agg["cost_usd"] == 0.03
    assert agg["models"] == ["claude", "mimo"]
    assert agg["providers"] == ["claude_cli", "mimo"]
    assert agg["ok"] is True and agg["failures"] == 0


def test_aggregate_est_idempotent(env):
    forge_metrics.record(kind="llm", task_id="E6-01", tokens_in=10)
    a, b = forge_task_ledger.aggregate("E6-01"), forge_task_ledger.aggregate("E6-01")
    assert a == b


def test_aggregate_remonte_les_echecs(env):
    forge_metrics.record(kind="llm", task_id="E6-01", ok=False, error="Boom: raté")
    agg = forge_task_ledger.aggregate("E6-01")
    assert agg["ok"] is False and agg["failures"] == 1
    assert agg["errors"] == ["Boom: raté"]


def test_quality_reste_none_tant_que_e6_02_nexiste_pas(env):
    forge_metrics.record(kind="llm", task_id="E6-01", tokens_in=10)
    assert forge_task_ledger.aggregate("E6-01")["quality"] is None


def test_quality_portee_si_fournie(env):
    forge_metrics.record(kind="llm", task_id="E6-01", meta={"quality": 82})
    assert forge_task_ledger.aggregate("E6-01")["quality"] == 82.0


# ── Le cœur du ticket : remplir actual_* ─────────────────────────────────────

def test_task_run_remplit_actual_tokens(env):
    with forge_task_ledger.task_run("E6-01", session="s") as run:
        run.tokens_in, run.tokens_out = 1000, 500
        run.artifact("00_CORE/forge_agents/forge_task_ledger.py")

    t = env.get("E6-01")
    assert t["state"] == "done"
    assert t["actual_tokens"] == 1500, "la colonne livrée vide par E1-01 est remplie"
    assert t["actual_days"] >= 0.0   # un passage de test dure ~0 jour, et c'est exact
    assert "00_CORE/forge_agents/forge_task_ledger.py" in t["artifacts"]
    assert forge_task_ledger.variance("E6-01")["measured"] is True


def test_task_run_agrege_les_evenements_du_travail(env):
    with forge_task_ledger.task_run("E6-01", session="s"):
        forge_metrics.record(kind="llm", task_id="E6-01", tokens_in=300,
                             tokens_out=100, cost_usd=0.05, model="mimo")
    t = env.get("E6-01")
    assert t["actual_tokens"] == 400
    assert forge_task_ledger.aggregate("E6-01")["cost_usd"] == 0.05


def test_echec_bloque_incremente_retries_et_garde_la_mesure(env):
    with pytest.raises(RuntimeError):
        with forge_task_ledger.task_run("E6-01", session="s") as run:
            run.tokens_in = 800
            raise RuntimeError("le build a cassé")

    t = env.get("E6-01")
    assert t["state"] == "blocked"
    assert t["retries"] == 1
    assert "le build a cassé" in t["block_reason"]
    assert t["actual_tokens"] == 800, "un échec coûte aussi — perdre sa mesure serait pire"
    assert forge_task_ledger.aggregate("E6-01")["ok"] is False


def test_echec_conserve_les_artefacts_partiels(env):
    with pytest.raises(ValueError):
        with forge_task_ledger.task_run("E6-01", session="s") as run:
            run.artifact("partiel.py")
            raise ValueError("stop")
    assert env.get("E6-01")["artifacts"] == ["partiel.py"]


def test_task_run_ne_masque_pas_lexception(env):
    with pytest.raises(KeyError, match="cle"):
        with forge_task_ledger.task_run("E6-01", session="s"):
            raise KeyError("cle")


def test_task_run_refuse_une_tache_a_dependance_ouverte(env):
    with pytest.raises(ValueError, match="dépendances non satisfaites"):
        with forge_task_ledger.task_run("E6-02", session="s"):
            pass


def test_task_run_sans_claim_ni_complete(env):
    env.set_state("E6-01", "in_progress")
    with forge_task_ledger.task_run("E6-01", "s", claim=False, complete=False) as run:
        run.tokens_in = 42
    t = env.get("E6-01")
    assert t["state"] == "in_progress", "aucune transition non demandée"
    assert t["actual_tokens"] == 42, "la mesure est reportée quand même"


def test_deux_passages_cumulent(env):
    with forge_task_ledger.task_run("E6-01", "s1", complete=False) as run:
        run.tokens_in = 100
    with forge_task_ledger.task_run("E6-01", "s1", claim=False) as run:
        run.tokens_in = 250
    assert env.get("E6-01")["actual_tokens"] == 350


# ── Conversions et rapports ──────────────────────────────────────────────────

def test_duree_convertie_en_jours_forge(env, monkeypatch):
    """Un « jour-Forge » n'est pas 24 h : le facteur doit être explicite."""
    monkeypatch.setattr(forge_task_ledger, "HOURS_PER_DAY", 8.0)
    forge_metrics.record(kind="task", task_id="E6-01",
                         latency_ms=4 * 3600 * 1000)          # 4 h
    assert forge_task_ledger.aggregate("E6-01")["duration_days"] == 0.5


def test_sync_backlog_ninvente_rien_sans_mesure(env):
    agg = forge_task_ledger.sync_backlog("E6-01")
    assert agg["events"] == 0
    t = env.get("E6-01")
    assert t["actual_days"] == 0.0 and t["actual_tokens"] == 0


def test_variance_estime_vs_reel(env):
    with forge_task_ledger.task_run("E6-01", "s") as run:
        run.tokens_in = 10
    v = forge_task_ledger.variance("E6-01")
    assert v["effort_days"] == 3.0
    assert v["measured"] is True
    assert v["variance_days"] == round(v["actual_days"] - 3.0, 4)


def test_variance_signale_labsence_de_mesure(env):
    v = forge_task_ledger.variance("E6-01")
    assert v["measured"] is False and v["actual_days"] == 0.0


def test_coverage_dit_la_verite(env):
    cov = forge_task_ledger.coverage()
    assert cov["done"] == 0 and cov["pct_done_measured"] == 0.0

    with forge_task_ledger.task_run("E6-01", "s") as run:
        run.tokens_in = 10
    cov = forge_task_ledger.coverage()
    assert cov["done"] == 1 and cov["done_measured"] == 1
    assert cov["pct_done_measured"] == 100.0
    assert cov["unmeasured"] == []


def test_coverage_liste_les_taches_faites_non_mesurees(env):
    env.claim("E6-01", "s")
    env.complete("E6-01")                       # terminée sans passer par task_run
    cov = forge_task_ledger.coverage()
    assert cov["unmeasured"] == ["E6-01"]
    assert cov["pct_done_measured"] == 0.0


def test_epic_costs(env):
    with forge_task_ledger.task_run("E6-01", "s") as run:
        run.tokens_in, run.cost_usd = 1000, 0.25
    costs = forge_task_ledger.epic_costs()
    assert costs["E6"]["tasks"] == 2 and costs["E6"]["measured"] == 1
    assert costs["E6"]["tokens"] == 1000
    assert costs["E6"]["cost_usd"] == 0.25


def test_render_report(env):
    with forge_task_ledger.task_run("E6-01", "s") as run:
        run.tokens_in = 5
    txt = forge_task_ledger.render_report()
    assert "1/1" in txt and "E6" in txt


# ── Non-régression sur forge_metrics ─────────────────────────────────────────

def test_champ_task_id_est_additif(env):
    """Les 8 appelants existants passent des kwargs explicites : rien ne casse."""
    rec = forge_metrics.record(kind="llm", workflow="w", agent="a", tokens_in=1)
    assert rec.task_id == ""
    s = forge_metrics.summary()
    assert s["total_calls"] >= 1
    assert forge_metrics.render_summary_table()          # ne doit pas lever


def test_ligne_ancienne_sans_task_id_est_ignoree(env, tmp_path):
    forge_metrics.METRICS_PATH.write_text(
        json.dumps({"kind": "llm", "tokens_in": 5, "ts": 1.0}) + "\n", encoding="utf-8")
    assert forge_task_ledger.events_for("E6-01") == []


# ── E2-06 · Mesurer un ticket qui ne tient pas dans un processus ─────────────

def test_claimed_start_relit_lhorodatage_de_prise(env):
    """`claim()` écrit `started_at` depuis E1-01 ; personne ne le relisait."""
    env.claim("E6-01", "s")
    assert forge_task_ledger.claimed_start("E6-01") > 0


def test_claimed_start_vaut_zero_si_la_tache_na_pas_ete_prise(env):
    """Zéro, jamais `time.time()` : une mesure absente doit rester absente
    plutôt que de se déguiser en durée nulle."""
    assert forge_task_ledger.claimed_start("E6-01") == 0.0


def test_started_at_mesure_depuis_la_prise_pas_depuis_le_with(env):
    """Le défaut qui a tenu `coverage()` à 0 % sur cinq tickets : un ticket réel
    s'étale sur des heures et plusieurs processus, `perf_counter()` ne mesurait
    que le dernier bloc `with` — une durée juste, sans rapport avec le ticket."""
    import time as _t
    env.claim("E6-01", "s")
    debut = forge_task_ledger.claimed_start("E6-01") - 7200      # prise il y a 2 h

    with forge_task_ledger.task_run("E6-01", "s", claim=False,
                                    started_at=debut) as run:
        run.tokens_in = 10

    heures = env.get("E6-01")["actual_days"] * forge_task_ledger.HOURS_PER_DAY
    assert 1.9 < heures < 2.1, "la durée doit être celle du ticket, pas du bloc"


def test_sans_started_at_le_comportement_dorigine_est_intact(env):
    """Rétro-compatibilité : les 24 tests d'E6-01 mesurent toujours le bloc."""
    with forge_task_ledger.task_run("E6-01", "s") as run:
        run.tokens_in = 10
    assert env.get("E6-01")["actual_days"] < 0.001
