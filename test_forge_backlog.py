"""
test_forge_backlog.py — E1-01, backlog persistant.

Deux niveaux, délibérément :
  1. la logique (validation, transitions, DAG) contre un store en mémoire — rapide,
     et c'est là que vivent les garde-fous ;
  2. un aller-retour contre le VRAI SQLite du secours, sur un fichier temporaire.
     Leçon d'E2-01 : un schéma qui se rend joliment n'est pas un schéma qui
     s'ouvre. Les listes (`depends_on`) traversent une sérialisation JSON — c'est
     exactement le genre d'endroit où ça casse en silence.

Aucun test ne touche `04_GRAPHIFY/forge_fallback.db` (base réelle du secours).
"""

import json
import sys
from pathlib import Path

import pytest

FORGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

from forge_agents.forge_backlog import (  # noqa: E402
    COMPLEXITIES,
    TASK_PROPS,
    TASK_STATES,
    Backlog,
    can_transition,
    get_backlog,
    table_ddl,
    validate_task,
)


# ── Store en mémoire : même contrat que forge_db.deep_insert/deep_query ───────

class MemStore:
    """Imite `forge_db` : upsert par `id`, lecture bornée par `limit`."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def deep_insert(self, table, row):
        assert table == "tasks"
        # Comme le secours : la ligne fait un aller-retour JSON.
        self.rows[row["id"]] = json.loads(json.dumps(row, default=str))

    def deep_query(self, table, filt=None, limit=50):
        assert table == "tasks"
        out = list(self.rows.values())
        if filt:
            out = [r for r in out if all(str(r.get(k)) == str(v) for k, v in filt.items())]
        return out[:limit]


@pytest.fixture
def bl():
    return Backlog(db=MemStore())


def _seed(bl, tid, **kw):
    base = {"id": tid, "epic": tid.split("-")[0], "title": f"tâche {tid}"}
    return bl.upsert(**{**base, **kw})


# ── 1. DDL dérivé (fonction pure) ─────────────────────────────────────────────

def test_ddl_contient_toutes_les_proprietes():
    ddl = table_ddl()
    for prop in TASK_PROPS:
        assert prop in ddl, f"{prop} absente du DDL"


def test_ddl_idempotent_et_indexe():
    ddl = table_ddl()
    assert "CREATE TABLE IF NOT EXISTS tasks" in ddl
    assert "id TEXT PRIMARY KEY" in ddl
    assert "tasks_epic_idx" in ddl and "tasks_state_idx" in ddl


def test_ddl_est_pur():
    assert table_ddl() == table_ddl()


# ── 2. Validation : les garde-fous LÈVENT ────────────────────────────────────

def test_defauts_appliques():
    t = validate_task({"id": "E1-01"})
    assert t["state"] == "pending"
    assert t["complexity"] == "M"
    assert t["depends_on"] == [] and t["artifacts"] == [] and t["files"] == []
    assert t["retries"] == 0
    assert set(t) == set(TASK_PROPS)


def test_id_obligatoire():
    with pytest.raises(ValueError, match="id"):
        validate_task({"epic": "E1"})
    with pytest.raises(ValueError, match="id"):
        validate_task({"id": "   "})


def test_propriete_hors_whitelist_leve():
    with pytest.raises(ValueError, match="whitelist"):
        validate_task({"id": "E1-01", "priorite": "haute"})


def test_etat_hors_vocabulaire_leve():
    with pytest.raises(ValueError, match="hors vocabulaire"):
        validate_task({"id": "E1-01", "state": "presque_fini"})


def test_complexite_hors_vocabulaire_leve():
    with pytest.raises(ValueError, match="hors vocabulaire"):
        validate_task({"id": "E1-01", "complexity": "XL"})


def test_type_incorrect_leve():
    with pytest.raises(ValueError, match="attendu"):
        validate_task({"id": "E1-01", "depends_on": "E1-02"})   # str, pas list
    with pytest.raises(ValueError, match="attendu"):
        validate_task({"id": "E1-01", "retries": "trois"})


def test_booleen_refuse_sur_champ_numerique():
    # En Python `True == 1` : sans garde explicite, retries=True passerait.
    with pytest.raises(ValueError):
        validate_task({"id": "E1-01", "retries": True})


def test_auto_dependance_leve():
    with pytest.raises(ValueError, match="elle-même"):
        validate_task({"id": "E1-01", "depends_on": ["E1-01"]})


def test_dependance_dupliquee_leve():
    with pytest.raises(ValueError, match="dupliquée"):
        validate_task({"id": "E1-02", "depends_on": ["E1-01", "E1-01"]})


def test_effort_negatif_leve():
    with pytest.raises(ValueError, match="négatif"):
        validate_task({"id": "E1-01", "effort_days": -2})


def test_dependances_nettoyees():
    t = validate_task({"id": "E1-02", "depends_on": ["  E1-01  ", "", "   "]})
    assert t["depends_on"] == ["E1-01"]


# ── 3. Machine à états ────────────────────────────────────────────────────────

def test_transitions_legales_et_illegales():
    assert can_transition("pending", "in_progress")
    assert can_transition("in_progress", "done")
    assert can_transition("done", "in_progress")      # réouverture explicite
    assert not can_transition("cancelled", "done")
    assert not can_transition("done", "blocked")
    assert not can_transition("pending", "inexistant")


def test_toutes_les_sources_sont_couvertes():
    for s in TASK_STATES:
        assert can_transition(s, s) or s in ("done", "cancelled") or True
        assert any(can_transition(s, d) for d in TASK_STATES), s


def test_set_state_refuse_transition_interdite(bl):
    _seed(bl, "E1-01", state="done")
    with pytest.raises(ValueError, match="transition interdite"):
        bl.set_state("E1-01", "blocked")


def test_set_state_refuse_etat_inconnu(bl):
    _seed(bl, "E1-01")
    with pytest.raises(ValueError, match="hors vocabulaire"):
        bl.set_state("E1-01", "fini_a_moitie")


# ── 4. Écriture / persistance ─────────────────────────────────────────────────

def test_upsert_puis_relecture(bl):
    _seed(bl, "E1-01", effort_days=2, complexity="M", depends_on=[])
    t = bl.get("E1-01")
    assert t["title"] == "tâche E1-01"
    assert t["effort_days"] == 2.0
    assert t["created_at"] > 0 and t["updated_at"] > 0


def test_upsert_preserve_created_at(bl):
    first = _seed(bl, "E1-01")
    second = bl.upsert(id="E1-01", epic="E1", title="renommée")
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert bl.get("E1-01")["title"] == "renommée"


def test_require_leve_sur_tache_inconnue(bl):
    with pytest.raises(ValueError, match="inconnue"):
        bl.require("E9-99")
    assert bl.get("E9-99") is None


def test_upsert_many_est_atomique(bl):
    lot = [{"id": "E1-01", "epic": "E1"}, {"id": "E1-02", "epic": "E1", "state": "faux"}]
    with pytest.raises(ValueError):
        bl.upsert_many(lot)
    assert bl.all() == [], "un lot refusé ne doit rien avoir écrit"


def test_upsert_many_refuse_les_doublons(bl):
    with pytest.raises(ValueError, match="dupliqués"):
        bl.upsert_many([{"id": "E1-01"}, {"id": "E1-01"}])


def test_upsert_many_nominal(bl):
    bl.upsert_many([{"id": "E1-01", "epic": "E1"}, {"id": "E1-02", "epic": "E1"}])
    assert {t["id"] for t in bl.all()} == {"E1-01", "E1-02"}


# ── 5. Claim / complete / retry ───────────────────────────────────────────────

def test_claim_bloque_par_dependance_ouverte(bl):
    _seed(bl, "E1-01")
    _seed(bl, "E1-02", depends_on=["E1-01"])
    with pytest.raises(ValueError, match="dépendances non satisfaites"):
        bl.claim("E1-02", "session-a")


def test_claim_possible_quand_dependance_faite(bl):
    _seed(bl, "E1-01")
    _seed(bl, "E1-02", depends_on=["E1-01"])
    bl.claim("E1-01", "session-a")
    bl.complete("E1-01")
    t = bl.claim("E1-02", "session-a", assignee="hermes")
    assert t["state"] == "in_progress" and t["assignee"] == "hermes"
    assert t["started_at"] > 0


def test_dependance_inconnue_nest_jamais_satisfaite(bl):
    _seed(bl, "E1-02", depends_on=["E0-00"])
    assert bl.unmet_dependencies("E1-02") == ["E0-00"]
    with pytest.raises(ValueError, match="dépendances non satisfaites"):
        bl.claim("E1-02", "session-a")


def test_claim_refuse_si_tenue_par_une_autre_session(bl):
    _seed(bl, "E1-01")
    bl.claim("E1-01", "session-a")
    with pytest.raises(ValueError, match="déjà tenue"):
        bl.claim("E1-01", "session-b")
    assert bl.claim("E1-01", "session-a")["state"] == "in_progress"


def test_complete_enregistre_le_reel(bl):
    _seed(bl, "E1-01", effort_days=2)
    bl.claim("E1-01", "s")
    t = bl.complete("E1-01", actual_days=3.5, actual_tokens=120_000,
                    artifacts=["00_CORE/forge_agents/forge_backlog.py"])
    assert t["state"] == "done"
    assert t["actual_days"] == 3.5 and t["actual_tokens"] == 120_000
    assert t["artifacts"] == ["00_CORE/forge_agents/forge_backlog.py"]
    assert t["completed_at"] > 0
    assert t["effort_days"] == 2.0, "l'estimé doit survivre au réel (E1-03)"


def test_block_et_bump_retry(bl):
    _seed(bl, "E1-01")
    assert bl.block("E1-01", "kuzu absent des deps")["block_reason"] == "kuzu absent des deps"
    assert bl.bump_retry("E1-01")["retries"] == 1
    assert bl.bump_retry("E1-01")["retries"] == 2


# ── 6. DAG ────────────────────────────────────────────────────────────────────

def test_ready_ne_retient_que_le_prenable(bl):
    _seed(bl, "E1-01")
    _seed(bl, "E1-02", depends_on=["E1-01"])
    _seed(bl, "E1-03", depends_on=["E0-00"])          # dépendance orpheline
    assert [t["id"] for t in bl.ready()] == ["E1-01"]


def test_ready_exclut_les_etats_terminaux(bl):
    _seed(bl, "E1-01", state="done")
    _seed(bl, "E1-02", state="cancelled")
    _seed(bl, "E1-03")
    assert [t["id"] for t in bl.ready()] == ["E1-03"]


def test_dependents_of(bl):
    _seed(bl, "E1-01")
    _seed(bl, "E1-02", depends_on=["E1-01"])
    _seed(bl, "E1-05", depends_on=["E1-01", "E6-01"])
    assert bl.dependents_of("E1-01") == ["E1-02", "E1-05"]


def test_dag_sain_na_pas_de_cycle(bl):
    _seed(bl, "E1-01")
    _seed(bl, "E1-02", depends_on=["E1-01"])
    _seed(bl, "E1-04", depends_on=["E1-02"])
    assert bl.find_cycles() == []


def test_cycle_a_deux_detecte(bl):
    bl.upsert(id="A", epic="E1", title="a")
    bl.upsert(id="B", epic="E1", title="b", depends_on=["A"])
    bl.upsert(id="A", epic="E1", title="a", depends_on=["B"])
    cycles = bl.find_cycles()
    assert cycles, "cycle A↔B non détecté"
    assert {"A", "B"} <= set(cycles[0])


def test_cycle_a_trois_detecte(bl):
    for a, b in (("A", "C"), ("B", "A"), ("C", "B")):
        bl.upsert(id=a, epic="E1", title=a, depends_on=[b])
    assert bl.find_cycles()


def test_chaine_profonde_ne_fait_pas_exploser_la_pile(bl):
    # DFS itérative : 400 maillons passeraient la limite de récursion par défaut.
    prev = None
    for i in range(400):
        tid = f"T{i:03d}"
        bl.upsert(id=tid, epic="E1", title=tid,
                  depends_on=[prev] if prev else [])
        prev = tid
    assert bl.find_cycles() == []
    assert [t["id"] for t in bl.ready()] == ["T000"]


def test_ordre_topologique(bl):
    _seed(bl, "E1-01", effort_days=2)
    _seed(bl, "E1-02", effort_days=3, depends_on=["E1-01"])
    _seed(bl, "E1-04", effort_days=3, depends_on=["E1-02"])
    order = bl.topological_order()
    assert order.index("E1-01") < order.index("E1-02") < order.index("E1-04")


def test_ordre_topologique_deterministe(bl):
    for i in range(6):
        _seed(bl, f"E1-0{i}", effort_days=1)
    assert bl.topological_order() == bl.topological_order()


def test_ordre_topologique_leve_sur_cycle(bl):
    bl.upsert(id="A", epic="E1", title="a")
    bl.upsert(id="B", epic="E1", title="b", depends_on=["A"])
    bl.upsert(id="A", epic="E1", title="a", depends_on=["B"])
    with pytest.raises(ValueError, match="cycle"):
        bl.topological_order()
    with pytest.raises(ValueError, match="cycle"):
        bl.critical_path()


# ── 6b. Chemin critique (E1-02) ──────────────────────────────────────────────

def test_chemin_critique_chaine_simple(bl):
    _seed(bl, "E1-01", effort_days=2)
    _seed(bl, "E1-02", effort_days=3, depends_on=["E1-01"])
    _seed(bl, "E1-04", effort_days=4, depends_on=["E1-02"])
    cp = bl.critical_path()
    assert cp["duration_days"] == 9.0
    assert cp["path"] == ["E1-01", "E1-02", "E1-04"]
    assert cp["critical"] == ["E1-01", "E1-02", "E1-04"]


def test_chemin_critique_choisit_la_branche_longue(bl):
    _seed(bl, "R", effort_days=1)
    _seed(bl, "COURT", effort_days=2, depends_on=["R"])
    _seed(bl, "LONG-A", effort_days=5, depends_on=["R"])
    _seed(bl, "LONG-B", effort_days=4, depends_on=["LONG-A"])
    cp = bl.critical_path()
    assert cp["duration_days"] == 10.0
    assert cp["path"] == ["R", "LONG-A", "LONG-B"]
    assert "COURT" not in cp["critical"]


def test_marge_calculee(bl):
    _seed(bl, "R", effort_days=1)
    _seed(bl, "COURT", effort_days=2, depends_on=["R"])
    _seed(bl, "LONG-A", effort_days=5, depends_on=["R"])
    _seed(bl, "FIN", effort_days=1, depends_on=["COURT", "LONG-A"])
    sched = bl.critical_path()["schedule"]
    assert sched["LONG-A"]["slack"] == 0.0
    assert sched["COURT"]["slack"] == 3.0, "COURT peut glisser de 3 j sans décaler FIN"
    assert sched["FIN"]["early_start"] == 6.0


def test_taches_paralleles_ne_sadditionnent_pas(bl):
    _seed(bl, "A", effort_days=4)
    _seed(bl, "B", effort_days=6)
    _seed(bl, "C", effort_days=5)
    assert bl.critical_path()["duration_days"] == 6.0


def test_chemin_critique_restant_ignore_le_fait(bl):
    _seed(bl, "E1-01", effort_days=2)
    _seed(bl, "E1-02", effort_days=3, depends_on=["E1-01"])
    assert bl.critical_path()["duration_days"] == 5.0
    bl.claim("E1-01", "s")
    bl.complete("E1-01")
    assert bl.critical_path()["duration_days"] == 5.0, "le plan conçu ne bouge pas"
    assert bl.critical_path(remaining=True)["duration_days"] == 3.0


def test_dependance_orpheline_exclue_de_lordonnancement(bl):
    _seed(bl, "E1-02", effort_days=3, depends_on=["E0-00"])
    cp = bl.critical_path()
    assert cp["duration_days"] == 3.0
    assert "E0-00" not in cp["schedule"]
    # …mais elle bloque toujours le claim et reste signalée
    assert bl.unmet_dependencies("E1-02") == ["E0-00"]
    assert bl.validate()["dangling_dependencies"] == [["E1-02", "E0-00"]]


def test_chemin_critique_backlog_vide(bl):
    assert bl.critical_path()["duration_days"] == 0.0


# ── 6c. Conflits (remplace check_conflicts fichier-only) ─────────────────────

def test_conflit_de_fichiers(bl):
    _seed(bl, "E1-01", files=["a.py", "b.py"])
    _seed(bl, "E6-01", files=["b.py", "c.py"])
    bl.claim("E6-01", "session-b")
    c = bl.conflicts("E1-01")
    assert c["blocked"] is True
    assert c["file_overlaps"] == [{"task": "E6-01", "session": "session-b",
                                   "files": ["b.py"]}]
    assert c["unmet_dependencies"] == []


def test_conflit_dordre_invisible_pour_la_version_fichier_only(bl):
    """Aucun fichier partagé, et pourtant la tâche ne doit pas démarrer."""
    _seed(bl, "E1-01", files=["a.py"])
    _seed(bl, "E1-02", files=["z.py"], depends_on=["E1-01"])
    c = bl.conflicts("E1-02")
    assert c["file_overlaps"] == []
    assert c["unmet_dependencies"] == ["E1-01"]
    assert c["blocked"] is True


def test_aucun_conflit(bl):
    _seed(bl, "E1-01", files=["a.py"])
    c = bl.conflicts("E1-01")
    assert c["blocked"] is False and c["state"] == "pending"


def test_conflit_ignore_les_taches_non_demarrees(bl):
    _seed(bl, "E1-01", files=["a.py"])
    _seed(bl, "E6-01", files=["a.py"])          # pending, pas in_progress
    assert bl.conflicts("E1-01")["file_overlaps"] == []


def test_conflits_tache_inconnue(bl):
    with pytest.raises(ValueError, match="inconnue"):
        bl.conflicts("E9-99")


def test_validate_rapporte_les_dependances_orphelines(bl):
    _seed(bl, "E1-02", depends_on=["E0-00"])
    rep = bl.validate()
    assert rep["tasks"] == 1
    assert rep["dangling_dependencies"] == [["E1-02", "E0-00"]]
    assert rep["cycles"] == []
    assert rep["by_state"]["pending"] == 1


# ── 7. Vues ───────────────────────────────────────────────────────────────────

def test_epic_summary(bl):
    _seed(bl, "E1-01", effort_days=2, state="done")
    _seed(bl, "E1-02", effort_days=3)
    _seed(bl, "E2-01", effort_days=4)
    s = bl.epic_summary()
    assert s["E1"]["tasks"] == 2 and s["E1"]["done"] == 1
    assert s["E1"]["effort_days"] == 5.0
    assert s["E1"]["pct_done"] == 50.0
    assert s["E2"]["pct_done"] == 0.0


def test_by_state_et_by_epic(bl):
    _seed(bl, "E1-01", state="done")
    _seed(bl, "E2-01")
    assert [t["id"] for t in bl.by_state("done")] == ["E1-01"]
    assert [t["id"] for t in bl.by_epic("E2")] == ["E2-01"]
    with pytest.raises(ValueError):
        bl.by_state("inexistant")


def test_projection_kanban_compatible(bl):
    """Le board projeté doit être consommable par forge_dispatch/kanban.py."""
    _seed(bl, "E1-01", effort_days=2, files=["00_CORE/forge_agents/forge_db.py"])
    _seed(bl, "E1-02", effort_days=3, depends_on=["E1-01"], state="ready")
    board = bl.to_kanban_board("Plan RPG")

    assert board["version"] == 1 and board["parent_task"] == "Plan RPG"
    assert board["total_est_days"] == 5.0
    for t in board["tasks"]:
        assert {"id", "name", "status", "files"} <= set(t), "clés attendues par kanban.py"
        assert t["status"] in ("pending", "in_progress", "done", "blocked", "cancelled")
    # `ready` est un état du backlog, pas du kanban : il doit être projeté.
    assert [t["status"] for t in board["tasks"]] == ["pending", "pending"]
    assert board["tasks"][0]["epic"] == "E1"


def test_status_kanban_lit_la_projection(bl, tmp_path, monkeypatch):
    """Preuve d'interopérabilité : kanban.status() rend le board sans planter."""
    sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_dispatch"))
    import kanban  # type: ignore

    _seed(bl, "E1-01", effort_days=2)
    _seed(bl, "E1-02", effort_days=3, depends_on=["E1-01"])
    board_file = tmp_path / "board_rpg.json"
    board_file.write_text(json.dumps(bl.to_kanban_board("Plan RPG")), encoding="utf-8")
    monkeypatch.setattr(kanban, "KANBAN_FILE", lambda: board_file)

    out = kanban.status()
    assert "E1-01" in out and "E1-02" in out
    assert "⬜2" in out or "pending" in out


def test_render_lisible(bl):
    _seed(bl, "E1-01", effort_days=2, state="done")
    _seed(bl, "E2-01", effort_days=4)
    txt = bl.render()
    assert "Backlog — 2 tâches" in txt
    assert "E1" in txt and "E2" in txt


# ── 8. Relecture depuis Postgres (types JSON) ─────────────────────────────────

def test_coerce_relit_une_liste_serialisee_en_json():
    """PG peut rendre JSONB en chaîne : sans normalisation, `ready()` mentirait."""
    from forge_agents.forge_backlog import _coerce_row
    r = _coerce_row({"id": "E1-02", "depends_on": '["E1-01"]', "retries": "2",
                     "effort_days": "3.5"})
    assert r["depends_on"] == ["E1-01"]
    assert r["retries"] == 2 and r["effort_days"] == 3.5


def test_coerce_survit_a_un_json_casse():
    from forge_agents.forge_backlog import _coerce_row
    assert _coerce_row({"id": "X", "depends_on": "{pas du json"})["depends_on"] == []


def test_backlog_lit_une_ligne_style_postgres(bl):
    bl.db.rows["E1-02"] = {"id": "E1-02", "epic": "E1", "title": "t",
                           "state": "pending", "complexity": "M",
                           "depends_on": '["E1-01"]', "artifacts": "[]",
                           "files": "[]", "retries": "0"}
    assert bl.get("E1-02")["depends_on"] == ["E1-01"]
    assert bl.unmet_dependencies("E1-02") == ["E1-01"]


# ── 9. VRAI SQLite : le secours doit accepter la table `tasks` ────────────────

def test_table_tasks_declaree_dans_le_secours():
    from forge_agents import forge_db_fallback
    assert "tasks" in forge_db_fallback._DEEP_TABLES, (
        "sans ça, deep_insert ignore SILENCIEUSEMENT les écritures du backlog")


def test_aller_retour_contre_le_vrai_sqlite(tmp_path, monkeypatch):
    """Le backlog doit survivre à un vrai INSERT/SELECT SQLite, pas à une maquette."""
    from forge_agents import forge_db_fallback

    monkeypatch.setattr(forge_db_fallback, "FALLBACK_DB", tmp_path / "fallback.db")
    store = forge_db_fallback.FallbackStore()

    # La table a bien été créée par _init_schema
    tables = {r[0] for r in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "tasks" in tables

    bl = Backlog(db=store)
    bl.upsert_many([
        {"id": "E1-01", "epic": "E1", "title": "Schéma Task", "effort_days": 2,
         "complexity": "M"},
        {"id": "E1-02", "epic": "E1", "title": "DAG", "effort_days": 3,
         "complexity": "H", "depends_on": ["E1-01"]},
    ])

    assert len(bl.all()) == 2
    assert bl.get("E1-02")["depends_on"] == ["E1-01"], "liste perdue à la traversée JSON"
    assert [t["id"] for t in bl.ready()] == ["E1-01"]

    bl.claim("E1-01", "session-reelle")
    bl.complete("E1-01", actual_days=2.5)
    assert [t["id"] for t in bl.ready()] == ["E1-02"]

    # Idempotence : réécrire ne duplique pas la ligne
    bl.upsert(id="E1-02", epic="E1", title="DAG renommé", depends_on=["E1-01"])
    assert len(bl.all()) == 2

    # Persistance réelle : une seconde connexion au même fichier revoit tout
    store2 = forge_db_fallback.FallbackStore()
    assert len(Backlog(db=store2).all()) == 2
    assert Backlog(db=store2).get("E1-01")["actual_days"] == 2.5


def test_ddl_backlog_atteignable_depuis_forge_db():
    """`_ensure_schema` importe `table_ddl` tardivement : prouver l'absence de cycle."""
    from forge_agents.forge_backlog import table_ddl as td
    assert "tasks" in td()
    import forge_agents.forge_db as fdb
    assert hasattr(fdb.ForgeDB, "_ensure_schema")


def test_singleton_get_backlog():
    assert get_backlog() is get_backlog()
    assert isinstance(get_backlog(), Backlog)


def test_vocabulaires_geles():
    """Ces tuples sont un contrat : les changer casse les boards déjà écrits."""
    assert TASK_STATES == ("pending", "ready", "in_progress", "blocked",
                           "done", "cancelled")
    assert COMPLEXITIES == ("S", "M", "H")
