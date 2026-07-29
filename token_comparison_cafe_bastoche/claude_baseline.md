# CLAUDE.md — baseline (Version A, SANS Forge)

> Contexte minimal pour le bras témoin. AUCUNE règle Forge (pas de blueprint,
> pas de délégation `forge_call`, pas de jury, pas de token-budget imposé).
> C'est le comportement « Claude par défaut » qu'on veut mesurer.

## Tâche
Génère un site web **responsive**, **design ultra-moderne**, pour le
**Café Bastoche** à **Ixelles** (Bruxelles).

## Contraintes minimales (celles d'un dev lambda)
- HTML/CSS/JS statique, pas de framework lourd.
- Responsive mobile-first.
- Sections attendues d'un site de café : hero, menu, à propos, galerie, horaires, contact + carte.
- Pas de `localStorage` (environnements isolés).

## Ce que Claude fait
Écrit tout le code lui-même, directement. Pas d'outil externe, pas de sous-agent.
