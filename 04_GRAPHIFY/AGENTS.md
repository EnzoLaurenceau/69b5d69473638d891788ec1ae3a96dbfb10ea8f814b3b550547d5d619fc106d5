# AGENTS.md — 04_GRAPHIFY

## Purpose
L0 collective memory: Graphify's source of truth (graph.json), generated wiki articles, SHA256 anti-reprocessing cache, and the LangGraph SQLite checkpoint DB.

## Ownership
Owns: graph.json, GRAPH_REPORT.md, wiki/, cache/, forge_checkpoints.db (+ -shm/-wal).

## Local Contracts
- `graph.json` is the SOURCE OF TRUTH (règle d'or #2 — jamais de raw output direct). All writes go through `graphify_index()`/`sync_findings_to_graphify()` (00_CORE/forge_agents/graphify_checkpointer.py), batched via `tool_batcher`.
- `forge_checkpoints.db*` is LangGraph's SqliteSaver state for `ForgeRunner` — never hand-edit; delete only with explicit user confirmation (resets all session history).
- `cache/` keys are SHA256 of processed content, used to skip reprocessing — safe to clear to force a full reprocess.
- `wiki/` articles are generated summaries — regenerate via Graphify rather than hand-editing.

## Work Guidance
- `graphify_index`/`graphify_query` fall back to direct `graph.json` read/write if the `graphify` CLI is unavailable — keep both paths schema-compatible.

## Verification
- `graphify . --update --mode deep` repairs a corrupted graph (CLAUDE.md "Urgences").

## Child DOX Index
(none)
