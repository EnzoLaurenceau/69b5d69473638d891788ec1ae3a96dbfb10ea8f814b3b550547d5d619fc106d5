# SERAUI COMPONENT CATALOG
# Source: https://seraui.com | https://github.com/seraui/seraui
# Stack: React + Next.js + Tailwind CSS + Framer Motion
# Stars: 1.3k+ | Components: 200+

---

## INSTALLATION

```bash
# Core setup (Next.js project)
npx create-next-app@latest my-app --typescript --tailwind --app
cd my-app
npm install framer-motion clsx tailwind-merge

# Individual components are copy-paste from https://seraui.com/components/<name>
# No npm package — each component is a standalone .tsx file
```

---

## UTILITY: cn() HELPER (Required by all components)

```tsx
// src/lib/utils.ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

---

## UI COMPONENTS

### Marquee Scroller
- Use: Logo walls, testimonials, infinite scroll content
- Code: https://seraui.com/components/marquee-scroller
- Key: `Marquee` component with `--gap` and `--duration` CSS vars

### Orbiting Circles Animation
- Use: Tech stack display, feature orbit, interactive decoration
- Code: https://seraui.com/components/orbiting-circles-animation
- Key: Framer Motion `motion.div` with calculated orbit paths

### Network Visualization
- Use: Team/org charts, knowledge graphs, interactive maps
- Code: https://seraui.com/components/network-visualization
- Key: Canvas/SVG + force-directed layout

### Video Text Overlay
- Use: Hero sections with video backgrounds
- Code: https://seraui.com/components/video-text-overlay
- Key: `mix-blend-mode` + `background-clip: text`

### Image Swiper Carousel
- Use: Product galleries, portfolio showcases
- Code: https://seraui.com/components/image-swiper-carousel
- Key: Touch-enabled with `useMotionValue` from Framer

### Section Divider
- Use: Creative breaks between sections
- Code: https://seraui.com/components/section-divider
- Key: SVG wave/curve/fade patterns

### Noise Background
- Use: Subtle grain texture on any surface
- Code: https://seraui.com/components/noise-background
- Key: CSS `filter: url(#noise)` with SVG feTurbulence

### Glitch Vault Card
- Use: Cyberpunk/tech portfolio cards
- Code: https://seraui.com/components/glitch-vault-card
- Key: CSS `clip-path` animation + RGB split

### Glow Line Effect
- Use: Animated separators, CTAs, nav highlights
- Code: https://seraui.com/components/glow-line-effect
- Key: `box-shadow` with animated gradient

### Modal Dialog
- Use: Confirmation dialogs, forms, detail views
- Code: https://seraui.com/components/modal-dialog
- Key: Framer Motion `AnimatePresence` + backdrop blur

### Infinite Grid
- Use: Product showcases, gallery walls
- Code: https://seraui.com/components/infinite-grid
- Key: CSS Grid + `animation: scroll` infinite

### Timeline Components
- Use: Company history, project milestones, process flows
- Code: https://seraui.com/components/timeline-components
- Key: Vertical/horizontal variants with animated connectors

### Progress Bar
- Use: File uploads, skill levels, completion states
- Code: https://seraui.com/components/progress-bar
- Key: `motion.div` with `layoutId` animation

---

## BUTTONS & ACTIONS

### Glow Button
- Use: Primary CTAs, hero actions, important triggers
- Code: https://seraui.com/components/glow-button
- Key: Radial gradient overlay on hover + box-shadow pulse

```tsx
// Core pattern (simplified)
<button className="relative group px-8 py-3 rounded-full bg-white 
  text-black font-medium overflow-hidden transition-all duration-300
  hover:shadow-[0_0_30px_rgba(255,255,255,0.3)]">
  <span className="relative z-10">{children}</span>
  <div className="absolute inset-0 bg-gradient-to-r from-transparent 
    via-white/20 to-transparent opacity-0 group-hover:opacity-100 
    transition-opacity duration-500" />
</button>
```

### Shimmer Button
- Use: Loading states, attention-grabbing CTAs
- Code: https://seraui.com/components/shimmer-button
- Key: CSS `@keyframes shimmer` with gradient sweep

### Liquid Glass Button
- Use: Premium/modern glassmorphism aesthetic
- Code: https://seraui.com/components/liquid-glass-button
- Key: `backdrop-blur` + animated border gradient

### Slide-out Drawer
- Use: Mobile nav, settings panels, detail views
- Code: https://seraui.com/components/slide-out-drawer
- Key: Framer Motion `x` animation + overlay

---

## TEXT EFFECTS

### Decrypting Text
- Use: Hero headlines, tech/terminal aesthetic
- Code: https://seraui.com/components/decrypting-text
- Key: `setInterval` with random char replacement

```tsx
// Core pattern
const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
// On each tick, replace random positions with random chars
// Converge to final text over N iterations
```

### Aurora Text Effect
- Use: Gradient shimmer on headings
- Code: https://seraui.com/components/aurora-text-effect
- Key: `background-clip: text` + animated gradient position

### Sparkles Text
- Use: Magical/premium feel, celebration moments
- Code: https://seraui.com/components/sparkles-text
- Key: Canvas particles + `globalCompositeOperation: "lighter"`

### Number Ticker Counter
- Use: Stats sections, metrics dashboards
- Code: https://seraui.com/components/number-ticker-counter
- Key: Framer Motion `useSpring` + `useTransform`

### Letter Glitch Effect
- Use: Cyberpunk headers, matrix aesthetic
- Code: https://seraui.com/components/letter-glitch-effect
- Key: CSS grid of spans with randomized `animation-delay`

### Flip Words Animation
- Use: Rotating value props ("Build X, Y, Z")
- Code: https://seraui.com/components/flip-words-animation
- Key: Framer Motion `AnimatePresence` + `mode="wait"`

### Noise Text
- Use: Distorted/edgy typography
- Code: https://seraui.com/components/noise-text
- Key: SVG filter `feTurbulence` on text element

### Curved Text
- Use: Circular logos, badges, decorative elements
- Code: https://seraui.com/components/curved-text
- Key: SVG `<textPath>` along `<circle>` or `<path>`

---

## NAVIGATION & LAYOUT

### Dock-style Tabs
- Use: macOS-style bottom navigation, app switchers
- Code: https://seraui.com/components/dock-style-tabs
- Key: Framer Motion `layoutId` for indicator animation

### 3D Carousel
- Use: Portfolio, product showcase, team display
- Code: https://seraui.com/components/3d-carousel
- Key: CSS `perspective` + `rotateY` with Framer drag

### App Dock
- Use: macOS-style icon dock with magnification
- Code: https://seraui.com/components/app-dock
- Key: Mouse proximity detection + scale transform

### File Tree Explorer
- Use: Documentation sites, code editors, file managers
- Code: https://seraui.com/components/file-tree-explorer
- Key: Recursive component + animated expand/collapse

---

## ACCORDIONS

### Fancy Accordion
- Use: FAQ sections, feature details, settings panels
- Code: https://seraui.com/components/fancy-accordion
- Key: Framer Motion `AnimatePresence` + height animation

---

## BACKGROUNDS & EFFECTS

### Aurora Background
- Use: Hero sections, full-page backgrounds
- Code: https://seraui.com/components/aurora-background
- Key: CSS radial gradients + animated hue rotation

### Grid Background
- Use: Subtle tech patterns, section backgrounds
- Code: https://seraui.com/components/grid-background
- Key: CSS `background-image` with linear-gradient grid

### Starfield Background
- Use: Space/tech themed sections
- Code: https://seraui.com/components/starfield-background
- Key: Canvas + parallax scroll effect

### Retro Grid
- Use: 80s/synthwave aesthetic, landing pages
- Code: https://seraui.com/components/retro-grid
- Key: CSS perspective + animated grid lines

---

## CARDS & CONTENT

### Bento Grid
- Use: Feature showcases, dashboard layouts, portfolio
- Code: https://seraui.com/components/bento-grid
- Key: CSS Grid with `grid-template-areas` + span variants

### Code Profile Card
- Use: Developer portfolio, GitHub-style profile
- Code: https://seraui.com/components/code-profile-card
- Key: Terminal aesthetic with syntax highlighting

### Portfolio Showcase
- Use: Designer/developer portfolio grid
- Code: https://seraui.com/components/portfolio-showcase
- Key: Masonry layout with hover reveal

---

## FORM INPUTS

### Command Prompt
- Use: Terminal-style interfaces, CLI demos
- Code: https://seraui.com/components/command-prompt
- Key: Input with prefix label + autocomplete dropdown

### Combo Box
- Use: Searchable select, filter dropdowns
- Code: https://seraui.com/components/combo-box
- Key: Popover + command palette pattern

---

## BADGES & NOTIFICATIONS

### Toast Notification
- Use: Success/error/info feedback
- Code: https://seraui.com/components/toast-notification
- Key: Framer Motion `layout` + auto-dismiss timer

### Announcement Banner
- Use: Product launches, maintenance notices
- Code: https://seraui.com/components/announcement-banner
- Key: Dismissible top bar with localStorage persistence

---

## PATTERN: STYLE-TO-COMPONENT MAPPING

When TASTE_PROFILE.md selects a style archetype, prefer these SeraUI components:

| Style | Preferred Components |
|-------|---------------------|
| Ethereal Glass | Glow Button, Aurora Background, Noise Background, Modal Dialog |
| Editorial Luxury | Section Divider, Timeline, Fancy Tabs, Bento Grid |
| Soft Structuralism | Basic Button, Progress Bar, Marquee, Carousel |
| Premium Minimalism | Basic Tabs, File Tree, Code Profile Card, Toast |
| Industrial Brutalism | Letter Glitch, Decrypting Text, Retro Grid, Command Prompt |
| Cyberpunk/Tech | Glitch Vault Card, Sparkles Text, Starfield, Network Viz |

---

## COMPONENT CODE PATTERNS

All SeraUI components follow these conventions:

1. **Standalone .tsx files** — copy-paste, no package install
2. **"use client"** directive at top (Next.js App Router)
3. **cn() utility** for className merging
4. **Framer Motion** for animations (not CSS-only)
5. **Tailwind CSS** for styling (not styled-components)
6. **TypeScript** with proper prop types
7. **Dark mode** via Tailwind `dark:` prefix
8. **Responsive** via Tailwind breakpoint prefixes

### Typical Component Structure:
```tsx
"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface ComponentNameProps {
  // typed props
  className?: string;
}

export function ComponentName({ className, ...props }: ComponentNameProps) {
  return (
    <motion.div className={cn("base-styles", className)} {...props}>
      {/* component content */}
    </motion.div>
  );
}
```
