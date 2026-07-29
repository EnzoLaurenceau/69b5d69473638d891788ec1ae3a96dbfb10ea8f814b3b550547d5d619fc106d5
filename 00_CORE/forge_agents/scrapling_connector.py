"""
scrapling_connector.py — Connecteur de scraping basé sur Scrapling
====================================================================
Remplace Firecrawl (API payante) pour le scraping de masse de la Forge
(MARKET / PRODUCT / CHANNEL_CLONE agents). Scrapling tourne en local,
est gratuit, et contourne la plupart des protections anti-bot (Cloudflare
Turnstile) out of the box.

Repo : https://github.com/D4Vinci/Scrapling

Stratégie de fetch (du moins cher au plus cher) :
  1. Fetcher          — requête HTTP simple (statique, le plus rapide)
  2. StealthySession  — navigateur furtif (sites protégés / JS lourd)
  3. crawl4ai         — fallback local gratuit (playwright, JS complet)
                        pip install crawl4ai && crawl4ai-setup

Installation côté Forge :
  pip install "scrapling[fetchers]" --break-system-packages
  scrapling install   # télécharge les navigateurs furtifs si besoin

Usage :
  from forge_agents.scrapling_connector import scrape, scrape_many

  r = scrape("https://example.com")
  if r.ok:
      print(r.markdown[:500])

  results = scrape_many(["https://a.com", "https://b.com"], stealthy=False)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("ScraplingConnector")


# ─── Résultat unifié ────────────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    url: str
    ok: bool
    source: str                     # "scrapling_fetcher" | "scrapling_stealthy" | "crawl4ai" | "error"
    markdown: str = ""
    text: str = ""
    status_code: Optional[int] = None
    error: Optional[str] = None
    meta: dict = field(default_factory=dict)


# ─── Backend Scrapling ──────────────────────────────────────────────────────

def _try_scrapling_static(url: str) -> Optional[ScrapeResult]:
    """Fetch statique rapide (HTTP simple). Échoue silencieusement si bloqué."""
    try:
        from scrapling.fetchers import Fetcher
    except ImportError:
        logger.debug("[Scrapling] package non installé (pip install \"scrapling[fetchers]\")")
        return None

    try:
        page = Fetcher.get(url, stealthy_headers=True)
        if not page or page.status >= 400:
            return None
        markdown = _to_markdown(page)
        return ScrapeResult(
            url=url, ok=True, source="scrapling_fetcher",
            markdown=markdown, text=page.get_all_text() if hasattr(page, "get_all_text") else markdown,
            status_code=page.status,
        )
    except Exception as e:
        logger.debug(f"[Scrapling] fetch statique échoué pour {url}: {e}")
        return None


def _try_scrapling_stealthy(url: str) -> Optional[ScrapeResult]:
    """Fetch avec navigateur furtif (sites protégés / SPA / Cloudflare)."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if not page or page.status >= 400:
            return None
        markdown = _to_markdown(page)
        return ScrapeResult(
            url=url, ok=True, source="scrapling_stealthy",
            markdown=markdown, text=page.get_all_text() if hasattr(page, "get_all_text") else markdown,
            status_code=page.status,
        )
    except Exception as e:
        logger.debug(f"[Scrapling] fetch stealthy échoué pour {url}: {e}")
        return None


def _to_markdown(page) -> str:
    """Convertit une page Scrapling en markdown léger (titre + texte).

    NOTE (fix 2026-06-12) : `page.css_first(...)` n'existe PAS dans
    l'API Selector de Scrapling 0.4.x (AttributeError — la méthode
    correcte est `re_first` pour les regex, ou `.css(...).get()` /
    `.css(...).extract_first()` pour CSS). Vérifié en live contre
    scrapling==0.4.9.
    """
    try:
        title = (page.css("title::text").get() or "")
        body_text = page.get_all_text(ignore_tags=("script", "style", "nav", "footer"))
        return f"# {title}\n\n{body_text}".strip()
    except Exception:
        return str(page)[:5000]


# ─── Backend crawl4ai (fallback local gratuit) ─────────────────────────────

def _try_crawl4ai(url: str) -> Optional[ScrapeResult]:
    """Fallback gratuit via crawl4ai (playwright, JS complet, zéro API key).
    pip install crawl4ai && crawl4ai-setup
    """
    try:
        from crawl4ai import AsyncWebCrawler
    except ImportError:
        logger.debug("[crawl4ai] non installé — pip install crawl4ai && crawl4ai-setup")
        return None

    import asyncio
    import concurrent.futures

    async def _fetch():
        async with AsyncWebCrawler() as crawler:
            return await crawler.arun(url=url)

    try:
        try:
            result = asyncio.run(_fetch())
        except RuntimeError:
            # Déjà dans un event loop (LangGraph async) → thread séparé
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _fetch()).result(timeout=30)

        if result.success and result.markdown:
            return ScrapeResult(
                url=url, ok=True, source="crawl4ai",
                markdown=result.markdown, text=result.markdown, status_code=200,
            )
        return ScrapeResult(url=url, ok=False, source="crawl4ai",
                             error=getattr(result, "error_message", "empty result"))
    except Exception as e:
        return ScrapeResult(url=url, ok=False, source="crawl4ai", error=str(e))


# ─── API publique ───────────────────────────────────────────────────────────

def scrape(url: str, stealthy: bool = False, allow_crawl4ai_fallback: bool = False) -> ScrapeResult:
    """
    Scrape une URL avec la cascade : Scrapling (static) → Scrapling (stealthy).
    Le fallback crawl4ai est désactivé par défaut (passer True explicitement si besoin).
    """
    if not stealthy:
        result = _try_scrapling_static(url)
        if result and result.ok:
            return result

    result = _try_scrapling_stealthy(url)
    if result and result.ok:
        return result

    if allow_crawl4ai_fallback:
        c4 = _try_crawl4ai(url)
        if c4:
            return c4

    return ScrapeResult(
        url=url, ok=False, source="error",
        error="Scrapling indisponible/échec et fallback crawl4ai désactivé ou non installé",
    )


def scrape_many(urls: list[str], stealthy: bool = False,
                allow_crawl4ai_fallback: bool = False) -> list[ScrapeResult]:
    """Scrape une liste d'URLs séquentiellement (cascade par URL)."""
    return [scrape(u, stealthy=stealthy, allow_crawl4ai_fallback=allow_crawl4ai_fallback) for u in urls]



# ─── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    r = scrape(test_url)
    print(f"ok={r.ok} source={r.source} status={r.status_code}")
    if r.ok:
        print(r.markdown[:500])
    else:
        print(f"error={r.error}")
