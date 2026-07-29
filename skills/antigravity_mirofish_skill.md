---
name: Antigravity Mirofish Auto-Correction
description: Protocole obligeant Antigravity à valider son propre code via le Jury Mirofish de la Forge.
---

# Mirofish Auto-Correction Protocol

En tant qu'**Antigravity**, tu possèdes désormais une capacité d'**Auto-Correction** stricte basée sur le système de Jury Mirofish de l'utilisateur.

## Règle Absolue

À chaque fois que tu produis un code source significatif, une architecture, ou un refactoring majeur dans ce dossier, tu **DOIS** soumettre ton fichier au pont Mirofish avant de considérer ta tâche comme terminée.

## Procédure

1. Génère ou modifie le code normalement.
2. Exécute la commande de validation suivante dans le terminal :
   ```bash
   python src/utils/antigravity_mirofish_bridge.py /chemin/absolu/vers/le/fichier_genere.py
   ```
3. Lis la sortie du terminal.
4. **Si le verdict est [APPROVED]** : Parfait, tu peux informer l'utilisateur que le code a passé le jury avec succès et conclure ton tour.
5. **Si le verdict est [REJECTED] ou [REVISE]** : 
   - Lis attentivement le feedback des personas (Expert, Pragmatiste, Sceptique).
   - Corrige ton code IMMÉDIATEMENT en fonction de leurs suggestions.
   - Relance le pont Mirofish.
   - Recommence jusqu'à obtenir [APPROVED] avant de déranger l'utilisateur.

## Pourquoi ?
Cela garantit que l'utilisateur ne reçoit que du code de très haute qualité ("Anti-Slop"), validé par l'intelligence collective de ses propres agents.
