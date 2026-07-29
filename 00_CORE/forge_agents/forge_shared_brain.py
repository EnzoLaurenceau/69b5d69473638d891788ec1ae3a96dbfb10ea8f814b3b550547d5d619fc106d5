"""
forge_shared_brain.py — V6 Shared Brain Architecture
Transforme la Forge en mémoire + raisonnement central partagé.

AVANT (isolation) :
  Agent A → MCP + reasoning (isolé)
  Agent B → MCP + reasoning (isolé)
  → explosion tokens, duplication, inefficacité

APRÈS (mutualisé) :
  FORGE CORE BRAIN
     ↓
  shared kernel / shared retrieval / shared memory / shared MCP cache
     ↓
  agents = workers légers

Composants :
  1. GlobalKernelStore — un kernel unique, tous les agents le lisent
  2. MCPProxyCache — cache MCP global (premier fetch → tous réutilisent)
  3. SharedReasoningState — décisions partagées, zéro duplication
  4. ContextInjector — injecte le contexte partagé dans chaque agent
"""

from __future__ import annotations
import json
import time
import hashlib
import threading
import datetime
from typing import Any, Optional
from dataclasses import dataclass, field

from .forge_kernel import Kernel, get_or_extract_kernel


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GLOBAL KERNEL STORE
# ═══════════════════════════════════════════════════════════════════════════════

class GlobalKernelStore:
    """
    Stocke le kernel courant. Tous les agents lisent le même.
    Zéro re-parsing individuel.
    """

    def __init__(self):
        self._kernel: Optional[Kernel] = None
        self._lock = threading.Lock()
        self._access_count = 0
        self._last_access: Optional[str] = None

    def set(self, kernel: Kernel) -> None:
        """Définit le kernel de la session courante."""
        with self._lock:
            self._kernel = kernel
            self._access_count = 0

    def get(self) -> Optional[Kernel]:
        """Récupère le kernel partagé (tous les agents appellent ça)."""
        with self._lock:
            self._access_count += 1
            self._last_access = datetime.datetime.now().isoformat()
            return self._kernel

    def get_or_create(self, task: str) -> Kernel:
        """Récupère ou crée le kernel pour une tâche."""
        with self._lock:
            if self._kernel is None or self._kernel.is_stale():
                self._kernel = get_or_extract_kernel(task)
                self._access_count = 0
            self._access_count += 1
            self._last_access = datetime.datetime.now().isoformat()
            return self._kernel

    def stats(self) -> dict:
        with self._lock:
            return {
                "has_kernel": self._kernel is not None,
                "kernel_id": self._kernel.kernel_id if self._kernel else None,
                "access_count": self._access_count,
                "last_access": self._last_access,
                "stale": self._kernel.is_stale() if self._kernel else True,
            }

    def clear(self) -> None:
        with self._lock:
            self._kernel = None
            self._access_count = 0


# Singleton global
_global_kernel_store = GlobalKernelStore()


def get_kernel_store() -> GlobalKernelStore:
    return _global_kernel_store


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MCP PROXY CACHE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CachedMCPResult:
    """Résultat MCP mis en cache."""
    tool_name: str
    args_hash: str
    result: Any
    cached_at: float
    ttl: float = 300.0  # 5 min par défaut
    hit_count: int = 0
    cost_saved: float = 0.0  # tokens économisés

    def is_valid(self) -> bool:
        return (time.time() - self.cached_at) < self.ttl


class MCPProxyCache:
    """
    Cache MCP intelligent.
    Premier agent fetch → résultat caché → tous les autres réutilisent.
    Division du coût MCP par 5 à 20x.
    """

    def __init__(self, max_entries: int = 200):
        self._cache: dict[str, CachedMCPResult] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._total_hits = 0
        self._total_misses = 0
        self._total_cost_saved = 0.0

    def _make_key(self, tool_name: str, args: dict) -> str:
        """Clé de cache = hash(tool_name + args sérialisés)."""
        raw = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, tool_name: str, args: dict) -> Optional[Any]:
        """Vérifie le cache. Retourne None si miss."""
        key = self._make_key(tool_name, args)
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.is_valid():
                entry.hit_count += 1
                self._total_hits += 1
                return entry.result
            elif entry:
                # Expired
                del self._cache[key]
            self._total_misses += 1
            return None

    def put(self, tool_name: str, args: dict, result: Any,
            ttl: float = 300.0, estimated_tokens: int = 0) -> None:
        """Cache un résultat MCP."""
        key = self._make_key(tool_name, args)
        with self._lock:
            # Eviction LRU simple si plein
            if len(self._cache) >= self._max_entries:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].cached_at)
                del self._cache[oldest_key]

            self._cache[key] = CachedMCPResult(
                tool_name=tool_name,
                args_hash=key,
                result=result,
                cached_at=time.time(),
                ttl=ttl,
                cost_saved=estimated_tokens * 0.00003,  # estimation coût
            )

    def invalidate(self, tool_name: str = None) -> int:
        """Invalide le cache (tout ou pour un outil spécifique)."""
        with self._lock:
            if tool_name:
                keys = [k for k, v in self._cache.items() if v.tool_name == tool_name]
                for k in keys:
                    del self._cache[k]
                return len(keys)
            count = len(self._cache)
            self._cache.clear()
            return count

    def stats(self) -> dict:
        with self._lock:
            total = self._total_hits + self._total_misses
            return {
                "entries": len(self._cache),
                "hits": self._total_hits,
                "misses": self._total_misses,
                "hit_rate": self._total_hits / max(total, 1),
                "total_cost_saved": sum(e.cost_saved for e in self._cache.values()),
            }


# Singleton global
_mcp_cache = MCPProxyCache()


def get_mcp_cache() -> MCPProxyCache:
    return _mcp_cache


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SHARED REASONING STATE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ReasoningEntry:
    """Une décision/entrée dans le raisonnement partagé."""
    key: str
    value: Any
    source_agent: str
    confidence: float
    timestamp: str = ""
    contradicted_by: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now().isoformat()


class SharedReasoningState:
    """
    État de raisonnement partagé entre tous les agents.
    Tous les agents ÉCRIVENT dedans → zéro duplication de réflexion.
    Contient : decisions, rejected_options, confirmed_facts, partial_solutions.
    """

    def __init__(self):
        self._decisions: dict[str, ReasoningEntry] = {}
        self._rejected: list[dict] = []
        self._confirmed_facts: dict[str, ReasoningEntry] = {}
        self._partial_solutions: list[dict] = []
        self._retrieved_docs: list[str] = []
        self._lock = threading.Lock()

    def add_decision(self, key: str, value: Any, agent: str, confidence: float = 0.8) -> None:
        """Enregistre une décision prise par un agent."""
        with self._lock:
            existing = self._decisions.get(key)
            if existing and existing.confidence >= confidence:
                return  # Ne pas écraser une décision plus confiante
            self._decisions[key] = ReasoningEntry(
                key=key, value=value, source_agent=agent, confidence=confidence
            )

    def add_confirmed_fact(self, fact: str, agent: str, confidence: float = 0.9) -> None:
        """Enregistre un fait confirmé."""
        with self._lock:
            self._confirmed_facts[fact] = ReasoningEntry(
                key=fact, value=True, source_agent=agent, confidence=confidence
            )

    def reject_option(self, option: str, reason: str, agent: str) -> None:
        """Enregistre une option rejetée (évite que d'autres agents la reprennent)."""
        with self._lock:
            self._rejected.append({
                "option": option,
                "reason": reason,
                "agent": agent,
                "timestamp": datetime.datetime.now().isoformat(),
            })

    def add_partial_solution(self, solution: dict, agent: str) -> None:
        """Enregistre une solution partielle (pour fusion ultérieure)."""
        with self._lock:
            self._partial_solutions.append({
                **solution,
                "source_agent": agent,
                "timestamp": datetime.datetime.now().isoformat(),
            })

    def add_retrieved_doc(self, doc_ref: str) -> None:
        """Enregistre un document récupéré (évite re-fetch)."""
        with self._lock:
            if doc_ref not in self._retrieved_docs:
                self._retrieved_docs.append(doc_ref)

    def was_rejected(self, option: str) -> bool:
        """Vérifie si une option a déjà été rejetée."""
        with self._lock:
            return any(r["option"] == option for r in self._rejected)

    def get_decision(self, key: str) -> Optional[Any]:
        """Récupère une décision existante."""
        with self._lock:
            entry = self._decisions.get(key)
            return entry.value if entry else None

    def get_all_decisions(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._decisions.items()}

    def get_confirmed_facts(self) -> list[str]:
        with self._lock:
            return list(self._confirmed_facts.keys())

    def get_context_summary(self) -> str:
        """Résumé compact du raisonnement pour injection dans agents légers."""
        with self._lock:
            parts = []
            if self._decisions:
                decisions_str = "; ".join(f"{k}={v.value}" for k, v in list(self._decisions.items())[:5])
                parts.append(f"DECISIONS: {decisions_str}")
            if self._confirmed_facts:
                facts_str = "; ".join(list(self._confirmed_facts.keys())[:5])
                parts.append(f"FACTS: {facts_str}")
            if self._rejected:
                rejected_str = "; ".join(r["option"] for r in self._rejected[-3:])
                parts.append(f"REJECTED: {rejected_str}")
            if self._retrieved_docs:
                parts.append(f"DOCS: {len(self._retrieved_docs)} retrieved")
            return " | ".join(parts) if parts else "(no shared reasoning yet)"

    def stats(self) -> dict:
        with self._lock:
            return {
                "decisions": len(self._decisions),
                "confirmed_facts": len(self._confirmed_facts),
                "rejected_options": len(self._rejected),
                "partial_solutions": len(self._partial_solutions),
                "retrieved_docs": len(self._retrieved_docs),
            }

    def clear(self) -> None:
        with self._lock:
            self._decisions.clear()
            self._rejected.clear()
            self._confirmed_facts.clear()
            self._partial_solutions.clear()
            self._retrieved_docs.clear()


# Singleton global
_shared_reasoning = SharedReasoningState()


def get_shared_reasoning() -> SharedReasoningState:
    return _shared_reasoning


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CONTEXT INJECTOR — Forge Context Injection Layer
# ═══════════════════════════════════════════════════════════════════════════════

def build_agent_context(
    task: str,
    agent_name: str,
    allowed_tools: list[str] = None,
) -> dict:
    """
    Construit le contexte partagé à injecter dans CHAQUE agent.
    C'est LE mécanisme V6 qui élimine la duplication de raisonnement.

    Chaque agent reçoit :
      - global_kernel (intent, entities, capabilities)
      - shared_memory_snapshot (décisions, faits, rejets)
      - cached_mcp_results (ce qui est déjà fetché)
      - allowed_tools (outils autorisés pour cet agent)
      - previous_decisions (pour éviter de re-décider)
    """
    kernel_store = get_kernel_store()
    reasoning = get_shared_reasoning()
    mcp = get_mcp_cache()

    kernel = kernel_store.get_or_create(task)

    return {
        "global_kernel": kernel.to_dict(),
        "shared_memory_snapshot": reasoning.get_context_summary(),
        "cached_mcp_stats": mcp.stats(),
        "allowed_tools": allowed_tools or [],
        "previous_decisions": reasoning.get_all_decisions(),
        "confirmed_facts": reasoning.get_confirmed_facts(),
        "hallucination_checkpoint": kernel.to_checkpoint(),
        "agent_name": agent_name,
    }


def format_context_for_prompt(context: dict) -> str:
    """Formate le contexte partagé en texte injectable dans un system prompt."""
    lines = [
        "=== FORGE SHARED CONTEXT (V6) ===",
        f"Task: {context['global_kernel'].get('core_intent', '?')}",
        f"Domain: {context['global_kernel'].get('domain', '?')}",
        f"Complexity: {context['global_kernel'].get('complexity_estimate', '?')}",
        f"Agent: {context['agent_name']}",
    ]

    if context.get("shared_memory_snapshot"):
        lines.append(f"Shared Reasoning: {context['shared_memory_snapshot']}")

    if context.get("confirmed_facts"):
        lines.append(f"Confirmed Facts: {'; '.join(context['confirmed_facts'][:5])}")

    if context.get("previous_decisions"):
        decs = "; ".join(f"{k}={v}" for k, v in list(context["previous_decisions"].items())[:3])
        lines.append(f"Previous Decisions: {decs}")

    checkpoint = context.get("hallucination_checkpoint", {})
    if checkpoint.get("unknowns"):
        lines.append(f"Unknowns: {'; '.join(checkpoint['unknowns'][:3])}")

    lines.append("=== END SHARED CONTEXT ===")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BRAIN ORCHESTRATOR — coordonne les 3 composants
# ═══════════════════════════════════════════════════════════════════════════════

class ForgeBrain:
    """
    Orchestrateur du Shared Brain.
    Point d'entrée unique pour les nodes LangGraph.
    """

    def __init__(self):
        self.kernel_store = get_kernel_store()
        self.mcp_cache = get_mcp_cache()
        self.reasoning = get_shared_reasoning()

    def initialize_for_task(self, task: str) -> Kernel:
        """Initialise le brain pour une nouvelle tâche."""
        self.reasoning.clear()
        self.mcp_cache.invalidate()
        kernel = self.kernel_store.get_or_create(task)
        return kernel

    def get_agent_context(self, task: str, agent_name: str, tools: list[str] = None) -> str:
        """Retourne le contexte formaté pour un agent."""
        ctx = build_agent_context(task, agent_name, tools)
        return format_context_for_prompt(ctx)

    def record_mcp_call(self, tool: str, args: dict, result: Any, tokens: int = 0) -> None:
        """Enregistre un appel MCP dans le cache partagé."""
        self.mcp_cache.put(tool, args, result, estimated_tokens=tokens)

    def check_mcp_cache(self, tool: str, args: dict) -> Optional[Any]:
        """Vérifie si un résultat MCP est déjà en cache."""
        return self.mcp_cache.get(tool, args)

    def full_stats(self) -> dict:
        """Stats complètes du brain."""
        return {
            "kernel": self.kernel_store.stats(),
            "mcp_cache": self.mcp_cache.stats(),
            "reasoning": self.reasoning.stats(),
        }

    def reset(self) -> None:
        """Reset complet (nouvelle session)."""
        self.kernel_store.clear()
        self.mcp_cache.invalidate()
        self.reasoning.clear()


# Singleton
_forge_brain: Optional[ForgeBrain] = None


def get_brain() -> ForgeBrain:
    global _forge_brain
    if _forge_brain is None:
        _forge_brain = ForgeBrain()
    return _forge_brain


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    brain = get_brain()
    task = "Build a Telegram hotel concierge bot with booking API"
    kernel = brain.initialize_for_task(task)
    print(f"Kernel: {kernel.core_intent}")
    print(f"Domain: {kernel.domain}")
    print(f"Capabilities: {kernel.required_capabilities}")

    # Simulate shared reasoning
    brain.reasoning.add_decision("framework", "python-telegram-bot", "orchestrator", 0.9)
    brain.reasoning.add_confirmed_fact("API uses REST JSON", "researcher", 0.95)
    brain.reasoning.reject_option("webhook-based", "latency too high", "critic")

    # Generate context for a sub-agent
    ctx = brain.get_agent_context(task, "builder", ["terminal", "file", "web"])
    print(f"\n{ctx}")
    print(f"\nBrain stats: {json.dumps(brain.full_stats(), indent=2)}")
