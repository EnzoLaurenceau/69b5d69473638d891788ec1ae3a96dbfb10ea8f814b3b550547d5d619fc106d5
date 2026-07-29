"""
money_scope.py — Wrapper MoneyScope pour la Forge (bug bounty scope discovery)
================================================================================
Repo : https://github.com/obheda12/MoneyScope
Règle DO NOT INVENT : on appelle le script bash via WSL, on ne réécrit pas la logique.

Sources disponibles :
  a = all   i = intigriti   h = hackerone
  b = bugcrowd   y = yeswehack   o = other (hackenproof+federacy)

# ponytail: WSL-only; upgrade path = pure Python si jq+requests suffisent
"""

from __future__ import annotations
import subprocess
import tempfile
import os
from pathlib import Path

REPO_URL = "https://github.com/obheda12/MoneyScope"
WSL_INSTALL_DIR = "/opt/MoneyScope"
SCRIPT = f"{WSL_INSTALL_DIR}/MoneyScope.sh"


def _wsl(cmd: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a command in WSL bash."""
    prefix = f"cd {cwd} && " if cwd else ""
    return subprocess.run(
        ["wsl", "bash", "-c", prefix + cmd],
        capture_output=True, text=True
    )


def ensure_installed() -> bool:
    """Clone MoneyScope into WSL if not already present. Returns True if ready."""
    check = _wsl(f"test -f {SCRIPT} && echo ok || echo missing")
    if "ok" in check.stdout:
        return True
    result = _wsl(
        f"git clone {REPO_URL} {WSL_INSTALL_DIR} && chmod +x {SCRIPT}"
    )
    return result.returncode == 0


def get_scope(sources: str = "a") -> dict:
    """
    Pull paid bounty scope from the specified platforms.

    sources: string of flags without dash, e.g. "a", "bh", "yhi"
             a=all  i=intigriti  h=hackerone  b=bugcrowd  y=yeswehack  o=other

    Returns:
        {
          "domains": ["example.com", ...],
          "tlds": [".com", ...],
          "source_flags": "a",
          "domain_count": N,
          "tld_count": N,
        }
    """
    if not ensure_installed():
        raise RuntimeError("MoneyScope not available in WSL. Install: git + jq + haktldextract")

    # Use a WSL temp dir as working directory so output files are predictable
    wsl_tmp = "/tmp/moneyscope_out"
    _wsl(f"mkdir -p {wsl_tmp}")

    flag = f"-{sources}"
    run = _wsl(f"bash {SCRIPT} {flag}", cwd=wsl_tmp)

    if run.returncode != 0:
        raise RuntimeError(f"MoneyScope failed: {run.stderr}")

    # Read output files — names depend on flag used
    prefix_map = {
        "a": "all", "i": "intigriti", "h": "h1",
        "b": "bugcrowd", "y": "yeswehack", "o": "other",
    }

    domains: list[str] = []
    tlds: list[str] = []

    for char in sources:
        prefix = prefix_map.get(char, char)
        d = _wsl(f"cat {wsl_tmp}/{prefix}_bbscope.txt 2>/dev/null || true")
        t = _wsl(f"cat {wsl_tmp}/{prefix}_bbscope_tld.txt 2>/dev/null || true")
        domains += [ln for ln in d.stdout.splitlines() if ln.strip()]
        tlds += [ln for ln in t.stdout.splitlines() if ln.strip()]

    # Dedup
    domains = sorted(set(domains))
    tlds = sorted(set(tlds))

    return {
        "domains": domains,
        "tlds": tlds,
        "source_flags": sources,
        "domain_count": len(domains),
        "tld_count": len(tlds),
    }


def save_scope(sources: str = "a", out_dir: str = "06_FINDINGS") -> tuple[str, str]:
    """Run get_scope and persist results to forge findings dir. Returns (domains_path, tlds_path)."""
    result = get_scope(sources)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    d_path = f"{out_dir}/bbscope_{sources}_domains.txt"
    t_path = f"{out_dir}/bbscope_{sources}_tlds.txt"
    Path(d_path).write_text("\n".join(result["domains"]))
    Path(t_path).write_text("\n".join(result["tlds"]))
    print(f"[MoneyScope] {result['domain_count']} domains → {d_path}")
    print(f"[MoneyScope] {result['tld_count']} TLDs     → {t_path}")
    return d_path, t_path


if __name__ == "__main__":
    # self-check: print domain count from HackerOne only (fast)
    r = get_scope("h")
    assert r["domain_count"] > 0, "Expected HackerOne domains, got 0"
    print(f"OK — {r['domain_count']} H1 domains, {r['tld_count']} TLDs")
