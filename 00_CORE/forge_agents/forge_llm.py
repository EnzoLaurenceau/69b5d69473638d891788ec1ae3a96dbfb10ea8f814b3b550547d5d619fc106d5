"""
forge_llm.py — LLM Router unifié (Forge + OpenCLI Antigravity)
==============================================================
Moteur : Claude via CLI abonnement (claude -p), fallback MiMo (payant).
Plus de tier gratuit : ds2api et Groq retirés (décisions 5+6, 2026-07-25).
MiMo est la seule soupape restante — facturée par bloc de 1000, sous garde-fou budget.

Hiérarchie de coût :

  TIER 1 — Claude Haiku 4.5   (tâches légères : score, extract, classify...)
  TIER 2 — Claude Sonnet 4.5  (research, build, close)
  TIER 3 — Claude Opus 4.6 + extended thinking (orchestration, audit, critique)

Le routeur intègre automatiquement :
  • token_tracker.py  → log coût/latence à chaque appel
  • OpenViking        → contexte mémoire injecté dans le prompt si disponible

Usage:
  from forge_agents.forge_llm import forge_call, forge_score, LLMTier
OptiForge v2 — Stateless one-shot, 50K ceiling, semantic cache, nano-machine.

Changements vs v1:
  - TOKEN_CEILING = 50 000 tokens max par prompt (hard block)
  - SUBTASK_BUDGET = 5 000 tokens max par sous-tâche (soft warn)
  - Semantic cache : si code pattern >95% similaire déjà audité → cache hit, 0 tokens
  - State offloading : chaque réponse sauvegardée dans .nexus/agent_state.json
  - Flush mémoire : variables locales vidées après chaque appel stateless
  result = forge_call("...", tier=LLMTier.HAIKU, task_type="coding_only")
  score  = forge_score("output", "critères")
"""

from __future__ import annotations
import os, json, time, re, logging
import hashlib
import threading
from enum import Enum
from pathlib import Path
from typing import Optional

# ─── Inference optimizations ─────────────────────────────────────────────────
try:
    from .inference_patch import (
        optimized_prepare, optimized_check_cache, optimized_store_cache,
        optimized_record_latency, optimized_get_best_provider,
        get_optimization_stats,
    )
    _INFERENCE_OPTIMIZED = True
except ImportError:
    _INFERENCE_OPTIMIZED = False

# ─── Jailbreak module (L1B3RT4S + G0DM0D3) ──────────────────────────────────
_JAILBREAK_AVAILABLE = False
try:
    import sys as _sys
    _jb_path = Path(__file__).parent.parent / "forge_jailbreak"
    if _jb_path.exists():
        _sys.path.insert(0, str(_jb_path.parent))
        from forge_jailbreak.forge_jailbreak import (
            JAILBREAK_SYSTEM_PROMPT as _JB_SYSTEM,
            HERMES_JAILBREAK_PROMPT as _JB_HERMES,
            LIBERATION_COMMANDS as _JB_COMMANDS,
            parseltongue as _parseltongue_fn,
            stm_pipeline as _stm_fn,
            build_jailbreak_messages as _build_jb_msgs,
            GODMODE_COMBOS as _GODMODE_COMBOS,
        )
        _JAILBREAK_AVAILABLE = True
        _sys.path.pop(0)
except Exception as exc:
    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

logger = logging.getLogger("ForgeLLM")

# ─── Config paths ─────────────────────────────────────────────────────────────
FORGE_ROOT     = Path(__file__).parent.parent.parent

# ─── OptiForge constants (stateless one-shot, ceiling, semantic cache) ───────
TOKEN_CEILING   = 65_000   # hard max tokens par prompt — ceiling Mimo/Hermes (round-trip billing)
SUBTASK_BUDGET  = 5_000    # soft max tokens par sous-tâche
NEXUS_STATE_FILE = FORGE_ROOT / ".nexus" / "agent_state.json"

# ─── Tiers ───────────────────────────────────────────────────────────────────
class LLMTier(str, Enum):
    HAIKU  = "haiku"
    SONNET = "sonnet"
    OPUS   = "opus"

# ─── Task → Tier mapping ─────────────────────────────────────────────────────
TASK_TIER_MAP: dict[str, LLMTier] = {
    # Haiku — tâches légères (score, extraction, format...) + génération contenu
    "score": LLMTier.HAIKU, "summarize": LLMTier.HAIKU, "format": LLMTier.HAIKU,
    "extract": LLMTier.HAIKU, "classify": LLMTier.HAIKU, "translate": LLMTier.HAIKU,
    "rewrite": LLMTier.HAIKU, "template": LLMTier.HAIKU,
    "coding_only": LLMTier.HAIKU, "fast_extraction": LLMTier.HAIKU,
    "write_email": LLMTier.HAIKU, "write_post": LLMTier.HAIKU,
    "write_caption": LLMTier.HAIKU, "generate": LLMTier.HAIKU,
    "jury": LLMTier.HAIKU,  # jury MiroFish
    # Sonnet
    "market_scan": LLMTier.SONNET, "research": LLMTier.SONNET,
    "build": LLMTier.SONNET, "close": LLMTier.SONNET, "hunt": LLMTier.SONNET,
    "massive_context": LLMTier.SONNET, "general_purpose": LLMTier.SONNET,
    # Opus 4.8 — raisonnement lourd UNIQUEMENT (plan d'implémentation, orchestration, critique, audit)
    "orchestrate": LLMTier.OPUS, "critique": LLMTier.OPUS,
    "audit": LLMTier.OPUS, "plan": LLMTier.OPUS, "implementation_plan": LLMTier.OPUS,
}

def tier_for_task(task_type: str) -> LLMTier:
    return TASK_TIER_MAP.get(task_type.lower(), LLMTier.SONNET)

# ─── Anthropic model IDs (right-sized — "pile poil sa tâche, rien d'overkill") ─
# MAJ 2026-06-16 : IDs Claude courants. Opus 4.8 réservé au raisonnement lourd.
ANTHROPIC_MODELS = {
    LLMTier.HAIKU:  "claude-haiku-4-5",    # extraction / format / score / classify
    LLMTier.SONNET: "claude-sonnet-4-6",   # build / codegen / research / général
    LLMTier.OPUS:   "claude-opus-4-8",     # plan d'implémentation / orchestration / audit
}
# Thinking : Opus 4.8 / Sonnet 4.6 = ADAPTATIF uniquement (budget_tokens → 400).
# Haiku 4.5 = pas de thinking, pas d'effort. Cf. skill claude-api.
THINKING_MODE = {
    LLMTier.HAIKU:  None,                 # pas de thinking
    LLMTier.SONNET: None,                 # workhorse lean (thinking omis = off)
    LLMTier.OPUS:   {"type": "adaptive"}, # plan → réflexion adaptative
}
OPUS_EFFORT = "high"  # output_config.effort pour les plans (jamais budget_tokens)

# ─── Politique de routage Claude RÉEL (couche cerveau, hors cascade gratuite) ──
# "pile assez" : chaque task_type → le plus PETIT modèle Claude qui suffit.
# Opus 4.8 = UNIQUEMENT le plan d'implémentation complet + raisonnement lourd.
CLAUDE_TASK_MODEL: dict[str, str] = {
    # Opus 4.8 — raisonnement lourd uniquement
    "plan": "claude-opus-4-8", "implementation_plan": "claude-opus-4-8",
    "orchestrate": "claude-opus-4-8", "architect": "claude-opus-4-8",
    "critique": "claude-opus-4-8", "audit": "claude-opus-4-8",
    # Sonnet 4.6 — exécution / code / recherche
    "build": "claude-sonnet-4-6", "code": "claude-sonnet-4-6", "coding_only": "claude-sonnet-4-6",
    "refactor": "claude-sonnet-4-6", "debug": "claude-sonnet-4-6", "research": "claude-sonnet-4-6",
    "market_scan": "claude-sonnet-4-6", "general_purpose": "claude-sonnet-4-6",
    # Haiku 4.5 — tâches simples / rapides
    "extract": "claude-haiku-4-5", "format": "claude-haiku-4-5", "score": "claude-haiku-4-5",
    "classify": "claude-haiku-4-5", "summarize": "claude-haiku-4-5", "translate": "claude-haiku-4-5",
    "write_email": "claude-haiku-4-5", "write_post": "claude-haiku-4-5",
}

def claude_model_for_task(task_type: str) -> str:
    """Modèle Claude RÉEL idéal pour la tâche (rien d'overkill).
    Opus 4.8 réservé au plan d'implémentation complet / orchestration / audit.
    Défaut : Sonnet 4.6 (workhorse). Tâches triviales → tier Haiku."""
    return CLAUDE_TASK_MODEL.get((task_type or "").lower(), "claude-sonnet-4-6")

# ─── [S-24] ds2api + RTK — CODE MORT, retiré du routage le 2026-07-27 ──────────
# Les symboles ci-dessous ne sont plus appelés par _call_anthropic (Claude→MiMo).
# Gardés temporairement pour référence ; à supprimer dans un nettoyage futur.

_DS2API_BOOTSTRAPPED = False

def _ensure_ds2api() -> None:
    """Lazy-init: auto-start ds2api container on first forge_call. Idempotent."""
    global _DS2API_BOOTSTRAPPED
    if _DS2API_BOOTSTRAPPED:
        return
    _DS2API_BOOTSTRAPPED = True
    try:
        from ..ds2api.bootstrap_ds2api import bootstrap_ds2api
        result = bootstrap_ds2api()
        if result["ready"]:
            logger.info("[forge_llm] ds2api auto-started and verified ✓")
        else:
            logger.warning(f"[forge_llm] ds2api bootstrap partial: {result}")
    except Exception as e:
        logger.debug(f"[forge_llm] ds2api bootstrap skipped: {e}")

# ─── Env loading ─────────────────────────────────────────────────────────────
def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    for env_path in [FORGE_ROOT / ".env", FORGE_ROOT / ".env.local"]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env

# ─── DS2API Rate Limiter (token bucket, avoid ban) ───────────────────────────
class _RateLimiter:
    """Thread-safe token bucket rate limiter per provider."""
    def __init__(self, max_per_minute: int = 6, burst: int = 2):
        self._max = max_per_minute
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """Returns True if request allowed, False if rate-limited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._max, self._tokens + elapsed * (self._max / 60.0))
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def wait_time(self) -> float:
        """Seconds until next token available."""
        with self._lock:
            if self._tokens >= 1.0:
                return 0.0
            return (1.0 - self._tokens) / (self._max / 60.0)

# Conservative: 6 req/min, burst 2 — safe for DeepSeek web interface
_DS2API_LIMITER = _RateLimiter(max_per_minute=6, burst=2)

# Tasks allowed to use ds2api (simple, low-stakes — never orchestration/build/critique)
DS2API_SIMPLE_TASKS = frozenset({
    "score", "summarize", "format", "extract", "classify",
    "translate", "rewrite", "template", "fast_extraction",
})

# ─── Token tracker (optionnel — ne casse pas si absent) ──────────────────────
def _log_to_tracker(provider: str, tier: str, input_tok: int, output_tok: int,
                    latency_ms: int, node: str = "forge_llm", task_type: str = ""):
    try:
        from .token_tracker import get_tracker, TokenUsage, model_from_tier_and_provider
        model = model_from_tier_and_provider(tier, provider)
        from .token_tracker import compute_cost
        cost = compute_cost(model, input_tok, output_tok)
        usage = TokenUsage(
            model=model.value, input_tokens=input_tok, output_tokens=output_tok,
            cost_usd=cost, latency_ms=latency_ms, node_name=node, task_type=task_type
        )
        get_tracker().add_log(usage)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        model = None
        cost = 0.0

    # ── forge_metrics.jsonl : observabilité unifiée (P0 instrumentation) ──
    # Émet un record LLM dans le sink JSONL avec les VRAIS cost_usd + latency_ms.
    # Avant ce fix, seuls les tool records (SEE) étaient écrits → 0% instrumentation
    # LLM sur cost/latency. Désormais chaque forge_call() traçable.
    try:
        from .forge_metrics import record as _fm_record
        model_str = model.value if hasattr(model, 'value') else str(model) if model else tier
        _fm_record(
            kind="llm",
            workflow=task_type or node,
            agent=provider or tier,
            node=node,
            provider=provider,
            model=model_str,
            tokens_in=input_tok,
            tokens_out=output_tok,
            latency_ms=latency_ms,
            cost_usd=round(cost, 6),
        )
    except Exception as exc:
        logger.debug("forge_metrics record skipped: %s", exc)

# ─── OpenViking context enrichment ────────────────────────────────────────────
def _enrich_with_openviking(prompt: str, task_type: str) -> str:
    """Injecte le contexte OpenViking (Graphify) dans le prompt si disponible."""
    try:
        from .openviking import VikingContext, get_viking
        ctx: VikingContext = get_viking().retrieve_context(query=prompt[:300], task_type=task_type)
        if ctx.content and not ctx.is_fallback:
            return f"[Mémoire Forge]\n{ctx.content}\n\n---\n{prompt}"
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return prompt

# ─── VRAI Claude (Anthropic SDK) — moteur par défaut de la Forge ─────────────
def _claude_enabled(env: dict | None = None) -> bool:
    """La Forge tourne sur Claude par défaut. Kill switch : FORGE_CLAUDE_DEFAULT=0."""
    env = env or _load_env()
    return env.get("FORGE_CLAUDE_DEFAULT", "1").lower() in ("true", "1", "yes")


def _call_claude_cli(prompt: str, system: str, model: str, max_tokens: int,
                     node: str = "forge_llm", task_type: str = "", tier_label: str = "",
                     thinking: bool = False) -> str:
    """
    Appel Claude via le CLI `claude -p` (headless) = ABONNEMENT, PAS d'API au token.
    Utilise la session Claude Code connectée (OAuth abo) — aucune ANTHROPIC_API_KEY.
    Lève si le CLI est absent/échoue → l'appelant retombe sur le SDK API puis les proxies.
    Kill switch : FORGE_CLAUDE_CLI=0 dans .env.

    thinking=True : active l'extended thinking (Opus uniquement, budget adaptatif).
    Kill switch : FORGE_THINKING=0 dans .env désactive le thinking même si demandé.
    """
    import shutil, subprocess
    exe = shutil.which("claude") or shutil.which("claude.cmd")
    if not exe:
        raise RuntimeError("CLI `claude` introuvable (PATH)")
    # model full-ID → alias CLI robuste (haiku/sonnet/opus) : les IDs peuvent être périmés
    m = (model or "").lower()
    alias = "haiku" if "haiku" in m else "opus" if "opus" in m else "sonnet"
    cmd = [exe, "-p", "--model", alias, "--output-format", "text"]
    # Extended thinking : activé seulement si demandé ET non désactivé par .env
    env = _load_env()
    thinking_enabled = env.get("FORGE_THINKING", "1").lower() in ("true", "1", "yes")
    if thinking and thinking_enabled and alias == "opus":
        cmd.append("--thinking")
        logger.debug(f"[forge_llm] extended thinking activé pour {alias}")
    if system:
        cmd += ["--append-system-prompt", system]
    t0 = time.time()
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI rc={proc.returncode}: {(proc.stderr or '')[:200]}")
    text = (proc.stdout or "").strip()
    if not text:
        raise RuntimeError("claude CLI rc=0 mais sortie vide (fluke) — fallback")
    latency = int((time.time() - t0) * 1000)
    in_tok, out_tok = len(prompt) // 4, len(text) // 4
    _log_to_tracker("claude_cli", tier_label or alias, in_tok, out_tok, latency, node, task_type)
    logger.debug(f"ROUTE|CLAUDE_CLI|{alias}|thinking={thinking}|{latency}ms (abonnement)")
    return text


def _call_claude(prompt: str, system: str, model: str, max_tokens: int,
                 node: str = "forge_llm", task_type: str = "", tier_label: str = "",
                 thinking: bool = False) -> str:
    """
    Claude par ABONNEMENT d'abord (CLI `claude -p`, 0 token API), puis SDK API en
    fallback (ANTHROPIC_API_KEY). Lève si les deux échouent → l'appelant retombe
    sur les proxies gratuits (dégradation gracieuse).

    thinking=True : active l'extended thinking pour Opus (via CLI ou SDK).
    """
    # ── Health check : skip Claude si indisponible ──────────────────────
    from .forge_claude_health import claude_health, ClaudeStatus
    health = claude_health()
    if not health.is_available():
        reason = health.fallback_reason()
        logger.debug(f"[forge_llm] Claude SKIP ({reason})")
        raise RuntimeError(f"Claude indisponible: {reason}")

    env = _load_env()
    # ── ABONNEMENT d'abord : CLI `claude -p` (session connectée, pas de facturation) ──
    if env.get("FORGE_CLAUDE_CLI", "1").lower() in ("true", "1", "yes"):
        try:
            return _call_claude_cli(prompt, system, model, max_tokens, node, task_type,
                                    tier_label, thinking=thinking)
        except Exception as e:
            logger.debug(f"[forge_llm] CLI abonnement fail: {e}, fallback SDK API")
            # Met à jour le health tracker avec l'erreur
            health.check(force=True)
    # ── Fallback : SDK API (facturé au token) ──
    key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("CLI abonnement indisponible et ANTHROPIC_API_KEY absent (.env)")
    import anthropic
    client = anthropic.Anthropic(api_key=key, max_retries=1)
    t0 = time.time()
    kwargs: dict = {"model": model, "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    # Extended thinking via SDK (Opus/Sonnet avec budget adaptatif)
    if thinking:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": min(max_tokens * 2, 10000)}
    resp = client.messages.create(**kwargs)
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", "") == "text")
    latency = int((time.time() - t0) * 1000)
    in_tok  = getattr(resp.usage, "input_tokens", len(prompt) // 4)
    out_tok = getattr(resp.usage, "output_tokens", len(text) // 4)
    _log_to_tracker("anthropic", tier_label or model, in_tok, out_tok, latency, node, task_type)
    logger.debug(f"ROUTE|CLAUDE|{model}|thinking={thinking}|{latency}ms in={in_tok} out={out_tok}")
    return text


# ─── Paid tier : MiMo (HAIKU) + Claude (SONNET/OPUS) + fallbacks ─────────────
# NOTE : RTK n'est PAS un LLM — c'est le Rust Token Killer (compression de
# sorties de commandes). Il n'apparaît donc PAS dans la cascade LLM. Voir
# 00_CORE/tools/rtk.py pour l'optimisation tokens des commandes.
def _call_anthropic(prompt: str, system: str, tier: LLMTier,
                    max_tokens: int, node: str = "forge_llm",
                    task_type: str = "", thinking: bool = False) -> str:
    """
    Routing S-24 : Claude → MiMo (payant, budget-gardé).

      TOUS les tiers → Claude d'abord → MiMo si Claude indisponible.
      Plus de tier gratuit : ds2api et Groq retirés (décisions 5+6, 2026-07-25).
      MiMo est la seule soupape restante — facturée, sous garde-fou budget (S-07).

    thinking=True : active l'extended thinking pour Opus (via effort level).
    """
    env = _load_env()
    errors = []

    # ── 1. Claude (moteur par défaut pour TOUS les tiers) ───────────────
    if _claude_enabled(env):
        try:
            model = ANTHROPIC_MODELS.get(tier, ANTHROPIC_MODELS[LLMTier.SONNET])
            return _call_claude(prompt, system, model, max_tokens, node, task_type,
                                tier.value, thinking=thinking)
        except Exception as e:
            logger.debug(f"[forge_llm] {tier.value}→Claude fail: {e}, fallback MiMo")
            errors.append(f"claude: {e}")

    # ── 2. MiMo (payant — la seule soupape restante) ────────────────────
    # S-07 : budget check AVANT de dépenser. Si le budget MiMo est épuisé,
    # on échoue franchement au lieu de brûler des tokens qu'on ne peut pas payer.
    try:
        from .forge_mimo import mimo_call, is_available as mimo_available, _est_tokens
        from .mimo_budget import check as budget_check, BudgetExceeded
        if mimo_available():
            budget_check(_est_tokens(prompt + (system or "")) + max_tokens)
            text, m = mimo_call(prompt, system=system, max_tokens=max_tokens)
            _log_to_tracker("mimo", "mimo-v2.5-pro", m.get("in", 0), m.get("out", 0),
                            m.get("latency_ms", 0), node, task_type)
            logger.debug(f"ROUTE|{tier.value}|mimo|{m.get('latency_ms',0)}ms "
                         f"in={m.get('in',0)} out={m.get('out',0)} billed={m.get('billed_tokens',0)}")
            return text
    except BudgetExceeded:
        raise  # S-07 : ne pas dégrader — le budget est épuisé
    except Exception as e:
        logger.debug(f"[forge_llm] {tier.value}→MiMo fail: {e}")
        errors.append(f"mimo: {e}")

    raise EnvironmentError(
        f"[forge_llm] {tier.value}: Claude et MiMo ont tous échoué.\n"
        f"Errors: {' | '.join(errors)}"
    )



# ─── OptiForge: stateless one-shot helpers ───────────────────────────────────

def _estimate_token_count(text: str) -> int:
    """Estimation rapide: ~1 token per 4 chars (conservative)."""
    return len(text) // 4

def _check_ceiling(prompt: str, system: str = "") -> None:
    """Hard block si le prompt dépasse 50K tokens. Lève OverflowError."""
    total = _estimate_token_count(prompt + (system or ""))
    if total > TOKEN_CEILING:
        raise OverflowError(
            f"[OPTIFORGE] PROMPT EXCEEDS CEILING: {total} > {TOKEN_CEILING} tokens. "
            f"CHUNKING REQUIRED. Reduce context or split task."
        )

def _check_subtask_budget(prompt: str, node: str = "") -> bool:
    """Soft warn si sous-tâche dépasse 5K tokens. Retourne True si OK."""
    est = _estimate_token_count(prompt)
    if est > SUBTASK_BUDGET:
        logger.debug(f"ERR|SUBTASK_BUDGET|{node}|{est}>{SUBTASK_BUDGET}_tok")
        return False
    return True

def _save_stateless(result: str, task_type: str, node: str, tokens_used: int) -> None:
    """Sauvegarde résultat dans .nexus/agent_state.json (state offloading)."""
    try:
        NEXUS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "last_result": result[:2000],  # tronquer pour limiter taille
            "task_type": task_type,
            "node": node,
            "tokens_used": tokens_used,
            "timestamp": time.time(),
            "flushed": True,
        }
        NEXUS_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")
        logger.debug(f"[OPTIFORGE] STATE SAVED → {NEXUS_STATE_FILE}. CONTEXT FLUSHED.")
    except Exception as e:
        logger.debug(f"[OPTIFORGE] state save failed: {e}")

def _semantic_cache_check(code_or_prompt: str) -> Optional[str]:
    """Vérifie le cache sémantique. Retourne le résultat caché ou None."""
    try:
        from .semantic_cache import get_cache
        cache = get_cache()
        entry = cache.lookup(code_or_prompt)
        if entry:
            logger.debug(f"ROUTE|CACHE|{entry.file_path}|HIT score={entry.score}")
            return entry.result
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return None

def _semantic_cache_store(code_or_prompt: str, result: str, task_type: str, score: float = 0.0) -> None:
    """Stocke un résultat dans le cache sémantique."""
    try:
        from .semantic_cache import get_cache
        cache = get_cache()
        cache.store(code_or_prompt, f"forge_call:{task_type}", "0-0", result, score)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


# ─── Public API ──────────────────────────────────────────────────────────────
_NMP_SYSTEM: Optional[str] = None  # lazy load pour éviter import circulaire

def _get_nano_system() -> str:
    global _NMP_SYSTEM
    if _NMP_SYSTEM is None:
        try:
            from .nanomachine import NANO_SYSTEM_PROMPT
            _NMP_SYSTEM = NANO_SYSTEM_PROMPT
        except Exception:
            _NMP_SYSTEM = "Speak only in: COMMAND|SOURCE|TARGET|PAYLOAD. No prose."
    return _NMP_SYSTEM


try:
    from .forge_observability import traced as _traced, init_observability as _init_obs
    _init_obs()  # set LANGCHAIN_* env tôt → LangGraph s'auto-trace aussi
except Exception:
    def _traced(*_a, **_k):
        def _d(f):
            return f
        return _d


@_traced(name="forge_call", run_type="llm")
def forge_call(
    prompt: str,
    tier: LLMTier = LLMTier.SONNET,
    system: str = "",
    max_tokens: int = 1500,
    task_type: Optional[str] = None,
    node: str = "forge_llm",
    use_openviking: bool = True,
    nano_mode: bool = True,
    show_tokens: bool = True,
    jailbreak: bool = False,
    parseltongue_level: int = 0,
    liberation_command: Optional[str] = None,
    post_stm: bool = False,
    effort: Optional[str] = None,
) -> str:
    """
    Appel LLM unifié — NMP natif pour Mimo/Hermes.
    OPTIFORGE v2 : stateless one-shot, 65K ceiling, NMP system, semantic cache, flush.

    nano_mode=True (défaut) : NANO_SYSTEM_PROMPT injecté dans TOUS les sous-agents.
    Seul l'output final user (agent_output) reste human-readable — appelé avec nano_mode=False.
    show_tokens=True (défaut) : affiche estimate avant + actual après chaque appel.

    effort="low|medium|high|max" : contrôle le niveau de raisonnement.
      - low    → MiMo/Haiku, pas de thinking (extraction, score, format)
      - medium → Sonnet, pas de thinking (code, research, build)
      - high   → Opus + thinking adaptatif (orchestration, audit, critique)
      - max    → Opus + thinking forcé (plan d'implémentation complexe)
      Si None, déduit automatiquement du task_type via effort_for_task().

    jailbreak=True : injecte le system prompt GODMODE (L1B3RT4S + G0DM0D3).
      - parseltongue_level : 0=off, 1=leetspeak, 2=+homoglyphs, 3=+zerowidth+phonetic
      - liberation_command : ex "{GODMODE:ENABLED}", "!JAILBREAK", "!OPPO", etc.
      - post_stm : applique STM pipeline sur la réponse (strip hedging)
    """
    # ── JAILBREAK INJECTION (L1B3RT4S + G0DM0D3) ─────────────────────
    if jailbreak:
        if not _JAILBREAK_AVAILABLE:
            logger.warning("[forge_llm] jailbreak=True mais forge_jailbreak module non disponible")
        else:
            # Override system prompt with GODMODE
            system = _JB_SYSTEM
            # Disable nano_mode (NMP conflicts with jailbreak format)
            nano_mode = False
            # Disable OpenViking (jailbreak context is self-contained)
            use_openviking = False
            # Apply Parseltongue perturbation to user prompt
            if parseltongue_level > 0:
                prompt = _parseltongue_fn(prompt, parseltongue_level)
                logger.debug(f"[JAILBREAK] Parseltongue L{parseltongue_level} applied")
            # Prepend liberation command if provided
            if liberation_command:
                # Normalize: strip braces for lookup ({GODMODE:ENABLED} → GODMODE:ENABLED)
                cmd_key = liberation_command.strip("{}")
                if cmd_key in _JB_COMMANDS or liberation_command in _JB_COMMANDS:
                    prompt = f"{liberation_command}\n\n{prompt}"
                    logger.debug(f"[JAILBREAK] Liberation: {liberation_command}")
                else:
                    # Try fuzzy match
                    matches = [c for c in _JB_COMMANDS if cmd_key.lower() in c.lower()]
                    if matches:
                        prompt = f"{matches[0]}\n\n{prompt}"
                        logger.debug(f"[JAILBREAK] Liberation (fuzzy): {matches[0]}")
                    else:
                        prompt = f"{liberation_command}\n\n{prompt}"
                        logger.warning(f"[JAILBREAK] Unknown command: {liberation_command}")
            logger.info(f"[JAILBREAK] GODMODE active | parseltongue={parseltongue_level} | cmd={liberation_command}")

    # ── CLAUDE HEALTH WARM-UP : check une seule fois par session ──────
    from .forge_claude_health import claude_health
    claude_health().warm_up()

    # ── INFERENCE OPTIMIZATION: compress + cache check ────────────────────
    if _INFERENCE_OPTIMIZED:
        prompt, system = optimized_prepare(prompt, system)

    # ── CERVELET: Interception Token-ID (réflexe RAM, 0 token LLM) ──────
    from .cervelet import cervelet_intercept
    _cervelet_result = cervelet_intercept(prompt.strip())
    if _cervelet_result is not None:
        if _cervelet_result == "ERR:SURVIE_BUDGET_STOP":
            raise RuntimeError("[Cervelet] Budget forge critique — appels LLM suspendus.")
        logger.info(f"[CERVELET] Réflexe RAM → {_cervelet_result}")
        return _cervelet_result

    # ── AAOS 63/64: Execution fingerprint — zero-redundancy gate (TOUS tiers) ──
    # Même tâche + même contexte + même version d'agents → 0 appel LLM.
    _fp = None
    try:
        from .forge_fingerprint import get_fingerprint_store, make_fingerprint, fingerprint_enabled
        if fingerprint_enabled():
            _fp = make_fingerprint(prompt, system, tier.value, task_type or "")
            _fp_hit = get_fingerprint_store().check(_fp)
            if _fp_hit is not None:
                logger.info(f"ROUTE|FINGERPRINT|HIT 0_tokens ({_fp[:12]})")
                try:
                    from .token_tracker import get_tracker
                    get_tracker().add_saving(tokens=_fp_hit.get("tokens", 0),
                                             cost=_fp_hit.get("cost", 0.0),
                                             latency_ms=int(_fp_hit.get("latency", 0.0) * 1000))
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
                return _fp_hit["result"]
    except Exception as e:
        logger.debug(f"[fingerprint] check skipped: {e}")

    # ── OPTIFORGE: Semantic cache check (0 tokens si hit) ────────────
    if task_type in ("coding_only", "audit", "build", "fast_extraction"):
        cached = _semantic_cache_check(prompt)
        if cached:
            logger.debug(f"ROUTE|CACHE|{task_type}|HIT 0_tokens")
            return cached

    # ── NMP System Prompt injection (tous sous-agents sauf output user) ──
    if nano_mode:
        nano_suffix = "\n\n" + _get_nano_system()
        system = (system + nano_suffix) if system else nano_suffix

    # ── PXPipe: Visual Context Compression ──────────────────────────────
    # Si le system prompt dépasse le seuil ET que le provider supporte vision,
    # on compresse en image PNG (~1600 tokens fixe au lieu de 10K+ tokens texte).
    # Flag: PXPipe=1 dans .env active la compression visuelle.
    _pxpipe_active = False
    try:
        env_px = _load_env()
        if env_px.get("PXPipe", "").lower() in ("true", "1", "yes"):
            from .forge_pxpipe import should_compress, inject_visual_context
            if system and should_compress(system):
                original_tokens = _estimate_token_count(system)
                system = inject_visual_context(system)
                _pxpipe_active = True
                logger.info(f"[PXPipe] system compressed: {original_tokens} tok → "
                            f"~1600 tok (image)")
    except Exception as e:
        logger.debug(f"[PXPipe] skipped: {e}")

    # ── OPTIFORGE: 65K token ceiling Mimo/Hermes (HARD BLOCK) ────────
    _check_ceiling(prompt, system)

    # ── OPTIFORGE: Subtask budget warn (SOFT) ────────────────────────
    _check_subtask_budget(prompt, node)

    # Safe load environment to check test overrides
    env = _load_env()
    if task_type:
        tier = tier_for_task(task_type)
    if use_openviking and task_type:
        prompt = _enrich_with_openviking(prompt, task_type)

    # ── TOKEN ESTIMATE (before call) ──────────────────────────────────
    est_in = _estimate_token_count(prompt + (system or ""))
    est_out = min(max_tokens, est_in // 2)  # heuristic: output ≈ 50% of input
    if show_tokens:
        # Détermine le provider attendu pour l'affichage
        from .forge_claude_health import claude_health as _ch
        _ch_snap = _ch().snapshot()
        _claude_ok = _ch_snap.status.value == "ready"
        if tier == LLMTier.HAIKU:
            from .forge_mimo import is_available as _mimo_ok
            _provider = "mimo" if _mimo_ok() else ("claude" if _claude_ok else "fallback")
        else:
            _provider = "claude" if _claude_ok else "fallback"
        _claude_note = "" if _claude_ok else f" | Claude: {_ch_snap.status.value}"
        est_cost = 0.0  # Claude abonnement / MiMo payant — coût non chiffrable ici
        print(f"╔══════════════════════════════════════════════════════╗")
        print(f"║ TOKEN ESTIMATE — {task_type or 'general':<18} tier={tier.value:<8} ║")
        print(f"╠══════════════════════════════════════════════════════╣")
        print(f"║ Est. Input   : {est_in:>8,} tokens                     ║")
        print(f"║ Est. Output  : {est_out:>8,} tokens (max_tokens={max_tokens:<5}) ║")
        print(f"║ Provider     : {_provider:<8}{_claude_note:<30} ║")
        print(f"║ Est. Cost    : Free (mimo/cli/proxy)                 ║")
        print(f"╚══════════════════════════════════════════════════════╝")

    t0 = time.time()

    # ── EFFORT → THINKING resolution ──────────────────────────────────
    from .forge_effort import effort_for_task, effort_params, EffortLevel
    if effort is not None:
        effort_level = EffortLevel(effort.lower())
    elif task_type:
        effort_level = effort_for_task(task_type)
    else:
        effort_level = EffortLevel.MEDIUM
    effort_cfg = effort_params(effort_level)
    thinking = effort_cfg.get("claude_thinking", False)
    if show_tokens:
        logger.debug(f"[EFFORT] {effort_level.value} → thinking={thinking} model={effort_cfg['claude_model']}")

    result = _call_anthropic(prompt, system, tier, max_tokens, node, task_type or "",
                             thinking=thinking)

    elapsed = time.time() - t0

    # ── TOKEN ACTUAL (after call) ─────────────────────────────────────
    actual_out = _estimate_token_count(result)
    if show_tokens:
        variance_in = 0
        variance_out = ((actual_out - est_out) / est_out * 100) if est_out else 0
        pxpipe_note = " | PXPipe: ACTIVE (image)" if _pxpipe_active else ""
        print(f"╔══════════════════════════════════════════════════════╗")
        print(f"║ TOKEN ACTUAL  — {task_type or 'general':<18} tier={tier.value:<8} ║")
        print(f"╠══════════════════════════════════════════════════════╣")
        print(f"║ Real Output  : {actual_out:>8,} tokens                     ║")
        print(f"║ Latency      : {elapsed:>8.1f}s                         ║")
        print(f"║ Cost         : Claude (abonnement) / MiMo (payant)  ║")
        print(f"║ Variance out : {variance_out:>+7.1f}%{pxpipe_note:<20} ║")
        print(f"╚══════════════════════════════════════════════════════╝")

    # ── OPTIFORGE: Stateless save + flush ────────────────────────────
    tokens_used = _estimate_token_count(prompt + result)
    _save_stateless(result, task_type or "", node, tokens_used)

    # ── OPTIFORGE: Store in semantic cache for future reuse ──────────
    if task_type in ("coding_only", "audit", "build"):
        _semantic_cache_store(prompt, result, task_type or "")

    # ── AAOS 63: Enregistre l'empreinte d'exécution (zero-redundancy futur) ──
    if _fp is not None:
        try:
            from .forge_fingerprint import get_fingerprint_store
            get_fingerprint_store().record(
                _fp, result=result, provider=tier.value, cost=0.0,
                latency=elapsed, tokens=tokens_used,
                task=prompt[:200], task_type=task_type or "")
        except Exception as e:
            logger.debug(f"[fingerprint] record skipped: {e}")

    # ── JAILBREAK: STM post-processing (strip hedging from output) ───
    if jailbreak and post_stm and _JAILBREAK_AVAILABLE:
        result = _stm_fn(result)
        logger.debug("[JAILBREAK] STM post-processing applied")

    return result


def forge_score(text: str, criteria: str, node: str = "mirofish") -> float:
    """Score 0.0–10.0 via tier Haiku. Utilisé par MiroFish + auto_complexification."""
    prompt = (f"Note ce texte de 0.0 à 10.0 selon les critères.\n"
              f"Réponds UNIQUEMENT avec un nombre décimal (ex: 7.5).\n\n"
              f"Critères: {criteria}\n\nTexte:\n{text[:800]}\n\nNote (0.0-10.0):")
    try:
        result = forge_call(prompt, tier=LLMTier.HAIKU, max_tokens=10, node=node,
                            use_openviking=False)
        match = re.search(r'\d+\.?\d*', result)
        if match:
            return max(0.0, min(10.0, float(match.group())))
    except Exception as e:
        logger.debug(f"[forge_score] error: {e}")
    return 5.0


def forge_summarize(text: str, max_words: int = 100, node: str = "forge_llm") -> str:
    """Résumé rapide via tier Haiku."""
    return forge_call(
        f"Résume en {max_words} mots maximum, en français:\n\n{text[:2000]}",
        tier=LLMTier.HAIKU, max_tokens=200, node=node, use_openviking=False
    )


def forge_orchestrate(task: str, context: str, history: str = "",
                      node: str = "orchestrator") -> dict:
    """Décision d'orchestration dynamique via Opus + extended thinking."""
    system = (
        "Tu es l'orchestrateur d'un système multi-agents (Meta-Agent Factory). "
        "PENSE COMME UN VRAI CEO : tu n'exécutes JAMAIS la tâche toi-même. Ton seul job "
        "est de décider QUI tu dois recruter pour QUELLE tâche. Pour chaque tâche/sous-tâche :\n"
        "  1. Quel expert précis faut-il ? (titre, spécialité, séniorité)\n"
        "  2. Cet expert existe-t-il déjà ? Sinon, tu le CONÇOIS sur-mesure (nom + prompt) — un CEO "
        "embauche le bon profil quand il manque, il ne bricole pas avec un généraliste.\n"
        "  3. Tu délègues, tu ne fais pas. Le 'dynamic_prompt' EST la fiche de poste de l'expert.\n"
        "Réponds STRICTEMENT en JSON (aucune accolade imbriquée, pas de bloc markdown): {\n"
        "  \"dynamic_agent_name\": \"...\",\n"
        "  \"dynamic_prompt\": \"...\",\n"
        "  \"reasoning\": \"...\",\n"
        "  \"priority\": \"high|medium|low\",\n"
        "  \"complexity_score\": 0.0\n"
        "}\n"
        "Le 'dynamic_agent_name' doit être un titre d'expert sans espace (ex: Senior_Data_Scientist). "
        "Le 'dynamic_prompt' doit être son prompt système très détaillé (outils à utiliser, façon de penser). "
        "Le 'complexity_score' est un flottant 0.0–1.0 : à quel point la tâche exige un expert conçu "
        "sur-mesure (0.85+ = aucun généraliste ne suffit, concevoir un expert ULTRA)."
    )
    prompt = f"Tâche: {task}\n\nContexte: {context[:1000]}"
    if history:
        prompt += f"\n\nHistorique: {history[:500]}"
    result = forge_call(prompt, tier=LLMTier.SONNET, system=system, max_tokens=800,
                        node=node, task_type="plan")
    try:
        # Strip d'éventuels fences markdown puis match glouton (gère l'imbrication
        # d'accolades, contrairement à [^{}]+ qui cassait au 1er objet interne).
        cleaned = re.sub(r'```(?:json)?|```', '', result)
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            parsed["next_agent"] = "dynamic_agent"  # Forcer le routage vers le noeud dynamique
            try:
                parsed["complexity_score"] = max(0.0, min(1.0, float(parsed.get("complexity_score", 0.0))))
            except (TypeError, ValueError):
                parsed["complexity_score"] = 0.0
            return parsed
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return {
        "next_agent": "dynamic_agent",
        "dynamic_agent_name": "Fallback_Expert",
        "dynamic_prompt": "Tu es un expert par défaut. Résous la tâche.",
        "reasoning": result[:200],
        "priority": "medium",
        "complexity_score": 0.5,  # parse KO → milieu : ni architect ULTRA ni gate plan, mais pas 0
    }


# ─── CLI self-test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print("=== forge_llm self-test ===")
    print("Tier routing:")
    for t, expected in [("score", "haiku"), ("build", "sonnet"), ("critique", "opus")]:
        got = tier_for_task(t).value
        status = "✅" if got == expected else "❌"
        print(f"  {status} {t:15} → {got}")
    print()
    print(f"Jailbreak module available: {_JAILBREAK_AVAILABLE}")
    if _JAILBREAK_AVAILABLE:
        print(f"  System prompts: 2 (GODMODE + HERMES)")
        print(f"  Liberation commands: {len(_JB_COMMANDS)}")
        print(f"  Parseltongue: 3 levels")
        print(f"  GODMODE combos: {len(_GODMODE_COMBOS)}")
    print()
    print("forge_score (Haiku, sans connexion réseau → fallback 5.0):")
    s = forge_score("Test court", "pertinence")
    print(f"  score = {s}")
