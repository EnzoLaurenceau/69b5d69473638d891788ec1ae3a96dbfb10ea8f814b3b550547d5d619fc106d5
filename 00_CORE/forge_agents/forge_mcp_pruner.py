"""
forge_mcp_pruner.py — V6 MCP Pruning Engine
Détecte les outils MCP inutilisés et recommande le pruning.
C'est LE levier #1 de réduction de coût (GitHub: 62% ET reduction).

Problème : les LLM APIs sont stateless → tool schemas inclus à CHAQUE requête.
  - 1 outil MCP = ~300-400 bytes de JSON schema
  - 40 outils = 10-15 KB/tour
  - Supprimer les inutilisés = 8-12 KB économisés/appel

Solution :
  1. Tracker l'utilisation de chaque outil MCP
  2. Calculer le schema size de chaque outil
  3. Recommander le pruning des outils à 0 appel
  4. Remplacer les appels MCP simples par CLI (gh, curl, etc.)

Intégration : forge_experience_db fournit les données d'utilisation.
"""

from __future__ import annotations
import json
import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


FORGE_ROOT = Path(__file__).parent.parent.parent


@dataclass
class MCPToolStats:
    """Stats d'utilisation d'un outil MCP."""
    tool_name: str
    server: str = ""
    schema_size_bytes: int = 0     # taille du JSON schema
    call_count: int = 0            # nombre d'appels
    last_called: str = ""
    total_tokens: int = 0          # tokens consommés par cet outil
    avg_latency: float = 0.0
    success_rate: float = 1.0
    can_replace_with_cli: bool = False  # remplaçable par CLI ?
    cli_alternative: str = ""      # ex: "gh pr diff", "curl ..."

    @property
    def is_unused(self) -> bool:
        return self.call_count == 0

    @property
    def cost_per_call(self) -> float:
        """Coût estimé par appel (schema overhead inclus)."""
        # Schema ajouté à chaque tour de conversation
        return self.schema_size_bytes * 0.00003  # estimation

    @property
    def potential_savings(self) -> float:
        """Économies si pruned (en tokens)."""
        if self.is_unused:
            return self.schema_size_bytes
        return 0


@dataclass
class PruneRecommendation:
    """Recommandation de pruning."""
    tool_name: str
    action: str  # "prune" | "replace_with_cli" | "keep"
    reason: str
    schema_savings_bytes: int = 0
    estimated_token_savings: int = 0
    priority: str = "medium"  # critical | high | medium | low


class MCPPruningEngine:
    """
    Moteur de pruning MCP.
    Analyse l'utilisation des outils et recommande des optimisations.
    """

    def __init__(self):
        self._tools: dict[str, MCPToolStats] = {}
        self._recommendations: list[dict] = []

    def register_tool(self, name: str, server: str = "",
                      schema_size: int = 350, can_replace_cli: bool = False,
                      cli_alt: str = "") -> None:
        """Enregistre un outil MCP."""
        self._tools[name] = MCPToolStats(
            tool_name=name,
            server=server,
            schema_size_bytes=schema_size,
            can_replace_with_cli=can_replace_cli,
            cli_alternative=cli_alt,
        )

    def record_call(self, name: str, tokens: int = 0, latency: float = 0,
                    success: bool = True) -> None:
        """Enregistre un appel MCP."""
        if name not in self._tools:
            self._tools[name] = MCPToolStats(tool_name=name)
        tool = self._tools[name]
        tool.call_count += 1
        tool.total_tokens += tokens
        tool.last_called = datetime.datetime.now().isoformat()
        if latency:
            n = tool.call_count
            tool.avg_latency = ((tool.avg_latency * (n - 1)) + latency) / n

    def scan_from_experience_db(self) -> None:
        """
        Scanne l'experience DB pour peupler les stats d'utilisation.
        Lit le fichier experience_db.json directement.
        """
        db_path = FORGE_ROOT / "05_STATE" / "experience_db.json"
        if not db_path.exists():
            return
        try:
            data = json.loads(db_path.read_text(encoding="utf-8"))
            comp_health = data.get("component_health", {})
            for cid, health in comp_health.items():
                if cid not in self._tools:
                    self._tools[cid] = MCPToolStats(tool_name=cid)
                tool = self._tools[cid]
                tool.call_count = health.get("total_calls", 0)
                tool.total_tokens = health.get("total_tokens", 0)
                tool.last_used = health.get("last_used", "")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def analyze(self) -> list[PruneRecommendation]:
        """Analyse et génère les recommandations de pruning."""
        recs = []
        for name, tool in self._tools.items():
            if tool.is_unused:
                recs.append(PruneRecommendation(
                    tool_name=name,
                    action="prune",
                    reason=f"0 calls — dead weight ({tool.schema_size_bytes}B/turn)",
                    schema_savings_bytes=tool.schema_size_bytes,
                    estimated_token_savings=tool.schema_size_bytes,
                    priority="critical",
                ))
            elif tool.can_replace_with_cli and tool.call_count < 10:
                recs.append(PruneRecommendation(
                    tool_name=name,
                    action="replace_with_cli",
                    reason=f"Only {tool.call_count} calls — replace with {tool.cli_alternative}",
                    schema_savings_bytes=tool.schema_size_bytes,
                    estimated_token_savings=tool.schema_size_bytes,
                    priority="high",
                ))

        # Sort by priority
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda r: order.get(r.priority, 9))
        self._recommendations = [asdict(r) for r in recs]
        return recs

    def get_summary(self) -> dict:
        """Résumé du pruning."""
        total = len(self._tools)
        unused = sum(1 for t in self._tools.values() if t.is_unused)
        total_schema = sum(t.schema_size_bytes for t in self._tools.values())
        unused_schema = sum(t.schema_size_bytes for t in self._tools.values() if t.is_unused)
        return {
            "total_tools": total,
            "unused_tools": unused,
            "unused_pct": unused / max(total, 1),
            "total_schema_bytes": total_schema,
            "unused_schema_bytes": unused_schema,
            "potential_savings_per_call": unused_schema,
            "recommendations": self._recommendations,
            "github_benchmark": "62% ET reduction via MCP pruning + CLI replacement",
        }

    def auto_register_from_registry(self) -> None:
        """
        Auto-enregistre les outils depuis le registry.json de la Forge.
        Estime le schema size depuis la docstring/fichier.
        """
        registry_path = FORGE_ROOT / "00_CORE" / "tools" / "registry.json"
        if not registry_path.exists():
            return
        try:
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            for entry in reg.get("tools", []):
                if not isinstance(entry, str) or not entry.startswith("TOOL|"):
                    continue
                parts = entry.split("|")
                if len(parts) < 7:
                    continue
                name = parts[1]
                purpose = parts[4]
                wrapper = parts[5]

                # Estimer le schema size depuis le fichier wrapper
                schema_size = 350  # default
                wrapper_path = FORGE_ROOT / "00_CORE" / wrapper
                if wrapper_path.exists():
                    try:
                        content = wrapper_path.read_text(encoding="utf-8")
                        # Schema size ≈ longueur du docstring + noms de fonctions
                        doc_lines = [l for l in content.split("\n") if '"""' in l or "'''" in l]
                        schema_size = min(len(content) // 10, 800)  # rough estimate
                    except Exception as exc:
                        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

                # Détecter les remplacements CLI possibles
                can_cli = False
                cli_alt = ""
                if "github" in purpose.lower() or "gh " in purpose.lower():
                    can_cli = True
                    cli_alt = "gh CLI"
                elif "api" in purpose.lower() and "rest" in purpose.lower():
                    can_cli = True
                    cli_alt = "curl"

                if name not in self._tools:
                    self.register_tool(name, schema_size=schema_size,
                                       can_replace_cli=can_cli, cli_alt=cli_alt)
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def save(self) -> None:
        """Persiste les recommandations."""
        out_path = FORGE_ROOT / "05_STATE" / "mcp_pruning_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": datetime.datetime.now().isoformat(),
            **self.get_summary(),
        }
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


# Singleton
_pruner: Optional[MCPPruningEngine] = None


def get_pruner() -> MCPPruningEngine:
    global _pruner
    if _pruner is None:
        _pruner = MCPPruningEngine()
        _pruner.auto_register_from_registry()
        _pruner.scan_from_experience_db()
    return _pruner


def refresh_pruner() -> MCPPruningEngine:
    global _pruner
    _pruner = MCPPruningEngine()
    _pruner.auto_register_from_registry()
    _pruner.scan_from_experience_db()
    return _pruner


if __name__ == "__main__":
    pruner = get_pruner()
    pruner.analyze()
    pruner.save()
    s = pruner.get_summary()
    print(f"Tools: {s['total_tools']}")
    print(f"Unused: {s['unused_tools']} ({s['unused_pct']:.0%})")
    print(f"Schema: {s['total_schema_bytes']}B total, {s['unused_schema_bytes']}B unused")
    print(f"Savings: {s['potential_savings_per_call']}B/call")
    print(f"\nRecommendations:")
    for r in s["recommendations"]:
        print(f"  [{r['priority']}] {r['action']} {r['tool_name']}: {r['reason']}")
