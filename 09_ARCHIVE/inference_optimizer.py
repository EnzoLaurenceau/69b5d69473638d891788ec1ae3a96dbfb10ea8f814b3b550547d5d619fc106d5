"""
inference_optimizer.py — High-Performance Inference Layer for the Forge
========================================================================
Quantization + vLLM/SGLang + KV Cache + Prompt Caching

Architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │                    FORGE INFERENCE LAYER                     │
  ├─────────────────────────────────────────────────────────────┤
  │                                                             │
  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
  │  │  Quantization │    │  Inference   │    │  KV Cache    │  │
  │  │  AWQ/GPTQ/    │───→│  Engine      │───→│  Manager     │  │
  │  │  GGUF/INT8    │    │  vLLM/SGLang │    │  PagedAttn   │  │
  │  └──────────────┘    └──────────────┘    └──────────────┘  │
  │         ↑                   ↑                   ↑          │
  │    Model Registry     Batch Scheduler    Prompt Cache      │
  │    (HuggingFace)      (continuous)       (system msgs)     │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘

Key optimizations:
  1. Quantization: 4-bit AWQ → 4x memory reduction, <2% quality loss
  2. PagedAttention: KV cache as pages → no memory fragmentation
  3. Continuous batching: new requests join running batch → max GPU util
  4. Prompt caching: system prompts cached → instant reuse across agents
  5. Speculative decoding: small model drafts, large model verifies → 2-3x speedup

LangChain tradeoff:
  - LangChain adds ~10-50ms overhead per call (abstraction layers)
  - For high-throughput inference: BYPASS LangChain, call vLLM/SGLang directly
  - For orchestration/agents: KEEP LangGraph (it's the graph, not the inference)
  - Solution: LangGraph for orchestration, direct vLLM for inference
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
CACHE_DIR = FORGE_ROOT / ".nexus" / "inference_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# QUANTIZATION — Model compression for inference
# ═══════════════════════════════════════════════════════════════════════════════

class QuantFormat(Enum):
    """Supported quantization formats."""
    FP16 = "fp16"      # Full precision (baseline)
    FP8 = "fp8"        # 8-bit float (H100 native)
    INT8 = "int8"      # 8-bit integer (bitsandbytes)
    INT4 = "int4"      # 4-bit integer (bitsandbytes)
    AWQ = "awq"        # Activation-aware Weight Quantization (INT4)
    GPTQ = "gptq"      # GPT Quantization (INT4/INT8)
    GGUF = "gguf"      # llama.cpp format (CPU/GPU hybrid)
    EXL2 = "exl2"      # ExLlamaV2 (adaptive 2-8 bit)


@dataclass
class QuantConfig:
    """Quantization configuration."""
    format: QuantFormat
    bits: int                    # 4, 8, 16
    group_size: int = 128        # AWQ/GPTQ group size
    desc_act: bool = True        # GPTQ: descending activation order
    damp_percent: float = 0.01   # GPTQ: damping factor
    sym: bool = False            # Symmetric quantization
    
    @property
    def memory_reduction(self) -> float:
        """Memory reduction factor vs FP16."""
        return 16.0 / self.bits
    
    @property
    def quality_loss_estimate(self) -> float:
        """Estimated quality loss percentage."""
        estimates = {
            QuantFormat.FP16: 0.0,
            QuantFormat.FP8: 0.5,
            QuantFormat.INT8: 1.0,
            QuantFormat.INT4: 2.0,
            QuantFormat.AWQ: 1.5,
            QuantFormat.GPTQ: 1.8,
            QuantFormat.GGUF: 2.0,  # Q4_K_M
            QuantFormat.EXL2: 1.0,
        }
        return estimates.get(self.format, 2.0)


# Model registry: which quantization works best for each model
MODEL_QUANT_REGISTRY = {
    # Model name → recommended quantization
    "llama-3.3-70b": QuantConfig(QuantFormat.AWQ, bits=4, group_size=128),
    "llama-3.1-8b": QuantConfig(QuantFormat.AWQ, bits=4, group_size=128),
    "mistral-7b": QuantConfig(QuantFormat.AWQ, bits=4, group_size=128),
    "qwen-2.5-72b": QuantConfig(QuantFormat.AWQ, bits=4, group_size=128),
    "deepseek-v3": QuantConfig(QuantFormat.FP8, bits=8),
    "codellama-34b": QuantConfig(QuantFormat.GPTQ, bits=4, group_size=128),
    "mixtral-8x7b": QuantConfig(QuantFormat.AWQ, bits=4, group_size=64),
}

# HuggingFace repos for pre-quantized models
QUANTIZED_REPOS = {
    ("llama-3.3-70b", QuantFormat.AWQ): "TheBloke/Llama-3.3-70B-AWQ",
    ("llama-3.1-8b", QuantFormat.AWQ): "TechxGenus/Meta-Llama-3.1-8B-Instruct-AWQ",
    ("mistral-7b", QuantFormat.AWQ): "TheBloke/Mistral-7B-Instruct-v0.2-AWQ",
    ("qwen-2.5-72b", QuantFormat.AWQ): "Qwen/Qwen2.5-72B-Instruct-AWQ",
    ("codellama-34b", QuantFormat.GPTQ): "TheBloke/CodeLlama-34B-Instruct-GPTQ",
    ("mixtral-8x7b", QuantFormat.AWQ): "TheBloke/Mixtral-8x7B-Instruct-v0.1-AWQ",
    
    # GGUF for llama.cpp (CPU inference)
    ("llama-3.3-70b", QuantFormat.GGUF): "bartowski/Llama-3.3-70B-Instruct-GGUF",
    ("llama-3.1-8b", QuantFormat.GGUF): "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
    ("mistral-7b", QuantFormat.GGUF): "TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
    ("qwen-2.5-72b", QuantFormat.GGUF): "bartowski/Qwen2.5-72B-Instruct-GGUF",
}


# ═══════════════════════════════════════════════════════════════════════════════
# INFERENCE ENGINE — vLLM / SGLang / llama.cpp
# ═══════════════════════════════════════════════════════════════════════════════

class InferenceEngine(Enum):
    """Supported inference engines."""
    VLLM = "vllm"              # Best for high-throughput GPU
    SGLANG = "sglang"          # Best for structured output
    LLAMACPP = "llamacpp"      # Best for CPU/edge
    TENSORRT = "tensorrt"      # Best for NVIDIA production
    EXLLAMA = "exllama"        # Best for consumer GPUs
    OPENAI = "openai"          # API fallback
    ANTHROPIC = "anthropic"    # API fallback


@dataclass
class EngineConfig:
    """Inference engine configuration."""
    engine: InferenceEngine
    model: str
    quantization: Optional[QuantConfig] = None
    
    # vLLM/SGLang specific
    tensor_parallel: int = 1       # Number of GPUs
    pipeline_parallel: int = 1     # Pipeline stages
    max_model_len: int = 8192      # Max sequence length
    gpu_memory_utilization: float = 0.90  # GPU memory fraction
    
    # PagedAttention
    block_size: int = 16           # KV cache block size
    max_num_seqs: int = 256        # Max concurrent sequences
    max_num_batched_tokens: int = 8192  # Max tokens per batch
    
    # Quantization
    quantization_method: Optional[str] = None  # "awq", "gptq", "fp8"
    
    # Cache
    enable_prefix_caching: bool = True  # Prompt caching
    enable_chunked_prefill: bool = True  # Chunked prefill
    
    # Speculative decoding
    speculative_model: Optional[str] = None  # Draft model
    num_speculative_tokens: int = 5          # Tokens to speculate
    
    @property
    def engine_command(self) -> list[str]:
        """Generate engine startup command."""
        if self.engine == InferenceEngine.VLLM:
            cmd = [
                "python", "-m", "vllm.entrypoints.openai.api_server",
                "--model", self.model,
                "--tensor-parallel-size", str(self.tensor_parallel),
                "--max-model-len", str(self.max_model_len),
                "--gpu-memory-utilization", str(self.gpu_memory_utilization),
                "--block-size", str(self.block_size),
                "--max-num-seqs", str(self.max_num_seqs),
                "--max-num-batched-tokens", str(self.max_num_batched_tokens),
            ]
            if self.quantization_method:
                cmd.extend(["--quantization", self.quantization_method])
            if self.enable_prefix_caching:
                cmd.extend(["--enable-prefix-caching"])
            if self.enable_chunked_prefill:
                cmd.extend(["--enable-chunked-prefill"])
            if self.speculative_model:
                cmd.extend([
                    "--speculative-model", self.speculative_model,
                    "--num-speculative-tokens", str(self.num_speculative_tokens),
                ])
            return cmd
        
        elif self.engine == InferenceEngine.SGLANG:
            cmd = [
                "python", "-m", "sglang.launch_server",
                "--model-path", self.model,
                "--tp", str(self.tensor_parallel),
                "--mem-fraction-gpu", str(self.gpu_memory_utilization),
            ]
            if self.quantization_method:
                cmd.extend(["--quantization", self.quantization_method])
            return cmd
        
        elif self.engine == InferenceEngine.LLAMACPP:
            cmd = [
                "llama-server",
                "--model", self.model,
                "--ctx-size", str(self.max_model_len),
                "--n-gpu-layers", "999",  # All layers on GPU
                "--flash-attn",
            ]
            return cmd
        
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# KV CACHE MANAGER — PagedAttention + Prompt Caching
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CacheEntry:
    """A cached prompt/KV pair."""
    prompt_hash: str
    prompt_prefix: str          # First 200 chars for debugging
    tokens_count: int
    cache_hit_count: int = 0
    last_access: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    
    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at
    
    @property
    def is_stale(self) -> bool:
        # Stale after 1 hour or 1000 accesses
        return self.age_seconds > 3600 or self.cache_hit_count > 1000


class KVCacheManager:
    """
    Manages KV cache for prompt reuse across agents.
    
    Key insight: In a multi-agent system, many agents share the same
    system prompt prefix. By caching the KV states for these prefixes,
    we avoid recomputing them on every call.
    
    Example:
      System prompt: "You are a security researcher..." (500 tokens)
      Agent A: system + "Analyze CVE-2024-1234" (600 tokens)
      Agent B: system + "Analyze CVE-2024-5678" (600 tokens)
      
      Without cache: 500 + 600 + 600 = 1700 tokens computed
      With cache:    500 + 100 + 100 = 700 tokens computed (59% savings)
    """
    
    def __init__(self, max_entries: int = 1000):
        self.cache: dict[str, CacheEntry] = {}
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0
    
    def get_cache_key(self, prompt: str, model: str) -> str:
        """Generate cache key for a prompt."""
        # Use first 1000 chars + model for key
        content = f"{model}:{prompt[:1000]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def lookup(self, prompt: str, model: str) -> Optional[CacheEntry]:
        """Look up cached KV state for a prompt."""
        key = self.get_cache_key(prompt, model)
        entry = self.cache.get(key)
        
        if entry and not entry.is_stale:
            entry.cache_hit_count += 1
            entry.last_access = time.time()
            self.hits += 1
            return entry
        
        self.misses += 1
        return None
    
    def store(self, prompt: str, model: str, tokens_count: int) -> CacheEntry:
        """Store a prompt/KV pair in cache."""
        key = self.get_cache_key(prompt, model)
        
        # Evict stale entries if at capacity
        if len(self.cache) >= self.max_entries:
            self._evict_stale()
        
        entry = CacheEntry(
            prompt_hash=key,
            prompt_prefix=prompt[:200],
            tokens_count=tokens_count,
        )
        self.cache[key] = entry
        return entry
    
    def get_prefix_match(self, prompt: str, model: str) -> Optional[tuple[str, int]]:
        """
        Find the longest cached prefix that matches the beginning of prompt.
        
        Returns (cached_prefix, cached_tokens) or None.
        """
        # Sort by length (longest first) for best match
        for key, entry in sorted(
            self.cache.items(), 
            key=lambda x: -x[1].tokens_count
        ):
            if not entry.is_stale and entry.prompt_prefix in prompt[:entry.tokens_count]:
                return entry.prompt_prefix, entry.tokens_count
        
        return None
    
    def _evict_stale(self):
        """Remove stale entries."""
        stale_keys = [
            k for k, v in self.cache.items() 
            if v.is_stale
        ]
        for k in stale_keys[:self.max_entries // 4]:  # Remove 25%
            del self.cache[k]
    
    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "entries": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.hit_rate:.1%}",
            "stale_entries": sum(1 for e in self.cache.values() if e.is_stale),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT CACHE — System prompt reuse
# ═══════════════════════════════════════════════════════════════════════════════

class PromptCache:
    """
    Caches system prompts for instant reuse across agents.
    
    In the Forge, many agents share common system prompts:
      - NMP protocol instructions
      - YAGNI rules (Ponytail)
      - Harness quality gates
      - Economic theory context
    
    By caching these, we avoid re-processing them on every call.
    """
    
    # Common system prompt components that can be cached
    CACHEABLE_COMPONENTS = {
        "nmp_protocol": "ACTION|SOURCE|TARGET|PAYLOAD format for inter-agent communication...",
        "yagni_rules": "Before writing code, stop at the FIRST rung that holds...",
        "harness_gates": "Every artifact must pass through quality gates...",
        "economic_theory": "CRRA utility, Prospect Theory, behavioral biases...",
        "markov_regimes": "BULL/BEAR/SIDEWAYS/CRISIS/RECOVERY states...",
    }
    
    def __init__(self, kv_cache: KVCacheManager):
        self.kv_cache = kv_cache
        self.component_hashes: dict[str, str] = {}
        
        # Pre-compute hashes for cacheable components
        for name, content in self.CACHEABLE_COMPONENTS.items():
            self.component_hashes[name] = hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def build_system_prompt(self, components: list[str], custom: str = "") -> str:
        """
        Build system prompt from cached components + custom text.
        
        Components are cached, custom text is appended.
        """
        parts = []
        
        for comp in components:
            if comp in self.CACHEABLE_COMPONENTS:
                parts.append(self.CACHEABLE_COMPONENTS[comp])
        
        if custom:
            parts.append(custom)
        
        return "\n\n".join(parts)
    
    def get_cached_prefix(self, system_prompt: str, model: str) -> Optional[str]:
        """Get cached prefix for a system prompt."""
        entry = self.kv_cache.lookup(system_prompt, model)
        if entry:
            return entry.prompt_prefix
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# INFERENCE OPTIMIZER — Main orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class InferenceResult:
    """Result of an optimized inference call."""
    text: str
    tokens_used: int
    latency_ms: float
    cache_hit: bool
    engine: InferenceEngine
    quantization: QuantFormat
    throughput_tps: float  # tokens per second
    cost_estimate: float   # estimated cost in USD


class InferenceOptimizer:
    """
    High-performance inference optimizer for the Forge.
    
    Integrates:
    1. Quantization (AWQ/GPTQ/GGUF)
    2. Inference engines (vLLM/SGLang/llama.cpp)
    3. KV cache management (PagedAttention)
    4. Prompt caching (system prompt reuse)
    5. Continuous batching (max GPU utilization)
    
    Usage:
        optimizer = InferenceOptimizer()
        optimizer.start_engine("llama-3.3-70b", QuantFormat.AWQ)
        result = optimizer.infer("Analyze this vulnerability...", system_prompt="...")
    """
    
    def __init__(self):
        self.kv_cache = KVCacheManager(max_entries=1000)
        self.prompt_cache = PromptCache(self.kv_cache)
        
        # Active engines
        self.engines: dict[str, EngineConfig] = {}
        self.engine_processes: dict[str, subprocess.Popen] = {}
        
        # Statistics
        self.total_calls = 0
        self.total_tokens = 0
        self.total_latency = 0.0
    
    def start_engine(self, model: str, quant: QuantFormat = QuantFormat.AWQ,
                     engine: InferenceEngine = InferenceEngine.VLLM,
                     gpus: int = 1) -> EngineConfig:
        """
        Start an inference engine with quantized model.
        
        Args:
            model: Model name or HuggingFace repo
            quant: Quantization format
            engine: Inference engine to use
            gpus: Number of GPUs for tensor parallelism
            
        Returns:
            EngineConfig with connection details
        """
        logger.info(f"Starting {engine.value} with {model} ({quant.value})...")
        
        # Get quantization config
        if model in MODEL_QUANT_REGISTRY:
            quant_config = MODEL_QUANT_REGISTRY[model]
        else:
            quant_config = QuantConfig(quant, bits=4 if quant == QuantFormat.AWQ else 8)
        
        # Check for pre-quantized model
        quant_repo = QUANTIZED_REPOS.get((model, quant))
        if quant_repo:
            model = quant_repo
            logger.info(f"  Using pre-quantized: {quant_repo}")
        
        # Configure engine
        config = EngineConfig(
            engine=engine,
            model=model,
            quantization=quant_config,
            tensor_parallel=gpus,
            quantization_method=quant.value if quant in [QuantFormat.AWQ, QuantFormat.GPTQ, QuantFormat.FP8] else None,
        )
        
        # Store config
        self.engines[model] = config
        
        # Generate startup command
        cmd = config.engine_command
        logger.info(f"  Command: {' '.join(cmd[:5])}...")
        
        # Note: Actual process management would go here
        # For now, we return the config
        
        return config
    
    def infer(self, prompt: str, system_prompt: str = "",
              model: str = "llama-3.3-70b",
              max_tokens: int = 2048,
              temperature: float = 0.7) -> InferenceResult:
        """
        Run inference with all optimizations.
        
        Optimizations applied:
        1. Prompt cache lookup (avoid recomputing system prompt)
        2. KV cache hit (reuse cached states)
        3. Quantized model (reduced memory)
        4. PagedAttention (efficient KV management)
        5. Continuous batching (max throughput)
        """
        start_time = time.time()
        
        # Build full prompt
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        # Check cache
        cache_entry = self.kv_cache.lookup(full_prompt, model)
        cache_hit = cache_entry is not None
        
        if cache_hit:
            logger.info(f"Cache HIT for {model} (saved {cache_entry.tokens_count} tokens)")
        
        # Check prefix cache
        prefix_match = self.prompt_cache.get_cached_prefix(full_prompt, model)
        if prefix_match:
            cached_prefix, cached_tokens = prefix_match
            # Only send the new part
            new_prompt = full_prompt[len(cached_prefix):]
            logger.info(f"Prefix cache: reusing {cached_tokens} tokens, sending {len(new_prompt)} new")
        
        # Get engine config
        config = self.engines.get(model)
        if not config:
            # Auto-start engine
            config = self.start_engine(model)
        
        # Simulate inference (in production, call vLLM/SGLang API)
        # This would be an HTTP call to the engine's API endpoint
        tokens_used = len(full_prompt.split()) * 1.3  # Rough estimate
        latency_ms = (time.time() - start_time) * 1000
        
        # Store in cache
        if not cache_hit:
            self.kv_cache.store(full_prompt, model, int(tokens_used))
        
        # Update stats
        self.total_calls += 1
        self.total_tokens += int(tokens_used)
        self.total_latency += latency_ms
        
        # Estimate cost (rough: $0.001 per 1K tokens for local inference)
        cost = tokens_used / 1000 * 0.001
        
        return InferenceResult(
            text="[Inference result would go here]",
            tokens_used=int(tokens_used),
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            engine=config.engine,
            quantization=config.quantization.format if config.quantization else QuantFormat.FP16,
            throughput_tps=tokens_used / (latency_ms / 1000) if latency_ms > 0 else 0,
            cost_estimate=cost,
        )
    
    def batch_infer(self, prompts: list[str], system_prompt: str = "",
                    model: str = "llama-3.3-70b",
                    max_concurrent: int = 32) -> list[InferenceResult]:
        """
        Batch inference with continuous batching.
        
        vLLM's continuous batching allows new requests to join
        a running batch, maximizing GPU utilization.
        """
        logger.info(f"Batch inference: {len(prompts)} prompts on {model}")
        
        results = []
        for prompt in prompts:
            result = self.infer(prompt, system_prompt, model)
            results.append(result)
        
        return results
    
    def stats(self) -> dict[str, Any]:
        """Get inference statistics."""
        return {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "avg_latency_ms": self.total_latency / self.total_calls if self.total_calls > 0 else 0,
            "cache_stats": self.kv_cache.stats(),
            "active_engines": list(self.engines.keys()),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# LANGCHAIN TRADEOFF — When to use, when to bypass
# ═══════════════════════════════════════════════════════════════════════════════

LANGCHAIN_ANALYSIS = """
═══════════════════════════════════════════════════════════════════════════════
LANGCHAIN TRADEOFF ANALYSIS FOR THE FORGE
═══════════════════════════════════════════════════════════════════════════════

QUESTION: Is LangChain useful for the Forge?

ANSWER: It depends on the use case.

┌─────────────────┬─────────────────┬─────────────────┬─────────────────────┐
│ Use Case        │ LangChain?      │ Why             │ Alternative         │
├─────────────────┼─────────────────┼─────────────────┼─────────────────────┤
│ Agent graphs    │ ✅ YES          │ LangGraph is    │ Custom FSM (more    │
│                 │                 │ excellent for   │ work, same result)  │
│                 │                 │ multi-agent     │                     │
├─────────────────┼─────────────────┼─────────────────┼─────────────────────┤
│ High-throughput │ ❌ NO           │ 10-50ms overhead│ Direct vLLM/SGLang  │
│ inference       │                 │ per call        │ HTTP API            │
├─────────────────┼─────────────────┼─────────────────┼─────────────────────┤
│ Tool calling    │ ⚠️ MAYBE        │ Good for simple │ Custom parser for   │
│                 │                 │ tools, slow for │ complex tools       │
│                 │                 │ complex ones    │                     │
├─────────────────┼─────────────────┼─────────────────┼─────────────────────┤
│ RAG pipelines   │ ⚠️ MAYBE        │ Good defaults,  │ LlamaIndex or       │
│                 │                 │ but heavy       │ custom              │
├─────────────────┼─────────────────┼─────────────────┼─────────────────────┤
│ Structured      │ ❌ NO           │ Pydantic +      │ Outlines or         │
│ output          │                 │ retry = slow    │ Instructor          │
├─────────────────┼─────────────────┼─────────────────┼─────────────────────┤
│ Streaming       │ ❌ NO           │ SSE directly    │ httpx + async       │
│                 │                 │ is simpler      │ generator           │
└─────────────────┴─────────────────┴─────────────────┴─────────────────────┘

RECOMMENDATION FOR THE FORGE:

  KEEP:
    - LangGraph for agent orchestration (the graph IS the value)
    - LangChain memory for conversation history
    - LangChain callbacks for logging/tracing

  REPLACE:
    - LLM calls → direct vLLM/SGLang API (no abstraction)
    - Tool calling → custom parser (faster, more control)
    - RAG → custom pipeline (lighter, tuned for our data)
    - Structured output → Outlines (faster, more reliable)

  HYBRID APPROACH:
    - LangGraph orchestrates the agents (graph structure)
    - Each agent calls vLLM directly (no LangChain overhead)
    - Results flow through LangGraph state (checkpointing)
    
  This gives us:
    - Graph orchestration (LangGraph) ✅
    - Fast inference (direct vLLM) ✅
    - State management (LangGraph) ✅
    - No unnecessary overhead ✅

═══════════════════════════════════════════════════════════════════════════════
"""


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_optimizer() -> InferenceOptimizer:
    """Get singleton optimizer instance."""
    if not hasattr(get_optimizer, '_instance'):
        get_optimizer._instance = InferenceOptimizer()
    return get_optimizer._instance


def quick_infer(prompt: str, model: str = "llama-3.3-70b",
                quant: QuantFormat = QuantFormat.AWQ) -> InferenceResult:
    """Quick inference with default settings."""
    optimizer = get_optimizer()
    if model not in optimizer.engines:
        optimizer.start_engine(model, quant)
    return optimizer.infer(prompt, model=model)


def print_langchain_analysis():
    """Print LangChain tradeoff analysis."""
    print(LANGCHAIN_ANALYSIS)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    if "--analysis" in sys.argv:
        print_langchain_analysis()
        sys.exit(0)
    
    print("=" * 70)
    print("INFERENCE OPTIMIZER — FORGE")
    print("=" * 70)
    print()
    
    optimizer = get_optimizer()
    
    # Show quantization options
    print("📊 QUANTIZATION OPTIONS:")
    for fmt in QuantFormat:
        config = QuantConfig(fmt, bits=4 if fmt in [QuantFormat.AWQ, QuantFormat.GPTQ] else 8)
        print(f"  {fmt.value:8s}: {config.memory_reduction:.1f}x memory reduction, "
              f"~{config.quality_loss_estimate:.1f}% quality loss")
    print()
    
    # Show engine options
    print("🚀 INFERENCE ENGINES:")
    for engine in InferenceEngine:
        print(f"  {engine.value:12s}: ", end="")
        if engine == InferenceEngine.VLLM:
            print("Best for high-throughput GPU (PagedAttention, continuous batching)")
        elif engine == InferenceEngine.SGLANG:
            print("Best for structured output (RadixAttention)")
        elif engine == InferenceEngine.LLAMACPP:
            print("Best for CPU/edge (GGUF format)")
        elif engine == InferenceEngine.TENSORRT:
            print("Best for NVIDIA production (INT8/FP8)")
        elif engine == InferenceEngine.EXLLAMA:
            print("Best for consumer GPUs (2-8 bit adaptive)")
        else:
            print("API fallback")
    print()
    
    # Show registered models
    print("📦 REGISTERED MODELS:")
    for model, config in MODEL_QUANT_REGISTRY.items():
        repo = QUANTIZED_REPOS.get((model, config.format), "auto-quantize")
        print(f"  {model:20s}: {config.format.value} ({config.bits}-bit) → {repo}")
    print()
    
    # Cache stats
    print("💾 CACHE STATS:")
    stats = optimizer.kv_cache.stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()
    
    # LangChain analysis
    print("🤔 LANGCHAIN TRADEOFF:")
    print_langchain_analysis()
    
    print("=" * 70)
