"""
semantic_cache.py — utilitaires SimHash (garder) + SemanticCache → Nexus CAS
=============================================================================
_tokenize / _simhash / _hamming_similarity : utilisés par forge_db.py (garder).
SemanticCache : redirige vers nexus_bridge (Nexus CAS remplace le JSON local).
"""
from __future__ import annotations
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

FORGE_ROOT = Path(__file__).parent.parent.parent
SIMILARITY_THRESHOLD = 0.95

@dataclass
class CacheEntry:
    signature: str
    file_path: str
    line_range: str
    result: str
    score: float
    timestamp: float
    hit_count: int = 0

# ─── Utilitaires SimHash (conservés — importés par forge_db) ─────────────────

def _tokenize(code: str) -> list[str]:
    return re.findall(r'[a-zA-Z_]\w*|\d+\.?\d*|[^\s\w]', code.lower())

def _simhash(tokens: list[str], hashbits: int = 64) -> int:
    v = [0] * hashbits
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        for i in range(hashbits):
            v[i] += 1 if h & (1 << i) else -1
    fingerprint = 0
    for i in range(hashbits):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint

def _hamming_similarity(h1: int, h2: int, hashbits: int = 64) -> float:
    return 1.0 - bin(h1 ^ h2).count('1') / hashbits

# ─── SemanticCache → Nexus CAS ───────────────────────────────────────────────
# ponytail: Nexus CAS déduplique automatiquement par content hash.
# SemanticCache garde l'API pour compatibilité mais écrit dans nexus_bridge.

import json
import logging

logger = logging.getLogger(__name__)

class SemanticCache:
    def __init__(self):
        self._mem: dict[str, CacheEntry] = {}

    def compute_signature(self, code: str) -> int:
        return _simhash(_tokenize(code))

    def lookup(self, code: str) -> Optional[CacheEntry]:
        sig = self.compute_signature(code)
        # Recherche dans mémoire locale (Nexus CAS gère la persistance)
        for entry in self._mem.values():
            try:
                if _hamming_similarity(sig, int(entry.signature)) >= SIMILARITY_THRESHOLD:
                    entry.hit_count += 1
                    return entry
            except Exception:
                continue
        return None

    def store(self, code: str, file_path: str, line_range: str,
              result: str, score: float) -> None:
        sig = str(self.compute_signature(code))
        key = f"cache_{sig}"
        entry = CacheEntry(sig, file_path, line_range, result, score, time.time())
        self._mem[key] = entry
        # Persistance via Nexus CAS (async fire-and-forget)
        try:
            from .nexus_bridge import memory_store
            memory_store(key, json.dumps({
                "signature": sig, "file_path": file_path, "line_range": line_range,
                "result": result, "score": score, "timestamp": entry.timestamp,
            }))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def stats(self) -> dict:
        return {"entries": len(self._mem), "total_hits": sum(e.hit_count for e in self._mem.values())}

_CACHE: Optional[SemanticCache] = None

def get_cache() -> SemanticCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = SemanticCache()
    return _CACHE
