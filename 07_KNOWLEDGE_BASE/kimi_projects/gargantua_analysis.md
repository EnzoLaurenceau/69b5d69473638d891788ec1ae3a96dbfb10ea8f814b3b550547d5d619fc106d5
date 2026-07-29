# GARGANTUA — Technical Deep-Dive Analysis

## Schwarzschild Black Hole Raytracer · Advanced WebGL/GLSL Reference

---

## 1. Architecture Overview

```
index.html          Single-page app, ES module entry
  ├── css/style.css     Spacecraft-terminal UI (glassmorphism, grid HUD)
  ├── js/shaders.js     GLSL source exports (ray + composite shaders)
  ├── js/main.js        Renderer, camera, audio, HUD, params, loop
  └── vendor/           Three.js + addons (importmap ES modules)
```

**Data flow:**
1. `index.html` defines the DOM skeleton: canvas `#view`, HUD `#hud`, params console `#params`, intro overlay `#intro`, fatal-error dialog `#fatal`
2. `js/main.js` imports Three.js via `<script type="importmap">` — no bundler, no CDN for core deps
3. A single fullscreen `ShaderMaterial` on a 2×2 plane renders the entire black hole scene via ray-marching in the fragment shader (`RAY_FRAG`)
4. `EffectComposer` runs: RenderPass → UnrealBloomPass → composite ShaderPass (ACES tonemap + vignette + CA + grain)
5. The observer `PerspectiveCamera` never renders geometry — it only supplies position/FOV uniforms to the ray shader
6. `OrbitControls` drives the camera for manual interaction; cinematic and preset-flight paths override it

**Key design principle:** The entire relativistic scene is procedural — no meshes, no textures, no loaders. Every pixel is computed from scratch via null-geodesic integration in a single fragment shader.

---

## 2. Three.js Setup

### 2.1 WebGLRenderer

```js
renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;  // linear pipe — ACES applied manually in composite
renderer.toneMapping = THREE.NoToneMapping;               // no built-in tonemap
```

- `antialias: false` — the ray-marched image is already high-res; MSAA would waste cycles on a fullscreen quad
- Linear color space throughout the pipeline; tone mapping deferred to the composite fragment shader

### 2.2 Half-Float Render Targets

```js
const rtType = halfFloatOK ? THREE.HalfFloatType : THREE.UnsignedByteType;
```

The renderer probes `EXT_color_buffer_float` / `EXT_color_buffer_half_float`. If unsupported, bloom is disabled and a toast warns the user. Half-float is essential for HDR bloom — values above 1.0 must survive the intermediate render targets.

### 2.3 EffectComposer Pipeline

```
RenderPass(fsScene, fsCam)      →  Fullscreen ray shader (HDR, linear)
  ↓
UnrealBloomPass(strength, radius, threshold)  →  Glow on bright pixels (accretion disk, photon ring)
  ↓
ShaderPass(COMPOSITE_FRAG)     →  ACES tonemap + chromatic aberration + vignette + film grain
```

- `fsScene` / `fsCam`: dedicated orthographic scene with a single 2×2 plane — the ray shader never interacts with the main Three.js scene graph
- Bloom is disabled for debug modes 3–9 (raw pass inspection)
- `resize()` applies a **pixel budget** per quality profile (1.4M / 2.4M / 3.8M pixels) by capping DPR

### 2.4 Shader Error Handling

```js
renderer.debug.onShaderError = (gl, program, vs, fs) => { ... fatal('SHADER FAULT', ...) };
```

A custom `onShaderError` callback catches GLSL compile/link failures and surfaces them in the fatal dialog rather than silently failing.

---

## 3. GLSL Shader Techniques

All physics code lives in `js/shaders.js`. Two shader pairs are exported:
- `RAY_VERT` / `RAY_FRAG` — the fullscreen ray-marching pass
- `COMPOSITE_VERT` / `COMPOSITE_FRAG` — the post-processing pass

### 3.1 Schwarzschild Geodesic Raytracing (Null-Geodesic Integration)

**The core physics loop** (lines 235–285 of RAY_FRAG):

```glsl
for(int i=0;i<600;i++){
    if(i >= uSteps) break;
    float r = length(pos);
    if(r < 1.03*RS){ trans = 0.0; break; }           // event horizon capture
    if(r > 45.0 && dot(pos,vel) > 0.0){ break; }     // escaped to infinity

    float dt = max(0.012, r*mix(0.02, 0.06, smoothstep(6.0, 20.0, r)));
    // ...
    vel = normalize(vel + accAt(pos, vel)*dt);         // geodesic deflection
    pos = pos + vel*dt;                                // position advance
}
```

**Key insight:** In the Schwarzschild metric (c = G = 1, Rs = 1), null geodesics (light rays) experience an effective radial acceleration:

```glsl
vec3 accAt(vec3 p, vec3 v){
    vec3 h = cross(p, v);                           // angular momentum vector
    float r2 = dot(p, p);
    return -1.5 * RS * dot(h,h) / (r2*r2*sqrt(r2)) * p;  // radial inward pull
}
```

This is the **post-Newtonian approximation** of the Schwarzschild null-geodesic equation. The `1.5 * RS * L² / r³` term creates the famous light-bending effect. The cross product `h = p × v` gives the conserved angular momentum direction, and `dot(h,h)` gives L².

**Adaptive step sizing:** `dt` scales with radius — small steps near the black hole (where curvature is extreme), larger steps far away. The `smoothstep(6.0, 20.0, r)` interpolation smoothly transitions step sizes.

### 3.2 RK2 Refinement Near the Event Horizon

For `r < 4.4` (near the photon sphere at r = 1.5 Rs), the shader switches to a **2-step midpoint method (RK2)**:

```glsl
if(r < 4.4){
    float hdt = dt*0.5;
    for(int s = 0; s < 2; s++){
        vec3 k1 = accAt(pos, vel);
        vec3 pm = pos + vel*(hdt*0.5);
        vec3 vm = normalize(vel + k1*(hdt*0.5));
        vec3 k2 = accAt(pm, vm);
        vec3 pn = pos + vm*hdt;
        vel = normalize(vel + k2*hdt);
        // disk crossing test at each substep
        if(diskCross(pos, pn, vel, ...)){ absorbed = true; }
        pos = pn;
    }
}
```

This gives O(dt²) accuracy where it matters most — near the photon ring where rays make tight spirals. The total step budget (`uSteps`) is unchanged; each near-horizon step is simply subdivided.

### 3.3 Accretion Disk Rendering

The disk is a **thin equatorial plane** intersected by ray-segment tests:

```glsl
bool diskCross(vec3 a, vec3 b, ...){
    if(a.y*b.y > 0.0) return false;        // same side of plane → no crossing
    float t = abs(a.y)/(abs(a.y) + abs(b.y) + 1e-5);  // linear interpolation factor
    vec3 q = mix(a, b, t);                  // crossing point
    float qr = length(q.xz);               // radial distance from center
    if(qr <= uDin || qr >= uDout) return false;  // outside disk annulus
```

Multiple crossings are supported — rays can pass through the disk multiple times (front and back of the accretion disk), accumulating color via **front-to-back alpha compositing**:

```glsl
col += trans * alpha * dcol;    // additive contribution weighted by remaining transparency
trans *= 1.0 - alpha;           // reduce transparency
if(trans < 0.02){ trans = 0.0; return true; }  // early-out when opaque
```

### 3.4 Novikov-Thorne Flux Model

The disk brightness follows the **Novikov-Thorne thin disk** model with ISCO at 3 Rs:

```glsl
float x = max(qr, 3.001);
float flux = max(pow(x/3.0, -3.0) * (1.0 - sqrt(3.0/x)), 0.0);
float temp = pow(flux*10.0, 0.25);   // T ∝ F^(1/4) Stefan-Boltzmann
```

This gives the characteristic brightness profile: peaked near ISCO, falling off as r⁻³ outward.

### 3.5 Disk Turbulence (FBM Noise)

The disk texture is entirely procedural using **5-octave value-noise FBM**:

```glsl
float fbm(vec3 p){
    float v = 0.0; float a = 0.5;
    for(int i=0;i<5;i++){
        v += a*vnoise(p);
        p = p*2.03 + 11.3;   // non-integer frequency ratio prevents periodicity
        a *= 0.5;
    }
    return v;
}
```

**Layered turbulence composition:**
1. **Domain-warped turbulence:** `fbm(pc*2.0 + warp*1.5)` where `warp` is a 3-channel FBM offset
2. **Inner detail mask:** `1.0 - smoothstep(4.0, 18.0, qr)` — turbulence is strong near ISCO, smooth far out
3. **22× streaks:** `fbm(vec3(rp.x*22.0, rp.y*22.0, qr*1.4))` — high-frequency azimuthal streaks in the inner disk
4. **Lane mask:** Another FBM layer modulating brightness in lanes
5. **Radial gain:** Inner disk gets a 1.0 multiplier, outer fades to 0.38

The disk pattern is **rotated over time** using a precomputed rotation matrix (never using atan-sampled polar coords, which would cause seam artifacts):

```glsl
float omega = uRotSign * 1.1 * uRotSpeed * pow(3.0/qr, 1.5);  // Keplerian ω ∝ r^(-3/2)
float rot = omega * uTime;
float ca = cos(rot), sa = sin(rot);
vec3 qp = vec3(ca*q.x + sa*q.z, 0.0, -sa*q.x + ca*q.z);  // rotate in xz plane
```

### 3.6 Doppler Shift & Gravitational Redshift

**Relativistic beaming** from the orbital motion of disk material:

```glsl
float beta = sqrt(0.5/qr);                              // v/c ≈ √(GM/2r)
float gamma = 1.0/sqrt(max(1.0 - beta*beta, 1e-4));    // Lorentz factor
vec3 tdir = normalize(vec3(-sin(ang), 0.0, cos(ang))) * uRotSign;  // tangential velocity direction
float dop = 1.0/(gamma*(1.0 - dot(tdir*beta, rayDir))); // special-relativistic Doppler
dop = clamp(dop, 0.50, uDopMax);                        // capped to prevent blowout
```

**Gravitational redshift** (time dilation at radius r):

```glsl
float g = sqrt(max(1.0 - RS/qr, 0.0));   // √(1 - Rs/r)
```

Both are applied to the blackbody temperature and final intensity:

```glsl
vec3 dcol = blackbody(temp*dop*g) * I * (dop*dop*dop) * g * uDiskBright;
//                         ^^^^                ^^^^^^^
//                   color shift          intensity beaming ∝ δ³
```

The `dop³` factor comes from relativistic aberration + Doppler boosting combined.

### 3.7 Pseudo-Blackbody Coloring

```glsl
vec3 blackbody(float t){
    vec3 c = mix(vec3(0.55,0.06,0.01), vec3(1.00,0.42,0.10), smoothstep(0.00,0.55,t));  // deep red → orange
    c = mix(c, vec3(1.00,0.86,0.55), smoothstep(0.50,1.05,t));   // orange → white-yellow
    c = mix(c, vec3(0.85,0.92,1.25), smoothstep(1.05,1.90,t));   // white → blue-white (hot)
    return c;
}
```

A 3-segment piecewise approximation of Planck's law. The blue channel exceeds 1.0 at the hottest end (1.25), relying on HDR bloom to spread the glow.

### 3.8 Volumetric Halo

A thin volumetric glow hugs the disk plane:

```glsl
float absY = abs(pos.y);
if(absY < 0.45 && r > uDin && r < uDout){
    float dens = exp(-absY*30.0)*0.03*(1.0 - smoothstep(10.0, uDout-1.0, r));
    // Novikov-Thorne flux for glow color
    haloCol += trans * glowc * (fluxh*3.5) * dens * dt * uDiskBright;
}
```

This gives the disk a soft atmospheric glow that fades with distance from the plane. The `exp(-absY*30.0)` creates an extremely thin shell (σ ≈ 0.033 Rs).

### 3.9 Photon Ring

A synthetic bright ring at the photon sphere:

```glsl
vec3 ringAdd = vec3(1.0,0.92,0.80) * exp(-pow((minR-1.55)*4.0, 2.0)) * 0.05;
```

Where `minR` is the closest approach of the ray. Rays that graze r ≈ 1.55 Rs (the photon sphere) get a bright additive contribution. The Gaussian width (σ = 0.25) and low intensity (0.05) let bloom amplify it.

### 3.10 Star Field & Background

**Three procedural layers + hero stars + Milky Way:**

```glsl
vec3 background(vec3 d){
    vec3 col = uSkyFloor * vec3(0.10,0.13,0.28);   // faint sky floor
    col += milkyway(d);                              // band of FBM clouds
    col += starLayer(d,  26.0, 0.952, ...);          // dense faint stars
    col += starLayer(d,  47.0, 0.952, ...);          // medium density
    col += starLayer(d,  83.0, 0.952, ...);          // sparse
    col += starLayer(d, 150.0, 0.968, ...);          // very sparse bright
    col += heroStars(d);                              // rare bright point stars
    return col * uStarBright;
}
```

Each `starLayer` uses a 3D hash to place stars on a grid, with per-cell randomized position (`hash3`), brightness (`hash1`), and tint (warm/cool). The sharpness parameter controls star size. `heroStars` adds rare double-glow stars (wide + tight Gaussian).

The **Milky Way** band uses two FBM octaves modulated by a Gaussian falloff from a tilted plane normal `n = normalize(0.25, 1.0, 0.15)`.

### 3.11 Composite Shader (Post-Processing)

```glsl
// 1. Chromatic aberration — radial, R/B symmetric
float ca = uCA * dot(dir, dir);
col.r = texture2D(tDiffuse, uv + dir*ca).r;
col.b = texture2D(tDiffuse, uv - dir*ca).b;

// 2. ACES tonemap (manual, since renderer toneMapping is OFF)
col = aces(col);  // clamp((x*(2.51x+0.03))/(x*(2.43x+0.59)+0.14))

// 3. Aspect-aware vignette
float vig = smoothstep(1.30, 0.30, length(dir*vec2(aspect,1.0))*1.15);

// 4. Animated film grain
float g = ghash(gl_FragCoord.xy + fract(uTime*13.7)*97.0) - 0.5;
col += g * uGrain * (1.0 - 0.5*col);   // grain reduced in bright areas
```

### 3.12 Debug Visualization Modes

Modes 1–9 provide diagnostic views:
| Mode | Visualization |
|------|---------------|
| 0 | Normal render |
| 1 | Disk + halo only |
| 2 | Lensed background only |
| 3 | Step usage heatmap (grey) |
| 4 | First-crossing radius map (viridis-like) |
| 5 | Raw turbulence value |
| 6 | minR (red) / crossing count (green) |
| 7 | Valid crossing count (blue→green→red) |
| 8 | Three-phase sine of first crossing angle |
| 9 | Crossing-radius bands |

---

## 4. Cinematic Camera System

### 4.1 Keyframe Path

8 keyframes define a closed loop in **spherical coordinates** (radius, inclination°, azimuth°):

```js
const CINE_KEYS = [
  [58, 12, -30], [36, 6, 10], [26, 24, 55], [14, 14, 100],
  [20, 52, 150], [34, 80, 200], [46, 35, 270], [36, 8, 330],
];
```

### 4.2 Catmull-Rom Spline Interpolation

```js
function cr(p0, p1, p2, p3, t){
    const t2 = t*t, t3 = t2*t;
    return 0.5*((2*p1) + (-p0+p2)*t + (2*p0-5*p1+4*p2-p3)*t2 + (-p0+3*p1-3*p2+p3)*t3);
}
```

Standard Catmull-Rom centripetal spline — C1 continuous, passes through all control points. Each coordinate (r, inclination, azimuth) is interpolated independently with wrapping indices for the closed loop.

**Azimuth unwrapping** prevents discontinuity at 0°/360°:

```js
const az = k => K_A[wrapIdx(k, n)] + 2*Math.PI*Math.floor(k/n);
```

### 4.3 Preset Flight Transitions

Presets (`poster`, `edge`, `polar`, `close`) use **cubic ease-in-out** with `lerpVectors`:

```js
S.flight = { t: 0, dur: 2.6, from: camera.position.clone(), to: presetVec(name) };
// in frame():
camera.position.lerpVectors(f.from, f.to, easeCubic(Math.min(1, f.t/f.dur)));
```

OrbitControls momentum is purged once at flight start to prevent drift.

### 4.4 Cinema Blend-In

When entering cinematic mode, the camera smoothly blends from its current position to the path:

```js
S.cineBlend = 0;  // starts at current position
// in frame():
S.cineBlend = Math.min(1, S.cineBlend + dt/2);  // 2-second blend
_v1.lerpVectors(S.cineFrom, _v1, easeCubic(S.cineBlend));
```

### 4.5 Manual Takeover

A capture-phase event listener on `pointerdown` and `wheel` fires **before** OrbitControls, canceling any active cinema/flight and handing control to the user at the interpolated position.

---

## 5. HUD/UI Design Patterns

### 5.1 Layout Structure

The HUD is a fixed overlay (`pointer-events: none`) with:
- **Corner brackets** — 4 decorative L-shaped borders with flicker animation
- **Title block** — top-left: "GARGANTUA" + subtitle + tag line
- **Mission clock** — top-right: elapsed time since page load
- **Telemetry** — bottom-left: observer distance, inclination, steps, profile, FPS
- **Flight deck** — bottom-right: control buttons (pointer-events: auto)
- **Toast** — center-top: transient notifications (amber border)
- **Hint bar** — bottom-center: keyboard shortcuts

### 5.2 Button Grid System

```html
<div class="grid2">  <!-- 2-column: view presets -->
<div class="grid4">  <!-- 4-column: utility buttons -->
```

CSS grid with `gap: 6px` for tight spacecraft-panel alignment.

### 5.3 State-Driven Button Updates

`updateDeck()` syncs all button states (active class, aria-pressed, text content) from the `S` state object. Every toggle calls `updateDeck()`.

---

## 6. Quality Profiles System

### 6.1 Three Profiles

```js
const QUALITY = {
    standard:  { label: 'STANDARD',  steps: 200, dpr: 1.0 },
    high:      { label: 'HIGH',      steps: 320, dpr: 1.5 },
    cinematic: { label: 'CINEMATIC', steps: 460, dpr: 2.0 },
};
```

### 6.2 Pixel Budget Enforcement

Each profile has a maximum pixel count:

```js
const PIXEL_BUDGET = { standard: 1.4e6, high: 2.4e6, cinematic: 3.8e6 };
```

`resize()` computes: `dpr = min(deviceDPR, profileDPR, √(budget/(w×h)))`, clamped to ≥ 0.65.

### 6.3 Quality Cycling

The quality button cycles through `standard → high → cinematic → standard`. Setting quality always overrides the step count from the profile (clearing any URL `steps` override).

### 6.4 Fatal Error Recovery

On shader crash or context loss, the "LOWER QUALITY" button navigates to the next lower profile via `?q=standard` (or `?q=high` from cinematic).

---

## 7. Audio System

### 7.1 Format Selection

```js
if(can('audio/ogg; codecs="opus"')) src = 'audio/gargantua-main.opus';
else if(can('audio/mpeg')) src = 'audio/gargantua-main.mp3';
else if(can('audio/ogg; codecs="vorbis"')) src = 'audio/gargantua-main.ogg';
```

Probes `canPlayType()` to select the best available format (opus > mp3 > vorbis).

### 7.2 Two-Track System

- **Intro track** (`audioIntro`): plays during the intro overlay
- **Main loop** (`audioMain`): loops for the duration of the experience

When the intro ends, the main track is seeked to the cinema phase and starts with a fade-in.

### 7.3 Cinema Audio Sync

```js
function syncAudioToCine(){
    const want = S.cineTime % LOOP_SECONDS;
    if(Math.abs(audioMain.currentTime - want) > 0.3) audioMain.currentTime = want;
}
```

Audio is periodically synced to the cinematic camera time. The main track duration (176s) matches 2× the 88-second camera loop.

### 7.4 Fade Control

`fadeMainTo(target, seconds)` uses `setInterval(50ms)` to smoothly ramp volume — used for fade-in on play.

### 7.5 Blocked Audio Handling

If `play()` throws or fires an error event, the button shows "⚠ SOUND: BLOCKED" and sound state resets. This handles browsers that block autoplay.

---

## 8. Parameter Console

### 8.1 Parameter Definitions

21 parameters with `{key, label, min, max, step, def, fmt}`:

| Category | Parameters |
|----------|-----------|
| Physics | uSteps, uDin, uDout, uDopMax, uOpNear, uOpFar |
| Visual | uDiskBright, uStarBright, uSkyFloor, uRotSpeed |
| Post-processing | bloomStrength, bloomRadius, bloomThreshold, vignette, grain, ca |
| Camera | fov, maxDistance, orbitSpeed, cineSegment |
| Debug | debug (0–9) |

### 8.2 localStorage Persistence

```js
const STORE_KEY = 'gargantua.params.v1';
// Load: parse JSON, clamp each value to [min, max], skip non-finite
// Save: serialize all non-URL-overridden params
```

URL overrides (`?steps=N`, `?debug=N`) take priority over localStorage and are excluded from saves via the `S.overrides` Set.

### 8.3 Dynamic UI Generation

`buildParams()` creates one `<div class="prow">` per parameter with a label, value display, and range slider. Input events update `S.params`, call `applyParam()`, and persist to localStorage.

### 8.4 Reset

`resetParams()` clears localStorage, resets all values to `PARAM_DEFS.def`, re-applies quality profile step count, but preserves any URL overrides active for this run.

---

## 9. CSS Design Patterns

### 9.1 Glassmorphism

```css
.deck {
    background: linear-gradient(135deg, rgba(6,18,32,.82), rgba(4,10,20,.72));
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    border: 1px solid var(--cyan-hair);  /* rgba(127,220,255,.28) */
}
```

Semi-transparent dark gradient + blur + hairline border = the spacecraft-panel look. Used on `.deck` and `#params`.

### 9.2 Color System

```css
--cyan: #7fdcff;          /* primary accent — links, borders, active glow */
--cyan-dim: rgba(127,220,255,.45);  /* secondary text */
--cyan-hair: rgba(127,220,255,.28); /* borders */
--amber: #ffb454;         /* alerts, active states, subtitles */
--white: #eafaff;         /* primary text (not pure white — slight cyan tint) */
```

### 9.3 Typography

All monospace: `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace`. Extremely tight tracking (`letter-spacing: .14em–.5em`), all-uppercase, small sizes (8.5–11px). Evokes a terminal/avionics display.

### 9.4 Post-Processing Overlay (#fx)

```css
#fx {
    background:
        repeating-linear-gradient(0deg, rgba(255,255,255,.025) 0px, ... 1px, transparent 1px, transparent 3px),
        radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,.55) 100%);
    mix-blend-mode: screen;
    opacity: .6;
}
```

Simulates CRT scanlines + a CSS vignette. Uses `mix-blend-mode: screen` to only lighten (never darken).

### 9.5 Animations

- **Corner flicker** (`cornerFlick`): 6-second step-end keyframe with subtle opacity drops — simulates instrument flicker
- **Intro card** (`introCard`): 5.2-second blur → reveal → fade sequence
- **`prefers-reduced-motion`**: Disables corner flicker, simplifies intro to opacity-only, speeds up transitions

### 9.6 Responsive Breakpoints

- `@media (max-width: 900px)`: Hides hint bar
- `@media (max-width: 720px)`: Shrinks corners, reduces all font sizes, narrows telemetry label width, enlarges touch targets to 40px min-height

### 9.7 Custom Scrollbar

```css
#params { scrollbar-width: thin; scrollbar-color: rgba(127,220,255,.35) transparent; }
#params::-webkit-scrollbar-thumb { background: rgba(127,220,255,.35); }
```

### 9.8 Range Slider Styling

Custom `-webkit-slider-thumb` (cyan circle with glow shadow) and `-moz-range-thumb` for cross-browser consistency. Track is a thin cyan hairline.

---

## 10. Key JavaScript Patterns

### 10.1 State Management

A single global `S` object holds all mutable state:

```js
const S = {
    params: {},           // current parameter values
    quality: 'cinematic', // active quality profile
    cineMode: false,      // cinematic camera active
    cineTime: 0,          // position along cinema path
    flight: null,         // active preset flight {t, dur, from, to}
    soundOn: false,       // audio toggle
    hudVisible: true,     // HUD visibility
    overrides: new Set(), // URL-overridden keys (excluded from localStorage save)
    // ... frame counters, FPS smoothing, error flags
};
```

No framework, no reactive system — just direct mutation and explicit `updateDeck()` / `applyParam()` calls.

### 10.2 URL Parameter System

```js
const qs = new URLSearchParams(location.search);
```

Supported URL params:
| Param | Effect |
|-------|--------|
| `?q=standard\|high\|cinematic` | Quality profile |
| `?steps=N` | Override geodesic steps (60–600) |
| `?debug=0..9` | Debug visualization mode |
| `?cam=poster\|edge\|polar\|close` | Jump to preset camera (disables cinema) |
| `?ctime=N` | Start cinema at N seconds |
| `?nocine` | Disable auto-cinema |
| `?shot` | Shot mode (4 frames then freeze) |
| `?capture=canvas` | Enable canvas readback in shot mode |

### 10.3 Reduced-Motion Support

```js
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// ...
const wantCine = !qs.has('nocine') && !reducedMotion && !qs.has('cam');
```

When `prefers-reduced-motion` is active:
- Cinema is disabled by default
- Auto-rotate is off
- CSS animations are simplified
- Transitions are shortened

### 10.4 Render Loop Architecture

```js
function frame(){
    const now = performance.now();
    const realDelta = (now - lastNow)/1000;   // wall clock for FPS
    const dt = Math.min(realDelta, 0.1);       // clamped sim delta

    // Camera priority: flight > cinema > OrbitControls
    // Update uniforms (cheap scalar/vector writes)
    // composer.render()
    // First frame → dismiss intro
    // Shot mode → 4 frames then freeze
    // FPS: 1-second window + EMA smoothing (0.6/0.4)
    // HUD: 4 Hz update rate
    // Visibility API: pause when hidden, resume with gap discard
    rafId = requestAnimationFrame(frame);
}
```

### 10.5 Visibility API Integration

```js
document.addEventListener('visibilitychange', () => {
    if(document.hidden){ cancelAnimationFrame(rafId); rafId = 0; }
    else{ lastNow = performance.now(); rafId = requestAnimationFrame(frame); }
});
```

Pauses the render loop when the tab is hidden (saves GPU/battery), discards the time gap on resume to prevent a huge dt spike.

### 10.6 WebGL Context Loss Handling

```js
canvas.addEventListener('webglcontextlost', e => {
    e.preventDefault();  // allow restoration
    contextLost = true;
    cancelAnimationFrame(rafId);
    fatal('SIGNAL LOST', 'WebGL context lost...');
});
canvas.addEventListener('webglcontextrestored', () => location.reload());
```

### 10.7 Shot Mode (Automated Capture)

When `?shot` is in the URL:
1. Intro is skipped
2. Renders exactly 4 frames (to let bloom stabilize)
3. Frame 3: optionally captures canvas to `window.__SHOT_PNG` (base64 PNG)
4. Sets `document.title = 'SHOT_OK'` and `window.__SHOT_DONE = true` as signals
5. Stops the render loop

This is designed for automated screenshot harnesses (Puppeteer/Playwright).

### 10.8 Introspection Handle

```js
window.__G = { S, uniforms, camera, controls, QUALITY, ...toggleFns };
```

Exposes the internal state for automated testing/harness use.

---

## Appendix: Uniform Reference

### Ray Shader Uniforms

| Uniform | Type | Description |
|---------|------|-------------|
| `uRes` | vec2 | Drawing buffer resolution (pixels) |
| `uTime` | float | Simulation time (seconds) |
| `uCamPos` | vec3 | Observer camera position |
| `uCamTarget` | vec3 | Look-at target (always origin) |
| `uFov` | float | `1/tan(fov/2)` — focal length |
| `uSteps` | int | Max geodesic integration steps |
| `uRotSign` | float | Disk rotation direction (+1/-1) |
| `uDebug` | int | Debug mode (0=normal, 1-9=diagnostic) |
| `uDin` | float | Disk inner edge (Rs units) |
| `uDout` | float | Disk outer edge (Rs units) |
| `uDopMax` | float | Doppler boost cap |
| `uOpNear` | float | Near-edge opacity |
| `uOpFar` | float | Far-edge opacity |
| `uDiskBright` | float | Disk brightness multiplier |
| `uStarBright` | float | Star field brightness multiplier |
| `uSkyFloor` | float | Minimum sky brightness |
| `uRotSpeed` | float | Disk rotation speed multiplier |

### Composite Shader Uniforms

| Uniform | Type | Description |
|---------|------|-------------|
| `tDiffuse` | sampler2D | Input texture from bloom pass |
| `uRes` | vec2 | Resolution |
| `uTime` | float | For animated grain |
| `uVignette` | float | Vignette intensity |
| `uGrain` | float | Film grain intensity |
| `uCA` | float | Chromatic aberration magnitude |

---

## Appendix: Physics Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `RS` | 1.0 | Schwarzschild radius (normalized) |
| ISCO | 3.0 Rs | Innermost Stable Circular Orbit |
| Photon sphere | 1.5 Rs | Unstable circular photon orbit |
| Event horizon | 1.0 Rs | Point of no return |
| Escape check | r > 45.0 | Ray considered escaped |
| Horizon capture | r < 1.03 Rs | Ray absorbed by black hole |

---

*Analysis covers all source files: `index.html` (101 lines), `css/style.css` (463 lines), `js/main.js` (893 lines), `js/shaders.js` (388 lines). Total: 1,845 lines of hand-written code.*
