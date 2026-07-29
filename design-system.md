# La Forge — Design System

Référence unique pour tout écran, composant ou mockup produit pour La Forge. À respecter à la lettre par tout agent/designer qui génère de l'UI pour la plateforme.

## 1. Identité

- **Archétype** : l'artisan-technologue. Précision d'ingénieur, fierté d'artisan — jamais startup corporate froide, jamais no-code jouet.
- **Ton** : direct, concret, jamais grandiloquent. Pas de "disruptif", pas de "synergie". On montre des chiffres réels ("6 agents actifs", "23% de tokens économisés") plutôt que des promesses vagues.
- **Mode par défaut : sombre.** Le clair reste disponible pour l'usage bureautique, mais l'identité visuelle est pensée dark-first.
- **Zéro cliché forge/médiéval** : pas d'enclumes 3D, pas d'étincelles animées en continu. La métaphore vit dans le nom et le vocabulaire, pas dans la décoration.

## 2. Couleurs

Tokens CSS à copier tels quels :

```css
:root {
  /* accent de marque */
  --forge-coral-50:  #FAECE7;
  --forge-coral-400: #D85A30; /* couleur signature : logo, CTA, accents */
  --forge-coral-900: #4A1B0C; /* texte sur fond coral clair */

  /* succès / actif */
  --forge-teal-50:  #E1F5EE;
  --forge-teal-400: #1D9E75;
  --forge-teal-900: #04342C;

  /* attention / budget */
  --forge-amber-50:  #FAEEDA;
  --forge-amber-400: #EF9F27;
  --forge-amber-900: #412402;

  /* information / LLM */
  --forge-blue-50:  #E6F1FB;
  --forge-blue-400: #378ADD;
  --forge-blue-900: #042C53;

  /* neutre / structure */
  --forge-gray-50:  #F1EFE8;
  --forge-gray-400: #888780;
  --forge-gray-900: #2C2C2A;

  /* surfaces */
  --forge-bg-dark:      #16140F; /* fond app par défaut */
  --forge-surface-dark: #201D17; /* cartes en dark mode */
  --forge-bg-light:     #FFFFFF;
  --forge-surface-light:#F7F6F3;
}
```

| Couleur | Usage | Ne jamais utiliser pour |
|---|---|---|
| Coral 400 | Logo, CTA principal, accents de marque | Statuts d'erreur (utiliser une teinte rouge sémantique séparée si besoin) |
| Teal 400 | Agent actif, succès, "en cours" | Éléments neutres |
| Amber 400 | Budget/quota à surveiller, avertissement | Succès |
| Bleu 400 | Info, tiers LLM, liens | Boutons d'action primaire |
| Gris 400/900 | Texte secondaire, éléments en veille | Accent de marque |

Règles : aucun dégradé, aucun glow/néon, surfaces toujours plates. La couleur porte un sens (statut), jamais la décoration seule.

## 3. Typographie

```css
:root {
  --font-ui:   "Inter", "Geist", system-ui, sans-serif; /* interface, texte courant */
  --font-mono: "JetBrains Mono", "Berkeley Mono", monospace; /* code, logs, ids d'agents, terminal */
}
```

- Poids autorisés : **400 (regular) et 500 (medium) uniquement.** Jamais 600/700 — trop lourd.
- Casse : phrase normale partout. Jamais MAJUSCULES, jamais Casse De Titre — y compris dans les libellés d'UI.
- Échelle : h1 22px / h2 18px / h3 16px (poids 500) — body 16px/400, line-height 1.7 — caption/label 12–13px.
- `--font-mono` s'utilise pour : identifiants d'agents, logs d'exécution, valeurs de tokens/coûts, blocs de code.

## 4. Espacement et rayons

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  --radius-md: 8px;  /* boutons, badges, inputs */
  --radius-lg: 12px; /* cartes */
  --radius-xl: 16px; /* conteneurs larges */
}
```

- Pas de coins arrondis sur une bordure à un seul côté (`border-left`/`border-top` accent → `radius: 0`).
- Bordures : `0.5px solid` en usage par défaut, jamais plus épais que 1px.

## 5. Composants de référence

### Carte standard
```css
.forge-card {
  background: var(--forge-surface-dark);
  border: 0.5px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-lg);
  padding: 1rem 1.25rem;
}
```

### Carte métrique (dashboard)
Label 13px muted au-dessus, valeur 24px/500 en dessous. Fond `--forge-surface-dark`, pas de bordure.

### Badge de statut
| Statut | Fond | Texte |
|---|---|---|
| en cours / actif | `--forge-teal-50` (light) ou teal 900 fill | teal-900 / teal-50 |
| en attente / veille | `--forge-gray-50` | gray-900 |
| bloqué / erreur | `--forge-coral-50` | coral-900 |
| info | `--forge-blue-50` | blue-900 |

```html
<span style="font-size:11px;padding:2px 8px;border-radius:8px;background:#E1F5EE;color:#04342C;">en cours</span>
```

### Bouton primaire
Fond `--forge-coral-400`, texte blanc, `radius-md`, aucun dégradé, état hover = assombrir de ~10%, état actif = `scale(0.98)`.

### Icônes
Tabler **outline** uniquement (`ti ti-{nom}`), jamais `-filled`, jamais d'emoji. Set de base : `ti-flame` (marque), `ti-cpu` (agents), `ti-network` (orchestrateur/neural map), `ti-battery-2` (budget), `ti-bolt` (RTK/performance), `ti-git-branch` (orchestrateur), `ti-list-check` (tâches), `ti-coin` (coût).

## 6. États et motion

- **Vide** : toujours actionnable ("lancer votre premier agent"), jamais un écran gris passif.
- **Chargement** : squelettes plats, jamais de spinner isolé générique.
- **Erreur/blocage** : message + action concrète ("relancer", "voir le détail").
- **Temps réel** : statuts d'agents et neural map mis à jour en direct (WebSocket/SSE), jamais de rafraîchissement manuel.
- **Seule animation tolérée** : micro-pulsation discrète sur badge "en cours" ou lien actif de la neural map. Durée courte, `transform`/`opacity` uniquement, toujours enveloppée dans `@media (prefers-reduced-motion: no-preference)`.

## 7. À faire / à éviter

| À faire | À éviter |
|---|---|
| Chiffres réels visibles (tokens, coûts, agents) | Jargon marketing creux |
| Dark mode natif, surfaces plates | Dégradés, glow, néon |
| Accent coral utilisé avec retenue | Cliché forgeron (enclumes, étincelles en continu) |
| Micro-interaction qui informe | Animation décorative sans signification |

## 8. Palette de mockups déjà validés

Dashboard, Orchestrateur (Kanban), Router LLM, Token budget & RTK, Neural map 2D — servent de guide de composition, pas de spec pixel-perfect. Toute nouvelle vue doit réutiliser ce même vocabulaire de tokens.
