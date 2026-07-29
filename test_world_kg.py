"""L'ontologie du monde tient-elle ses promesses ? (E2-01)

Kùzu n'est pas installé dans tous les interpréteurs de la Forge : le module est
donc écrit pour que TOUT ce qui décide de la correction du schéma soit une
fonction PURE — DDL, identité, sérialisation, validation des couples d'arêtes.
Ces tests-là tournent partout et sans base.

Les tests d'écriture réelle sont marqués et sautés si Kùzu manque : ils vérifient
qu'un schéma qui se rend correctement s'ouvre aussi correctement. Un skip est
visible, une absence de test ne l'est pas.

Même leçon que `test_graph_db_escaping.py` : on teste ce que la fonction RETOURNE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.world_kg import (  # noqa: E402
    CANON_KINDS,
    STATUS_KINDS,
    WORLD_EDGE_PAIRS,
    WORLD_EDGE_TABLES,
    WORLD_NODE_TABLES,
    WorldKG,
    _literal,
    edge_ddl,
    edge_group_ddl,
    node_ddl,
    props_for,
    reset_world_kg,
    slugify,
    world_key,
)


# ── Ontologie : ce que le ticket E2-01 exige littéralement ───────────────────

def test_les_dix_types_du_ticket_existent():
    """E2-01 nomme 10 types. Aucun ne doit manquer, quel qu'en soit le motif."""
    attendus = {"Character", "Faction", "Location", "Quest", "Item", "Ability",
                "Event", "LoreRule", "DialogueNode", "DesignDecision"}
    assert set(WORLD_NODE_TABLES) == attendus


def test_les_six_aretes_du_ticket_existent():
    attendus = {"KNOWS", "OWNS", "LOCATED_IN", "REQUIRES", "CONTRADICTS", "DERIVED_FROM"}
    assert set(WORLD_EDGE_TABLES) == attendus


def test_aucune_arete_ne_reference_un_type_inconnu():
    """Un couple pointant vers un label absent produirait un DDL invalide,
    silencieusement avalé par le `except` de `_create_schema`."""
    for edge, pairs in WORLD_EDGE_PAIRS.items():
        for src, dst in pairs:
            assert src in WORLD_NODE_TABLES, f"{edge}: source inconnue {src}"
            assert dst in WORLD_NODE_TABLES, f"{edge}: cible inconnue {dst}"


def test_aucune_arete_sans_couple():
    for edge in WORLD_EDGE_TABLES:
        assert WORLD_EDGE_PAIRS[edge], f"{edge} n'autorise aucun couple"


def test_pas_de_couple_duplique():
    """Kùzu refuse un couple FROM/TO déclaré deux fois dans la même table —
    `DERIVED_FROM` est construite par compréhension, la collision est plausible."""
    for edge, pairs in WORLD_EDGE_PAIRS.items():
        assert len(pairs) == len(set(pairs)), f"{edge} déclare un couple en double"


# ── DDL : la seule chose vérifiable hors Kùzu ────────────────────────────────

def test_le_ddl_de_noeud_porte_la_cle_primaire_et_le_cloisonnement():
    ddl = node_ddl("Character")
    assert "CREATE NODE TABLE IF NOT EXISTS Character(" in ddl
    assert "PRIMARY KEY(id)" in ddl
    assert "world_id STRING" in ddl
    assert "created TIMESTAMP" in ddl and "updated TIMESTAMP" in ddl


def test_le_ddl_de_noeud_couvre_toutes_les_proprietes_declarees():
    for label in WORLD_NODE_TABLES:
        ddl = node_ddl(label)
        for prop in props_for(label):
            assert f"{prop} " in ddl, f"{label}: {prop} absente du DDL"


def test_le_ddl_darete_declare_tous_les_couples():
    ddl = edge_ddl("LOCATED_IN")
    for src, dst in WORLD_EDGE_PAIRS["LOCATED_IN"]:
        assert f"FROM {src} TO {dst}" in ddl
    assert "weight DOUBLE" in ddl and "context STRING" in ddl


def test_le_repli_ancienne_version_a_la_meme_forme():
    """Kùzu < 0.7 nomme le multi-couples REL TABLE GROUP. Le repli doit produire
    exactement les mêmes couples — sinon les deux chemins divergent en silence."""
    for edge in WORLD_EDGE_TABLES:
        neuf, ancien = edge_ddl(edge), edge_group_ddl(edge)
        assert ancien.startswith("CREATE REL TABLE GROUP IF NOT EXISTS")
        assert neuf.split("(", 1)[1] == ancien.split("(", 1)[1]


def test_un_label_inconnu_leve_au_lieu_de_construire_du_ddl():
    with pytest.raises(ValueError):
        node_ddl("Character) DROP TABLE Agent //")
    with pytest.raises(ValueError):
        edge_ddl("KNOWS) //")


# ── Identité : le premier rempart anti-doublon ───────────────────────────────

def test_slugify_neutralise_accents_casse_et_ponctuation():
    assert slugify("Sévérian") == "severian"
    assert slugify("Severian") == "severian"
    assert slugify("  Le Bourreau, dit Sévérian !  ") == "le-bourreau-dit-severian"


def test_la_cle_encode_le_monde_et_le_type():
    assert world_key("urth", "Character", "Sévérian") == "urth:Character:severian"


def test_deux_mondes_ne_se_marchent_pas_dessus():
    """Kùzu n'accepte qu'une colonne en clé primaire : si le monde n'était pas
    encodé DANS la clé, le second jeu écraserait le premier."""
    assert world_key("urth", "Character", "Severian") != world_key(
        "autre-monde", "Character", "Severian")


def test_un_nom_sans_contenu_exploitable_leve():
    """« !!! » produit un slug vide : accepter donnerait la clé `urth:Character:`,
    que tout nom vide suivant viendrait écraser."""
    with pytest.raises(ValueError):
        world_key("urth", "Character", "!!!")


def test_la_cle_refuse_un_label_inconnu():
    with pytest.raises(ValueError):
        world_key("urth", "Dragon", "Tiamat")


# ── Sérialisation : le typage vient du schéma, pas de la valeur ──────────────

def test_un_entier_rendu_par_un_llm_atterrit_en_entier():
    assert _literal("12", "INT64") == "12"
    assert _literal(12.9, "INT64") == "12"
    assert _literal("bruit", "INT64") == "0"


def test_les_booleens_acceptent_les_formes_llm():
    assert _literal("oui", "BOOL") == "true"
    assert _literal("false", "BOOL") == "false"
    assert _literal(0, "BOOL") == "false"


def test_les_chaines_sont_echappees():
    """L'échappement est celui de graph_db (déjà verrouillé) — on vérifie ici
    qu'il est bien APPLIQUÉ, pas qu'il existe."""
    assert _literal("l'Autarque", "STRING") == "'l\\'Autarque'"
    assert _literal("fin\\", "STRING") == "'fin\\\\'"


def test_une_liste_devient_un_csv_echappe():
    assert _literal(["sombre", "gothique"], "STRING") == "'sombre,gothique'"


# ── Validation d'écriture : refuser plutôt qu'avaler ─────────────────────────

def _kg() -> WorldKG:
    """Instance NON initialisée : la validation précède l'ouverture de la base,
    donc ces tests tournent sans Kùzu. C'est voulu — la validation ne doit
    jamais dépendre du moteur."""
    return WorldKG(world_id="test-monde")


def test_une_propriete_inventee_est_refusee():
    """Un agent qui écrit `hair_color` doit être bloqué, pas se croire enregistré."""
    with pytest.raises(ValueError, match="propriétés inconnues"):
        _kg().upsert("Character", "Severian", hair_color="brun")


def test_un_canon_hors_vocabulaire_est_refuse():
    """E9 et le gate copyright s'appuient sur `canon` : il ne peut pas être libre."""
    with pytest.raises(ValueError, match="canon"):
        _kg().upsert("Character", "Severian", canon="peut-etre")
    assert "canon" in CANON_KINDS and "generated" in CANON_KINDS


def test_un_status_hors_vocabulaire_est_refuse():
    with pytest.raises(ValueError, match="status"):
        _kg().upsert("Quest", "La Griffe", status="en-cours")
    assert set(STATUS_KINDS) == {"draft", "validated", "cut"}


def test_une_relation_qui_na_pas_de_sens_est_refusee():
    """Un objet ne connaît personne. Sans ce garde-fou, un LLM peut peupler le
    graphe de relations que le moteur accepte et que le jeu ne sait pas lire."""
    with pytest.raises(ValueError, match="n'accepte pas"):
        _kg().link("KNOWS", "Item", "La Griffe", "Character", "Severian")


def test_une_relation_declaree_passe_la_validation(tmp_path):
    """Le pendant du test précédent : un couple DÉCLARÉ ne doit jamais être
    rejeté par la validation. Ce qui se passe ensuite (base absente, nœuds
    inexistants) est hors sujet — seul le `ValueError` de couple est testé."""
    kg = WorldKG(world_id="test-monde", db_path=tmp_path / "kuzu_link_test")
    try:
        kg.link("LOCATED_IN", "Character", "Severian", "Location", "Nessus")
    except ValueError as e:
        pytest.fail(f"couple pourtant déclaré, rejeté par la validation: {e}")
    except Exception:
        pass    # Kùzu absent ou nœuds manquants : ce n'est pas ce qu'on teste
    finally:
        kg.close()


# ── Écriture réelle (sautée sans Kùzu) ───────────────────────────────────────

@pytest.fixture(autouse=True)
def _connexions_propres():
    """Kùzu garde un verrou fichier tant que la base est ouverte : sans purge du
    registre partagé, les bases temporaires s'accumulent et Windows refuse de
    nettoyer les `tmp_path`."""
    yield
    reset_world_kg()


@pytest.fixture
def kuzu_kg(tmp_path):
    pytest.importorskip("kuzu", reason="Kùzu absent de cet interpréteur")
    kg = WorldKG(world_id="test-monde", db_path=tmp_path / "kuzu_world_test")
    yield kg
    kg.close()


def test_le_schema_souvre_vraiment(kuzu_kg):
    """Le DDL est peut-être joli et refusé par le moteur. Seul ce test le dit."""
    kuzu_kg._ensure_init()
    assert kuzu_kg.rel_mode in ("rel_table", "rel_table_group"), (
        f"aucune syntaxe d'arête acceptée (rel_mode={kuzu_kg.rel_mode})")
    assert kuzu_kg.count_nodes() == {lbl: 0 for lbl in WORLD_NODE_TABLES}


def test_upsert_puis_relecture(kuzu_kg):
    key = kuzu_kg.add_character("Sévérian", role="protagoniste", canon="canon", alive=True)
    assert key == "test-monde:Character:severian"
    node = kuzu_kg.get("Character", "Severian")   # sans accent : même clé
    # Clés NUES : l'alias Cypher (`n.role`) ne doit pas fuiter jusqu'ici.
    assert node and node["role"] == "protagoniste"
    assert not any("." in k for k in node), f"préfixe d'alias non retiré: {list(node)}"


def test_deux_ecritures_du_meme_nom_ne_font_quun_noeud(kuzu_kg):
    """L'unicité SÉMANTIQUE est E2-02 ; l'unicité par clé, elle, est due ici."""
    kuzu_kg.add_character("Severian", role="bourreau")
    kuzu_kg.add_character("Sévérian", role="autarque")
    assert kuzu_kg.count_nodes()["Character"] == 1
    assert kuzu_kg.get("Character", "Severian")["role"] == "autarque"


def test_une_arete_se_relit_dans_les_deux_sens(kuzu_kg):
    kuzu_kg.add_character("Severian")
    kuzu_kg.add_location("Nessus", kind="city")
    assert kuzu_kg.link("LOCATED_IN", "Character", "Severian", "Location", "Nessus")
    assert any(v["dir"] == "out" for v in kuzu_kg.neighbors("Character", "Severian"))
    assert any(v["dir"] == "in" for v in kuzu_kg.neighbors("Location", "Nessus"))


def test_context_pack_remonte_les_regles_dures(kuzu_kg):
    """C'est la fonction que tout agent consommera avant d'écrire (E2-05/E7) :
    si les règles dures n'y sont pas, le lore n'est pas défendu."""
    kuzu_kg.add_character("Severian")
    kuzu_kg.add_lore_rule("Le soleil meurt", hard=True, statement="Le soleil s'éteint")
    kuzu_kg.add_lore_rule("Détail mou", hard=False)
    pack = kuzu_kg.context_pack("Character", "Severian")
    noms = {r["name"] for r in pack["hard_rules"]}
    assert pack["found"] and noms == {"Le soleil meurt"}


def test_context_pack_dit_quand_lentite_nexiste_pas(kuzu_kg):
    """Ne jamais renvoyer un paquet vide qui ressemble à un paquet valide."""
    assert kuzu_kg.context_pack("Character", "Inconnu")["found"] is False


def test_les_mondes_sont_cloisonnes(tmp_path):
    """Deux mondes partagent UNE base — le cloisonnement est dans la clé, pas
    dans le fichier. Kùzu verrouille une base par processus : si la connexion
    n'était pas partagée par chemin, le second monde ne s'ouvrirait même pas."""
    pytest.importorskip("kuzu", reason="Kùzu absent de cet interpréteur")
    a = WorldKG(world_id="urth", db_path=tmp_path / "kuzu_world_multi")
    b = WorldKG(world_id="autre", db_path=tmp_path / "kuzu_world_multi")
    a.add_character("Severian", role="bourreau")
    b.add_character("Severian", role="marchand")
    assert a.count_nodes()["Character"] == 1, "le second monde a écrasé le premier"
    assert a.get("Character", "Severian")["role"] == "bourreau"
    assert b.get("Character", "Severian")["role"] == "marchand"
    a.close(); b.close()


def test_chronologie_ordonnee(kuzu_kg):
    """E9 détecte les incohérences temporelles : sans ordre stable, rien à détecter."""
    kuzu_kg.add_event("Chute de l'Autarque", chrono=200, era="Urth")
    kuzu_kg.add_event("Naissance de Severian", chrono=100, era="Urth")
    assert [e["name"] for e in kuzu_kg.chronology()] == [
        "Naissance de Severian", "Chute de l'Autarque"]


def test_les_contradictions_sont_stockees_pas_seulement_signalees(kuzu_kg):
    kuzu_kg.add_lore_rule("Le soleil meurt", hard=True)
    kuzu_kg.add_event("Le soleil se rallume", chrono=300)
    kuzu_kg.link("CONTRADICTS", "LoreRule", "Le soleil meurt",
                 "Event", "Le soleil se rallume", weight=9.0, context="E9")
    conflits = kuzu_kg.contradictions()
    assert len(conflits) == 1 and conflits[0]["severity"] == 9.0
