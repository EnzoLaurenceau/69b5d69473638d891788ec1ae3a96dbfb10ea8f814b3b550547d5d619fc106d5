# Reel « Forest walk » : rapport de montage
> 2026-10-05 · Source : `IMG_0011.mp4` · Pipeline : `00_CORE/tools/product_bricks/generative_media/reel_forge/`

## 0. TL;DR
- **6 exports prêts Instagram** (1080x1920, 30 fps, H.264 High, AAC 48 kHz, -14 LUFS). Tous ont été montés **uniquement à partir de ton rush**, sans plan inventé.
- **Version recommandée : D « Story Venkai » (FR)**, 12 s, avec 6 sous-titres qui racontent une mini-histoire. Boucle temporelle parfaite : la dernière image enchaîne sur la première, sans couture.
- **Musique** : aucune musique n'est intégrée, volontairement. Le montage est calé sur une grille de **120 BPM**. Choisis le son dans Instagram au moment de publier (voir §5).
- **À valider avant de publier** : les phrases « les heures à construire Venkai » et « Mais je ne construis pas seul » sont une narration que je propose ; elles ne sont tirées d'aucun fait vérifié. Il faut aussi **l'accord des deux potes visibles** (droit à l'image).

## 1. Analyse du MP4 (frame-by-frame)
Métadonnées : 1080x1920 natif vertical, 30 fps, 15,70 s (471 frames), H.264 + AAC 44,1 kHz, BT.709, iPhone en selfie à la main.
Outils : `reel_forge/analyze.py` (flux optique Farneback, netteté Laplacien, luma, ratio de vert, Haar faces, PySceneDetect, onsets librosa), planches à 4 fps et skill GitHub `claude-watch` (mode hook, effort high).

| Source | Plan | Qualité | Usage |
|---|---|---|---|
| 0.00–0.30 | Retournement du téléphone (flou total) | ✗ | coupé |
| 0.30–2.30 | Selfie toi (afro, pull rose, lunettes), sourire à 1.25–1.80 | bonne | slow-mo « sourire » |
| 2.30–2.85 | **Whip pan droite** vers le chemin, potes de dos | flou naturel | transition |
| 2.85–3.95 | Chemin sinueux, **tilt-up qui révèle la grotte / l'arche rocheuse** | **très net** (netteté 3 000–3 900) | révélation, boucle |
| 3.95–4.36 | **Pote (sweat gris) qui marche vers la caméra, grotte derrière** | net | cold open (A/D) |
| 4.36–4.56 | **Whip gauche** retour selfie | flou | transition |
| 4.60–5.15 | Toi hors cadre, buissons | ✗ faible | coupé |
| 5.40–5.85 | Selfie énergique | moyen | pattern interrupt |
| 5.85–6.15 | **Whip droite** vers le pote | flou | transition |
| 6.15–7.55 | Pote en dutch angle, signe « OK », sourire | **très net** (4 500–5 700) | plan potes |
| 7.55–7.98 | **Whip retour** | flou | transition |
| 7.98–8.50 | **Grand rire face caméra** | net | impact émotionnel |
| 8.50–13.65 | Selfie qui parle, profil, regard ailleurs (5 s statiques) | ✗ temps mort | 3 micro-moments gardés (9.3, 10.4, 13.0) |
| 13.70–14.40 | **Toi + un pote qui apparaît derrière** | bon | hero « squad » |
| 14.40–15.10 | **Whip vers le sol** (bouteille) | flou | sortie / boucle |
| 15.20–15.70 | Doigt sur l'objectif, 6 frames noires | ✗ | coupé |

Coupes détectées : 2.37 · 3.17 · 4.17 · 6.13 · 7.63 · 9.20 · 10.03 · 13.77 · 14.57 s. Audio : parole continue (‑17 à ‑32 dB RMS), pic à ‑2,4 dBFS. **Transcription impossible** : huggingface.co est bloqué par la politique réseau du conteneur, donc ce que tu dis n'a pas été vérifié.
Verdict hook du rush brut (`claude-watch`) : frame 0 floue, aucun texte, aucune promesse, premier pattern interrupt seulement à 2,3 s. En l'état, le rush n'a pas de hook.

## 2–3. Concept retenu et pourquoi
**D, « Story Venkai »** : contraste *ce que vous voyez* (balade entre potes) / *ce que vous ne voyez pas* (construire Venkai), puis une promesse qui boucle (« Dans un an, cette vidéo aura du sens »).
- C'est le pattern « What you see vs what it takes », récurrent dans la niche build-in-public. Il prend le dessus sur la rétention parce que les sous-titres mot à mot ouvrent une boucle de curiosité à chaque plan.
- Il colle à l'arc demandé (jeune → libre → amis → mouvement → quelque chose se construit) sans transformer le Reel en pub.
- La phrase finale incite à revoir et à enregistrer. La boucle temporelle cache la couture.

## 4. Timeline de D (0.00 → 12.00), grille 120 BPM (1 temps = 0,5 s)
| Sortie | Source | Vitesse | Image / motion | Son | Sous-titre |
|---|---|---|---|---|---|
| 0.00–0.80 | 4.00–4.36 | 0.18→0.8x (ramp) | Cold open : pote qui arrive, grotte derrière, micro-zoom 1.05→1.07 | feuilles | « Ce que vous voyez : une balade entre potes. » (0.15) |
| 0.80–1.00 | 4.36–4.56 | 1x | Whip gauche | whoosh G | |
| 1.00–2.00 | 7.99–8.47 | 0.48x | Ton rire, slow-mo par flux optique | **impact sub** + shake + flash | |
| 2.00–2.30 | 5.50–5.80 | 1x | Selfie énergie | | |
| 2.30–2.50 | 5.84–6.14 | 1.5x | Whip droite (motion blur 180°) | whoosh D | |
| 2.50–3.80 | 6.16–7.46 | 1x | Pote « OK » | | « Ce que vous ne voyez pas… » |
| 3.80–4.00 | 7.55–7.98 | 2.1x | Whip retour | whoosh G | |
| 4.00–5.50 | 1.10–1.84 | 0.49x | Sourire slow-mo + **light leak** chaud | | « les heures à construire *Venkai.* » |
| 5.50–6.50 | 9.28–9.88 | 0.6x | Regard vers l'avant | | « Personne ne comprend encore ce qu'on bâtit. » |
| 6.50–7.00 | 12.98–13.48 | 1x | Micro-cut face caméra | subtle hit · **riser** | |
| 7.00–7.50 | 10.40–10.90 | 1x | Micro-cut trois-quarts | subtle hit | |
| 7.50–9.50 | 13.74–14.40 | 0.33x | **HERO : toi + pote derrière**, push-in 1.04→1.10 | **impact payoff** + flash + shake | « Mais je ne construis pas seul. » |
| 9.50–10.00 | 14.42–15.04 | ramp → 2x | Whip out vers le sol | whoosh D (déborde sur 0.00) | |
| 10.00–10.20 | 2.62–2.85 | 1.15x | Whip in sur le chemin | | |
| 10.20–12.00 | 2.85–3.95 | 0.61x | Chemin → **révélation grotte** | feuilles | « Dans un an, cette vidéo aura du sens. » |
| → 0.00 | 3.95 → 4.00 | | **Boucle** : la source enchaîne exactement | vent continu | |

Densité : 15 plans en 12 s (1,25 coupe/s), un pattern interrupt toutes les 0,5 à 1,5 s, payoff à 62 % de la durée.

## 5. Musique
Pas de musique figée dans le fichier : les sons natifs d'Instagram gardent leur avantage de distribution et ne vieillissent pas dans l'export. Toutes les coupes tombent sur une **grille de 120 BPM** (marqueurs dans `*_markers.json`). Trois catégories à chercher dans la bibliothèque audio d'Instagram :
1. **Électro / indie-dance cinématique, 110–125 BPM**, avec un build et un drop. Cale le drop sur le payoff : **7,5 s** (A, D), **8,5 s** (B), **4,0 s** (C).
2. **Piano ou cordes ambient, 60–85 BPM** (60 BPM = moitié de la grille, donc les coupes restent sur le temps). Idéal pour D.
3. **Indie / R&B nostalgique slowed + reverb, 70–95 BPM**, avec une ligne vocale reconnaissable. Pour A (cinématique).

Réglage dans Instagram : musique à environ 80 %, « audio original » à 30–50 % pour garder les SFX, le vent et ton rire.

## 6. SFX (tous synthétisés, donc zéro sample sous droits)
Whoosh à chaque whip (spatialisés gauche/droite selon le sens) · impact sub 70→38 Hz sur le rire et le payoff · deux subtle hits sur les micro-cuts · riser de 1,5 s avant le payoff · feuilles granulaires sur les plans chemin · vent continu (‑31 dB), sans couture à la boucle · tick discret (‑30 dB) à chaque sous-titre · ta voix d'origine conservée en fond (‑12 dB, passe-bas et ralentie sur les slow-mo).
Hiérarchie : [musique IG] > impacts / whoosh > ambiance > micro-SFX. Master à ‑14 LUFS, limiteur true-peak (suréchantillonné ×4) à ‑2 dBTP.

## 7. Motion design
Slow-mo par interpolation de flux optique (DIS bidirectionnel, 0,33–0,6x) · speed ramps « ramp_up » dans les whips · motion blur synthétique (obturateur 180°) au-delà de 1,2x · micro push-in 2 à 10 % · camera shake amorti (10 px, 0,3 s) uniquement sur les impacts · flash d'exposition de 0,15 s · un seul light leak chaud · grain luma léger. Pas de glitch, de sticker, d'emoji ni de transition de bibliothèque.

## 8. Étalonnage (`grade.py` → LUT 3D 33³)
Courbe filmique (noirs propres légèrement relevés, S douce, épaule sur les hautes lumières) · verts de la pelouse désaturés de 46 %, assombris et tirés vers un vert plus profond (fin du « citron vert ») · tons chair protégés · rose du pull préservé · split-tone discret (ombres froides, hautes lumières chaudes) · vignette légère.

## 9. Texte
Police DM Serif Display (OFL), halo d'ombre flou, apparition mot à mot (100 ms par mot) avec focus-in (flou → net). Toujours dans la zone sûre Instagram (x 6–94 %, y 14–65 %, centre à y ≈ 1130). Taille calculée selon la ligne la plus longue.

## 10. Boucle
- **Boucle temporelle** (A, D) : le dernier plan est 2,85→3,95 s du rush, le premier commence à 4,00 s. Le spectateur voit la suite exacte du mouvement.
- **C** : même principe (tilt du chemin → push-in sur la grotte).
- **Boucle sonore** : le dernier whoosh et le vent débordent sur le début (placement circulaire).
- **Boucle narrative** (D) : « Dans un an, cette vidéo aura du sens » enchaîne sur « Ce que vous voyez… ».

## 11–12. Scores (estimations heuristiques, pas des mesures)
| | Rétention estimée | Potentiel viral | Pourquoi |
|---|---|---|---|
| **D Story FR / EN** | 7,5/10 | 6,5/10 | hook visuel + texte dès 0,15 s, boucle narrative, déclencheur d'envoi (« pas seul ») |
| A Cinematic | 7/10 | 5,5/10 | rythme et boucle parfaits, mais aucune promesse : dépend fortement de la musique |
| C Mystery | 7/10 | 6/10 | 8 s (format court au meilleur taux de complétion), hook POV + grotte |
| B Founder | 6,5/10 | 5,5/10 | hook visage, phrase connue du format, sous-titres moins narratifs |

Plafond réel : le rush est un selfie de balade sans « événement » et tes lunettes cachent tes yeux. La viralité dépendra surtout du hook texte, des envois et de la régularité de publication.

## 13. Risques
- Droit à l'image : **deux potes visibles**, demande-leur leur accord.
- Voix d'origine non transcrite : réécoute pour vérifier qu'aucune phrase ne pose problème (elle est en fond, mais audible).
- Narration D : à valider (formulations proposées, pas des faits).
- Musique : uniquement la bibliothèque Instagram (droits).
- Slow-mo interpolé : aucun artefact visible au contrôle, mais les plans rapides restent la zone à risque si tu ralentis davantage.

## 14. Variantes
| Version | Durée | Hook (0–1 s) | Texte | Boucle | Raison stratégique |
|---|---|---|---|---|---|
| **D_story_venkai_FR** | 12 s | pote + grotte, sous-titre dès 0,15 s | 6 sous-titres FR mot à mot | temporelle + narrative | **post principal** (audience FR) |
| D_story_venkai_EN | 12 s | idem | 6 sous-titres EN | idem | Trial Reel, audience internationale |
| A_cinematic | 12 s | pote + grotte | aucun | temporelle | Trial Reel, « silent vlog » cinématique |
| C_mystery | 8 s | push-in sur la grotte | « POV: you're building something nobody understands yet. » | temporelle | Trial Reel court |
| B_founder | 11 s | ton sourire | « 11 seconds of life / before going back to building. » + `building venkai` | retournement du téléphone (sol → visage) → sourire | test du hook visage |
| B_founder_FR | 11 s | idem | version FR | idem | idem |

Publication : D-FR en Reel normal, A / C / D-EN en **Trial Reels** (non-abonnés, partage auto si performance à 72 h). 5 hashtags max, par exemple `#buildinpublic #startup #entrepreneur #founder #venkai`. Légende courte avec un appel à l'envoi : « Envoie ça au pote qui build avec toi. » Cover : `*_cover.jpg`.

## 15. Fichiers exportés et QC
| Fichier | Durée | Débit | Taille | LUFS | True peak | Frames noires | Coupes/s | Texte en zone sûre | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `D_story_venkai_FR.mp4` | 12.00 s | 21.0 Mb/s | 31.4 Mo | -14.6 | -1.9 dBTP | 0 | 1.17 | ✓ | **PASS** |
| `D_story_venkai_EN.mp4` | 12.00 s | 20.9 Mb/s | 31.4 Mo | -14.6 | -1.9 dBTP | 0 | 1.17 | ✓ | **PASS** |
| `A_cinematic.mp4` | 12.00 s | 21.0 Mb/s | 31.5 Mo | -14.5 | -1.8 dBTP | 0 | 1.17 | — | **PASS** |
| `C_mystery.mp4` | 8.00 s | 22.1 Mb/s | 22.1 Mo | -14.5 | -2.0 dBTP | 0 | 1.25 | ✓ | **PASS** |
| `B_founder.mp4` | 11.00 s | 19.6 Mb/s | 27.0 Mo | -14.6 | -1.9 dBTP | 0 | 1.36 | ✓ | **PASS** |
| `B_founder_FR.mp4` | 11.00 s | 19.7 Mb/s | 27.1 Mo | -14.6 | -1.9 dBTP | 0 | 1.36 | ✓ | **PASS** |

Checklist phase 13, vérifiée automatiquement par `qc.py` + visuellement sur planches 4 fps :
- [x] hook < 1 s (première coupe ou mouvement + texte avant 1 s)
- [x] aucun temps mort (plan le plus long 2,0 s, en slow-mo avec push-in)
- [x] premier pattern interrupt ≤ 1,0 s (D/A/B) ou 1,0 s (C)
- [x] cuts justifiés (sur whips naturels ou sur le temps, grille 120 BPM)
- [x] SFX synchronisés (spectrogramme vérifié : whoosh, impacts, riser aux timecodes prévus)
- [x] voix d'origine en fond (-11/-12 dB), filtrée sur les slow-mo
- [x] pas de clipping · true peak ≤ -1 dBTP · -14 ±1 LUFS
- [x] 0 frame noire (les 6 frames noires du rush sont coupées)
- [x] texte lisible, en zone sûre Instagram (bbox mesurée)
- [x] aucune transition artificielle (uniquement les whips réels du rush)
- [x] étalonnage cohérent (même LUT sur tout), visages naturels
- [x] boucle cohérente (couture ≤ 1,5 × p90 des différences inter-frames)
- [x] 1080x1920 · 30 fps · H.264 High · yuv420p · BT.709 · AAC 48 kHz stéréo · faststart

Livrables du dépôt (dossier `07_REPORTS/reel_forest_walk/`) : `covers/` (vignettes), `qc/` (JSON + aperçus zone sûre), `markers/` (beats et coupes), `analysis_frame_by_frame.png`. Les MP4 sont exclus par le `.gitignore` (`*.mp4`) : ils t'ont été envoyés directement.


## Annexes
**Outils GitHub pour que Claude « voie » une vidéo** :
- [alexlarcheveque/claude-watch](https://github.com/alexlarcheveque/claude-watch) (utilisé ici : frames + transcript, prompts hook / rétention ; bug : à 2 fps il écrase une frame sur deux)
- [jordanrendric/claude-video-vision](https://github.com/jordanrendric/claude-video-vision) (plugin + MCP, audio via Whisper / Gemini)
- [terminusapp-ai/watch-video](https://github.com/terminusapp-ai/watch-video)
- [ridelink0/video-watch](https://github.com/ridelink0/video-watch)
- [victor-shulga/watch](https://github.com/victor-shulga/watch)
- [fabriqaai/ffmpeg-analyse-video-skill](https://github.com/fabriqaai/ffmpeg-analyse-video-skill)

**« Top 100 des posts viraux » : non réalisé, honnêtement.** Je n'ai aucun accès à l'API Instagram, et le proxy a bloqué l'ouverture des pages de recherche. Je n'ai donc publié aucun classement, aucun créateur ni aucun chiffre invérifiable. J'ai utilisé à la place les patterns d'études agrégées (Socialinsider 6M Reels 2026, Buffer, Later, OpusClip) et les signaux officiels de ranking (watch time, likes par reach, **envois par reach**, skip rate sur 3 s, originalité), via résumés de moteur de recherche (confiance moyenne). Pour un vrai top 100, il faudrait un accès Graph API ou un scraper autorisé.

**Écarts à la doctrine Forge** : la stack Forge n'est pas installée dans ce conteneur cloud (langgraph absent, pas de clé MiMo, binaire RTK Windows, MCP GitNexus indisponible). Le travail a été fait directement, sans `forge_call`, token tracker, RTK ni `detect_changes`.

**Reproduire / modifier** : édite un `edl/*.json` (texte, timings, SFX), puis lance
`python render.py edl/forest_walk_D_story_venkai_FR.json IMG_0011.mp4 out/ --fonts fonts/` et `python qc.py out/D_story_venkai_FR.mp4 --ass out/D_story_venkai_FR.ass --fonts fonts/`.
