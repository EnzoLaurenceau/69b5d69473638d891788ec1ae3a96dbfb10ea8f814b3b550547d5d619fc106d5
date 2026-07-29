"""Tests E2-02 — unicité sémantique des entités du monde.

Deux étages, volontairement séparés :

1. **Pur** — `similarity`, `name_tokens`, `split_aliases` : fonctions
   déterministes, testées sans moteur. C'est là que se joue la définition de
   « même entité », et elle doit être lisible sans base de données.
2. **Moteur** — la contrainte elle-même, contre un vrai Kùzu sur base jetable.
   Leçon d'E2-01 : un schéma qui se rend correctement n'est pas un schéma qui
   s'ouvre. Un `skip` ici serait un test qui ment ; on saute seulement si le
   paquet est absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.world_kg import (  # noqa: E402
    SIMILARITY_THRESHOLD,
    DuplicateEntityError,
    WorldKG,
    name_tokens,
    reset_world_kg,
    similarity,
    split_aliases,
)

kuzu = pytest.importorskip("kuzu", reason="E2-02 se vérifie contre le vrai moteur")


# ── Étage 1 : la définition de « même entité », sans moteur ──────────────────

def test_un_nom_est_identique_a_lui_meme():
    assert similarity("Severian", "Severian") == 1.0


def test_laccent_et_la_casse_ne_font_pas_deux_entites():
    """Hérite de `slugify` : une seule définition de « même chaîne »."""
    assert similarity("Sévérian", "severian") == 1.0


def test_un_nom_contenu_dans_lautre_est_repute_le_meme():
    """« Severian » ⊂ « Severian le bourreau » : Jaccard seul donnerait 0,33 et
    laisserait passer le doublon. C'est l'inclusion qui l'attrape."""
    assert similarity("Severian", "Severian le bourreau") == 1.0


def test_deux_noms_etrangers_ne_se_ressemblent_pas():
    assert similarity("Severian", "Thecla") == 0.0


def test_les_mots_vides_ne_portent_aucune_ressemblance():
    """Sans retrait des articles, « le Bourreau » et « la Sorcière » partagent
    un token et remontent un score — deux entités seraient fusionnées à tort."""
    assert similarity("le Bourreau", "la Sorciere") == 0.0


def test_un_article_seul_ne_fait_pas_disparaitre_le_nom():
    """Un nom entièrement composé de mots vides doit rester comparable plutôt
    que de produire un jeu vide qui matcherait n'importe quoi."""
    assert name_tokens("Le") == frozenset({"le"})
    assert similarity("Le", "Le") == 1.0


def test_le_seuil_par_defaut_separe_les_cas_du_ticket():
    """Garde-fou sur le réglage : « empêche 2 PNJ identiques » doit rester vrai
    au seuil livré, sinon la valeur par défaut est un piège."""
    assert similarity("Severian", "Severian le bourreau") >= SIMILARITY_THRESHOLD
    assert similarity("Severian", "Thecla") < SIMILARITY_THRESHOLD


@pytest.mark.parametrize("brut,attendu", [
    (None, []),
    ("", []),
    ("a|b", ["a", "b"]),
    (["a", "b"], ["a", "b"]),
    ("a|a|A", ["a"]),                      # dédoublonné par slug
    ("  espace  |  autre ", ["espace", "autre"]),
    ("nom, avec virgule", ["nom, avec virgule"]),   # la virgule n'est PAS un séparateur
])
def test_les_alias_se_lisent_sous_toutes_leurs_formes(brut, attendu):
    assert split_aliases(brut) == attendu


# ── Étage 2 : la contrainte, contre le vrai moteur ──────────────────────────

@pytest.fixture(autouse=True)
def _connexions_propres():
    """Referme les bases entre deux tests.

    `_CONNECTIONS` (E2-01) partage la connexion Kùzu PAR CHEMIN et n'évince
    jamais : sans ce nettoyage, chaque test laisse une base ouverte et le moteur
    finit par refuser d'en ouvrir une de plus — l'échec remonte alors en
    `UnicodeDecodeError`, parce que le message d'erreur natif (cp1252, accentué)
    est décodé en utf-8 par le binding. Symptôme illisible, cause banale : les
    tests passaient un par un et échouaient en série.
    """
    yield
    reset_world_kg()


@pytest.fixture()
def kg(tmp_path) -> WorldKG:
    """Base jetable par test : aucune fuite vers `04_GRAPHIFY/kuzu_world`."""
    return WorldKG(world_id="test-identite", db_path=tmp_path / "world")


def test_le_doublon_exact_reste_un_upsert(kg):
    """Acquis d'E2-01 : ne pas le casser en ajoutant E2-02."""
    kg.add_character("Severian", role="protagoniste")
    kg.add_character("Severian", role="bourreau")
    assert len(kg.all_nodes("Character")) == 1
    assert kg.get("Character", "Severian")["role"] == "bourreau"


def test_un_quasi_doublon_est_refuse(kg):
    """Le cœur du ticket : « empêche 2 PNJ identiques »."""
    kg.add_character("Severian")
    with pytest.raises(DuplicateEntityError):
        kg.add_character("Severian le bourreau")
    assert len(kg.all_nodes("Character")) == 1


def test_le_refus_nomme_le_coupable_et_la_sortie(kg):
    """Un refus qui n'explique pas quoi faire fait réessayer au hasard."""
    kg.add_character("Severian")
    with pytest.raises(DuplicateEntityError) as err:
        kg.add_character("Severian le bourreau")
    message = str(err.value)
    assert "Severian" in message
    assert "allow_similar" in message and "aliases" in message
    assert err.value.candidates[0]["name"] == "Severian"


def test_deux_entites_vraiment_distinctes_restent_possibles(kg):
    """La contrainte ne doit pas rendre le monde inécrivable : la sortie existe,
    mais elle est EXPLICITE."""
    kg.add_character("Severian")
    kg.add_character("Severian le bourreau", allow_similar=True)
    assert len(kg.all_nodes("Character")) == 2


def test_un_alias_resout_vers_lentite_existante(kg):
    kg.add_character("Thecla", aliases=["la chatelaine"])
    assert kg.resolve("Character", "la chatelaine") == kg.resolve("Character", "Thecla")


def test_ecrire_sous_un_alias_met_a_jour_lentite_au_lieu_den_creer_une(kg):
    """C'est ce qui distingue E2-02 d'un simple refus : la bonne écriture
    atterrit sur la bonne entité."""
    kg.add_character("Thecla", aliases=["la chatelaine"])
    kg.add_character("la chatelaine", role="noble")
    assert len(kg.all_nodes("Character")) == 1
    node = kg.get("Character", "Thecla")
    assert node["role"] == "noble"
    assert node["name"] == "Thecla", "le nom canonique ne doit pas être écrasé par l'alias"


def test_un_alias_deja_pris_par_une_autre_entite_est_refuse(kg):
    """Sans ce garde-fou, un nom désignerait deux entités et `resolve()`
    renverrait l'une ou l'autre selon l'ordre de parcours."""
    kg.add_character("Thecla", aliases=["la chatelaine"])
    with pytest.raises(DuplicateEntityError, match="deux entités"):
        kg.add_character("Agia", aliases=["La Chatelaine"])


def test_les_alias_fusionnent_au_lieu_de_secraser(kg):
    """Deux agents qui enrichissent la même entité ne doivent pas s'effacer."""
    kg.add_character("Thecla", aliases=["la chatelaine"])
    kg.add_character("Thecla", aliases=["la prisonniere"])
    assert sorted(kg.aliases_of("Character", "Thecla")) == ["la chatelaine", "la prisonniere"]


def test_reajouter_son_propre_alias_ne_leve_pas(kg):
    """Une écriture idempotente doit rester idempotente."""
    kg.add_character("Thecla", aliases=["la chatelaine"])
    kg.add_character("Thecla", aliases=["la chatelaine"])
    assert kg.aliases_of("Character", "Thecla") == ["la chatelaine"]


def test_la_ressemblance_alerte_mais_ne_fusionne_pas(kg):
    """`resolve` ne doit PAS résoudre sur une ressemblance : fusionner deux
    entités sans que personne l'ait décidé serait pire que le doublon."""
    kg.add_character("Severian")
    assert kg.resolve("Character", "Severian le bourreau") is None
    assert kg.find_similar("Character", "Severian le bourreau")


def test_find_similar_classe_par_score_decroissant(kg):
    kg.add_character("Severian")
    kg.add_character("Severian le bourreau", allow_similar=True)
    found = kg.find_similar("Character", "Severian le tortionnaire")
    assert found, "au moins un voisin attendu"
    scores = [row["score"] for row in found]
    assert scores == sorted(scores, reverse=True)


def test_une_entite_ne_se_trouve_pas_elle_meme(kg):
    kg.add_character("Severian")
    assert kg.find_similar("Character", "Severian") == []


def test_deux_mondes_nont_pas_les_memes_doublons(tmp_path):
    """Le cloisonnement d'E2-01 doit survivre à la contrainte d'E2-02 : un
    « Severian » dans un monde ne bloque pas celui d'un autre monde."""
    path = tmp_path / "world"
    urth = WorldKG(world_id="urth", db_path=path)
    autre = WorldKG(world_id="autre", db_path=path)
    urth.add_character("Severian")
    autre.add_character("Severian le bourreau")      # ne doit PAS lever
    assert len(urth.all_nodes("Character")) == 1
    assert len(autre.all_nodes("Character")) == 1


def test_les_types_non_personnages_sont_proteges_aussi(kg):
    """La contrainte est portée par `upsert`, donc valable pour les 10 types —
    pas seulement les PNJ cités dans l'intitulé du ticket."""
    kg.add_location("Nessus")
    with pytest.raises(DuplicateEntityError):
        kg.add_location("la cite de Nessus")


def test_la_validation_des_proprietes_precede_le_controle_dunicite(kg):
    """Une écriture fautive sur les deux plans doit se voir reprocher la faute
    la moins chère — et la validation doit rester utilisable sans base."""
    kg.add_character("Severian")
    with pytest.raises(ValueError, match="propriétés inconnues"):
        kg.add_character("Severian le bourreau", hair_color="brun")


def test_le_schema_se_reconcilie_sur_une_base_existante(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` ne touche pas une table déjà créée : sans
    réconciliation, ajouter une propriété n'aurait aucun effet sur une base
    existante. On simule une base d'avant E2-02 en supprimant la colonne."""
    from forge_agents.world_kg import _migrate_schema, table_columns

    path = tmp_path / "world"
    kg = WorldKG(world_id="urth", db_path=path)
    kg.add_character("Severian")            # force l'ouverture et la création
    conn = kg._conn

    conn.execute("ALTER TABLE Character DROP aliases")
    assert "aliases" not in table_columns(conn, "Character")

    added = _migrate_schema(conn)
    assert "Character.aliases" in added
    assert "aliases" in table_columns(conn, "Character")
