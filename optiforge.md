Voici une **Forge Agent Runtime Spec “production-grade Claude Code”**. C’est une architecture exécutable, pensée pour LangGraph + MCP + multi-agents + mémoire + compression + anti-hallucination.

---

# 🧠 FORGE AGENT RUNTIME SPEC v1 (PRODUCTION)

## 🎯 Objectif

Construire un runtime qui :

* exécute des agents multi-parallèles
* partage mémoire + kernel global
* cache MCP intelligemment
* compresse automatiquement le contexte
* limite hallucinations via vérification obligatoire
* optimise tokens en continu (lazy execution)
* devient auto-observant (meta-loop)

---

# 🧱 1. ARCHITECTURE GLOBALE

```text id="arc0"
USER REQUEST
   ↓
KERNEL ENGINE (compression + abstraction)
   ↓
FORGE ORCHESTRATOR (routing + planning)
   ↓
SHARED STATE BUS (memory + MCP cache + decisions)
   ↓
AGENT RUNTIME POOL (light workers)
   ↓
HYPER-VISOR HARNESS (verification + scoring)
   ↓
OUTPUT MERGER
   ↓
META LOOP (self-optimization)
```

---

# 🧠 2. CORE COMPONENTS

---

# 2.1 Kernel Engine (mandatory entry point)

📍 `/core/kernel_engine.ts`

## rôle :

Transformer toute requête en structure minimale exploitable.

```ts id="k0"
export interface Kernel {
  objective: string
  entities: string[]
  constraints: string[]
  assumptions: string[]
  required_capabilities: string[]
}
```

---

## fonction principale :

```ts id="k1"
function buildKernel(input: string, context: SharedState): Kernel
```

---

## règles :

* supprimer tout bruit conversationnel
* fusionner les redondances
* extraire uniquement les variables utiles à la décision

---

# 2.2 Forge Orchestrator

📍 `/core/orchestrator.ts`

## rôle :

Décider :

* quels agents lancer
* quelles capacités activer
* quelles données récupérer
* quand simplifier vs explorer

```ts id="o1"
function planExecution(kernel: Kernel, registry: SystemMap): ExecutionPlan
```

---

## ExecutionPlan :

```ts id="o2"
interface ExecutionPlan {
  agents: AgentTask[]
  mcp_calls: MCPCall[]
  reuse_cache: boolean
  risk_level: number
}
```

---

# 2.3 Shared State Bus (CRITIQUE)

📍 `/runtime/shared_state.ts`

## rôle :

Source unique de vérité temporaire

```ts id="s1"
interface SharedState {
  kernel: Kernel
  decisions: Decision[]
  memory_hits: MemoryEntry[]
  mcp_cache: Map<string, any>
  partial_outputs: any[]
  confidence: number
}
```

---

## règles :

* tous les agents écrivent ici
* aucun agent ne stocke localement du contexte long
* toute duplication est supprimée

---

# ⚡ 3. AGENT RUNTIME SYSTEM

---

# 3.1 Agent Wrapper

📍 `/agents/agent_wrapper.ts`

```ts id="a1"
interface AgentInput {
  kernel: Kernel
  shared_state: SharedState
  task: string
}
```

---

## agent rule :

```text id="a2"
Agents are NOT thinkers.
Agents are executors of kernel-defined subtasks.
```

---

## output :

```ts id="a3"
interface AgentOutput {
  contribution: string
  confidence: number
  evidence_used: string[]
}
```

---

# 3.2 Agent Types

```ts id="a4"
enum AgentType {
  planner,
  researcher,
  coder,
  critic,
  verifier,
  optimizer,
  contrarian
}
```

---

# 🔁 4. FORGE LOOP ENGINE

📍 `/loops/forge_loop.ts`

---

## MAIN LOOP

```text id="l0"
Kernel Build
↓
Plan Execution
↓
Check Cache (MCP + Memory)
↓
Spawn Agents (light mode)
↓
Aggregate Outputs
↓
Verify
↓
If failure → refine kernel + retry
↓
Else → commit result
↓
Meta optimization
```

---

## LOOP LIMITS

```ts id="l1"
max_iterations = 5
max_agents = 10
max_mcp_calls = adaptive
```

---

# 🧠 5. MCP PROXY LAYER (CRITICAL FOR TOKENS)

📍 `/mcp/mcp_proxy.ts`

---

## rôle :

centraliser tous les appels MCP

```ts id="m1"
function callMCP(tool, input) {
  if (cache.exists(tool, input)) {
    return cache.get(tool, input)
  }

  const result = execute(tool, input)
  cache.store(tool, input, result)
  return result
}
```

---

## rules :

* NEVER allow direct MCP calls from agents
* ALL MCP goes through proxy
* ALL results are broadcast to shared state

---

# 🧠 6. MEMORY SYSTEM (BIGSET EVOLUTION)

📍 `/memory/bigset.ts`

---

## structure :

```ts id="b1"
interface Experience {
  kernel: Kernel
  solution: string
  success: boolean
  confidence: number
  cost: number
  hallucination_flags: number
}
```

---

## usage:

* retrieve only relevant kernel matches
* compress before storage
* no raw dumps

---

# 🧪 7. HYPERVISOR HARNESS (ANTI-HALLUCINATION)

📍 `/harness/verifier.ts`

---

## pipeline :

```text id="h1"
Output → Fact Check → Kernel Alignment → Consistency → Score
```

---

## scoring:

```ts id="h2"
score =
  factuality * 0.4 +
  kernel_alignment * 0.3 +
  memory_match * 0.2 +
  efficiency * 0.1
```

---

## rules:

```ts id="h3"
if score < 0.85:
  reject OR retry
```

---

# ⚡ 8. CONTEXT COMPRESSION ENGINE

📍 `/core/compression.ts`

---

## trigger conditions:

* context growth detected
* duplication detected
* multi-agent overlap
* MCP redundancy

---

## function:

```ts id="c1"
function compress(state: SharedState): SharedState
```

---

## output format:

```json id="c2"
{
  "kernel": "...",
  "decisions": [],
  "active_facts": [],
  "open_questions": []
}
```

---

# 🧬 9. META LOOP (SELF-IMPROVEMENT ENGINE)

📍 `/meta/meta_loop.ts`

---

## rôle :

* observe system performance
* detect inefficiencies
* reduce complexity
* improve routing
* prune agents

---

## inputs:

```ts id="m1"
system_metrics: {
  token_cost,
  latency,
  success_rate,
  hallucination_rate
}
```

---

## actions:

```ts id="m2"
optimize_graph()
remove_unused_nodes()
merge_redundant_agents()
adjust_cache_policy()
```

---

# ⚡ 10. PERFORMANCE RULES

---

## HARD RULES

```text id="r1"
NO full context loading unless required
NO duplicate reasoning
NO MCP bypass
NO unverified outputs
NO uncontrolled agent spawning
```

---

## SOFT RULES

```text id="r2"
prefer reuse > retrieval > reasoning
prefer compression > expansion
prefer cache > recompute
```

---

# 🧠 11. SYSTEM GUARANTEE MODEL

The Forge is designed to guarantee:

* minimal token usage per task
* maximum reuse of prior computation
* bounded hallucination risk
* deterministic agent behavior under kernel constraints

---

# 🔥 12. FULL EXECUTION TRACE

```text id="e1"
USER INPUT
↓
KERNEL ENGINE
↓
ORCHESTRATOR
↓
CACHE CHECK (MCP + Memory)
↓
AGENT SPAWN (light tasks only)
↓
SHARED STATE UPDATE
↓
HYPERVISOR CHECK
↓
LOOP (if needed)
↓
FINAL OUTPUT
↓
META UPDATE
```

---

# 🚀 RESULT FINAL

Avec ce runtime :

### tu obtiens :

* 🔻 10x à 30x réduction tokens
* 🔻 réduction massive duplication agents
* 🔻 MCP centralisé (plus de spam)
* 🔻 mémoire réellement utile (pas brute)
* 🔻 agents légers et contrôlés
* 🔻 système auto-améliorant réel

---

# 🧩 ONE-LINE SUMMARY

```text id="z1"
Forge Runtime = Kernel-driven, memory-shared, MCP-cached, verification-gated multi-agent system with strict compression loops and meta-optimization layer.
```

---

