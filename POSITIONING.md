# POSITIONING — Super Agent Forge

> Créé : 2026-07-22 · Board : `05_STATE/kanban/forge_product_board.json` (WAVE 4)
> Base factuelle : `09_TASKS/analysis/TRIAGE_GPT_FORGE_2026-07-22.md` (état vérifié dans le code)
> **Ce document existe pour geler un périmètre avant d'investir davantage.**

---

## 1. Le problème à trancher

Le risque n'est pas technique, il est de positionnement. Formulé crûment :

> **10 briques excellentes, aucune assez indispensable pour qu'un client paie.**

Preuve que le risque est déjà là : la brique la plus différenciante sur le papier
(édition minimale) était déclarée livrée depuis 4 jours alors que son cœur était un stub
et que personne ne l'appelait. Une brique que rien n'utilise n'a pas de valeur — quelle
que soit sa qualité.

Test de survie : répondre en < 10 secondes à « à quoi sert la Forge ? ».
Aujourd'hui la réponse honnête est « à beaucoup de choses », ce qui signifie « à rien de précis ».

## 2. Carte concurrentielle

| Couche | Acteurs | Ce qu'ils possèdent | Position de la Forge |
|---|---|---|---|
| Agents de dev | Claude Code, OpenHands, Codex CLI, Cursor, Windsurf | la génération de code, la distribution, l'IDE | ⛔ **ne pas attaquer** — coût prohibitif, aucun avantage |
| Frameworks d'agents | LangGraph, CrewAI, AutoGen, Mastra, Agents SDK | la construction de workflows | 🟡 la Forge en est un **utilisateur** (LangGraph), pas un concurrent |
| Observabilité IA | LangSmith, Langfuse, Helicone, Phoenix, Weave | traces, coûts, latence | ⛔ **déjà intégré** (LangSmith branché) — recréer serait de la redondance |
| Mémoire IA | Mem0, Zep, Letta | persistance d'agent | 🟡 la Forge a la sienne (`forge_experience_db`, graphify) — pas un produit à part |
| Infra LLM | LiteLLM, OpenRouter, Portkey, Vercel AI Gateway | routage, compatibilité | ⛔ commodité, marché déjà pris |
| Recherche de code | Sourcegraph, Continue, Aider | compréhension de dépôt | 🟡 GitNexus couvre déjà le besoin en interne |
| **Coût de transformation** | **— personne —** | **—** | ✅ **le seul espace vide** |

La dernière ligne est le point important. Tous les acteurs optimisent *la qualité de la
sortie*. Aucun n'optimise *le coût de la modification*. C'est là qu'un positionnement
défendable existe — et c'est le seul endroit où la Forge a déjà du code qui tourne.

## 3. Ce qui est réellement livré (vérifié, pas déclaré)

| Brique | État | Preuve |
|---|---|---|
| Édition de coût minimal (MCPT) | ✅ niveau 1-2, testé | `test_see.py` — 5 cas, gains 12-60 % |
| Observabilité (tokens/latence/coût/qualité) | ✅ | `forge_metrics.jsonl` + LangSmith + dashboard :7777 |
| Compréhension de dépôt | ✅ | GitNexus — 83 150 symboles, 111 561 relations |
| Analyse d'impact | ✅ | `impact()` GitNexus, gate humain dans CLAUDE.md |
| Mémoire persistante | ✅ | `forge_experience_db`, `patch_memory`, graphify |
| Optimisation de coût LLM | ✅ | tiers, fingerprint zero-redundancy, cache sémantique, RTK |
| Modification sûre bout-en-bout | 🔲 gelé | WAVE 2 — **volontairement non commencée** |
| Dette technique / santé dépôt | 🔲 backlog | WAVE 3 |

Six briques sur huit sont réelles. Ce n'est pas un problème de construction, c'est un
problème de **choix**.

## 4. Positionnement proposé

> **La Forge exécute des agents IA en optimisant le coût de chaque transformation —
> et rend ce coût visible, mesurable et réductible.**

Trois différenciateurs, dans cet ordre :

1. **Transformation de coût minimal (MCPT).** L'agent ne réécrit pas, il choisit le plan
   d'édition le moins cher qui reste sûr. Personne d'autre ne formule le problème ainsi.
2. **Observabilité native par transformation.** Chaque édition émet stratégie, coût
   d'émission, caractères/lignes touchés, économie en tokens, score de sûreté.
3. **Mémoire persistante** des décisions, patchs et échecs — le système devient
   progressivement moins cher sur un même dépôt.

Ce qu'on ne revendique pas : générer du meilleur code que Claude Code ou Cursor.

## 5. Les trois périmètres possibles (à trancher)

### Option A — « Le moteur d'édition le moins cher »
Terminer WAVE 2 (patch → review → tests → diff/PR) et faire du MCPT un produit à part
entière, utilisable par d'autres agents.
*Pour* : creuse le seul espace vide, code déjà à 60 %. *Contre* : brique d'infra —
se vend à des constructeurs d'agents, marché étroit.

### Option B — « Comprendre et faire évoluer un dépôt dans la durée »
WAVE 3 d'abord : dette technique + santé du dépôt + vue par tâche, sur la base GitNexus
et `forge_metrics` déjà en place.
*Pour* : besoin quotidien, acheteur identifié (équipes), briques déjà là.
*Contre* : marché occupé (Sourcegraph, SonarQube) — la différence tiendrait au MCPT et
à la mémoire, donc dépend de A.

### Option C — « Plateforme d'exécution observable pour agents »
Le positionnement large de la §4, vendu comme infrastructure.
*Pour* : cohérent avec l'architecture réelle. *Contre* : c'est exactement le risque
« 10 briques, aucune indispensable ». **Non recommandé tant qu'aucune brique n'a de
premier usage réel.**

### Recommandation formulée le 2026-07-22
**A puis B** — terminer MCPT jusqu'au dogfooding, mesurer 30 jours, décider ensuite.

## 6. DÉCISION — Option C (arrêtée le 2026-07-22)

**Périmètre retenu : C — Plateforme d'exécution observable pour agents IA.**

> **La Forge est une plateforme d'exécution pour agents IA qui rend chaque décision
> observable, mesurable et optimisable.**

Décision prise en connaissance du risque documenté en §5 (option C) et en §1.
WAVE 2 et WAVE 3 sont **dégelées** — elles servent toutes deux le positionnement C :
WAVE 2 rend les transformations sûres et traçables, WAVE 3 les rend visibles.

### Garde-fou attaché à la décision

Le risque de C est nommé : *beaucoup de briques, aucune indispensable*. La contre-mesure
n'est pas de réduire le périmètre mais d'imposer une règle d'admission, applicable à
chaque brique livrée sous C :

1. **Une brique n'existe que si quelque chose l'appelle.** Pas d'appelant → pas de « done ».
   (C'est précisément ce qui avait rendu le SEE inutile pendant 4 jours.)
2. **Une brique n'est « livrée » que si un test le prouve.** Le roadmap ne fait pas foi, le code fait foi.
3. **Chaque brique émet ses métriques** dans `forge_metrics.jsonl` — sans mesure, pas d'« optimisable »,
   donc pas de positionnement C.

Ces trois règles sont la condition pour que C soit une phrase vraie plutôt qu'une ambition.

### Ordre d'exécution retenu

`WAVE 2` (sûreté + traçabilité des transformations) → `WAVE 3` (visibilité : dette, santé,
vue par tâche). WAVE 2 d'abord car WAVE 3 affiche ce que WAVE 2 produit.
