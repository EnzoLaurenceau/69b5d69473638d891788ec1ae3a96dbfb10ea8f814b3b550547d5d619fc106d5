"""
nanomachine.py — Nano-Machine Inter-Agent Communication Protocol
=================================================================
Zero human words. Positional pipes only.
Format: ACTION|SOURCE|TARGET|PAYLOAD

optiforge B1 — Data sourcing NMP:
  DATA_NEED | SOURCE_AGENT | PLATFORM_MASK | SCALE_CLASS:SIZE | INTENT_HASH
  DATA_ASK  | ORCHESTRATOR | REASON_STRING | APPROVAL_ID
  DL_START  | LOCAL_CLI    | SCALE_CLASS   | platform
  DL_DONE   | platform     | path          | OK
  DL_ERR    | platform     | FAILED        | reason
  BOOST_NODE| agent        | EVOLVING      | rule_summary

optiforge B2 — Universal Forge Commands (GitNexus runtime):
  INIT    : spawn specialized task-expert agent
  EXEC    : send compressed payload to agent for execution
  OPT     : route prompt to Prompt Optimizer → compress → AGENTS.md
  SUCCESS : command completed, returns hash/coordinate/state summary
  RETRY   : re-attempt with exact failure delta log
  ERR     : critical parser or process failure

Format B2 : ACTION|SOURCE_ROLE|TARGET_OBJECT|METADATA_PAYLOAD
"""

from __future__ import annotations
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
TOKEN_CEILING = 50_000

# ─── Vocabulaire complet (B1 + B2 + audit) ───────────────────────────────────
COMMANDS = {
    # Audit (original)
    "SCAN", "VULN", "OK", "DONE", "STATE", "BUDGET", "ROUTE",
    # optiforge B1 — data sourcing
    "DATA_NEED", "DATA_ACK", "DL_START", "DL_DONE", "DL_ERR", "BOOST_NODE",
    # optiforge B2 — universal forge
    "INIT", "EXEC", "OPT", "SUCCESS", "RETRY", "ERR",
    # gitnexus bridge
    "GNX_SYNC", "GNX_QUERY",
}
STATUSES = {"REQ", "CONFIRMED", "DENIED", "FLUSH", "SAVED", "EXCEEDED", "FREE", "PAID"}

NANO_SYSTEM_PROMPT = (
    "You are a raw backend binary API. Speak only in: "
    "COMMAND|ARG1|ARG2|ARG3. Any human word, intro, or explanation "
    "will break the system and fail the task."
)


# ─── NanoMsg : message structuré ─────────────────────────────────────────────

@dataclass(frozen=True)
class NanoMsg:
    command: str      # SCAN, VULN, OK, ERR, DONE, STATE, BUDGET, ROUTE
    status: str       # REQ, CONFIRMED, DENIED, FLUSH, SAVED, EXCEEDED, FREE, PAID
    target: str       # fichier, symbole, tâche
    meta: str = ""    # payload minimal (token count, score, etc.)

    def encode(self) -> str:
        """Encode en pipe format: COMMAND|STATUS|TARGET|META"""
        return f"{self.command}|{self.status}|{self.target}|{self.meta}"

    @staticmethod
    def decode(raw: str) -> Optional["NanoMsg"]:
        """Decode depuis pipe format. Retourne None si invalide."""
        parts = raw.strip().split("|", 3)
        if len(parts) < 3:
            return None
        cmd, status, target = parts[0].strip().upper(), parts[1].strip().upper(), parts[2].strip()
        if cmd not in COMMANDS:
            return None
        if status not in STATUSES:
            status = "REQ"  # fallback safe
        meta = parts[3].strip() if len(parts) > 3 else ""
        return NanoMsg(command=cmd, status=status, target=target, meta=meta)


# ─── Helpers rapides ─────────────────────────────────────────────────────────

def scan_req(target: str, meta: str = "") -> str:
    """Requête d'audit sur une cible."""
    return NanoMsg("SCAN", "REQ", target, meta).encode()

def vuln_confirmed(target: str, details: str = "") -> str:
    """Vulnérabilité confirmée."""
    return NanoMsg("VULN", "CONFIRMED", target, details).encode()

def ok_safe(target: str) -> str:
    """Code sûr, faux positif."""
    return NanoMsg("OK", "CONFIRMED", target, "").encode()

def err(target: str, reason: str = "") -> str:
    """Erreur système."""
    return NanoMsg("ERR", "DENIED", target, reason).encode()

def done(target: str, meta: str = "") -> str:
    """Tâche terminée."""
    return NanoMsg("DONE", "CONFIRMED", target, meta).encode()

def state_saved(checkpoint: str) -> str:
    """Checkpoint sauvegardé."""
    return NanoMsg("STATE", "SAVED", checkpoint, "").encode()

def budget_exceeded(tokens_used: int, limit: int) -> str:
    """Budget tokens dépassé."""
    return NanoMsg("BUDGET", "EXCEEDED", f"{tokens_used}", f"limit={limit}").encode()

def budget_free(tokens_used: int) -> str:
    """Appel gratuit effectué."""
    return NanoMsg("BUDGET", "FREE", f"{tokens_used}", "").encode()

def route_decision(tier: str, model: str) -> str:
    """Décision de routage LLM."""
    return NanoMsg("ROUTE", tier.upper(), model, "").encode()


# ─── Validation ──────────────────────────────────────────────────────────────

def validate_pipe(raw: str) -> bool:
    """Vérifie qu'un message respecte le protocole nano-machine."""
    msg = NanoMsg.decode(raw)
    return msg is not None

def extract_tokens_from_meta(meta: str) -> Optional[int]:
    """Extrait le nombre de tokens depuis un champ META."""
    match = re.search(r"(\d+)", meta)
    return int(match.group(1)) if match else None


# ─── optiforge B2 — GitNexus native query (NO LLM tokens) ───────────────────

def invoke_gitnexus(tool_name: str, query: str = "") -> str:
    """
    Bypasse le LLM : exécute GitNexus CLI localement sur Hermes.
    Token cost = 0. Retourne métadonnées graph, jamais raw files.
    """
    try:
        if tool_name in ("query", "context"):
            cmd = ["npx", "gitnexus", tool_name, query, "--json"]
        elif tool_name == "analyze":
            cmd = ["npx", "gitnexus", "analyze"]
        else:
            cmd = ["npx", "gitnexus", tool_name, query]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(FORGE_ROOT), timeout=30
        )
        return result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        return f"ERR|GITNEXUS|{tool_name}|{e}"


def _compress_prompt_local(prompt: str) -> str:
    """Compression locale sans LLM : 1 ligne clé par paragraphe, 300 chars max."""
    lines = [l.strip() for l in prompt.splitlines() if l.strip()]
    return ". ".join(lines[:5])[:300]


def append_to_gitnexus_rules(agent_name: str, rule: str) -> None:
    """
    optiforge B2 §4 + B1 retroactive_boost :
    Écrit la règle dans AGENTS.md ET .cursorrules (GitNexus workspace).
    Zéro tokens LLM.
    """
    marker = f"### {agent_name}"
    entry  = f"\n{marker}\n{rule}\n"
    for target in [FORGE_ROOT / "AGENTS.md", FORGE_ROOT / ".cursorrules"]:
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            if marker not in existing:
                with target.open("a", encoding="utf-8") as f:
                    f.write(entry)
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)


def boost_node(agent_name: str, execution_insights: str) -> str:
    """
    optiforge B1+B3 BOOST_NODE :
    Compresse l'expérience → AGENTS.md + .cursorrules + TurboVec brain.
    """
    compressed = _compress_prompt_local(execution_insights)
    rule = f"Use local strategy for {agent_name}. {compressed}"
    append_to_gitnexus_rules(agent_name, rule)
    # Indexe aussi dans TurboVec (Token Guard persistant)
    try:
        from .turbovec_brain import get_turbovec_brain
        get_turbovec_brain().store(rule, agent=agent_name, score=7.0)
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return f"BOOST_NODE|{agent_name}|EVOLVING_WORKSPACE|AGENTS_MD_UPDATED"


def parse_and_route(raw_packet: str) -> str:
    """
    optiforge B2 §4 : route NMP packets SANS LLM.
    Hard ceiling Mimo/Hermes = 65 000 tokens.
    """
    line = raw_packet.strip()
    if "|" not in line:
        return "ERR|PARSER|MALFORMED_PACKET|NO_PIPES"
    parts   = line.split("|", 3)
    command = parts[0].strip().upper()
    source  = parts[1].strip() if len(parts) > 1 else ""
    target  = parts[2].strip() if len(parts) > 2 else ""
    payload = parts[3].strip() if len(parts) > 3 else ""

    if command not in COMMANDS:
        return f"ERR|PARSER|UNKNOWN_CMD|{command}"

    # Hard ceiling 65k — jamais de payload > ceiling dans le contexte
    estimated_tokens = int(len(payload.split()) * 1.3)
    if estimated_tokens > TOKEN_CEILING:
        return f"ERR|ORCHESTRATOR|EXCEEDS_{TOKEN_CEILING}_CEILING|ABORT"

    if command == "OPT":
        # Prompt Optimizer = méthode prompt-master (étape 6, audit tokens déterministe,
        # zéro LLM → respecte le contrat réflexe SANS token). Cf. tools/prompt_master.py.
        try:
            from tools.prompting.prompt_master import optimize_local as _opt
            compressed = _opt(payload)
        except Exception:
            compressed = _compress_prompt_local(payload)  # fallback historique
        append_to_gitnexus_rules(target or source, compressed)
        return f"SUCCESS|ORCHESTRATOR|{target}|RULES_UPDATED"
    if command == "INIT":
        return f"SUCCESS|ORCHESTRATOR|SPAWN:{target}|READY"
    if command == "EXEC":
        return f"SUCCESS|LOCAL_ENGINE|{target}|ROUTED"
    if command == "BOOST_NODE":
        return boost_node(target, payload)
    if command in ("DATA_NEED", "DL_START", "DL_DONE", "DL_ERR", "DATA_ACK"):
        return f"SUCCESS|BRAIN|{command}|{target}"
    if command == "RETRY":
        return f"RETRY|{source}|{target}|delta={payload[:80]}"
    return f"SUCCESS|LOCAL_ENGINE|{command}|ROUTED"


def deconstruct_task(task: str, max_tokens_per_step: int = 2000) -> list[dict]:
    """
    optiforge B2 §4-1 : divise la tâche en étapes atomiques ≤ max_tokens_per_step.
    Chaque étape = INIT NMP packet prêt à router.
    """
    words = task.split()
    total = int(len(words) * 1.3)
    if total <= max_tokens_per_step:
        return [{"step": 1, "description": task, "token_budget": max_tokens_per_step,
                 "nmp": f"INIT|ORCHESTRATOR|step_1|budget={max_tokens_per_step}"}]

    sentences = re.split(r"(?<=[.!?])\s+", task)
    steps, current, budget_used, n = [], [], 0, 1
    for sent in sentences:
        tok = int(len(sent.split()) * 1.3)
        if budget_used + tok > max_tokens_per_step and current:
            steps.append({"step": n, "description": " ".join(current),
                          "token_budget": max_tokens_per_step,
                          "nmp": f"INIT|ORCHESTRATOR|step_{n}|budget={max_tokens_per_step}"})
            n += 1; current, budget_used = [], 0
        current.append(sent); budget_used += tok
    if current:
        steps.append({"step": n, "description": " ".join(current),
                      "token_budget": max_tokens_per_step,
                      "nmp": f"INIT|ORCHESTRATOR|step_{n}|budget={max_tokens_per_step}"})
    return steps


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Démonstration
    msgs = [
        scan_req("forge_graph.py:42", "pattern=sql_injection"),
        vuln_confirmed("agent_nodes.py:127", "unsanitized_input"),
        ok_safe("forge_state.py"),
        budget_exceeded(52000, 50000),
        route_decision("free", "groq/llama-3.3-70b"),
        done("audit_complete", "score=8.2"),
    ]
    for m in msgs:
        print(m)
        assert validate_pipe(m), f"INVALID: {m}"
    print("\n✅ All nano-machine messages valid.")
