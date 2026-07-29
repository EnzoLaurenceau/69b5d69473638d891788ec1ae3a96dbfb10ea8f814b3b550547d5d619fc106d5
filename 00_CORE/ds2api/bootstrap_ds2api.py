"""
bootstrap_ds2api.py — Auto-start ds2api + health check + LLM test
Called at forge startup. Idempotent.
"""
from __future__ import annotations
import json, time, sys, subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = FORGE_ROOT / "00_CORE" / "ds2api" / "config.json"
DS2API_BASE = "http://localhost:5001"
DS2API_KEY  = "forge-local-key"

def _log(msg: str, level: str = "INFO"):
    print(f"[DS2API-{level}] {msg}")

def _docker_running() -> bool:
    """Check if ds2api container is running."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", "ds2api"],
            capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0 and "true" in r.stdout.lower()
    except Exception:
        return False

def _docker_exists() -> bool:
    """Check if ds2api container exists (stopped or running)."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "ds2api"],
            capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False

def _start_container() -> bool:
    """Start or create+start ds2api container."""
    if not CONFIG_PATH.exists():
        _log(f"Config missing: {CONFIG_PATH}", "ERR")
        return False

    # Check if config has placeholder credentials
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        accounts = cfg.get("accounts", [])
        if not accounts or "REMPLIR_EMAIL" in str(accounts):
            _log("Config has placeholder credentials — fill in DeepSeek email/password", "ERR")
            return False
    except Exception as e:
        _log(f"Config parse error: {e}", "ERR")
        return False

    # Remove stopped container if exists
    if _docker_exists() and not _docker_running():
        _log("Removing stopped ds2api container...")
        subprocess.run(["docker", "rm", "-f", "ds2api"],
                       capture_output=True, timeout=15)

    # Pull image if not present
    _log("Pulling ds2api image (if needed)...")
    subprocess.run(
        ["docker", "pull", "ghcr.io/cjackhwang/ds2api:latest"],
        capture_output=True, timeout=120
    )

    # Start container
    _log("Starting ds2api container on port 5001...")
    r = subprocess.run([
        "docker", "run", "-d",
        "--name", "ds2api",
        "--restart", "unless-stopped",
        "-p", "5001:5001",
        "-v", f"{CONFIG_PATH}:/app/config.json:ro",
        "-e", "DS2API_ADMIN_KEY=forge-admin",
        "ghcr.io/cjackhwang/ds2api:latest",
    ], capture_output=True, text=True, timeout=30)

    if r.returncode != 0:
        # Container name conflict — remove and retry
        if "already in use" in r.stderr:
            subprocess.run(["docker", "rm", "-f", "ds2api"],
                           capture_output=True, timeout=15)
            r = subprocess.run([
                "docker", "run", "-d",
                "--name", "ds2api",
                "--restart", "unless-stopped",
                "-p", "5001:5001",
                "-v", f"{CONFIG_PATH}:/app/config.json:ro",
                "-e", "DS2API_ADMIN_KEY=forge-admin",
                "ghcr.io/cjackhwang/ds2api:latest",
            ], capture_output=True, text=True, timeout=30)

    if r.returncode != 0:
        _log(f"Docker start failed: {r.stderr[:200]}", "ERR")
        return False

    _log(f"Container started: {r.stdout.strip()[:12]}")
    return True

def _wait_health(timeout: int = 20) -> bool:
    """Wait for ds2api /healthz to respond."""
    _log(f"Waiting for healthz (max {timeout}s)...")
    import urllib.request, urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{DS2API_BASE}/healthz")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    _log("Health check PASSED ✓")
                    return True
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        time.sleep(1)
    _log("Health check FAILED — ds2api not responding", "ERR")
    return False

def _test_llm() -> bool:
    """Test a real LLM call through ds2api."""
    _log("Testing LLM call...")
    import urllib.request
    try:
        body = json.dumps({
            "model": "deepseek-v4-flash-nothinking",
            "messages": [{"role": "user", "content": "Say OK in 1 word."}],
            "max_tokens": 10,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{DS2API_BASE}/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {DS2API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            _log(f"LLM test PASSED ✓ — response: '{text[:50]}'")
            return True
    except Exception as e:
        _log(f"LLM test FAILED: {e}", "ERR")
        return False

def bootstrap_ds2api() -> dict:
    """
    Full bootstrap: start container → health check → LLM test.
    Returns status dict. Idempotent.
    """
    result = {"container": False, "health": False, "llm_test": False, "ready": False}

    # 1. Already running?
    if _docker_running():
        _log("Container already running ✓")
        result["container"] = True
    else:
        # Check Docker available
        try:
            subprocess.run(["docker", "version"],
                          capture_output=True, timeout=5)
        except Exception:
            _log("Docker not available — ds2api disabled", "WARN")
            return result

        result["container"] = _start_container()
        if not result["container"]:
            return result

    # 2. Health check
    result["health"] = _wait_health()
    if not result["health"]:
        return result

    # 3. LLM test
    result["llm_test"] = _test_llm()
    result["ready"] = result["container"] and result["health"] and result["llm_test"]

    if result["ready"]:
        _log("DS2API READY — all checks passed ✓")
    else:
        _log("DS2API PARTIAL — some checks failed", "WARN")

    return result

if __name__ == "__main__":
    status = bootstrap_ds2api()
    print(json.dumps(status, indent=2))
    sys.exit(0 if status["ready"] else 1)
