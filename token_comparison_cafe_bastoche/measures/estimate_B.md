# TOKEN ESTIMATE — Version B (AVEC Forge)

Tâche : `cafe_bastoche_site` — `run_forge.py --task`. Claude orchestre, les experts
dynamiques génèrent le code via `forge_call` (tier FREE/Haiku), jury + audit.

```
╔══════════════════════════════════════════════════════════════════════╗
║ TOKEN ESTIMATE — Task: cafe_bastoche_site  [B / Forge]               ║
║ Poste                    │ Est.In  │ Est.Out │ Tier      │ Cost est. ║
║ Claude orchestration     │  3,000  │  1,500  │ EXPENSIVE │ ~$0.16    ║
║ Forge génération (experts)│ 22,000 │ 14,000  │ FREE/Haiku│ ~$0.00–.06║
║ Jury MiroFish + Herald   │ 12,000  │  4,000  │ FREE/Haiku│ ~$0.00    ║
║ ──────────────────────────────────────────────────────────────────  ║
║ TOTAL contexte Claude (tier cher) : ~4,500 tokens                    ║
║ TOTAL Forge LLM (FREE/cheap)       : ~52,000 tokens                  ║
╚══════════════════════════════════════════════════════════════════════╝
```

Hypothèses :
- Le code du site vit dans des fichiers, **jamais** dans le contexte Claude
  → contexte Claude ~4,5k (3,3× moins que A).
- Génération déportée sur modèles FREE/cheap → coût quasi nul même si + de tokens bruts.
- 2 passes anti-hallucination : jury MiroFish (personas) + audit Herald (grade ≥ B requis).
- Traçé LangSmith automatiquement (`@traced` sur `forge_call`).

Thèse mesurée : **B consomme ~3× moins de tokens Claude chers** et **déplace le gros
de la génération vers du gratuit**, avec en bonus des passes anti-hallucination absentes de A.
Le fact-check (`comparison_report.md`) confirmera avec les chiffres réels.
