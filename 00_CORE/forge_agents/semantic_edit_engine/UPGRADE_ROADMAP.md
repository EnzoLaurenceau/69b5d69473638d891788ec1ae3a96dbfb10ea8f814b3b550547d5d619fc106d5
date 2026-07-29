# Semantic Edit Engine — Upgrade Roadmap

> Ce fichier est la référence unique pour les évolutions futures du SEE.
> Maintenu par la Forge. Mis à jour après chaque phase livrée.

---

## Phase actuelle : Phase 1 ✅ (livrée 2026-07-22)

> ⚠️ Correction d'honnêteté (2026-07-22) : la Phase 1 avait été déclarée livrée le
> 2026-07-18 alors que `SemanticPatchOptimizer` était un stub (une seule règle,
> `if "timeout" in instruction`) et que le module entier était **orphelin** — importé
> nulle part hors de son propre test. Le statut ci-dessous reflète le code réel.

### Livré (vérifié par `test_see.py`)
- SymbolResolver avec fallback regex
- **EditPrimitives** — 4 primitives (`Replace`, `InsertAfter`, `DeleteRange`, `ReplaceSymbolBody`)
- **`derive_ops()`** — dérivation déterministe, 0 token, des plans candidats
  (stratégies character / token / statement / semantic) + vérification stricte
  que chaque plan reproduit exactement la cible
- **SemanticPatchOptimizer réellement multi-stratégie** — coût MCPT composite
  (emit / chars / lignes / nb d'ops) + plancher de sûreté sur le PatchScorer
- PatchScorer 6 critères pondérés
- AutoRollback transactionnel
- EditMetrics + **sink réel** vers `05_STATE/forge_metrics.jsonl` (`record_edit`)
- IntelligentContextWindow
- PatchMemory via Graphify
- **Câblage** : `00_CORE/tools/see_edit.py` (`plan_minimal_edit` / `apply_minimal_edit` + CLI)

### Non livré (contrairement à la déclaration initiale)
- Tree-sitter comme parser AST universel multi-langage → le resolver fonctionne
  en Python + fallback regex ; l'universalité reste à prouver langage par langage.
- « EditMetrics 18 métriques » : les champs existent, une partie reste à 0
  (tree_edit_distance, test_time_ms, rollback_rate, hallucination_rate).

---

## Phase 2 — Patch Review + Semantic Safety ✅ (livrée 2026-07-22)

**Statut** : ✅ livrée — vérifiée par `test_see.py` sections [6] à [9]

### 2.1 Patch Review Pipeline (`patch_review.py`)
- [x] Static Analyzer — Ruff / ESLint / Semgrep, **tous optionnels** (aucun installé
      sur la machine actuelle → reportés en `tools_skipped`, jamais fatals)
- [x] Delta avant/après — seuls les diagnostics **introduits** par le patch bloquent
- [ ] Reviewer Agent (LLM) — non livré : le delta déterministe suffit pour l'instant
- [ ] Formatter Checker (Black/Prettier) — non livré
- [ ] Pipeline LangGraph multi-agent — non livré (le pipeline est procédural, cf. 2.3)

### 2.2 Semantic Safety (`semantic_safety.py`)
- [x] Détection suppression d'API publique → BLOCK
- [x] Détection changement de signature publique → WARN
- [x] Intégrité des imports (import retiré encore utilisé) → BLOCK
- [x] Références pendantes introduites par le patch → BLOCK
- [x] Syntaxe → BLOCK
- [x] Exécution des tests impactés → via `edit_pipeline` (`test_cmd`)
- [ ] Détection d'effets de bord — non livré (nécessiterait une analyse de flux)

### 2.3 Boucle complète (`edit_pipeline.py`) + gate impact (`impact_gate.py`)
- [x] `plan → impact → revue → application → tests → diff` avec rollback à chaque étage
- [x] Blast radius GitNexus exécutable (CRITICAL → BLOCK, HIGH → WARN, absent → non bloquant)
- [x] `force=True` tracé dans le résultat
- [x] Câblé dans `00_CORE/tools/see_edit.py` (`--test`, `--force`)

---

## Phase 3 — Intelligence & Learning

**Statut** : 🔲 À faire

### 3.1 Patch Learning (`patch_learning.py`)
- [ ] ML sur PatchMemory — prédiction meilleure stratégie
- [ ] Ajustement dynamique des poids PatchScorer
- [ ] Détection de patterns de régression
- [ ] Scoring adaptatif par projet

### 3.2 Reinforcement Learning
- [ ] Feedback loop: patch appliqué → test → reward signal
- [ ] Bandit multi-bras pour sélection de stratégie

---

## Phase 4 — LSP Integration

**Statut** : 🔲 À faire (upgrade Tree-sitter → LSP)

### 4.1 Serveurs LSP supportés
- [ ] Pyright / Pylsp (Python)
- [ ] tsserver (TypeScript/JavaScript)
- [ ] gopls (Go)
- [ ] rust-analyzer (Rust)
- [ ] jdtls (Java)
- [ ] clangd (C/C++)

### 4.2 Fonctionnalités LSP ciblées
- [ ] Go to Definition — résolution de symboles cross-file
- [ ] Find References — recherche de références projet-wide
- [ ] Rename Symbol — renommage sûr avec mise à jour de toutes les refs
- [ ] Code Actions — suggestions de correction automatique
- [ ] Diagnostics — erreurs/warnings en temps réel
- [ ] Hover — information de type pour scoring sémantique

### 4.3 Architecture LSP
```
SymbolResolver
    ├── Tree-sitter (actuel, rapide, local)
    └── LSP Client (futur, précis, cross-file)
         ├── pygls (Python LSP client)
         ├── Protocole: JSON-RPC sur stdio
         └── Lifecycle: start → initialize → textDocument/* → shutdown
```

### 4.4 Migration
- Tree-sitter reste le backend par défaut (rapide, offline)
- LSP activé par configuration quand disponible
- Fallback automatique Tree-sitter → regex si LSP non démarré

---

## Phase 5 — Advanced Technologies

**Statut** : 🔲 Exploration future

### 5.1 AST Diff avancé
- [ ] GumTree — diff structurel d'AST
- [ ] Tree Edit Distance (TED) — distance minimale entre arbres
- [ ] ChangeDistiller — extraction fine des changements

### 5.2 Semantic Patching
- [ ] Comby — pattern matching structurel
- [ ] Coccinelle — semantic patching (C/Linux kernel style)

### 5.3 Analyse statique profonde
- [ ] CodeQL — requêtes de sécurité sur le code
- [ ] SonarQube — qualité continue
- [ ] Clang-Tidy (C/C++)

### 5.4 Parsers spécialisés (alternative/complément Tree-sitter)
- [ ] LibCST (Python) — CST complet avec whitespace
- [ ] Roslyn (.NET) — compilation-as-a-service
- [ ] ts-morph (TypeScript) — manipulation TypeScript programmatique
- [ ] JavaParser — AST Java manipulable
- [ ] Babel Parser — JavaScript/JSX/TSX

---

## Changelog

| Date | Phase | Changement |
|------|-------|-----------|
| 2026-07-18 | Phase 1 | Création initiale — 8 modules core (optimizer stubbé, module orphelin) |
| 2026-07-22 | Phase 1 | MCPT réel : edit_primitives.py + derive_ops + optimizer multi-stratégie + sink métriques + câblage `tools/see_edit.py` + suite de tests 5 cas |
| 2026-07-22 | Phase 2 | semantic_safety.py + patch_review.py + impact_gate.py + edit_pipeline.py ; suite de tests portée à 9 sections. Bug corrigé : `source_text` sans newline final produisait un patch fantôme sur cible identique |
