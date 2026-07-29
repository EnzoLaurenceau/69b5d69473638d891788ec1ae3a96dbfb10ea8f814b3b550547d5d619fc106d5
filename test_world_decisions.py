"""Tests E2-06 — journal des décisions de design (ADR jeu).

Deux étages, même découpage qu'E2-02 :

1. **Pur** — sérialisation des listes, lecture du label depuis la clé, et les
   préconditions d'ontologie du ticket (`DesignDecision` et les couples
   `DERIVED_FROM` doivent exister AVANT qu'on câble quoi que ce soit).
2. **Moteur** — le journal contre un vrai Kùzu. Ce qui est vérifié ici n'est pas
   « une décision s'écrit » mais « le journal ne ment pas » : `link()` renvoie
   `True` sur une cible inexistante et duplique les arêtes appelé deux fois. Un
   journal de traçabilité qui hérite de ces deux comportements revendique une
   traçabilité qu'il n'a pas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.world_decisions import (  # noqa: E402
    DECISION_LABEL,
    SUPERSEDES,
    DecisionJournal,
    UntraceableDecisionError,
    label_of,
    split_list,
)
from forge_agents.world_kg import (  # noqa: E402
    WORLD_EDGE_PAIRS,
    WORLD_NODE_TABLES,
    DuplicateEntityError,
    WorldKG,
    reset_world_kg,
    world_key,
)

kuzu = pytest.importorskip("kuzu", reason="E2-06 se vérifie contre le vrai moteur")


# ── Étage 1 : sans moteur ────────────────────────────────────────────────────

def test_lontologie_du_ticket_existe_deja():
    """E2-06 est du câblage : s'il doit créer un label, c'est qu'il déborde."""
    assert DECISION_LABEL in WORLD_NODE_TABLES


def test_une_entite_peut_deriver_dune_decision():
    """Sans ce couple, `affects` ne peut rien relier."""
    assert ("Character", DECISION_LABEL) in WORLD_EDGE_PAIRS["DERIVED_FROM"]


def test_une_decision_peut_deriver_dune_decision():
    """C'est ce qui rend la révision représentable sans toucher au schéma."""
    assert (DECISION_LABEL, DECISION_LABEL) in WORLD_EDGE_PAIRS["DERIVED_FROM"]


@pytest.mark.parametrize("brut,attendu", [
    (None, []),
    ("", []),
    ("a|b", ["a", "b"]),
    (["a", "b"], ["a", "b"]),
    ("mort douce, sans perte", ["mort douce, sans perte"]),   # virgule NON séparatrice
])
def test_les_alternatives_se_lisent_sous_toutes_leurs_formes(brut, attendu):
    assert split_list(brut) == attendu


def test_le_label_se_lit_dans_la_cle():
    assert label_of(world_key("urth", DECISION_LABEL, "perma-mort")) == DECISION_LABEL


def test_une_cle_malformee_ne_fait_pas_planter_la_lecture_du_label():
    """`neighbors()` peut remonter n'importe quoi ; un `split` optimiste ferait
    lever une IndexError au milieu d'un parcours."""
    assert label_of("n-importe-quoi") == ""
    assert label_of("") == ""


# ── Étage 2 : le journal contre le vrai moteur ──────────────────────────────

@pytest.fixture(autouse=True)
def _connexions_propres():
    """`_CONNECTIONS` (E2-01) n'évince jamais — cf. `test_world_kg_identity`."""
    yield
    reset_world_kg()


@pytest.fixture()
def kg(tmp_path) -> WorldKG:
    return WorldKG(world_id="test-decisions", db_path=tmp_path / "world")


@pytest.fixture()
def monde(kg) -> tuple[WorldKG, DecisionJournal]:
    """Un monde minimal : deux PNJ (dont un avec alias) et une quête."""
    kg.add_character("Severian", role="protagoniste")
    kg.add_character("Thecla", aliases=["la chatelaine"])
    kg.add_quest("La Griffe", act=1)
    return kg, DecisionJournal(kg)


def test_une_decision_se_relie_a_ce_quelle_produit(monde):
    _, j = monde
    res = j.decide("perma-mort", question="Mort définitive ?", choice="Oui",
                   affects=[("Character", "Severian"), ("Quest", "La Griffe")])
    assert res["linked"] == 2
    assert [d["name"] for d in j.why("Character", "Severian")] == ["perma-mort"]
    assert {a["name"] for a in j.affected_by("perma-mort")} == {"Severian", "La Griffe"}


def test_une_cible_inconnue_refuse_la_decision_entiere(monde):
    """`link()` renvoie `True` sur une cible absente sans rien créer (vérifié
    contre le moteur). Écrire la décision quand même produirait un journal qui
    revendique une traçabilité inexistante — tout ou rien."""
    _, j = monde
    with pytest.raises(UntraceableDecisionError) as err:
        j.decide("perma-mort", affects=[("Character", "Severian"),
                                        ("Character", "Personne")])
    assert err.value.missing == [("Character", "Personne")]
    assert j.get("perma-mort") is None
    assert j.why("Character", "Severian") == []   # la cible valide non plus


def test_un_alias_suffit_a_designer_la_cible(monde):
    """Acquis d'E2-02 : `resolve()` connaît « la chatelaine »."""
    _, j = monde
    res = j.decide("noblesse", affects=[("Character", "la chatelaine")])
    assert res["affects"] == [("Character", "Thecla")]
    assert [d["name"] for d in j.why("Character", "Thecla")] == ["noblesse"]


def test_redeclarer_une_decision_ne_duplique_pas_les_aretes(monde):
    """`link()` appelé deux fois crée deux arêtes : `why()` afficherait alors
    deux fois la même décision."""
    _, j = monde
    j.decide("perma-mort", affects=[("Character", "Severian")])
    res = j.decide("perma-mort", affects=[("Character", "Severian")])
    assert res["linked"] == 0
    assert len(j.why("Character", "Severian")) == 1
    assert len(j.affected_by("perma-mort")) == 1


def test_une_redeclaration_partielle_neffece_pas_le_pourquoi(monde):
    """Le défaut trouvé au premier jet : re-déclarer en ne précisant que le
    `choice` effaçait rationale, alternatives et auteur. Pour un journal dont le
    produit EST le « pourquoi », c'est la pire perte possible."""
    _, j = monde
    j.decide("perma-mort", question="Mort définitive ?", choice="Oui",
             rationale="La tension retombe sinon",
             alternatives=["mort douce", "checkpoints"], decided_by="game-design")
    j.decide("perma-mort", choice="Oui, hors sanctuaire")

    node = j.get("perma-mort")
    assert node["choice"] == "Oui, hors sanctuaire"        # bien mis à jour
    assert node["rationale"] == "La tension retombe sinon"  # et rien de perdu
    assert node["decided_by"] == "game-design"
    assert split_list(node["alternatives"]) == ["mort douce", "checkpoints"]


def test_une_decision_validee_ne_retombe_pas_en_draft(monde):
    """Même piège que ci-dessus, sur le champ d'état : `status` a une valeur par
    défaut, et une valeur par défaut écrase."""
    _, j = monde
    j.decide("perma-mort", choice="Oui", status="validated")
    j.decide("perma-mort", rationale="précision tardive")
    assert j.get("perma-mort")["status"] == "validated"


def test_why_ignore_les_filiations_qui_ne_sont_pas_des_decisions(monde):
    """`DERIVED_FROM` relie aussi une entité à une `LoreRule`. Le journal ne doit
    remonter que les décisions, pas tout ce dont l'entité découle."""
    kg, j = monde
    kg.add_lore_rule("magie-rare", statement="La magie coûte cher", hard=True)
    kg.link("DERIVED_FROM", "Character", "Severian", "LoreRule", "magie-rare")
    j.decide("perma-mort", affects=[("Character", "Severian")])
    assert [d["name"] for d in j.why("Character", "Severian")] == ["perma-mort"]


def test_une_revision_remplace_sans_ecraser(monde):
    """Un journal qui s'écrase n'est pas un journal : l'ancienne décision reste
    lisible, avec ce qu'elle avait produit."""
    _, j = monde
    j.decide("perma-mort", choice="Oui hors sanctuaire",
             affects=[("Character", "Severian")])
    j.decide("perma-mort v2", choice="Oui partout", supersedes="perma-mort",
             allow_similar=True, affects=[("Quest", "La Griffe")])

    assert j.superseded_by("perma-mort") == ["perma-mort v2"]
    assert j.superseded_by("perma-mort v2") == []
    assert j.supersede_chain("perma-mort v2") == ["perma-mort v2", "perma-mort"]
    assert j.get("perma-mort")["choice"] == "Oui hors sanctuaire"
    assert {a["name"] for a in j.affected_by("perma-mort")} == {"Severian"}


def test_la_decision_qui_remplace_nest_pas_une_consequence(monde):
    """Elle pointe vers l'ancienne par la même arête `DERIVED_FROM` — la
    confondre avec une conséquence de design fausserait `affected_by`."""
    _, j = monde
    j.decide("perma-mort", affects=[("Character", "Severian")])
    j.decide("perma-mort v2", supersedes="perma-mort", allow_similar=True)
    noms = {a["name"] for a in j.affected_by("perma-mort")}
    assert noms == {"Severian"}
    assert "perma-mort v2" not in noms


def test_remplacer_une_decision_inexistante_leve(monde):
    _, j = monde
    with pytest.raises(UntraceableDecisionError):
        j.decide("perma-mort v2", supersedes="jamais-prise")
    assert j.get("perma-mort v2") is None


def test_une_revision_au_nom_proche_reste_un_acte_delibere(monde):
    """E2-06 hérite de l'unicité d'E2-02 : « perma-mort v2 » ressemble assez à
    « perma-mort » pour être refusée. C'est voulu — une révision se déclare."""
    _, j = monde
    j.decide("perma-mort", choice="Oui")
    with pytest.raises(DuplicateEntityError):
        j.decide("perma-mort v2", choice="Oui partout", supersedes="perma-mort")


def test_un_cycle_de_revisions_ne_boucle_pas(monde):
    """Donnée absurde mais possible ; une boucle infinie serait une très
    mauvaise façon de la signaler."""
    _, j = monde
    j.decide("alpha", choice="a")
    j.decide("omega", choice="o", supersedes="alpha")
    j.decide("alpha", supersedes="omega")
    chaine = j.supersede_chain("alpha")
    assert chaine == ["alpha", "omega"]


def test_les_decisions_sans_consequence_sont_visibles(monde):
    """Une décision qui ne produit rien est soit non appliquée, soit un
    `affects` oublié. Les deux méritent d'être vues."""
    _, j = monde
    j.decide("perma-mort", affects=[("Character", "Severian")])
    j.decide("ton-general", choice="Sombre")
    assert j.orphans() == ["ton-general"]


def test_le_journal_distingue_ce_qui_est_en_vigueur(monde):
    _, j = monde
    j.decide("alpha", choice="a")
    j.decide("omega", choice="o", supersedes="alpha")
    courantes = [r["name"] for r in j.journal() if r["current"]]
    assert courantes == ["omega"]
    assert [r["name"] for r in j.journal(include_superseded=False)] == ["omega"]


def test_le_rendu_porte_le_pourquoi_et_marque_les_remplacees(monde):
    """Le document est une VUE : ce qu'il montre doit venir du graphe."""
    _, j = monde
    j.decide("perma-mort", question="Mort définitive ?", choice="Oui",
             rationale="La tension retombe sinon", alternatives=["mort douce"],
             decided_by="game-design", affects=[("Character", "Severian")])
    j.decide("perma-mort v2", choice="Oui partout", supersedes="perma-mort",
             allow_similar=True)
    texte = j.render()
    assert "La tension retombe sinon" in texte
    assert "mort douce" in texte
    assert "Character « Severian »" in texte
    assert "⟨remplacée⟩" in texte
    assert "1 en vigueur" in texte


def test_un_monde_sans_decision_se_rend_quand_meme(monde):
    """Un journal vide doit le dire, pas planter ni rendre un titre orphelin."""
    _, j = monde
    assert "Aucune décision enregistrée" in j.render()


def test_le_marqueur_de_revision_est_porte_par_larete(monde):
    """Vérifie le choix d'archi : la révision est une arête, pas un champ — donc
    aucune constante d'E2-01 (`STATUS_KINDS`) n'a eu à bouger."""
    kg, j = monde
    j.decide("alpha", choice="a")
    j.decide("omega", choice="o", supersedes="alpha")
    aretes = [nb for nb in kg.neighbors(DECISION_LABEL, "omega")
              if nb["edge"] == "DERIVED_FROM" and nb["dir"] == "out"]
    assert [nb["context"] for nb in aretes] == [SUPERSEDES]
