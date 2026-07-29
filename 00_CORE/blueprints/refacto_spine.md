# Refacto Spine — Forge respecte ses propres règles

> Principe ponytail : on **unifie l'existant**, on ne réécrit rien. ~6-8 fichiers touchés.
> 4 problèmes ciblés (décision user) : honnêteté, tokens, vraie boucle, règles respectées.
> Orca (onorca.dev) = inspiration worktree-isolé seulement, zéro dépendance.

## Constat (code réel lu)

| Existe déjà | Fichier | Problème |
|---|---|---|
| 4 caches LLM | `inference_patch`, `cervelet`, `forge_fingerprint`, `semantic_cache` | dispersés dans `forge_call`, jamais tous appliqués, dupliqués |
| Batching | `forge_mimo.MimoBatcher`, `tool_batcher` | pas au niveau `forge_call` (micro-appels isolés) |
| 5 mod. honnêteté | `anti_hallucination`, `neuro_symbolic_guard`, `hallucination_judge`, `forge_no_mistakes`, `harness_engine` | vérifient mais **ne pausent jamais** → retry ou continue, **jamais « je sais pas → humain »** |
| Gates règles | `legal_compliance.legal_check`, herald grade | modules OK mais pas 1 choke-point unique avant DELIVER |
| Boucle | `forge_graph` (orchestrator→agent→verify→complexify→loop) | déjà une boucle, juste à nommer explicitement + insérer 2 gates |

## Spine = 3 piliers + 1 contrôleur

### Pilier 1 — Gateway LLM unifié (tokens)
**But** : CHAQUE appel LLM passe par 1 seul point qui empile toutes les optims, dans l'ordre.
- `forge_gateway.py` (fin, ~120 l) : `cervelet reflex → cache unifié (exact+semantic) → batch coalescer → provider`.
- **Cache** : facade `cache_get/cache_set` par-dessus les 3 caches existants (fingerprint+semantic+inference). On **dédupe** (on n'ajoute pas un 5e cache) : 1 lookup, 1 store.
- **Batch** : généralise `MimoBatcher` à tous providers — fenêtre courte, coalesce N micro-prompts → 1 appel. Opt-in par les nœuds qui bouclent.
- `forge_call` route via gateway. Providers inchangés.
- ponytail : si 2 caches se recouvrent à >90 %, on en supprime un, on n'abstrait pas.

### Pilier 2 — Gate honnêteté + escalade humaine (HITL) ← le vrai manque
**But** : modèle ne sait pas → il le **dit** + **appelle un humain**, zéro invention.
- Nœud `honesty_gate` après vérif : score confiance/grounding (réutilise `meta.uncertainty` déjà dans le state + juges existants).
- Sous seuil OU auto-incertitude OU claim non-groundé → émet `ESCALATE_HUMAN`, écrit la question dans `05_STATE/human_queue.json`, et **`interrupt()` LangGraph natif** pause le graphe. Reprise quand l'humain répond.
- `forge_call` : appel isolé sous seuil → retourne sentinelle `UNKNOWN:<raison>` au lieu d'halluciner (l'appelant décide d'escalader).
- Réutilise `anti_hallucination` + `neuro_symbolic_guard` comme scorers, ne les remplace pas.

### Pilier 3 — Gate DELIVER (règles)
**But** : 1 choke-point unique = la Forge respecte ses blueprints.
- Nœud `deliver_gate` avant fin : `legal_check` + herald grade + grounding/re-rank existants.
- Un échec (legal < B, herald < C, grounding manquant) → **bloque DELIVER**, route back ou escalade humaine.

### Contrôleur — Loop engineer
- Renomme les phases du graph existant en boucle explicite : `OBSERVE → PLAN → ACT → VERIFY → GATE → (ESCALATE|REPEAT|DELIVER)`.
- Insère `honesty_gate` (après VERIFY) et `deliver_gate` (avant END). Machinerie de boucle déjà là.
- Orca-inspired : isolation worktree seulement là où la flotte écrit en parallèle (réutilise `openhands.run_fleet`). Pas de dépendance Orca.

## Phase 0 — Audit câblage (sandbox, ~0 token contexte)
Cartographier le wiring exact des 4 caches + 5 mod. honnêteté + point DELIVER réel, pour **supprimer la duplication** au lieu d'ajouter. Sortie : liste précise fichiers/lignes à toucher.

## Fichiers touchés (estimé)
`forge_gateway.py` (new) · `forge_llm.py` (route via gateway + sentinelle UNKNOWN) · `honesty_gate` (new node) · `deliver_gate` (new node) · `forge_graph.py` (wire + rename phases) · `auto_complexification.py`/`agent_nodes.py` (routing) · `forge_state.py` (2-3 champs : `human_pending`, `confidence`, `deliver_blocked`).

## Non-fait exprès (à demander si besoin)
- Pas de réécriture des 30 modules `forge_agents/`.
- Pas d'intégration Orca runtime (inspiration seulement).
- Pas de nouveau cache/juge — on unifie.
