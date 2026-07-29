"""Le compteur de budget MiMo dit-il la vérité, et refuse-t-il de dépenser au-delà du plan ?

Ce module est la condition d'exécution de S-07 (garde-fou) et de S-24 (retrait de ds2api /
Groq) : tant qu'il n'existe aucun compteur, basculer le repli sur MiMo transformerait un
incident Claude en fuite budgétaire invisible. Ce qui est vérifié ici, c'est donc moins
« le calcul est juste » que **« le module ne peut pas mentir dans le sens qui coûte »** :

  - le point de départ déclaré ne se re-compte pas tous les mois ;
  - un dépassement LÈVE (comme `forge_quota`), il ne tronque pas en silence ;
  - un ledger corrompu ne redevient pas un solde vierge sans le dire ;
  - `report()["source"]` ne prétend jamais « mesuré » quand rien n'a été mesuré.

Le ledger est redirigé vers `tmp_path` : aucun test ne touche au compteur réel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents import mimo_budget as mb  # noqa: E402

#: Emplacement RÉEL du ledger, capturé à l'import — avant que la fixture ne le détourne
#: vers `tmp_path`. C'est lui qu'on veut vérifier, pas le fichier jetable des tests.
REAL_LEDGER = mb.LEDGER_FILE


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """Ledger jetable + config déterministe (plan 10 000, départ 1 000 ce mois-ci)."""
    monkeypatch.setattr(mb, "LEDGER_FILE", tmp_path / "mimo_budget.json")
    monkeypatch.setenv("MIMO_MONTHLY_TOKENS", "10000")
    monkeypatch.setenv("MIMO_BASELINE_TOKENS", "1000")
    monkeypatch.setenv("MIMO_BASELINE_PERIOD", mb.current_period())
    monkeypatch.setenv("MIMO_USAGE_URL", "")          # aucun appel réseau
    monkeypatch.setenv("MIMO_ALERT_PCT", "80")
    mb._remote_cache.update({"ts": 0.0, "value": None})
    yield


def test_point_de_depart_ne_vaut_que_pour_son_mois():
    # Sinon les 4 Md déjà consommés seraient re-décomptés chaque mois et le solde
    # affiché ne remonterait jamais — un plan mensuel qui ne se recharge pas.
    assert mb.used() == 1000
    assert mb.baseline_for("1999-01") == 0


def test_le_ledger_mesure_le_facture_et_le_reel():
    mb.record(2000, real_tokens=1200)
    mb.record(3000, real_tokens=1500)
    led = mb.ledger()
    assert led["calls"] == 2
    assert led["billed_tokens"] == 5000
    # Le réel est gardé À CÔTÉ du facturé : c'est l'écart qui chiffre le round-up (S-05/S-06).
    assert led["real_tokens"] == 2700
    assert mb.used() == 6000       # 1000 déclarés + 5000 mesurés


def test_depassement_leve_au_lieu_de_tronquer():
    mb.record(8000)
    with pytest.raises(mb.BudgetExceeded) as exc:
        mb.check(2000)
    assert exc.value.limit == 10000
    assert exc.value.used == 11000
    assert exc.value.period == mb.current_period()


def test_mode_observation_ne_leve_pas():
    mb.record(9500)
    assert mb.check(5000, enforce=False) == 15500   # compte, ne bloque pas


def test_ledger_corrompu_ne_devient_pas_un_solde_vierge():
    mb.LEDGER_FILE.write_text("{ pas du json", encoding="utf-8")
    # Le compteur mesuré repart à zéro (on ne peut pas inventer ce qui est perdu), mais le
    # point de départ déclaré, lui, tient : le solde ne remonte pas à 100 % par accident.
    assert mb.ledger()["billed_tokens"] == 0
    assert mb.used() == 1000


def test_report_ne_pretend_pas_mesurer_quand_rien_n_est_mesure():
    r = mb.report()
    assert r["source"] == "declared"          # aucun appel encore : on le DIT
    assert r["calls"] == 0
    assert r["measured_since"] is None
    mb.record(4000, real_tokens=3000)
    r2 = mb.report()
    assert r2["source"] == "local"            # désormais mesuré ici
    assert r2["remaining_tokens"] == 5000
    assert r2["measured_since"] is not None


def test_seuil_d_alerte_bascule_au_bon_moment():
    mb.record(6900)                            # 7900 / 10000 = 79 %
    assert mb.report()["over_alert"] is False
    mb.record(200)                             # 8100 / 10000 = 81 %
    assert mb.report()["over_alert"] is True


def test_remote_desactive_sans_url_configuree():
    # On ne devine pas l'endpoint fournisseur : sans URL, aucun appel, source locale.
    assert mb.remote_usage() is None
    mb.record(100)
    assert mb.report()["source"] == "local"


def test_un_appel_mimo_debite_reellement_le_plan(monkeypatch):
    """Le maillon qui fait la différence entre un compteur et une décoration.

    `mimo_call` est le point de passage UNIQUE (batcher, swarm, judge y aboutissent
    tous) : si le débit n'a pas lieu là, le solde affiché reste figé sur la déclaration
    et on redécouvre la consommation à la facture. Ici le client HTTP est doublé —
    aucun token réel n'est dépensé pour prouver qu'on sait les compter.
    """
    from forge_agents import forge_mimo

    class _Msg:
        content = "réponse"

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})()]
        usage = type("U", (), {"prompt_tokens": 1200, "completion_tokens": 300})()

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**_kwargs):
                    return _Resp()

    monkeypatch.setenv("MIMO_API_KEY", "clé-de-test")
    monkeypatch.setenv("MIMO_TOKEN_BLOCK", "1000")
    monkeypatch.setattr(forge_mimo, "_client", lambda: _FakeClient())

    assert mb.ledger()["calls"] == 0
    _text, m = forge_mimo.mimo_call("prompt de test")

    # 1200 in et 300 out, arrondis au bloc de 1000 : 2000 + 1000 = 3000 facturés
    assert m["billed_tokens"] == 3000
    led = mb.ledger()
    assert led["calls"] == 1
    assert led["billed_tokens"] == 3000
    assert led["real_tokens"] == 1500          # le réel, pour chiffrer le round-up
    assert mb.used() == 4000                   # 1000 déclarés + 3000 mesurés


def test_un_ledger_casse_ne_fait_pas_echouer_l_appel_llm(monkeypatch):
    """Un appel déjà payé ne doit jamais être perdu parce que la comptabilité coince."""
    from forge_agents import forge_mimo

    def _boom(*_a, **_kw):
        raise OSError("disque plein")

    monkeypatch.setattr(mb, "record", _boom)
    forge_mimo._record_budget(3000, 1500)      # absorbe, ne lève pas


def test_le_ledger_est_hors_de_l_espace_tenant():
    # Le plan est commun à tous les tenants : le cloisonner donnerait à chacun son propre
    # « 11 Md restants ». Le fichier vit donc à côté des quotas, pas dans 05_STATE/tenants.
    assert "tenants" not in REAL_LEDGER.parts
    assert REAL_LEDGER.parent.name == "identity"      # à côté de quotas.json
    # et le contenu est bien indexé par mois, pas par tenant
    mb.record(1)
    written = json.loads(mb.LEDGER_FILE.read_text(encoding="utf-8"))
    assert list(written["periods"]) == [mb.current_period()]
