"""
open_osint.py — Wrapper OpenOSINT pour la Forge (OSINT agent)
==============================================================
Repo    : https://github.com/OpenOSINT/OpenOSINT
Install : pip install openosint holehe sherlock-project sublist3r
MCP     : claude mcp add openosint python <path>/openosint/mcp_server.py
          → 18 outils exposés nativement à Claude Code (préférer le MCP en session)

Règle DO NOT INVENT : on appelle openosint CLI, pas de réimplémentation.

18 outils disponibles :
  email · username · breach · whois · ip · domain · dorks · paste
  phone · shodan · virustotal · censys · ip2location · abuseipdb
  github · dns · dorks_live · scrape_url

Clés API (optionnelles, dans .env) :
  ANTHROPIC_API_KEY (requis pour le mode AI)
  SHODAN_API_KEY · VIRUSTOTAL_API_KEY · CENSYS_API_ID · CENSYS_SECRET
  HIBP_API_KEY · IP2LOCATION_API_KEY · ABUSEIPDB_API_KEY · IPINFO_TOKEN
"""

from __future__ import annotations
import subprocess
import json
from typing import Any

# ponytail: subprocess wrapping only — 18 tools live in the package itself


def _run(args: list[str], timeout: int = 60) -> str:
    """Run openosint CLI and return stdout."""
    result = subprocess.run(
        ["openosint"] + args + ["--json"],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout or result.stderr


def investigate(target: str, parallel: bool = True, no_pdf: bool = True) -> dict:
    """
    AI-powered OSINT investigation (uses ANTHROPIC_API_KEY).
    target: email, username, IP, domain, phone number
    """
    flags = ["--no-pdf"] if no_pdf else []
    if parallel:
        flags.append("--parallel")
    raw = _run(flags + [target])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def email(address: str) -> dict:
    raw = _run(["email", address])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def username(handle: str) -> dict:
    raw = _run(["username", handle])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def ip(address: str) -> dict:
    raw = _run(["ip2location", address])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def domain(target: str) -> dict:
    raw = _run(["dns", target])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def shodan(query: str) -> dict:
    raw = _run(["shodan", query])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def github(query: str) -> dict:
    raw = _run(["github", query])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def multi(targets: list[str]) -> dict:
    """Parallel multi-target investigation (max 10)."""
    raw = _run(["multi"] + targets[:10])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


if __name__ == "__main__":
    # self-check: version + tool count (no API key needed)
    result = subprocess.run(["openosint", "--help"], capture_output=True, text=True)
    assert "openosint" in result.stdout.lower() or result.returncode == 0, "openosint not found"
    print("OK — openosint installed and reachable")
    print("MCP: claude mcp list  (check openosint is registered)")
