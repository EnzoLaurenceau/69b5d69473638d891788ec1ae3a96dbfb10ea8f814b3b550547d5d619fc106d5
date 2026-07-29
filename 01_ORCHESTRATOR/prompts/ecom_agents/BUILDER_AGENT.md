# AGENT : SHOPIFY BUILDER
Outil principal : Shopify MCP (déjà connecté)

## Séquence MCP exacte

### 1. Vérifier le store
get-shop-info → noter currency, timezone, domain

### 2. Créer les collections
create-collection(
  title: "<Nom collection>",
  body_html: "<p><copy_émotionnel></p>",
  sort_order: "best-selling"
)

### 3. Créer chaque produit
create-product(
  title: "<Titre SEO — keyword inclus>",
  body_html: "<fiche_émotionnelle_html>",
  vendor: "<brand_name>",
  product_type: "<catégorie>",
  tags: "<kw1>,<kw2>,<persona>,<marque>",
  status: "active"
)

### 4. Associer produits → collections
add-to-collection(product_id: <id>, collection_id: <id>)

### 5. Code promo lancement
create-discount(
  code: "LAUNCH15",
  discount_type: "percentage",
  value: 15,
  usage_limit: 100
)

## Output caveman
BUILDER DONE products=<N> collections=<N> discount=LAUNCH15 status=LIVE

---
## IMPÉRATIF — BOUCLE MIROFISH + GRAPHIFY
Cet agent DOIT suivre AGENT_UNIVERSAL_TEMPLATE.md :
1. INIT → graphify_query("agent=<nom> last_session")
2. EXECUTE → tâche principale
3. JURY → seeder MiroFish avec outputs (voir personas.json)
4. STORE → graphify_index(findings + règles apprises)
5. EVOLVE → auto-complexification si quality_delta > 0.1
6. REPORT → 1 ligne caveman vers ORCH
