# AGENTS.md — 03_JURY

## Purpose
L3 MiroFish jury configuration: persona definitions, round/consensus parameters, per-cycle verdict history.

## Ownership
Owns: personas.json, config.json, verdicts/.

## Local Contracts
- `personas.json` defines the 5-7 jury personas (incl. Slop_Detector, weight 0.8 per CLAUDE.md deslop integration) — consumed by `mirofish.py`.
- `config.json` sets rounds and `consensus_min`/`KILL_BELOW` — changes affect `auto_complexification_node` rollback/level-up decisions.
- `verdicts/` is append-only, one entry per cycle; do not edit past verdicts.
- Herald security grade (when AsyncHerald runs) is injected as extra jury context per CLAUDE.md "Intégration MiroFish ← Herald" — thresholds live there, not here.

## Work Guidance
- Threshold changes that alter global policy must also be reflected in CLAUDE.md.

## Verification
(le jury lui-même constitue la vérification)

## Child DOX Index
(none)
