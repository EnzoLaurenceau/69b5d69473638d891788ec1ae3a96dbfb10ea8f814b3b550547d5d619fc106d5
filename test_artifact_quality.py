"""Tests E6-02 — score qualité normalisé 0-100 par type d'artefact.

Trois étages :

1. **Pur** — la normalisation elle-même : un critère non mesuré sort du
   dénominateur, un lot entièrement non mesuré vaut `None` (jamais 0, jamais
   100), et le barème A-F est celui de `herald_audit`.
2. **Sondes** — chaque type contre un vrai fichier fabriqué pour l'occasion :
   PNG uniforme, WAV silencieux, WAV saturé, Python cassé, markdown à trous.
   Ce qui est vérifié n'est pas « une note sort » mais « la note baisse pour la
   raison annoncée ».
3. **Régression Harness** — les trois mensonges constatés avant d'écrire le
   module : gates injoignables passées par défaut, `flake8 clean` sans flake8,
   `HarnessResult.grade` inexistant. Un test par mensonge, pour qu'aucun ne
   revienne en silence.
"""

from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.artifact_quality import (  # noqa: E402
    ASSET,
    AUDIO,
    CAP_BLOCKED,
    CODE,
    CRITICAL,
    HIGH,
    NARRATIVE,
    UNKNOWN,
    Criterion,
    _band,
    _normalize,
    classify,
    grade_of,
    quality_of,
    score_artifact,
    score_artifacts,
)

PIL = pytest.importorskip("PIL.Image", reason="Pillow requis pour les sondes image")


# ══════════════════════════════════════════════════════════════════════════════
# 1. NORMALISATION — le cœur du ticket
# ══════════════════════════════════════════════════════════════════════════════

def test_normalise_sur_les_seuls_criteres_mesures():
    """Un critère non mesuré sort du dénominateur — il n'est PAS un succès.

    C'est l'erreur exacte du Harness (`passed=True` par défaut) : elle transforme
    une sonde muette en note pleine.
    """
    score, confidence = _normalize([
        Criterion("a", 3.0, 1.0),
        Criterion("b", 3.0, 0.0),
        Criterion("c", 4.0, None),      # muet : ni bonus ni malus
    ])
    assert score == 50.0                # 3/(3+3), et non 3/10
    assert confidence == 0.6            # 6 poids mesurés sur 10 déclarés


def test_aucune_mesure_donne_none_pas_zero_ni_cent():
    score, confidence = _normalize([Criterion("a", 3.0, None),
                                    Criterion("b", 1.0, None)])
    assert score is None
    assert confidence == 0.0


def test_grade_absent_nest_pas_un_f():
    """`?` dit « pas mesuré », `F` dit « mauvais ». Les confondre fait jeter un
    livrable correct qu'on n'a pas su ausculter."""
    assert grade_of(None) == "?"
    assert grade_of(0.0) == "F"
    assert (grade_of(90), grade_of(70), grade_of(50), grade_of(30)) == ("A", "B", "C", "D")


def test_bande_lineaire_bornee():
    assert _band(0, 0, 10) == 0.0
    assert _band(10, 0, 10) == 1.0
    assert _band(5, 0, 10) == 0.5
    assert _band(-3, 0, 10) == 0.0 and _band(99, 0, 10) == 1.0


def test_classify_ne_devine_jamais():
    assert classify("a/b/c.py") == CODE
    assert classify("hero.PNG") == ASSET
    assert classify("theme.wav") == AUDIO
    assert classify("quete.md") == NARRATIVE
    # Ni JSON ni INI ne sont rangés dans le type « le plus proche ».
    assert classify("data.json") == UNKNOWN
    assert classify("pytest.ini") == UNKNOWN
    assert classify("Makefile") == UNKNOWN


def test_moyenne_du_lot_ignore_les_non_notes_mais_les_compte():
    """Un artefact non notable ne doit ni tirer la moyenne vers le bas ni
    disparaître : il sort du calcul ET reste listé."""
    unknown = ROOT / "pytest.ini"
    result = score_artifacts([str(unknown)])
    assert result["score"] is None and result["scored"] == 0
    assert result["unscored"] == [str(unknown)]
    assert result["artifacts"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 2. SONDES PAR TYPE
# ══════════════════════════════════════════════════════════════════════════════

def _criterion(quality, name) -> Criterion:
    return next(c for c in quality.criteria if c.name == name)


# ── code ──────────────────────────────────────────────────────────────────────

def test_code_syntaxe_cassee_effondre_le_score(tmp_path):
    bad = tmp_path / "casse.py"
    bad.write_text("def f(:\n    pass\n", encoding="utf-8")
    q = score_artifact(bad)
    assert q.kind == CODE
    assert _criterion(q, "syntax").value == 0.0
    assert q.score < 70                       # une syntaxe morte ne passe pas


def test_code_docstrings_et_annotations_sont_gradues(tmp_path):
    """Le Harness bascule à un seuil fixe (>10 manquants) : sur 2 fonctions il
    ne bascule jamais. Une proportion, elle, mesure."""
    src = tmp_path / "moitie.py"
    src.write_text(
        'def documentee(x: int) -> int:\n'
        '    """Docstring."""\n'
        '    return x\n\n'
        'def nue(x):\n'
        '    return x\n', encoding="utf-8")
    q = score_artifact(src)
    assert _criterion(q, "docstrings").value == 0.5
    assert _criterion(q, "type_hints").value == 0.5


def test_code_secret_en_dur_est_attrape(tmp_path):
    src = tmp_path / "fuite.py"
    src.write_text('API_KEY = "sk-abcdefghijklmnopqrstuvwxyz0123"\n', encoding="utf-8")
    q = score_artifact(src)
    assert _criterion(q, "no_secrets").value == 0.0


def test_code_non_python_laisse_ses_sondes_muettes(tmp_path):
    """Un `.js` n'a ni AST ni linter ici. Les sondes concernées ressortent NON
    mesurées — et la confiance le dit — au lieu de « réussies »."""
    js = tmp_path / "script.js"
    js.write_text("export const x = 1;\n", encoding="utf-8")
    q = score_artifact(js)
    assert q.kind == CODE
    assert _criterion(q, "syntax").value is None
    assert _criterion(q, "no_print").value is None
    assert q.confidence < 0.5
    assert q.score is not None                # les sondes textuelles, elles, ont parlé


def test_code_tests_cherches_ailleurs_que_dans_le_dossier():
    """Dans cette Forge les tests vivent à la RACINE. Ne regarder que le dossier
    du fichier faisait répondre « absent » à tous les coups."""
    q = score_artifact(ROOT / "00_CORE" / "forge_agents" / "forge_task_ledger.py")
    assert _criterion(q, "tests_exist").value == 1.0


# ── asset ─────────────────────────────────────────────────────────────────────

def _png(path: Path, size=(64, 64), color=(0, 0, 0, 0)):
    from PIL import Image
    Image.new("RGBA", size, color).save(path)
    return path


def test_asset_image_uniforme_est_un_rendu_vide(tmp_path):
    """Le mode d'échec le plus courant d'une chaîne d'assets — et invisible à
    toute vérification de format."""
    q = score_artifact(_png(tmp_path / "vide.png"))
    assert _criterion(q, "readable").value == 1.0      # le fichier est valide…
    assert _criterion(q, "not_blank").value == 0.0     # …et pourtant vide
    assert q.score < 70


def test_asset_image_pleine_passe(tmp_path):
    from PIL import Image
    img = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
    for x in range(64):
        img.putpixel((x, x), (255, 255, 255, 255))
    path = tmp_path / "sprite.png"
    img.save(path)
    q = score_artifact(path)
    assert _criterion(q, "not_blank").value == 1.0
    assert q.score >= 70


def test_asset_extension_mensongere_est_detectee(tmp_path):
    """Un `.png` qui est en fait une page d'erreur HTML : mode d'échec réel des
    pipelines génératifs."""
    faux = tmp_path / "hero.png"
    faux.write_bytes(b"<html><body>404</body></html>")
    q = score_artifact(faux)
    assert _criterion(q, "readable").value == 0.0
    assert _criterion(q, "container").value == 0.0
    assert q.score is not None and q.score < 30


def test_asset_svg_sans_dessin(tmp_path):
    vide = tmp_path / "icone.svg"
    vide.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"></svg>',
                    encoding="utf-8")
    q = score_artifact(vide)
    assert _criterion(q, "readable").value == 1.0
    assert _criterion(q, "not_blank").value == 0.0


# ── audio ─────────────────────────────────────────────────────────────────────

def _wav(path: Path, samples, rate=44100, width=2, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return path


def test_audio_silence_est_detecte(tmp_path):
    """Un silence est LISIBLE, de durée saine, à 44,1 kHz, sans saturation ni
    offset : toutes ses sondes sauf une disent « bon ». Sans plafond, il sortait
    à 76,9/100 — un B pour un fichier inutilisable. C'est ce cas qui a imposé
    `CAP_BLOCKED`."""
    q = score_artifact(_wav(tmp_path / "silence.wav", [0] * 4410))
    assert _criterion(q, "readable").value == 1.0
    assert _criterion(q, "not_silent").value == 0.0
    assert q.score == CAP_BLOCKED
    assert q.grade == "D"


def test_audio_sature_perd_sur_le_clipping(tmp_path):
    q = score_artifact(_wav(tmp_path / "sature.wav", [32767, -32768] * 2205))
    assert _criterion(q, "not_silent").value == 1.0
    assert _criterion(q, "no_clipping").value == 0.0


def test_audio_propre_passe(tmp_path):
    import math
    samples = [int(16000 * math.sin(2 * math.pi * 440 * n / 44100))
               for n in range(44100)]
    q = score_artifact(_wav(tmp_path / "note.wav", samples))
    assert q.score >= 90
    assert _criterion(q, "dc_offset").value > 0.9


def test_audio_basse_qualite_note_plus_bas_sans_echouer(tmp_path):
    import math
    samples = [int(16000 * math.sin(2 * math.pi * 220 * n / 16000))
               for n in range(16000)]
    q = score_artifact(_wav(tmp_path / "bas.wav", samples, rate=16000))
    assert _criterion(q, "sample_rate").value == 0.3
    assert 70 <= q.score < 100


def test_audio_non_wav_reste_non_mesure_plutot_que_note_plein(tmp_path):
    """Aucune dépendance audio dans cette Forge : un `.ogg` ne doit pas sortir à
    100 parce que personne ne sait le lire."""
    ogg = tmp_path / "theme.ogg"
    ogg.write_bytes(b"OggS" + b"\x00" * 60)
    q = score_artifact(ogg)
    assert _criterion(q, "readable").value is None
    assert q.confidence < 0.2
    assert q.score == 100.0            # sur la seule signature…
    assert "signature" in q.note        # …et le rapport le dit


# ── narratif ──────────────────────────────────────────────────────────────────

def test_narratif_gabarit_residuel_est_un_trou(tmp_path):
    md = tmp_path / "quete.md"
    md.write_text("# La Griffe\n\nTODO: écrire la quête.\n" + "mot " * 400,
                  encoding="utf-8")
    q = score_artifact(md)
    assert _criterion(q, "no_placeholder").value == 0.0


def test_narratif_repetition_est_penalisee(tmp_path):
    ligne = ("Le vieux gardien répète toujours la même chose devant la porte close. ")
    md = tmp_path / "boucle.md"
    md.write_text("# Boucle\n\n" + ligne * 12, encoding="utf-8")
    q = score_artifact(md)
    assert _criterion(q, "no_repetition").value == 0.0


def test_narratif_fragment_perd_sur_la_substance(tmp_path):
    md = tmp_path / "bribe.md"
    md.write_text("# Titre\n\nTrois mots.\n", encoding="utf-8")
    q = score_artifact(md)
    assert _criterion(q, "substance").value == 0.0
    assert _criterion(q, "no_repetition").value is None   # trop court pour juger


def test_narratif_ancrage_compte_les_noms_hors_monde(tmp_path):
    """LE critère qui distingue un texte de jeu d'un texte bien écrit : un PNJ
    inventé en cours de rédaction est indétectable au style, et fatal à la
    cohérence. Ici deux noms sur trois existent dans le monde, le troisième non.
    """
    kuzu = pytest.importorskip("kuzu", reason="World-KG requis")   # noqa: F841
    from forge_agents import world_kg as wk

    monde = wk.WorldKG(world_id="test-e6-02", db_path=tmp_path / "world")
    monde.add_character("Severian", role="protagoniste")
    monde.add_character("Thecla", aliases=["la chatelaine"])
    monde.add_location("Nessus")
    # Le scoreur passe par le registre singleton : on y branche CE monde-là.
    wk._WORLDS[monde.world_id] = monde
    try:
        md = tmp_path / "chapitre.md"
        md.write_text(
            "# Chapitre\n\n"
            "Le voyage de Severian vers Nessus dure trois jours pleins.\n\n"
            "La chatelaine attend dans la tour, et Baldanders surveille.\n\n"
            + "Les rues restent vides sous la pluie battante. " * 20,
            encoding="utf-8")
        q = score_artifact(md, world_id="test-e6-02")
        grounded = _criterion(q, "grounded")
        assert grounded.value is not None
        assert 0.0 < grounded.value < 1.0
        assert "Baldanders" in grounded.detail        # nommé, donc contestable
        assert "Severian" not in grounded.detail      # ancré, donc tu
    finally:
        wk._WORLDS.pop(monde.world_id, None)
        wk.reset_world_kg()


def test_narratif_ancrage_non_mesure_sans_monde(tmp_path):
    """Sans monde de référence, sanctionner un nom propre reviendrait à noter au
    hasard : le critère sort NON mesuré et la confiance baisse."""
    md = tmp_path / "lore.md"
    md.write_text("# Lore\n\n" + "Severian marche vers Nessus. " * 30, encoding="utf-8")
    q = score_artifact(md)
    grounded = _criterion(q, "grounded")
    assert grounded.value is None
    assert grounded.weight == CRITICAL
    assert q.confidence < 1.0


# ══════════════════════════════════════════════════════════════════════════════
# 3. HONNÊTETÉ DE BOUT EN BOUT
# ══════════════════════════════════════════════════════════════════════════════

def test_artefact_absent_nest_pas_un_artefact_mediocre(tmp_path):
    q = score_artifact(tmp_path / "jamais_ecrit.py")
    assert q.score is None and q.grade == "?"
    assert "introuvable" in q.note


def test_deux_executions_donnent_le_meme_chiffre(tmp_path):
    """Déterministe et gratuit : aucun appel LLM ne se glisse dans la note."""
    src = tmp_path / "stable.py"
    src.write_text('"""Doc."""\n\n\ndef f(x: int) -> int:\n    """D."""\n    return x\n',
                   encoding="utf-8")
    assert score_artifact(src).score == score_artifact(src).score


def test_quality_of_rend_un_seul_chiffre_ou_rien(tmp_path):
    assert quality_of([]) is None
    assert quality_of([str(ROOT / "pytest.ini")]) is None
    src = tmp_path / "ok.py"
    src.write_text('"""D."""\n', encoding="utf-8")
    assert isinstance(quality_of([str(src)]), float)


# ══════════════════════════════════════════════════════════════════════════════
# 4. RÉGRESSIONS HARNESS — les trois mensonges constatés
# ══════════════════════════════════════════════════════════════════════════════

def test_harness_execute_desormais_ses_gates(tmp_path):
    """Les gates déclarent `check="check_no_secrets"` ; le répartiteur ne
    cherchait que `_check_{check}`. Huit gates sur dix, dont trois `critical`,
    étaient « passées par défaut »."""
    from forge_agents.harness_engine import ArtifactType, HarnessEngine

    fuite = tmp_path / "fuite.py"
    fuite.write_text('password = "hunter2-hunter2"\n', encoding="utf-8")
    result = HarnessEngine().validate(ArtifactType.CODE, [fuite])

    details = " ".join(r.details for r in result.results)
    assert "passed by default" not in details
    assert not result.passed
    assert any("no_hardcoded_secrets" in f for f in result.critical_failures)


def test_le_png_note_comme_du_code_reste_un_trou_du_harness(tmp_path):
    """Le correctif du répartiteur ne suffit PAS à ce cas, et le test le dit.

    Toutes les gates CODE filtrent `.py` : sur un lot qui n'en contient aucun,
    chacune « réussit » sans avoir rien regardé, et le PNG ressort toujours à
    100/100. Ce qu'E6-02 garantit ici, c'est le CLASSEMENT (un PNG est un
    `asset`, jamais du code), pas le Harness. Point ouvert, pas point corrigé —
    ce test tombera le jour où quelqu'un fera refuser à `validate()` un lot
    étranger à son type, et c'est le moment de le réécrire.
    """
    from forge_agents.harness_engine import ArtifactType, HarnessEngine

    png = _png(tmp_path / "image.png")
    assert HarnessEngine().validate(ArtifactType.CODE, [png]).score == 100.0
    assert score_artifact(png).kind == ASSET
    assert score_artifact(png).score <= CAP_BLOCKED      # image uniforme


def test_harness_expose_un_grade():
    """`agent_nodes` lisait `_hr.grade` sur un objet qui ne l'avait pas :
    l'`AttributeError` partait dans un `except Exception` et le post-mortem
    n'affichait jamais rien."""
    from forge_agents.harness_engine import ArtifactType, HarnessEngine

    result = HarnessEngine().validate(ArtifactType.CODE,
                                      [ROOT / "00_CORE" / "forge_agents" / "forge_task_ledger.py"])
    assert result.grade in ("A", "B", "C", "D", "F")
    assert result.grade == grade_of(result.score)


def test_harness_ne_declare_pas_flake8_propre_sans_flake8(tmp_path):
    """`python -m flake8` absent sort en code ≠ 0 avec une sortie VIDE, lue
    comme « 0 erreur »."""
    import importlib.util

    from forge_agents.harness_engine import HarnessEngine, QualityGate

    if importlib.util.find_spec("flake8") is not None:
        pytest.skip("flake8 installé : le mensonge visé n'est pas observable ici")
    src = tmp_path / "quelconque.py"
    src.write_text("x = 1\n", encoding="utf-8")
    gate = QualityGate("lint_flake8", "", "high", "flake8", threshold=0)
    res = HarnessEngine()._check_flake8(gate, [src], None)
    assert "not installed" in res.details


def test_le_contenu_du_fichier_ne_peut_pas_se_faire_passer_pour_une_sonde_muette(tmp_path):
    """Le détail d'un échec Harness CITE le texte trouvé dans le fichier. Or
    « placeholder » est lui-même un motif anti-slop : reconnaître les sondes
    muettes par sous-chaîne transformait « AI slop detected: 'placeholder' » en
    « sonde indisponible » — donc en critère non mesuré, donc en meilleure note.
    Constaté sur le fichier de tests de ce module même."""
    from forge_agents.artifact_quality import _is_mute

    piege = tmp_path / "piege.py"
    piege.write_text('MESSAGE = "placeholder"\n', encoding="utf-8")
    assert _criterion(score_artifact(piege), "no_slop").value == 0.0

    assert _is_mute("No implementation (passed by default)")
    assert _is_mute("isort check (placeholder)")
    assert _is_mute("flake8 not installed (skipped)")
    assert not _is_mute("piege.py: AI slop detected: 'placeholder'")


def test_scoreur_ne_compte_pas_un_succes_par_defaut_du_harness(tmp_path):
    """Même si le Harness venait à repasser en mode « succès par défaut », le
    score E6-02 ne s'en nourrirait pas : ces détails sont lus comme NON mesurés."""
    from forge_agents import artifact_quality as aq

    class _Faux:
        passed = True
        details = "No implementation (passed by default)"

    monkey = lambda *a, **k: _Faux()  # noqa: E731
    assert callable(aq._harness_gate)
    from forge_agents.harness_engine import HarnessEngine

    original = HarnessEngine._check_no_secrets
    try:
        HarnessEngine._check_no_secrets = monkey
        src = tmp_path / "x.py"
        src.write_text("x = 1\n", encoding="utf-8")
        q = score_artifact(src)
        assert _criterion(q, "no_secrets").value is None
    finally:
        HarnessEngine._check_no_secrets = original


# ══════════════════════════════════════════════════════════════════════════════
# 5. BRANCHEMENT SUR E6-01
# ══════════════════════════════════════════════════════════════════════════════

def test_ledger_autoscore_remplit_le_champ_reste_vide(tmp_path):
    """E6-01 laissait `quality` à `None` faute de formule ; `autoscore=True` la
    calcule depuis les artefacts déclarés."""
    from forge_agents.forge_task_ledger import _score_artifacts

    src = tmp_path / "livrable.py"
    src.write_text('"""Doc."""\n\n\ndef f(x: int) -> int:\n    """D."""\n    return x\n',
                   encoding="utf-8")
    score, detail = _score_artifacts([str(src)])
    assert isinstance(score, float)
    assert detail["grade"] == grade_of(score)
    assert detail["by_kind"][CODE]["scored"] == 1


def test_ledger_autoscore_laisse_le_champ_vide_si_rien_de_notable():
    from forge_agents.forge_task_ledger import _score_artifacts

    score, detail = _score_artifacts([str(ROOT / "pytest.ini")])
    assert score is None                    # jamais 0
    assert detail["scored"] == 0


def test_ledger_sans_autoscore_ne_change_rien(tmp_path):
    """Non-régression : le comportement par défaut d'E6-01 est inchangé."""
    from forge_agents.forge_task_ledger import task_run

    run = task_run("E0-00", claim=False, complete=False)
    assert run.quality is None and run.autoscore is False
