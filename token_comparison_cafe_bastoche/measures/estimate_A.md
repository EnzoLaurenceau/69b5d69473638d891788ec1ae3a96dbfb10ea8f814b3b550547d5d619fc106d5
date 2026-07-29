# TOKEN ESTIMATE — Version A (SANS Forge)

Tâche : `cafe_bastoche_site` — Claude écrit le site directement dans son contexte.

```
╔════════════════════════════════════════════════════════════════╗
║ TOKEN ESTIMATE — Task: cafe_bastoche_site  [A / baseline]      ║
║ Model             │ Est.In  │ Est.Out │ Tier    │ Cost est.    ║
║ claude-opus-4-8   │  4,000  │ 11,000  │ EXPENSIVE│ ~$0.88       ║
║ ─────────────────────────────────────────────────────────────  ║
║ TOTAL contexte Claude (tier cher) : ~15,000 tokens             ║
╚════════════════════════════════════════════════════════════════╝
```

Hypothèses :
- Sortie = index.html (~260 l) + style.css (~420 l) + app.js (~110 l) ≈ 790 lignes.
- ~14 tokens/ligne de code moyenne → ~11k tokens output.
- Tout le code transite par le contexte Claude (tier cher). Aucune déportation.
- 0 passe anti-hallucination.
- Coût : Opus 4.8 ≈ $15/M in, $75/M out → 4k·15 + 11k·75 = $0.06 + $0.825 ≈ **$0.88**.
