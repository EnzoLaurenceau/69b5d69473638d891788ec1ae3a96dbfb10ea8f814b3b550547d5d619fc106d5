"""Tests E2-05 — interroger le monde avant d'écrire.

Trois étages, volontairement séparés :

1. **Pur** — projection d'une entité en document, tokenisation, normalisation,
   invariants de pondération. C'est là que se joue « ce que la recherche VOIT
   du monde », et ça doit se lire sans base ni modèle.
2. **Moteur** — la recherche contre un vrai Kùzu sur base jetable. Un index qui
   se construit n'est pas un index qui répond ; et la promesse du ticket (« tout
   agent interroge le monde AVANT d'écrire ») n'a de sens que contre un monde
   réel.
3. **Injecté** — la branche cross-encoder. `forge_rag_optimized` ne s'importe
   PAS dans cette Forge (torch absent, mesuré) : sans injection d'un moteur de
   substitution, cette branche ne serait couverte par aucun test. Un `skip`
   aurait laissé croire qu'elle est vérifiée ailleurs.

Leçon reprise d'E2-01/E2-02 : on teste ce que la fonction RETOURNE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.semantic_cache import _tokenize  # noqa: E402
from forge_agents.world_kg import (  # noqa: E402
    CANON_KINDS,
    WORLD_NODE_TABLES,
    DuplicateEntityError,
    WorldKG,
    reset_world_kg,
)
from forge_agents.world_rag import (  # noqa: E402
    CANON_WEIGHT,
    HIDDEN_STATUS,
    MAX_RELATIONS,
    MIN_SCORE,
    RERANK_WEIGHTS,
    WorldRAG,
    _normalize,
    _tokens,
    _Chunk,
    entity_text,
    load_reranker,
)


# ── Étage 1 : ce que la recherche voit du monde, sans moteur ─────────────────

def test_les_poids_du_reclassement_somment_a_un():
    """Une part ajoutée sans rééquilibrage rendrait les scores incomparables
    d'une version à l'autre, en silence."""
    assert round(sum(RERANK_WEIGHTS.values()), 6) == 1.0


def test_chaque_provenance_du_vocabulaire_est_ponderee():
    """`CANON_KINDS` est déclaré en E2-01 : un cinquième `canon` ajouté là-bas
    ne doit pas retomber muettement sur le poids de `generated`."""
    assert set(CANON_WEIGHT) == set(CANON_KINDS)


def test_le_canon_pese_plus_que_le_genere():
    assert CANON_WEIGHT["canon"] > CANON_WEIGHT["generated"]


def test_les_statuts_ecartes_saccordent_avec_le_gdd():
    """Même valeur que `world_gdd.HIDDEN_STATUS`, sans l'importer : la recherche
    n'a pas à dépendre du module qui rend un document. Ce test EST le lien —
    une divergence doit se voir, pas se découvrir en production."""
    from forge_agents.world_gdd import HIDDEN_STATUS as GDD_HIDDEN
    assert HIDDEN_STATUS == GDD_HIDDEN


def test_le_tokenizer_partage_mutile_le_francais():
    """Le défaut qu'on corrige, relevé ici pour qu'il ne soit pas une croyance :
    le motif du tokenizer commence par `[a-zA-Z_]`, donc « é » n'ouvre aucun
    token et la première lettre est perdue."""
    assert _tokenize("épée dorée") == ["pée", "dorée"]


def test_les_accents_ne_coupent_plus_la_recherche():
    """« épée » et « epee » doivent se rencontrer — le monde s'écrit en français."""
    assert _tokens("épée dorée") == _tokens("epee doree") == ["epee", "doree"]


def test_les_separateurs_de_slug_ne_sont_pas_des_tokens():
    """`slugify` produit des `-` ; présents dans tous les documents, ils ne
    discriminent rien et gonfleraient le recouvrement lexical."""
    assert "-" not in _tokens("Sévérian le bourreau")


def test_une_requete_vide_ne_produit_aucun_token():
    assert _tokens("") == []
    assert _tokens("   ") == []


def test_le_document_commence_par_le_type_et_le_nom():
    """C'est la queue que le cross-encoder tronque (256 tokens) : ce qui
    identifie l'entité doit être en tête."""
    txt = entity_text("Character", {"name": "Sévérian"})
    assert txt.splitlines()[0] == "Character « Sévérian »"


def test_le_document_ne_contient_aucune_ligne_vide():
    """`semantic_chunk` coupe sur les lignes vides ; un document coupé perd son
    nom (mesuré : 2 morceaux, le second sans le nom)."""
    txt = entity_text("Character", {
        "name": "Sévérian", "summary": "Bourreau.", "aliases": "le bourreau",
        "role": "protagoniste", "tags": "heros,guilde",
    }, [{"edge": "OWNS", "dir": "out", "other_name": "Griffe"}])
    assert "" not in txt.splitlines()


def test_le_document_porte_les_alias_le_resume_et_les_relations():
    txt = entity_text("Character", {
        "name": "Sévérian", "summary": "Bourreau devenu Autarque.",
        "aliases": "le bourreau", "role": "protagoniste", "tags": "heros",
    }, [{"edge": "LOCATED_IN", "dir": "out", "other_name": "Nessus",
         "context": "exil"}])
    for attendu in ("le bourreau", "Bourreau devenu Autarque.", "protagoniste",
                    "heros", "LOCATED_IN", "Nessus", "exil"):
        assert attendu in txt


def test_une_propriete_absente_ne_met_pas_none_dans_le_document():
    """Sondé en E2-04 : une propriété non fournie revient à `None`, pas `""`."""
    assert "None" not in entity_text("Character", {"name": "Agia"})


def test_une_propriete_typee_ajoutee_devient_cherchable_sans_toucher_ici():
    """Le rendu dérive de `props_for` (E2-01) : ajouter une propriété au schéma
    suffit. Sans ça, la recherche ignorerait en silence les extensions du monde."""
    txt = entity_text("Location", {"name": "Nessus", "biome": "fluvial",
                                   "climate": "humide", "danger": 3})
    assert "biome fluvial" in txt and "climate humide" in txt and "danger 3" in txt


def test_les_relations_sont_plafonnees():
    """Une entité à cent liens noierait son identité sous ses voisins."""
    rels = [{"edge": "KNOWS", "dir": "out", "other_name": f"PNJ {i}"}
            for i in range(MAX_RELATIONS + 30)]
    txt = entity_text("Character", {"name": "Sévérian"}, rels)
    assert txt.count("KNOWS") == MAX_RELATIONS


def test_le_document_est_deterministe():
    """Même entité, mêmes octets : sinon deux index du même monde diffèrent."""
    node = {"name": "Sévérian", "summary": "Bourreau.", "role": "protagoniste",
            "faction": "Guilde", "alive": True}
    assert entity_text("Character", node) == entity_text("Character", node)


def test_le_sens_de_la_relation_est_rendu():
    entrant = entity_text("Item", {"name": "Griffe"},
                          [{"edge": "OWNS", "dir": "in", "other_name": "Sévérian"}])
    sortant = entity_text("Character", {"name": "Sévérian"},
                          [{"edge": "OWNS", "dir": "out", "other_name": "Griffe"}])
    assert "←" in entrant and "→" in sortant


def test_la_normalisation_rend_zero_quand_tout_se_vaut():
    """Quand tous les candidats se valent, le signal ne doit RIEN dire — et non
    tout affirmer. Des uns feraient peser à plein un signal sans information."""
    assert _normalize([3.0, 3.0, 3.0]) == [0.0, 0.0, 0.0]


def test_la_normalisation_dune_liste_vide_ne_leve_pas():
    assert _normalize([]) == []


def test_la_normalisation_etale_bien_entre_zero_et_un():
    assert _normalize([1.0, 3.0, 5.0]) == [0.0, 0.5, 1.0]


def test_le_chargement_du_reranker_ne_leve_jamais():
    """`forge_rag_optimized` manque ici (torch absent) : l'absence est un mode
    de fonctionnement annoncé, pas une panne."""
    engine, mode = load_reranker()
    assert mode in ("cross-encoder", "graphe")
    assert (engine is None) == (mode == "graphe")


def test_le_chunk_porte_ce_quun_reranker_attend():
    c = _Chunk("texte", "cle")
    assert c.text == "texte" and c.rerank_score == 0.0 and c.doc_id == "cle"


# ── Étage 2 : la recherche contre le vrai moteur ─────────────────────────────

kuzu = pytest.importorskip("kuzu", reason="E2-05 se vérifie contre le vrai moteur")


@pytest.fixture(autouse=True)
def _connexions_propres():
    """`_CONNECTIONS` (E2-01) n'évince jamais : sans ce nettoyage, le moteur
    finit par refuser d'ouvrir une base de plus et l'échec remonte en
    `UnicodeDecodeError` illisible."""
    yield
    reset_world_kg()


@pytest.fixture()
def kg(tmp_path) -> WorldKG:
    """Un petit monde jetable, assez peuplé pour que le classement ait à trancher."""
    k = WorldKG(world_id="test-rag", db_path=tmp_path / "world")
    k.add_character("Sévérian", summary="Bourreau de la Guilde devenu Autarque.",
                    aliases=["le bourreau"], role="protagoniste",
                    canon="canon", status="validated")
    k.add_character("Agia", summary="Voleuse rivale, marchande de reliques.",
                    role="antagoniste", allow_similar=True)
    k.add_character("Thecla", summary="Châtelaine écartée du jeu.",
                    status="cut", allow_similar=True)
    k.add_location("Nessus", summary="Cité du fleuve Gyoll.", kind="city")
    k.add_item("Griffe du Conciliateur", summary="Relique qui guérit les mourants.",
               rarity="unique", canon="canon")
    k.add_lore_rule("mort-definitive", statement="Nul ne ressuscite hors sanctuaire.",
                    hard=True, scope="Character")
    k.add_lore_rule("guildes-rivales", statement="Les guildes ne s'allient jamais.",
                    hard=False)
    k.link("LOCATED_IN", "Character", "Sévérian", "Location", "Nessus")
    k.link("OWNS", "Character", "Sévérian", "Item", "Griffe du Conciliateur")
    k.link("KNOWS", "Character", "Sévérian", "Character", "Agia")
    return k


@pytest.fixture()
def rag(kg) -> WorldRAG:
    return WorldRAG(kg)


def test_toutes_les_aretes_du_monde_en_une_passe(kg):
    """`all_edges` (ajout E2-01) : c'est lui qui rend tenable la reconstruction
    systématique de l'index — mesuré ×76 contre un parcours nœud par nœud."""
    edges = kg.all_edges()
    assert {e["edge"] for e in edges} == {"LOCATED_IN", "OWNS", "KNOWS"}
    assert all(e["src_id"] and e["other_id"] for e in edges)


def test_les_aretes_dun_autre_monde_ne_fuient_pas(tmp_path, kg):
    """Le cloisonnement d'E2-01 vaut aussi pour la lecture en masse."""
    autre = WorldKG(world_id="autre-monde", db_path=tmp_path / "world")
    assert autre.all_edges() == []


def test_le_corpus_couvre_le_monde_et_ecarte_les_entites_coupees(rag):
    stats = rag.stats()
    assert stats["documents"] == 6          # 7 entités, moins Thecla (`cut`)
    assert stats["excluded_cut"] == 1
    assert stats["by_label"]["Character"] == 2


def test_une_entite_coupee_nest_jamais_proposee_a_un_agent(rag):
    """`cut` veut dire écartée du jeu : la proposer comme matière à réutiliser
    rendrait le statut décoratif."""
    assert all("Thecla" != h["name"] for h in rag.search("châtelaine écartée"))


def test_le_degre_vient_des_deux_sens_de_larete(rag):
    docs = {d.name: d for d in rag.docs}
    assert docs["Sévérian"].degree == 3      # 3 arêtes sortantes
    assert docs["Nessus"].degree == 1        # la même arête, vue de l'autre bout


def test_chercher_une_entite_par_son_nom_la_rend_en_premier(rag):
    """LA régression du ticket : le nom d'une entité figure dans le document de
    chacun de ses voisins, son IDF s'effondre et BM25 classait l'entité DERNIÈRE
    (0,0059 contre 0,0078). Chercher « Severian » rendait Agia et la Griffe."""
    hits = rag.search("Severian")
    assert hits and hits[0]["name"] == "Sévérian"


def test_un_alias_designe_bien_son_entite(rag):
    """Hérite d'E2-02 : « le bourreau » EST Sévérian."""
    hits = rag.search("le bourreau")
    assert hits and hits[0]["name"] == "Sévérian"


def test_le_nom_hisse_est_signale_comme_tel(rag):
    """Le hissage est un mécanisme explicite, pas un score qui aurait bien tourné."""
    hits = rag.search("Severian")
    assert hits[0]["named"] is True
    assert hits[0]["signals"]["name"] == 1.0


def test_on_trouve_une_entite_par_son_resume_sans_connaitre_son_nom(rag):
    """La raison d'être du ticket : l'agent ne connaît pas le nom, il décrit."""
    hits = rag.search("relique qui guérit les mourants")
    assert hits and hits[0]["name"] == "Griffe du Conciliateur"


def test_on_trouve_une_entite_par_ce_que_ses_voisins_en_disent(rag):
    """Les relations sont dans le document exprès : « rivale de Severian »
    doit trouver Agia, qui ne porte ce nom nulle part dans ses propriétés."""
    noms = [h["name"] for h in rag.search("marchande de reliques")]
    assert "Agia" in noms


def test_un_agent_qui_tape_sans_accent_trouve_lentite_accentuee(kg):
    """La conséquence réelle du tokenizer mutilé, contre le moteur : un agent
    (ou un modèle) qui écrit « epee doree » doit trouver « Épée dorée ». Sans
    passage par `slugify`, la lettre initiale accentuée disparaît d'un côté
    seulement et les deux ne se rencontrent jamais."""
    kg.add_item("Épée dorée", summary="Lame de cérémonie.")
    hits = WorldRAG(kg).search("epee doree")
    assert hits and hits[0]["name"] == "Épée dorée"


def test_une_requete_hors_du_monde_ne_rend_rien(rag):
    """Mesuré : BM25 rend un vecteur nul, et `argsort` d'un vecteur nul rend
    l'ordre des indices. Rendre le top-5 de ce vecteur, c'est répondre au
    hasard avec l'aplomb d'une recherche."""
    assert rag.search("zzzz quantique blockchain") == []


def test_une_requete_vide_ne_rend_rien(rag):
    assert rag.search("") == []
    assert rag.search("   ") == []


def test_la_recherche_respecte_le_top_k(rag):
    assert len(rag.search("guilde", top_k=2)) <= 2


def test_deux_recherches_identiques_rendent_le_meme_ordre(rag):
    """À score égal, l'ordre ne doit pas dépendre du parcours de la base."""
    a = [h["key"] for h in rag.search("guilde reliques")]
    b = [h["key"] for h in rag.search("guilde reliques")]
    assert a == b


def test_les_regles_dures_accompagnent_toujours_le_paquet(rag):
    pack = rag.world_context("relique qui guérit")
    assert [r["name"] for r in pack["hard_rules"]] == ["mort-definitive"]


def test_les_regles_dures_survivent_a_une_requete_sans_resultat(rag):
    """C'est le cas qui compte : un top-5 peut écarter la règle qui interdit
    exactement ce que l'agent s'apprête à écrire, d'autant plus sûrement
    qu'elle est formulée en termes généraux."""
    pack = rag.world_context("zzzz quantique blockchain")
    assert pack["found"] is False
    assert [r["name"] for r in pack["hard_rules"]] == ["mort-definitive"]


def test_une_regle_molle_nest_pas_hissee(rag):
    """`hard=True` est ce qui bloque ; hisser tout le lore noierait la règle."""
    noms = [r["name"] for r in rag.world_context("guildes").get("hard_rules", [])]
    assert "guildes-rivales" not in noms


def test_les_regles_dures_ne_sont_pas_repayees_dans_chaque_entite(rag):
    """E2-01 rejoint les règles à CHAQUE `context_pack`. Les garder ferait payer
    les mêmes règles k fois dans le prompt — pour rien."""
    pack = rag.world_context("relique qui guérit")
    assert pack["entities"]
    assert all("hard_rules" not in e["pack"] for e in pack["entities"])


def test_chaque_entite_du_paquet_porte_son_voisinage(rag):
    """C'est `context_pack` d'E2-01 qui est rendu — une seule définition du
    « voisinage d'une entité » dans la Forge."""
    pack = rag.world_context("Severian")
    entite = pack["entities"][0]
    assert entite["pack"]["found"] is True
    assert entite["pack"]["entity"]["name"] == "Sévérian"
    assert entite["pack"]["neighbors"]


def test_le_paquet_dit_par_quel_moteur_il_a_repondu(rag):
    """Une recherche qui dégrade en silence est un monde que les agents
    ré-inventeront à côté."""
    pack = rag.world_context("Severian")
    assert pack["mode"] in ("rag_optimized", "bm25", "lexical")
    assert pack["reranker"] in ("cross-encoder", "graphe")
    assert pack["considered"] == 6 and pack["excluded"] == 1


def test_lindex_nest_jamais_perime(rag, kg):
    """Décision 4 : reconstruction à chaque requête, donc aucune fenêtre pendant
    laquelle un agent lit un monde qui n'existe plus."""
    assert rag.search("Baldanders") == []
    kg.add_character("Baldanders", summary="Géant qui grandit sans fin.")
    hits = rag.search("Baldanders")
    assert hits and hits[0]["name"] == "Baldanders"


def test_la_sortie_explicite_fige_bien_lindex(rag, kg):
    """`fresh=False` est la sortie de secours pour qui boucle sur un monde figé."""
    rag.refresh()
    kg.add_character("Baldanders", summary="Géant qui grandit sans fin.")
    assert rag.search("Baldanders", fresh=False) == []


def test_le_mode_lexical_repond_encore_sans_bm25(rag, monkeypatch):
    """Troisième étage de la dégradation : sans `rank_bm25`, la recherche
    fonctionne moins finement — elle ne s'éteint pas."""
    rag.refresh()
    rag._bm25 = None
    rag.mode = "lexical"
    hits = rag.search("relique qui guérit", fresh=False)
    assert hits and hits[0]["name"] == "Griffe du Conciliateur"


# ── `before_write` : la promesse du ticket, rendue vérifiable ────────────────

def test_avant_decrire_le_monde_annonce_le_refus_qui_vient(rag):
    """`would_raise` n'est pas un avis : c'est la règle d'E2-02 rejouée."""
    avis = rag.before_write("Character", "Severian le bourreau", summary="marchand")
    assert avis["would_raise"].startswith("DuplicateEntityError")
    assert avis["duplicates"][0]["name"] == "Sévérian"


def test_lannonce_de_refus_est_daccord_avec_le_vrai_upsert(rag, kg):
    """Le seul test qui rende la prédiction honnête : on l'oppose au moteur,
    dans les DEUX sens. Une prédiction jamais confrontée dérive en silence."""
    avis = rag.before_write("Character", "Severian le bourreau")
    assert avis["would_raise"]
    with pytest.raises(DuplicateEntityError):
        kg.add_character("Severian le bourreau")

    libre = rag.before_write("Character", "Baldanders")
    assert libre["would_raise"] == ""
    kg.add_character("Baldanders")          # ne doit pas lever
    assert kg.get("Character", "Baldanders") is not None


def test_ecrire_sous_un_nom_existant_nest_pas_un_doublon(rag):
    """Ré-écrire une entité connue est un `upsert` légitime, pas une collision."""
    avis = rag.before_write("Character", "Sévérian", summary="Autarque")
    assert avis["would_raise"] == ""
    assert avis["existing"]["name"] == "Sévérian"
    assert avis["duplicates"] == []


def test_ecrire_sous_un_alias_resout_vers_lentite(rag):
    """Hérite d'E2-02 : un alias déclaré désigne l'entité, il ne la duplique pas."""
    avis = rag.before_write("Character", "le bourreau")
    assert avis["would_raise"] == ""
    assert avis["resolved_to"].endswith(":Character:severian")


def test_lacte_delibere_leve_le_refus(rag):
    """`allow_similar=True` — « je sais, ce sont bien deux entités »."""
    avis = rag.before_write("Character", "Severian le bourreau", allow_similar=True)
    assert avis["would_raise"] == ""


def test_les_regles_en_portee_sont_filtrees_par_type(rag):
    """Une règle qui ne vise que les personnages n'a rien à dire d'un objet."""
    perso = rag.before_write("Character", "Baldanders")
    objet = rag.before_write("Item", "Lanterne")
    assert [r["name"] for r in perso["rules_in_scope"]] == ["mort-definitive"]
    assert objet["rules_in_scope"] == []


def test_avant_decrire_on_voit_ce_que_le_monde_sait_deja(rag):
    """La question à laquelle le ticket répond : l'agent décrit ce qu'il va
    écrire, le monde lui rend ce qu'il a déjà là-dessus."""
    avis = rag.before_write("Item", "Relique du guérisseur",
                            summary="objet qui guérit les mourants")
    assert avis["found"] is True
    assert "Griffe du Conciliateur" in [e["name"] for e in avis["entities"]]


# ── Étage 3 : la branche cross-encoder, par injection ────────────────────────

class _RerankerFactice:
    """Un reranker qui classe selon un ordre imposé — pour vérifier que le
    module l'ÉCOUTE, sans dépendre de torch."""

    def __init__(self, ordre: list[str]):
        self.ordre = ordre
        self.appels: list[str] = []

    def rerank(self, query, chunks, top_k=5):
        self.appels.append(query)
        for c in chunks:
            score = next((len(self.ordre) - i for i, frag in enumerate(self.ordre)
                          if frag in c.text), 0)
            c.rerank_score = float(score)
        return sorted(chunks, key=lambda c: -c.rerank_score)[:top_k]


class _RerankerCasse:
    def rerank(self, query, chunks, top_k=5):
        raise RuntimeError("modèle introuvable")


def test_le_cross_encoder_est_reellement_consulte(kg):
    faux = _RerankerFactice(["Nessus"])
    r = WorldRAG(kg, engine=faux)
    r.search("cité guilde reliques")
    assert faux.appels == ["cité guilde reliques"]
    assert r.stats()["reranker"] == "cross-encoder"
    assert r.stats()["mode"] == "rag_optimized"


def test_le_cross_encoder_change_bien_le_classement(kg):
    """Sans effet observable sur l'ordre, « brancher le re-ranking » serait un
    appel décoratif."""
    # « Gyoll » et non « Nessus » : le nom d'une entité figure aussi dans le
    # document de ses voisins (c'est le fond de la décision 7), donc viser
    # « Nessus » aurait aussi hissé Sévérian et le test n'aurait rien montré.
    sans = WorldRAG(kg)
    avec = WorldRAG(kg, engine=_RerankerFactice(["Gyoll"]))
    q = "guilde cité reliques"
    assert [h["name"] for h in sans.search(q)] != [h["name"] for h in avec.search(q)]
    assert avec.search(q)[0]["name"] == "Nessus"


def test_un_cross_encoder_en_panne_ne_casse_pas_la_recherche(kg):
    """Un modèle qui tombe doit dégrader vers le score de recherche, pas
    emporter la requête de l'agent."""
    r = WorldRAG(kg, engine=_RerankerCasse())
    hits = r.search("relique qui guérit")
    assert hits and hits[0]["name"] == "Griffe du Conciliateur"


def test_le_nom_reste_hisse_meme_contre_le_cross_encoder(kg):
    """Un cross-encoder ignore tout du monde : il ne doit pas pouvoir écarter
    l'entité que la requête NOMME."""
    r = WorldRAG(kg, engine=_RerankerFactice(["Nessus", "Griffe"]))
    hits = r.search("Severian")
    assert hits[0]["name"] == "Sévérian"


def test_les_signaux_de_graphe_survivent_au_cross_encoder(kg):
    """Le cross-encoder remplace la part « pertinence », pas le reste : sinon
    le classement perdrait canon, degré et statut sans que rien ne le dise."""
    r = WorldRAG(kg, engine=_RerankerFactice(["Nessus"]))
    hit = r.search("cité")[0]
    assert set(hit["signals"]) == set(RERANK_WEIGHTS)


def test_le_plancher_ecarte_le_bruit_mais_jamais_une_entite_nommee(kg):
    """Deux règles qui doivent coexister : sous `MIN_SCORE` on ne rend rien, mais
    une entité que la requête nomme est une réponse quel que soit son score."""
    r = WorldRAG(kg)
    hits = r.search("Severian")
    assert hits[0]["named"] is True
    assert MIN_SCORE > 0.0


def test_le_corpus_couvre_tous_les_types_declares(rag):
    """Aucun des 10 types d'E2-01 ne doit être invisible à la recherche : un
    type absent du corpus ne se voit pas — une recherche ne dit pas ce qu'elle
    n'a pas indexé."""
    peuplables = {d.label for d in rag.docs}
    assert peuplables <= set(WORLD_NODE_TABLES)
    assert {"Character", "Location", "Item", "LoreRule"} <= peuplables
