"""
browser_use.py — Wrapper browser-use (github.com/browser-use/browser-use)
==========================================================================
QA web + scraping navigateur Playwright Python. MIT.
Teste les sites générés, scrape les sites JS/login, remplit des formulaires.

Usage :
    from tools.automation import browser_use
    result = await browser_use.run_task("Va sur example.com et clique sur Login")
    text   = await browser_use.scrape("https://example.com/dashboard")
    ok     = await browser_use.fill_form("https://example.com/signup", {"email": "…"})
    path   = await browser_use.screenshot("https://example.com", "out.png")
"""

from __future__ import annotations
import asyncio, os
from pathlib import Path

_HEADLESS = os.environ.get("BROWSER_USE_HEADLESS", "1") == "1"


def _get_agent(task: str):
    """Construit un browser-use Agent avec le LLM forge (free tier)."""
    try:
        from browser_use import Agent
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        return Agent(task=task, llm=llm)
    except ImportError as e:
        raise RuntimeError(
            f"browser-use non installé : pip install browser-use langchain-anthropic\n{e}"
        )


async def run_task(task: str) -> str:
    """
    Exécute une tâche en langage naturel dans le navigateur.
    Ex: 'Va sur google.com, cherche Python, retourne le 1er résultat'
    Retourne le résultat final de l'agent.
    """
    agent = _get_agent(task)
    result = await agent.run()
    return str(result)


async def scrape(url: str) -> str:
    """Scrape une page JS/auth → retourne le texte visible."""
    return await run_task(f"Va sur {url} et retourne tout le texte visible de la page.")


async def fill_form(url: str, fields: dict[str, str], submit: bool = True) -> bool:
    """
    Remplit un formulaire sur url avec les champs donnés.
    fields = {"email": "...", "password": "..."}
    Retourne True si la soumission semble réussie.
    """
    field_desc = ", ".join(f'{k}="{v}"' for k, v in fields.items())
    action = "puis soumets le formulaire" if submit else "ne soumets pas"
    result = await run_task(f"Va sur {url}, remplis les champs: {field_desc}, {action}.")
    return "error" not in result.lower() and "failed" not in result.lower()


async def screenshot(url: str, output_path: str | Path = "screenshot.png") -> Path:
    """
    Prend une capture d'écran d'une page (après rendu JS complet).
    Retourne le path du fichier créé.
    """
    from playwright.async_api import async_playwright
    out = Path(output_path)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=_HEADLESS)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path=str(out), full_page=True)
        await browser.close()
    return out


async def qa_checklist(url: str, checks: list[str]) -> dict[str, bool]:
    """
    QA automatique : vérifie une liste de critères sur un site.
    checks = ["Le bouton Login est visible", "Le footer contient 'Contact'"]
    Retourne {check: True/False}.
    """
    results: dict[str, bool] = {}
    for check in checks:
        result = await run_task(f"Sur {url}, vérifie si: {check}. Réponds UNIQUEMENT par 'oui' ou 'non'.")
        results[check] = result.strip().lower().startswith("oui")
    return results


def install_hint() -> str:
    """Retourne la commande d'installation."""
    return "pip install browser-use langchain-anthropic && playwright install chromium"


# ponytail: wrapper async mince. browser-use gère Playwright + LLM loop. On délègue.
if __name__ == "__main__":
    print("browser_use: wrapper QA/scraping navigateur")
    print(f"headless: {_HEADLESS}")
    print(f"install: {install_hint()}")
    print("ops: run_task() scrape() fill_form() screenshot() qa_checklist()")

    async def _demo():
        try:
            _get_agent("test")
            print("browser-use: installé ✓")
        except RuntimeError as e:
            print(f"browser-use: {e}")
    asyncio.run(_demo())
