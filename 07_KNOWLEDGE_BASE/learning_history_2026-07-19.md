# HISTORIQUE D'APPRENTISSAGE — Projets Kimi + Cybersecurity
# Date: 2026-07-19
# Source: 2 projets Kimi + 1 repo GitHub

════════════════════════════════════════════════════════════════════
 PROJET 1: GARGANTUA — Schwarzschild Black Hole Raytracer
════════════════════════════════════════════════════════════════════

## Architecture
- Single-page ES module app, NO bundler
- importmap pour Three.js (pas de node_modules)
- Three.js WebGLRenderer + EffectComposer pipeline
- Fullscreen ray-marching avec géodésiques nulles

## Techniques GLSL Apprises

### 1. Raytracing Relativiste (Null-Geodesic Integration)
- Intégration numérique des géodésiques nulles dans la métrique de Schwarzschild
- Accélération: a = -(3/2) * Rs * L² / r⁴ (force effective gravitationnelle)
- RK2 refinement près de la sphère des photons (r < 3 RS)
- Pas adaptatif: plus de pas près du trou noir

### 2. Disque d'Accrétion
- Modèle de flux Novikov-Thorne: F(r) ∝ r^(-3/4) * (1 - sqrt(Rin/r))^(-1/4)
- Compositing alpha front-to-back pour les traversées du disque
- Rotation képlérienne avec turbulence FBM (domain warping)
- Doppler shift: δ = 1 / (γ(1 - β·cosθ)) * (1/√(1-2M/r))
- Gravitational redshift: √(1 - 2M/r)
- Coloration blackbody pseudo-physique

### 3. Étoiles Procédurales
- 4 couches: étoiles ponctuelles, nébuleuses, voie lactée, sky floor
- FBM à 5 octaves pour la voie lactée
- Hash spatial 3D pour les étoiles

### 4. Post-Processing
- UnrealBloomPass pour le glow du disque
- ACES tonemapping dans le composite shader
- Chromatic aberration (R/G/B offset radial)
- Vignette (distance au centre)
- Film grain (noise temporel)

### 5. Caméra Cinématique
- Catmull-Rom splines sur 8 keyframes sphériques
- Easing cubique pour les presets
- Blend-in de 2 secondes
- Capture-phase manual takeover (pointerdown/wheel)

### 6. HUD Design
- Spacecraft-panel layout avec corner brackets
- Telemetry: distance, inclination, geodesic steps, FPS
- Grid-based button deck
- Toast notifications
- Glassmorphism (backdrop-filter: blur + semi-transparent gradient)

### 7. Système de Qualité
- Standard: 200 steps, DPR 1.0
- High: 320 steps, DPR 1.5
- Cinematic: 460 steps, DPR 2.0
- Pixel budget par profil (1.4M–3.8M pixels)

### 8. Audio
- Format probing: opus > mp3 > ogg
- Two-track intro + loop
- Cinema time sync
- Autoplay-blocked handling

════════════════════════════════════════════════════════════════════
 PROJET 2: ORBIT VEIL — Real-time Satellite Tracker
════════════════════════════════════════════════════════════════════

## Architecture
- React 18 + Vite (bundled)
- Three.js pour le globe 3D
- SGP4 orbital propagation (satellite.js)
- IndexedDB pour le cache TLE

## Techniques Apprises

### 1. Globe 3D avec Three.js
- Custom WebGLRenderer (pas Globe.gl ni Cesium)
- Earth avec day/night texture blending via custom shaders
- Atmosphère Fresnel-based rim glow
- UnrealBloomPass pour le glow des satellites
- InstancedMesh pour des milliers de satellites

### 2. Données Orbitales
- TLE (Two-Line Element) format de CelesTrak
- Groupes: active, visual, stations, GPS, Galileo, Starlink, OneWeb, debris
- SGP4 propagation pour calculer les positions en temps réel
- Cache IndexedDB pour offline support

### 3. UI/UX Patterns
- Dark "Mission Control" theme (#04060a)
- Glass morphism panels
- Monospace typography, uppercase labels
- Responsive: bottom sheet mobile, right sidebar desktop
- Color palette: sky-400 (#38bdf8) accent

### 4. Performance
- Adaptive DPR
- FPS monitoring
- WebGL context loss handling
- InstancedMesh pour le rendu de masse

### 5. Time Simulation
- Play/pause/speed control
- Go-to-now button
- Time multiplier: -240x to +240x

════════════════════════════════════════════════════════════════════
 REPO: Anthropic Cybersecurity Skills (817 skills)
════════════════════════════════════════════════════════════════════

## Structure
- 817 skills, 29 domaines, 6 frameworks
- Format: YAML frontmatter + Markdown body
- ~30 tokens pour scanner le frontmatter
- 500-2000 tokens pour charger complètement

## 6 Frameworks
1. MITRE ATT&CK v19.1: 15 tactics, 286 techniques
2. NIST CSF 2.0: 6 functions, 22 categories
3. MITRE ATLAS v5.4: 16 tactics, 84 techniques (AI/ML threats)
4. MITRE D3FEND v1.3: 7 categories, 267 techniques
5. NIST AI RMF 1.0: 4 functions, 72 subcategories
6. MITRE F3 v1.1: 8 tactics, 123 techniques (fraud)

## 29 Domaines de Sécurité
- Cloud Security (66), Threat Hunting (58), Threat Intelligence (52)
- Network Security (43), Web App Security (42), Digital Forensics (41)
- Malware Analysis (39), IAM (37), SOC Operations (35)
- Red Teaming (33), Container Security (33), Security Operations (28)
- OT/ICS Security (28), API Security (28), Incident Response (26)
- Vulnerability Management (25), Penetration Testing (21)
- DevSecOps (18), Zero Trust (17), Endpoint Security (17)
- Cryptography (16), Phishing Defense (15), AI Security (14)
- Mobile Security (13), Ransomware Defense (13)
- Compliance (9), Supply Chain (8), Deception (6), Hardware (4)

## Patterns d'Architecture pour les Skills
- Progressive disclosure: frontmatter → full body
- Step-by-step workflows
- Reference files pour le contexte technique
- Cross-framework mapping

════════════════════════════════════════════════════════════════════
 TECHNIQUES TRANSVERSALES APPLIQUÉES
════════════════════════════════════════════════════════════════════

## WebGL/Three.js
1. Importmap pour les modules ES (pas de bundler nécessaire)
2. EffectComposer pipeline: RenderPass → UnrealBloomPass → Custom composite
3. Fullscreen ray-marching avec shaders GLSL
4. InstancedMesh pour le rendu de masse
5. Half-float render targets pour la précision
6. ACES tonemapping dans les shaders custom

## GLSL
1. Null-geodesic raytracing (physique réelle)
2. FBM noise (5 octaves, domain warping)
3. Blackbody coloring
4. Fresnel rim glow
5. Chromatic aberration
6. Film grain

## UI/UX
1. Glassmorphism (backdrop-filter: blur)
2. HUD spacecraft-style avec corner brackets
3. Monospace typography pour les données
4. Color system: cyan/amber pour les highlights
5. Responsive: mobile bottom sheet, desktop sidebar

## Données
1. TLE format pour les satellites
2. SGP4 propagation
3. IndexedDB pour le cache
4. CelesTrak API pour les données en temps réel

## Performance
1. Adaptive DPR
2. Pixel budgets par qualité
3. WebGL context loss handling
4. Visibility API pause/resume

════════════════════════════════════════════════════════════════════
 FICHIERS CRÉÉS
════════════════════════════════════════════════════════════════════

- 07_KNOWLEDGE_BASE/cybersecurity_skills_forge.md (17KB)
- 07_KNOWLEDGE_BASE/kimi_projects/gargantua_analysis.md (27KB)
- 07_KNOWLEDGE_BASE/kimi_projects/orbit_veil_analysis.md (14KB)
- 07_KNOWLEDGE_BASE/kimi_projects/gargantua/ (projet complet)
- 07_KNOWLEDGE_BASE/kimi_projects/orbit_veil/ (projet complet)
- 07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills/ (repo complet)

## Serveurs de Test
- GARGANTUA: http://localhost:8765/
- ORBIT VEIL: http://localhost:8766/
