# ORBIT VEIL — Real-time Satellite Tracker Analysis

**Project:** ORBIT VEIL — Real-time Satellite Tracker  
**Location:** `C:/Users/Enzo/Documents/MODELS/.claude/07_KNOWLEDGE_BASE/kimi_projects/orbit_veil/`  
**Build:** Vite + React (bundled, minified)  
**Bundle Size:** ~868KB JS, ~19KB CSS  
**Analysis Date:** July 19, 2026

---

## 1. Libraries & Frameworks

### Core Stack
- **React 18+** — Full React runtime with concurrent features
  - `useState`, `useRef`, `useCallback`, `useMemo` hooks throughout
  - JSX runtime (`St.jsx`, `St.jsxs` — minified `React.jsx`/`React.jsxs`)
  - `Z` is the minified React namespace
- **Three.js** — Full WebGL 3D rendering pipeline
  - `WebGLRenderer` with antialiasing, high-performance power preference
  - `PerspectiveCamera` (42° FOV, near=0.05, far=400)
  - `OrbitControls` with damping (0.08), auto-rotate (0.25 speed), min/max distance (1.35–30)
  - `EffectComposer` with `UnrealBloomPass` for glow effects
  - `ShaderMaterial` with custom vertex/fragment shaders
  - `InstancedMesh` likely used for satellite dots (performance optimization)
  - `ResizeObserver` for responsive canvas sizing
  - WebGL context loss handling
- **React Router** — Client-side routing
  - `Route`, `Routes`, `useRoutes`, `useLocation`, `useNavigate`
- **Tailwind CSS** — Utility-first CSS framework
  - All `--tw-*` CSS variables present
  - Responsive breakpoints (`md:`, `max-md:`)
  - Arbitrary values (`text-[10px]`, `tracking-[0.25em]`, `w-[300px]`)
- **Vite** — Build tool
  - Module preload pattern in HTML
  - Asset hashing (`index-2YwmtxR8.js`, `index-BGL6OXCx.css`)
  - ES module output
- **IndexedDB** — Client-side TLE caching
  - Database: `"leo-live"`
  - Object store: `"tle"`

### No Evidence Of
- CesiumJS, Globe.gl, or react-globe.gl (custom Three.js implementation instead)
- Redux, Zustand, Jotai, or Recoil (React hooks-based state management)
- SGP4/SDP4 library visible in bundle (orbital propagation likely custom or bundled)

---

## 2. CSS Design Patterns

### Design Language: "Dark Mission Control"
- **Background:** `#04060a` (near-black with blue tint)
- **Clear color:** `0x263690` (deep space blue)
- **Color palette:**
  - Primary accent: `#38bdf8` (sky-400, orbital ring in favicon)
  - Secondary: `#2563eb` (blue-600, globe dot in favicon)
  - Text primary: `text-white`, `text-slate-100`
  - Text secondary: `text-slate-500`
  - Data labels: `#9aa7bd` (slate-400)
  - Borders: `border-white/[0.07]` (subtle glass borders)
  - Backgrounds: `bg-white/[0.03]` (frosted glass panels)

### Typography
- **Monospace throughout** — `font-mono` for all data display
- **Uppercase labels** with wide letter-spacing:
  - `text-[10px] uppercase tracking-[0.25em]` (group labels)
  - `text-[9px] uppercase tracking-[0.18em]` (data field labels)
  - `text-[11px]` (NORAD IDs)
  - `text-[13px] tabular-nums` (numeric data values)
  - `text-base font-semibold tracking-wide` (satellite names)

### Layout & Spacing
- **Responsive side panel:**
  - Mobile: `inset-x-3 bottom-[92px] max-h-[46vh] overflow-y-auto` (bottom sheet)
  - Desktop: `right-7 top-1/2 w-[300px] -translate-y-1/2` (right sidebar, centered)
- **Grid layouts:** `grid grid-cols-2 gap-1.5` for data cards
- **Glass morphism:** `rounded-lg border border-white/[0.07] bg-white/[0.03] px-2.5 py-2`

### Visual Effects
- **Frosted glass panels** with transparent backgrounds
- **Subtle borders** at 7% white opacity
- **Bloom/glow** via UnrealBloomPass on 3D scene
- **Atmosphere shader** with Fresnel-based intensity falloff
- **Auto-rotating globe** with damping for smooth interaction

---

## 3. Data Sources & Satellite Tracking

### TLE Data Source
- **Primary source:** CelesTrak (inferred from TLE format parsing)
- **TLE validation:** Checks for lines starting with `"1 "` and `"2 "` (standard TLE format)
- **Data format:** Standard NORAD Two-Line Element sets
- **Epoch tracking:** Median epoch time calculated across all satellites

### Data Architecture
```
Satellite Object:
  - group: number (index into `ra` group array)
  - epochMs: number (epoch timestamp in milliseconds)
  - name: string (satellite name)
  - norad: string (NORAD catalog ID)

Satellite Collection (bw function):
  - sats: Satellite[] (full array)
  - counts: number[] (per-group counts, ra.length groups)
  - epochMs: number (median epoch)
  - source: string (data source identifier)
  - fetchedAt: number (fetch timestamp)
  - total: number (total satellite count)
```

### Caching Strategy
- **IndexedDB** database `"leo-live"` with `"tle"` object store
- **Purpose:** Cache TLE data to reduce API calls
- **Offline support:** Data persists between sessions

### Satellite Groups
- Groups tracked via `ra` array (group definitions with labels and colors)
- Each satellite assigned to a group index
- Group counts maintained in real-time
- Group labels displayed with color coding (`d?.color ?? "#9aa7bd"`)

### Data Processing Functions
- `bw(sats, source, fetchedAt)` — Builds satellite collection with group counts
- `mS(timestamp)` — Formats UTC timestamp: `"YYYY-MM-DD HH:MM:SS UTC"`
- `Ew(timestamp)` — Formats time only: `"HH:MM:SS"`
- `Tw(timestamp)` — Formats date only: `"YYYY-MM-DD UTC"`

---

## 4. 3D Globe Rendering Architecture

### Earth Rendering
```javascript
// Earth sphere with day/night textures
SphereGeometry(1, 96, 96)  // radius=1, 96 segments
rotateX(Math.PI/2)          // Align poles

// Custom ShaderMaterial uniforms:
  uDay: Texture     // earth-day.jpg (sRGB color space)
  uNight: Texture   // earth-night.jpg (sRGB color space)
  uSunDir: Vector3  // Sun direction (1,0,0)

// Atmosphere shell (slightly larger sphere)
SphereGeometry(1.09, 64, 64)  // radius=1.09
AdditiveBlending, DoubleSide, transparent, no depth write
```

### Atmosphere Shader (GLSL)
```glsl
varying vec3 vN;
void main() {
  float intensity = pow(max(0.60 - dot(normalize(vN), vec3(0.0, 0.0, 1.0)), 0.0), 4.5);
  gl_FragColor = vec4(0.30, 0.55, 1.05, 1.0) * intensity * 1.6;
}
```
- Fresnel-based rim glow effect
- Blue tint: `(0.30, 0.55, 1.05)` multiplied by 1.6
- Power 4.5 for sharp falloff

### Post-Processing Pipeline
- **EffectComposer** with render passes
- **UnrealBloomPass** — Multi-mip bloom (5 mip levels)
  - Bright pass extraction
  - Gaussian blur at multiple resolutions
  - Additive blending for glow
- **Render targets:** Float type for HDR

### Satellite Visualization
- **Points/Sprites** for satellite dots (canvas-drawn circle marker)
  - 96×96 canvas, white circle stroke (lineWidth=7)
  - Custom texture per satellite group (color-coded)
- **InstancedMesh** likely used for rendering thousands of satellites efficiently
- **Orbit paths:** Line geometry for past/future orbital arcs
- **Foot line:** Ground track visualization
- **Selection marker:** Highlighted satellite indicator

### Camera & Controls
- **Initial position:** `(1, -2.75, 1.35)` — Elevated 3/4 view
- **Up vector:** `(0, 0, 1)` — Z-up coordinate system
- **Auto-rotate:** 0.25 speed, can be toggled
- **Damping:** 0.08 factor for smooth deceleration
- **Distance limits:** 1.35 (close) to 30 (far)
- **View offset:** Applied for responsive layout

### Performance Optimizations
- **Quality cap:** `qualityCap=1.5` limits DPR
- **Adaptive DPR:** Reduces pixel ratio when FPS drops
- **Frame time tracking:** `frameTimes[]` array for performance monitoring
- **FPS window:** 1-second measurement windows
- **Hidden tab handling:** Pauses rendering when tab hidden
- **Context loss recovery:** Handles WebGL context loss gracefully
- **ResizeObserver:** Efficient resize handling

---

## 5. UI/UX Patterns

### Component Architecture (from source paths)
```
src/components/
  hud/
    DetailPanel.tsx     — Satellite detail overlay
    (likely others)
```

### HUD (Heads-Up Display) Pattern
- **Overlay UI** on top of 3D globe
- **Glass morphism panels** with subtle transparency
- **Non-intrusive** — doesn't block globe interaction
- **Responsive** — repositions for mobile/desktop

### Detail Panel
- **Position:** Right side (desktop) / Bottom sheet (mobile)
- **Content:**
  - Group label (uppercase, colored)
  - Satellite name (large, white, bold)
  - NORAD ID (small, muted)
  - Data grid (2 columns)
    - Field labels (9px uppercase)
    - Values (13px tabular-nums)
  - Close button (7×7 rounded, hover effects)

### Time Controls
```javascript
// useTime() hook — Custom time simulation
{
  getTime: () => number    // Current simulated time
  speed: number            // Playback speed multiplier
  playing: boolean         // Play/pause state
  setSpeed: (s) => void    // Change speed
  pause: () => void        // Pause simulation
  resume: () => void       // Resume simulation
  goNow: () => void        // Reset to real time
}
```
- **Real-time simulation** with adjustable speed
- **Play/pause** toggle
- **Speed control** (likely slider or buttons)
- **"Go to now"** button to sync with real time
- **Performance.now()** based for smooth timing

### Interaction Patterns
- **Click satellite** → Show detail panel
- **Hover satellite** → Highlight (hoverIdx tracking)
- **Follow mode** → Camera tracks selected satellite
- **Orbit toggle** → Show/hide orbital paths
- **Foot toggle** → Show/hide ground tracks
- **Group filters** → Show/hide satellite categories

### Responsive Design
- **Mobile:** Bottom bar (92px from bottom), bottom sheet for details
- **Desktop:** Right sidebar (300px wide), centered vertically
- **Canvas:** Full viewport with ResizeObserver

### Accessibility
- **ARIA labels** on interactive elements (`aria-label="Close"`)
- **Keyboard navigation** implied by semantic HTML
- **High contrast** white text on dark backgrounds

---

## 6. Source Code Structure (Reconstructed)

```
src/
  App.tsx                    — Main app with React Router
  main.tsx                   — Entry point
  components/
    hud/
      DetailPanel.tsx        — Satellite detail overlay
    globe/
      GlobeRenderer.tsx      — Three.js globe wrapper
    controls/
      TimeControl.tsx        — Playback controls
    filters/
      GroupToggle.tsx        — Satellite group filters
  hooks/
    useTime.ts               — Time simulation hook
    useSatData.ts            — Satellite data management
  utils/
    tle.ts                   — TLE parsing and validation
    propagator.ts            — Orbital propagation
    groups.ts                — Satellite group definitions
  shaders/
    earth.vert.glsl          — Earth vertex shader
    earth.frag.glsl          — Earth day/night fragment shader
    atmosphere.vert.glsl     — Atmosphere vertex shader
    atmosphere.frag.glsl     — Atmosphere fragment shader
  types/
    satellite.ts             — Satellite type definitions
```

---

## 7. Key Technical Insights

### Why Custom Three.js Instead of Globe.gl/Cesium?
- **Performance:** Direct control over rendering pipeline for thousands of satellites
- **Custom shaders:** Day/night Earth texture blending, atmosphere effects
- **Bloom effects:** UnrealBloomPass for satellite glow
- **Minimal overhead:** No unnecessary features from larger libraries
- **Bundle size:** Three.js tree-shakeable vs Cesium's large bundle

### TLE Data Flow
```
CelesTrak API
    ↓ fetch()
TLE Text (lines starting with "1 " and "2 ")
    ↓ parse
Satellite Objects {group, epochMs, name, norad}
    ↓ IndexedDB cache
    ↓ bw() aggregation
Satellite Collection {sats, counts, epochMs, source, fetchedAt, total}
    ↓ Three.js rendering
InstancedMesh / Points on globe
```

### Real-time Update Loop
1. Fetch TLE data (with IndexedDB caching)
2. Parse TLE → satellite objects
3. Propagate orbits to current simulated time
4. Update InstancedMesh positions
5. Render scene with bloom post-processing
6. requestAnimationFrame loop

---

## 8. Rebuild Recommendations

### Minimum Viable Stack
- **React 18** + **TypeScript**
- **Three.js** + **@react-three/fiber** + **@react-three/drei**
- **Tailwind CSS** v3
- **Vite** for build
- **satellite.js** (sgp4/sdp4 propagation)
- **IndexedDB** via idb library for caching

### Key Implementation Details
1. **Earth:** SphereGeometry with custom ShaderMaterial (day/night blend)
2. **Atmosphere:** Slightly larger sphere with Fresnel rim shader
3. **Satellites:** InstancedMesh with per-instance colors (group-coded)
4. **Orbits:** BufferGeometry lines updated per frame
5. **Post-processing:** UnrealBloomPass via @react-three/postprocessing
6. **UI:** Glass morphism panels with Tailwind utilities
7. **Data:** CelesTrak TLE API with IndexedDB offline cache
8. **Time:** Custom hook with performance.now() for smooth simulation

### CSS Variables to Match
```css
--background: #04060a;
--clear-color: #263690;
--accent-primary: #38bdf8;
--accent-secondary: #2563eb;
--text-primary: #f1f5f9;     /* slate-100 */
--text-secondary: #64748b;   /* slate-500 */
--text-muted: #9aa7bd;       /* slate-400 */
--border: rgba(255, 255, 255, 0.07);
--glass: rgba(255, 255, 255, 0.03);
```

---

## 9. External Dependencies (Inferred)

| Dependency | Purpose | Evidence |
|------------|---------|----------|
| React 18 | UI framework | Concurrent features, JSX runtime |
| React Router | Client routing | Route, useRoutes, useLocation |
| Three.js | 3D rendering | WebGLRenderer, ShaderMaterial, EffectComposer |
| Tailwind CSS | Styling | --tw-* variables, utility classes |
| Vite | Build tool | Module preload, asset hashing |
| satellite.js | TLE propagation | SGP4/SDP4 (likely bundled) |

---

## 10. Assets Required for Rebuild

```
public/
  textures/
    earth-day.jpg        — Blue Marble day texture (sRGB)
    earth-night.jpg      — City lights night texture (sRGB)
```

Note: The atmosphere and satellite markers are generated procedurally via shaders/canvas.

---

*Analysis based on reverse-engineering of minified bundle: `index-2YwmtxR8.js` (868KB) and `index-BGL6OXCx.css` (19KB)*
