# reel_forge — AGENTS.md

## Purpose
Pipeline local de montage de Reels/TikTok verticaux à partir d'un rush existant
(aucun plan inventé) : analyse frame-by-frame → timeline EDL → rendu (speed ramps,
slow-mo par flux optique, étalonnage, texte cinétique, sound design procédural) → QC.

## Ownership
Brique `product_bricks/generative_media`. Aucun appel LLM, aucune clé API : 100 % local
(ffmpeg + OpenCV + librosa + numpy/scipy). Les SFX sont synthétisés (pas de samples tiers).

## Local Contracts
- `analyze.py clip.mp4 out/ [--no-asr]` → `analysis.json` (mouvement, netteté, luma, vert,
  visages, frames noires par frame ; coupes PySceneDetect ; RMS + onsets audio ; transcription
  faster-whisper si le modèle est téléchargeable) + `analysis.png`.
- `render.py edl.json clip.mp4 out/ --fonts dir/` → `NAME.mp4` (1080x1920, 30 fps, H.264 High
  CRF17 ≤20 Mb/s, bt709, AAC 320k 48 kHz, -14 LUFS / ≤ -1 dBTP), `NAME.wav`, `NAME.ass`,
  `NAME_markers.json` (grille de beats + coupes), `NAME_cover.jpg`.
- `qc.py out/NAME.mp4 --ass out/NAME.ass --fonts dir/` → `NAME_qc.json` + `NAME_safezone.jpg`.
- `grade.py out.cube` → LUT 3D « cinematic natural » (verts contrôlés, peau protégée).
- EDL (`edl/*.json`) : `segments[{label, src:[in,out], dur, ease: linear|ramp_up|ramp_down,
  zoom:[z0,z1], center:[x,y]}]`, `fx[{type: whoosh|hit|riser|leaves|shake|leak|flash, t, dur, …}]`,
  `text[{text, start, end, style: Serif|Sig, size?, y, reveal: words, word_ms}]` (`{DUR}` = durée arrondie ;
  taille Serif auto = min(84, 1800 / plus longue ligne) ; `reveal: words` = sous-titres mot par mot),
  `audio{natural_db, wind_db, lufs}`, `bpm`, `cover`. Durées en multiples de 0,1 s (3 frames).
- Les SFX se placent avec wrap circulaire : un son qui dépasse la fin reprend au début
  (boucle sonore sans couture).

## Work Guidance
- Couper les whips (pans flous) entre deux moments non contigus du rush : le flou masque le raccord.
- Slow-mo ≥ 0,33x sur plans à mouvement modéré ; au-delà, artefacts de warping.
- Texte : DM Serif Display (OFL, style `Serif`, halo flou) + Inter (OFL, style `Sig`) depuis
  google/fonts (`--fonts` doit contenir les .ttf) ; zone sûre = x 6–94 %, y 14–65 %.
- Limiteur à -2 dBFS : l'encodage AAC ajoute ~1 dB de true peak.
- Dépendances : `pip install "opencv-python-headless<5" scenedetect librosa soundfile pyloudnorm`
  (OpenCV 5 a retiré les cascades Haar du module principal).

## Verification
`python qc.py …` doit afficher `PASS` (specs IG, 0 frame noire, -14 ±1 LUFS, TP ≤ -1 dBTP,
hook < 1 s, couture de boucle lisse, texte en zone sûre).
