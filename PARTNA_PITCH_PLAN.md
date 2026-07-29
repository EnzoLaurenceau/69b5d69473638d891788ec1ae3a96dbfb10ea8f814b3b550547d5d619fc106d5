# Plan de prospection — Partna

## L'insight qui change l'angle

Partna n'est pas un client "IA-curieux" à qui expliquer que les tokens coûtent cher. C'est une agence — Julius Meto'o Ndongo et Mathis, tous deux ex-Solvay Business School, incubés à StartLab Bruxelles — qui vend elle-même des architectures d'agents IA (leur produit s'appelle OpenClaw, connecté à Hermes) en abonnement à des PME belges : audit, installation, agents sur mesure, maintenance et optimisation mensuelle incluse.

Conséquence directe : à chaque client signé, leur marge dépend du coût d'inférence des agents qui tournent en continu derrière Slack/WhatsApp/Telegram/Discord. Plus ils scalent leur base de clients, plus la facture LLM agrégée pèse sur leur rentabilité. C'est un problème d'unit economics réel pour une boîte jeune (2 fondateurs visibles, stade incubateur), pas du confort.

Le pitch n'est donc pas « utilisez l'IA pour réduire vos coûts » — ils font déjà ça pour leurs clients, ils connaissent le sujet mieux que la moyenne. C'est : *j'optimise ce qui tourne sous OpenClaw* — routing du modèle selon la tâche (pas d'Opus pour trier un email), compression du contexte avant l'appel, cache/batching des appels répétés — pour baisser leur coût d'inférence par client, sans rien changer à ce que voit le client final.

Positionnement à tenir absolument : couche d'optimisation complémentaire à OpenClaw, jamais un concurrent ou un remplaçant.

## Ce qu'ils valorisent (écrit noir sur blanc sur leur propre site)

Leur page "À propos" a une section entière listant ce qu'ils refusent de faire : promesses floues, effet waouh en démo, outils livrés sans adoption réelle. Ils s'y opposent frontalement : "Pas des promesses. Des résultats mesurés chez un vrai client."

Donc : ne pas arriver avec "ma forge est incroyable." Arriver avec un chiffre vérifiable. Tu en as déjà un dans ton propre projet — RTK mesuré à -66% sur un `git status` (785 → 268 caractères), -60 à -90% en général sur les outputs CLI. Montre cet avant/après tel quel plutôt que de vendre le concept en abstrait.

## Structure de l'offre — calquer leur propre funnel

Ils vendent avec un audit gratuit (45 min) et une garantie remboursement dès le premier mois. Reprendre exactement cette mécanique, terrain qu'ils connaissent et respectent déjà :

1. **Audit à bas risque** — pas de ta forge, de LEUR stack : quels modèles/providers derrière OpenClaw, volume d'appels par client actif, où des tâches simples tournent sur un modèle cher. Gratuit ou symbolique, zéro engagement.
2. **Pilote scopé sur un seul workflow** — implémenter routing + compression sur une brique isolée (ex. le tri d'emails ou les réponses SAV qu'ils montrent déjà en démo sur leur site), mesurer le $ économisé en réel sur 2-4 semaines.
3. **Engagement continu** — soit un % des économies mesurées pendant 6-12 mois (risque quasi nul pour eux, aligné avec leur propre logique de garantie), soit un forfait mensuel greffé sur leur abonnement client existant.

## Comment les approcher

Lien faible (connu de vue à la fac, pas un ami) → message court, sans sur-vente, ancré dans un fait précis de leur site plutôt qu'un "salut ça va."

Leur page "À propos" se termine par une invitation à prendre un café — porte déjà ouverte, à reprendre littéralement plutôt qu'inventer une accroche.

Trame du message : qui tu es (1-2 lignes) → un fait concret sur eux (le témoignage client sur les 3h/jour gagnées, ou leur garantie premier mois) → le problème précis que tu résous (coût d'inférence à l'échelle de leur portefeuille clients, pas "l'IA" en général) → le chiffre RTK réel → demande basse friction (15-20 min, pas une proposition commerciale d'entrée).

Ne pas nommer "la forge" comme un produit fini — se présenter comme quelqu'un qui construit et opère un système multi-agents au quotidien et qui a dû résoudre ce problème pour lui-même en premier.

## Inconnues à vérifier au premier échange, pas à deviner avant

- Quels providers/modèles tournent réellement derrière OpenClaw/Hermes.
- Nombre de clients actifs et volume d'appels — sans ça, le chiffre "plusieurs dizaines de milliers de $/mois" reste une moyenne de marché, pas un fait vérifié sur Partna. Ne pas l'avancer comme s'il s'appliquait à eux avant confirmation.
- Taille réelle de l'équipe au-delà des 2 fondateurs affichés — détermine si c'est une conversation founder-to-founder directe ou s'il faut convaincre un tech lead en plus.

## Prochaine action

Rédiger le message d'approche (DM Instagram ou LinkedIn) une fois le canal et le ton (tutoiement probable vu le lien université) confirmés.
