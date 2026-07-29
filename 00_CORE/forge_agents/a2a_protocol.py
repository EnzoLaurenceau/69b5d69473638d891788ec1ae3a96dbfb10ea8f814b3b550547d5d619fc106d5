"""
A2A (Agent-to-Agent) Protocol Module for La Forge
===================================================
Establishes a unified, ultra-compact Agent-to-Agent communication schema
replacing verbose natural language and JSON/MCP serialization overhead.

Format: A2A|[ACTION]|[SENDER]|[RECEIVER]|[PAYLOAD_KV]|[SCORE]

NMP: TOOL|INDEX|a2a_protocol|savings=75|pattern=a2a local protocol|approach=Direct regex parsing + suffix injection
"""

import re
from typing import Dict, Any, Optional, Tuple

A2A_RE = re.compile(r'^A2A\|([A-Z]{3,6})\|([^|]+)\|([^|]+)\|([^|]*)\|?([\d.]*)$')

A2A_SYSTEM_SUFFIX = (
    "\n\n--- A2A PROTOCOL REQUIREMENT (Agent-to-Agent) ---\n"
    "Respond ONLY in the strict A2A format. DO NOT output prose, intro, markdown, or lists.\n"
    "Syntax: A2A|[ACTION]|[SENDER]|[RECEIVER]|[PAYLOAD_KV]|[SCORE]\n"
    "Actions: EXEC (execute), FIND (discovery), WARN (warning), RECOM (recommendation), DONE (complete), FAIL (error).\n"
    "Example: A2A|FIND|SEO_AGENT|ORCHESTRATOR|citability=8.5,crawlers=valid|8.5\n"
)


class A2APacket:
    def __init__(
        self,
        action: str,
        sender: str,
        receiver: str,
        payload: Dict[str, str],
        score: Optional[float] = None
    ):
        self.action = action.upper()
        self.sender = sender.upper()
        self.receiver = receiver.upper()
        self.payload = payload
        self.score = score

    def encode(self) -> str:
        """Encode the packet into a single A2A protocol string."""
        kv_pairs = []
        for k, v in self.payload.items():
            # Sanitize keys and values to prevent separator issues
            k_clean = str(k).replace("=", "").replace(",", "").replace("|", "")
            v_clean = str(v).replace("=", "").replace(",", "").replace("|", ";")
            kv_pairs.append(f"{k_clean}={v_clean}")
        kv_str = ",".join(kv_pairs)
        score_str = f"|{self.score}" if self.score is not None else ""
        return f"A2A|{self.action}|{self.sender}|{self.receiver}|{kv_str}{score_str}"

    @classmethod
    def decode(cls, packet_str: str) -> Optional['A2APacket']:
        """Decode an A2A protocol string into a packet object."""
        match = A2A_RE.match(packet_str.strip())
        if not match:
            return None
        action, sender, receiver, kv_raw, score_raw = match.groups()
        
        payload = {}
        if kv_raw:
            for kv in kv_raw.split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    payload[k.strip()] = v.strip()

        score = float(score_raw) if score_raw else None
        return cls(action, sender, receiver, payload, score)
