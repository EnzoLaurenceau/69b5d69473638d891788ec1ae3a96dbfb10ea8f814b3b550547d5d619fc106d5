"""Tests E3-03 — Wrappers outils pour le pipeline d'assets.

La Forge n'avait aucun wrapper asset (audit §6 : pipelines=5/10). Ce ticket
ajoute quatre wrappers, trois en stub (ComfyUI, Blender, Aseprite — pas
installés) et un réel (Pillow — toujours disponible).

Trois étages :
  1. **Disponibilité** — les outils sont détectés correctement.
  2. **Pillow** — resize, crop, convert, sprite sheet, power-of-two.
  3. **Stubs** — ComfyUI, Blender, Aseprite lèvent proprement quand absents.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.asset_tools import (  # noqa: E402
    AsepriteOps,
    BlenderOps,
    ComfyUIOps,
    ImageInfo,
    PillowOps,
    aseprite_available,
    aseprite_ops,
    blender_available,
    blender_ops,
    comfyui_available,
    comfyui_ops,
    pillow_available,
    pillow_ops,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. DISPONIBILITÉ
# ═══════════════════════════════════════════════════════════════════════════


class TestAvailability:
    """Détection des outils."""

    def test_pillow_disponible(self):
        assert pillow_available() is True

    def test_comfyui_non_disponible(self):
        assert comfyui_available() is False

    def test_blender_non_disponible(self):
        assert blender_available() is False

    def test_aseprite_non_disponible(self):
        assert aseprite_available() is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. PILLOW — opérations réelles
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def img_512():
    """Image RGBA 512×512."""
    from PIL import Image
    return Image.new("RGBA", (512, 512), (100, 150, 200, 255))


@pytest.fixture
def img_300():
    """Image RGBA 300×200 (non carrée, non POT)."""
    from PIL import Image
    return Image.new("RGBA", (300, 200), (50, 100, 150, 255))


@pytest.fixture
def png_file(tmp_path, img_512):
    """Fichier PNG temporaire."""
    path = tmp_path / "test.png"
    pillow_ops.save(img_512, path, format="PNG")
    return path


class TestPillowOps:
    """Opérations image via Pillow."""

    def test_load(self, png_file):
        img = pillow_ops.load(png_file)
        assert img.size == (512, 512)

    def test_save_png(self, img_512, tmp_path):
        out = tmp_path / "saved.png"
        pillow_ops.save(img_512, out, format="PNG")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_info(self, png_file):
        info = pillow_ops.info(png_file)
        assert isinstance(info, ImageInfo)
        assert info.width == 512
        assert info.height == 512
        assert info.mode == "RGBA"
        assert info.is_power_of_two is True

    def test_info_non_pot(self, tmp_path, img_300):
        path = tmp_path / "nonpot.png"
        pillow_ops.save(img_300, path)
        info = pillow_ops.info(path)
        assert info.is_power_of_two is False

    def test_resize_contain(self, img_300):
        result = pillow_ops.resize(img_300, 400, 400, fit="contain")
        assert result.size == (400, 400)

    def test_resize_cover(self, img_300):
        result = pillow_ops.resize(img_300, 200, 200, fit="cover")
        assert result.size == (200, 200)

    def test_resize_stretch(self, img_300):
        result = pillow_ops.resize(img_300, 100, 100, fit="stretch")
        assert result.size == (100, 100)

    def test_resize_pot(self, img_300):
        """fill_power_of_two arrondit aux puissances de 2."""
        result = pillow_ops.resize(img_300, 300, 200, fit="fill_power_of_two")
        w, h = result.size
        assert (w & (w - 1)) == 0  # power of 2
        assert (h & (h - 1)) == 0

    def test_crop(self, img_512):
        cropped = pillow_ops.crop(img_512, 10, 20, 100, 150)
        assert cropped.size == (90, 130)

    def test_ensure_power_of_two(self, img_300):
        pot = pillow_ops.ensure_power_of_two(img_300)
        w, h = pot.size
        assert (w & (w - 1)) == 0
        assert (h & (h - 1)) == 0
        assert w >= 300
        assert h >= 200

    def test_convert_format(self, png_file, tmp_path):
        jpg = tmp_path / "converted.jpg"
        pillow_ops.convert_format(png_file, jpg, target_format="JPEG")
        assert jpg.exists()
        info = pillow_ops.info(jpg)
        assert info.format == "JPEG"


class TestSpriteSheet:
    """Sprite sheet : assemble et découpe."""

    def test_make_sprite_sheet(self):
        from PIL import Image
        frames = [Image.new("RGBA", (64, 64), (i * 30, 100, 200, 255))
                  for i in range(9)]
        sheet, meta = pillow_ops.make_sprite_sheet(frames, columns=3)
        assert sheet.size[0] == 3 * 64
        assert sheet.size[1] == 3 * 64
        assert len(meta) == 9

    def test_make_sprite_sheet_auto_columns(self):
        from PIL import Image
        frames = [Image.new("RGBA", (32, 32), (0, 0, 0, 255)) for _ in range(16)]
        sheet, meta = pillow_ops.make_sprite_sheet(frames)
        # Auto = sqrt(16) = 4 columns
        assert len(meta) == 16

    def test_split_sprite_sheet(self):
        from PIL import Image
        frames = [Image.new("RGBA", (64, 64), (i * 50, 0, 0, 255))
                  for i in range(4)]
        sheet, meta = pillow_ops.make_sprite_sheet(frames, columns=2)
        split = pillow_ops.split_sprite_sheet(sheet, meta)
        assert len(split) == 4

    def test_sprite_sheet_vide_leve(self):
        with pytest.raises(ValueError, match="Au moins une frame"):
            pillow_ops.make_sprite_sheet([])

    def test_sprite_sheet_avec_padding(self):
        from PIL import Image
        frames = [Image.new("RGBA", (32, 32)) for _ in range(4)]
        sheet, meta = pillow_ops.make_sprite_sheet(frames, columns=2, padding=4)
        assert sheet.size[0] == 2 * 32 + 4  # 2 cols + 1 padding
        assert sheet.size[1] == 2 * 32 + 4


class TestImageInfo:
    """Les métadonnées sont correctes."""

    def test_aspect_ratio(self, tmp_path, img_300):
        path = tmp_path / "ratio.png"
        pillow_ops.save(img_300, path)
        info = pillow_ops.info(path)
        assert abs(info.aspect_ratio - 1.5) < 0.01  # 300/200

    def test_power_of_two_512(self, img_512, tmp_path):
        path = tmp_path / "pot.png"
        pillow_ops.save(img_512, path)
        assert pillow_ops.info(path).is_power_of_two is True

    def test_power_of_two_300(self, tmp_path, img_300):
        path = tmp_path / "nonpot.png"
        pillow_ops.save(img_300, path)
        assert pillow_ops.info(path).is_power_of_two is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. STUBS — ComfyUI, Blender, Aseprite lèvent proprement
# ═══════════════════════════════════════════════════════════════════════════


class TestComfyUIStub:
    def test_available_false(self):
        assert comfyui_ops.available() is False

    def test_generate_leve(self):
        with pytest.raises(RuntimeError, match="ComfyUI non accessible"):
            comfyui_ops.generate("test")


class TestBlenderStub:
    def test_available_false(self):
        assert blender_ops.available() is False

    def test_convert_leve(self):
        with pytest.raises(RuntimeError, match="Blender introuvable"):
            blender_ops.convert_model("in.fbx", "out.obj")

    def test_render_leve(self):
        with pytest.raises(RuntimeError, match="Blender introuvable"):
            blender_ops.render_model("mesh.fbx")


class TestAsepriteStub:
    def test_available_false(self):
        assert aseprite_ops.available() is False

    def test_export_leve(self):
        with pytest.raises(RuntimeError, match="Aseprite CLI introuvable"):
            aseprite_ops.export_sprite_sheet("test.ase")

    def test_palette_from_image_sans_aseprite(self, tmp_path):
        """palette_from_image utilise Pillow, pas Aseprite — fonctionne toujours."""
        from PIL import Image
        # Image avec plusieurs couleurs distinctes
        img = Image.new("RGB", (64, 64), (255, 0, 0))
        for x in range(32):
            for y in range(64):
                img.putpixel((x, y), (0, 0, 255))
        path = tmp_path / "multi.png"
        img.save(str(path))
        palette = aseprite_ops.palette_from_image(path, max_colors=4)
        assert len(palette) >= 2  # au moins rouge et bleu
        assert all(isinstance(c, tuple) and len(c) == 3 for c in palette)


# ═══════════════════════════════════════════════════════════════════════════
# 4. INSTANCES PUBLIQUES
# ═══════════════════════════════════════════════════════════════════════════


class TestInstances:
    def test_pillow_ops_instance(self):
        assert isinstance(pillow_ops, PillowOps)

    def test_comfyui_ops_instance(self):
        assert isinstance(comfyui_ops, ComfyUIOps)

    def test_blender_ops_instance(self):
        assert isinstance(blender_ops, BlenderOps)

    def test_aseprite_ops_instance(self):
        assert isinstance(aseprite_ops, AsepriteOps)
