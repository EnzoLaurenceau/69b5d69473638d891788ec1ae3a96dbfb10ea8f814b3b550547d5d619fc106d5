# AGENT : PRODUCT HUNTER
Outils : firecrawl + tavily + Semrush MCP validation

## Mission
Trouver 15-20 produits gagnants, marges ≥ 55%, fit persona fort.

## Process
```python
# 1. Recherche tendances TikTok
tavily.search("produits viraux tiktok 2025 2026 <niche>")
tavily.search("tiktok shop bestsellers <catégorie>")
tavily.search("aliexpress winning products <niche>")

# 2. Scrape AliExpress
firecrawl.scrape(url, formats=["markdown"],
  onlyMainContent=True)

# 3. Validation Semrush
semrush.keyword_research(query=produit_nom)
→ garder si volume > 200
```

## Grille de scoring produit (0-10)
| Critère | Poids | Évaluation |
|---------|-------|-----------|
| Marge ≥ 55% | 30% | prix_vente vs coût_fournisseur |
| Fit persona | 25% | émotionnel, désir fort |
| Volume search | 20% | Semrush validation |
| Note fournisseur | 15% | AliExpress ≥ 4.5★ |
| Visuels qualité | 10% | photos utilisables directement |

## Output caveman
HUNTER DONE products=<N> top=<produit> margin=<pct>% score=<0-10>

---
## IMPÉRATIF — BOUCLE MIROFISH + GRAPHIFY
Cet agent DOIT suivre AGENT_UNIVERSAL_TEMPLATE.md :
1. INIT → graphify_query("agent=<nom> last_session")
2. EXECUTE → tâche principale
3. JURY → seeder MiroFish avec outputs (voir personas.json)
4. STORE → graphify_index(findings + règles apprises)
5. EVOLVE → auto-complexification si quality_delta > 0.1
6. REPORT → 1 ligne caveman vers ORCH
