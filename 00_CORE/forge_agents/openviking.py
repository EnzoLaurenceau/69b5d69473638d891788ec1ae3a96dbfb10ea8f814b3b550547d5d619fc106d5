"""
openviking.py — REMPLACÉ par nexus_bridge (Memory brick)
=========================================================
Shim de compatibilité : les imports existants continuent de fonctionner.
Toute la logique est dans nexus_bridge.memory_retrieve() / memory_store().
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .nexus_bridge import memory_retrieve, memory_store

@dataclass
class VikingContext:
    content: str
    is_fallback: bool
    sources: list
    query: str
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return bool(self.content and not self.is_fallback)

class _Viking:
    def retrieve_context(self, query: str, task_type: str = "",
                         top_k: int = 5, max_chars: int = 1200) -> VikingContext:
        text = memory_retrieve(query, k=top_k, max_chars=max_chars)
        return VikingContext(
            content=text,
            is_fallback=not bool(text),
            sources=[],
            query=query,
        )

    def get_findings_context(self, max_chars: int = 1200) -> str:
        # ponytail: findings = confirmed-findings slice of unified memory; "" if none.
        text = memory_retrieve("confirmed findings résumé", k=5, max_chars=max_chars)
        return ("[Findings]\n" + text) if text else ""

_instance: Optional[_Viking] = None

def get_viking() -> _Viking:
    global _instance
    if _instance is None:
        _instance = _Viking()
    return _instance
