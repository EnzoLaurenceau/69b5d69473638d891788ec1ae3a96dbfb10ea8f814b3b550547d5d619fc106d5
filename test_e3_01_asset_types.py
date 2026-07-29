"""Tests E3-01 — ArtifactType étendu pour les assets RPG.

Le Harness ne connaissait que les types web (CODE, WEBSITE, BOT…). Les assets
d'un jeu — concept art, sprites, textures, modèles 3D, rigs, animations, VFX —
avaient le score 100/100 par défaut (pas de gates = tout passe). Ce ticket
ajoute 7 types + des gates réels (existence, format, taille).

Deux étages :
  1. **Enum** — les types existent, ont des gates, sont sérialisables.
  2. **Gates** — les checks fonctionnent sur de vrais fichiers temporaires.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.harness_engine import (  # noqa: E402
    ArtifactType,
    HarnessEngine,
    HarnessResult,
    QualityGate,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ENUM — les 7 types jeu existent
# ═══════════════════════════════════════════════════════════════════════════


GAME_TYPES = [
    ArtifactType.CONCEPT,
    ArtifactType.SPRITE,
    ArtifactType.TEXTURE,
    ArtifactType.MODEL_3D,
    ArtifactType.RIG,
    ArtifactType.ANIM,
    ArtifactType.VFX,
]


class TestEnum:
    """Les types jeu sont dans l'enum et ont la bonne valeur."""

    @pytest.mark.parametrize("member,expected", [
        (ArtifactType.CONCEPT, "concept"),
        (ArtifactType.SPRITE, "sprite"),
        (ArtifactType.TEXTURE, "texture"),
        (ArtifactType.MODEL_3D, "model_3d"),
        (ArtifactType.RIG, "rig"),
        (ArtifactType.ANIM, "anim"),
        (ArtifactType.VFX, "vfx"),
    ])
    def test_valeur_enum(self, member, expected):
        assert member.value == expected

    def test_17_types_au_total(self):
        """10 types web/dev + 7 types jeu."""
        assert len(ArtifactType) == 17

    def test_tous_les_types_sont_json_serializable(self):
        """Un type doit pouvoir être stocké dans un log JSON."""
        for t in ArtifactType:
            s = json.dumps({"type": t.value})
            assert json.loads(s)["type"] == t.value


# ═══════════════════════════════════════════════════════════════════════════
# 2. GATES — chaque type jeu a des gates définis
# ═══════════════════════════════════════════════════════════════════════════


class TestGatesExist:
    """Chaque type jeu a au moins 2 gates dans GATES."""

    @pytest.mark.parametrize("atype", GAME_TYPES)
    def test_a_des_gates(self, atype):
        engine = HarnessEngine()
        gates = engine.GATES.get(atype, [])
        assert len(gates) >= 2, f"{atype.value} n'a que {len(gates)} gate(s)"

    @pytest.mark.parametrize("atype", GAME_TYPES)
    def test_a_un_gate_existence(self, atype):
        """Chaque type a un gate 'asset_file_exists' (critical)."""
        engine = HarnessEngine()
        gates = engine.GATES.get(atype, [])
        existence_gates = [g for g in gates if g.name == "asset_file_exists"]
        assert len(existence_gates) == 1
        assert existence_gates[0].severity == "critical"

    @pytest.mark.parametrize("atype", GAME_TYPES)
    def test_a_un_gate_file_size(self, atype):
        """Chaque type a un gate 'file_size' avec un seuil."""
        engine = HarnessEngine()
        gates = engine.GATES.get(atype, [])
        size_gates = [g for g in gates if g.name == "file_size"]
        assert len(size_gates) == 1
        assert size_gates[0].threshold is not None
        assert size_gates[0].threshold > 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. CHECKS — les vrais checks sur des fichiers temporaires
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def engine():
    return HarnessEngine()


class TestAssetFileExists:
    """Le check d'existence fonctionne."""

    def test_fichier_existant(self, engine, tmp_path):
        f = tmp_path / "exists.png"
        f.write_bytes(b"\x89PNG\r\n")
        result = engine._check_asset_file_exists(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert result.passed

    def test_fichier_manquant(self, engine):
        result = engine._check_asset_file_exists(
            QualityGate("t", "", "critical", "t"), ["/nonexistent/foo.png"])
        assert not result.passed
        assert "Missing" in result.details


class TestFileSize:
    """Le check de taille respecte le seuil."""

    def test_sous_le_seuil(self, engine, tmp_path):
        f = tmp_path / "small.png"
        f.write_bytes(b"\x00" * 1024)  # 1 KB
        gate = QualityGate("t", "", "high", "t", threshold=5)
        result = engine._check_file_size(gate, [str(f)])
        assert result.passed

    def test_depasse_le_seuil(self, engine, tmp_path):
        f = tmp_path / "big.fbx"
        f.write_bytes(b"\x00" * (6 * 1024 * 1024))  # 6 MB
        gate = QualityGate("t", "", "high", "t", threshold=5)
        result = engine._check_file_size(gate, [str(f)])
        assert not result.passed
        assert "MB" in result.details


class TestFormatChecks:
    """Les checks de format rejettent les mauvaises extensions."""

    def test_image_format_accepte_png(self, engine, tmp_path):
        f = tmp_path / "art.png"
        f.write_bytes(b"\x89PNG")
        result = engine._check_image_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert result.passed

    def test_image_format_rejette_fbx(self, engine, tmp_path):
        f = tmp_path / "model.fbx"
        f.write_bytes(b"FBX")
        result = engine._check_image_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert not result.passed

    def test_sprite_format_accepte_webp(self, engine, tmp_path):
        f = tmp_path / "char.webp"
        f.write_bytes(b"RIFF")
        result = engine._check_sprite_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert result.passed

    def test_sprite_format_rejette_jpg(self, engine, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff")
        result = engine._check_sprite_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert not result.passed

    def test_texture_format_accepte_tga(self, engine, tmp_path):
        f = tmp_path / "wall.tga"
        f.write_bytes(b"\x00")
        result = engine._check_texture_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert result.passed

    def test_model_format_accepte_gltf(self, engine, tmp_path):
        f = tmp_path / "mesh.gltf"
        f.write_bytes(b"{}")
        result = engine._check_model_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert result.passed

    def test_model_format_rejette_png(self, engine, tmp_path):
        f = tmp_path / "not_a_model.png"
        f.write_bytes(b"\x89PNG")
        result = engine._check_model_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert not result.passed

    def test_anim_format_accepte_bvh(self, engine, tmp_path):
        f = tmp_path / "walk.bvh"
        f.write_bytes(b"HIERARCHY")
        result = engine._check_anim_format(
            QualityGate("t", "", "critical", "t"), [str(f)])
        assert result.passed

    def test_vfx_format_accepte_shader(self, engine, tmp_path):
        f = tmp_path / "fire.shader"
        f.write_bytes(b"Shader")
        result = engine._check_vfx_format(
            QualityGate("t", "", "high", "t"), [str(f)])
        assert result.passed

    def test_vfx_format_rejette_fbx(self, engine, tmp_path):
        f = tmp_path / "effect.fbx"
        f.write_bytes(b"FBX")
        result = engine._check_vfx_format(
            QualityGate("t", "", "high", "t"), [str(f)])
        assert not result.passed


# ═══════════════════════════════════════════════════════════════════════════
# 4. VALIDATE — le pipeline complet sur un type jeu
# ═══════════════════════════════════════════════════════════════════════════


class TestValidate:
    """validate() fonctionne sur les types jeu comme sur les types web."""

    def test_concept_valide(self, engine, tmp_path):
        """Un PNG existant et de taille raisonnable passe les gates CONCEPT."""
        f = tmp_path / "mood.png"
        f.write_bytes(b"\x89PNG" + b"\x00" * 1024)
        result = engine.validate(ArtifactType.CONCEPT, [str(f)])
        assert isinstance(result, HarnessResult)
        assert result.artifact_type == ArtifactType.CONCEPT
        assert result.gates_checked > 0

    def test_sprite_fichier_manquant(self, engine):
        """Un fichier inexistant échoue au gate critical d'existence."""
        result = engine.validate(ArtifactType.SPRITE, ["/no/such/file.png"])
        assert not result.passed
        assert len(result.critical_failures) > 0

    def test_model_3d_valide(self, engine, tmp_path):
        f = tmp_path / "mesh.fbx"
        f.write_bytes(b"FBX" + b"\x00" * 1024)
        result = engine.validate(ArtifactType.MODEL_3D, [str(f)])
        assert result.gates_checked >= 2

    def test_score_et_grade(self, engine, tmp_path):
        """Le résultat a un score et un grade (hérité de HarnessResult)."""
        f = tmp_path / "anim.bvh"
        f.write_bytes(b"HIERARCHY" + b"\x00" * 1024)
        result = engine.validate(ArtifactType.ANIM, [str(f)])
        assert 0 <= result.score <= 100
        assert result.grade in ("A", "B", "C", "D", "F")


# ═══════════════════════════════════════════════════════════════════════════
# 5. ARTIFACT_QUALITY — les extensions sont mappées
# ═══════════════════════════════════════════════════════════════════════════


class TestExtensionMapping:
    """Les extensions jeu sont mappées vers 'asset' dans artifact_quality."""

    @pytest.mark.parametrize("ext", [
        ".fbx", ".obj", ".gltf", ".glb", ".blend", ".dae",
        ".psd", ".aseprite", ".shader", ".hlsl", ".bvh", ".anim",
    ])
    def test_extension_mappee(self, ext):
        from forge_agents.artifact_quality import EXTENSIONS
        assert ext in EXTENSIONS, f"{ext} manque dans EXTENSIONS"
        assert EXTENSIONS[ext] == "asset"
