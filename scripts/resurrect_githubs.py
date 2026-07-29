"""
resurrect_githubs.py — Clone & Index 41+ GitHub Repos
======================================================
Plan B §2.1 : Inventaire historique des dépôts identifiés.

Clone les repos sous 07_KNOWLEDGE_BASE/external_repos/ et les indexe
via GitNexus + Kuzu.

Usage:
    python scripts/resurrect_githubs.py
    python scripts/resurrect_githubs.py --repos 5  # clone only 5
    python scripts/resurrect_githubs.py --skip-clone  # index only
"""

from __future__ import annotations
import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("ResurrectGitHub")

FORGE_ROOT = Path(__file__).parent.parent
REPOS_DIR = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "external_repos"
INVENTORY_FILE = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "external_resources.json"

# ─── 41 repos identifiés ─────────────────────────────────────────────────────
REPOS = [
    # Core Forge dependencies
    {"owner": "abhigyanpatwari", "repo": "GitNexus", "category": "indexing", "priority": "high"},
    {"owner": "lak7", "repo": "devildev", "category": "blueprint", "priority": "high"},
    {"owner": "teamchong", "repo": "pxpipe", "category": "compression", "priority": "high"},
    {"owner": "hkuds", "repo": "rag-anything", "category": "rag", "priority": "high"},
    {"owner": "lmcache", "repo": "lmcache", "category": "cache", "priority": "high"},
    {"owner": "kunchenguid", "repo": "no-mistakes", "category": "quality", "priority": "high"},

    # RAG & LLM
    {"owner": "Danielskry", "repo": "Awesome-RAG", "category": "rag", "priority": "medium"},
    {"owner": "Shubhamsaboo", "repo": "awesome-llm-apps", "category": "llm", "priority": "medium"},
    {"owner": "camel-ai", "repo": "mcpify", "category": "mcp", "priority": "medium"},
    {"owner": "addyosmani", "repo": "agent-skills", "category": "agents", "priority": "medium"},
    {"owner": "nidhinjs", "repo": "prompt-master", "category": "prompts", "priority": "medium"},
    {"owner": "nebius", "repo": "nebius-partner-cookbook", "category": "cloud", "priority": "low"},

    # Security & Pentest
    {"owner": "danielmiessler", "repo": "SecLists", "category": "security", "priority": "medium"},
    {"owner": "swisskyrepo", "repo": "PayloadsAllTheThings", "category": "security", "priority": "medium"},
    {"owner": "fuzzdb-project", "repo": "fuzzdb", "category": "security", "priority": "medium"},
    {"owner": "Yara-Rules", "repo": "rules", "category": "security", "priority": "low"},
    {"owner": "PurpleAILAB", "repo": "Decepticon", "category": "adversarial", "priority": "medium"},

    # Data & Scraping
    {"owner": "D4Vinci", "repo": "Scrapling", "category": "scraping", "priority": "medium"},
    {"owner": "ertugrulakben", "repo": "cashclaw", "category": "finance", "priority": "low"},
    {"owner": "obheda12", "repo": "MoneyScope", "category": "finance", "priority": "low"},

    # 3D & Vision
    {"owner": "3D-Vision-World", "repo": "awesome-NeRF-and-3DGS-SLAM", "category": "3d", "priority": "low"},
    {"owner": "DietrichGebert", "repo": "ponytail", "category": "yagni", "priority": "medium"},

    # Additional frameworks (19 repos)
    {"owner": "langchain-ai", "repo": "langchain", "category": "llm", "priority": "medium"},
    {"owner": "langchain-ai", "repo": "langgraph", "category": "agents", "priority": "high"},
    {"owner": "huggingface", "repo": "transformers", "category": "ml", "priority": "medium"},
    {"owner": "qdrant", "repo": "qdrant", "category": "vector-db", "priority": "medium"},
    {"owner": "weaviate", "repo": "weaviate", "category": "vector-db", "priority": "low"},
    {"owner": "chroma-core", "repo": "chroma", "category": "vector-db", "priority": "low"},
    {"owner": "run-llama", "repo": "llama_index", "category": "rag", "priority": "medium"},
    {"owner": "openai", "repo": "openai-python", "category": "llm", "priority": "medium"},
    {"owner": "anthropics", "repo": "anthropic-sdk-python", "category": "llm", "priority": "medium"},
    {"owner": "microsoft", "repo": "semantic-kernel", "category": "agents", "priority": "low"},
    {"owner": "Significant-Gravitas", "repo": "AutoGPT", "category": "agents", "priority": "low"},
    {"owner": "geekan", "repo": "MetaGPT", "category": "agents", "priority": "low"},
    {"owner": "joaomdmoura", "repo": "crewAI", "category": "agents", "priority": "medium"},
    {"owner": "phidatahq", "repo": "phidata", "category": "agents", "priority": "low"},
    {"owner": "embedchain", "repo": "embedchain", "category": "rag", "priority": "low"},
    {"owner": "unstructured-io", "repo": "unstructured", "category": "ingestion", "priority": "low"},
    {"owner": "BerriAI", "repo": "litellm", "category": "llm", "priority": "medium"},
    {"owner": "vllm-project", "repo": "vllm", "category": "inference", "priority": "low"},
    {"owner": "ollama", "repo": "ollama", "category": "inference", "priority": "medium"},
]


def clone_repo(owner: str, repo: str, target_dir: Path) -> bool:
    """Clone un repo GitHub."""
    url = f"https://github.com/{owner}/{repo}.git"
    dest = target_dir / f"{owner}__{repo}"

    if dest.exists():
        logger.info(f"  Already cloned: {owner}/{repo}")
        return True

    try:
        logger.info(f"  Cloning {owner}/{repo}...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            logger.info(f"  ✓ Cloned: {owner}/{repo}")
            return True
        else:
            logger.warning(f"  ✗ Failed: {owner}/{repo}: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"  ✗ Timeout: {owner}/{repo}")
        return False
    except Exception as e:
        logger.warning(f"  ✗ Error: {owner}/{repo}: {e}")
        return False


def index_repo(owner: str, repo: str, target_dir: Path) -> bool:
    """Index un repo via GitNexus."""
    dest = target_dir / f"{owner}__{repo}"
    if not dest.exists():
        return False

    try:
        logger.info(f"  Indexing {owner}/{repo}...")
        result = subprocess.run(
            ["npx", "gitnexus", "analyze"],
            capture_output=True, text=True,
            cwd=str(dest), timeout=60
        )
        if result.returncode == 0:
            logger.info(f"  ✓ Indexed: {owner}/{repo}")
            return True
        else:
            logger.warning(f"  ✗ Index failed: {owner}/{repo}")
            return False
    except FileNotFoundError:
        logger.debug(f"  npx/gitnexus not found, skipping index for {owner}/{repo}")
        return False
    except subprocess.TimeoutExpired:
        logger.warning(f"  ✗ Index timeout: {owner}/{repo}")
        return False
    except Exception as e:
        logger.debug(f"  ✗ Index error: {owner}/{repo}: {e}")
        return False


def update_inventory(repos: list[dict], results: dict):
    """Met à jour external_resources.json avec l'inventaire."""
    inventory = {
        "resources": [],
        "integration_matrix": {},
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_repos": len(repos),
        "cloned": sum(1 for r in results.values() if r.get("cloned")),
        "indexed": sum(1 for r in results.values() if r.get("indexed")),
    }

    for repo_info in repos:
        key = f"{repo_info['owner']}/{repo_info['repo']}"
        result = results.get(key, {})
        inventory["resources"].append({
            "owner": repo_info["owner"],
            "repo": repo_info["repo"],
            "category": repo_info["category"],
            "priority": repo_info["priority"],
            "cloned": result.get("cloned", False),
            "indexed": result.get("indexed", False),
            "path": str(REPOS_DIR / f"{repo_info['owner']}__{repo_info['repo']}"),
        })

    INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_FILE.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Inventory saved: {INVENTORY_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Resurrect GitHub repos")
    parser.add_argument("--repos", type=int, default=len(REPOS), help="Max repos to clone")
    parser.add_argument("--skip-clone", action="store_true", help="Skip cloning, index only")
    parser.add_argument("--skip-index", action="store_true", help="Skip indexing")
    parser.add_argument("--priority", choices=["high", "medium", "low"], help="Filter by priority")
    args = parser.parse_args()

    # Filter repos
    repos = REPOS
    if args.priority:
        repos = [r for r in repos if r["priority"] == args.priority]
    repos = repos[:args.repos]

    logger.info(f"Resurrecting {len(repos)} repos...")
    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    results = {}

    for i, repo_info in enumerate(repos, 1):
        key = f"{repo_info['owner']}/{repo_info['repo']}"
        logger.info(f"[{i}/{len(repos)}] {key} ({repo_info['category']})")

        result = {"cloned": False, "indexed": False}

        # Clone
        if not args.skip_clone:
            result["cloned"] = clone_repo(repo_info["owner"], repo_info["repo"], REPOS_DIR)

        # Index
        if not args.skip_index:
            result["indexed"] = index_repo(repo_info["owner"], repo_info["repo"], REPOS_DIR)

        results[key] = result

    # Update inventory
    update_inventory(repos, results)

    # Summary
    cloned = sum(1 for r in results.values() if r["cloned"])
    indexed = sum(1 for r in results.values() if r["indexed"])
    logger.info(f"\nDone: {cloned}/{len(repos)} cloned, {indexed}/{len(repos)} indexed")


if __name__ == "__main__":
    main()
