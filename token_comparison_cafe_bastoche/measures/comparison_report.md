# FACT-CHECK — Café Bastoche : Claude basique vs Forge

Date : 2026-07-17 · Observabilité : LangSmith projet `super-agent-forge` (ON, `@traced`).

---

## 1. Résultat brut mesuré

| Métrique | **A — SANS Forge** | **B — Forge (run autonome)** |
|---|---|---|
| Site livré | ✅ oui, vérifié navigateur | ❌ **non** (0 fichier, statut ÉCHEC) |
| Modèle génération | claude-opus-4-8 (tier cher) | ds2api-deepseek-v4 (tier FREE) |
| Appels LLM | 1 passe | 20 calls |
| Tokens input | ~4 000 | **20 847** |
| Tokens output | **4 430** (mesuré fichiers) | **13 581** |
| Tokens total | ~8 430 | **34 428** |
| Coût API réel | **~$0.39** | **$0.00** (free tier) |
| Passes anti-hallucination | 0 (mais 0 fait inventé) | jury+MiroFish : REVISE 0.55 → rejet |
| Efficiency score Forge | n/a | **0.0 / 100** |
| Findings confirmés | n/a | 0 |
| Bugs Forge à corriger avant de tourner | 0 | **3** (voir §4) |

Log Forge : `08_LOGS/tokens/cafe_bastoche_B4-20260717-052849.json`

---

## 2. Estimate → Actual (précision de prévision = anti-dérive)

### Version A
| | Estimate | Actual | Écart |
|---|---|---|---|
| Output tokens | 11 000 | 4 430 | **−60 %** (sur-estimé 2,5×) |
| Coût | $0.88 | ~$0.39 | −56 % |
> Leçon : mon estimate baseline était trop pessimiste. Un site café statique = ~4,4k tok, pas 11k.

### Version B (tracker interne Forge)
| | Estimate | Actual | Écart |
|---|---|---|---|
| Input | 28 000 | 20 847 | −25,5 % |
| Output | 10 500 | 13 581 | +29,3 % |
| Coût | $0 | $0 | ✅ exact |
| **Livrable** | site généré | **rien** | ❌ prévision fausse |
> Le tracker prévoit bien les tokens (±30 %) mais 4 modèles planifiés (gemini, groq,
> haiku, sonnet) n'ont **jamais été appelés** → 38 500 tokens de budget « libérés » =
> plan sur-dimensionné. Efficiency 0/100.

---

## 3. Lecture honnête — qui gagne quoi

**Ce que la Forge fait vraiment gagner (confirmé) :**
- **Coût API → $0** : génération 100 % déportée sur free tier (deepseek) vs Opus payant.
- **Contexte Claude protégé** : les 34k tokens de génération n'entrent PAS dans le contexte
  Claude — ils vivent dans les appels free. Le contexte cher reste minimal.
- **Anti-hallucination active** : le jury a réellement **rejeté** l'output faible (consensus
  0.55, décision REVISE). Le mécanisme fonctionne.

**Ce que la Forge coûte / rate (confirmé sur ce run) :**
- **Aucun livrable** : statut ÉCHEC, 0 fichier écrit. Le jury a bloqué un « Fallback_Expert »
  générique au lieu d'un expert dynamique spécialisé → rien ne passe le gate.
- **3 bugs bloquants** dans les modules V6 (untracked) : il a fallu que Claude les corrige
  pour que le graph tourne jusqu'au bout (§4). Ce debugging = vrai coût contexte Claude, invisible
  dans le token-tracker.
- **Efficiency 0/100** : 5,6× plus de tokens bruts que A, plan sur-dimensionné, 0 résultat.

**Baseline Claude :** 1 passe, ~4,4k tokens, site responsive fonctionnel + carte OSM,
0 fait inventé (discipline placeholder auto-imposée, sans jury).

---

## 4. Bugs Forge corrigés pour permettre le run (fidélité)

Le run autonome a crashé 3 fois ; corrections minimales appliquées :

1. `openviking.py` — `_Viking` manquait `get_findings_context()` (appelé par `adaptive_rag.py:199`). Ajouté.
2. `forge_graph.py` — `import threading` manquant (`v6_post_execution_node`, l.287). Ajouté.
3. `auto_complexification.py` — `CavemanMsg(...)` appelé comme constructeur alors que
   `CavemanMsg = str` (NMPPacket pipe). Remplacé par strings NMP `VERB|SRC|OBJ|PAYLOAD`.

Ces 3 fichiers sont dans le batch V6 « untracked/non-indexé » → jamais exécutés end-to-end
avant ce test. Le test a servi de smoke-test involontaire.

---

## 5. Verdict quantifié

| Axe | Gagnant | Chiffre |
|---|---|---|
| Coût API | **Forge** | $0 vs $0.39 |
| Tokens bruts consommés | **Claude** | 8,4k vs 34,4k (4,1×) |
| Contexte cher protégé | **Forge** | génération 100 % off-context |
| Anti-hallucination (mécanisme) | **Forge** | jury REVISE actif vs aucun |
| Anti-hallucination (résultat) | **égalité** | 0 fait inventé des 2 côtés |
| Fiabilité livraison | **Claude** | site livré vs ÉCHEC |
| Précision estimate | **Forge tracker** | ±30 % vs mon −60 % sur A |

**Conclusion :** sur *cette* tâche et *cet* état du code, la Forge prouve son intérêt
structurel (coût nul + off-context + garde-fous jury) mais **échoue à livrer** à cause de
bugs V6 latents et d'un expert fallback trop générique. Le gain token/anti-hallucination
est réel *en potentiel* ; il ne se matérialise pas tant que le chemin dynamic_agent→fichiers
n'est pas fiabilisé. Baseline Claude reste plus rapide et fiable pour un one-shot simple.

> Site B livré séparément en **rescue** (`site_B_avec_forge/`, Claude suivant le blueprint
> Forge) pour disposer de 2 sites comparables visuellement — son coût n'est PAS compté dans
> les chiffres Forge ci-dessus, qui mesurent le run autonome réel.
