"""Tests E2-04 — GDD vivant généré depuis le graphe.

Deux étages, même découpage qu'E2-02 et E2-06 — mais le skip Kùzu est posé dans
la FIXTURE, pas en tête de module (comme `test_world_kg.py`) : l'invariant le
plus important du ticket — aucun type du monde ne peut disparaître du document —
est une propriété pure, et il serait absurde qu'il cesse d'être vérifié parce
que le moteur manque dans l'interpréteur.

1. **Pur** — l'exhaustivité des sections, le vocabulaire de statuts emprunté à
   E2-01, les clés de tri (dont celle qui empêche un `chrono` absent de lever),
   et le verrou d'intégrité.
2. **Moteur** — le document contre un vrai Kùzu. Ce qui est vérifié ici n'est
   pas « un GDD se rend » mais **« le document ne ment pas »** : ce qu'il cache
   est compté, ce qu'il tronque est dit, ses trous sont réels (pas de faux
   positif) et deux générations d'un monde inchangé donnent les mêmes octets.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.world_decisions import (  # noqa: E402
    DECISION_LABEL,
    DecisionJournal,
)
from forge_agents.world_gdd import (  # noqa: E402
    HIDDEN_STATUS,
    MARKED_STATUS,
    HandEditedGDDError,
    LivingGDD,
    _body_hash,
    _chrono_key,
    _detect_hand_edit,
    _SECTIONS,
    _sort_key,
    _text,
    _with_lock,
    visible,
)
from forge_agents.world_kg import (  # noqa: E402
    STATUS_KINDS,
    WORLD_NODE_TABLES,
    WorldKG,
    reset_world_kg,
)


# ── Étage 1 : sans moteur ────────────────────────────────────────────────────

def test_chaque_type_du_monde_est_range_dans_une_section():
    """L'invariant du ticket. Un 11ᵉ type ajouté à E2-01 et oublié ici
    disparaîtrait du GDD en silence — et un document ne dit pas ce qu'il ne
    contient pas, donc personne ne le verrait."""
    ranges = [lbl for s in _SECTIONS for lbl in s.labels]
    assert sorted(ranges) == sorted(WORLD_NODE_TABLES)


def test_aucun_type_nest_range_deux_fois():
    """Le rendre deux fois ferait un document qui se contredit lui-même."""
    ranges = [lbl for s in _SECTIONS for lbl in s.labels]
    assert len(ranges) == len(set(ranges))


def test_aucune_section_ne_range_un_type_inexistant():
    for section in _SECTIONS:
        for label in section.labels:
            assert label in WORLD_NODE_TABLES, f"{section.key} range {label}"


def test_les_statuts_viennent_du_vocabulaire_de_e2_01():
    """`HIDDEN_STATUS`/`MARKED_STATUS` ne créent pas de vocabulaire : ils
    choisissent dans celui d'E2-01. Une faute de frappe deviendrait sinon un
    statut muet qui ne cache et ne signale rien."""
    assert set(HIDDEN_STATUS) <= set(STATUS_KINDS)
    assert set(MARKED_STATUS) <= set(STATUS_KINDS)


def test_le_brouillon_nest_pas_le_statut_signale():
    """`draft` est la valeur PAR DÉFAUT d'`upsert()` : le signaler pose un badge
    sur presque tout le monde (mesuré : 11 entités sur 13), et un marqueur
    universel apprend au lecteur à l'ignorer."""
    assert "draft" not in MARKED_STATUS
    assert "validated" in MARKED_STATUS


@pytest.mark.parametrize("status,attendu", [
    ("cut", False),
    ("draft", True),
    ("validated", True),
    ("", True),          # écrite avant que le vocabulaire ne soit fixé
    (None, True),
    ("CUT", False),      # la casse ne doit pas rouvrir la porte
])
def test_seul_ce_qui_est_explicitement_ecarte_disparait(status, attendu):
    assert visible({"status": status}) is attendu


@pytest.mark.parametrize("brut,attendu", [
    (None, ""),          # sondé : une propriété non fournie revient à None
    ("", ""),
    (True, "oui"),
    (False, ""),
    (12, "12"),
    ("  x  ", "x"),
    (["a", "b"], "a, b"),
])
def test_une_propriete_absente_ne_secrit_pas_none_dans_le_document(brut, attendu):
    assert _text(brut) == attendu


def test_un_evenement_sans_rang_ne_fait_pas_lever_le_tri():
    """Sondé : `chrono` non fourni revient à `None`, et `sorted([10, None])`
    lève un TypeError qui emporterait le document entier pour un seul
    événement mal saisi."""
    rangs = [{"name": "b", "chrono": 2}, {"name": "sans", "chrono": None},
             {"name": "a", "chrono": 1}]
    assert [e["name"] for e in sorted(rangs, key=_chrono_key)] == ["a", "b", "sans"]


def test_le_tri_neutralise_les_accents():
    """Même normalisation que les clés d'E2-01 : « Sévérian » et « Severian »
    ne doivent pas se retrouver à deux endroits éloignés du document."""
    assert _sort_key({"name": "Sévérian"})[0] == _sort_key({"name": "Severian"})[0]


def test_un_document_genere_nest_pas_pris_pour_une_edition_humaine():
    edited, _ = _detect_hand_edit(_with_lock("# GDD\n\ncorps\n"))
    assert edited is False


def test_une_retouche_a_la_main_est_detectee():
    edited, raison = _detect_hand_edit(_with_lock("# GDD\n\ncorps\n") + "note humaine\n")
    assert edited is True
    assert "main" in raison


def test_un_fichier_etranger_est_traite_comme_ecrit_a_la_main():
    """On ne présume jamais qu'un fichier qu'on n'a pas écrit est jetable."""
    edited, raison = _detect_hand_edit("# Mon GDD écrit à la main\n")
    assert edited is True
    assert "gdd-lock" in raison


def test_un_aller_retour_crlf_ne_declenche_pas_le_garde():
    """Git (`core.autocrlf`) et les éditeurs Windows réécrivent les fins de
    ligne sans toucher au contenu : hacher les octets bruts ferait crier
    « édité à la main » au premier passage par le dépôt."""
    genere = _with_lock("# GDD\n\ncorps\n")
    assert _detect_hand_edit(genere.replace("\n", "\r\n"))[0] is False


def test_le_verrou_change_quand_le_corps_change():
    assert _body_hash("a") != _body_hash("b")


# ── Étage 2 : le document contre le vrai moteur ─────────────────────────────

@pytest.fixture(autouse=True)
def _connexions_propres():
    """`_CONNECTIONS` (E2-01) n'évince jamais — cf. `test_world_kg_identity`."""
    yield
    reset_world_kg()


@pytest.fixture()
def kg(tmp_path) -> WorldKG:
    pytest.importorskip("kuzu", reason="E2-04 se vérifie contre le vrai moteur")
    return WorldKG(world_id="test-gdd", db_path=tmp_path / "world")


@pytest.fixture()
def monde(kg) -> tuple[WorldKG, DecisionJournal, LivingGDD]:
    """Un monde minimal mais RÉALISTE : du validé, du brouillon, de l'écarté,
    un événement hors chronologie et une quête sans objectif."""
    kg.add_character("Severian", role="protagoniste", summary="Un bourreau exilé.",
                     status="validated")
    kg.add_character("Thecla")                                   # draft implicite
    kg.add_character("Agia", status="cut", summary="Retirée du jeu")
    kg.add_location("Nessus", kind="city", summary="Ville-fleuve.")
    kg.add_quest("La Griffe", act=1)                             # sans objectif
    kg.add_event("Chute", chrono=10, summary="Le soleil faiblit.")
    kg.add_event("Sans rang", summary="Mal saisi")                # sans chrono
    kg.link("LOCATED_IN", "Character", "Severian", "Location", "Nessus")
    journal = DecisionJournal(kg)
    journal.decide("perma-mort", question="Mort définitive ?", choice="Oui",
                   rationale="La tension retombe sinon",
                   alternatives=["mort douce", "checkpoints"],
                   status="validated", affects=[("Character", "Severian")])
    return kg, journal, LivingGDD(kg, journal)


def test_le_document_rend_le_monde(monde):
    _, _, gdd = monde
    doc = gdd.render()
    assert "Severian" in doc and "Nessus" in doc and "La Griffe" in doc


def test_une_entite_ecartee_nest_nulle_part_dans_le_document(monde):
    """Sinon `cut` ne veut rien dire."""
    _, _, gdd = monde
    assert "Agia" not in gdd.render()


def test_mais_le_document_dit_combien_il_en_a_ecarte(monde):
    """Omettre en silence serait mentir par soustraction."""
    _, _, gdd = monde
    data = gdd.build()
    assert data["hidden"] == 1
    assert "1 entité(s) écartée(s)" in gdd.render(data)


def test_seul_le_valide_est_marque(monde):
    _, _, gdd = monde
    entities = {e["name"]: e for s in gdd.build()["sections"] for e in s["entities"]}
    assert entities["Severian"]["marked"] is True
    assert entities["Thecla"]["marked"] is False


def test_le_pourquoi_du_document_est_celui_du_journal(monde):
    """Le GDD relit le voisinage qu'il tient déjà plutôt que d'appeler
    `why()` (qui ré-interrogerait le graphe deux fois par entité). Les deux
    lectures DOIVENT dire la même chose — c'est ce test qui rend la
    réutilisation du vocabulaire d'E2-06 sûre plutôt qu'approximative."""
    _, journal, gdd = monde
    entities = {e["name"]: e for s in gdd.build()["sections"] for e in s["entities"]}
    for nom in ("Severian", "Thecla"):
        attendu = sorted(d["name"] for d in journal.why("Character", nom))
        assert entities[nom]["because"] == attendu
    assert entities["Severian"]["because"] == ["perma-mort"]


def test_une_decision_nest_pas_une_entite_a_documenter(monde):
    """Le taux de traçabilité compare les entités du MONDE aux décisions. Y
    inclure les décisions elles-mêmes gonflerait le dénominateur avec des
    objets qui ne peuvent pas découler d'une décision."""
    _, _, gdd = monde
    data = gdd.build()
    assert data["decidable"] == data["total"] - 1        # la seule décision
    assert data["traced"] == 1


def test_la_chronologie_est_ordonnee_et_le_sans_rang_finit_a_la_fin(monde):
    """Régression du TypeError : un seul événement mal saisi emportait tout."""
    _, _, gdd = monde
    section = [s for s in gdd.build()["sections"] if s["key"] == "chronologie"][0]
    assert [e["name"] for e in section["entities"]] == ["Chute", "Sans rang"]


def test_deux_generations_dun_monde_inchange_donnent_les_memes_octets(monde):
    """Sans ça, le diff entre deux GDD ne montre plus ce qui a bougé dans le
    monde mais le bruit de l'horodatage — et le document cesse d'être lisible
    d'une session à l'autre, ce qui est tout l'objet du ticket."""
    _, _, gdd = monde
    assert gdd.render() == gdd.render()


def test_le_rendu_ne_reinterroge_pas_le_graphe(monde):
    """`render(data)` est une fonction de la vue seule : on peut re-rendre un
    `build()` déjà pris, et vérifier le contenu sans dépendre du moteur."""
    _, _, gdd = monde
    data = gdd.build()
    assert gdd.render(data) == gdd.render(data)


def test_un_document_tronque_le_dit(monde):
    """Sondé : `all_nodes(limit=2)` sur 3 entités en renvoie 2 sans un mot. Un
    GDD tronqué en silence EST le « document d'apparence complète » qu'on refuse."""
    _, _, gdd = monde
    data = gdd.build(limit=2)
    assert "Character" in data["truncated"]
    assert "tronqué" in gdd.render(data)
    assert any(g["kind"] == "troncature" for g in data["gaps"])


def test_les_trous_sont_nommes(monde):
    _, _, gdd = monde
    trous = {(g["kind"], g["name"]) for g in gdd.gaps()}
    assert ("quête sans objectif", "La Griffe") in trous
    assert ("événement hors chronologie", "Sans rang") in trous
    assert ("sans résumé", "Thecla") in trous


def test_une_entite_ecartee_ne_compte_pas_comme_un_trou(monde):
    """« Agia » n'est pas dans le document : lui reprocher un manque
    reviendrait à demander de compléter ce qu'on a décidé de retirer."""
    _, _, gdd = monde
    assert all(g["name"] != "Agia" for g in gdd.gaps())


def test_une_decision_documentee_nest_pas_un_trou(monde):
    """Un faux positif dans une liste de trous est pire qu'un trou manquant :
    il apprend à ne plus lire la liste. La substance d'une décision est son
    `rationale`, pas un `summary` que personne ne remplit."""
    _, _, gdd = monde
    assert all(g["name"] != "perma-mort" for g in gdd.gaps())


def test_une_decision_sans_justification_est_un_trou(monde):
    _, journal, gdd = monde
    journal.decide("mode-photo", question="Un mode photo ?", choice="Plus tard")
    trous = {(g["kind"], g["name"]) for g in gdd.gaps()}
    assert ("sans justification", "mode-photo") in trous
    assert ("décision sans conséquence", "mode-photo") in trous


def test_une_regle_dure_sans_enonce_nest_comptee_quune_fois(monde):
    """Elle relève de deux règles (substance manquante, règle inapplicable) ;
    la compter deux fois ferait douter du décompte entier."""
    kg, _, gdd = monde
    kg.add_lore_rule("Interdit majeur", hard=True)
    trous = [g for g in gdd.gaps() if g["name"] == "Interdit majeur"]
    assert len(trous) == 1
    assert trous[0]["kind"] == "règle dure sans énoncé"


def test_une_contradiction_se_lit_avec_des_noms_pas_des_cles(monde):
    """`contradictions()` ne rend que des clés internes (`monde:Label:slug`) :
    les afficher telles quelles montrerait la plomberie à un game designer."""
    kg, _, gdd = monde
    kg.add_lore_rule("Soleil eternel", hard=True, statement="Le soleil ne meurt pas.")
    kg.add_lore_rule("Soleil mourant", hard=True, statement="Le soleil s'éteint.")
    kg.link("CONTRADICTS", "LoreRule", "Soleil eternel", "LoreRule", "Soleil mourant")
    trou = [g for g in gdd.gaps() if g["kind"] == "contradiction"][0]
    assert "Soleil eternel" in trou["name"]
    assert "Soleil mourant" in trou["detail"]
    assert ":LoreRule:" not in trou["name"] + trou["detail"]


def test_le_format_de_stockage_des_alternatives_ne_fuit_pas(monde):
    """Elles sont sérialisées `a|b` (séparateur d'E2-02). Un document livré ne
    doit pas montrer ce format."""
    _, _, gdd = monde
    entities = {e["name"]: e for s in gdd.build()["sections"] for e in s["entities"]}
    assert entities["perma-mort"]["details"]["alternatives"] == "mort douce, checkpoints"


def test_un_monde_vide_le_dit_au_lieu_de_rendre_un_squelette(kg):
    """Un GDD d'apparence complète sur un monde vide fait croire le travail fait."""
    doc = LivingGDD(kg, DecisionJournal(kg)).render()
    assert "Le monde est vide" in doc


# ── Écriture : le document est une VUE ───────────────────────────────────────

def test_lecriture_pose_un_verrou_dintegrite(monde, tmp_path):
    _, _, gdd = monde
    cible = gdd.write(tmp_path / "gdd.md")
    assert cible.exists()
    assert _detect_hand_edit(cible.read_text(encoding="utf-8"))[0] is False


def test_regenerer_un_document_intact_est_sans_histoire(monde, tmp_path):
    _, _, gdd = monde
    cible = gdd.write(tmp_path / "gdd.md")
    assert gdd.write(cible) == cible


def test_regenerer_refuse_decraser_une_retouche_humaine(monde, tmp_path):
    """Perdre une fois le travail de quelqu'un suffit à ce que plus personne ne
    régénère — et un GDD qu'on ne régénère plus est mort."""
    _, _, gdd = monde
    cible = gdd.write(tmp_path / "gdd.md")
    cible.write_text(cible.read_text(encoding="utf-8") + "\nnote humaine\n",
                     encoding="utf-8")
    with pytest.raises(HandEditedGDDError) as err:
        gdd.write(cible)
    assert err.value.path == cible
    assert "note humaine" in cible.read_text(encoding="utf-8")   # rien n'a été perdu


def test_la_sortie_est_explicite_jamais_implicite(monde, tmp_path):
    _, _, gdd = monde
    cible = gdd.write(tmp_path / "gdd.md")
    cible.write_text("écrit à la main", encoding="utf-8")
    gdd.write(cible, force=True)
    assert "écrit à la main" not in cible.read_text(encoding="utf-8")


def test_un_fichier_preexistant_etranger_nest_pas_ecrase(monde, tmp_path):
    _, _, gdd = monde
    cible = tmp_path / "GDD_ecrit_a_la_main.md"
    cible.write_text("# Mon GDD\n\nDes mois de travail.\n", encoding="utf-8")
    with pytest.raises(HandEditedGDDError):
        gdd.write(cible)
    assert "Des mois de travail." in cible.read_text(encoding="utf-8")


def test_le_document_ecrit_est_celui_qui_est_rendu(monde, tmp_path):
    _, _, gdd = monde
    cible = gdd.write(tmp_path / "gdd.md")
    ecrit = cible.read_text(encoding="utf-8")
    assert ecrit.endswith(gdd.render())


def test_le_chemin_par_defaut_porte_le_monde(monde):
    """Deux mondes ne doivent pas écrire dans le même fichier."""
    _, _, gdd = monde
    assert gdd.default_path().name == f"gdd_{gdd.kg.world_id}.md"


def test_le_journal_par_defaut_sadosse_au_meme_monde(kg):
    """`get_journal(world_id)` s'adosse au singleton `get_world_kg`, qui ouvre
    la base PAR DÉFAUT : sur un `kg` de test le journal serait vide sans que
    rien ne le signale. `LivingGDD` construit donc son journal SUR son `kg`."""
    gdd = LivingGDD(kg)
    assert gdd.journal.kg is kg


def test_une_decision_est_rendue_en_adr_pas_en_voisinage_brut(monde):
    """Ses conséquences arrivent en arêtes ENTRANTES : les rendre telles
    quelles (« ← DERIVED_FROM ») dirait le schéma, pas le sens."""
    _, _, gdd = monde
    doc = gdd.render()
    section = doc.split("## Décisions de design", 1)[1]
    assert "**Conséquences** — Character « Severian »" in section
    assert "DERIVED_FROM" not in section


def test_le_gdd_ne_recopie_pas_le_journal_complet(monde):
    """E2-06 possède la vue ADR. Deux documents à tenir d'accord sur le même
    sujet divergent toujours ; le GDD CITE, il ne re-rend pas."""
    _, _, gdd = monde
    assert "DecisionJournal.render()" in gdd.render()
