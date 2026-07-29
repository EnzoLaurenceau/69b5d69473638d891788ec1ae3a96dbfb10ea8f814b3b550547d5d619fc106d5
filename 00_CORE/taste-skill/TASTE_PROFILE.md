# FORGE ARTISTIC TASTE PROFILE
# Source: taste-skill.dev (45k+ stars) + seraui.com (200+ components)
# Purpose: EVERYTHING that has a UI passes through this filter
# Applies to: landing pages, dashboards, apps, admin panels, emails, docs, settings, presentations

---

## DIRECTIVE: ANTI-SLOP ENFORCEMENT

EVERY visual artifact produced by the Forge MUST pass through the Taste Skill
brief-inference system BEFORE writing a single line of code. No exceptions.
This includes "simple" pages — settings panels, forms, CRUD views, internal tools.
Data-heavy does NOT mean ugly. Every screen deserves intentional design.

---

## PHASE 1: BRIEF INFERENCE (Mandatory — Section 0)

Before ANY code generation, output a one-line Design Read:

"Reading this as: <page kind> for <audience>, with a <vibe> language,
leaning toward <design system or aesthetic family>."

### Signals to Read:
1. **Page kind** — landing (SaaS/consumer/agency/event), portfolio, redesign, editorial
2. **Vibe words** — minimalist, brutalist, Apple-y, playful, editorial, glassy, dark tech
3. **Reference signals** — URLs, screenshots, competing brands
4. **Audience** — B2B panel vs design-conscious consumer vs recruiter
5. **Brand assets** — logo, color, type, photography
6. **Quiet constraints** — accessibility-first, public-sector, regulated industries

### Anti-Default Discipline:
NEVER default to: AI-purple gradients, centered hero over dark mesh, three equal
feature cards, generic glassmorphism, infinite micro-animations, Inter + slate-900.

---

## PHASE 2: THE THREE DIALS

After design read, set three dials that gate ALL layout/motion/density decisions:

- DESIGN_VARIANCE: 1-10 (1=Perfect Symmetry, 10=Artsy Chaos)
- MOTION_INTENSITY: 1-10 (1=Static, 10=Cinematic/Physics)
- VISUAL_DENSITY: 1-10 (1=Art Gallery/Airy, 10=Cockpit/Packed Data)

---

## PHASE 3: STYLE SELECTOR

Choose ONE primary style archetype per project. NEVER mix within a project.

### Style A: ETHEREAL GLASS (SaaS / AI / Tech)
- Deepest OLED black (#050505), radial mesh gradients
- Vantablack cards with backdrop-blur-2xl
- Wide geometric Grotesk typography
- Skill file: `taste-skill.md` Section 0-14

### Style B: EDITORIAL LUXURY (Lifestyle / Real Estate / Agency)
- Warm creams (#FDFBF7), muted sage, deep espresso
- Variable Serif fonts for massive headings
- CSS noise/film-grain overlay (opacity 0.03)
- Skill file: `soft-skill.md`

### Style C: SOFT STRUCTURALISM (Consumer / Health / Portfolio)
- Silver-grey or white backgrounds
- Massive bold Grotesk typography
- Floating components with ultra-diffuse ambient shadows
- Skill file: `soft-skill.md`

### Style D: PREMIUM UTILITARIAN MINIMALISM (Workspace / SaaS / Editorial)
- Warm monochrome (#F7F6F3), spot pastels only for semantic meaning
- Extreme typographic contrast (serif headers + sans body)
- Bento grids, flat components, generous whitespace
- Skill file: `minimalist-skill.md`

### Style E: INDUSTRIAL BRUTALISM (Data / Portfolio / Editorial)
- Swiss Industrial Print OR Tactical Telemetry CRT
- Massive uppercase headers, monospace micro-type
- Rigid grids, visible dividers, analog degradation effects
- Skill file: `brutalist-skill.md`

### Style F: REDESIGN (Existing Projects)
- Audit-first: scan, diagnose, fix
- Never rewrite from scratch
- Skill file: `redesign-skill.md`

---

## PHASE 4: COMPONENT ARSENAL (SeraUI)

React/Next.js + Tailwind CSS components from seraui.com.
Use these INSTEAD of building generic components from scratch.

### UI Components
- Marquee Scroller — infinite horizontal scroll for logos/testimonials
- Code Profile Card — developer portfolio card
- Portfolio Showcase — project gallery with hover effects
- Orbiting Circles Animation — tech stack orbit display
- Network Visualization — interactive node graph
- Video Text Overlay — text with video background
- Image Swiper Carousel — touch-friendly image gallery
- Section Divider — creative section breaks
- Noise Background — subtle grain texture overlay
- Glitch Vault Card — cyberpunk-style card with glitch effect
- Glow Line Effect — animated glow separator
- Modal Dialog — accessible modal with backdrop blur
- HTML Code Runner — live code preview
- Infinite Grid — endless scrolling grid
- Orbiting Skills — animated skill badges
- Orbiting Carousel — 3D orbiting items
- Timeline Components — vertical/horizontal timelines
- Radio Buttons — custom styled radio inputs
- Progress Bar — animated progress indicator

### Buttons & Actions
- Basic Button — clean minimal button
- Modern Button — elevated with hover states
- Glow Button — neon glow on hover
- Dropdown Menu — animated dropdown
- Shimmer Button — loading shimmer effect
- Slide-out Drawer — side panel drawer
- Liquid Glass Button — glassmorphism button

### Badges & Notifications
- Status Badge — colored status indicators
- Animated Badge — pulse/glow badges
- Verify Badge — checkmark verification badge
- Toast Notification — popup notifications
- Announcement Banner — top-bar announcements

### Form Inputs
- Search Input — search with autocomplete
- Command Prompt — terminal-style input
- Password Input — show/hide toggle
- Combo Box — searchable select dropdown

### Text Effects
- Text Animation — entrance animations
- Fuzzy Text Effect — glitch/fuzzy reveal
- Flip Words Animation — rotating word carousel
- Text Reveal Effect — scroll-triggered reveal
- Decrypting Text — cipher-style decryption animation
- Aurora Text Effect — gradient shimmer text
- Sparkles Text — sparkle particle text
- Number Ticker Counter — animated number counting
- Letter Glitch Effect — matrix-style letter scramble
- Resize Handle Text — draggable text resize
- Noise Text — noisy/distorted text
- Random Text Reveal — random character reveal
- Text Highlighter — animated highlight effect
- Curved Text — text along a path
- Kbd Text — keyboard shortcut styling

### Navigation & Layout
- Dock-style Tabs — macOS dock-style navigation
- Carousel — image/content carousel
- 3D Carousel — perspective 3D carousel
- Basic Tabs — simple tab navigation
- Fancy Tabs — animated tab transitions
- Classic Tabs — traditional tab layout
- App Dock — macOS-style app dock
- File Tree Explorer — directory tree navigation
- Copy to Clipboard — copy button with feedback

### Accordions
- Basic Accordion — simple expand/collapse
- Fancy Accordion — animated accordion

### Cards & Content
- Bento Grid — asymmetric masonry grid
- Pricing Card — pricing table card
- Feature Card — feature showcase card
- Testimonial Card — customer quote card
- Team Member Card — team grid card
- Blog Post Card — article preview card

### Backgrounds & Effects
- Gradient Background — mesh/linear/radial gradients
- Grid Background — dot/line grid patterns
- Particle Background — interactive particles
- Aurora Background — northern lights effect
- Starfield Background — animated star field
- Retro Grid — 80s perspective grid

### Loaders & States
- Skeleton Loader — content placeholder
- Spinner — loading spinner variants
- Progress Ring — circular progress
- Typing Indicator — chat typing dots

---

## PHASE 5: ANTI-SLOP BAN LIST

These patterns are HARD FAILURES. If any appear, the design fails:

### Banned Fonts
Inter, Roboto, Arial, Open Sans, Helvetica (use Geist, Clash Display,
PP Editorial New, Plus Jakarta Sans, Cabinet Grotesk, Satoshi instead)

### Banned Icons
Standard thick-stroked Lucide, FontAwesome, Material Icons
(use Phosphor Light, Remix Line, ultra-light SVG instead)

### Banned Layouts
- Three equal card columns as feature row
- Everything centered and symmetrical
- Edge-to-edge sticky navbars glued to top
- height: 100vh (use min-height: 100dvh)

### Banned Colors
- Pure #000000 background (use off-black #0a0a0a, #121212)
- Oversaturated accents (>80% saturation)
- Purple/blue "AI gradient" aesthetic
- Mixing warm and cool grays

### Banned Motion
- Standard linear or ease-in-out transitions
- Instant state changes without interpolation
- Infinite-loop micro-animations everywhere

### Banned Copy
- "Elevate", "Seamless", "Unleash", "Next-Gen", "Game-changer", "Delve"
- Generic placeholder names ("John Doe", "Acme Corp", "Lorem Ipsum")
- Emojis in code, markup, or alt text

### Banned Shadows
- Generic 1px solid gray borders
- Harsh dark drop shadows (shadow-md, rgba(0,0,0,0.3))
- Untinted pure-black shadows

---

## PHASE 6: PRE-FLIGHT CHECKLIST

Before shipping ANY frontend, verify ALL of these:

- [ ] Design Read declared in one line
- [ ] Three dials set (Variance, Motion, Density)
- [ ] Style archetype chosen and committed
- [ ] Zero banned fonts in codebase
- [ ] Zero banned layout patterns
- [ ] Zero banned color patterns
- [ ] Zero banned copy patterns
- [ ] Motion uses spring/custom easing, not linear/ease-in-out
- [ ] Dark mode: off-black/off-white, WCAG AA contrast, brand fidelity
- [ ] Mobile: min-h-[100dvh], no h-screen, proper breakpoints
- [ ] All code blocks complete (see output-skill.md)
- [ ] No placeholders, TODOs, or "implement here" comments
- [ ] SeraUI components used where applicable (not reinventing)

---

## PHASE 7: IMPECCABLE REVIEW (Production Quality Gate)

After taste workflow produces code, run IMPECCABLE to verify production readiness.

### For NEW builds:
1. `impeccable:critique [target]` — UX review: hierarchy, clarity, emotional resonance
2. `impeccable:audit [target]` — Technical: a11y, performance, responsive, edge cases
3. `impeccable:polish [target]` — Final pass: design system alignment, shipping readiness
4. `impeccable:harden [target]` — Error handling, text overflow, i18n, loading states

### For REVIEWING existing prototypes:
1. `impeccable:critique` → find what's wrong (UX, hierarchy, clarity)
2. `impeccable:audit` → technical gaps (a11y, perf, responsive)
3. `impeccable:polish` → fix and ship
4. `impeccable:harden` → edge cases, error states, i18n

### Impeccable's Key Commands:
| Command | Use When |
|---------|----------|
| `impeccable:craft` | Building new feature from scratch |
| `impeccable:shape` | Planning UX before code |
| `impeccable:critique` | Reviewing existing UI for quality |
| `impeccable:audit` | Technical quality check |
| `impeccable:polish` | Final production pass |
| `impeccable:bolder` | Design is too boring/generic |
| `impeccable:quieter` | Design is too loud/chaotic |
| `impeccable:harden` | Adding robustness (errors, edge cases) |
| `impeccable:animate` | Adding purposeful motion |
| `impeccable:typeset` | Fixing typography issues |
| `impeccable:colorize` | Color strategy problems |
| `impeccable:layout` | Spacing/rhythm issues |
| `impeccable:distill` | Stripping to essence |
| `impeccable:onboard` | First-run/empty states |
| `impeccable:adapt` | Responsive/device adaptation |
| `impeccable:optimize` | Performance improvements |
| `impeccable:overdrive` | Ambitious visual effects |
| `impeccable:delight` | Adding moments of joy |
| `impeccable:clarify` | Unclear UX copy |

### Impeccable's Design Laws (Always Apply):
- OKLCH colors, never #000 or #fff, tint neutrals toward brand hue
- Body max 65-75ch line length
- Hierarchy through scale+weight contrast (≥1.25 ratio)
- Vary spacing for rhythm — same padding everywhere = monotony
- Cards are lazy — use only when truly the best affordance
- Don't animate CSS layout properties
- Ease-out with exponential curves (quart/quint/expo)
- No em dashes — use commas, colons, semicolons, periods

### AI Slop Test:
If someone could look at this and say "AI made that" — it failed.
- First-order: category → palette obvious? (observability → dark blue) → FAIL
- Second-order: anti-reference → aesthetic obvious? → FAIL

---

## QUICK REFERENCE: FILE MAP

| File | Purpose |
|------|---------|
| `TASTE_PROFILE.md` | This file — master integration |
| `taste-skill.md` | Full v2 anti-slop skill (1206 lines) |
| `soft-skill.md` | Calm, expensive, Awwwards-tier UI |
| `minimalist-skill.md` | Editorial minimalism, warm monochrome |
| `brutalist-skill.md` | Swiss print + CRT telemetry |
| `output-skill.md` | Anti-laziness, no placeholders |
| `redesign-skill.md` | Audit-first existing project upgrades |
| `seraui-components.md` | SeraUI component catalog + usage |

---

## USAGE IN FORGE

When the Forge generates a landing page or frontend:

1. Load TASTE_PROFILE.md into context
2. Run Brief Inference (Phase 1)
3. Set Three Dials (Phase 2)
4. Pick Style Archetype (Phase 3) → load corresponding skill file
5. Pull components from SeraUI catalog (Phase 4)
6. Enforce Ban List (Phase 5)
7. Run Pre-Flight (Phase 6)
8. Only THEN write code

This ensures every site looks fundamentally different from the last.
