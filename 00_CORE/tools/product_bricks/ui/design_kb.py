"""
design_kb.py — Design Knowledge Base (UI & Visual)
====================================================
Catalogue de sources UI/design indexé dans turbovec.
L'orchestrateur interroge cette base pour choisir les sources
adaptées à la marque/besoin — PAS de défaut imposé.

Usage :
    from tools.product_bricks.ui import design_kb
    design_kb.build()                               # indexe turbovec (1x)
    hits = design_kb.search("minimal SaaS React")   # sources pertinentes
    details = design_kb.get("shadcn")               # {id, name, url, style, ...}
    design_kb.register({...})                       # ajoute une source
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(FORGE_ROOT / "00_CORE"))

CATALOG_FILE = Path(__file__).resolve().parent / "design_kb_catalog.json"

_SOURCES: list[dict] = [
    {
        "id": "shadcn",
        "name": "shadcn/ui",
        "url": "https://ui.shadcn.com",
        "style": ["minimal", "clean", "professional"],
        "type": ["SaaS", "dashboard", "app"],
        "tech": ["React", "Tailwind", "Radix"],
        "access": "copy-paste (npx shadcn@latest add)",
        "license": "MIT",
        "caller": "tools/product_bricks/ui/shadcn_caller.py",
        "note": "Composants sans dépendance forcée — copy-paste dans le projet.",
    },
    {
        "id": "21st_dev",
        "name": "21st.dev",
        "url": "https://21st.dev",
        "style": ["modern", "bold", "animated"],
        "type": ["SaaS", "landing", "marketing"],
        "tech": ["React", "Tailwind"],
        "access": "Magic MCP + catalogue web",
        "license": "varies per component",
        "note": "Génération de composants via MCP — idéal landing/hero sections.",
    },
    {
        "id": "componentry",
        "name": "componentry.fun",
        "url": "https://componentry.fun",
        "style": ["playful", "creative", "expressive"],
        "type": ["landing", "portfolio", "blog"],
        "tech": ["React", "vanilla"],
        "access": "web browse + copy",
        "license": "open (vérifier par composant)",
        "note": "Composants expressifs pour marques créatives — vérifier licence au build.",
    },
    {
        "id": "themefisher",
        "name": "Themefisher React Templates",
        "url": "https://themefisher.com/react-themes",
        "style": ["professional", "clean", "corporate"],
        "type": ["landing", "agency", "startup", "ecom"],
        "tech": ["React", "Next.js"],
        "access": "download (free/premium)",
        "license": "MIT (free) / commercial (premium) — vérifier avant revente",
        "note": "Templates complets React/Next — adapter à la marque, ne pas livrer tel quel.",
    },
    {
        "id": "tailwind_ui",
        "name": "Tailwind UI",
        "url": "https://tailwindui.com",
        "style": ["clean", "professional", "minimal"],
        "type": ["SaaS", "marketing", "ecom", "app"],
        "tech": ["React", "Vue", "HTML", "Tailwind"],
        "access": "licence one-time (payante)",
        "license": "Tailwind UI license (commercial, multi-projet)",
        "note": "Référence qualité — vérifier licence multi-projet avant usage.",
    },
    {
        "id": "daisyui",
        "name": "DaisyUI",
        "url": "https://daisyui.com",
        "style": ["playful", "colorful", "themeable"],
        "type": ["app", "dashboard", "blog", "ecom"],
        "tech": ["Tailwind", "React", "Svelte", "Vue"],
        "access": "npm install daisyui",
        "license": "MIT",
        "note": "30+ thèmes — idéal quand la marque a une palette forte à respecter.",
    },
    {
        "id": "refero",
        "name": "Refero (150K real app screens)",
        "url": "https://refero.design",
        "style": ["research", "reference", "real-world"],
        "type": ["any"],
        "tech": ["any"],
        "access": "Refero MCP + skill (~/.claude/skills/refero)",
        "license": "reference only",
        "note": "BASE de recherche design — interroger AVANT de choisir les composants. 150K écrans réels.",
    },
    {
        "id": "footer_design",
        "name": "Footer.design",
        "url": "https://footer.design",
        "style": ["professional", "clean", "trust"],
        "type": ["SaaS", "landing", "agency", "ecom", "fintech"],
        "tech": ["HTML", "CSS", "React"],
        "access": "forge_agents/design_assets.py — get_footer_pattern() / generate_footer_html(brand)",
        "license": "patterns de référence — HTML/CSS généré custom",
        "note": "1000+ footers curés. generate_footer_html(pattern, brand) injecte un footer AU NOM de la marque.",
    },
    {
        "id": "svgdoodles",
        "name": "SVG Doodles",
        "url": "https://svgdoodles.com",
        "style": ["organic", "playful", "premium", "hand-drawn"],
        "type": ["landing", "onboarding", "empty-state", "portfolio"],
        "tech": ["SVG", "inline"],
        "access": "forge_agents/design_assets.py — inject_doodle(name, color)",
        "license": "free (usage commercial OK)",
        "note": "200+ SVG hand-drawn colorisables à la teinte de marque. Aspect organique/premium.",
    },
]


def build() -> None:
    """Indexe le catalogue dans turbovec (agent='UI') + écrit design_kb_catalog.json."""
    try:
        from forge_agents.turbovec_brain import get_turbovec_brain
        brain = get_turbovec_brain()
        for src in _SOURCES:
            text = (
                f"UI source: {src['name']} | style: {', '.join(src['style'])} | "
                f"type: {', '.join(src['type'])} | tech: {', '.join(src['tech'])} | "
                f"note: {src['note']}"
            )
            brain.store(text, agent="UI", metadata={"id": src["id"], "url": src["url"]})
    except Exception:
        pass  # ponytail: turbovec optionnel, catalogue JSON suffit en fallback
    CATALOG_FILE.write_text(json.dumps(_SOURCES, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"design_kb: {len(_SOURCES)} sources indexées → {CATALOG_FILE.name}")


def search(query: str) -> list[dict]:
    """Sources UI pertinentes pour un mood/type/tech donné (match par mot-clé)."""
    tokens = [t for t in query.lower().replace(",", " ").split() if t]
    results = []
    for src in _SOURCES:
        score = 0
        haystack = " ".join(
            src[f] if isinstance(src[f], str) else " ".join(src[f])
            for f in ("style", "type", "tech")
        ).lower()
        blob = (haystack + " " + src.get("note", "") + " " + src.get("name", "")).lower()
        for tok in tokens:
            if tok in blob:
                score += 1
        if score:
            results.append((score, src))
    return [s for _, s in sorted(results, key=lambda x: -x[0])]


def get(source_id: str) -> dict | None:
    """Détails d'une source par id."""
    return next((s for s in _SOURCES if s["id"] == source_id), None)


def register(source: dict) -> None:
    """Ajoute une source au catalogue et ré-indexe."""
    _SOURCES.append(source)
    build()


def brand_kit(brand_hex: str = "#6366f1", fonts: list[str] | None = None) -> dict:
    """
    Personnalité de marque : palette + footer + doodles + thème, tous à la couleur
    de la marque. Délègue à forge_agents/design_assets.py (DesignAssetManager).
    C'est ce qui rend chaque site PROPRE à sa marque (pas un template générique).
    """
    try:
        from forge_agents.design_assets import DesignAssetManager
        mgr = DesignAssetManager()
        return {
            "palette": mgr.generate_palette(brand_hex),
            "fontshare": mgr.get_fontshare_embed(fonts or ["Satoshi", "General Sans"]),
            "assets": mgr.list_all_assets(),
            "brand_hex": brand_hex,
            "hint": "get_footer(pattern, brand) / get_doodle(name, brand_hex) / get_park_component(name, brand_hex)",
        }
    except Exception as e:
        return {"error": f"design_assets indisponible: {e}", "brand_hex": brand_hex}


if __name__ == "__main__":
    build()
    hits = search("SaaS minimal React")
    print(f"search('SaaS minimal React') → {len(hits)} sources")
    for h in hits:
        print(f"  {h['id']}: style={h['style']} | tech={h['tech']}")
