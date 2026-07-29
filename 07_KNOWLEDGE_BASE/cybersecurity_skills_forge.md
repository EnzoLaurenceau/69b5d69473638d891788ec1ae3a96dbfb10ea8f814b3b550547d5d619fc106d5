# Anthropic Cybersecurity Skills — Forge Knowledge Document

> **Source:** `07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills/`
> **Updated:** 2026-07-19 | **Skills:** 817 | **Domains:** 29 | **Frameworks:** 6
> **License:** Apache-2.0 | **Standard:** [agentskills.io](https://agentskills.io)
> **Repo:** https://github.com/mukul975/Anthropic-Cybersecurity-Skills

---

## 1. Overview

The **Anthropic Cybersecurity Skills** library is the largest open-source cybersecurity skills
library for AI agents. It contains **817 production-grade skills** across **29 security domains**,
each following the [agentskills.io](https://agentskills.io) open standard. Every skill is mapped
to **six industry frameworks** — MITRE ATT&CK v19.1, NIST CSF 2.0, MITRE ATLAS v5.4, MITRE
D3FEND v1.3, NIST AI RMF 1.0, and MITRE Fight Fraud Framework (F3) v1.1.

This is NOT a collection of scripts or checklists. It is an **AI-native knowledge base** built
from the ground up for AI agents — YAML frontmatter for sub-second discovery, structured Markdown
for step-by-step execution, and reference files for deep technical context. Every skill encodes
real practitioner workflows.

**Community project** by @mukul975. Not affiliated with Anthropic PBC.

**Key facts:**
- 817 skills, 29 security domains, 6 framework mappings
- Compatible with 26+ AI platforms (Claude Code, Copilot, Cursor, Codex CLI, Gemini CLI, etc.)
- MITRE ATT&CK v19.1: 286 distinct techniques across 15 tactics, 754/754 skills mapped
- MITRE F3: 94 fraud-relevant skills, 123 technique IDs
- Released v1.0.0: March 11, 2026 (734 skills); main branch now has 817

---

## 2. All 29 Security Domains

| # | Domain | Skills | Key Capabilities |
|---|--------|--------|------------------|
| 1 | Cloud Security | 66 | AWS, Azure, GCP hardening · CSPM · cloud attack emulation · cloud forensics |
| 2 | Threat Hunting | 58 | Hypothesis-driven hunts · LOTL detection · EVTX hunting · fleet hunting |
| 3 | Threat Intelligence | 52 | STIX/TAXII · MISP · OpenCTI · feed integration · actor profiling |
| 4 | Network Security | 43 | IDS/IPS · firewall rules · VLAN segmentation · traffic analysis |
| 5 | Web Application Security | 42 | OWASP Top 10 · SQLi · XSS · SSRF · deserialization |
| 6 | Digital Forensics | 41 | Disk imaging · memory forensics · Hayabusa/KAPE/Plaso timelines |
| 7 | Malware Analysis | 39 | Static/dynamic analysis · reverse engineering · sandboxing |
| 8 | Identity & Access Management | 37 | Entra ID/ROADtools · device-code phishing · PAM · zero trust identity |
| 9 | SOC Operations | 35 | Playbooks · escalation workflows · Graph-log detection · tabletop exercises |
| 10 | Red Teaming | 33 | ADCS/Certipy · BloodHound CE · Sliver/Havoc C2 · NTLM relay |
| 11 | Container Security | 33 | K8s RBAC · image scanning · Falco · container escape |
| 12 | Security Operations | 28 | SIEM correlation · log analysis · alert triage |
| 13 | OT/ICS Security | 28 | Modbus · DNP3 · IEC 62443 · historian defense · SCADA |
| 14 | API Security | 28 | GraphQL · REST · OWASP API Top 10 · WAF bypass |
| 15 | Incident Response | 26 | Breach containment · ransomware response · IR playbooks |
| 16 | Vulnerability Management | 25 | Nessus · scanning workflows · patch prioritization · CVSS |
| 17 | Penetration Testing | 21 | Network · web · cloud · mobile · NetExec lateral movement |
| 18 | DevSecOps | 18 | CI/CD security · Trivy IaC/image scanning · code signing |
| 19 | Zero Trust Architecture | 17 | BeyondCorp · CISA maturity model · microsegmentation |
| 20 | Endpoint Security | 17 | EDR · LOTL detection · fileless malware · persistence hunting |
| 21 | Cryptography | 16 | TLS · Ed25519 · post-quantum migration · key management |
| 22 | Phishing Defense | 15 | Email authentication · BEC detection · phishing IR |
| 23 | AI Security | 14 | LLM red-teaming (garak/PyRIT) · prompt injection · MCP/agentic security · guardrails |
| 24 | Mobile Security | 13 | Android/iOS analysis · mobile pentesting · MDM forensics |
| 25 | Ransomware Defense | 13 | Precursor detection · response · recovery · encryption analysis |
| 26 | Compliance & Governance | 9 | NIST 800-30/RMF · CMMC · HIPAA · TPRM · CIS benchmarks |
| 27 | Supply Chain Security | 8 | SBOMs · dependency confusion · malicious-package triage · SLSA/Sigstore |
| 28 | Deception Technology | 6 | Honeytokens · canarytokens · breach detection |
| 29 | Hardware & Firmware Security | 4 | CHIPSEC/UEFI audit · Secure Boot bypass · TPM attestation · bootkit hunting |

---

## 3. The 6 Framework Mappings

### 3.1 MITRE ATT&CK v19.1

- **Scope:** 15 tactics · 286 techniques · 754/754 skills mapped
- **What it maps:** Adversary behaviors and TTPs

| Tactic | ID | Skills |
|--------|------|--------|
| Reconnaissance | TA0043 | 103 |
| Resource Development | TA0042 | 22 |
| Initial Access | TA0001 | 467 |
| Execution | TA0002 | 350 |
| Persistence | TA0003 | 444 |
| Privilege Escalation | TA0004 | 464 |
| Stealth | TA0005 | 442 |
| Defense Impairment | TA0112 | 92 |
| Credential Access | TA0006 | 202 |
| Discovery | TA0007 | 237 |
| Lateral Movement | TA0008 | 68 |
| Collection | TA0009 | 172 |
| Command and Control | TA0011 | 123 |
| Exfiltration | TA0010 | 82 |
| Impact | TA0040 | 50 |

> v19.1 restructured Defense Evasion into **Stealth** (TA0005) and **Defense Impairment** (TA0112).

### 3.2 NIST CSF 2.0

- **Scope:** 6 functions · 22 categories · 106 subcategories
- **What it maps:** Organizational security posture

| Function | Skills | Focus |
|----------|--------|-------|
| Govern (GV) | 30+ | Risk strategy, policy frameworks, roles & responsibilities |
| Identify (ID) | 120+ | Asset discovery, threat landscape assessment, risk analysis |
| Protect (PR) | 150+ | IAM hardening, WAF rules, zero trust, encryption |
| Detect (DE) | 200+ | Threat hunting, SIEM correlation, anomaly detection |
| Respond (RS) | 160+ | Incident response, forensics, breach containment |
| Recover (RC) | 40+ | Ransomware recovery, BCP, disaster recovery |

> NIST CSF 2.0 (Feb 2024) added the **Govern** function and expanded scope to all organizations.

### 3.3 MITRE ATLAS v5.4

- **Scope:** 16 tactics · 84 techniques
- **What it maps:** AI/ML adversarial threats
- Covers agentic AI attack vectors: AI agent context poisoning, tool invocation abuse,
  MCP server compromises, malicious agent deployment
- Protects ML pipelines, model weights, inference APIs, autonomous workflows

### 3.4 MITRE D3FEND v1.3

- **Scope:** 7 categories · 267 techniques
- **What it maps:** Defensive countermeasures
- Categories: Model, Harden, Detect, Isolate, Deceive, Evict, Restore
- Built on OWL 2 ontology with shared Digital Artifact layer
- Bidirectionally maps defensive countermeasures to ATT&CK offensive techniques

### 3.5 NIST AI RMF 1.0 + GenAI Profile (AI 600-1)

- **Scope:** 4 functions · 72 subcategories
- **What it maps:** AI risk management
- Functions: Govern, Map, Measure, Manage
- GenAI Profile adds 12 risk categories (confabulation, prompt injection, supply chain)
- Colorado AI Act (Feb 2026) provides legal safe harbor for NIST AI RMF compliance

### 3.6 MITRE Fight Fraud Framework (F3) v1.1

- **Scope:** 8 tactics · 123 techniques · 94 fraud-relevant skills
- **What it maps:** Cyber-enabled financial fraud TTPs
- Released April 9, 2026 by MITRE CTID (with JPMorganChase, Citigroup, CrowdStrike, etc.)
- Two fraud-specific tactics not in ATT&CK:
  - **Positioning** (FA0001) — synthetic-identity seeding, account warming, SIM-swap pre-positioning
  - **Monetization** (FA0002) — money-mule layering, APP fraud, crypto off-ramping
- Fraud techniques use `F1XXX` IDs; reused ATT&CK techniques keep `T1XXX` IDs

### Cross-Framework Example

| Skill | ATT&CK | NIST CSF | ATLAS | D3FEND | AI RMF | F3 |
|-------|--------|----------|-------|--------|--------|-----|
| `analyzing-network-traffic-of-malware` | T1071 | DE.CM | AML.T0047 | D3-NTA | MEASURE-2.6 | — |
| `detecting-business-email-compromise` | T1566 | DE.AE | — | — | — | F1005.006 |

---

## 4. The agentskills.io Standard Format

Every skill follows the [agentskills.io](https://agentskills.io) open standard.

### Directory Structure

```
skills/<skill-name>/
├── SKILL.md              ← Skill definition (YAML frontmatter + Markdown body)
├── references/
│   ├── standards.md      ← MITRE ATT&CK, ATLAS, D3FEND, NIST mappings
│   └── workflows.md      ← Deep technical procedure reference
├── scripts/
│   └── process.py        ← Working helper scripts (optional)
└── assets/
    └── template.md       ← Filled-in checklists and report templates (optional)
```

### YAML Frontmatter (~30 tokens to scan)

```yaml
---
name: performing-memory-forensics-with-volatility3
description: Analyze volatile memory dumps using Volatility 3 to extract running processes,
  network connections, loaded modules, and evidence of malicious activity.
domain: cybersecurity
subdomain: digital-forensics
tags: [forensics, memory-forensics, volatility, ram-analysis, malware-detection, incident-response]
version: '1.0'
author: mahipal
license: Apache-2.0
nist_csf: [RS.AN-01, RS.AN-03, DE.AE-02, RS.MA-01]
mitre_attack: [T1005, T1074, T1119, T1070, T1059]
---
```

**Frontmatter fields:**
- `name` — kebab-case, 1–64 chars, unique identifier
- `description` — keyword-rich for agent discovery
- `domain` — always `cybersecurity`
- `subdomain` — one of the 29 domains (e.g., `digital-forensics`, `web-application-security`)
- `tags` — freeform keywords for matching
- `version`, `author`, `license` — metadata
- `nist_csf` — NIST CSF 2.0 category references
- `mitre_attack` — MITRE ATT&CK technique IDs
- `atlas_techniques` — MITRE ATLAS IDs (optional)
- `d3fend_techniques` — MITRE D3FEND IDs (optional)
- `nist_ai_rmf` — NIST AI RMF references (optional)
- `mitre_f3` — MITRE F3 technique IDs (optional)

### Markdown Body (500–2000 tokens to fully load)

```markdown
## When to Use
Trigger conditions — when should an AI agent activate this skill?

## Prerequisites
Required tools, access levels, and environment setup.

## Workflow
Step-by-step execution guide with specific commands and decision points.

## Verification
How to confirm the skill was executed successfully.
```

### Progressive Disclosure Architecture

- **~30 tokens** to scan frontmatter (all 817 skills = ~24,500 tokens — fits in one pass)
- **500–2,000 tokens** to fully load a single skill's workflow
- Agents scan all frontmatters → identify relevant skills → load only the top matches

---

## 5. Top 10 Most Useful Skills for Web Development Security

These skills are most directly applicable to developers building and securing web applications:

| # | Skill | Subdomain | Why It Matters |
|---|-------|-----------|----------------|
| 1 | `exploiting-sql-injection-vulnerabilities` | penetration-testing | OWASP A03 — understand SQLi attack vectors (error-based, union, blind, time-based) across all major DB engines |
| 2 | `detecting-sql-injection-via-waf-logs` | web-application-security | Learn to detect SQLi attempts in WAF logs for defense |
| 3 | `exploiting-nosql-injection-vulnerabilities` | penetration-testing | MongoDB, CouchDB injection — critical for modern JS backends |
| 4 | `exploiting-template-injection-vulnerabilities` | penetration-testing | Server-Side Template Injection (SSTI) in Jinja2, Twig, Freemarker |
| 5 | `performing-csrf-attack-simulation` | web-application-security | Validate CSRF protections in forms and APIs |
| 6 | `performing-blind-ssrf-exploitation` | web-application-security | Server-Side Request Forgery — OWASP Top 10 critical |
| 7 | `exploiting-websocket-vulnerabilities` | penetration-testing | Real-time app security — WebSocket hijacking, message injection |
| 8 | `implementing-cloud-waf-rules` | cloud-security | Deploy and tune WAF rules for AWS WAF, Cloudflare, Azure Front Door |
| 9 | `conducting-api-security-testing` | api-security | OWASP API Top 10 — test REST/GraphQL endpoints for auth, injection, rate limiting |
| 10 | `integrating-dast-with-owasp-zap-in-pipeline` | devsecops | Automated security scanning in CI/CD with OWASP ZAP |

**Also worth loading for web devs:**
- `exploiting-sql-injection-with-sqlmap` — automated SQLi exploitation
- `performing-soap-web-service-security-testing` — legacy API security
- `implementing-web-application-logging-with-modsecurity` — ModSecurity WAF setup
- `performing-api-security-testing-with-postman` — API testing workflows
- `implementing-api-security-posture-management` — continuous API security

---

## 6. How to Use These Skills with Hermes Agent

### 6.1 Direct File Reference (Current Method)

The skills are cloned at:
```
C:/Users/Enzo/Documents/MODELS/.claude/07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills/
```

When a security-related task arises, load the relevant SKILL.md:

```
# Example: Agent needs to do memory forensics
read_file("C:/Users/Enzo/Documents/MODELS/.claude/07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills/skills/performing-memory-forensics-with-volatility3/SKILL.md")
```

### 6.2 Skill Discovery Workflow

1. **Scan frontmatters** — Read the first 28 lines (YAML block) of each SKILL.md to match
   `tags`, `subdomain`, and `description` against the user's request
2. **Load top matches** — Read the full SKILL.md (500–2000 tokens) for the 1–3 best matches
3. **Execute workflow** — Follow the step-by-step Workflow section
4. **Verify results** — Use the Verification section to confirm success

### 6.3 Quick Domain Lookup

To find skills for a specific domain, list the directory:
```bash
ls skills/ | grep <keyword>
```

Domain keywords: `cloud`, `forensic`, `malware`, `web`, `api`, `container`, `kubernetes`,
`phishing`, `ransomware`, `incident`, `vulnerability`, `red-team`, `soc`, `zero-trust`,
`endpoint`, `crypto`, `mobile`, `supply-chain`, `deception`, `hardware`, `ot`, `ics`, `ai`

### 6.4 Hermes Skill Integration Pattern

To create a Hermes-compatible skill that wraps a cybersecurity skill:

```markdown
# In ~/.hermes/profiles/default/skills/cybersecurity-forensics/SKILL.md

---
name: cybersecurity-forensics
description: Digital forensics and incident response capabilities
---

When the user asks about forensic analysis, memory dumps, disk imaging, or incident response,
load the relevant skill from:
C:/Users/Enzo/Documents/MODELS/.claude/07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills/skills/

Key skills to consider:
- performing-memory-forensics-with-volatility3
- analyzing-disk-image-with-autopsy
- acquiring-disk-image-with-dd-and-dcfldd
- analyzing-windows-event-logs-for-credential-access
```

---

## 7. Key Patterns

### 7.1 Progressive Disclosure

The library is designed for efficient agent consumption:

```
All 817 frontmatters scanned  →  ~24,500 tokens (one pass)
Identify top 3 matches        →  3 × ~1,500 tokens = ~4,500 tokens
Execute one skill fully       →  ~1,500 tokens
Total agent overhead          →  ~30,500 tokens for full discovery + execution
```

Without progressive disclosure, loading all 817 skills fully would require
~1.2 million tokens — impossible in any context window.

### 7.2 Step-by-Step Workflows

Every skill follows this structure:

1. **When to Use** — Trigger conditions and scope limits
2. **Prerequisites** — Tools, access, environment requirements
3. **Workflow** — Numbered steps with specific commands, decision points, and expected outputs
4. **Verification** — How to confirm success (IOC checks, log verification, framework mapping)

The Workflow section is the core value — it encodes the exact sequence a senior analyst would
follow, including tool-specific commands, flag options, and interpretation guidance.

### 7.3 Reference Files Structure

Each skill directory may contain:

- `references/standards.md` — Framework mappings (ATT&CK, ATLAS, D3FEND, NIST CSF, AI RMF, F3)
- `references/workflows.md` — Deep technical procedure reference beyond the main workflow
- `scripts/` — Working helper scripts (Python, Bash) that automate parts of the workflow
- `assets/` — Report templates, checklists, IOC templates

The reference files provide depth without bloating the main SKILL.md — agents only load them
when the main workflow requires deeper context.

### 7.4 Cross-Framework Mapping Pattern

A single skill can map to all 6 frameworks simultaneously, enabling:
- Compliance reporting (NIST CSF, AI RMF)
- Threat correlation (ATT&CK, ATLAS)
- Countermeasure recommendation (D3FEND)
- Fraud detection (F3)

This is unique to this library — no other open-source skills library provides unified
cross-framework coverage.

---

## Appendix: Quick Reference

**Repo location:** `C:/Users/Enzo/Documents/MODELS/.claude/07_KNOWLEDGE_BASE/Anthropic-Cybersecurity-Skills/`
**Skills directory:** `skills/<skill-name>/SKILL.md`
**Total skills:** 817
**Total domains:** 29
**Total frameworks:** 6
**Standard:** agentskills.io
**License:** Apache-2.0
**Platforms:** 26+ (Claude Code, Copilot, Cursor, Codex CLI, Gemini CLI, etc.)
