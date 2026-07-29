# AGENTS.md — 06_FINDINGS

## Purpose
Triaged output of agent findings, sorted by jury verdict.

## Ownership
Owns: FINDING_TEMPLATE.json, confirmed/, pending/, killed/.

## Local Contracts
- New findings start in `pending/`, matching `FINDING_TEMPLATE.json` (mirrors the `Finding` TypedDict in forge_state.py).
- Jury consensus ≥ 0.7 → `confirmed/` (also indexed into Graphify via `sync_findings_to_graphify`); Critic score < 5 → `killed/` (archived, not deleted).
- `killed/` is kept for audit — never permanently delete.

## Work Guidance
- Follow the pending → confirmed/killed flow driven by the MiroFish jury; do not move findings manually outside that flow.

## Verification
(la décision du jury constitue la vérification)

## Child DOX Index
(none)
