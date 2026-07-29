"""Tests E2-03 — canon source, index de citations, gate copyright.

Ce module est le GATE COPYRIGHT du pipeline narratif. Ses promesses :

1. **L'index ne contient aucun mot de l'œuvre.** Seules des empreintes sha1
   tronquées et des numéros de passage sont stockés. On ne peut pas
   reconstruire la source depuis l'index — c'est le premier test.
2. **Le fichier source ne jamais entre dans le dépôt.** `refuse_repo_source()`
   lève si le chemin est dans l'arbre LaForge.
3. **Ré-ingérer remplace, jamais n'accumule.** Deux passes sur le même texte
   ne doublent pas les empreintes.
4. **Le verdict est chiffré.** `check()` distingue reprise continue (copier-
   coller franc) et patchwork (fragments multiples). `guard()` lève.
5. **La doctrine CLAUDE.md §3 est codée en dur** : 15 mots max, 1 citation.
   Changer ces seuils ici serait changer la règle en douce.

Trois étages :
  - **pur** — `normalize`, `shingles`, `refuse_repo_source`, `CanonIndex` en
    mémoire (tmp_path). Pas de fichier réel.
  - **fichier** — ingestion depuis un vrai fichier temporaire (pas dans le
    dépôt), vérifie le flux complet `ingest_file → attribute → check → guard`.
  - **invariant** — l'index JSON ne contient AUCUN mot de l'œuvre source.
"""

from __future__ import annotations

import importlib.util as _ilu
import json
import sys
import types as _types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# forge_agents.__init__.py importe langgraph (absent ici) : on charge les
# modules par leur fichier, sans déclencher le __init__ du paquet.
# Chaîne : forge_tenant → graph_db → forge_store → world_kg → world_canon.


def _load_module(name: str, path: Path):
    """Charge un module par son fichier et l'enregistre dans sys.modules."""
    if name in sys.modules:
        return sys.modules[name]
    spec = _ilu.spec_from_file_location(name, str(path))
    mod = _types.ModuleType(name)
    mod.__file__ = str(path)
    mod.__package__ = "forge_agents"
    mod.__spec__ = spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_PKG = ROOT / "00_CORE" / "forge_agents"

# Package factice (pas le vrai __init__.py qui importe langgraph)
if "forge_agents" not in sys.modules:
    _pkg = _types.ModuleType("forge_agents")
    _pkg.__path__ = [str(_PKG)]
    _pkg.__package__ = "forge_agents"
    sys.modules["forge_agents"] = _pkg

_load_module("forge_agents.forge_tenant", _PKG / "forge_tenant.py")
_load_module("forge_agents.graph_db", _PKG / "graph_db.py")
_load_module("forge_agents.forge_store", _PKG / "forge_store.py")
_load_module("forge_agents.world_kg", _PKG / "world_kg.py")
_world_canon = _load_module("forge_agents.world_canon", _PKG / "world_canon.py")

CHUNK_WORDS = _world_canon.CHUNK_WORDS
MAX_QUOTE_WORDS = _world_canon.MAX_QUOTE_WORDS
MAX_QUOTES = _world_canon.MAX_QUOTES
SHINGLE_WORDS = _world_canon.SHINGLE_WORDS
CanonIndex = _world_canon.CanonIndex
CopyrightViolation = _world_canon.CopyrightViolation
get_canon = _world_canon.get_canon
normalize = _world_canon.normalize
refuse_repo_source = _world_canon.refuse_repo_source
reset_canon = _world_canon.reset_canon
shingles = _world_canon.shingles


# ── Textes de test ──────────────────────────────────────────────────────────
# Textes volontairement longs pour couvrir les fenêtres et les runs.

PASSAGE_A = (
    "Le soleil ancien se levait sur la ville aux murs de fer, "
    "et la lumière tombait comme une poussière lente sur les toits. "
    "Les rues étroites s'éveillaient au bruit des pas précipités "
    "des soldats de la Guilde qui changeaient la garde. "
    "Un bourreau marchait seul, portant sur son dos le poids "
    "d'une lame que personne ne voulait nommer. "
    "Il traversa la place du marché en silence, ignorant les regards "
    "qui se détournaient par habitude ou par peur. "
    "La tour de l'ancien phare se dressait encore au loin, "
    "témoin muet d'un monde qui avait oublié la lumière du vrai soleil."
) * 3  # répéter pour avoir assez de mots pour des runs

PASSAGE_B = (
    "Dans les profondeurs du labyrinthe, un vieil homme gardait "
    "les reliques d'une époque révolue. Chaque objet portait en lui "
    "le souvenir d'une guerre que les livres ne racontaient plus. "
    "L'épée Terminus Est reposait sur un autel de pierre noire, "
    "sa lame brillant d'un éclat que le temps n'avait pas terni. "
    "Le gardien savait que celui qui la porterait changerait le monde, "
    "mais il ignorait si ce changement serait pour le meilleur."
) * 3

# Un texte qui COPIE un morceau de PASSAGE_A (pour tester le gate)
COPIE_FRANCHE = (
    "Le soleil ancien se levait sur la ville aux murs de fer, "
    "et la lumière tombait comme une poussière lente sur les toits. "
    "Les rues étroites s'éveillaient au bruit des pas précipités "
    "des soldats de la Guilde qui changeaient la garde."
)

# Un texte INNOVÉ — aucune empreinte en commun avec les passages
TEXTE_INNOVE = (
    "La pluie battait les vitres de la taverne tandis qu'un marchand "
    "d'épices comptait ses pièces d'or. Le feu crépitait dans l'âtre "
    "et l'odeur du café montait depuis la cuisine."
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. PUR — normalize, shingles, refuse_repo_source
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalize:
    """La normalisation neutralise accents, casse, ponctuation."""

    def test_accents_neutralises(self):
        assert normalize("Épée dorée") == normalize("epee doree")

    def test_casse_neutralisee(self):
        assert normalize("Severian") == normalize("SEVERIAN")

    def test_ponctuation_supprimee(self):
        tokens = normalize("Bonjour, monde ! Il fait beau.")
        assert "," not in tokens
        assert "!" not in tokens
        assert "." not in tokens

    def test_chaine_vide(self):
        assert normalize("") == []

    def test_mots_francais(self):
        tokens = normalize("L'épée du bourreau")
        assert "epee" in tokens
        assert "bourreau" in tokens


class TestShingles:
    """Fenêtres glissantes → empreintes sha1 tronquées (16 hexa)."""

    def test_taille_fenetre(self):
        words = [f"mot{i}" for i in range(20)]
        result = shingles(words)
        assert len(result) == 20 - SHINGLE_WORDS + 1

    def test_texte_trop_court(self):
        words = [f"m{i}" for i in range(SHINGLE_WORDS - 1)]
        assert shingles(words) == []

    def test_exactement_taille_fenetre(self):
        words = [f"m{i}" for i in range(SHINGLE_WORDS)]
        result = shingles(words)
        assert len(result) == 1

    def test_deterministe(self):
        words = "le soleil ancien se levait sur la ville".split()
        a = shingles(words)
        b = shingles(words)
        assert a == b

    def test_empreintes_tronquees_16_hexa(self):
        words = [f"mot{i}" for i in range(20)]
        for s in shingles(words):
            assert len(s) == 16
            int(s, 16)  # doit être un hexa valide

    def test_textes_differents_empreintes_differentes(self):
        a = shingles(normalize("Le soleil se levait sur la ville aux murs"))
        b = shingles(normalize("La pluie battait les vitres de la taverne"))
        if a and b:
            assert a != b

    def test_taille_personnalisee(self):
        words = [f"m{i}" for i in range(10)]
        s3 = shingles(words, size=3)
        assert len(s3) == 10 - 3 + 1


class TestRefuseRepoSource:
    """Un fichier DANS le dépôt est refusé bruyamment."""

    def test_chemin_dans_le_depot(self, tmp_path: Path):
        fake = ROOT / "test_canon_fixture_temp.txt"
        try:
            fake.write_text("test", encoding="utf-8")
            with pytest.raises(ValueError, match="DANS le dépôt"):
                refuse_repo_source(fake)
        finally:
            fake.unlink(missing_ok=True)

    def test_chemin_exterieur_passe(self, tmp_path: Path):
        ext = tmp_path / "nouveau-soleil.txt"
        ext.write_text("test", encoding="utf-8")
        refuse_repo_source(ext)


# ═══════════════════════════════════════════════════════════════════════════
# 2. CanonIndex — opérations en mémoire (tmp_path)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def idx(tmp_path: Path) -> CanonIndex:
    """Index frais, fichier dans tmp_path."""
    return CanonIndex(tmp_path / "canon_index.json")


class TestIngestText:
    """Ingestion depuis un texte brut (pas de fichier requis)."""

    def test_decompte_mots_et_empreintes(self, idx: CanonIndex):
        result = idx.ingest_text(PASSAGE_A, work="Passage A")
        assert result["words"] > 0
        assert result["shingles"] > 0
        assert result["slug"] == "passage-a"

    def test_oeuvre_trop_courte_leve(self, idx: CanonIndex):
        short = "quelques mots"
        with pytest.raises(ValueError, match="il en faut au moins"):
            idx.ingest_text(short, work="Trop court")

    def test_remplacement_jamais_accumulation(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Test")
        nb_shingles_a = len(idx._load()["shingles"])
        idx.ingest_text(PASSAGE_B, work="Test")  # même slug → remplace
        assert len(idx.works()) == 1
        work = idx.works()[0]
        assert work["title"] == "Test"
        # Les shingles de PASSAGE_A doivent avoir été remplacées par celles de B
        nb_shingles_b = len(idx._load()["shingles"])
        # Si forget ne marche pas, nb_shingles_b > nb_shingles_a
        assert nb_shingles_b <= nb_shingles_a + 10, (
            f"Shingles accumulées : {nb_shingles_a} avant, {nb_shingles_b} après — "
            "forget() n'a pas nettoyé les anciennes empreintes"
        )

    def test_plusieurs_oeuvres(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Œuvre A")
        idx.ingest_text(PASSAGE_B, work="Œuvre B")
        assert len(idx.works()) == 2

    def test_slug_normalisation(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Le Livre du Nouveau Soleil")
        idx.ingest_text(PASSAGE_A, work="Le livre Du nouveau soleil")
        assert len(idx.works()) == 1

    def test_licence_enregistree(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Test", license="tous droits réservés")
        assert idx.works()[0]["license"] == "tous droits réservés"


class TestForget:
    """Retrait d'une œuvre et nettoyage de ses empreintes."""

    def test_forget_existant(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="À oublier")
        assert idx.forget("À oublier") is True
        assert len(idx.works()) == 0

    def test_forget_inexistant(self, idx: CanonIndex):
        assert idx.forget("N'existe pas") is False

    def test_forget_nettoie_les_shingles(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Test")
        data = idx._load()
        nb_avant = len(data["shingles"])
        assert nb_avant > 0
        idx.forget("Test")
        data_apres = idx._load()
        assert len(data_apres["shingles"]) == 0

    def test_forget_selectif(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="A")
        idx.ingest_text(PASSAGE_B, work="B")
        idx.forget("A")
        assert len(idx.works()) == 1
        assert idx.works()[0]["slug"] == "b"


class TestAttribute:
    """Attribution : « d'où vient ce texte ? » — repères, jamais de texte."""

    def test_texte_indexe_trouve(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source A")
        extrait = "Le soleil ancien se levait sur la ville aux murs"
        hits = idx.attribute(extrait)
        assert len(hits) > 0
        assert hits[0]["work"] == "Source A"

    def test_texte_etranger_pas_de_hit(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source A")
        hits = idx.attribute(TEXTE_INNOVE)
        for h in hits:
            assert h["work"] != "Source A"

    def test_resultats_sont_des_reperes(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source A")
        hits = idx.attribute("Le soleil ancien se levait sur la ville aux murs")
        for h in hits:
            assert "passage" in h
            assert "windows" in h
            assert isinstance(h["passage"], int)

    def test_index_vide(self, idx: CanonIndex):
        hits = idx.attribute("n'importe quoi")
        assert hits == []


class TestCheck:
    """Verdict chiffré : ok / warn / blocked."""

    def test_texte_innove_ok(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        report = idx.check(TEXTE_INNOVE)
        assert report["verdict"] == "ok"
        assert report["blocked"] is False

    def test_copie_franche_bloquee(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        report = idx.check(COPIE_FRANCHE)
        assert report["blocked"] is True
        assert report["verdict"] == "blocked"
        assert report["longest_run_words"] > MAX_QUOTE_WORDS

    def test_index_vide_ok(self, idx: CanonIndex):
        report = idx.check("Tout texte passe quand l'index est vide")
        assert report["verdict"] == "ok"
        assert report["words"] > 0

    def test_texte_tres_court_ok(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        report = idx.check("un mot")
        assert report["verdict"] == "ok"

    def test_champs_du_rapport(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        report = idx.check(TEXTE_INNOVE)
        assert "verdict" in report
        assert "blocked" in report
        assert "words" in report
        assert "longest_run_words" in report
        assert "quotes" in report
        assert "overlap_pct" in report
        assert "matched_windows" in report
        assert "sources" in report
        assert "reason" in report

    def test_plusieurs_citations_detectees(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        mots_a = normalize(PASSAGE_A)
        fenetre1 = " ".join(mots_a[0:SHINGLE_WORDS + 5])
        fenetre2 = " ".join(mots_a[100:100 + SHINGLE_WORDS + 5])
        texte = f"{fenetre1}. La taverne était calme et la pluie tombait. {fenetre2}."
        report = idx.check(texte)
        if report["matched_windows"] > 0:
            assert report["quotes"] >= 1


class TestGuard:
    """`guard()` = `check()` qui lève CopyrightViolation."""

    def test_guard_leve_sur_copie(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        with pytest.raises(CopyrightViolation) as exc_info:
            idx.guard(COPIE_FRANCHE, what="le texte de test")
        assert "recopie" in str(exc_info.value)
        assert hasattr(exc_info.value, "report")
        assert exc_info.value.report["blocked"] is True

    def test_guard_passe_sur_inspiration(self, idx: CanonIndex):
        idx.ingest_text(PASSAGE_A, work="Source")
        report = idx.guard(TEXTE_INNOVE)
        assert report["blocked"] is False

    def test_guard_passe_avec_index_vide(self, idx: CanonIndex):
        report = idx.guard("Tout passe quand l'index est vide")
        assert report["blocked"] is False


class TestCopyrightViolation:
    """L'exception porte le rapport complet."""

    def test_porte_le_report(self):
        report = {"blocked": True, "reason": "test"}
        exc = CopyrightViolation("msg", report=report)
        assert exc.report is report
        assert str(exc) == "msg"


# ═══════════════════════════════════════════════════════════════════════════
# 3. INVARIANT CRITIQUE — l'index ne contient aucun mot de l'œuvre
# ═══════════════════════════════════════════════════════════════════════════


class TestInvariantNoSourceText:
    """L'index persisté ne contient que des sha1 et des locateurs.

    C'est le cœur du gate copyright : un index qui conserve le texte pour
    « se défendre » EST la fuite qu'il prétend empêcher.
    """

    def test_json_ne_contient_pas_de_mots_de_loeuvre(self, tmp_path: Path):
        idx = CanonIndex(tmp_path / "canon.json")
        idx.ingest_text(PASSAGE_A, work="Livre du Nouveau Soleil")
        idx.ingest_text(PASSAGE_B, work="Second texte")
        raw = json.loads((tmp_path / "canon.json").read_text(encoding="utf-8"))
        json_str = json.dumps(raw, ensure_ascii=False)
        mots_distinctifs = normalize("bourreau marchait seul reliques labyrinthe")
        for mot in mots_distinctifs:
            assert mot not in json_str, (
                f"Le mot '{mot}' de l'œuvre source se retrouve dans l'index JSON"
            )

    def test_index_ne_contient_que_des_hexa_et_locateurs(self, tmp_path: Path):
        idx = CanonIndex(tmp_path / "canon.json")
        idx.ingest_text(PASSAGE_A, work="Test")
        raw = json.loads((tmp_path / "canon.json").read_text(encoding="utf-8"))
        for key in raw["shingles"]:
            assert len(key) == 16
            int(key, 16)
        for locators in raw["shingles"].values():
            for loc in locators:
                assert "#" in loc

    def test_texte_source_non_reconstructible(self, tmp_path: Path):
        idx = CanonIndex(tmp_path / "canon.json")
        idx.ingest_text(PASSAGE_A, work="Secret")
        raw = json.loads((tmp_path / "canon.json").read_text(encoding="utf-8"))
        json_str = json.dumps(raw, ensure_ascii=False)
        mots = normalize(PASSAGE_A)
        for i in range(0, len(mots) - 20, 20):
            fragment = " ".join(mots[i:i + 20])
            assert fragment not in json_str


# ═══════════════════════════════════════════════════════════════════════════
# 4. FICHIER — ingestion depuis un vrai fichier temporaire
# ═══════════════════════════════════════════════════════════════════════════


class TestIngestFile:
    """Flux complet : fichier → ingestion → attribution → gate."""

    def test_ingest_file_hors_depot(self, tmp_path: Path):
        source = tmp_path / "nouveau-soleil.txt"
        source.write_text(PASSAGE_A, encoding="utf-8")
        idx = CanonIndex(tmp_path / "index.json")
        result = idx.ingest_file(source, work="Le Livre du Nouveau Soleil",
                                 license="tous droits réservés")
        assert result["work"] == "Le Livre du Nouveau Soleil"
        assert result["shingles"] > 0

    def test_ingest_file_dans_le_depot_leve(self, tmp_path: Path):
        fake = ROOT / "test_canon_temp_fixture.txt"
        try:
            fake.write_text(PASSAGE_A, encoding="utf-8")
            idx = CanonIndex(tmp_path / "index.json")
            with pytest.raises(ValueError, match="DANS le dépôt"):
                idx.ingest_file(fake)
        finally:
            fake.unlink(missing_ok=True)

    def test_workflow_complet(self, tmp_path: Path):
        source = tmp_path / "source.txt"
        source.write_text(PASSAGE_A, encoding="utf-8")
        idx = CanonIndex(tmp_path / "index.json")
        idx.ingest_file(source, work="Source")

        extrait = "Le soleil ancien se levait sur la ville"
        hits = idx.attribute(extrait)
        assert any(h["work"] == "Source" for h in hits)

        with pytest.raises(CopyrightViolation):
            idx.guard(COPIE_FRANCHE)

        report = idx.guard(TEXTE_INNOVE)
        assert report["blocked"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 5. PERSISTANCE — le JSON survit à un cycle load/save
# ═══════════════════════════════════════════════════════════════════════════


class TestPersistance:
    """L'index se recharge correctement depuis le disque."""

    def test_survie_au_rechargement(self, tmp_path: Path):
        path = tmp_path / "canon.json"
        idx1 = CanonIndex(path)
        idx1.ingest_text(PASSAGE_A, work="Persistant")

        idx2 = CanonIndex(path)
        assert len(idx2.works()) == 1
        assert idx2.works()[0]["slug"] == "persistant"

        hits = idx2.attribute("Le soleil ancien se levait sur la ville")
        assert any(h["work"] == "Persistant" for h in hits)

    def test_persistance_apres_forget(self, tmp_path: Path):
        path = tmp_path / "canon.json"
        idx1 = CanonIndex(path)
        idx1.ingest_text(PASSAGE_A, work="A")
        idx1.ingest_text(PASSAGE_B, work="B")
        idx1.forget("A")

        idx2 = CanonIndex(path)
        assert len(idx2.works()) == 1
        assert idx2.works()[0]["slug"] == "b"


# ═══════════════════════════════════════════════════════════════════════════
# 6. get_canon / reset_canon — singleton par chemin
# ═══════════════════════════════════════════════════════════════════════════


class TestSingleton:
    """Gestion du singleton CanonIndex."""

    def test_reset_clear_cache(self, tmp_path: Path):
        path = tmp_path / "test.json"
        c1 = get_canon(path)
        c2 = get_canon(path)
        assert c1 is c2
        reset_canon()
        c3 = get_canon(path)
        assert c3 is not c1

    def test_chemins_differents_instances_differentes(self, tmp_path: Path):
        c1 = get_canon(tmp_path / "a.json")
        c2 = get_canon(tmp_path / "b.json")
        assert c1 is not c2
        reset_canon()


# ═══════════════════════════════════════════════════════════════════════════
# 7. DOCTRINE — les seuils de CLAUDE.md §3 sont encodés
# ═══════════════════════════════════════════════════════════════════════════


class TestDoctrine:
    """Les seuils ne sont pas des paramètres ajustables."""

    def test_max_quote_words_est_15(self):
        assert MAX_QUOTE_WORDS == 15

    def test_max_quotes_est_1(self):
        assert MAX_QUOTES == 1

    def test_shingle_words_sous_la_limite_citation(self):
        assert SHINGLE_WORDS <= MAX_QUOTE_WORDS
