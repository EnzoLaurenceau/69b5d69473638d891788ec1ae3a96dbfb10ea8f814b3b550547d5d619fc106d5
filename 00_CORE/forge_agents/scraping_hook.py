"""
scraping_hook.py — Hook universel de scraping (Scrapling-first)
==================================================================
Règle : DÈS QU'UNE TÂCHE IMPLIQUE DU SCRAPING — peu importe l'agent
(existant OU généré dynamiquement par l'orchestrateur, même un agent
qui n'existe pas encore) — Scrapling DOIT être appelé en premier,
avant tout appel LLM. crawl4ai (gratuit, local) est le fallback final
si Scrapling échoue (cf. scrapling_connector.py).

Ce module ne dépend d'AUCUN nom d'agent : il détecte l'intention de
scraping directement dans `current_task` (URL présente + verbes
scraping FR/EN) et retourne un bloc de contexte prêt à injecter.
Zéro configuration par agent — branché une seule fois dans
dynamic_agent_node() (agent_nodes.py).

Usage :
  from .scraping_hook import maybe_scrape_for_task
  scraped_ctx = maybe_scrape_for_task(task)
  if scraped_ctx:
      ctx += "\n\n[SCRAPLING]\n" + scraped_ctx
"""

from __future__ import annotations

import logging
import re

from .scrapling_connector import scrape_many

logger = logging.getLogger("ScrapingHook")

URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')

# Verbes/expressions indiquant une intention de scraping même sans URL
# explicite déjà présente (utile pour logguer/avertir, mais on ne scrape
# jamais sans URL concrète — pas de devinette d'adresse).
SCRAPE_INTENT_KEYWORDS = (
    "scrape", "scrap", "crawl", "fetch", "récupère", "recupere",
    "analyse le site", "analyse la page", "visite", "extrait du site",
    "extraire de la page", "lis la page", "contenu de la page",
    "scraping",
)

MAX_URLS_PER_TASK = 3
MAX_CHARS_PER_URL = 4000


def extract_urls(task: str) -> list[str]:
    """Retourne toutes les URLs http(s) trouvées dans la tâche."""
    if not task:
        return []
    return URL_RE.findall(task)


def has_scraping_intent(task: str) -> bool:
    """True si la tâche mentionne une URL ou un verbe de scraping."""
    if not task:
        return False
    if extract_urls(task):
        return True
    task_l = task.lower()
    return any(kw in task_l for kw in SCRAPE_INTENT_KEYWORDS)


def maybe_scrape_for_task(task: str, stealthy: bool = False,
                           allow_crawl4ai_fallback: bool = True,
                           max_chars: int = MAX_CHARS_PER_URL) -> str:
    """
    Si `task` contient une ou plusieurs URLs, scrape CHAQUE URL via la
    cascade Scrapling (static -> stealthy -> crawl4ai) et retourne un
    bloc markdown prêt à injecter dans le contexte de l'agent (peu
    importe lequel). Retourne "" si rien à scraper.

    Cette fonction est agent-agnostique : applicable à n'importe quel
    agent dynamique présent ou futur dès qu'une URL apparaît dans la
    tâche.
    """
    urls = extract_urls(task)
    if not urls:
        if has_scraping_intent(task):
            logger.debug(
                "[ScrapingHook] Intention de scraping détectée sans URL "
                "explicite — aucune action (pas de devinette d'adresse)."
            )
        return ""

    urls = urls[:MAX_URLS_PER_TASK]
    logger.info(f"[ScrapingHook] {len(urls)} URL(s) détectée(s) → Scrapling cascade")

    results = scrape_many(urls, stealthy=stealthy,
                           allow_crawl4ai_fallback=allow_crawl4ai_fallback)

    parts = []
    for r in results:
        if r.ok:
            content = r.markdown[:max_chars]
            parts.append(f"[SCRAPLING:{r.source}] {r.url}\n{content}")
        else:
            parts.append(f"[SCRAPLING:ERROR] {r.url} -> {r.error}")
    return "\n\n".join(parts)
