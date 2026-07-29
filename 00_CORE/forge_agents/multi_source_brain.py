"""
multi_source_brain.py — MultiSourceBrainOrchestrator
=====================================================
Implémente les prescriptions optiforge.txt §2-§4 :
  - Source Hierarchy : HuggingFace → GitHub Gists → Kaggle → fallback web
  - Dataset Size Matrix : FEATHERWEIGHT(< 1MB) → MASSIVE(>1GB)
  - Just-In-Time Consent Barrier (non-interactive : log + callback)
  - NMP étendu : DATA_NEED|SOURCE_AGENT|PLATFORM_MASK|SCALE_CLASS|INTENT_HASH

TurboVec remplacé par OpenViking (déjà en place, même sémantique).
"""

from __future__ import annotations
import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .nanomachine import NanoMsg, COMMANDS

log = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent


# ─── Dataset Size Matrix §2 ──────────────────────────────────────────────────

class ScaleClass(str, Enum):
    FEATHERWEIGHT = "FEATHERWEIGHT"   # < 1 MB
    LIGHTWEIGHT   = "LIGHTWEIGHT"    # 1 MB – 10 MB
    MIDWEIGHT     = "MIDWEIGHT"      # 10 MB – 100 MB
    HEAVYWEIGHT   = "HEAVYWEIGHT"    # 100 MB – 1 GB
    MASSIVE       = "MASSIVE"        # > 1 GB (justification requise)

_SIZE_BYTES = {
    ScaleClass.FEATHERWEIGHT: 1_000_000,
    ScaleClass.LIGHTWEIGHT:   10_000_000,
    ScaleClass.MIDWEIGHT:     100_000_000,
    ScaleClass.HEAVYWEIGHT:   1_000_000_000,
    ScaleClass.MASSIVE:       float("inf"),
}

def classify_scale(estimated_bytes: int) -> ScaleClass:
    for cls in (ScaleClass.FEATHERWEIGHT, ScaleClass.LIGHTWEIGHT,
                ScaleClass.MIDWEIGHT, ScaleClass.HEAVYWEIGHT):
        if estimated_bytes <= _SIZE_BYTES[cls]:
            return cls
    return ScaleClass.MASSIVE


# ─── NMP étendu §3 ───────────────────────────────────────────────────────────
# Syntaxe : DATA_NEED|SOURCE_AGENT|PLATFORM_MASK|SCALE_CLASS:SIZE|INTENT_HASH

COMMANDS.update({"DATA_NEED", "DATA_ACK", "DL_START", "DL_DONE", "DL_ERR"})

def _intent_hash(query: str) -> str:
    return hashlib.sha1(query.encode()).hexdigest()[:8].upper()

def nmp_data_need(agent: str, platforms: list[str], scale: ScaleClass,
                  size_bytes: int, query: str) -> str:
    mask = "+".join(p.upper() for p in platforms)
    intent = _intent_hash(query)
    return f"DATA_NEED|{agent.upper()}|{mask}|{scale.value}:{size_bytes}|{intent}"

def nmp_dl_start(platform: str, scale: ScaleClass) -> str:
    return f"DL_START|LOCAL_CLI|FETCHING_{scale.value}_ASSET|{platform.upper()}"

def nmp_dl_done(platform: str, path: str) -> str:
    return f"DL_DONE|{platform.upper()}|{path}|OK"

def nmp_dl_err(platform: str, reason: str) -> str:
    return f"DL_ERR|{platform.upper()}|FAILED|{reason}"


# ─── Source Hierarchy §1 + §3 ────────────────────────────────────────────────

PLATFORMS = ["huggingface", "github_gists", "kaggle"]
FALLBACK_PLATFORMS = ["gitlab", "zenodo", "public_repos"]

@dataclass
class DownloadResult:
    platform: str
    success: bool
    local_path: Optional[Path] = None
    bytes_fetched: int = 0
    error: str = ""


def _download_huggingface(query: str, scale: ScaleClass, dest: Path) -> DownloadResult:
    hf_token = os.getenv("HUGGINGFACE_TOKEN", "")
    cmd = ["huggingface-cli", "download", query, "--local-dir", str(dest)]
    if hf_token:
        cmd += ["--token", hf_token]
    log.info(nmp_dl_start("huggingface", scale))
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        log.info(nmp_dl_done("huggingface", str(dest)))
        return DownloadResult("huggingface", True, dest, size)
    except Exception as e:
        log.warning(nmp_dl_err("huggingface", str(e)))
        return DownloadResult("huggingface", False, error=str(e))


def _download_github_gists(query: str, scale: ScaleClass, dest: Path) -> DownloadResult:
    gh_token = os.getenv("GITHUB_TOKEN", "")
    import urllib.request, json as _json
    headers = {"Accept": "application/vnd.github+json"}
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
    url = f"https://api.github.com/gists?per_page=10"
    log.info(nmp_dl_start("github_gists", scale))
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            gists = _json.loads(r.read())
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        for g in gists[:5]:
            for fname, fdata in g.get("files", {}).items():
                content = fdata.get("content", "")
                if query.lower() in content.lower() or query.lower() in fname.lower():
                    out = dest / fname
                    out.write_text(content, encoding="utf-8")
                    written += len(content.encode())
        log.info(nmp_dl_done("github_gists", str(dest)))
        return DownloadResult("github_gists", True, dest, written)
    except Exception as e:
        log.warning(nmp_dl_err("github_gists", str(e)))
        return DownloadResult("github_gists", False, error=str(e))


def _download_kaggle(query: str, scale: ScaleClass, dest: Path) -> DownloadResult:
    log.info(nmp_dl_start("kaggle", scale))
    try:
        import kaggle  # type: ignore
        dest.mkdir(parents=True, exist_ok=True)
        kaggle.api.dataset_download_files(query, path=str(dest), unzip=True)
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        log.info(nmp_dl_done("kaggle", str(dest)))
        return DownloadResult("kaggle", True, dest, size)
    except Exception as e:
        log.warning(nmp_dl_err("kaggle", str(e)))
        return DownloadResult("kaggle", False, error=str(e))


# ─── MultiSourceBrainOrchestrator §4 ─────────────────────────────────────────

@dataclass
class MultiSourceBrainOrchestrator:
    """
    Orchestre l'ingestion multi-source selon la hiérarchie optiforge :
      1. HuggingFace CLI
      2. GitHub Gists API
      3. Kaggle API
      Fallback: deep web search (délégué à forge_llm)
    """
    dl_root: Path = field(default_factory=lambda: FORGE_ROOT / "07_DATASETS")
    consent_callback: Optional[Callable[[str, ScaleClass], bool]] = None

    def select_source_and_scale(self, agent_name: str, query: str,
                                 estimated_bytes: int = 500_000) -> Optional[DownloadResult]:
        scale = classify_scale(estimated_bytes)
        msg = nmp_data_need(agent_name, PLATFORMS, scale, estimated_bytes, query)
        log.info(msg)

        if not self._just_in_time_consent(agent_name, query, scale):
            log.info(f"DL_ERR|ORCHESTRATOR|DOWNLOAD_REJECTED|{agent_name}")
            return None

        return self._execute_with_fallback(agent_name, query, scale)

    def _just_in_time_consent(self, agent_name: str, reason: str, scale: ScaleClass) -> bool:
        if scale == ScaleClass.MASSIVE:
            log.warning(f"[BARRIER] SCALE=MASSIVE requires explicit consent. agent={agent_name}")
            if self.consent_callback:
                return self.consent_callback(reason, scale)
            return False
        if self.consent_callback:
            return self.consent_callback(reason, scale)
        return True  # auto-approve pour FEATHERWEIGHT..HEAVYWEIGHT

    def _execute_with_fallback(self, agent_name: str, query: str,
                                scale: ScaleClass) -> Optional[DownloadResult]:
        dest = self.dl_root / agent_name / scale.value
        dest.mkdir(parents=True, exist_ok=True)

        for platform, fn in [
            ("huggingface",  lambda: _download_huggingface(query, scale, dest / "hf")),
            ("github_gists", lambda: _download_github_gists(query, scale, dest / "gists")),
            ("kaggle",       lambda: _download_kaggle(query, scale, dest / "kaggle")),
        ]:
            result = fn()
            if result.success and result.bytes_fetched > 0:
                return result
            log.info(f"[SOURCE_SKIP] {platform} → trying next")

        # Fallback : log only (web search délégué à l'appelant)
        log.warning(f"DL_ERR|ALL_PLATFORMS|NO_DATA|query={query}")
        return None

    def retroactive_learning_boost(self, agent_name: str, execution_insights: str) -> None:
        """
        Phase 3 optiforge §4 : évolution rétroactive.
        Écrit dans AGENTS.md ET dans le fichier d'instruction de l'agent sous 02_AGENTS/.
        """
        from .graphify_checkpointer import graphify_index

        rule = f"[NODE_EVOLUTION_{agent_name.upper()}] {execution_insights[:200]}"

        # 1. Write to root AGENTS.md (legacy)
        agents_md = FORGE_ROOT / "AGENTS.md"
        if agents_md.exists():
            existing = agents_md.read_text(encoding="utf-8")
            marker = f"NODE_EVOLUTION_{agent_name.upper()}"
            if marker not in existing:
                with agents_md.open("a", encoding="utf-8") as f:
                    f.write(f"\n{rule}\n")
                log.info(f"[CAVEMAN] AGENTS.md UPDATED|{agent_name}|ZERO TOKENS BOUGHT")

        # 2. Write to agent's own instruction file (02_AGENTS/{agent_name}/)
        agent_dir = FORGE_ROOT / "02_AGENTS" / agent_name.lower()
        if not agent_dir.exists():
            # Try common variations
            for variant in [agent_name, agent_name.replace("-", "_"), agent_name + "_agent"]:
                alt = FORGE_ROOT / "02_AGENTS" / variant
                if alt.exists():
                    agent_dir = alt
                    break

        if agent_dir.exists():
            # Find the instruction file
            instruction_file = None
            for pattern in ["*.md", "prompt.txt", "*.txt"]:
                candidates = list(agent_dir.glob(pattern))
                if candidates:
                    # Prefer files with agent name in them
                    for c in candidates:
                        if agent_name.lower() in c.stem.lower():
                            instruction_file = c
                            break
                    if not instruction_file:
                        instruction_file = candidates[0]
                    break

            if instruction_file:
                existing_content = instruction_file.read_text(encoding="utf-8")
                marker = "## Règles Apprises (Historique)"

                insight_line = f"- [{datetime.datetime.now().strftime('%Y-%m-%d')}] {execution_insights[:200]}"

                if marker not in existing_content:
                    # Add section header + first insight
                    new_section = f"\n\n{marker}\n{insight_line}\n"
                    with instruction_file.open("a", encoding="utf-8") as f:
                        f.write(new_section)
                    log.info(f"[CAVEMAN] {instruction_file.name} UPDATED|{agent_name}|new section")
                else:
                    # Append to existing section
                    if insight_line not in existing_content:
                        updated = existing_content.rstrip() + f"\n{insight_line}\n"
                        instruction_file.write_text(updated, encoding="utf-8")
                        log.info(f"[CAVEMAN] {instruction_file.name} UPDATED|{agent_name}|appended")

        graphify_index(rule, agent=agent_name, cycle=0)
        log.info(nmp_dl_done("AGENTS_MD", str(agents_md)))


# ─── Singleton ───────────────────────────────────────────────────────────────

_brain: Optional[MultiSourceBrainOrchestrator] = None

def get_brain(consent_callback: Optional[Callable] = None) -> MultiSourceBrainOrchestrator:
    global _brain
    if _brain is None:
        _brain = MultiSourceBrainOrchestrator(consent_callback=consent_callback)
    return _brain
