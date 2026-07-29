"""Phase 3 — l'isolation multi-tenant tient-elle sous auth réelle, quota réel, multi-process ?

Différence avec `test_inference_api.py` (contrat, tenant/moteur doublés) : ICI on branche
la VRAIE identité (`forge_identity`), le VRAI quota (`forge_quota`) et le VRAI magasin
(`forge_store`). Seul le moteur (`_run_engine`) est doublé — lancer LangGraph n'apprend
rien sur l'isolation et coûte des tokens réels.

Le test app réplique le `tenant_middleware` de `server.py` (Bearer → tenant → contexte)
parce que c'est LUI qui rend le quota par-requête effectif : sans contexte tenant,
`forge_quota.consume` retombe hors scope et n'applique rien. On teste donc le câblage réel.

Critères d'acceptation Phase 3 couverts :
  - deux tokens = deux espaces ; A ne lit jamais rien de B (identité réelle + magasin) ;
  - un tenant qui dépasse son quota est bloqué (429) SANS dégrader l'autre ;
  - provisioning admin (rôle opérateur ≠ jeton tenant) ;
  - isolation prouvée entre PROCESSUS distincts (repli fichier, 1 process/tenant).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI, Request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "09_WEB"))
sys.path.insert(0, str(ROOT / "00_CORE"))

import inference_api as api  # noqa: E402
from forge_agents import forge_identity, forge_quota, forge_tenant, forge_store  # noqa: E402

TENANTS_ROOT = ROOT / "05_STATE" / "tenants"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Identité + quotas hermétiques (fichiers temporaires), moteur doublé, app /v1
    montée AVEC le middleware tenant réel (Bearer → contexte). Nettoie les espaces créés."""
    monkeypatch.setattr(forge_identity, "REGISTRY", tmp_path / "tenants.json")
    monkeypatch.setattr(forge_quota, "LIMITS_FILE", tmp_path / "quotas.json")

    # Moteur doublé : le run passe par le registre/stream mais ne lance pas LangGraph.
    def _fake_engine(run: "api.Run") -> None:
        run.status = "running"; run.started = time.time()
        run.push("run.started", {"task": run.task})
        run.push("run.done", {"task": run.task})
        run.status = "done"; run.ended = time.time()
    monkeypatch.setattr(api, "_run_engine", _fake_engine)

    created: list[str] = []

    def _new_tenant(prefix: str) -> tuple[str, str]:
        tid = f"t-{prefix}-{uuid.uuid4().hex[:8]}"
        token = forge_identity.create_tenant(tid, label=prefix)
        created.append(tid)
        return tid, token

    app = FastAPI()

    @app.middleware("http")
    async def _tenant_mw(request: Request, call_next):
        # Réplique server.py : Bearer > X-Forge-Token > ?token, posé dans le contexte.
        auth = request.headers.get("authorization") or ""
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        token = bearer or request.headers.get("x-forge-token") or request.query_params.get("token")
        tenant = forge_identity.resolve_token(token) if token else None
        if not tenant:
            return await call_next(request)
        ctx = forge_tenant.set_tenant(tenant)
        try:
            return await call_next(request)
        finally:
            forge_tenant.reset_tenant(ctx)

    app.include_router(api.router)
    api.REGISTRY._runs.clear()

    client = TestClient(app)
    try:
        yield type("Env", (), {"client": client, "new_tenant": _new_tenant})
    finally:
        client.close()
        import shutil
        for tid in created:
            shutil.rmtree(TENANTS_ROOT / tid, ignore_errors=True)


# ── Deux tokens = deux espaces ────────────────────────────────────────────────
def test_deux_tokens_deux_espaces_magasin(env):
    """Au niveau magasin : sous le tenant de A, une clé écrite est INVISIBLE pour B."""
    a_id, _ = env.new_tenant("a")
    b_id, _ = env.new_tenant("b")
    with forge_tenant.tenant_scope(a_id):
        forge_store.put("cfg", "secret", {"v": "propre-a-A"})
    with forge_tenant.tenant_scope(b_id):
        assert forge_store.get("cfg", "secret") is None       # B ne voit rien de A
        forge_store.put("cfg", "secret", {"v": "propre-a-B"})
    with forge_tenant.tenant_scope(a_id):
        assert forge_store.get("cfg", "secret")["v"] == "propre-a-A"  # A intact


def test_deux_tokens_run_isole_via_http(env):
    """Au niveau /v1 : un run de A est 404 pour B (jeton réel résolu par forge_identity)."""
    _, tok_a = env.new_tenant("a")
    _, tok_b = env.new_tenant("b")
    r = env.client.post("/v1/agents/run", json={"task": "secret de A"},
                        headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    r = env.client.get(f"/v1/runs/{run_id}", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404
    r = env.client.get(f"/v1/runs/{run_id}", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200


# ── Quota 429 pour A, sans dégrader B ─────────────────────────────────────────
def test_quota_429_pour_A_sans_degrader_B(env):
    a_id, tok_a = env.new_tenant("a")
    _, tok_b = env.new_tenant("b")
    forge_quota.set_limits(a_id, requests=2)          # A : 2 requêtes/fenêtre

    codes_a = [env.client.post("/v1/agents/run", json={"task": "x"},
                               headers={"Authorization": f"Bearer {tok_a}"}).status_code
               for _ in range(3)]
    assert codes_a == [202, 202, 429], codes_a        # la 3e franchit la limite

    # B n'a pas de limite basse : il n'est PAS dégradé par le blocage de A.
    r_b = env.client.post("/v1/agents/run", json={"task": "y"},
                          headers={"Authorization": f"Bearer {tok_b}"})
    assert r_b.status_code == 202, r_b.text


# ── Provisioning admin (rôle opérateur ≠ jeton tenant) ────────────────────────
def test_admin_refuse_sans_jeton_operateur(env, monkeypatch):
    monkeypatch.delenv("FORGE_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("FORGE_WEB_ALLOW_INSECURE", raising=False)
    r = env.client.post("/v1/admin/tenants", json={"tenant_id": "t-nope"})
    assert r.status_code == 403


def test_admin_provisionne_un_tenant_utilisable(env, monkeypatch):
    monkeypatch.setenv("FORGE_ADMIN_TOKEN", "op-secret")
    tid = f"t-prov-{uuid.uuid4().hex[:8]}"
    # jeton tenant ≠ jeton opérateur : un jeton tenant ne doit pas ouvrir l'admin
    _, tok_a = env.new_tenant("a")
    r = env.client.post("/v1/admin/tenants", json={"tenant_id": tid},
                        headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 403

    r = env.client.post("/v1/admin/tenants", json={"tenant_id": tid, "limits": {"requests": 5}},
                        headers={"Authorization": "Bearer op-secret"})
    assert r.status_code == 201, r.text
    new_token = r.json()["token"]
    try:
        # le jeton fraîchement émis résout et ouvre les routes tenant
        r = env.client.get("/v1/metrics", headers={"Authorization": f"Bearer {new_token}"})
        assert r.status_code == 200
        # il apparaît dans la vue opérateur
        r = env.client.get("/v1/admin/tenants", headers={"Authorization": "Bearer op-secret"})
        assert any(t["tenant"] == tid for t in r.json()["tenants"])
        # révocation : le jeton cesse d'être valide
        r = env.client.post(f"/v1/admin/tenants/{tid}/tokens", json={"action": "revoke"},
                            headers={"Authorization": "Bearer op-secret"})
        assert r.status_code == 200
        r = env.client.get("/v1/metrics", headers={"Authorization": f"Bearer {new_token}"})
        assert r.status_code == 401
    finally:
        import shutil
        shutil.rmtree(TENANTS_ROOT / tid, ignore_errors=True)


# ── Isolation entre PROCESSUS distincts (repli fichier) ───────────────────────
_WORKER = r"""
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "00_CORE"))
from forge_agents import forge_tenant, forge_store
tid, secret = sys.argv[2], sys.argv[3]
with forge_tenant.tenant_scope(tid):
    forge_store.put("cfg", "secret", {"owner": tid, "v": secret})
    # depuis SON scope, ce process ne voit que sa propre valeur
    print(forge_store.get("cfg", "secret")["v"])
"""


def test_isolation_multiprocess(tmp_path):
    """Deux PROCESSUS écrivent chacun sous leur tenant : aucune fuite croisée sur disque."""
    a = f"t-mp-a-{uuid.uuid4().hex[:8]}"
    b = f"t-mp-b-{uuid.uuid4().hex[:8]}"
    worker = tmp_path / "worker.py"
    worker.write_text(_WORKER, encoding="utf-8")
    try:
        out_a = subprocess.run([sys.executable, str(worker), str(ROOT), a, "valeur-A"],
                               capture_output=True, text=True, timeout=60)
        out_b = subprocess.run([sys.executable, str(worker), str(ROOT), b, "valeur-B"],
                               capture_output=True, text=True, timeout=60)
        assert out_a.returncode == 0, out_a.stderr
        assert out_b.returncode == 0, out_b.stderr
        assert out_a.stdout.strip() == "valeur-A"
        assert out_b.stdout.strip() == "valeur-B"

        # Sur disque : chaque secret vit dans l'espace de SON tenant, et nulle part ailleurs.
        sec_a = json.loads((TENANTS_ROOT / a / "cfg" / "secret").read_text(encoding="utf-8"))
        sec_b = json.loads((TENANTS_ROOT / b / "cfg" / "secret").read_text(encoding="utf-8"))
        assert sec_a == {"owner": a, "v": "valeur-A"}
        assert sec_b == {"owner": b, "v": "valeur-B"}
        assert not (TENANTS_ROOT / a / "cfg" / "secret").read_text().count("valeur-B")
    finally:
        import shutil
        for tid in (a, b):
            shutil.rmtree(TENANTS_ROOT / tid, ignore_errors=True)
