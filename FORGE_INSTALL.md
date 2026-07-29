# FORGE V6 — Installation Guide for Claude Code

> **Purpose**: This file is the single source of truth for recreating the Forge V6 on a fresh machine.
> Give this file to Claude Code and say: *"Read FORGE_INSTALL.md and build everything it describes."*
> The Forge will be rebuilt clean — no junk files, no legacy state.

---

## 0. Prerequisites

```bash
# Python 3.11+
python --version  # must be >= 3.11

# pip packages
pip install langgraph langgraph-checkpoint-sqlite langgraph-checkpoint-postgres \
  langchain-core langchain-anthropic redis "psycopg[binary]" pgvector \
  anthropic google-generativeai openai requests httpx \
  python-dotenv pydantic rich numpy
```

### Free LLM Providers (Tier 0 — no cost)
- **Gemini 2.5 Flash**: https://ai.google.dev — get GEMINI_API_KEY
- **Groq (Llama 4)**: https://console.groq.com — get GROQ_API_KEY
- **Cerebras**: https://cloud.cerebras.ai — get CEREBRAS_API_KEY

### Optional (for paid models)
- **Anthropic**: ANTHROPIC_API_KEY
- **OpenAI**: OPENAI_API_KEY

---

## 1. Directory Structure

Create this exact structure under your project root (e.g. `~/.claude/`):

```
.claude/
├── 00_CORE/
│   ├── forge_agents/          # Core Python package (THE HEART)
│   ├── tools/                 # Tool wrappers organized by category
│   │   ├── registry.json      # Tool registry v2.0 (NMP format)
│   │   ├── research/
│   │   ├── catalog/
│   │   ├── mcp/
│   │   ├── product_bricks/
│   │   │   ├── ui/
│   │   │   ├── generative_media/
│   │   │   ├── saas_starters/
│   │   │   ├── ai_workflows/
│   │   │   ├── crm/
│   │   │   └── documents/
│   │   ├── delivery/
│   │   ├── automation/
│   │   ├── outreach/
│   │   ├── money/
│   │   ├── dev/
│   │   └── prompting/
│   ├── impeccable/            # UX/UI design skill (reference docs)
│   └── taste-skill/           # Design taste profiles
├── 01_ORCHESTRATOR/
│   ├── config.json            # Budget allocation
│   └── prompts/               # Agent prompts
├── 04_GRAPHIFY/               # LangGraph checkpoints (auto-created)
├── 05_STATE/                  # Persistent runtime state (auto-created)
│   ├── logs/executions/       # Execution traces
│   ├── system_registry/       # System registry JSON
│   ├── evidence/              # Quality gate evidence
│   └── kanban/                # Kanban board state
├── 09_TASKS/
│   ├── queue/                 # Pending tasks
│   └── done/                  # Completed tasks
├── .env                       # API keys (NEVER commit)
├── AGENTS.md                  # Agent instructions
├── CLAUDE.md                  # Session config
└── requirements.txt           # Python deps
```

Create it:
```bash
mkdir -p 00_CORE/forge_agents 00_CORE/tools/{research,catalog,mcp,product_bricks/{ui,generative_media,saas_starters,ai_workflows,crm,documents},delivery,automation,outreach,money,dev,prompting}
mkdir -p 00_CORE/impeccable/reference 00_CORE/taste-skill
mkdir -p 01_ORCHESTRATOR/prompts 04_GRAPHIFY
mkdir -p 05_STATE/{logs/executions,system_registry,evidence,kanban,agents,datasets}
mkdir -p 09_TASKS/{queue,done}
```

---

## 2. Environment File (.env)

Create `.env` in the project root:

```env
# LLM Providers (at least one Tier 0 required)
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
CEREBRAS_API_KEY=your_key_here
# ANTHROPIC_API_KEY=your_key_here
# OPENAI_API_KEY=your_key_here

# Database (optional — falls back to SQLite)
# DATABASE_URL=postgresql://user:pass@localhost:5432/forge
# REDIS_URL=redis://localhost:6380

# Forge
FORGE_ROOT=/path/to/your/.claude
```

---

## 3. Core Package — 00_CORE/forge_agents/

This is the heart of the Forge. Create these files in order.

### 3.1 `__init__.py` — Package entry point

```python
"""
Forge Agents — LangGraph Meta-Agent System V6
"""
import sys as _sys
for _stream in ("stdout", "stderr"):
    try:
        getattr(_sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .forge_state import ForgeState, Finding, CavemanMsg, JuryVerdict, initial_state
from .forge_graph import ForgeRunner, build_forge_graph
from .forge_kernel import Kernel, extract_kernel_fast, get_or_extract_kernel
from .forge_shared_brain import ForgeBrain, get_brain, get_kernel_store, get_mcp_cache, get_shared_reasoning
from .forge_experience_db import ExperienceDB, Experience, get_experience_db
from .forge_meta import ForgeMetaLayer, EmotionalState, get_meta
from .forge_lazy import LazyExecutionEngine, get_lazy_engine
from .forge_event_bus import ForgeEventBus, ForgeEvent, get_event_bus, get_tracer
from .forge_self_heal import SelfHealingEngine, get_healer, CheckpointManager
from .forge_system_registry import SystemRegistry, get_registry, refresh_registry
from .forge_execution_logger import ExecutionLogger, ExecutionLog, get_logger
from .forge_mcp_pruner import MCPPruningEngine, get_pruner, refresh_pruner
from .forge_no_mistakes import NoMistakesGate, ForgeQualityGate, get_quality_gate

__all__ = [
    "ForgeState", "Finding", "CavemanMsg", "JuryVerdict", "initial_state",
    "ForgeRunner", "build_forge_graph",
    "Kernel", "extract_kernel_fast", "get_or_extract_kernel",
    "ForgeBrain", "get_brain", "get_kernel_store", "get_mcp_cache", "get_shared_reasoning",
    "ExperienceDB", "Experience", "get_experience_db",
    "ForgeMetaLayer", "EmotionalState", "get_meta",
    "LazyExecutionEngine", "get_lazy_engine",
    "ForgeEventBus", "ForgeEvent", "get_event_bus", "get_tracer",
    "SelfHealingEngine", "get_healer", "CheckpointManager",
    "SystemRegistry", "get_registry", "refresh_registry",
    "ExecutionLogger", "ExecutionLog", "get_logger",
    "MCPPruningEngine", "get_pruner", "refresh_pruner",
    "NoMistakesGate", "ForgeQualityGate", "get_quality_gate",
]
```

### 3.2 `forge_state.py` — Shared State (48 fields)

The ForgeState TypedDict is the single shared state between ALL agents. Every node reads AND writes this.

Key fields:
- **Orchestration**: current_task, cycle, level (L1-L4), next_agent, task_complete
- **Agents**: dynamic_agent_name, dynamic_agent_prompt
- **Messages**: messages (LangGraph native), nmp_log (NMP packets, max 50)
- **Findings**: findings (max 20), agent_output, agent_output_tokens
- **Jury**: jury_seed, jury_persona_scores, jury_verdict
- **Complexification**: quality_history, quality_delta, should_level_up, should_rollback
- **Tokens**: token_estimate, token_actual, token_analysis
- **Progress**: progress_done, progress_todo, progress_current_step
- **V6 Shared Brain**: kernel_id, kernel_domain, kernel_confidence, shared_context
- **V6 MCP Cache**: mcp_cache_hits, mcp_cache_misses
- **V6 Meta**: meta_confidence, meta_uncertainty, meta_risk, meta_reward, meta_curiosity, meta_recommendation
- **V6 Lazy**: lazy_strategy, lazy_reason
- **V6 Experience**: experience_recorded
- **V6 Self-Heal**: heal_actions, heal_executed
- **V6 Events**: events_emitted
- **Meta**: error, error_agent, session_id

Build this file with all 48 fields as a TypedDict. Use `Annotated[list, prune_func]` for lists that need bounds.

### 3.3 `forge_graph.py` — LangGraph Graph

**Nodes (11):**
1. `v6_init` — Kernel extraction, shared brain init, lazy engine plan, event bus start
2. `estimate_budget` — Token budget estimation
3. `orchestrator` — Routing decision
4. `dynamic_agent` — Dynamic agent execution
5. `v6_post_execution` — Meta layer update, experience DB, self-heal, event bus
6. `auto_complexification` — Level up/rollback/continue/kill
7. `post_mortem` — Final analysis
8. `memory_pruner` — Memory pruning
9. `zsl_analysis` — Zero-shot learning analysis
10. `neuro_symbolic_verification` — Neuro-symbolic verification
11. `anti_hallucination` — Anti-hallucination check

**Edges:**
```
ENTRY → v6_init → estimate_budget → orchestrator

orchestrator → (conditional: route_from_orchestrator)
  → dynamic_agent
  → zsl_analysis
  → END

dynamic_agent → (conditional: route_after_agent)
  → v6_post_execution  (key: "auto_complexification")
  → neuro_symbolic_verification
  → END

zsl_analysis → dynamic_agent
v6_post_execution → auto_complexification

neuro_symbolic_verification → anti_hallucination
anti_hallucination → (conditional)
  → auto_complexification
  → dynamic_agent (retry)

auto_complexification → (conditional)
  → memory_pruner (key: "orchestrator")
  → post_mortem (key: "__end__")

memory_pruner → orchestrator (loop)
post_mortem → END
```

**Checkpointer**: PostgresSaver (primary) → SqliteSaver (fallback) → MemorySaver (tests)

Build `ForgeRunner` class with `run_task(task, task_desc, max_cycles, quiet)` method.

### 3.4 V6 Core Modules (11 files)

Each module is self-contained with its own singleton getter. Build them in this order:

1. **forge_kernel.py** — Kernel Engine
   - `Kernel` dataclass: core_intent, entities, constraints, required_capabilities, domain, complexity_estimate, confidence, evidence, assumptions, unknowns, sources, kernel_id
   - `extract_kernel_fast(task)` — fast extraction WITHOUT LLM (keyword-based)
   - `detect_domain(task)` — domain detection (web_dev, security, data, product, bot, devops, design, ai_ml, email, agency)
   - `detect_capabilities(task)` — capability detection
   - `estimate_complexity(task)` — complexity 0.0→1.0
   - `get_or_extract_kernel(task)` — cached extraction
   - `hallucination_checkpoint(kernel)` — checkpoint format

2. **forge_shared_brain.py** — Shared Brain
   - `GlobalKernelStore` — one kernel, all agents read it
   - `MCPProxyCache` — first fetch → cache → all reuse (÷5-20x cost)
   - `SharedReasoningState` — decisions, rejected_options, confirmed_facts, partial_solutions, retrieved_docs
   - `ContextInjector` — builds agent context from kernel + reasoning + MCP cache
   - `ForgeBrain` — orchestrator of all 3 components

3. **forge_experience_db.py** — Experience Database
   - `Experience` dataclass: kernel_id, task, used_nodes, outcome, reason, cost, latency, tokens_used, hallucination_flags, quality_score, domain
   - `WorkflowScore` — reputation aggregated per workflow
   - `ComponentHealth` — health per component (healthy/degraded/dead)
   - `ExperienceDB` — persists to 05_STATE/experience_db.json
   - `subsystem_consolidation()` — background memory consolidation

4. **forge_meta.py** — Meta Layer (Alter Stratégique)
   - `EmotionalState`: confidence, uncertainty, risk, reward, curiosity, novelty
   - `SystemHealth`: redundancy, cost, hallucination_rate, underused_nodes, broken_nodes
   - `ForgeMetaLayer.observe_execution()` — updates emotional state after each run
   - `suggest_optimization()` — returns actionable recommendation
   - Persists to 05_STATE/meta_state.json

5. **forge_lazy.py** — Lazy Execution Engine
   - `SolutionCacheStore` — cached solutions
   - `LazyExecutionEngine.plan(task)` → strategy: "reuse" | "adapt" | "full_execution"
   - Anti-loop: max 5 loops per task
   - `record_solution(task, solution, quality)` — cache for reuse

6. **forge_event_bus.py** — Event Bus
   - `ForgeEvent` dataclass: type, source, data, timestamp
   - `ForgeEventBus` — subscribe/emit/get_history
   - Event types: NODE_EXECUTED, NODE_FAILED, KERNEL_EXTRACTED, MCP_CACHE_HIT, MCP_CACHE_MISS, HALLUCINATION_DETECTED, OPTIMIZATION_SUGGESTED, V6_INIT
   - `ExecutionTracer` — traces complete execution paths

7. **forge_self_heal.py** — Self-Healing
   - `Evidence` — verified evidence with type, source, confidence
   - `EVIDENCE_TYPES`: official_docs, github, postmortems, benchmarks, security_data, case_studies, reddit_feedback
   - `DOMAIN_EVIDENCE_MAP` — domain→required evidence types
   - `Checkpoint` — anti-hallucination checkpoint (goal, known_facts, assumptions, unknowns, sources, confidence)
   - `CheckpointManager` — creates/rollbacks checkpoints every N tokens
   - `SelfHealingEngine.diagnose(component_health)` → heal actions
   - Actions: merge, remove, replace, optimize, escalate

8. **forge_system_registry.py** — System Registry
   - `SystemNode`: id, type, capabilities, inputs, outputs, reliability, cost, latency
   - `SystemEdge`: source, target, type (dependency/data_flow/control_flow)
   - `Capability`: name, providers, domain
   - `SystemRegistry.scan()` — scans forge_agents/*.py, tools/registry.json, impeccable/reference/*.md
   - Auto-detects capabilities from code (kernel, mcp, memory, verify, scrape, llm, etc.)
   - Persists to 05_STATE/system_registry/{nodes,edges,capabilities}.json

9. **forge_execution_logger.py** — Execution Logger
   - `ExecutionLog`: trace_id, task, path, node_metrics, total_cost, total_tokens, input_tokens, output_tokens, cache_read, effective_tokens (ET)
   - `compute_et(model_multiplier)` — ET = input + (output×4) + (cache×0.1)
   - Persists traces to 05_STATE/logs/executions/trace-{id}.json

10. **forge_mcp_pruner.py** — MCP Pruning Engine
    - `MCPToolStats`: tool_name, schema_size_bytes, call_count, can_replace_with_cli
    - `auto_register_from_registry()` — reads tools/registry.json
    - `analyze()` → prune recommendations
    - GitHub benchmark: 62% ET reduction through MCP pruning
    - Persists to 05_STATE/mcp_pruning_report.json

11. **forge_no_mistakes.py** — Quality Gate
    - Integrates https://github.com/kunchenguid/no-mistakes (1.5k stars, MIT)
    - Pipeline: review → test → docs → lint → push → PR → CI
    - `EVIDENCE_PATTERNS` — 30 validation rules across 5 categories
    - `ForgeQualityGate.validate_code(files)` → findings
    - Auto-fix mechanical issues, escalate human judgment
    - Persists evidence to 05_STATE/evidence/

### 3.5 Supporting Modules

These are needed by the graph but not V6-specific. Build from the inventory:

- `forge_llm.py` — LLM router (Tier 0=free → Tier 3=Opus). `forge_call()`, `forge_score()`, `forge_summarize()`
- `forge_db.py` — PostgreSQL+Redis store with SQLite fallback
- `nanomachine.py` — NMP inter-agent protocol (ACTION|SOURCE|TARGET|PAYLOAD)
- `agent_nodes.py` — All graph node implementations
- `auto_complexification.py` — Level up/rollback routing logic
- `graphify_checkpointer.py` — Redirects to nexus_bridge
- `token_tracker.py` — Token accounting
- `prompt_architect.py` — Prompt optimization
- `turbovec_brain.py` — 4-bit semantic brain
- `cervelet.py` — Reflexes (0 LLM tokens) + homeostasis
- `agency_personas.py` — Role-based personas
- `harness_engine.py` — Quality gates (CODE, WEBSITE, VIDEO, BOT, EMAIL, API)
- `ponytail.py` — YAGNI layer (6-step ladder)

### 3.6 Visualizer

- `forge_visualizer.py` — HTTP server serving dashboard + 12 API endpoints
- `forge_dashboard.html` — 7-tab dashboard (Linear-style dark theme)

---

## 4. Tools Registry — 00_CORE/tools/registry.json

The registry uses NMP format (pipe-delimited):

```json
{
  "version": "2.0",
  "structure": {
    "tools.dev": "openhands",
    "tools.product_bricks.ai_workflows": "langflow, dify",
    "tools.product_bricks.crm": "twenty_crm",
    "tools.product_bricks.ui": "design_kb, shadcn_caller",
    "tools.product_bricks.generative_media": "open_gen_ai, opencut, hyperframes",
    "tools.mcp": "mcpify, metorial, repowise",
    "tools.automation": "browser_use",
    "tools.outreach": "whatsapp_agent, snapchat_ads",
    "tools.money": "cashclaw",
    "forge_agents.quality": "no_mistakes, harness_engine"
  },
  "tools": [
    "TOOL|id|kind|status|purpose|wrapper_path|tags",
    ...
  ]
}
```

33 tools total. Each tool is a Python wrapper in the appropriate subdirectory.

---

## 5. Config Files

### 01_ORCHESTRATOR/config.json
```json
{
  "budget_allocation": {
    "scraping": 0.40,
    "research": 0.20,
    "critic": 0.10,
    "jury": 0.15,
    "algorithm": 0.15
  },
  "thresholds": {
    "level_up_quality_gain": 0.10,
    "quality_regression_tolerance": 0.05,
    "min_cycles_before_levelup": 3,
    "finding_kill_below": 5.0
  }
}
```

---

## 6. LLM Tier Hierarchy (forge_llm.py)

```
Tier 0 (FREE):    Gemini 2.5 Flash, Groq Llama 4, Cerebras
Tier 1 (CHEAP):   DeepSeek V3, MiMo
Tier 2 (MEDIUM):  Claude Sonnet, GPT-4o
Tier 3 (PREMIUM): Claude Opus, GPT-4.5
```

Default routing: task complexity → tier selection. Simple tasks use Tier 0.

---

## 7. Verification

After building everything, verify:

```bash
# 1. All modules compile
cd /path/to/.claude
python -c "
import sys; sys.path.insert(0, '.')
from importlib import import_module
import glob, py_compile
ok = fail = 0
for f in sorted(glob.glob('00_CORE/forge_agents/forge_*.py')):
    try:
        py_compile.compile(f, doraise=True)
        ok += 1
    except Exception as e:
        print(f'FAIL: {f}: {e}')
        fail += 1
print(f'{ok} OK, {fail} FAIL')
"

# 2. System registry scans
python -c "
import sys; sys.path.insert(0, '.')
from importlib import import_module
reg = import_module('00_CORE.forge_agents.forge_system_registry')
r = reg.get_registry()
s = r.summary()
print(f'Nodes: {s[\"total_nodes\"]}, Edges: {s[\"total_edges\"]}, Caps: {s[\"total_capabilities\"]}')
"

# 3. Graph builds
python -c "
import sys; sys.path.insert(0, '.')
from importlib import import_module
fg = import_module('00_CORE.forge_agents.forge_graph')
g = fg.build_forge_graph(use_sqlite=False)
print('Graph compiled OK')
"

# 4. Dashboard works
python 00_CORE/forge_agents/forge_visualizer.py --port 8420
# Open http://localhost:8420 in browser
```

---

## 8. Architecture Summary

```
USER REQUEST
  → V6_INIT (kernel + brain + lazy + events)
  → ESTIMATE_BUDGET (token planning)
  → ORCHESTRATOR (routing)
  → DYNAMIC_AGENT (execute with shared context)
  → V6_POST_EXECUTION (meta + experience + heal + events)
  → AUTO_COMPLEXIFICATION (level up/rollback/continue/kill)
  → MEMORY_PRUNER → ORCHESTRATOR (loop)
  → POST_MORTEM → END

Shared Brain: kernel + MCP cache + reasoning state → ÷5-20x tokens
Lazy Engine: reuse > adapt > full execution
MCP Pruner: -62% ET (GitHub benchmark)
Quality Gate: no-mistakes pipeline (review→test→docs→lint→push→PR→CI)
Meta Layer: confidence/uncertainty/risk/reward/curiosity → auto-optimization
Experience DB: learn from every execution
Self-Healing: detect dead/degraded → merge/remove/replace/optimize
```

---

## 9. Quick Start

```python
import sys; sys.path.insert(0, '.')
from forge_agents import ForgeRunner

runner = ForgeRunner(session_id="my-session")
result = runner.run_task("build a Telegram hotel bot", max_cycles=5)
print(f"Level: {result.get('level')}, Findings: {len(result.get('findings', []))}")
```

---

## 10. Repos & References

| Repo | Purpose | Integration |
|------|---------|-------------|
| [no-mistakes](https://github.com/kunchenguid/no-mistakes) | Git quality gate | forge_no_mistakes.py |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Agent orchestration | forge_graph.py |
| [TurboVec](https://github.com/nousresearch/turbovec) | 4-bit semantic brain | turbovec_brain.py |
| [Nexus](https://github.com/nousresearch/nexus) | VFS memory layer | nexus_bridge.py |
| [Metorial](https://github.com/metorial/metorial) | MCP hub (1200+ integrations) | tools/mcp/metorial.py |
| [MCPify](https://github.com/nousresearch/mcpify) | Auto-generate MCP from CLI/API | tools/mcp/mcpify.py |

---

*Generated from Forge V6 codebase inventory — 2026-06-22*
*69 Python modules, 33 tools, 11 graph nodes, 48 state fields*
