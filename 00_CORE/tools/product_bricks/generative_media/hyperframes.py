"""
hyperframes.py — Wrapper HyperFrames (heygen-com/hyperframes)
==============================================================
HTML → MP4 déterministe. Headless Chrome + FFmpeg.
Built for agents : plain HTML, aucun build step, frame-accurate.

Cas d'usage Forge :
  - Snap Ads 9:16 à partir des photos/vidéos des chambres d'hôtel
  - Vidéos explicatives du fonctionnement du service (flash sale, rotation)
  - Motion graphics réutilisables pour funnel Snapchat → TG/WA

vs open_gen_ai.py :
  OpenGenAI  → génère du contenu de zéro par IA (pas de contrôle sur la structure)
  HyperFrames → compose TES assets (photos, vidéos, texte) en MP4 structuré et brandé

Prérequis : Node.js >=22, FFmpeg
Install   : npx hyperframes init <project>  (zéro install global nécessaire)

Usage :
    from tools.product_bricks.generative_media import hyperframes
    proj = hyperframes.init("videos/snap_hotel_room1")
    hyperframes.add_media(proj, "path/to/room.mp4", "path/to/logo.png")
    hyperframes.write_composition(proj, hyperframes.snap_ad_hotel(
        headline="Flash Sale — -50% cette nuit",
        subline="Disponible ce soir uniquement • 1-2 nuits",
        cta="Réserver sur Telegram",
        media_file="room.mp4",
    ))
    hyperframes.preview(proj)   # browser live reload
    out = hyperframes.render(proj)  # → videos/snap_hotel_room1/output.mp4
"""

from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path


def _npx(args: list[str], cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["npx", *args], cwd=str(cwd) if cwd else None, check=check)


def init(project_dir: str | Path) -> Path:
    """
    Initialise un projet HyperFrames.
    Crée project_dir/index.html + structure de base.
    """
    d = Path(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    _npx(["hyperframes", "init", d.name], cwd=d.parent)
    print(f"hyperframes: init → {d}")
    return d


def add_media(project_dir: str | Path, *media_paths: str | Path) -> None:
    """
    Copie des assets media (mp4, jpg, png, wav) dans le projet.
    Les chemins dans index.html doivent matcher le nom de fichier.
    """
    d = Path(project_dir)
    for src in media_paths:
        src = Path(src)
        dst = d / src.name
        shutil.copy2(src, dst)
        print(f"hyperframes: media → {dst.name}")


def add_catalog_block(project_dir: str | Path, block: str) -> None:
    """
    Installe un bloc depuis le catalogue HyperFrames.
    Ex: 'flash-through-white', 'instagram-follow', 'data-chart'
    """
    _npx(["hyperframes", "add", block], cwd=project_dir)
    print(f"hyperframes: block '{block}' ajouté")


def write_composition(project_dir: str | Path, html: str) -> Path:
    """Écrit index.html dans le projet."""
    p = Path(project_dir) / "index.html"
    p.write_text(html, encoding="utf-8")
    print(f"hyperframes: composition écrite → {p}")
    return p


def preview(project_dir: str | Path) -> None:
    """Lance le preview browser avec live reload (bloquant)."""
    _npx(["hyperframes", "preview"], cwd=project_dir)


def render(project_dir: str | Path, output: str = "output.mp4") -> Path:
    """Rend le projet en MP4. Retourne le chemin du fichier."""
    _npx(["hyperframes", "render", "--output", output], cwd=project_dir)
    out = Path(project_dir) / output
    print(f"hyperframes: rendu → {out}")
    return out


# ── Templates métier ──────────────────────────────────────────────────────────

def snap_ad_hotel(
    headline: str,
    subline: str,
    cta: str,
    media_file: str,
    duration: int = 12,
    accent_color: str = "#FFD700",
) -> str:
    """
    Génère un index.html pour une Snap Ad 9:16 (1080x1920).
    Composition : vidéo/photo chambre plein écran + overlay texte + CTA.

    ponytail: template minimal HTML/CSS, pas de framework. Headless Chrome suffit.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: 1080px; height: 1920px; overflow: hidden; background: #000; font-family: 'Helvetica Neue', Arial, sans-serif; }}

  #bg {{ position: absolute; inset: 0; object-fit: cover; width: 100%; height: 100%; }}

  #overlay {{
    position: absolute; inset: 0;
    background: linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.1) 50%, transparent 100%);
  }}

  #content {{
    position: absolute; bottom: 180px; left: 60px; right: 60px; color: #fff;
  }}

  #headline {{
    font-size: 80px; font-weight: 900; line-height: 1.05;
    text-shadow: 0 4px 20px rgba(0,0,0,0.6);
    margin-bottom: 24px;
  }}

  #headline span {{ color: {accent_color}; }}

  #subline {{
    font-size: 40px; font-weight: 400; opacity: 0.9;
    margin-bottom: 48px; line-height: 1.3;
  }}

  #cta {{
    display: inline-block;
    background: {accent_color}; color: #000;
    font-size: 44px; font-weight: 800;
    padding: 28px 64px; border-radius: 60px;
    letter-spacing: -0.5px;
  }}

  #badge {{
    position: absolute; top: 80px; right: 60px;
    background: {accent_color}; color: #000;
    font-size: 48px; font-weight: 900;
    width: 180px; height: 180px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    text-align: center; line-height: 1.1;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  }}
</style>
</head>
<body>
<div id="stage" data-composition-id="snap-hotel" data-start="0" data-width="1080" data-height="1920">

  <!-- Media chambre plein écran -->
  <video class="clip" id="bg" data-start="0" data-duration="{duration}" data-track-index="0"
    src="{media_file}" muted playsinline autoplay loop></video>

  <!-- Gradient overlay -->
  <div class="clip" id="overlay" data-start="0" data-duration="{duration}" data-track-index="1"></div>

  <!-- Badge -50% -->
  <div class="clip" id="badge" data-start="0.5" data-duration="{duration - 0.5}" data-track-index="2">
    -50%<br>ce soir
  </div>

  <!-- Texte principal -->
  <div class="clip" id="content" data-start="0.8" data-duration="{duration - 0.8}" data-track-index="3">
    <div id="headline">{headline.replace('-50%', '<span>-50%</span>')}</div>
    <div id="subline">{subline}</div>
    <div id="cta">{cta} →</div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.from("#badge",   {{ scale: 0, duration: 0.5, ease: "back.out(1.7)" }}, 0.5);
    tl.from("#content", {{ y: 60, opacity: 0, duration: 0.6, ease: "power3.out" }}, 0.8);
    window.__timelines = window.__timelines || {{}};
    window.__timelines["snap-hotel"] = tl;
  </script>
</div>
</body>
</html>"""


def explainer_service(
    title: str = "Comment ça marche ?",
    steps: list[str] | None = None,
    duration: int = 20,
) -> str:
    """
    Template vidéo explicative du service (fonctionnement flash sale + rotation).
    Format 16:9 (1920x1080) pour usage Web / TG.
    """
    steps = steps or [
        "1. Flash sales & annulations hôtelières → jusqu'à -50%",
        "2. Disponible 24h/24 dans le monde entier",
        "3. Séjours courts uniquement (1-2 nuits)",
        "4. Paiement : virement SG, cash ou crypto",
    ]
    steps_html = "\n".join(
        f'<div class="clip step" data-start="{2 + i * 4}" data-duration="{duration}" data-track-index="{i + 2}">{s}</div>'
        for i, s in enumerate(steps)
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: 1920px; height: 1080px; overflow: hidden; background: #0a0a0a; font-family: 'Helvetica Neue', Arial, sans-serif; color: #fff; }}
  #title {{ position: absolute; top: 120px; left: 100px; font-size: 96px; font-weight: 900; }}
  .step {{ position: absolute; left: 100px; right: 100px;
    font-size: 56px; font-weight: 500; padding: 32px 40px;
    border-left: 8px solid #FFD700; background: rgba(255,215,0,0.08);
    border-radius: 0 16px 16px 0; }}
  .step:nth-child(1) {{ top: 300px; }}
  .step:nth-child(2) {{ top: 460px; }}
  .step:nth-child(3) {{ top: 620px; }}
  .step:nth-child(4) {{ top: 780px; }}
</style>
</head>
<body>
<div id="stage" data-composition-id="explainer" data-start="0" data-width="1920" data-height="1080">
  <div class="clip" id="title" data-start="0" data-duration="{duration}" data-track-index="0">{title}</div>
  {steps_html}
  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.from("#title", {{ x: -80, opacity: 0, duration: 0.6 }}, 0);
    document.querySelectorAll(".step").forEach((el, i) => {{
      tl.from(el, {{ x: -60, opacity: 0, duration: 0.5 }}, 2 + i * 4);
    }});
    window.__timelines = {{ explainer: tl }};
  </script>
</div>
</body>
</html>"""


if __name__ == "__main__":
    print("hyperframes: vérification des prérequis")
    node_ok = shutil.which("node") is not None
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    print(f"  node   : {'✓' if node_ok else '✗ requis (>=22)'}")
    print(f"  ffmpeg : {'✓' if ffmpeg_ok else '✗ requis'}")
    print("Install: winget install FFmpeg.FFmpeg + node >=22")
    print("CLI    : npx hyperframes init my-video")
    print("Skills : npx skills add heygen-com/hyperframes")
