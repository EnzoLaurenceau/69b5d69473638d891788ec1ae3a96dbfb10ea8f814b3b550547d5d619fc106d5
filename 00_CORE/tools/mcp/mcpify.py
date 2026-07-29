"""
mcpify.py — Générateur automatique de MCP pour la Forge (camel-ai/mcpify).
==========================================================================
Source : https://github.com/camel-ai/mcpify

RÈGLE FORGE : quand un agent a besoin d'un logiciel/CLI/API pour automatiser une
tâche ET qu'AUCUN MCP n'existe pour ce logiciel → on en GÉNÈRE un automatiquement
avec mcpify (détection AST/LLM des APIs/commandes → config MCP → serveur MCP),
SANS modifier le code source du logiciel.

Flux :
    from tools.mcp import mcpify
    cfg = mcpify.ensure_mcp("https://github.com/user/some-cli", name="some_cli")
    # → clone (si URL) + détecte les commandes + écrit mcp/generated/some_cli.json
    print(mcpify.register_hint("some_cli"))   # comment brancher le MCP

CLI mcpify utilisée :
    mcpify detect <path> --output <cfg>        (auto)
    mcpify ast-detect <path> --output <cfg>    (statique, AUCUNE clé requise) ← défaut
    mcpify openai-detect / camel-detect ...    (LLM, nécessite une clé)
    mcpify validate <cfg>
    mcpify serve <cfg> --mode stdio|streamable-http

DÉPLOIEMENT (status: planned) :
    pip install mcpify          # + 'mcpify[ui]' pour l'UI Streamlit (optionnel)
    Sans install → ensure_mcp() lève McpifyUnavailable (l'agent le signale au user).
"""
from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path

FORGE_ROOT = Path(os.environ.get("FORGE_ROOT", Path(__file__).resolve().parents[3]))
GENERATED_DIR = FORGE_ROOT / "00_CORE" / "tools" / "mcp" / "generated"

_STRATEGY_CMD = {
    "auto": "detect",
    "ast": "ast-detect",        # statique, zéro clé → défaut Forge
    "openai": "openai-detect",  # nécessite OPENAI_API_KEY
    "camel": "camel-detect",
}


class McpifyUnavailable(RuntimeError):
    """mcpify non installé ou échec de génération."""


def is_available() -> bool:
    try:
        r = subprocess.run(["mcpify", "--help"], capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["mcpify", *args], capture_output=True, text=True, timeout=timeout)


def generate(project_path: str | Path, name: str, strategy: str = "ast",
             _runner=None) -> Path:
    """Détecte les APIs/commandes d'un projet local → config MCP dans mcp_generated/<name>.json.

    strategy: 'ast' (défaut, zéro clé) | 'auto' | 'openai' | 'camel'.
    _runner injectable pour les tests : (cmd_args:list) -> dict config.
    """
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    out = GENERATED_DIR / f"{name}.json"
    sub = _STRATEGY_CMD.get(strategy, "ast-detect")
    args = [sub, str(project_path), "--output", str(out)]

    if _runner is not None:  # test / stub
        out.write_text(json.dumps(_runner(args), indent=2), encoding="utf-8")
        return out

    if not is_available():
        raise McpifyUnavailable(
            "mcpify non installé. `pip install mcpify` puis réessaie "
            "(voir docstring tools/mcpify.py)."
        )
    r = _run(args)
    if r.returncode != 0 or not out.exists():
        raise McpifyUnavailable(f"mcpify {sub} a échoué: {(r.stderr or r.stdout)[-400:]}")
    # validation best-effort
    _run(["validate", str(out)])
    return out


def ensure_mcp(software: str, name: str, strategy: str = "ast", _runner=None) -> Path:
    """Garantit un MCP pour `software` (chemin local OU URL git). Génère si absent.

    Si déjà généré (mcp_generated/<name>.json existe), le retourne sans regénérer.
    """
    existing = GENERATED_DIR / f"{name}.json"
    if existing.exists():
        return existing

    path = software
    if str(software).startswith(("http://", "https://", "git@")):
        # clone shallow dans mcp_generated/<name>_src/
        src = GENERATED_DIR / f"{name}_src"
        if not src.exists():
            GENERATED_DIR.mkdir(parents=True, exist_ok=True)
            cl = subprocess.run(["git", "clone", "--depth", "1", str(software), str(src)],
                                capture_output=True, text=True, timeout=300)
            if cl.returncode != 0 and _runner is None:
                raise McpifyUnavailable(f"git clone échoué: {cl.stderr[-300:]}")
        path = src

    return generate(path, name, strategy=strategy, _runner=_runner)


def serve_command(name_or_config: str, mode: str = "stdio") -> str:
    """Commande pour lancer le MCP généré (à mettre dans la config MCP du client)."""
    cfg = name_or_config
    if not str(name_or_config).endswith(".json"):
        cfg = str(GENERATED_DIR / f"{name_or_config}.json")
    return f'mcpify serve "{cfg}" --mode {mode}'


def register_hint(name: str) -> str:
    """Explique comment brancher le MCP généré dans le client (Claude/forge)."""
    cfg = GENERATED_DIR / f"{name}.json"
    return (
        f"MCP '{name}' généré → {cfg}\n"
        f"Lancer (stdio) : {serve_command(name)}\n"
        f"Brancher dans le client MCP en pointant la commande ci-dessus "
        f"(ou mode streamable-http pour un endpoint réseau)."
    )


def demo():
    """ponytail: vérif runnable de la logique de génération (stub runner, sans mcpify)."""
    fake_cfg = {"name": "demo_cli", "backend": {"type": "commandline",
                "config": {"command": "python3", "args": ["./cli.py"]}},
                "tools": [{"name": "run", "description": "run", "args": ["--run"], "parameters": []}]}
    out = generate(FORGE_ROOT, "demo_cli", strategy="ast", _runner=lambda args: fake_cfg)
    assert out.exists() and json.loads(out.read_text(encoding="utf-8"))["name"] == "demo_cli"
    assert _STRATEGY_CMD["ast"] == "ast-detect"
    assert serve_command("demo_cli").endswith("--mode stdio")
    out.unlink()  # cleanup
    print("mcpify.demo OK |", register_hint("demo_cli").splitlines()[1])


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print("Usage: mcpify.py [generate <path> <name> [strategy] | ensure <software> <name> | "
              "serve-cmd <name> | available | demo]")
    elif a[0] == "generate" and len(a) >= 3:
        print(generate(a[1], a[2], a[3] if len(a) > 3 else "ast"))
    elif a[0] == "ensure" and len(a) >= 3:
        print(ensure_mcp(a[1], a[2]))
        print(register_hint(a[2]))
    elif a[0] == "serve-cmd" and len(a) >= 2:
        print(serve_command(a[1]))
    elif a[0] == "available":
        print(f"mcpify installé: {is_available()}")
    elif a[0] == "demo":
        demo()
    else:
        print("Unknown command.")
