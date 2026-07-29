"""
tools.product_bricks.ui — Design Knowledge Base
================================================
Catalogue de sources UI/design interrogeable.
PAS de lib imposée — chaque produit a son UI propre à sa marque.

Workflow orchestrateur :
  1. design_kb.search(mood, product_type)  → sources candidates
  2. Refero MCP / refero skill             → research 150K écrans réels
  3. Choix basé sur la marque/besoin       → shadcn_caller / 21st MCP / autre
  4. L'agent UI compose quelque chose d'unique

Outils ready :
  design_kb.py      — catalogue interrogeable (turbovec agent="UI")
  shadcn_caller.py  — npx shadcn@latest init/add (si l'agent choisit shadcn)

Sources dans le KB : shadcn, 21st.dev, componentry.fun, themefisher,
                     tailwind_ui, daisyui, refero
"""
