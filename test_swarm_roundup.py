"""Ce que le round-up MiMo coûte au swarm — et ce que le batcher en récupère vraiment.

POURQUOI CES TESTS EXISTENT (S-05)
----------------------------------
Le plan du sprint disait : « `run_swarm` appelle `mimo_call` une fois par unité, une
unité de 200 tokens réels est facturée 1000, donc brancher `MimoBatcher` est LE levier
de coût du dépôt ». Mesuré sur le corpus réel, c'est à moitié faux :

  - le round-up coûte bien cher — de l'ordre de **+20 % du facturé** ;
  - mais les unités de code pèsent ~3 000 tokens, pas 200. `MimoBatcher` auto-flushe dès
    que l'entrée en attente atteint `max_block_tokens` (4 blocs par défaut), donc il
    grouperait **1,8 unité par appel** et ne récupérerait que ~2 %.

Le levier n'est donc pas « brancher le batcher », c'est « brancher le batcher **avec un
seuil d'auto-flush relevé** » (~16 blocs → ~16 %, puis ça sature). Ces tests verrouillent
ce raisonnement pour qu'un futur S-06 ne rebranche pas le batcher au réglage par défaut
en croyant avoir corrigé quelque chose.

On assert des RELATIONS, pas des valeurs absolues : les fichiers du dépôt bougent, et un
test qui fige `8 917 tokens` deviendrait rouge sans qu'aucun bug n'apparaisse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.forge_swarm import (  # noqa: E402
    FileAudit, _cost_block, estimate_round_up,
)

#: Fichiers réels, stables, et assez gros pour produire des unités représentatives.
CORPUS = [
    "00_CORE/forge_agents/mimo_budget.py",
    "00_CORE/forge_agents/forge_quota.py",
    "00_CORE/forge_agents/forge_mimo.py",
]


# ── Le bloc `cost` d'un run : facturé VS réel ────────────────────────────────
def test_cost_block_expose_l_ecart_entre_facture_et_reel():
    """Sans cet écart, le gain d'une optimisation future ne serait pas démontrable."""
    audits = [
        FileAudit(file="a.py", billed_tokens=3000, real_tokens=1500, calls=1),
        FileAudit(file="b.py", billed_tokens=2000, real_tokens=1900, calls=1),
    ]
    c = _cost_block(audits)
    assert c["mimo_billed_tokens"] == 5000
    assert c["mimo_real_tokens"] == 3400
    assert c["round_up_overhead_tokens"] == 1600
    assert c["round_up_overhead_pct"] == pytest.approx(47.1, abs=0.1)
    assert c["mimo_calls"] == 2


def test_cost_block_ne_divise_pas_par_zero_sur_un_run_vide():
    c = _cost_block([])
    assert c["round_up_overhead_pct"] == 0.0
    assert c["mimo_billed_tokens"] == 0


# ── L'estimation, qui remplace le run témoin quand la clé MiMo manque ────────
def test_estimation_ne_depense_aucun_token(monkeypatch):
    """Garde-fou : cette fonction ne doit JAMAIS appeler MiMo. Elle sert précisément à
    chiffrer le coût là où l'on ne veut pas — ou ne peut pas — payer."""
    from forge_agents import forge_mimo

    def _interdit(*_a, **_kw):
        raise AssertionError("estimate_round_up a appelé MiMo — elle doit rester gratuite")

    monkeypatch.setattr(forge_mimo, "mimo_call", _interdit)
    monkeypatch.setattr(forge_mimo, "_client", _interdit)
    e = estimate_round_up(CORPUS)
    assert e["units"] >= len(CORPUS)


def test_le_facture_est_toujours_superieur_ou_egal_au_reel():
    e = estimate_round_up(CORPUS)
    assert e["naive_billed_tokens"] >= e["real_tokens"]
    assert e["naive_overhead_tokens"] == e["naive_billed_tokens"] - e["real_tokens"]
    assert e["naive_overhead_pct"] > 0, "un round-up au bloc coûte forcément quelque chose"


def test_l_estimation_distingue_ce_qui_est_mesure_de_ce_qui_est_assume():
    """Le point le plus important du rapport : ne pas faire passer une hypothèse sur la
    longueur des réponses pour une facture constatée."""
    e = estimate_round_up(CORPUS, out_tokens_per_unit=600)
    assert e["measured"]["in_tokens"] > 0
    assert e["assumed"]["out_tokens_per_unit"] == 600
    assert e["assumed"]["out_tokens"] == 600 * e["units"]
    assert e["real_tokens"] == e["measured"]["in_tokens"] + e["assumed"]["out_tokens"]
    assert "ASSUM" in e["note"].upper()


def test_un_fichier_absent_est_signale_pas_avale():
    e = estimate_round_up(CORPUS + ["00_CORE/n_existe_pas_du_tout.py"])
    assert "00_CORE/n_existe_pas_du_tout.py" in e["files_skipped"]


# ── LE constat qui pilote S-06 ───────────────────────────────────────────────
def test_le_batcher_au_reglage_par_defaut_ne_recupere_presque_rien():
    """Sur des unités de code, le batcher par défaut groupe à peine plus d'une unité.

    C'est le test qui empêche de « corriger » S-06 en branchant le batcher tel quel :
    au seuil par défaut, il ne rend quasiment pas de tokens.
    """
    e = estimate_round_up(CORPUS)   # seuil par défaut = 4 blocs
    assert e["batched_items_per_call"] < 3, (
        "si le batcher groupait beaucoup au réglage par défaut, le raisonnement de "
        "S-06 changerait — re-mesurer avant de conclure"
    )


def test_relever_le_seuil_d_auto_flush_est_ce_qui_rend_le_batching_rentable():
    """Le vrai levier, chiffré : plus de tokens par paquet = moins de round-ups payés."""
    from forge_agents.forge_mimo import token_block

    bas = estimate_round_up(CORPUS, batch_max_block_tokens=token_block() * 4)
    haut = estimate_round_up(CORPUS, batch_max_block_tokens=token_block() * 64)

    assert haut["batched_calls"] <= bas["batched_calls"]
    assert haut["batched_billed_tokens"] <= bas["batched_billed_tokens"]
    assert haut["savings_tokens"] >= bas["savings_tokens"]
    # Le gain est borné par le gaspillage total : on ne peut pas économiser plus que
    # ce que le round-up a coûté.
    assert haut["savings_tokens"] <= bas["naive_overhead_tokens"]


def test_les_paquets_simules_respectent_le_seuil_du_vrai_batcher():
    """La projection doit modéliser `MimoBatcher.add`, pas un découpage arbitraire :
    un groupe se ferme dès que l'entrée accumulée atteint le seuil (donc au plus un
    item de dépassement)."""
    from forge_agents.forge_mimo import token_block

    seuil = token_block() * 4
    e = estimate_round_up(CORPUS, batch_max_block_tokens=seuil)
    assert e["batch_max_block_tokens"] == seuil
    assert e["batched_calls"] >= 1
    assert e["batched_calls"] <= e["units"], "batcher ne peut pas faire PLUS d'appels que d'unités"
