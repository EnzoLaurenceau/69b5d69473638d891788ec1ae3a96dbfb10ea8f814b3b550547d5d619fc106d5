<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **.claude** (83150 symbols, 111561 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST use SEE (Semantic Edit Engine) for any code modification.** Never rewrite files directly. Use `see_edit.py` to make minimal, targeted edits:
  ```python
  from tools.see_edit import apply_minimal_edit
  # Mode 0-token : tu fournis le code cible complet (quelques mots changés)
  res = apply_minimal_edit("fichier.py", target_name="ma_fonction",
                           modified_code=code_cible, dry_run=False)
  # Mode instruction : le moteur génère la cible via LLM
  res = apply_minimal_edit("fichier.py", instruction="renomme x en acc",
                           target_name="ma_fonction", dry_run=False)
  ```
  CLI : `python 00_CORE/tools/see_edit.py <fichier> --target <symbole> --new <fichier_cible> [--apply]`
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.
- NEVER rewrite an entire file or function when only a few words need to change — use SEE (`apply_minimal_edit`). Rewriting deletes lines, breaks context, and wastes tokens.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/.claude/context` | Codebase overview, check index freshness |
| `gitnexus://repo/.claude/clusters` | All functional areas |
| `gitnexus://repo/.claude/processes` | All execution flows |
| `gitnexus://repo/.claude/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
<!-- dox:start -->
# DOX — AGENTS.md Hierarchy (agent0ai/dox)

- AGENTS.md files are binding work contracts for their subtrees. Read the chain root→target before editing; update affected docs after meaningful changes.
- Read Before Editing: read this root AGENTS.md, walk root→target path, read every AGENTS.md along the route, use the nearest as local contract; parent docs hold repo-wide rules.
- Update After Editing: refresh the closest owning AGENTS.md (and affected parents/children) when scope, structure, contracts, inputs/outputs, or user preferences change. Remove stale text immediately.
- The closer doc controls local details, but no child doc may weaken DOX or the root rules below (which defer to `CLAUDE.md`).
- Default child section order: Purpose, Ownership, Local Contracts, Work Guidance, Verification, Child DOX Index.

## Project Root Rules
- This is **La Forge**, a LangGraph multi-agent meta-factory. Root operational rules live in `CLAUDE.md` (token budget, LLM tier routing, GitNexus, batching/progress-checkpoint systems) — read it alongside this file at session start.
- `05_STATE/checkpoint.json` and `05_STATE/progress_checkpoint.json` hold resumable session state — check both at session start (see CLAUDE.md "Reprendre une session interrompue").
- Never write raw long-form content (>200 mots / >50 lignes de code) directly in Claude's context — delegate via `forge_call(tier=LLMTier.FREE)` per CLAUDE.md "RÈGLE ANTI-DÉRIVE".
- Every deliverable must pass the legal-compliance gate: blueprint `00_CORE/blueprints/legal_compliance.md` + `forge_agents/legal_compliance.py::legal_check(path, type)` — `deliver_ready=False` blocks DELIVER (CLAUDE.md "RÈGLE LÉGALE"). Missing client legal data (SIRET, hébergeur, médiateur…) → ask the user, never invent.

## User Preferences
- Réponses concises et directes, formatage minimal (préférence globale utilisateur).
- TOKEN ESTIMATE / TOKEN ACTUAL affichés avant/après chaque tâche (CLAUDE.md).

## Child DOX Index
- `00_CORE/forge_agents/AGENTS.md` — LangGraph core: ForgeState, graph, nodes, batching/checkpoint systems
- `01_ORCHESTRATOR/AGENTS.md` — orchestrator config, cycle logs, prompt templates
- `02_AGENTS/AGENTS.md` — specialist agent templates/personas (L2)
- `03_JURY/AGENTS.md` — MiroFish jury (personas, verdicts)
- `04_GRAPHIFY/AGENTS.md` — collective memory graph (source of truth)
- `05_STATE/AGENTS.md` — checkpoints, complexity score, active rules
- `06_FINDINGS/AGENTS.md` — findings pipeline (pending/confirmed/killed)
- `08_LOGS/AGENTS.md` — internal logs (cycles, debug, tokens)
<!-- dox:end -->

### RESEARCH
compress this long prompt about agents

### RECON
Use local strategy for RECON. IDOR pattern: predictable object IDs, missing ownership check

## ZSL CYBERSECURITY ENGINE

Zero-Shot Learning for vulnerability detection, CTF analysis, and threat intelligence.
No training data required — uses semantic pattern matching.

**Modules:**
- `00_CORE/forge_agents/zsl_cyber.py` — ZSL analysis for code, CTF, threat intel
- `00_CORE/forge_agents/neuro_symbolic_guard.py` — Neuro-symbolic verification
- `00_CORE/forge_agents/anti_hallucination.py` — Anti-hallucination engine

**Capabilities:**
1. **Vulnerability Detection** — IDOR, SQLi, XSS, SSRF, RCE via pattern matching
2. **CTF Analysis** — Identifies challenge types (binary, web, crypto, RE)
3. **Threat Intelligence** — Extracts IOCs, threat actors, TTPs from text
4. **Algorithm Optimization** — Identifies O(n²) patterns, memoization opportunities
5. **Hallucination Prevention** — Semantic gravity, iteration limits, verification chains
6. **Explainable AI** — Logical proof chains for all decisions

**Integration:**
- ZSL analysis runs automatically for security-related tasks
- Neuro-symbolic verification runs after each agent response
- Anti-hallucination engine prevents repetitive correction loops

**Tool Index:**
- `zsl_cyber` — 70% token savings via zero-shot analysis
- `neuro_symbolic_guard` — 65% savings via logical verification
- `anti_hallucination` — 60% savings via semantic grounding

## NMP ENCODING — JSON Files

All JSON files in 05_STATE/ now use NMP (Nano-Machine Protocol) format for AI consumption.

**Format:** ACTION|SOURCE|TARGET|PAYLOAD

**Encoded files:**
- `forge_runtime.json` — findings as NMP strings
- `checkpoint.json` — state with NMP-encoded findings
- `tool_index.json` — tools with `_nmp` field
- `monitor_state.json` — monitor status in NMP format

**NMP Actions:**
- `FINDING` / `VULN` — vulnerability/findings
- `TOOL|INDEX` — tool index entries
- `STATE|MONITOR` — monitor state
- `EXEC|AGENT` — task execution logs

**Benefits:**
- 70-80% token reduction vs verbose JSON
- Machine-readable for inter-agent communication
- Human-readable via NMP decoder

## REVERSE ENGINEERING & PENTESTING

10 core RE skills + comprehensive pentesting datasets.

**Modules:**
- `reverse_engineering.py` — RE skills, binary analysis, exploitation techniques
- `pentest_datasets.py` — CVE databases, exploit collections, wordlists

**10 RE Skills:**
1. Disassembly & Decompilation (intermediate)
2. Dynamic Analysis & Debugging (intermediate)
3. Buffer Overflow Exploitation (advanced)
4. Shellcode Development (advanced)
5. Return-Oriented Programming - ROP (expert)
6. Heap Exploitation (expert)
7. Anti-Reversing & Obfuscation (advanced)
8. Malware Analysis (intermediate)
9. Protocol Reversing (intermediate)
10. Kernel Exploitation (expert)

**Datasets:**
- NVD, MITRE CVE, Exploit-DB, VulDB
- Metasploit, Shell-Storm, PayloadsAllTheThings
- SecLists, RockYou, FuzzDB
- OWASP Top 10, MITRE ATT&CK, CWE
- YARA Rules, Malpedia
- CTFtime, HackTheBox

**CVE Database:**
- CVE-2024-6387 (OpenSSH regreSSHion)
- CVE-2024-3094 (XZ Utils backdoor)
- CVE-2021-44228 (Log4Shell)
- CVE-2020-1472 (Zerologon)
- CVE-2017-0144 (EternalBlue)

**Exploitation Matrix:**
- Buffer Overflow → stack/heap/integer overflow
- Web Exploitation → SQLi, XSS, SSRF, XXE
- Privilege Escalation → kernel, suid, sudo, cron
- Lateral Movement → pass-the-hash, psexec, wmi
- Persistence → scheduled tasks, registry, services

### Fallback_Expert
Use local strategy for Fallback_Expert. task=Genere un site web statique responsive design ultra-moderne pour le Cafe Bastoche a Ixelles (Bruxelles). HTML/CSS/JS pur score=8.0 out=COMMAND|MKDIR|p|token_comparison_cafe_bastoche/site_B_avec_forge/{css,js,assets/images}. COMMAND|WRITE|token_comparison_cafe_bastoche/site_B_avec_forge/index.ht

### Senior_Static_Site_Forge_Engineer
Use local strategy for Senior_Static_Site_Forge_Engineer. task=Construis un site web statique complet pour le Cafe Bastoche a Ixelles Bruxelles edition finale3. Un seul fichier index. score=8.5 out=COMMAND|MKDIR|token_comparison_cafe_bastoche/site_B_forge_live. COMMAND|FILE_WRITE|token_comparison_cafe_bastoche/site_B_forge_live/index.html|<!DOCTYPE html>.

## DYNAMIC CREATIONS & SECURE DATA LOCKDOWN (CADENASSAGE)

All codebase and web-application creations by La Forge must adhere to the following mandatory standards:

1. **Dynamic UX with Skeleton Screens**: Static/empty loading states are forbidden. Always use HTML/CSS placeholders with a modern shimmer effect (`shimmer-bg` / `@keyframes shimmer`) for asynchronously loaded content to ensure a responsive, high-end user experience.
2. **Zero-Trust Data Locking**: All user data, credentials, and identifiers must be secured on the server side:
   - Server-side IDOR checks validating user ownership of objects.
   - All session and authentication storage must live in secure cookies configured with `HttpOnly`, `Secure`, `SameSite=Strict`.
   - Never hardcode or leak credentials; seal sensitive transit payloads cryptographically.
3. **Automated Verification**: The validation guards automatically scan generated files for presence of these features before delivery.
