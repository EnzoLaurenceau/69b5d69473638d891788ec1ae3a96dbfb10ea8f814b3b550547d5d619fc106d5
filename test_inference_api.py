"""La façade `/v1` fait-elle vraiment ce que le contrat promet ?

Ce n'est pas un test du moteur (`ForgeRunner` a ses propres suites) : c'est un test du
CONTRAT — la seule chose qui compte pour la console et pour un futur client qui intègre
l'API. On monte `inference_api.router` seul (sans `server.py` ni ses 60 routes de
dashboard), et on remplace deux frontières externes par des doublures :

  - `_resolve_tenant` : évite toute dépendance au registre `forge_identity` sur disque —
    le test reste hermétique et rejouable.
  - `_run_engine` : évite de lancer `ForgeRunner`/LangGraph pour de vrai (lent, réseau,
    tokens réels). On vérifie que le REGISTRE et le STREAM se comportent bien quand le
    moteur pousse des events — pas que le moteur produit une bonne réponse.

Ce que ça prouve, concrètement : run → stream → done (boucle Phase 1), isolation stricte
entre deux tenants (aucune fuite de run), et le chemin 429 quand le quota est dépassé.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "09_WEB"))
sys.path.insert(0, str(ROOT / "00_CORE"))

import inference_api as api  # noqa: E402

TENANT_TOKENS = {"tok-a": "tenant-a", "tok-b": "tenant-b"}


@pytest.fixture(autouse=True)
def _isolated_client(monkeypatch):
    """App minimale : uniquement le routeur /v1, tenant/moteur doublés."""
    monkeypatch.setattr(api, "_resolve_tenant", lambda token: TENANT_TOKENS.get(token or ""))

    def _fake_engine(run: "api.Run") -> None:
        run.status = "running"
        run.started = time.time()
        run.push("run.started", {"task": run.task})
        run.push("agent.output", {"node": "demo", "content": f"réponse à: {run.task}"})
        run.tokens_in, run.tokens_out, run.cost = 12, 34, 0.001
        run.push("run.done", {"task": run.task})
        run.status = "done"
        run.ended = time.time()

    monkeypatch.setattr(api, "_run_engine", _fake_engine)

    app = FastAPI()
    app.include_router(api.router)
    api.REGISTRY._runs.clear()  # hermétique entre tests
    with TestClient(app) as client:
        yield client


def _run(client, token="tok-a", task="ping"):
    r = client.post("/v1/agents/run", json={"task": task},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


# ── Auth ────────────────────────────────────────────────────────────────────
def test_run_sans_token_refuse(_isolated_client):
    r = _isolated_client.post("/v1/agents/run", json={"task": "x"})
    assert r.status_code == 401


def test_run_token_invalide_refuse(_isolated_client):
    r = _isolated_client.post("/v1/agents/run", json={"task": "x"},
                              headers={"Authorization": "Bearer inconnu"})
    assert r.status_code == 401


# ── Boucle Phase 1 : run → stream → done ─────────────────────────────────────
def test_run_puis_stream_arrive_a_done(_isolated_client):
    run_id = _run(_isolated_client, task="dis bonjour")

    with _isolated_client.websocket_connect(f"/v1/stream?run_id={run_id}&token=tok-a") as ws:
        types = []
        while True:
            ev = ws.receive_json()
            assert ev["v"] == 1 and ev["run_id"] == run_id
            types.append(ev["type"])
            if ev["type"] == "run.done":
                break
    assert "run.started" in types
    assert "run.done" in types
    assert types.index("run.started") < types.index("run.done")

    r = _isolated_client.get(f"/v1/runs/{run_id}", headers={"Authorization": "Bearer tok-a"})
    snap = r.json()
    assert snap["status"] == "done"
    assert snap["tokens_in"] == 12 and snap["tokens_out"] == 34


def test_graph_nodes_typEs_et_aretes(_isolated_client, monkeypatch):
    """/v1/graph : nœuds TYPÉS (type+key), arêtes TYPÉES, stats — pour la neural map."""
    from forge_agents import graph_db

    class _FakeDB:
        def get_all_nodes(self, label, limit=60):
            return {"Agent": [{"name": "orchestrator"}], "Project": [{"name": "le-taj"}]}.get(label, [])
        def get_edges(self, limit=200):
            return [{"source": "orchestrator", "target": "le-taj", "type": "EXECUTES",
                     "source_type": "Agent", "target_type": "Project"}]
        def count_nodes(self):
            return {"Agent": 1, "Project": 1}

    monkeypatch.setattr(graph_db, "get_graph_db", lambda: _FakeDB())

    r = _isolated_client.get("/v1/graph", headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 200
    body = r.json()
    keys = {n["key"] for n in body["nodes"]}
    types = {n["type"] for n in body["nodes"]}
    assert keys == {"orchestrator", "le-taj"}
    assert types == {"Agent", "Project"}
    assert body["edges"][0]["type"] == "EXECUTES"
    assert body["stats"] == {"Agent": 1, "Project": 1}


def test_metrics_repond(_isolated_client):
    r = _isolated_client.get("/v1/metrics", headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 200
    body = r.json()
    for key in ("tokens_in", "tokens_out", "cost", "savings_pct", "agents_active"):
        assert key in body


def test_router_tiers_ne_declare_aucun_tier_gratuit(_isolated_client):
    """Le routeur annonçait MiMo/Gemini/Groq/Cerebras en `free`. Les quatre étaient faux.

    MiMo est facturé (17 €/mois), Gemini n'a pas d'accès API sur l'abonnement AI Pro, et
    Groq/ds2api ont été abandonnés (instables). Ce test existe pour qu'un « petit retour »
    à une liste statique optimiste casse la CI au lieu de faire router du volume payant
    en croyant décharger gratuitement.
    """
    r = _isolated_client.get("/v1/router/tiers", headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 200
    body = r.json()

    assert body["free_tier_available"] is False
    assert body["tiers"], "la liste des tiers ne doit jamais être vide"

    kinds = {t["name"]: t["kind"] for t in body["tiers"]}
    assert kinds["MiMo"] == "paid", "MiMo est facturé — jamais `free`"
    assert kinds["Claude"] == "subscription"
    for abandonne in ("Gemini", "Groq", "ds2api", "Cerebras"):
        assert kinds[abandonne] == "removed", f"{abandonne} est abandonné"

    # Aucun tier, quel qu'il soit, ne doit se présenter comme gratuit.
    assert not [t for t in body["tiers"] if t["kind"] == "free"]

    # Le contrat que la console consomme : chaque tier porte de quoi s'afficher.
    for t in body["tiers"]:
        assert {"name", "kind", "wired", "available", "detail"} <= set(t)


def test_budget_mimo_expose_le_plan_fournisseur_et_sa_provenance(_isolated_client):
    """`/v1/budget/mimo` répond sur l'axe FOURNISSEUR, et dit d'où sort son chiffre.

    C'est le second axe, à ne pas confondre avec `/quota` (axe client, fenêtre glissante).
    Le champ qui compte le plus est `source` : tant qu'on n'a pas d'endpoint fournisseur
    confirmé, le solde est en partie déclaré, et l'API doit l'avouer plutôt que de le
    présenter comme une mesure.
    """
    r = _isolated_client.get("/v1/budget/mimo", headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 200
    body = r.json()

    for key in ("provider", "period", "plan_tokens", "used_tokens", "remaining_tokens",
                "pct", "source", "baseline_tokens", "ledger_billed_tokens", "calls"):
        assert key in body, f"champ manquant au contrat : {key}"

    assert body["provider"] == "MiMo"
    assert body["source"] in ("remote", "local", "declared")
    assert body["plan_tokens"] > 0, "un plan à 0 afficherait un solde de 0 % en permanence"
    assert body["remaining_tokens"] == max(0, body["plan_tokens"] - body["used_tokens"])


def test_budget_mimo_sans_token_refuse(_isolated_client):
    assert _isolated_client.get("/v1/budget/mimo").status_code == 401


def test_board_renvoie_des_colonnes_pas_une_liste_a_plat(_isolated_client):
    """`/v1/orchestrator/board` renvoyait `{tasks:[…]}` quand la console attend
    `{columns:{…}}` : la vue n'affichait rien, **sans erreur**. Ce test verrouille la
    forme consommée, y compris la colonne `blocked` — une tâche bloquée qui disparaît
    du board est exactement le genre de silence que ce sprint supprime.
    """
    r = _isolated_client.get("/v1/orchestrator/board", headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 200
    body = r.json()

    assert "columns" in body and isinstance(body["columns"], dict)
    for col in ("todo", "doing", "done", "blocked"):
        assert col in body["columns"], f"colonne manquante : {col}"
        assert isinstance(body["columns"][col], list)
    assert body["scope"] in ("tenant", "global")
    assert set(body["counts"]) == set(body["columns"])
    for col, tasks in body["columns"].items():
        assert body["counts"][col] == len(tasks)


def test_board_traduit_chaque_statut_kanban_vers_sa_colonne(_isolated_client, monkeypatch):
    """Le mapping statut → colonne est le cœur de S-04 : c'est lui qui manquait."""
    from forge_dispatch import kanban

    monkeypatch.setattr(kanban, "load", lambda: {"tasks": [
        {"id": "A", "name": "a", "status": "pending"},
        {"id": "B", "name": "b", "status": "in_progress"},
        {"id": "C", "name": "c", "status": "done"},
        {"id": "D", "name": "d", "status": "blocked"},
        {"id": "E", "name": "e", "status": "statut-inventé"},
    ]})

    body = _isolated_client.get("/v1/orchestrator/board",
                                headers={"Authorization": "Bearer tok-a"}).json()
    cols = {c: [t["id"] for t in ts] for c, ts in body["columns"].items()}
    assert cols["doing"] == ["B"]
    assert cols["done"] == ["C"]
    assert cols["blocked"] == ["D"]
    # Statut inconnu : VISIBLE dans `todo`, jamais escamoté.
    assert cols["todo"] == ["A", "E"]


# ── Isolation stricte entre tenants ──────────────────────────────────────────
def test_tenant_b_ne_voit_jamais_le_run_de_tenant_a(_isolated_client):
    run_id = _run(_isolated_client, token="tok-a", task="secret de A")

    r = _isolated_client.get(f"/v1/runs/{run_id}", headers={"Authorization": "Bearer tok-b"})
    assert r.status_code == 404

    r = _isolated_client.get("/v1/runs", headers={"Authorization": "Bearer tok-b"})
    assert all(run["run_id"] != run_id for run in r.json()["runs"])

    r = _isolated_client.get("/v1/runs", headers={"Authorization": "Bearer tok-a"})
    assert any(run["run_id"] == run_id for run in r.json()["runs"])


def test_tenant_b_ne_peut_pas_annuler_le_run_de_tenant_a(_isolated_client):
    run_id = _run(_isolated_client, token="tok-a", task="secret de A")
    r = _isolated_client.post(f"/v1/runs/{run_id}/cancel",
                              headers={"Authorization": "Bearer tok-b"})
    assert r.status_code == 404


# ── Quota : 429 propre, pas un 500 ───────────────────────────────────────────
def test_quota_depasse_renvoie_429(_isolated_client, monkeypatch):
    from forge_agents import forge_quota

    def _raise(*a, **k):
        raise forge_quota.QuotaExceeded("requests", used=100, limit=100, tenant="tenant-a")

    monkeypatch.setattr(forge_quota, "consume", _raise)

    r = _isolated_client.post("/v1/agents/run", json={"task": "x"},
                              headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 429
    body = r.json()
    assert body["resource"] == "requests"
    assert body["used"] == 100 and body["limit"] == 100
