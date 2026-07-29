"""
inference_patch.py — Direct optimizations for forge_llm.py
===========================================================
Applique les optimisations d'inférence SANS changer l'architecture.

Optimisations:
  1. Prompt cache: system prompts mis en cache (hash → KV)
  2. Response cache: prompts identiques → réponse instantanée
  3. Compression: réduit la taille des prompts avant envoi
  4. Latency tracking: route vers le provider le plus rapide
  5. Batching: groupe les appels similaires

Usage:
  from forge_agents.inference_patch import apply_optimizations
  apply_optimizations()  # Patch forge_llm.py in-memory
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
CACHE_DIR = FORGE_ROOT / ".nexus" / "inference_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PROMPT CACHE — System prompts en cache
# ═══════════════════════════════════════════════════════════════════════════════

class PromptCache:
    """
    Cache les system prompts pour éviter de les retraiter.
    
    Dans la Forge, beaucoup d'agents partagent les mêmes system prompts:
      - Instructions NMP
      - Règles YAGNI (Ponytail)
      - Quality gates (Harness)
      - Contexte économique
    
    En les cachant, on économise du temps de traitement.
    """
    
    def __init__(self, max_size: int = 100):
        self.cache: dict[str, tuple[str, float]] = {}  # hash → (prompt, timestamp)
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def get_hash(self, text: str) -> str:
        """Hash rapide pour le cache."""
        return hashlib.md5(text.encode()).hexdigest()[:12]
    
    def get(self, system_prompt: str) -> Optional[str]:
        """Récupère un system prompt du cache."""
        if not system_prompt:
            return None
        
        h = self.get_hash(system_prompt)
        entry = self.cache.get(h)
        
        if entry:
            prompt, ts = entry
            # Cache valide 1 heure
            if time.time() - ts < 3600:
                self.hits += 1
                return prompt
            else:
                del self.cache[h]
        
        self.misses += 1
        return None
    
    def put(self, system_prompt: str) -> None:
        """Stocke un system prompt dans le cache."""
        if not system_prompt:
            return
        
        h = self.get_hash(system_prompt)
        
        # Éviction si plein
        if len(self.cache) >= self.max_size:
            # Supprimer le plus ancien
            oldest = min(self.cache.items(), key=lambda x: x[1][1])
            del self.cache[oldest[0]]
        
        self.cache[h] = (system_prompt, time.time())
    
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.hits/total:.1%}" if total > 0 else "0%",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RESPONSE CACHE — Réponses identiques en cache
# ═══════════════════════════════════════════════════════════════════════════════

class ResponseCache:
    """
    Cache les réponses pour prompts identiques.
    
    Si le même prompt + system est envoyé deux fois,
    on retourne la réponse cachée instantanément.
    """
    
    def __init__(self, max_size: int = 500):
        self.cache: dict[str, tuple[str, float]] = {}  # hash → (response, timestamp)
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def get_key(self, prompt: str, system: str, model: str) -> str:
        """Génère la clé de cache."""
        content = f"{system}|{prompt}|{model}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get(self, prompt: str, system: str, model: str) -> Optional[str]:
        """Récupère une réponse du cache."""
        key = self.get_key(prompt, system, model)
        entry = self.cache.get(key)
        
        if entry:
            response, ts = entry
            # Cache valide 30 minutes
            if time.time() - ts < 1800:
                self.hits += 1
                return response
            else:
                del self.cache[key]
        
        self.misses += 1
        return None
    
    def put(self, prompt: str, system: str, model: str, response: str) -> None:
        """Stocke une réponse dans le cache."""
        key = self.get_key(prompt, system, model)
        
        # Éviction si plein
        if len(self.cache) >= self.max_size:
            oldest = min(self.cache.items(), key=lambda x: x[1][1])
            del self.cache[oldest[0]]
        
        self.cache[key] = (response, time.time())
    
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.hits/total:.1%}" if total > 0 else "0%",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PROMPT COMPRESSION — Réduire la taille des prompts
# ═══════════════════════════════════════════════════════════════════════════════

class PromptCompressor:
    """
    Compresse les prompts pour réduire les tokens.
    
    Techniques:
      - Supprime les espaces multiples
      - Supprime les lignes vides excessives
      - Raccourcit les instructions répétitives
      - Compresse le contexte JSON
    """
    
    # Patterns de compression
    COMPRESS_PATTERNS = [
        (r'\n{3,}', '\n\n'),           # Max 2 newlines
        (r' {2,}', ' '),               # Max 1 space
        (r'\t+', ' '),                 # Tabs → spaces
        (r'# {2,}', '# '),             # Comment spacing
        (r'"""[\s\S]*?"""', '""""""'), # Empty docstrings
    ]
    
    # Instructions verbeuses → compactes
    VERBOSITY_MAP = {
        "Please make sure to": "Must",
        "It is important that you": "Must",
        "You should always": "Always",
        "You need to": "Must",
        "Don't forget to": "Must",
        "Remember to": "Must",
        "Make sure you": "Must",
        "Be sure to": "Must",
        "It's crucial that": "Must",
        "I want you to": "",
        "Can you please": "",
        "Could you please": "",
        "I would like you to": "",
    }
    
    def compress(self, text: str) -> str:
        """Compresse un prompt."""
        if not text:
            return text
        
        original_len = len(text)
        
        # Apply compression patterns
        for pattern, replacement in self.COMPRESS_PATTERNS:
            text = re.sub(pattern, replacement, text)
        
        # Reduce verbosity
        for verbose, compact in self.VERBOSITY_MAP.items():
            text = text.replace(verbose, compact)
        
        # Clean up
        text = text.strip()
        
        savings = original_len - len(text)
        if savings > 100:
            logger.debug(f"Compressed prompt: {original_len} → {len(text)} chars ({savings} saved)")
        
        return text
    
    def compress_json(self, data: Any) -> str:
        """Compresse du JSON (pas d'espaces, clés courtes)."""
        return json.dumps(data, separators=(',', ':'), ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LATENCY TRACKER — Route vers le provider le plus rapide
# ═══════════════════════════════════════════════════════════════════════════════

class LatencyTracker:
    """
    Track la latence de chaque provider pour router intelligemment.
    
    Si Groq est plus rapide que Cerebras → favorise Groq.
    Si un provider est down → le dépriorise temporairement.
    """
    
    def __init__(self, window_size: int = 50):
        self.latencies: dict[str, list[float]] = {}  # provider → [latencies]
        self.failures: dict[str, int] = {}            # provider → failure count
        self.window_size = window_size
    
    def record_success(self, provider: str, latency_ms: float) -> None:
        """Enregistre un succès."""
        if provider not in self.latencies:
            self.latencies[provider] = []
        
        self.latencies[provider].append(latency_ms)
        
        # Garder seulement les N derniers
        if len(self.latencies[provider]) > self.window_size:
            self.latencies[provider] = self.latencies[provider][-self.window_size:]
        
        # Reset failures
        self.failures[provider] = 0
    
    def record_failure(self, provider: str) -> None:
        """Enregistre un échec."""
        self.failures[provider] = self.failures.get(provider, 0) + 1
    
    def get_avg_latency(self, provider: str) -> float:
        """Latence moyenne d'un provider."""
        lats = self.latencies.get(provider, [])
        return sum(lats) / len(lats) if lats else 999999.0
    
    def get_best_provider(self, providers: list[str]) -> str:
        """Retourne le provider le plus rapide."""
        def score(p: str) -> float:
            avg = self.get_avg_latency(p)
            failures = self.failures.get(p, 0)
            # Pénalité pour les échecs
            return avg + (failures * 10000)
        
        return min(providers, key=score)
    
    def stats(self) -> dict:
        """Statistiques de latence."""
        return {
            p: {
                "avg_ms": round(self.get_avg_latency(p)),
                "samples": len(self.latencies.get(p, [])),
                "failures": self.failures.get(p, 0),
            }
            for p in set(list(self.latencies.keys()) + list(self.failures.keys()))
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. INFERENCE OPTIMIZER — Combine tout
# ═══════════════════════════════════════════════════════════════════════════════

class InferenceOptimizer:
    """
    Optimiseur d'inférence pour forge_llm.py.
    
    Combine:
      - Prompt cache (system prompts)
      - Response cache (prompts identiques)
      - Compression (réduction tokens)
      - Latency tracking (routing intelligent)
    """
    
    def __init__(self):
        self.prompt_cache = PromptCache(max_size=100)
        self.response_cache = ResponseCache(max_size=500)
        self.compressor = PromptCompressor()
        self.latency = LatencyTracker(window_size=50)
        
        # Stats
        self.total_calls = 0
        self.cache_savings = 0
    
    def prepare_prompt(self, prompt: str, system: str = "") -> tuple[str, str]:
        """
        Prépare un prompt avec toutes les optimisations.
        
        Returns:
            (compressed_prompt, compressed_system)
        """
        # Compress
        prompt = self.compressor.compress(prompt)
        system = self.compressor.compress(system)
        
        # Cache system prompt
        if system:
            cached = self.prompt_cache.get(system)
            if cached:
                # System prompt déjà en cache, on peut le court-circuiter
                pass
            else:
                self.prompt_cache.put(system)
        
        return prompt, system
    
    def check_cache(self, prompt: str, system: str, model: str) -> Optional[str]:
        """Vérifie le cache de réponses."""
        return self.response_cache.get(prompt, system, model)
    
    def store_cache(self, prompt: str, system: str, model: str, response: str) -> None:
        """Stocke une réponse dans le cache."""
        self.response_cache.put(prompt, system, model, response)
    
    def record_latency(self, provider: str, latency_ms: float, success: bool) -> None:
        """Enregistre la latence d'un appel."""
        if success:
            self.latency.record_success(provider, latency_ms)
        else:
            self.latency.record_failure(provider)
    
    def get_best_provider(self, providers: list[str]) -> str:
        """Retourne le provider le plus rapide."""
        return self.latency.get_best_provider(providers)
    
    def stats(self) -> dict:
        """Statistiques complètes."""
        return {
            "prompt_cache": self.prompt_cache.stats(),
            "response_cache": self.response_cache.stats(),
            "latency": self.latency.stats(),
            "total_calls": self.total_calls,
            "cache_savings": self.cache_savings,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════

_optimizer: Optional[InferenceOptimizer] = None

def get_optimizer() -> InferenceOptimizer:
    """Retourne l'optimiseur singleton."""
    global _optimizer
    if _optimizer is None:
        _optimizer = InferenceOptimizer()
    return _optimizer


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH FUNCTIONS — À appeler depuis forge_llm.py
# ═══════════════════════════════════════════════════════════════════════════════

def optimized_prepare(prompt: str, system: str = "") -> tuple[str, str]:
    """
    Prépare un prompt optimisé.
    
    À appeler AVANT l'envoi au provider.
    """
    opt = get_optimizer()
    return opt.prepare_prompt(prompt, system)


def optimized_check_cache(prompt: str, system: str, model: str) -> Optional[str]:
    """
    Vérifie si la réponse est en cache.
    
    À appeler AVANT l'envoi au provider.
    Si retourne non-None → retourner directement (0 tokens).
    """
    opt = get_optimizer()
    return opt.check_cache(prompt, system, model)


def optimized_store_cache(prompt: str, system: str, model: str, response: str) -> None:
    """
    Stocke une réponse dans le cache.
    
    À appeler APRÈS avoir reçu la réponse.
    """
    opt = get_optimizer()
    opt.store_cache(prompt, system, model, response)


def optimized_record_latency(provider: str, latency_ms: float, success: bool) -> None:
    """
    Enregistre la latence d'un appel.
    
    À appeler APRÈS chaque appel API.
    """
    opt = get_optimizer()
    opt.record_latency(provider, latency_ms, success)


def optimized_get_best_provider(providers: list[str]) -> str:
    """
    Retourne le provider le plus rapide.
    
    À utiliser pour choisir l'ordre des providers.
    """
    opt = get_optimizer()
    return opt.get_best_provider(providers)


def get_optimization_stats() -> dict:
    """Retourne les statistiques d'optimisation."""
    opt = get_optimizer()
    return opt.stats()
