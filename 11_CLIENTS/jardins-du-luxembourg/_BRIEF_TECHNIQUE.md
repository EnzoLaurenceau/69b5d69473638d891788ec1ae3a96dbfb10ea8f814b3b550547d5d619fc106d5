# BRIEF TECHNIQUE — Site vitrine « Les Jardins du Luxembourg »
> Contrat partagé par tous les agents. **Respecter les noms de classes/IDs à la lettre** :
> le HTML, le CSS, le JS et l'i18n sont écrits en parallèle par des agents différents.

## 0. Faits VÉRIFIÉS (ne rien inventer au-delà)

| Donnée | Valeur | Source |
|---|---|---|
| Enseigne | Les Jardins du Luxembourg (NL : De Tuinen van Luxemburg) | heures.be, ixelles.city, brusselslife.be |
| Entité légale | **MUSA SRL** (Société à responsabilité limitée) | BCE officielle (kbopub.economie.fgov.be) |
| N° entreprise / TVA | **BE 0465.955.732** — statut « Actif » | BCE officielle |
| Constitution | 24 avril 1999 | BCE |
| Activité NACE | Commerce de détail de fleurs, plantes, graines et engrais | BCE |
| Adresse | Rue de Trèves 2 / Trierstraat 2, 1050 Ixelles (Elsene), Belgique | BCE + annuaires |
| Quartier | Quartier Léopold / quartier européen, à côté de la gare Bruxelles-Luxembourg et du Parlement européen | OSM, brusselslife.be |
| Coordonnées GPS | **50.8378041, 4.3724434** | Nominatim / OpenStreetMap |
| Téléphone | **+32 2 512 52 15** (affiché `02 512 52 15`) | 3 sources concordantes |
| Effectif | 10 à 19 personnes | annuaires BCE-dérivés |
| Offre | fleurs coupées, bouquets prêts à emporter ou sur mesure, plantes vertes et fleuries en pot, compositions événementielles (mariage), deuil | brusselslife.be, cityplug.be, localservices.be |
| Site web actuel | **AUCUN** (c'est la raison de ce projet) | — |
| E-mail | **INCONNU** | — |

### ⛔ Données NON vérifiées — INTERDIT de les affirmer
- **Horaires** : les annuaires se contredisent (09:00–19:00 / 09:00–12:00+14:00–18:00 / 08:00–18:00).
  → afficher le jeu d'horaires ci-dessous **avec la mention « horaires indicatifs, à confirmer »**
    (`.hours__disclaimer`), et l'inscrire dans `_A_CONFIRMER.md`.
- **Avis / notes / témoignages** : ne JAMAIS écrire de faux témoignage client, ni de note chiffrée.
  À la place → section « Depuis 1999 » (fait vérifié) et « une équipe de 10 à 19 fleuristes ».
- **Prix, zones de livraison, réseaux sociaux, langues parlées** : ne pas les inventer.
- **Photos** : aucune photo réelle disponible → **zéro photo stock**. Uniquement des illustrations
  SVG botaniques faites main + dégradés CSS.

### Horaires à afficher (indicatifs)
Lundi–Vendredi 09:00 – 19:00 · Samedi 09:30 – 18:30 · Dimanche fermé

## 1. Marque & design (unique, pas de template)
Fleuriste d'exception du quartier européen : **élégant, botanique, éditorial** — jamais « corporate SaaS ».

```
--jl-forest:#14302A  --jl-green:#1F4D3F  --jl-sage:#7E9A85  --jl-cream:#FBF7F0
--jl-sand:#EFE6D6    --jl-rose:#C86B6E   --jl-rose-dk:#A94F53
--jl-ink:#1A1A17     --jl-muted:#6B6B62  --jl-gold:#C9A227   --jl-line:rgba(20,48,42,.14)
```
Typo via **Fontshare** (une seule balise `<link>`) :
`https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&f[]=gambetta@400,500,600&display=swap`
- Titres : `Gambetta, Georgia, serif` (serif éditoriale, italique pour les accents)
- Texte/UI : `Satoshi, system-ui, sans-serif`
- Fond crème, larges respirations, filets fins `--jl-line`, coins très légers (4–6 px), pas d'ombres lourdes.
- Micro-détails : lettrines, petits caps `letter-spacing:.18em` pour les eyebrows, séparateurs SVG feuille.
- Responsive mobile-first, breakpoints 640 / 900 / 1200. Grille max-width 1180px, gouttière 24px.
- Accessibilité **WCAG 2.2 AA** : contraste ≥ 4.5:1, focus visible `outline:2px solid var(--jl-gold)`,
  `prefers-reduced-motion` respecté, HTML sémantique, skip-link, labels explicites, `aria-*` corrects.

## 2. Fichiers (un agent par fichier)
```
11_CLIENTS/jardins-du-luxembourg/
├── index.html            (agent 1)
├── assets/css/style.css  (agent 2)
├── assets/js/app.js      (agent 3)
├── assets/js/i18n.js     (agent 4)
├── mentions-legales.html (agent 5)
├── confidentialite.html  (agent 5)
├── cookies.html          (agent 5)
├── README.md / AGENTS.md / _A_CONFIRMER.md (agent 6)
└── assets/img/botanical.svg (agent 1 — sprite <symbol>)
```
Ordre de chargement dans `<head>` : Fontshare → `assets/css/style.css`.
Avant `</body>` : `<script src="assets/js/i18n.js"></script>` puis `<script src="assets/js/app.js" defer></script>`
(i18n.js expose `window.JL_I18N`, app.js le consomme — pas de `defer` sur i18n.js pour garantir l'ordre).

## 3. Contrat DOM — index.html (à respecter EXACTEMENT)

```
a.skip-link[href="#main"]
header#site-header.header
  a.header__brand[href="/"] > svg(logo monogramme JL) + span.header__brand-name + span.header__brand-tag
  nav.header__nav#primary-nav > a.header__link[href="#..."] × (savoir-faire, collections, occasions, visite, contact)
  div.header__lang[role="group"][aria-label="Langue"] > button.lang-btn[data-lang="fr|nl|en"][aria-pressed]
  a.header__cta.btn.btn--primary[href="tel:+3225125215"]
  button.header__burger#nav-toggle[aria-expanded="false"][aria-controls="primary-nav"]
main#main
  section#hero.hero
    p.hero__eyebrow / h1.hero__title (avec <em>) / p.hero__lede
    div.hero__actions > a.btn.btn--primary[href="tel:..."] + a.btn.btn--ghost[href="#contact"]
    ul.hero__meta > li × 3 (adresse, téléphone, span#open-status.status-pill)
    figure.hero__art (SVG botanique décoratif, aria-hidden)
  section#savoir-faire.about   → h2.section__title, p, ul.about__points > li.about__point × 3, aside.about__since ("Depuis 1999")
  section#collections.collections → h2.section__title + div.collections__grid > article.collection-card × 6
      (fleurs coupées · bouquets sur mesure · plantes vertes · plantes fleuries · abonnements bureaux · cadeaux)
      chaque carte : svg.collection-card__icon (use #leaf-…) + h3.collection-card__title + p.collection-card__text
  section#occasions.occasions → h2.section__title + div.occasions__grid > article.occasion × 4
      (mariage · deuil · entreprises & institutions · anniversaires/remerciements)
  section#visite.visit
    div.visit__hours > h2.section__title + table.hours__table (thead + tbody#hours-body) + p.hours__disclaimer
    div.visit__map
      div#map-consent.map-consent > p + button#map-load.btn.btn--ghost   ← carte NON chargée avant clic
      div#map.map[hidden] + p.map__credit (attribution OSM obligatoire)
      a.visit__directions[href="https://www.openstreetmap.org/?mlat=50.8378041&mlon=4.3724434#map=18/50.8378041/4.3724434"]
  section#contact.contact
    form#contact-form.form[novalidate]
      champs (chacun label + input/select/textarea + p.form__error[id="err-<name>"][role="alert"]) :
        name(text,required) · email(email,required) · phone(tel) · occasion(select: bouquet|mariage|deuil|abonnement|autre)
        · date(date) · message(textarea,required) · consent(checkbox,required)
      button[type=submit].btn.btn--primary + p#form-status.form__status[role="status"][aria-live="polite"]
    aside.contact__direct (téléphone en grand, adresse, note « commande par téléphone »)
footer#site-footer.footer
  div.footer__cols (3 colonnes : marque · liens · coordonnées)
  div.footer__legal  ← bloc légal COMPLET (voir §5)
div#cookie-notice.cookie-notice[hidden] > p + a[href="cookies.html"] + button#cookie-ok.btn
```
Tous les textes traduisibles portent `data-i18n="cle"` (texte) ou `data-i18n-attr="placeholder:cle"`.
`<html lang="fr">` au départ.

## 4. Contrat JS — assets/js/app.js
1. **Burger** : toggle `.is-open` sur `#primary-nav` + `aria-expanded`, fermeture sur Escape / clic lien / resize ≥900px.
2. **Langue** : `setLang(code)` → parcourt `[data-i18n]`/`[data-i18n-attr]`, remplace depuis `window.JL_I18N[code]`,
   met à jour `document.documentElement.lang`, `aria-pressed` des `.lang-btn`, et re-render des horaires.
   Défaut : `navigator.language` si fr/nl/en, sinon `fr`. **AUCUN localStorage/sessionStorage** (interdit).
3. **Horaires** : source unique de vérité `const HOURS = [[9,19],[9,19],[9,19],[9,19],[9,19],[9.5,18.5],null]` (Lun→Dim),
   rend `#hours-body`, marque `.is-today`, et calcule `#open-status` (« Ouvert · ferme à 19:00 » / « Fermé · ouvre lundi à 09:00 »)
   en heure de Bruxelles (`Intl.DateTimeFormat('fr-BE',{timeZone:'Europe/Brussels'})`). Rafraîchi chaque minute.
4. **Carte** : Leaflet chargé **uniquement au clic** sur `#map-load` (injection dynamique de
   `https://unpkg.com/leaflet@1.9.4/dist/leaflet.{css,js}` avec `integrity` omis mais `crossorigin="anonymous"`),
   tuiles **CartoDB Voyager** `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png`,
   attribution `© OpenStreetMap contributors · © CARTO`, marqueur + popup sur 50.8378041/4.3724434, zoom 17.
   Si le chargement échoue → message de repli avec le lien OSM. Puis `#map-consent` masqué, `#map` visible.
5. **Formulaire** : validation à la soumission (champs requis, e-mail regex, consentement),
   messages d'erreur dans `p.form__error` + `aria-invalid`, focus sur le premier champ fautif.
   `const CONTACT_ENDPOINT = null;` → si `null`, **ne prétend pas envoyer** : affiche dans `#form-status`
   « Le formulaire n'est pas encore relié à une boîte e-mail — appelez le 02 512 52 15 » (traduit).
   Si un endpoint est configuré plus tard → `fetch` POST JSON. Ne jamais stocker les données côté client.
6. **Bandeau cookies** : affiche `#cookie-notice` au chargement, `#cookie-ok` le masque (mémoire vive seulement).
   Le site ne pose **aucun cookie** et ne charge aucun tracker : le bandeau est informatif.
7. **Divers** : scroll doux respectant `prefers-reduced-motion`, `IntersectionObserver` pour révéler les sections
   (classe `.is-visible`), année courante dans `[data-year]`.
8. Code vanilla ES2020, pas de dépendance hors Leaflet différé, `'use strict'`, aucune erreur console.

## 5. Bloc légal (footer de CHAQUE page + pages dédiées)
Éditeur : **MUSA SRL** — enseigne « Les Jardins du Luxembourg » · Rue de Trèves 2, 1050 Ixelles, Belgique ·
N° d'entreprise / TVA : **BE 0465.955.732** · Tél. **+32 2 512 52 15** ·
Responsable de la publication : `TODO-LEGAL: nom du représentant légal` ·
Hébergeur : `TODO-LEGAL: hébergeur (nom, adresse, téléphone)` ·
Contact : `TODO-LEGAL: adresse e-mail de contact`
Liens : Mentions légales · Politique de confidentialité · Cookies · Accessibilité (ancre dans confidentialite.html)

> Les marqueurs `TODO-LEGAL:` sont **volontaires** : le gate `legal_check()` doit bloquer la mise en ligne
> tant que le client n'a pas fourni ces données. Les afficher visuellement dans un encart
> `.legal-todo` (fond ambre, `role="note"`, texte « À compléter avant mise en ligne »).
> **Ne jamais inventer** ces valeurs.

Le site est une **vitrine sans vente en ligne** (pas de paiement, pas de panier) → pas de CGV/rétractation.
La politique de confidentialité doit couvrir : responsable du traitement, données du formulaire de contact,
base légale (consentement + intérêt légitime), durée de conservation, absence de transfert hors UE,
absence de tracker, droits RGPD (**accès, rectification, effacement**, limitation, opposition, portabilité),
réclamation auprès de l'**Autorité de protection des données** (Rue de la Presse 35, 1000 Bruxelles),
et une section **Accessibilité** (WCAG 2.2 AA / EAA).
La page cookies doit dire clairement : aucun cookie, aucun tracker, carte OSM/CARTO chargée sur consentement explicite.

## 6. Interdits absolus
- `localStorage` / `sessionStorage` (règle forge n°4 + gate légal) — **même pas dans un commentaire**.
- Faux avis, faux prix, faux e-mail, faux horaires affirmés, photos stock.
- Framework CSS/JS externe (Tailwind CDN, Bootstrap…) — tout est écrit à la main.
- Texte lorem ipsum.
