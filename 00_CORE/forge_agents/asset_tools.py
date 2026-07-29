"""
asset_tools.py — Wrappers outils pour le pipeline d'assets (ticket E3-03)
=========================================================================
Quatre outils, un même contrat : `available()` → opération.

1. **Pillow** — opérations image de base (toujours disponible). Redimensionner,
   rogner, convertir le format, extraire des métadonnées, composer des
   sprite sheets.
2. **ComfyUI/SDXL** — génération d'images par diffusion stable. Stub : le
   service n'est pas lancé ici. L'API attend un serveur ComfyUI ou
   `diffusers` local.
3. **Blender** — opérations 3D headless. Stub : Blender n'est pas installé.
   L'API couvre : import/export de modèles, rendu, conversion de format.
4. **Aseprite** — opérations sprite. Stub : Aseprite n'est pas installé.
   L'API couvre : sprite sheets, palettes, animations.

POURQUOI CE MODULE
------------------
E3-04 (pipeline complet) importera d'ici pour chaque étape :
  concept art → Pillow resize/crop
  sprite → Aseprite sprite_sheet / Pillow compose
  texture → Pillow convert/resize
  modèle 3D → Blender convert/render
  rig/anim → Blender import/export
  VFX → hors scope (shader = texte)

USAGE
-----
    from forge_agents.asset_tools import pillow_ops, blender_ops, comfyui_ops, aseprite_ops

    # Pillow (toujours dispo)
    img = pillow_ops.load("concept.png")
    resized = pillow_ops.resize(img, 1024, 1024)
    pillow_ops.save(resized, "concept_1024.png")

    # Blender (si installé)
    if blender_ops.available():
        blender_ops.render_model("mesh.fbx", "render.png", resolution=(1920, 1080))
"""

from __future__ import annotations

import io
import json
import logging
import math
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# PILLOW — opérations image de base (toujours disponible)
# ═══════════════════════════════════════════════════════════════════════════


def pillow_available() -> bool:
    """Pillow est-il installé ?"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class ImageInfo:
    """Métadonnées d'une image."""
    width: int
    height: int
    format: str
    mode: str  # RGB, RGBA, L, etc.
    file_size: int  # bytes

    @property
    def is_power_of_two(self) -> bool:
        return (self.width & (self.width - 1)) == 0 and (self.height & (self.height - 1)) == 0

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 0


class PillowOps:
    """Opérations image via Pillow. Chaque méthode retourne un PIL.Image ou un Path."""

    def load(self, path: str | Path):
        """Charge une image."""
        from PIL import Image
        return Image.open(path)

    def save(self, image, path: str | Path, format: str = None, quality: int = 95):
        """Sauvegarde une image."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if format:
            kwargs["format"] = format
        if format in ("JPEG", "jpg", None) and str(out).lower().endswith((".jpg", ".jpeg")):
            kwargs["quality"] = quality
        image.save(str(out), **kwargs)
        return out

    def info(self, path: str | Path) -> ImageInfo:
        """Extrait les métadonnées d'une image."""
        from PIL import Image
        p = Path(path)
        with Image.open(p) as img:
            return ImageInfo(
                width=img.width,
                height=img.height,
                format=img.format or p.suffix.lstrip(".").upper(),
                mode=img.mode,
                file_size=p.stat().st_size,
            )

    def resize(self, image, width: int, height: int,
               fit: str = "contain", background=(0, 0, 0, 0)):
        """Redimensionne une image.

        fit:
          - "contain" : maintient le ratio, ajoute un fond (letterbox)
          - "cover" : maintient le ratio, rogne les bords
          - "stretch" : étire sans maintenir le ratio
          - "fill_power_of_two" : arrondit aux puissances de 2 supérieures
        """
        from PIL import Image

        if fit == "stretch":
            return image.resize((width, height), Image.LANCZOS)

        if fit == "fill_power_of_two":
            w = 2 ** math.ceil(math.log2(max(width, 2)))
            h = 2 ** math.ceil(math.log2(max(height, 2)))
            return self.resize(image, w, h, fit="contain", background=background)

        if fit == "cover":
            ratio = max(width / image.width, height / image.height)
            new_w = int(image.width * ratio)
            new_h = int(image.height * ratio)
            resized = image.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - width) // 2
            top = (new_h - height) // 2
            return resized.crop((left, top, left + width, top + height))

        # "contain" (défaut)
        ratio = min(width / image.width, height / image.height)
        new_w = int(image.width * ratio)
        new_h = int(image.height * ratio)
        resized = image.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGBA", (width, height), background)
        offset = ((width - new_w) // 2, (height - new_h) // 2)
        canvas.paste(resized, offset)
        return canvas

    def crop(self, image, left: int, top: int, right: int, bottom: int):
        """Rogne une image."""
        return image.crop((left, top, right, bottom))

    def convert_format(self, input: str | Path, output: str | Path,
                       target_format: str = "PNG", **kwargs):
        """Convertit un fichier image vers un autre format."""
        img = self.load(input)
        # Assurer la bonne mode pour le format
        if target_format.upper() in ("JPEG", "JPG") and img.mode == "RGBA":
            img = img.convert("RGB")
        if target_format.upper() == "PNG" and img.mode not in ("RGBA", "RGB", "L", "P"):
            img = img.convert("RGBA")
        return self.save(img, output, format=target_format, **kwargs)

    def ensure_power_of_two(self, image, background=(0, 0, 0, 0)):
        """Redimensionne aux puissances de 2 supérieures (GPU-friendly)."""
        w = 2 ** math.ceil(math.log2(max(image.width, 2)))
        h = 2 ** math.ceil(math.log2(max(image.height, 2)))
        if w == image.width and h == image.height:
            return image
        return self.resize(image, w, h, fit="contain", background=background)

    def make_sprite_sheet(self, frames: list, columns: int = None,
                          padding: int = 0, background=(0, 0, 0, 0)):
        """Assemble des frames en une sprite sheet.

        Args:
            frames: Liste de PIL.Image (même taille recommandée).
            columns: Nombre de colonnes (défaut: racine carrée du nombre de frames).
            padding: Espacement entre les frames (pixels).
            background: Couleur de fond.

        Returns:
            (sheet_image, metadata) où metadata = liste de (x, y, w, h) par frame.
        """
        from PIL import Image

        if not frames:
            raise ValueError("Au moins une frame requise")

        if columns is None:
            columns = math.ceil(math.sqrt(len(frames)))

        fw = max(f.width for f in frames)
        fh = max(f.height for f in frames)
        rows = math.ceil(len(frames) / columns)

        sheet_w = columns * fw + (columns - 1) * padding
        sheet_h = rows * fh + (rows - 1) * padding
        sheet = Image.new("RGBA", (sheet_w, sheet_h), background)

        metadata = []
        for i, frame in enumerate(frames):
            col = i % columns
            row = i // columns
            x = col * (fw + padding)
            y = row * (fh + padding)
            # Centrer la frame dans sa cellule si elle est plus petite
            ox = x + (fw - frame.width) // 2
            oy = y + (fh - frame.height) // 2
            sheet.paste(frame, (ox, oy))
            metadata.append({"x": x, "y": y, "w": fw, "h": fh, "frame": i})

        return sheet, metadata

    def split_sprite_sheet(self, image, metadata: list[dict]) -> list:
        """Découpe une sprite sheet selon les métadonnées."""
        frames = []
        for m in metadata:
            frame = image.crop((m["x"], m["y"],
                                m["x"] + m["w"], m["y"] + m["h"]))
            frames.append(frame)
        return frames


#: Instance publique.
pillow_ops = PillowOps()


# ═══════════════════════════════════════════════════════════════════════════
# COMFYUI/SDXL — génération d'images par diffusion stable
# ═══════════════════════════════════════════════════════════════════════════


def comfyui_available() -> bool:
    """Un serveur ComfyUI est-il accessible ?"""
    import urllib.request
    host = _comfyui_host()
    try:
        urllib.request.urlopen(f"{host}/system_stats", timeout=2)
        return True
    except Exception:
        return False


def _comfyui_host() -> str:
    import os
    return os.environ.get("COMFYUI_HOST", "http://127.0.0.1:8188")


class ComfyUIOps:
    """Génération d'images via ComfyUI (API REST)."""

    def available(self) -> bool:
        return comfyui_available()

    def generate(self, prompt: str, output: str | Path = None,
                 negative_prompt: str = "",
                 width: int = 1024, height: int = 1024,
                 steps: int = 20, cfg: float = 7.0,
                 seed: int = -1, model: str = "sd_xl_base_1.0.safetensors") -> Path:
        """Génère une image à partir d'un prompt textuel.

        Nécessite un serveur ComfyUI lancé (docker ou local).
        Le workflow par défaut utilise SDXL.
        """
        if not self.available():
            raise RuntimeError(
                f"ComfyUI non accessible sur {_comfyui_host()}.\n"
                "Lancer avec : docker run -p 8188:8188 comfyui/comfyui\n"
                "Ou : python main.py --listen 0.0.0.0 (depuis le repo ComfyUI)"
            )

        import urllib.request

        # Workflow SDXL basique
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed if seed >= 0 else 42,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative_prompt, "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "forge", "images": ["8", 0]},
            },
        }

        host = _comfyui_host()
        data = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(
            f"{host}/prompt",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        prompt_id = result.get("prompt_id", "")

        logger.info("ComfyUI: prompt_id=%s (%s)", prompt_id, prompt[:60])

        # Poller le résultat (simplifié — en prod utiliserait websocket)
        import time
        for _ in range(120):  # max 2 min
            time.sleep(1)
            try:
                hist_resp = urllib.request.urlopen(f"{host}/history/{prompt_id}", timeout=5)
                hist = json.loads(hist_resp.read())
                if prompt_id in hist:
                    outputs = hist[prompt_id].get("outputs", {})
                    for node_id, node_out in outputs.items():
                        if "images" in node_out:
                            img_info = node_out["images"][0]
                            # Télécharger l'image
                            img_url = f"{host}/view?filename={img_info['filename']}&subfolder={img_info.get('subfolder', '')}&type={img_info.get('type', 'output')}"
                            out = Path(output) if output else Path(tempfile.mktemp(suffix=".png"))
                            urllib.request.urlretrieve(img_url, str(out))
                            return out
            except Exception:
                continue

        raise TimeoutError(f"ComfyUI n'a pas produit d'image en 120s (prompt_id={prompt_id})")


#: Instance publique.
comfyui_ops = ComfyUIOps()


# ═══════════════════════════════════════════════════════════════════════════
# BLENDER — opérations 3D headless
# ═══════════════════════════════════════════════════════════════════════════


def blender_available() -> bool:
    """Blender est-il dans le PATH ?"""
    return shutil.which("blender") is not None


def _blender_cmd() -> str:
    cmd = shutil.which("blender")
    if not cmd:
        raise RuntimeError(
            "Blender introuvable dans le PATH.\n"
            "Installer : https://www.blender.org/download/\n"
            "Ou via Chocolatey : choco install blender\n"
            "Ou via winget : winget install BlenderFoundation.Blender"
        )
    return cmd


def _run_blender(script: str, args: list[str] = None,
                 timeout: int = 300) -> subprocess.CompletedProcess:
    """Exécute un script Python dans Blender headless."""
    cmd = _blender_cmd()
    full_args = [cmd, "--background", "--python-expr", script]
    if args:
        full_args += args
    logger.debug("blender: %s", " ".join(full_args[:5]))
    return subprocess.run(full_args, capture_output=True, text=True, timeout=timeout)


class BlenderOps:
    """Opérations 3D via Blender headless."""

    def available(self) -> bool:
        return blender_available()

    def convert_model(self, input: str | Path, output: str | Path,
                      target_format: str = None) -> Path:
        """Convertit un modèle 3D vers un autre format.

        Formats supportés : FBX, OBJ, glTF/GLB, STL, PLY, DAE, BLEND.
        Le format cible est déduit de l'extension si non spécifié.
        """
        out = Path(output)
        if target_format is None:
            target_format = out.suffix.lstrip(".")

        script = f'''
import bpy
import sys

# Nettoyer la scène
bpy.ops.wm.read_factory_settings(use_empty=True)

# Importer
input_path = r"{str(input)}"
ext = input_path.rsplit(".", 1)[-1].lower()
if ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=input_path)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=input_path)
elif ext in ("gltf", "glb"):
    bpy.ops.import_scene.gltf(filepath=input_path)
elif ext == "stl":
    bpy.ops.wm.stl_import(filepath=input_path)
elif ext == "blend":
    bpy.ops.wm.open_mainfile(filepath=input_path)
elif ext == "dae":
    bpy.ops.wm.collada_import(filepath=input_path)
else:
    print(f"Format d'import non supporté: {{ext}}")
    sys.exit(1)

# Exporter
output_path = r"{str(out)}"
fmt = "{target_format}".lower()
if fmt == "fbx":
    bpy.ops.export_scene.fbx(filepath=output_path)
elif fmt == "obj":
    bpy.ops.wm.obj_export(filepath=output_path)
elif fmt in ("gltf", "glb"):
    bpy.ops.export_scene.gltf(filepath=output_path)
elif fmt == "stl":
    bpy.ops.wm.stl_export(filepath=output_path)
else:
    print(f"Format d'export non supporté: {{fmt}}")
    sys.exit(1)

print(f"Converti: {{input_path}} → {{output_path}}")
'''
        result = _run_blender(script)
        if result.returncode != 0:
            raise RuntimeError(f"Blender convert a échoué : {result.stderr.strip()}")
        return out

    def render_model(self, input: str | Path, output: str | Path = None,
                     resolution: tuple[int, int] = (1920, 1080),
                     engine: str = "BLENDER_EEVEE") -> Path:
        """Rendu d'une image depuis un modèle 3D."""
        out = Path(output) if output else Path(tempfile.mktemp(suffix=".png"))

        script = f'''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)

# Importer le modèle
input_path = r"{str(input)}"
ext = input_path.rsplit(".", 1)[-1].lower()
if ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=input_path)
elif ext in ("gltf", "glb"):
    bpy.ops.import_scene.gltf(filepath=input_path)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=input_path)
elif ext == "blend":
    bpy.ops.wm.open_mainfile(filepath=input_path)

# Configurer le rendu
bpy.context.scene.render.engine = "{engine}"
bpy.context.scene.render.resolution_x = {resolution[0]}
bpy.context.scene.render.resolution_y = {resolution[1]}
bpy.context.scene.render.filepath = r"{str(out)}"
bpy.ops.render.render(write_still=True)
print(f"Rendu: {{r'{str(out)}'}}")
'''
        result = _run_blender(script)
        if result.returncode != 0:
            raise RuntimeError(f"Blender render a échoué : {result.stderr.strip()}")
        return out

    def model_info(self, input: str | Path) -> dict:
        """Extrait les métadonnées d'un modèle 3D."""
        script = f'''
import bpy, json
bpy.ops.wm.read_factory_settings(use_empty=True)
input_path = r"{str(input)}"
ext = input_path.rsplit(".", 1)[-1].lower()
if ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=input_path)
elif ext in ("gltf", "glb"):
    bpy.ops.import_scene.gltf(filepath=input_path)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=input_path)
elif ext == "blend":
    bpy.ops.wm.open_mainfile(filepath=input_path)

meshes = [o for o in bpy.data.objects if o.type == 'MESH']
total_verts = sum(len(m.data.vertices) for m in meshes)
total_faces = sum(len(m.data.polygons) for m in meshes)
total_mats = len(bpy.data.materials)
info = {{
    "objects": len(meshes),
    "vertices": total_verts,
    "faces": total_faces,
    "materials": total_mats,
    "has_armature": any(o.type == 'ARMATURE' for o in bpy.data.objects),
    "has_animation": len(bpy.data.actions) > 0,
}}
print("__JSON__" + json.dumps(info))
'''
        result = _run_blender(script)
        if result.returncode != 0:
            raise RuntimeError(f"Blender info a échoué : {result.stderr.strip()}")
        # Extraire le JSON
        for line in result.stdout.splitlines():
            if line.startswith("__JSON__"):
                return json.loads(line[8:])
        return {"error": "pas de métadonnées extraites"}


#: Instance publique.
blender_ops = BlenderOps()


# ═══════════════════════════════════════════════════════════════════════════
# ASEPRITE — opérations sprite
# ═══════════════════════════════════════════════════════════════════════════


def aseprite_available() -> bool:
    """Aseprite CLI est-il dans le PATH ?"""
    return shutil.which("aseprite") is not None


def _aseprite_cmd() -> str:
    cmd = shutil.which("aseprite")
    if not cmd:
        raise RuntimeError(
            "Aseprite CLI introuvable dans le PATH.\n"
            "Installer : https://www.aseprite.org/download/\n"
            "Aseprite doit être en mode CLI (pas le GUI).\n"
            "Ou via Steam : Aseprite → Properties → Launch Options → --batch"
        )
    return cmd


class AsepriteOps:
    """Opérations sprite via Aseprite CLI."""

    def available(self) -> bool:
        return aseprite_available()

    def export_sprite_sheet(self, input: str | Path, output: str | Path = None,
                            columns: int = 0, width: int = 0,
                            height: int = 0) -> Path:
        """Exporte un fichier .ase/.aseprite en sprite sheet PNG."""
        out = Path(output) if output else Path(
            Path(input).stem + "_sheet.png")
        cmd = [_aseprite_cmd(), "-b", str(input),
               "--sheet", str(out),
               "--sheet-type", "horizontal" if columns == 1 else "packed"]
        if columns > 1:
            cmd += ["--sheet-columns", str(columns)]
        if width > 0:
            cmd += ["--sheet-width", str(width)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Aseprite export a échoué : {result.stderr.strip()}")
        return out

    def export_frames(self, input: str | Path, output_dir: str | Path = None,
                      prefix: str = "frame") -> list[Path]:
        """Exporte chaque frame en PNG individuel."""
        out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp())
        out_dir.mkdir(parents=True, exist_ok=True)
        pattern = str(out_dir / f"{prefix}_{{frame0000}}.png")
        cmd = [_aseprite_cmd(), "-b", str(input),
               "--save-as", pattern]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Aseprite frames a échoué : {result.stderr.strip()}")
        return sorted(out_dir.glob(f"{prefix}_*.png"))

    def convert_format(self, input: str | Path, output: str | Path) -> Path:
        """Convertit un fichier .ase en PNG, GIF, ou autre format."""
        cmd = [_aseprite_cmd(), "-b", str(input), "--save-as", str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Aseprite convert a échoué : {result.stderr.strip()}")
        return Path(output)

    def palette_from_image(self, image_path: str | Path,
                           max_colors: int = 16) -> list[tuple[int, int, int]]:
        """Extrait une palette de couleurs dominantes (via Pillow, pas Aseprite)."""
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        # Quantization pour extraire les couleurs dominantes
        quantized = img.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        colors = []
        for i in range(max_colors):
            idx = i * 3
            if idx + 2 < len(palette):
                colors.append((palette[idx], palette[idx + 1], palette[idx + 2]))
        return colors


#: Instance publique.
aseprite_ops = AsepriteOps()


# ═══════════════════════════════════════════════════════════════════════════
# SELF-CHECK
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    print("=== asset_tools self-check ===")
    print(f"Pillow:     {'✅' if pillow_available() else '❌'}")
    print(f"ComfyUI:    {'✅' if comfyui_available() else '❌ (serveur non lancé)'}")
    print(f"Blender:    {'✅' if blender_available() else '❌ (non installé)'}")
    print(f"Aseprite:   {'✅' if aseprite_available() else '❌ (non installé)'}")

    if pillow_available():
        print(f"\nPillow ops: {', '.join(m for m in dir(pillow_ops) if not m.startswith('_'))}")
        # Test rapide
        from PIL import Image
        img = Image.new("RGBA", (512, 512), (100, 150, 200, 255))
        resized = pillow_ops.resize(img, 256, 256)
        print(f"Resize 512→256: {resized.size}")
        pot = pillow_ops.ensure_power_of_two(img)
        print(f"Power-of-two: {pot.size}")
