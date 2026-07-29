"""
forge_pxpipe.py — Proxy Visuel de Contexte (Pxpipe)
====================================================
Convertit les gros prompts système en images PNG compactes.
Le modèle lit l'image via son canal Vision au lieu de recevoir
des dizaines de milliers de tokens de texte brut.

Économie théorique : 60-75% sur les prompts > seuil.
Coût fixe image : ~1600 tokens (quel que soit le contenu).

Inspiré de teamchong/pxpipe.

Usage:
    from forge_agents.forge_pxpipe import pxpipe_compress, should_compress, inject_visual_context

    # Dans forge_call(), avant l'envoi au LLM :
    if should_compress(system):
        system = inject_visual_context(system)
"""

from __future__ import annotations
import base64
import io
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ForgePxPipe")

# ── Config ───────────────────────────────────────────────────────────────────

# Seuil de tokens approximatif pour déclencher la compression visuelle
# En dessous, le texte est envoyé normalement (pas d'intérêt à compresser)
COMPRESS_THRESHOLD_TOKENS = 4000

# Tokens estimés pour une image (coût fixe Anthropic/OpenAI vision)
IMAGE_TOKEN_COST = 1600

# Dossier cache pour les PNG générés (évite de re-rendre le même texte)
CACHE_DIR = Path(__file__).parent.parent.parent / "04_GRAPHIFY" / "pxpipe_cache"

# Police et taille
FONT_SIZE = 13
LINE_HEIGHT = 18
MARGIN = 24
MAX_WIDTH_CHARS = 95  # largeur max en caractères avant wrap
BG_COLOR = (15, 15, 20)       # fond sombre (Forge design)
TEXT_COLOR = (220, 220, 230)   # texte clair
KEYWORD_COLOR = (100, 180, 255)  # bleu pour les mots-clés techniques
HEADER_COLOR = (247, 167, 17)    # orange pour les headers (HELB brand)

# Mots-clés à colorer (mémoire visuelle améliorée)
_KEYWORDS = frozenset([
    "import", "from", "class", "def", "return", "if", "else", "elif",
    "for", "while", "try", "except", "raise", "with", "as", "async",
    "await", "yield", "lambda", "None", "True", "False", "self",
    "function", "const", "let", "var", "export", "module",
    "ERROR", "WARNING", "CRITICAL", "TODO", "FIXME", "HACK",
])


# ── Token estimation (rapide, pas de tokenizer) ─────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Estimation rapide : ~4 chars/token (heuristique anglaise/française)."""
    return len(text) // 4


# ── Text rendering ──────────────────────────────────────────────────────────

def _word_wrap(text: str, max_width: int = MAX_WIDTH_CHARS) -> list[str]:
    """Word-wrap intelligent avec support des lignes longues et code blocks."""
    lines = []
    for line in text.split('\n'):
        if len(line) <= max_width:
            lines.append(line)
            continue
        # Wrap
        words = line.split(' ')
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= max_width:
                current = f"{current} {word}" if current else word
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def _get_font(size: int = FONT_SIZE):
    """Charge une police monospace. Fallback sur police par défaut Pillow."""
    try:
        from PIL import ImageFont
        # Essayer les polices courantes sur Windows
        for name in ["consola.ttf", "cour.ttf", "lucon.ttf", "DejaVuSansMono.ttf"]:
            try:
                return ImageFont.truetype(name, size)
            except (OSError, IOError):
                continue
        # Fallback: chercher dans les chemins Windows
        fonts_dir = Path("C:/Windows/Fonts")
        for name in ["consola.ttf", "cour.ttf", "lucon.ttf"]:
            try:
                return ImageFont.truetype(str(fonts_dir / name), size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()
    except Exception:
        return None


def _highlight_line(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """
    Retourne des segments (texte, couleur) pour une ligne.
    Coloration basique des mots-clés techniques.
    """
    if not line.strip():
        return [("", TEXT_COLOR)]

    # Headers markdown
    if line.strip().startswith('#'):
        return [(line, HEADER_COLOR)]

    # Commentaires
    stripped = line.strip()
    if stripped.startswith('//') or stripped.startswith('# ') or stripped.startswith('/*'):
        return [(line, (120, 120, 140))]

    # Séparateurs
    if stripped.startswith('---') or stripped.startswith('===') or stripped.startswith('```'):
        return [(line, (80, 80, 100))]

    # Coloration par mots-clés
    segments = []
    parts = re.split(r'(\b\w+\b)', line)
    for part in parts:
        if part in _KEYWORDS:
            segments.append((part, KEYWORD_COLOR))
        else:
            segments.append((part, TEXT_COLOR))
    return segments


def render_text_to_png(text: str, title: str = "") -> bytes:
    """
    Convertit du texte en image PNG (bytes).
    Design : fond sombre, texte monospace, coloration syntaxique basique.
    Retourne les bytes PNG bruts.
    """
    from PIL import Image, ImageDraw

    lines = _word_wrap(text)
    if title:
        lines = [f"═══ {title} ═══", ""] + lines

    font = _get_font()

    # Calculer la taille de l'image
    max_line_width = max((len(l) for l in lines), default=40)
    img_width = min(max(max_line_width * 8 + MARGIN * 2, 600), 1200)
    img_height = len(lines) * LINE_HEIGHT + MARGIN * 2 + 20  # +20 pour le footer

    # Créer l'image
    img = Image.new('RGB', (img_width, img_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    y = MARGIN
    for line in lines:
        segments = _highlight_line(line)
        x = MARGIN
        for text_seg, color in segments:
            if font:
                draw.text((x, y), text_seg, fill=color, font=font)
                x += font.getlength(text_seg) if hasattr(font, 'getlength') else len(text_seg) * 8
            else:
                draw.text((x, y), text_seg, fill=color)
                x += len(text_seg) * 8
        y += LINE_HEIGHT

    # Footer avec hash (pour debug/cache)
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
    footer = f"pxpipe:{text_hash} | {len(text)} chars → ~{_estimate_tokens(text)} tok → ~{IMAGE_TOKEN_COST} tok image"
    draw.text((MARGIN, img_height - 18), footer, fill=(60, 60, 80))

    # Encode en PNG
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


# ── Base64 encoding pour OpenAI Vision API ───────────────────────────────────

def text_to_base64_image(text: str, title: str = "") -> str:
    """Convertit du texte en image PNG base64-encodée (data URL)."""
    png_bytes = render_text_to_png(text, title)
    b64 = base64.b64encode(png_bytes).decode('ascii')
    return f"data:image/png;base64,{b64}"


# ── Cache (évite de re-rendre le même texte) ────────────────────────────────

def _get_cached_png(text: str) -> Optional[str]:
    """Retourne le data URL depuis le cache, ou None."""
    text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
    cache_file = CACHE_DIR / f"{text_hash}.png"
    if cache_file.exists():
        b64 = base64.b64encode(cache_file.read_bytes()).decode('ascii')
        return f"data:image/png;base64,{b64}"
    return None


def _save_to_cache(text: str, png_bytes: bytes) -> None:
    """Sauvegarde le PNG dans le cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
        cache_file = CACHE_DIR / f"{text_hash}.png"
        cache_file.write_bytes(png_bytes)
    except Exception as e:
        logger.debug(f"[pxpipe] cache save failed: {e}")


# ── API principale ──────────────────────────────────────────────────────────

def should_compress(text: str) -> bool:
    """Vérifie si le texte est assez long pour justifier la compression visuelle."""
    return _estimate_tokens(text) >= COMPRESS_THRESHOLD_TOKENS


def pxpipe_compress(text: str, title: str = "System Prompt") -> str:
    """
    Compresse du texte en image base64. Retourne le data URL.
    Utilise le cache si disponible.
    """
    cached = _get_cached_png(text)
    if cached:
        logger.debug(f"[pxpipe] cache HIT for text ({len(text)} chars)")
        return cached

    data_url = text_to_base64_image(text, title)
    png_bytes = base64.b64decode(data_url.split(',', 1)[1])
    _save_to_cache(text, png_bytes)

    logger.info(f"[pxpipe] rendered {len(text)} chars → PNG ({len(png_bytes)} bytes, "
                f"~{_estimate_tokens(text)} tok → ~{IMAGE_TOKEN_COST} tok)")
    return data_url


def build_vision_message(text_prompt: str, system_text: str = "",
                         image_title: str = "System Context") -> list[dict]:
    """
    Construit une liste de messages OpenAI-compatible avec image.
    
    Si system_text est fourni et dépasse le seuil :
    - Le system prompt est converti en image
    - Le prompt texte reste en texte
    
    Retourne une liste de messages au format OpenAI Chat Completions.
    """
    messages = []

    if system_text and should_compress(system_text):
        # System prompt → image
        data_url = pxpipe_compress(system_text, image_title)
        messages.append({
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "Voici le contexte système sous forme d'image. "
                            "Lis attentivement chaque instruction."
                },
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"}
                }
            ]
        })
    elif system_text:
        # System prompt court → texte normal
        messages.append({"role": "system", "content": system_text})

    # User prompt → toujours en texte
    messages.append({"role": "user", "content": text_prompt})

    return messages


def inject_visual_context(system: str) -> str:
    """
    Alternative textuelle : remplace le système prompt long par un résumé
    + référence à l'image (pour les providers qui ne supportent pas vision).
    
    Pour les providers vision (GPT-4V, Claude 3, Gemini), utilisez
    build_vision_message() à la place.
    """
    if not should_compress(system):
        return system

    # Extraire les premières et dernières lignes comme accroche
    lines = system.split('\n')
    head = '\n'.join(lines[:10])
    tail = '\n'.join(lines[-5:])

    data_url = pxpipe_compress(system, "System Context")

    return (
        f"{head}\n\n"
        f"[PXPipe VISUAL CONTEXT — {len(system)} chars compressed to image]\n"
        f"[Image: {data_url[:80]}...]\n\n"
        f"... ({len(lines) - 15} lines compressed) ...\n\n"
        f"{tail}"
    )


# ── Stats ────────────────────────────────────────────────────────────────────

def pxpipe_stats() -> dict:
    """Retourne les stats du cache Pxpipe."""
    if not CACHE_DIR.exists():
        return {"cached_prompts": 0, "total_bytes": 0, "cache_dir": str(CACHE_DIR)}

    files = list(CACHE_DIR.glob("*.png"))
    total = sum(f.stat().st_size for f in files)
    return {
        "cached_prompts": len(files),
        "total_bytes": total,
        "total_mb": round(total / 1024 / 1024, 2),
        "cache_dir": str(CACHE_DIR),
    }


if __name__ == "__main__":
    # Test rapide
    sample = """Tu es un architecte expert dans un système multi-agents.
Tu dois générer un blueprint détaillé pour la tâche suivante.

## Règles
1. Chaque module doit avoir une responsabilité unique
2. Les imports doivent être explicites
3. Pas de circular dependencies
4. Tests unitaires pour chaque fonction publique

## Architecture cible
- main.py: point d'entrée
- core/: logique métier
- adapters/: interfaces externes
- tests/: suite de tests

## Signatures requises
def process(data: dict) -> Result
def validate(input: Any) -> bool
class Pipeline:
    def run(self) -> Output
    def rollback(self) -> None

## Dépendances
- fastapi>=0.100.0
- pydantic>=2.0
- sqlalchemy>=2.0
- pytest>=7.0

## Risques
- Race condition possible entre les workers
- Memory leak sur les gros datasets
- Timeout sur les appels API externes
"""

    print("=== Pxpipe Test ===")
    print(f"Text: {len(sample)} chars, ~{_estimate_tokens(sample)} tokens")
    print(f"Should compress: {should_compress(sample)}")

    data_url = pxpipe_compress(sample, "Test Blueprint")
    print(f"Data URL: {data_url[:60]}...")
    print(f"Stats: {pxpipe_stats()}")
