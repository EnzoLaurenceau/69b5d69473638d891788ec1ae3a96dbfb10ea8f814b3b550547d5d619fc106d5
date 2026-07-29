"""
Design Assets Module for La Forge
===================================
Indexes footer.design patterns + svgdoodles.com assets
for UI-generation agents to reference during scaffolding.

Sources:
  - https://footer.design (curated footer gallery)
  - https://svgdoodles.com (200+ SVG hand-drawn elements)

NMP: TOOL|INDEX|design_assets|savings=55|pattern=ui asset injection|approach=Pattern DB + SVG inline injection
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─── SVG Doodles Asset Library ───────────────────────────────────────────

class SVGCategory(Enum):
    ARROWS = "arrows"
    CIRCLES = "circles"
    BLOBS = "blobs"
    LINES = "lines"
    HIGHLIGHTS = "highlights"
    RECTANGLES = "rectangles"
    UNDERLINES = "underlines"
    STARS = "stars"
    BRACKETS = "brackets"
    SCRIBBLES = "scribbles"


@dataclass
class SVGDoodle:
    """Single SVG doodle element from svgdoodles.com."""
    name: str
    category: SVGCategory
    svg_code: str  # Inline SVG markup
    color: str = "#000000"
    stroke_width: float = 2.0
    viewbox: str = "0 0 100 100"
    size_bytes: int = 0

    def colorize(self, hex_color: str) -> str:
        """Return SVG with custom color applied."""
        return self.svg_code.replace(self.color, hex_color)

    def scale(self, width: int, height: int) -> str:
        """Return SVG with custom dimensions."""
        svg = self.svg_code
        svg = svg.replace('width="100"', f'width="{width}"')
        svg = svg.replace('height="100"', f'height="{height}"')
        return svg


# Curated SVG templates — inline-ready, <3KB each
SVG_DOODLE_CATALOG = {
    "arrow_curved": SVGDoodle(
        name="arrow_curved",
        category=SVGCategory.ARROWS,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" width="100" height="50"><path d="M10 40 Q50 5 90 25" stroke="#000000" fill="none" stroke-width="2" stroke-linecap="round"/><path d="M82 18 L90 25 L83 32" stroke="#000000" fill="none" stroke-width="2" stroke-linecap="round"/></svg>',
    ),
    "circle_hand": SVGDoodle(
        name="circle_hand",
        category=SVGCategory.CIRCLES,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100"><ellipse cx="50" cy="50" rx="40" ry="38" stroke="#000000" fill="none" stroke-width="2" stroke-dasharray="4,2" transform="rotate(-3 50 50)"/></svg>',
    ),
    "underline_wavy": SVGDoodle(
        name="underline_wavy",
        category=SVGCategory.UNDERLINES,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 20" width="200" height="20"><path d="M5 10 Q25 2 50 10 Q75 18 100 10 Q125 2 150 10 Q175 18 195 10" stroke="#000000" fill="none" stroke-width="2" stroke-linecap="round"/></svg>',
    ),
    "highlight_box": SVGDoodle(
        name="highlight_box",
        category=SVGCategory.HIGHLIGHTS,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 50" width="120" height="50"><rect x="5" y="5" width="110" height="40" rx="3" ry="3" stroke="#000000" fill="none" stroke-width="2" transform="rotate(-1 60 25)"/></svg>',
    ),
    "blob_organic": SVGDoodle(
        name="blob_organic",
        category=SVGCategory.BLOBS,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100"><path d="M50 10 C70 5 95 25 90 50 C85 75 65 95 45 90 C25 85 5 70 10 45 C15 20 30 15 50 10Z" fill="#000000" opacity="0.08"/></svg>',
    ),
    "star_sparkle": SVGDoodle(
        name="star_sparkle",
        category=SVGCategory.STARS,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30" width="30" height="30"><path d="M15 2 L17 12 L27 15 L17 18 L15 28 L13 18 L3 15 L13 12Z" fill="#000000"/></svg>',
    ),
    "line_scratch": SVGDoodle(
        name="line_scratch",
        category=SVGCategory.LINES,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 10" width="150" height="10"><path d="M5 5 Q40 2 75 6 Q110 10 145 4" stroke="#000000" fill="none" stroke-width="1.5" stroke-linecap="round"/></svg>',
    ),
    "bracket_curly": SVGDoodle(
        name="bracket_curly",
        category=SVGCategory.BRACKETS,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 100" width="20" height="100"><path d="M15 5 Q5 5 5 25 L5 40 Q5 50 2 50 Q5 50 5 60 L5 75 Q5 95 15 95" stroke="#000000" fill="none" stroke-width="2" stroke-linecap="round"/></svg>',
    ),
    "scribble_cross": SVGDoodle(
        name="scribble_cross",
        category=SVGCategory.SCRIBBLES,
        svg_code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30" width="30" height="30"><path d="M5 5 L25 25 M25 5 L5 25" stroke="#000000" fill="none" stroke-width="2" stroke-linecap="round"/></svg>',
    ),
}


def get_doodles_by_category(category: SVGCategory) -> list[SVGDoodle]:
    """Get all doodles for a category."""
    return [d for d in SVG_DOODLE_CATALOG.values() if d.category == category]


def inject_doodle(doodle_name: str, color: str = "#6366f1", width: int = 100, height: int = 50) -> str:
    """Get an inline SVG ready for HTML injection."""
    doodle = SVG_DOODLE_CATALOG.get(doodle_name)
    if not doodle:
        return ""
    svg = doodle.colorize(color)
    return svg


# ─── Footer.design Pattern Library ──────────────────────────────────────

class FooterStyle(Enum):
    MINIMAL = "minimal"         # Clean, few elements
    MEGA = "mega"               # Multi-column, comprehensive
    CTA_FOCUSED = "cta"         # Conversion-optimized
    BRANDED = "branded"         # Strong brand presence
    NEWSLETTER = "newsletter"   # Email capture focused
    SOCIAL = "social"           # Social proof / links
    DARK = "dark"               # Dark theme
    GRADIENT = "gradient"       # Gradient background


class FooterIndustry(Enum):
    SAAS = "saas"
    AGENCY = "agency"
    PORTFOLIO = "portfolio"
    ECOMMERCE = "ecommerce"
    STARTUP = "startup"
    ENTERPRISE = "enterprise"
    FINTECH = "fintech"
    HEALTHTECH = "healthtech"


@dataclass
class FooterPattern:
    """Footer design pattern from footer.design."""
    name: str
    style: FooterStyle
    industry: FooterIndustry
    columns: int
    has_cta: bool = True
    has_newsletter: bool = False
    has_social: bool = True
    has_trust_signals: bool = False
    has_app_badges: bool = False
    dark_mode: bool = False
    css_template: str = ""
    html_structure: str = ""
    reference_url: str = "https://footer.design"


# Curated footer patterns extracted from footer.design
FOOTER_PATTERNS = {
    "saas_mega": FooterPattern(
        name="SaaS Mega Footer",
        style=FooterStyle.MEGA,
        industry=FooterIndustry.SAAS,
        columns=4,
        has_cta=True,
        has_newsletter=True,
        has_trust_signals=True,
        dark_mode=True,
        html_structure="""<footer class="footer-mega">
  <div class="footer-top">
    <div class="footer-cta">
      <h3>Ready to get started?</h3>
      <a href="#" class="btn-primary">Start Free Trial</a>
    </div>
  </div>
  <div class="footer-grid">
    <div class="footer-col footer-brand">
      <div class="logo"></div>
      <p class="tagline"></p>
      <div class="social-links"></div>
    </div>
    <div class="footer-col"><h4>Product</h4><ul></ul></div>
    <div class="footer-col"><h4>Resources</h4><ul></ul></div>
    <div class="footer-col"><h4>Company</h4><ul></ul></div>
  </div>
  <div class="footer-bottom">
    <p>&copy; 2026 Company. All rights reserved.</p>
    <div class="footer-legal"><a href="#">Privacy</a><a href="#">Terms</a></div>
  </div>
</footer>""",
        css_template="""footer.footer-mega { background: #0f172a; color: #94a3b8; padding: 4rem 2rem 2rem; }
.footer-top { text-align: center; padding-bottom: 3rem; border-bottom: 1px solid #1e293b; }
.footer-cta h3 { color: #f8fafc; font-size: 1.5rem; margin-bottom: 1rem; }
.btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; padding: 0.75rem 2rem; border-radius: 8px; text-decoration: none; }
.footer-grid { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 2rem; padding: 3rem 0; }
.footer-bottom { border-top: 1px solid #1e293b; padding-top: 1.5rem; display: flex; justify-content: space-between; font-size: 0.875rem; }""",
    ),
    "startup_minimal": FooterPattern(
        name="Startup Minimal Footer",
        style=FooterStyle.MINIMAL,
        industry=FooterIndustry.STARTUP,
        columns=1,
        has_cta=False,
        has_social=True,
        dark_mode=False,
        html_structure="""<footer class="footer-minimal">
  <div class="footer-inner">
    <div class="logo"></div>
    <nav class="footer-nav"><a href="#">About</a><a href="#">Blog</a><a href="#">Contact</a></nav>
    <div class="social-links"></div>
    <p class="copyright">&copy; 2026 Startup Inc.</p>
  </div>
</footer>""",
        css_template="""footer.footer-minimal { padding: 2rem; text-align: center; border-top: 1px solid #e2e8f0; }
.footer-inner { max-width: 600px; margin: 0 auto; }
.footer-nav { display: flex; gap: 1.5rem; justify-content: center; margin: 1rem 0; }
.footer-nav a { color: #64748b; text-decoration: none; font-size: 0.875rem; }
.social-links { margin: 1rem 0; }
.copyright { color: #94a3b8; font-size: 0.75rem; }""",
    ),
    "agency_branded": FooterPattern(
        name="Agency Branded Footer",
        style=FooterStyle.BRANDED,
        industry=FooterIndustry.AGENCY,
        columns=3,
        has_cta=True,
        has_newsletter=True,
        has_trust_signals=True,
        dark_mode=True,
        html_structure="""<footer class="footer-branded">
  <div class="footer-hero">
    <h2>Let's build something great together.</h2>
    <a href="#" class="btn-outline">Get in touch</a>
  </div>
  <div class="footer-cols">
    <div class="col"><h4>Services</h4><ul></ul></div>
    <div class="col"><h4>Work</h4><ul></ul></div>
    <div class="col newsletter"><h4>Stay updated</h4><input type="email" placeholder="your@email.com"/><button>Subscribe</button></div>
  </div>
  <div class="footer-bar">
    <span>&copy; 2026 Agency</span>
    <div class="badges"></div>
  </div>
</footer>""",
        css_template="""footer.footer-branded { background: linear-gradient(180deg, #1a1a2e, #16213e); color: #e2e8f0; }
.footer-hero { text-align: center; padding: 4rem 2rem; }
.footer-hero h2 { font-size: 2rem; background: linear-gradient(90deg, #f472b6, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.btn-outline { border: 1px solid #818cf8; color: #818cf8; padding: 0.75rem 2rem; border-radius: 999px; text-decoration: none; }
.footer-cols { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 2rem; padding: 2rem; }""",
    ),
    "ecommerce_trust": FooterPattern(
        name="E-commerce Trust Footer",
        style=FooterStyle.CTA_FOCUSED,
        industry=FooterIndustry.ECOMMERCE,
        columns=5,
        has_cta=True,
        has_newsletter=True,
        has_social=True,
        has_trust_signals=True,
        has_app_badges=True,
        dark_mode=False,
    ),
    "fintech_gradient": FooterPattern(
        name="Fintech Gradient Footer",
        style=FooterStyle.GRADIENT,
        industry=FooterIndustry.FINTECH,
        columns=4,
        has_cta=True,
        has_trust_signals=True,
        dark_mode=True,
    ),
}


def get_footer_pattern(style: Optional[FooterStyle] = None, industry: Optional[FooterIndustry] = None) -> list[FooterPattern]:
    """Query footer patterns by style and/or industry."""
    results = list(FOOTER_PATTERNS.values())
    if style:
        results = [p for p in results if p.style == style]
    if industry:
        results = [p for p in results if p.industry == industry]
    return results


def generate_footer_html(pattern_name: str, brand_name: str = "Company", primary_color: str = "#6366f1") -> str:
    """Generate ready-to-use footer HTML from a pattern."""
    pattern = FOOTER_PATTERNS.get(pattern_name)
    if not pattern:
        return "<!-- Pattern not found -->"
    html = pattern.html_structure.replace("Company", brand_name)
    css = pattern.css_template.replace("#6366f1", primary_color)
    return f"<style>\n{css}\n</style>\n{html}"


# ─── Fontshare & UI Colors & Park UI Integrations ───────────────────────

# Popular Fontshare fonts and their categories/fallback styles
FONTSHARE_FONTS = {
    "satoshi": {"name": "Satoshi", "weights": [300, 400, 500, 700, 900], "category": "sans-serif"},
    "clash-display": {"name": "Clash Display", "weights": [300, 400, 500, 600, 700], "category": "sans-serif"},
    "general-sans": {"name": "General Sans", "weights": [300, 400, 500, 600, 700], "category": "sans-serif"},
    "cabinet-grotesk": {"name": "Cabinet Grotesk", "weights": [800], "category": "sans-serif"},
    "boska": {"name": "Boska", "weights": [300, 400, 500, 700, 900], "category": "serif"},
    "synco": {"name": "Synco", "weights": [400, 700, 800], "category": "sans-serif"},
    "telma": {"name": "Telma", "weights": [300, 400, 700], "category": "sans-serif"},
}


def get_fontshare_link(fonts: list[str]) -> str:
    """Generate Fontshare CSS Link stylesheet HTML."""
    if not fonts:
        return ""
    # Example format: https://api.fontshare.com/v2/css?f[]=satoshi@300,400,500,700,900&f[]=clash-display@300,400,500,600,700&display=swap
    query_parts = []
    for f in fonts:
        f_lower = f.lower().replace(" ", "-")
        if f_lower in FONTSHARE_FONTS:
            weights_str = ",".join(str(w) for w in FONTSHARE_FONTS[f_lower]["weights"])
            query_parts.append(f"f[]={f_lower}@{weights_str}")
    if not query_parts:
        return ""
    url = "https://api.fontshare.com/v2/css?" + "&".join(query_parts) + "&display=swap"
    return f'<link href="{url}" rel="stylesheet">'


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert hex string (e.g. #6366f1) to RGB tuple."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    return int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB to hex string."""
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert RGB (0-255) to HSL (0-360, 0-100, 0-100)."""
    r_pct, g_pct, b_pct = r / 255.0, g / 255.0, b / 255.0
    mx = max(r_pct, g_pct, b_pct)
    mn = min(r_pct, g_pct, b_pct)
    diff = mx - mn
    l = (mx + mn) / 2.0
    
    if diff == 0:
        h = s = 0.0
    else:
        s = diff / (2.0 - mx - mn) if l > 0.5 else diff / (mx + mn)
        if mx == r_pct:
            h = (g_pct - b_pct) / diff + (6.0 if g_pct < b_pct else 0.0)
        elif mx == g_pct:
            h = (b_pct - r_pct) / diff + 2.0
        else:
            h = (r_pct - g_pct) / diff + 4.0
        h /= 6.0
        
    return h * 360.0, s * 100.0, l * 100.0


def hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """Convert HSL (0-360, 0-100, 0-100) to RGB (0-255, 0-255, 0-255)."""
    h /= 360.0
    s /= 100.0
    l /= 100.0
    if s == 0:
        r = g = b = l
    else:
        def hue_2_rgb(p, q, t):
            if t < 0: t += 1
            if t > 1: t -= 1
            if t < 1/6: return p + (q - p) * 6 * t
            if t < 1/2: return q
            if t < 2/3: return p + (q - p) * (2/3 - t) * 6
            return p
            
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue_2_rgb(p, q, h + 1/3)
        g = hue_2_rgb(p, q, h)
        b = hue_2_rgb(p, q, h - 1/3)
        
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def generate_uicolors_palette(hex_color: str) -> dict[int, str]:
    """
    Generate a Tailwind CSS 50-950 color scale algorithmically based on a single hex color.
    Simulates the uicolors.app scale mapping logic by shifting HSL lightness and saturation.
    """
    try:
        r, g, b = hex_to_rgb(hex_color)
    except Exception:
        # Fallback to Indigo if invalid hex
        r, g, b = 99, 102, 241
        
    h, s, l = rgb_to_hsl(r, g, b)
    
    # Specific lightness values mapping target for Tailwind shades
    lightness_targets = {
        50: 97.0,
        100: 93.0,
        200: 85.0,
        300: 75.0,
        400: 60.0,
        500: l,  # Keep original lightness for the base color
        600: max(l - 8.0, 15.0),
        700: max(l - 18.0, 12.0),
        800: max(l - 28.0, 9.0),
        900: max(l - 38.0, 6.0),
        950: max(l - 44.0, 4.0),
    }
    
    # Base saturation scaling to prevent neon or muddy colors at extremes
    palette = {}
    for shade, target_l in lightness_targets.items():
        if shade == 500:
            target_s = s
        elif shade < 500:
            # Shift saturation slightly higher for very light colors to retain color info
            target_s = min(s * 1.1, 100.0)
        else:
            # De-saturate slightly at the dark end to avoid overly saturated deep shades
            factor = (950 - shade) / 450.0  # 1.0 down to 0.0
            target_s = max(s * (0.7 + 0.3 * factor), 10.0)
            
        r_out, g_out, b_out = hsl_to_rgb(h, target_s, target_l)
        palette[shade] = rgb_to_hex(r_out, g_out, b_out)
        
    return palette


# Park UI component HTML/CSS recipes
PARK_UI_COMPONENTS = {
    "button": {
        "html": """<button class="park-btn park-btn-solid">
  <span>Confirm Action</span>
</button>
<button class="park-btn park-btn-outline">
  <span>Cancel</span>
</button>""",
        "css": """.park-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-satoshi, 'Satoshi', sans-serif);
  font-weight: 500;
  font-size: 0.875rem;
  border-radius: 0.5rem;
  padding: 0.5rem 1rem;
  transition: all 0.2s ease;
  cursor: pointer;
  outline: none;
  gap: 0.5rem;
  height: 2.5rem;
}
.park-btn-solid {
  background-color: var(--park-primary-500, #0f172a);
  color: #ffffff;
  border: 1px solid transparent;
}
.park-btn-solid:hover {
  background-color: var(--park-primary-600, #1e293b);
}
.park-btn-solid:focus-visible {
  box-shadow: 0 0 0 2px var(--park-primary-200, #94a3b8), 0 0 0 4px var(--park-primary-500, #0f172a);
}
.park-btn-outline {
  background-color: transparent;
  color: var(--park-primary-800, #1e293b);
  border: 1px solid var(--park-primary-200, #e2e8f0);
}
.park-btn-outline:hover {
  background-color: var(--park-primary-50, #f8fafc);
  border-color: var(--park-primary-300, #cbd5e1);
}""",
    },
    "card": {
        "html": """<div class="park-card">
  <div class="park-card-header">
    <h3 class="park-card-title">Project Settings</h3>
    <p class="park-card-description">Configure your repository visibility and build triggers.</p>
  </div>
  <div class="park-card-content">
    <div class="park-form-group">
      <label class="park-label">Project Name</label>
      <input type="text" class="park-input" placeholder="La Forge Engine" />
    </div>
  </div>
  <div class="park-card-footer">
    <button class="park-btn park-btn-outline">Cancel</button>
    <button class="park-btn park-btn-solid">Save Changes</button>
  </div>
</div>""",
        "css": """.park-card {
  border-radius: 0.75rem;
  border: 1px solid var(--park-primary-200, #e2e8f0);
  background-color: #ffffff;
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px -1px rgba(0, 0, 0, 0.05);
  font-family: var(--font-satoshi, 'Satoshi', sans-serif);
  max-width: 400px;
}
.park-card-header {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.park-card-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--park-primary-950, #090d16);
  margin: 0;
}
.park-card-description {
  font-size: 0.875rem;
  color: var(--park-primary-500, #64748b);
  margin: 0;
}
.park-card-content {
  padding: 0 1.5rem 1.5rem;
}
.park-card-footer {
  padding: 1.5rem;
  border-top: 1px solid var(--park-primary-100, #f1f5f9);
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
.park-form-group {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.park-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--park-primary-800, #1e293b);
}
.park-input {
  height: 2.5rem;
  border-radius: 0.5rem;
  border: 1px solid var(--park-primary-200, #e2e8f0);
  padding: 0 0.75rem;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.park-input:focus {
  border-color: var(--park-primary-500, #6366f1);
  box-shadow: 0 0 0 1px var(--park-primary-500, #6366f1);
}""",
    },
    "tabs": {
        "html": """<div class="park-tabs">
  <div class="park-tab-list">
    <button class="park-tab-trigger active" data-tab="account">Account</button>
    <button class="park-tab-trigger" data-tab="security">Security</button>
    <button class="park-tab-trigger" data-tab="billing">Billing</button>
  </div>
</div>""",
        "css": """.park-tabs {
  font-family: var(--font-satoshi, 'Satoshi', sans-serif);
  width: 100%;
}
.park-tab-list {
  display: inline-flex;
  background-color: var(--park-primary-100, #f1f5f9);
  padding: 0.25rem;
  border-radius: 0.5rem;
  gap: 0.25rem;
}
.park-tab-trigger {
  border: none;
  background: transparent;
  padding: 0.375rem 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--park-primary-600, #475569);
  cursor: pointer;
  transition: all 0.15s ease;
}
.park-tab-trigger:hover {
  color: var(--park-primary-900, #0f172a);
}
.park-tab-trigger.active {
  background-color: #ffffff;
  color: var(--park-primary-950, #090d16);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}""",
    }
}


def generate_park_theme_css(palette: dict[int, str], font_family: str = "Satoshi") -> str:
    """Generate the root CSS variables declaring the design system variables."""
    css = ":root {\n"
    for shade, hex_code in palette.items():
        css += f"  --park-primary-{shade}: {hex_code};\n"
    css += f"  --font-satoshi: '{font_family}', sans-serif;\n"
    css += "}\n"
    return css


# ─── Combined Design System ─────────────────────────────────────────────

class DesignAssetManager:
    """
    Unified access to design assets for forge's UI generation agents.
    
    Combines:
    - SVG doodles for decoration/polish
    - Footer patterns for complete footer scaffolding
    - Color palette generation (UI Colors algorithm)
    - Responsive breakpoint patterns
    - Fontshare web fonts integration
    - Park UI premium web components
    """

    def __init__(self):
        self.doodle_catalog = SVG_DOODLE_CATALOG
        self.footer_patterns = FOOTER_PATTERNS
        self.font_catalog = FONTSHARE_FONTS
        self.park_components = PARK_UI_COMPONENTS
        self.usage_stats = {"doodles_served": 0, "footers_served": 0, "palettes_generated": 0, "fonts_served": 0}

    def get_doodle(self, name: str, color: str = "#6366f1") -> str:
        self.usage_stats["doodles_served"] += 1
        return inject_doodle(name, color)

    def get_footer(self, pattern: str, brand: str = "Company") -> str:
        self.usage_stats["footers_served"] += 1
        return generate_footer_html(pattern, brand)

    def get_fontshare_embed(self, fonts: list[str]) -> str:
        self.usage_stats["fonts_served"] += 1
        return get_fontshare_link(fonts)

    def generate_palette(self, base_hex: str) -> dict[int, str]:
        self.usage_stats["palettes_generated"] += 1
        return generate_uicolors_palette(base_hex)

    def get_park_component(self, name: str, base_hex: str = "#6366f1") -> dict[str, str]:
        comp = self.park_components.get(name)
        if not comp:
            return {}
        palette = self.generate_palette(base_hex)
        theme_css = generate_park_theme_css(palette)
        
        return {
            "html": comp["html"],
            "css": f"{theme_css}\n{comp['css']}"
        }

    def list_all_assets(self) -> dict:
        return {
            "doodles": list(self.doodle_catalog.keys()),
            "doodle_categories": [c.value for c in SVGCategory],
            "footer_patterns": list(self.footer_patterns.keys()),
            "footer_styles": [s.value for s in FooterStyle],
            "footer_industries": [i.value for i in FooterIndustry],
            "fonts": list(self.font_catalog.keys()),
            "park_components": list(self.park_components.keys()),
        }

    def generate_skeleton_shimmer_css(self, dark_mode: bool = False) -> str:
        """Generate modern shimmer CSS skeleton rules."""
        if dark_mode:
            return (
                "@keyframes shimmer {\n"
                "  0% { background-position: -200% 0; }\n"
                "  100% { background-position: 200% 0; }\n"
                "}\n"
                ".shimmer-bg {\n"
                "  background: linear-gradient(90deg, #1f2937 25%, #374151 50%, #1f2937 75%);\n"
                "  background-size: 200% 100%;\n"
                "  animation: shimmer 1.5s infinite linear;\n"
                "}"
            )
        return (
            "@keyframes shimmer {\n"
            "  0% { background-position: -200% 0; }\n"
            "  100% { background-position: 200% 0; }\n"
            "}\n"
            ".shimmer-bg {\n"
            "  background: linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%);\n"
            "  background-size: 200% 100%;\n"
            "  animation: shimmer 1.5s infinite linear;\n"
            "}"
        )

    def get_shimmer_skeleton(self, layout_type: str = "card") -> str:
        """Return native HTML for standard shimmer skeletons (card, list, text)."""
        if layout_type == "list":
            return (
                '<div class="shimmer-list" style="display: flex; flex-direction: column; gap: 8px;">\n'
                '  <div class="shimmer-bg" style="height: 16px; width: 90%; border-radius: 4px;"></div>\n'
                '  <div class="shimmer-bg" style="height: 16px; width: 75%; border-radius: 4px;"></div>\n'
                '  <div class="shimmer-bg" style="height: 16px; width: 60%; border-radius: 4px;"></div>\n'
                '</div>'
            )
        elif layout_type == "text":
            return '<div class="shimmer-bg" style="height: 14px; width: 100%; border-radius: 4px;"></div>'
        # Default: card layout
        return (
            '<div class="shimmer-card" style="padding: 16px; border: 1px solid #e5e7eb; border-radius: 8px;">\n'
            '  <div class="shimmer-bg" style="height: 120px; border-radius: 6px; margin-bottom: 12px;"></div>\n'
            '  <div class="shimmer-bg" style="height: 20px; width: 55%; border-radius: 4px; margin-bottom: 8px;"></div>\n'
            '  <div class="shimmer-bg" style="height: 14px; width: 80%; border-radius: 4px;"></div>\n'
            '</div>'
        )

    def to_nmp(self) -> str:
        return f"ASSETS|DESIGN|doodles={len(self.doodle_catalog)}|footers={len(self.footer_patterns)}|fonts={len(self.font_catalog)}|park_components={len(self.park_components)}|served={self.usage_stats}"
