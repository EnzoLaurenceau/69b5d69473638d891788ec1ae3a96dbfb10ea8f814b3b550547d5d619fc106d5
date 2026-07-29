# PROTOCOLE DE SCRAPING FINOPS

Le scraping web génère les plus gros dépassements budgétaires en tokens (Input).
Afin d'optimiser les coûts, ce protocole est OBLIGATOIRE pour l'agent Scraper (L2) et tout module de collecte.

## 1. Règle absolue
**Interdiction stricte de passer du HTML brut ou du JSON lourd dans le prompt d'un modèle.**

## 2. Étapes de traitement (Pipeline)
Lorsqu'une page est récupérée, l'agent ou le script local DOIT effectuer les opérations suivantes *avant* tout appel LLM :

1. **Nettoyage HTML** : Utiliser un convertisseur (ex: `markdownify`, `BeautifulSoup`) pour extraire uniquement le texte et la structure markdown (titres, listes, liens). Supprimer les `<script>`, `<style>`, `<nav>`, et balises inutiles.
2. **Chunking** : Si le texte généré dépasse 4000 tokens, le diviser en morceaux (chunks) cohérents par paragraphes ou sections.
3. **Extraction Ciblée** : Envoyer uniquement le chunk pertinent au modèle (Tier LOW - Haiku/Flash) pour en extraire la donnée précise demandée par l'Orchestrateur.

## 3. Limite Output
Le modèle de Scraping (Tier LOW) ne doit générer **QUE** la donnée extraite, sans commentaire, avec un `max_tokens` strict de **300**.
