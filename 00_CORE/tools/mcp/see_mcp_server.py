"""see_mcp_server.py — MCP bridge: LaForge SEE → Hermes Agent.

Exposes 3 tools: see_edit, see_plan, see_health.
Runs as stdio MCP server, stubs heavy forge_agents deps (langgraph etc).

Hermes config (~/.hermes/config.yaml):
    mcp_servers:
      see:
        command: "python"
        args: ["C:/Users/Jack/Documents/LaForge/00_CORE/tools/mcp/see_mcp_server.py"]
        env:
          FORGE_ROOT: "C:/Users/Jack/Documents/LaForge"
"""

from __future__ import annotations
import importlib.util, json, os, sys, types
from pathlib import Path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))
CORE = FORGE_ROOT / "00_CORE"
SEE_DIR = CORE / "forge_agents" / "semantic_edit_engine"

# Stub forge_agents packages to skip langgraph imports
for name, path in [("forge_agents", CORE / "forge_agents"),
                   ("forge_agents.semantic_edit_engine", SEE_DIR)]:
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [str(path)]; m.__package__ = name
        sys.modules[name] = m

# Load SEE modules in dependency order
for mod_name in [
    "edit_primitives", "edit_metrics", "symbol_resolver", "patch_scorer",
    "semantic_safety", "context_window", "patch_memory", "auto_rollback",
    "impact_gate", "patch_review", "patch_optimizer", "edit_pipeline",
]:
    fqn = f"forge_agents.semantic_edit_engine.{mod_name}"
    spec = importlib.util.spec_from_file_location(fqn, str(SEE_DIR / f"{mod_name}.py"))
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "forge_agents.semantic_edit_engine"
    sys.modules[fqn] = mod
    spec.loader.exec_module(mod)

# Load forge_llm for the instruction-based path (allows SEE to call LLM
# when modified_code is not provided — essential for universal editing)
_llm_path = CORE / "forge_agents" / "forge_llm.py"
if _llm_path.exists():
    try:
        fqn = "forge_agents.forge_llm"
        spec = importlib.util.spec_from_file_location(fqn, str(_llm_path))
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = "forge_agents"
        sys.modules[fqn] = mod
        spec.loader.exec_module(mod)
    except Exception as _e:
        import logging; logging.getLogger("see_mcp").warning("forge_llm load failed: %s", _e)

run_edit = sys.modules["forge_agents.semantic_edit_engine.edit_pipeline"].run_edit

from mcp.server.fastmcp import FastMCP
mcp = FastMCP("see", instructions="SEE — semantic code editing with blast-radius gates and auto-rollback.")

def _p(fp: str) -> Path:
    p = Path(fp)
    return p if p.is_absolute() else FORGE_ROOT / p

@mcp.tool()
def see_edit(file_path: str, instruction: str = "", target_name: str = "",
             modified_code: str = "", apply: bool = False,
             test_cmd: str = "", force: bool = False) -> str:
    """Edit any file via SEE. apply=False = dry-run (plan only).
    Works on ALL file types: Python, JS/TS, HTML, CSS, Vue, Svelte, Lua, GDScript,
    C#, C++, Rust, shaders (GLSL/HLSL/WGSL), PHP, Ruby, Markdown, JSON, YAML, etc.
    instruction = natural language change. target_name = function/class/element/file.
    modified_code = target code (0-token mode, most efficient).
    If modified_code is empty, SEE uses the LLM to generate it from the instruction.
    test_cmd = run after apply, auto-rollback if red. force = bypass blocking gates."""
    path = _p(file_path)
    if not path.exists():
        return json.dumps({"error": f"not found: {path}", "status": "no_plan"})
    res = run_edit(path, instruction=instruction, target_name=target_name or None,
                   modified_code=modified_code or None, apply=apply,
                   test_cmd=test_cmd or None, force=force)
    out = res.to_dict()
    out["applied"] = res.status == "applied"
    out["summary"] = res.summary()
    if res.diff: out["diff"] = res.diff
    return json.dumps(out, indent=2, ensure_ascii=False)

@mcp.tool()
def see_plan(file_path: str, instruction: str = "", target_name: str = "",
             modified_code: str = "") -> str:
    """Dry-run: show edit plan, strategy, ops, diff without writing."""
    return see_edit(file_path=file_path, instruction=instruction,
                    target_name=target_name, modified_code=modified_code)

@mcp.tool()
def see_health() -> str:
    """Check SEE engine status and gate availability."""
    return json.dumps({"engine": "ok", "forge_root": str(FORGE_ROOT),
        "gates": {n: n in sys.modules for n in [
            "forge_agents.semantic_edit_engine.edit_primitives",
            "forge_agents.semantic_edit_engine.patch_optimizer",
            "forge_agents.semantic_edit_engine.edit_pipeline"]},
        "tools": ["see_edit", "see_plan", "see_health"]}, indent=2)

if __name__ == "__main__":
    mcp.run(transport="stdio")
