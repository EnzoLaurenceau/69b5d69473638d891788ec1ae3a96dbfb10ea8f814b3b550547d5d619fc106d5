"""tools.research — MARKET / RECHERCHE + index d'APIs publiques.

ready :
  public_apis → from tools.research.public_apis import fetch_and_index, search, get
    Index ~1562 APIs publiques (public-apis/public-apis) dans turbovec + catalogue
    JSON. Un agent cherche une API par besoin (météo, FX, OCR, géo...) et l'appelle.

reference (pas de wrapper — MCP/API directe, croiser ≥2 sources) :
  research-4 (MCP)  → mcpmarket.com/server/research-4
  RabbitResearch    → source alternative de recherche
  + firecrawl / semrush / agent-reach déjà disponibles.
"""
