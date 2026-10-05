# Venkai × Forest walk : 3 Reels, 3 angles psychologiques
> 2026-10-05 · Même footage (`IMG_0011.mp4`), 3 narrations radicalement différentes · Faits : uniquement `BRIEF_VENKAI_CANON.md`
> Fichiers : `V2_A_personne_ne_voit.mp4` · `V2_B_promesse_tech.mp4` · `V2_C_build_in_public.mp4`

## Ce qui est commun (pour que le test A/B/C mesure la narration, pas l'habillage)
- **Sous-titres** : écriture blanche sur fond noir (boîte opaque par ligne), Poppins ExtraBold 104 px (environ 37 pt sur smartphone), **mot-clé qui passe au jaune** pendant la lecture, apparition en « pop » (86 → 100 % en 140 ms).
  Placement au centre de l'écran, ou sur la poitrine quand le visage remplit le cadre. Jamais dans le tiers bas (zone sûre Instagram : y entre 14 et 65 %, x entre 6 et 94 %).
  Un écran de texte = une idée, 2 à 6 mots.
- **Étalonnage « Venkai dark »** (LUT `grade.py --look dark`) : exposition -12 %, courbe en S marquée, noirs propres, verts éteints (-58 % de saturation, assombris), ombres légèrement cyan, hautes lumières neutres, peau protégée, vignette 0,55. Forêt réelle, pas de cyberpunk.
- **Footage** : uniquement les plans du rush. Raccords cachés dans les vrais whip pans, slow-mo par flux optique (0,3 à 0,6x), motion blur synthétique sur les accélérations, micro push-in de 2 à 10 %.
- **Écran final** : footage assombri (dim de 25 à 42 %) avec le mot de fin et le wordmark `VENKAI` en Poppins SemiBold espacé.
  C'est un wordmark texte, aucun logo n'était fourni : remplace-le par le vrai logo si tu en as un.
- **Musique** : non intégrée. Je n'ai aucun accès aux tendances audio d'Instagram, donc je ne prétends pas connaître le son du moment. Coupes calées sur **120 BPM** ; catégorie et point de drop indiqués par version. À ajouter dans Instagram : musique à environ 80 %, son original à 30–50 %.
- **Export** : 1080x1920 · 30 fps · H.264 High L4.2 · CRF 17 plafonné à 20 Mb/s · yuv420p BT.709 · AAC-LC 320 kb/s 48 kHz stéréo · -14 LUFS intégrés · true peak ≤ -1 dBTP · faststart · GOP de 2 s.

---

## VERSION A : « Personne ne voit encore ce qui se construit » (16,5 s)
**Action visée : « Je veux voir la suite. »** Lent, cinématique, mystérieux.

| Temps | Footage (source) | Traitement | Texte (exact) · placement | Son |
|---|---|---|---|---|
| 0.0–2.0 | Grotte au bout du chemin (3.20–3.95) | slow-mo 0,38x + push-in 1.03→1.15 vers l'arche | « Personne ne voit encore / ce que je **construis.** » · centre (y 1010) | feuilles, vent |
| 2.0–2.8 | Ami qui arrive (3.95–4.36) | ramp 0,2→0,8x | (suite du hook) | whoosh discret |
| 2.8–3.0 | Whip gauche (4.36–4.56) | flou natif | | whoosh |
| 3.0–4.6 | Ton sourire (1.06–1.84) | slow-mo 0,49x | « Je construis **Venkai.** » · poitrine (y 1160) | **impact subtil** (révélation du nom) |
| 4.6–4.8 | Whip droite | | | whoosh |
| 4.8–6.2 | Pote signe OK (6.16–7.46) | 1x | « Une nouvelle façon / de transformer » · centre | |
| 6.2–6.4 | Whip retour | | | whoosh |
| 6.4–8.0 | Regard vers l'avant (9.20–9.88) | slow-mo 0,43x | « **l'intention humaine** » · poitrine | |
| 8.0–10.0 | Trois-quarts (10.30–10.95) | slow-mo 0,33x (respiration) | « en **exécution.** » · poitrine | |
| 10.0–12.0 | Montée : rire, grotte, selfie, ami | 4 cuts de 0,5 s | — (aucun texte : montée visuelle) | 3 subtle hits + **riser** |
| 12.0–15.0 | Toi + pote derrière (13.00–14.42) | slow-mo 0,47x, push-in, flash et shake d'impact, dim 28 % (remonte avant la fin) | « Ce n'est que le **début.** » · poitrine (y 1170) + `VENKAI` (13.3 s) | **impact payoff**, feuilles |
| 15.0–15.5 | Whip out vers le sol | speed ramp | | whoosh |
| 15.5–16.5 | Whip in → chemin, tilt-up (2.62–3.20) | 0,44x | — | feuilles, **reboucle exactement sur la grotte de 0.0** |

- **Boucle parfaite** (vérifiée au QC) : la dernière image (source 3.20) précède immédiatement la première (3.20 → grotte). En plus, la boucle est narrative : « Ce n'est que le début. » enchaîne sur « Personne ne voit encore… ».
- **Musique** : cinématique mystérieuse (piano, nappe, pulse grave), 60–90 BPM, sans drop agressif. Impact sur **12,0 s**.
- **Pourquoi ça marche** : écart d'information (on voit une balade, on nous dit que quelque chose se construit). Le nom arrive tôt (3 s) mais sans explication complète, ce qui donne envie de suivre la série.

## VERSION B : « La promesse technologique » (15,5 s) · prioritaire
**Action visée : « C'est quoi Venkai ? »** Rythme électronique précis, une coupe par temps dans la montée, micro-glitch sur les mots-clés.

| Temps | Footage (source) | Traitement | Texte (exact) · placement | Son |
|---|---|---|---|---|
| 0.0–1.5 | Chemin → révélation de la grotte (2.90–3.95) | 0,7x, push-in | « Et si l'IA arrêtait / de recommencer **à zéro** ? » · centre (y 1010) | **glitch RGB + blip numérique** sur « à zéro » (0.8 s) |
| 1.5–2.5 | Ami qui arrive + whip | ramp, flou | | whoosh + hit (2.5) |
| 2.5–4.5 | Regard vers l'avant + trois-quarts | 0,6x | « Les entreprises / n'ont pas besoin » | blip numérique (changement de texte) |
| 4.5–6.0 | Whip droite → pote OK | | « d'une IA **de plus.** » | hit + glitch sur « de plus » |
| 6.0–7.5 | Whip retour → sourire | slow-mo 0,49x | « Elles ont besoin / d'une IA qui comprend » | hit |
| 7.5–10.0 | Face caméra, puis 4 cuts au beat (grotte, selfie, ami, rire) | 1x, 0,5 s par plan | « leur **continuité.** » · poitrine | glitch + 4 hits + **riser** |
| 10.0–12.0 | Toi + pote (13.74–14.42) | slow-mo 0,34x, flash, shake | « C'est ce que je construis » (10.0) puis « avec **Venkai.** » (11.0) · poitrine | **impact payoff** (10.0) + glitch sur « Venkai » (11.15) |
| 12.0–12.7 | Whip out → whip in | ramp | | whoosh |
| 12.7–15.5 | Chemin → grotte (2.85–3.95), **assombri à 42 %** | 0,39x, push-in | « Human intent / → **execution.** » · centre + `VENKAI` | hit + glitch (13.08) |

- **Boucle** : rime visuelle, pas une boucle parfaite (choix). L'écran final sombre sur le chemin et la grotte renvoie au même lieu en pleine lumière au début, et la question « Et si… » relance.
- **Musique** : électronique moderne minimale, **120 BPM pile** (ou 124–128 en réalignant le début). Drop sur **10,0 s**.
- **Pourquoi ça marche** : le hook est une question, ce qui crée une boucle cognitive. La phrase est découpée sur plusieurs écrans (« n'ont pas besoin… » / « d'une IA de plus. »), donc on doit rester pour finir de lire.
  Il donne une **idée à comprendre et à transmettre**, le meilleur levier d'envoi en message. C'est la version qui positionne le plus Venkai comme une entreprise tech.

## VERSION C : « Build in public » (14,5 s)
**Action visée : « Je veux suivre son parcours. »** Humain, visage d'abord, progression.

| Temps | Footage (source) | Traitement | Texte (exact) · placement | Son |
|---|---|---|---|---|
| 0.0–1.0 | **Ton rire** (7.99–8.47) | slow-mo 0,48x | « J'ai décidé de construire » · poitrine (y 1170) | ton audio d'origine (-8 dB) |
| 1.0–2.2 | Sourire (1.25–1.84) | slow-mo 0,49x | « une vraie / **entreprise d'IA.** » | |
| 2.2–3.9 | Whip → chemin et grotte | 0,7x | « Pas dans un bureau / de **milliardaire.** » · centre | whoosh, feuilles |
| 3.9–4.9 | Ami qui arrive + whip | ramp | « Juste en avançant, » | whoosh |
| 4.9–6.2 | Pote signe OK | 1x | « une journée / **après l'autre.** » | |
| 6.2–7.4 | Whip → selfie énergie | slow-mo 0,45x | « Encore **étudiant.** » · poitrine | whoosh |
| 7.4–8.8 | Regard vers l'avant | 0,49x | « Déjà **fondateur.** » · poitrine | riser doux |
| 8.8–11.2 | Toi + pote (13.66–14.42) | slow-mo 0,32x, flash léger | « Je construis **Venkai.** » | impact doux |
| 11.2–11.9 | Whip out → whip in | | | whoosh |
| 11.9–14.5 | Chemin → grotte, assombri à 25 % | 0,42x, push-in | « Suivez la **construction.** » · centre + `VENKAI` | feuilles |

- **Boucle** : volontairement absente (ton brief : « ne la force pas »). La fin ouvre sur le chemin (« la suite »), ce qui sert le CTA narratif. L'objectif de cette version est la série, pas le rewatch.
- **Musique** : émotionnelle et moderne (piano + beat léger, ou indie-pop qui monte), 100–120 BPM. Lift sur **8,8 s** (« Je construis Venkai »).
- **Pourquoi ça marche** : identification (un étudiant comme toi), progression en 3 temps (décision → réalité → identité), puis invitation à suivre. C'est le format qui convertit le mieux en abonnés, pas forcément en vues.

---

## Test A/B/C
| Version | Hook | Promesse | Émotion | Pourquoi elle peut fonctionner | Risque |
|---|---|---|---|---|---|
| A | « Personne ne voit encore ce que je construis. » sur la grotte | il y a quelque chose de plus grand derrière la balade | curiosité, mystère, ambition | écart d'information + série (« ce n'est que le début ») | trop vague : on peut repartir sans comprendre, donc moins d'envois |
| B | « Et si l'IA arrêtait de recommencer à zéro ? » | une IA qui garde la continuité d'une entreprise | intrigue intellectuelle | question + idée transmissible, donc envois en message et visites de profil | plus abstrait, peut perdre un public non-tech ; texte plus dense |
| C | « J'ai décidé de construire une vraie entreprise d'IA. » sur ton rire | suivre un étudiant qui construit | identification, sympathie | visage + parcours = abonnements, crédibilité | moins de rewatch, format build-in-public répandu |

### Scores /10 (estimations de jugement, pas des mesures)
| Critère | A | B | C |
|---|---|---|---|
| Force du hook | 7 | **8** | 7,5 |
| Clarté | 6 | 7 | **8** |
| Rétention potentielle | 7 | **7,5** | 7 |
| Rewatch potentiel | **7** | 6,5 | 5,5 |
| Potentiel de partage (envois) | 5,5 | **7,5** | 6 |
| Branding Venkai | 6,5 | **8** | 6,5 |
| Crédibilité | 8 | 7 | **8,5** |
| Différenciation | 6,5 | **8** | 5,5 |
| **Total /80** | 53,5 | **59,5** | 54,5 |

**Ordre de test recommandé** : B en Reel principal, A et C en **Trial Reels** (non-abonnés d'abord, partage automatique si performance à 72 h). Publie-les à quelques jours d'écart, au même créneau, avec la même légende de base, pour isoler la variable narration.

## Métriques à suivre (par version, à 24 h, 72 h et 7 j)
views · **average watch time** · **completion rate** · rewatches (replays/vue) · **shares / sends** · saves · **profile visits** · follows · comments · **skip rate** (part qui quitte avant 3 s).
Lecture : le watch time et la complétion mesurent le montage. Les envois et visites de profil mesurent l'idée. Les follows mesurent la promesse de série. Ne juge aucune version aux likes seuls.

## QC
| Fichier | Durée | Débit master | LUFS | True peak | Frames noires | Coupes/s | Hook < 1 s | Boucle | Texte zone sûre | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| `V2_A_personne_ne_voit.mp4` | 16.5 s | 19.3 Mb/s | -14.4 | -1.8 dBTP | 0 | 0.97 | ✓ | parfaite (couture 18.37 ≤ 1,5×p90) | ✓ | **PASS** |
| `V2_B_promesse_tech.mp4` | 15.5 s | 20.0 Mb/s | -14.4 | -1.6 dBTP | 0 | 1.1 | ✓ | rime visuelle | ✓ | **PASS** |
| `V2_C_build_in_public.mp4` | 14.5 s | 19.3 Mb/s | -14.2 | -1.6 dBTP | 0 | 0.9 | ✓ | aucune (choix) | ✓ | **PASS** |

Specs communes vérifiées : 1080x1920 · 30 fps · H.264 High · yuv420p · BT.709 · AAC 48 kHz stéréo · faststart.
Les masters (environ 20 Mb/s) sont dans le conteneur ; les copies envoyées sont plafonnées à 13 Mb/s pour passer la limite d'envoi de 30 Mio. Instagram recompresse bien en dessous, donc aucune différence visible.
Revue visuelle à 2 fps des 3 versions + contrôle plein écran des écrans clés (sous-titres, écran final, wordmark).
Fichiers du dépôt : `v2/` (covers, QC JSON, aperçus zone sûre, marqueurs de beats et de coupes).

