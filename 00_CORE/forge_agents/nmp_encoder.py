"""
nmp_encoder.py — Encode findings and state to NMP format
=========================================================
Converts verbose JSON state to NMP (Nano-Machine Protocol) format.
Format: ACTION|SOURCE|TARGET|PAYLOAD
"""

from typing import Dict, List, Any
import json


def encode_finding_nmp(finding: Dict) -> str:
    """
    Encode a finding to NMP format.
    
    NMP Format: ACTION|SOURCE|TARGET|PAYLOAD
    
    For findings:
    - ACTION: FINDING (or VULN for vulnerabilities)
    - SOURCE: agent name
    - TARGET: finding ID
    - PAYLOAD: score|status|cycle|metadata
    """
    action = "VULN" if finding.get("score", 0) >= 7.5 else "FINDING"
    source = finding.get("agent", "UNKNOWN").upper()
    target = finding.get("id", "F-UNKNOWN")
    
    # Encode payload as key=value pairs
    payload_parts = []
    payload_parts.append(f"score={finding.get('score', 0)}")
    payload_parts.append(f"status={finding.get('status', 'pending')}")
    payload_parts.append(f"cycle={finding.get('cycle', 0)}")
    payload_parts.append(f"jury={finding.get('jury_consensus', 0)}")
    payload_parts.append(f"indexed={finding.get('graphify_indexed', False)}")
    
    payload = "|".join(payload_parts)
    
    return f"{action}|{source}|{target}|{payload}"


def encode_state_nmp(state: Dict) -> Dict:
    """
    Encode entire state to NMP format.
    
    Converts:
    - findings → NMP encoded strings
    - caveman_log → already NMP
    - quality_history → NMP STATE messages
    - Other fields → keep as-is for compatibility
    """
    encoded = {}
    
    # Encode findings
    if "findings" in state:
        encoded_findings = []
        for finding in state["findings"]:
            if isinstance(finding, dict):
                encoded_findings.append(encode_finding_nmp(finding))
            else:
                encoded_findings.append(finding)  # Already encoded
        encoded["findings"] = encoded_findings
    
    # Encode quality history as NMP STATE messages
    if "quality_history" in state:
        quality = state["quality_history"]
        if quality:
            latest = quality[-1] if quality else 0
            encoded["quality_state"] = f"STATE|MONITOR|QUALITY|current={latest}|history_len={len(quality)}"
    
    # Keep other fields as-is
    for key, value in state.items():
        if key not in ("findings", "quality_history"):
            encoded[key] = value
    
    return encoded


def encode_checkpoint_nmp(checkpoint: Dict) -> Dict:
    """
    Encode checkpoint to NMP format.
    
    Checkpoints contain:
    - current_level
    - cycle_count
    - last_task
    - findings (need encoding)
    """
    encoded = checkpoint.copy()
    
    # Encode findings in checkpoint
    if "findings" in encoded:
        encoded_findings = []
        for finding in encoded["findings"]:
            if isinstance(finding, dict):
                encoded_findings.append(encode_finding_nmp(finding))
            else:
                encoded_findings.append(finding)
        encoded["findings"] = encoded_findings
    
    # Add NMP header
    encoded["_nmp_version"] = "1.0"
    encoded["_encoding"] = "NMP"
    
    return encoded


def decode_finding_nmp(nmp_str: str) -> Dict:
    """
    Decode NMP encoded finding back to dict.
    
    Input: FINDING|AGENT|F-ID|score=8.0|status=confirmed|cycle=1|jury=0.8|indexed=True
    Output: {"id": "F-ID", "agent": "AGENT", "score": 8.0, ...}
    """
    parts = nmp_str.split("|")
    if len(parts) < 4:
        return {"error": "Invalid NMP format", "raw": nmp_str}
    
    action, source, target = parts[0], parts[1], parts[2]
    payload_parts = parts[3:]
    
    result = {
        "id": target,
        "agent": source,
        "action": action,
    }
    
    # Parse payload key=value pairs
    for part in payload_parts:
        if "=" in part:
            key, value = part.split("=", 1)
            # Convert types
            if value == "True":
                value = True
            elif value == "False":
                value = False
            elif value.replace(".", "").isdigit():
                value = float(value) if "." in value else int(value)
            result[key] = value
    
    return result


def encode_tool_index_nmp(tool_index: Dict) -> Dict:
    """
    Encode tool index to NMP format.
    
    Tools become: TOOL|INDEX|tool_name|savings=70|pattern=...|approach=...
    """
    encoded = {}
    
    for tool_name, tool_data in tool_index.items():
        if isinstance(tool_data, dict):
            savings = tool_data.get("savings", 0)
            pattern = tool_data.get("pattern", "")
            approach = tool_data.get("approach", "")
            nmp = f"TOOL|INDEX|{tool_name}|savings={savings}|pattern={pattern}|approach={approach}"
            encoded[tool_name] = nmp
        else:
            encoded[tool_name] = tool_data
    
    return encoded


def encode_monitor_state_nmp(monitor_state: Dict) -> str:
    """
    Encode monitor state to NMP format.
    
    Input: {"status": "idle", "alerts": 0, "transfers": 0}
    Output: STATE|MONITOR|STATUS|status=idle|alerts=0|transfers=0
    """
    status = monitor_state.get("status", "unknown")
    alerts = monitor_state.get("alerts", 0)
    transfers = monitor_state.get("transfers", 0)
    
    return f"STATE|MONITOR|STATUS|status={status}|alerts={alerts}|transfers={transfers}"


def encode_task_log_nmp(task_log: Dict) -> str:
    """
    Encode task log to NMP format.
    
    Input: {"task": "...", "tokens": 1000, "status": "done"}
    Output: EXEC|AGENT|TASK|task=...|tokens=1000|status=done
    """
    task = task_log.get("task", "unknown")
    tokens = task_log.get("tokens", 0)
    status = task_log.get("status", "unknown")
    agent = task_log.get("agent", "unknown")
    
    return f"EXEC|{agent}|TASK|task={task}|tokens={tokens}|status={status}"


# Convenience functions for common NMP encodings
def finding_to_nmp(finding: Dict) -> str:
    """Alias for encode_finding_nmp."""
    return encode_finding_nmp(finding)


def state_to_nmp(state: Dict) -> Dict:
    """Alias for encode_state_nmp."""
    return encode_state_nmp(state)


def checkpoint_to_nmp(checkpoint: Dict) -> Dict:
    """Alias for encode_checkpoint_nmp."""
    return encode_checkpoint_nmp(checkpoint)
