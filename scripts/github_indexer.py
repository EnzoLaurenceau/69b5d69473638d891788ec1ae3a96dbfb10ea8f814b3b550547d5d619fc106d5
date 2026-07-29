"""
github_indexer.py — GitNexus + Kuzu Indexing Engine
=====================================================
Plan B §2.2 : Indexation temps réel des dépôts GitHub.

Clone un repo, lance GitNexus analyze, crée les nœuds Kuzu.

Usage:
    from scripts.github_indexer import index_github_repo
    result = await index_github_repo("owner/repo")
"""

from __future__ import annotations
import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("GitHubIndexer")

FORGE_ROOT = Path(__file__).parent.parent
REPOS_DIR = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "external_repos"


async def index_github_repo(repo_url: str, project_context: str = "") -> dict:
    """
    Indexe un repo GitHub de façon asynchrone.
    1. Extraire owner/repo de l'URL
    2. Cloner sous 07_KNOWLEDGE_BASE/external_repos/
    3. Lancer GitNexus analyze
    4. Créer les nœuds Kuzu
    """
    owner, repo = _parse_github_url(repo_url)
    if not owner:
        return {"success": False, "error": f"Invalid GitHub URL: {repo_url}"}

    result = {
        "owner": owner,
        "repo": repo,
        "cloned": False,
        "indexed": False,
        "kuzu_nodes": 0,
        "duration_ms": 0,
    }

    start = time.time()

    # 1. Clone
    dest = REPOS_DIR / f"{owner}__{repo}"
    if not dest.exists():
        clone_ok = await _async_clone(owner, repo, dest)
        result["cloned"] = clone_ok
    else:
        result["cloned"] = True
        logger.info(f"Already cloned: {owner}/{repo}")

    # 2. GitNexus index
    if result["cloned"]:
        index_ok = await _async_gitnexus(dest)
        result["indexed"] = index_ok

    # 3. Kuzu nodes
    if result["indexed"]:
        kuzu_ok = await _create_kuzu_nodes(owner, repo, project_context)
        result["kuzu_nodes"] = kuzu_ok

    result["duration_ms"] = int((time.time() - start) * 1000)
    logger.info(f"Index complete: {owner}/{repo} ({result['duration_ms']}ms)")
    return result


def _parse_github_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """Parse GitHub URL → (owner, repo)."""
    import re
    patterns = [
        r"github\.com/([^/]+)/([^/\.]+)",
        r"github\.com/([^/]+)/([^/\.]+)\.git",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return None, None


async def _async_clone(owner: str, repo: str, dest: Path) -> bool:
    """Clone asynchrone."""
    url = f"https://github.com/{owner}/{repo}.git"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", url, str(dest),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode == 0:
            logger.info(f"Cloned: {owner}/{repo}")
            return True
        else:
            logger.warning(f"Clone failed: {owner}/{repo}: {stderr.decode()[:200]}")
            return False
    except asyncio.TimeoutError:
        logger.warning(f"Clone timeout: {owner}/{repo}")
        return False
    except Exception as e:
        logger.warning(f"Clone error: {owner}/{repo}: {e}")
        return False


async def _async_gitnexus(repo_dir: Path) -> bool:
    """Index asynchrone via GitNexus."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "npx", "gitnexus", "analyze",
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0:
            logger.info(f"GitNexus indexed: {repo_dir.name}")
            return True
        else:
            logger.debug(f"GitNexus not available for {repo_dir.name}")
            return False
    except (FileNotFoundError, asyncio.TimeoutError, Exception) as e:
        logger.debug(f"GitNexus skip: {e}")
        return False


async def _create_kuzu_nodes(owner: str, repo: str, project_context: str) -> int:
    """Crée les nœuds dans Kuzu Graph DB."""
    try:
        import sys
        sys.path.insert(0, str(FORGE_ROOT / "00_CORE" / "forge_agents"))
        from graph_db import get_graph_db

        db = get_graph_db()
        # Create repo node
        db.add_node("Repository", {
            "name": f"{owner}/{repo}",
            "owner": owner,
            "repo": repo,
            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        # Link to project if context provided
        if project_context:
            db.add_edge("Project", project_context, "Repository", f"{owner}/{repo}", "USES_REPO")

        return 1
    except Exception as e:
        logger.debug(f"Kuzu skip: {e}")
        return 0


async def index_from_chat_message(message: str, project_context: str = "") -> list[dict]:
    """
    Extrait les liens GitHub d'un message et les indexe.
    Appelé par le WebSocket interceptor.
    """
    import re
    github_pattern = r"https?://github\.com/[\w-]+/[\w.-]+"
    urls = re.findall(github_pattern, message)

    if not urls:
        return []

    results = []
    for url in urls:
        result = await index_github_repo(url, project_context)
        results.append(result)

    return results
