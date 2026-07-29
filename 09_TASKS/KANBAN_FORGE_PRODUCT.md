# Kanban — Forge cognitive & produit (issu du triage GPT 2026-07-22)

> Source triage : `09_TASKS/analysis/TRIAGE_GPT_FORGE_2026-07-22.md`
> Board machine : `05_STATE/kanban/forge_product_board.json`
> Colonnes : `backlog` → `todo` → `doing` → `review` → `done` · `dropped`

---

## WAVE 1 — Rendre vrai le différenciateur (MCPT / édition minimale)

| ID | Tâche | Fichier cible | Est. | Statut |
|---|---|---|---|---|
| W1-01 | Remplacer le stub `optimize()` par un vrai générateur **multi-stratégie** (CHARACTER / TOKEN / STATEMENT / SEMANTIC) + sélection min-coût via `PatchScorer` | `semantic_edit_engine/patch_optimizer.py` | M | ✅ done |
| W1-02 | Primitives d'édition minimales (4, pas 13) : `Replace(anchor)`, `InsertAfter`, `DeleteRange`, `ReplaceSymbolBody` — appliquées par ancre, sans réécriture de ligne | `semantic_edit_engine/edit_primitives.py` | M | ✅ done |
| W1-03 | ~~`EditPlanner` séparé~~ | — | — | ⛔ dropped — fusionné dans W1-01 : `SemanticPatchOptimizer.candidates()` **est** le planner (ponytail : pas de 2ᵉ module) |
| W1-04 | Câbler SEE dans la Forge : `plan_minimal_edit()` / `apply_minimal_edit()` + CLI | `00_CORE/tools/see_edit.py` | M | ✅ done |
| W1-05 | Émettre les métriques d'édition vers `forge_metrics` | `semantic_edit_engine/edit_metrics.py` | S | ✅ done |
| W1-06 | Tests réels sur 5 cas variés — plus aucun cas hardcodé | `semantic_edit_engine/test_see.py` | S | ✅ done |
| W1-07 | Corriger `UPGRADE_ROADMAP.md` : Phase 1 n'était pas livrée | `semantic_edit_engine/UPGRADE_ROADMAP.md` | XS | ✅ done |

**Definition of done WAVE 1** : ✅ atteinte — 5 cas de test, plan gagnant strictement moins coûteux que la réécriture, `py_compile` OK, métriques dans `forge_metrics.jsonl`.

### Résultats mesurés (WAVE 1)

| Cas | Stratégie gagnante | Coût d'émission | Réécriture | Gain |
|---|---|---|---|---|
| ajout condition (`if user` → `if user and user.is_active`) | character (`InsertAfter`) | 36 | 90 | −60 % |
| ajout paramètre | character | 63 | 72 | −13 % |
| ajout import | character | 26 | 57 | −54 % |
| suppression ligne morte | character (`DeleteRange`) | 16 | 24 | −33 % |
| renommage local | token (`Replace`) | 72 | 82 | −12 % |

Le cas d'école demandé est bien résolu comme voulu :
`InsertAfter(anchor=" user", text=" and user.is_active")` — on n'efface rien, on ajoute.

> Bug réel trouvé **par les tests** puis corrigé : la suppression pure passait par un
> `Replace` avec ancre complète (coût 29 > réécriture 24) faute d'émettre `DeleteRange`.
> Corrigé dans `derive_ops` → coût 16.

---

## WAVE 2 — Modification de code sûre (boucle complète) — ✅ **LIVRÉE 2026-07-22**

> Gelée puis dégelée par la décision **option C** (`POSITIONING.md` §6).

| ID | Tâche | Fichier | Est. | Statut |
|---|---|---|---|---|
| W2-01 | Pipeline `plan → impact → revue → apply → tests → diff`, rollback à chaque étage | `semantic_edit_engine/edit_pipeline.py` | L | ✅ done |
| W2-02 | `patch_review.py` : Ruff/ESLint/Semgrep **optionnels** + delta avant/après | `semantic_edit_engine/patch_review.py` | M | ✅ done |
| W2-03 | `semantic_safety.py` : API publique, imports, refs pendantes, syntaxe | `semantic_edit_engine/semantic_safety.py` | M | ✅ done |
| W2-04 | Gate GitNexus `impact()` **exécutable** (plus une règle humaine) | `semantic_edit_engine/impact_gate.py` | S | ✅ done |

**Definition of done WAVE 2** : ✅ atteinte — suite portée à 9 sections, `ALL TESTS PASSED`.

### Décisions de conception (WAVE 2)

- **Seuls les diagnostics introduits bloquent.** On lint l'avant ET l'après, on soustrait.
  Sinon tout patch sur un fichier sale serait rejeté pour de la dette qu'il n'a pas créée.
- **Un outil absent ne bloque jamais.** ruff/semgrep/eslint ne sont pas installés sur cette
  machine → reportés en `tools_skipped`. Un analyseur manquant se voit, il n'arrête pas le travail.
- **Le gate impact devient du code.** `CLAUDE.md` imposait déjà « impact() avant édition » —
  une consigne s'oublie, un gate non. Vérifié réellement : `forge_call` → `CRITICAL`,
  325 symboles, 55 flux → BLOCK.
- **`force=True` existe mais laisse une trace** dans le résultat et les métriques.

> Bug réel trouvé par les tests : `symbol_resolver.source_text` retire le saut de ligne final,
> donc une cible identique produisait un patch fantôme d'un caractère. Corrigé dans
> `patch_optimizer` (comparaison hors bordure).

---

## WAVE 3 — Observabilité & santé (produit visible) — ❄️ **GELÉE 2026-07-22**

| ID | Tâche | Est. | Statut |
|---|---|---|---|
| W3-01 | Vue « par tâche » sur le dashboard :7777 — temps / LLM / coût / tokens / latence / qualité / historique (données déjà dans `forge_metrics.jsonl`) | M | backlog |
| W3-02 | Scan dette technique périodique (duplication, fichiers trop gros, complexité, imports morts, deps obsolètes) → `05_STATE/tech_debt.json` | M | backlog |
| W3-03 | Priorisation de la dette par impact (croisement avec GitNexus : symboles les plus appelés d'abord) | M | backlog |
| W3-04 | Page « santé du dépôt » : complexité, couverture, dette, coût IA, modules instables | M | backlog |

---

## WAVE 4 — Cadrage produit (docs, pas code)

| ID | Tâche | Est. | Statut |
|---|---|---|---|
| W4-01 | `00_CORE/blueprints/mcpt.md` — MCPT formalisé : fonction de coût, 4 primitives, contraintes de sûreté, limites connues | S | ✅ done |
| W4-02 | `POSITIONING.md` — carte concurrentielle, état vérifié, phrase de positionnement, 3 options de périmètre | S | ✅ done |
| W4-03 | Trancher A / B / C et dégeler la wave correspondante | S | 🔶 **décision utilisateur — en attente** |

---

## DROPPED (décidé, ne pas revenir dessus)

| Élément | Raison |
|---|---|
| 13 primitives d'édition | YAGNI — 4 couvrent >90 % ; le reste = refactos, autre problème |
| Observabilité maison type LangSmith | LangSmith déjà branché (`forge_observability.py`) + métriques maison |
| Concurrencer Cursor/Windsurf sur la génération | Hors thèse, coût prohibitif (GPT le dit lui-même) |
| Niveau 3 « moteur sémantique » complet | Prématuré tant que Niveaux 1-2 ne tournent pas |
| Refaire compréhension de dépôt / mémoire / impact / routing coût | Déjà livrés et fonctionnels — vérifiés dans le code |
| Bot de revue de PR | Différé : suppose un produit hébergé qui n'existe pas encore |
