# AGENTS.md — 02_AGENTS

## Purpose
L2 specialist agent definitions: per-role instructions/templates available to `dynamic_agent_node` when the orchestrator spawns an agent for a sub-task.

## Ownership
Owns: AGENT_UNIVERSAL_TEMPLATE.md, SCRAPING_PROTOCOL.md, and per-role folders (audit_agent/, closer_pro/, critic/, founder_ceo/, legal_officer/, marketing_digital/, prompt_engineer/, research/, scraper/, senior_dev/).

## Local Contracts
- `AGENT_UNIVERSAL_TEMPLATE.md` is the base structure for every per-role prompt; `prompt_architect.py` (00_CORE/forge_agents) generates dynamic agents from this shape.
- `SCRAPING_PROTOCOL.md` is binding for any agent doing web scraping (scraper/, research/, marketing_digital/) — rate limits and source rules defined there.
- Per-role folders may go stale as `prompt_architect` increasingly generates agents on the fly — check currency (e.g. `marketing_digital/tiktok_scripts_v1.md`) before reuse.

## Work Guidance
- New static roles should follow `AGENT_UNIVERSAL_TEMPLATE.md`.

## Verification
(aucun framework de vérification dédié)

## Child DOX Index
(none — create a child AGENTS.md for a role folder only if it grows its own durable workflow)
