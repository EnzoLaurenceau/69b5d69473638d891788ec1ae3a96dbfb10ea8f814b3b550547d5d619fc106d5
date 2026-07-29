# AGENTS.md — 01_ORCHESTRATOR

## Purpose
L1 orchestrator configuration and run history: active orchestrator params, per-cycle caveman logs, reusable prompt templates, plus the e-commerce (ECOM_ORCHESTRATOR.md) and MVP Factory (MVP_FACTORY_CLAUDE.md) flow specs.

## Ownership
Owns: config.json, ECOM_ORCHESTRATOR.md, MVP_FACTORY_CLAUDE.md, cycles/, prompts/.

## Local Contracts
- `config.json` is read by `orchestrator_node` at init — changes apply to every cycle immediately.
- `cycles/` is append-only run history; prune only via `memory_pruner_node`, never by hand-deleting individual entries.
- `ECOM_ORCHESTRATOR.md` defines BOOT CHECK → MARKET SCAN → PRODUCT HUNT → BUILD → LAUNCH (target 600€/mois) — keep in sync with routing in `00_CORE/forge_agents/agent_nodes.py` if the flow changes.

## Work Guidance
(aucune norme spécifique au-delà de CLAUDE.md)

## Verification
(aucun framework de vérification dédié)

## Child DOX Index
(none)
