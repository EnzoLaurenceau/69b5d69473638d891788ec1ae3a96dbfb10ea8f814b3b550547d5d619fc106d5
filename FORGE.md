# ⚡ LA FORGE — Super Agent Workspace
> `C:\Users\Enzo\Documents\MODELS\.claude`
> v1.0 · 2026-05-28 · Architecture by AZylee

## Principe
Workspace persistant pour le système multi-agents AGENT_WORKFLOW_SYSTEM v1.0.
Toute session Claude repart de ce dossier. Rien n'existe si ce n'est pas ici.

---

## Arborescence

```
.claude/
│
├── FORGE.md                    ← CE FICHIER — carte de navigation
├── projects/                   ← Sessions Claude Code (auto-géré)
├── skills/                     ← Skills installés (auto-géré)
│
├── 00_CORE/                    ── FONDATION SYSTÈME
│   ├── ARCHITECTURE.md         ← Diagramme des couches L0→L3
│   ├── CAVEMAN_PROTOCOL.md     ← Règles format inter-agents
│   └── TOKEN_BUDGET.md         ← Config budgets tokens par phase
│
├── 01_ORCHESTRATOR/            ── L1 · CHEF D'ORCHESTRE
│   ├── config.json             ← Paramètres orchestrateur actifs
│   ├── cycles/                 ← Logs caveman par cycle
│   └── prompts/                ← Templates de prompts réutilisables
│
├── 02_AGENTS/                  ── L2 · AGENTS SPÉCIALISTES
│   ├── scraper/                ← Sources, stratégie, rate-limits
│   ├── research/               ← Synthèse & templates
│   └── critic/                 ← Scoring rubric & seuils
│
├── 03_JURY/                    ── L3 · MIROFISH JURY
│   ├── personas.json           ← 5-7 personas avec personnalités
│   ├── config.json             ← Rounds, consensus_min
│   └── verdicts/               ← Verdicts par cycle
│
├── 04_GRAPHIFY/                ── L0 · MÉMOIRE COLLECTIVE (71.5x)
│   ├── graph.json              ← SOURCE OF TRUTH
│   ├── wiki/                   ← Articles markdown
│   └── cache/                  ← SHA256 anti-reprocessing
│
├── 05_STATE/                   ── ÉTAT & CHECKPOINTS
│   ├── checkpoint.json         ← Niveau, cycle, règles actives
│   ├── complexity_score.json   ← Historique qualité
│   ├── active_rules.json       ← Règles algo en vigueur
│   └── skip_list.json          ← Sources à ignorer
│
├── 06_FINDINGS/                ── FINDINGS TRIÉS
│   ├── confirmed/              ← Jury ≥ 0.7
│   ├── pending/                ← En attente jury
│   └── killed/                 ← Critic < 5 (archivés)
│
├── 07_KNOWLEDGE_BASE/          ── RESSOURCES & DONNÉES
│   ├── external_resources.json ← Index des ressources externes (NMP)
│   ├── index.json              ← Index skills KB
│   ├── patterns/               ← Design patterns réutilisables
│   └── skills/                 ← Skills extraites
│
├── 07_REPORTS/                 ── RAPPORTS FINAUX
├── 08_LOGS/                    ── LOGS INTERNES
│   ├── cycles/
│   └── debug/
└── 09_TASKS/                   ── FILE SCRAPING
    ├── queue/
    └── done/
```

---

## Ressources Externes Intégrées

| Ressource | Type | Priorité | Module Forge |
|-----------|------|----------|--------------|
| [LMCache](https://github.com/lmcache/lmcache) | Infrastructure KV Cache | 🔴 CRITICAL | `lmcache_integration.py` |
| [Agent Skills](https://github.com/addyosmani/agent-skills) | SDLC Governance | 🟠 HIGH | `agent_skills_patterns.py` |
| [SVG Doodles](https://svgdoodles.com) | Design Assets SVG | 🟡 MEDIUM | `design_assets.py` |
| [Footer.design](https://footer.design) | Design Reference | 🟡 MEDIUM | `design_assets.py` |

---

## Règles d'or
1. Même résultat, moins de tokens
2. Jamais de raw output dans le contexte
3. Caveman entre tous les éléments
4. Vérifier avant d'évoluer
5. 05_STATE = la mémoire persistante
6. Sécurité d'abord — ZSL + Herald audit sur tout output
7. Ship fast — ressources externes = accélérateurs

