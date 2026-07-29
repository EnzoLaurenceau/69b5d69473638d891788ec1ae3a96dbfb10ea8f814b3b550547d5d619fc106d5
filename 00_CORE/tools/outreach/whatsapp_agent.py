"""
whatsapp_agent.py — Wrapper WhatsApp Claude Agent
==================================================
Source: github.com/dsebastien/whatsapp-claude-agent (Node.js / Baileys)

⚠️  PRODUCTION : utiliser Meta Business API officielle pour scale.
    Baileys (WA Web) = OK pour dev/test, ToS risk à >100 msg/j.

Opt-out RGPD intégré : tout envoi vérifie OptOutManager avant d'envoyer.
Tout message entrant "STOP" → blocklist immédiate.

Usage :
    from tools.outreach import whatsapp_agent
    proc = whatsapp_agent.start(work_dir, session_name="forge_prospect")
    whatsapp_agent.send("+33612345678", "Bonjour !")
    whatsapp_agent.broadcast(leads_list, message_template, dry_run=True)
"""

from __future__ import annotations
import json, os, subprocess, time, urllib.request
from pathlib import Path
from typing import Optional

from ...forge_agents.opt_out_manager import get_opt_out_manager, ContactOptedOut

REPO = "https://github.com/dsebastien/whatsapp-claude-agent"
INSTALL_CMD = "npm install -g @dsebastien/whatsapp-claude-agent"
DEFAULT_PORT = int(os.environ.get("WA_AGENT_PORT", 3099))
DEFAULT_HOST = os.environ.get("WA_AGENT_HOST", f"http://localhost:{DEFAULT_PORT}")

_proc: Optional[subprocess.Popen] = None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def start(work_dir: str | Path = ".", session_name: str = "forge") -> subprocess.Popen:
    """
    Lance le whatsapp-claude-agent en subprocess.
    Scanner le QR code affiché dans le terminal pour lier le compte.
    """
    global _proc
    env = {**os.environ, "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    config = Path(work_dir) / ".whatsapp-claude-agent.json"
    if not config.exists():
        config.write_text(json.dumps({
            "agentName": session_name,
            "permissionMode": "default",
            "maxTurns": 10,
        }, indent=2), encoding="utf-8")

    _proc = subprocess.Popen(
        ["npx", "@dsebastien/whatsapp-claude-agent"],
        cwd=str(work_dir), env=env,
    )
    print(f"whatsapp_agent: démarré (PID {_proc.pid}) — scanner le QR code")
    return _proc


def stop() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        _proc = None
        print("whatsapp_agent: arrêté")


# ── Envoi (avec opt-out check obligatoire) ────────────────────────────────────

def send(contact_id: str, message: str, channel: str = "whatsapp") -> dict:
    """
    Envoie un message WhatsApp à un contact.
    Lève ContactOptedOut si le contact a demandé l'arrêt.
    contact_id = numéro E.164 (ex: +33612345678) ou JID WhatsApp.
    """
    mgr = get_opt_out_manager()
    mgr.check(contact_id)  # bloque si opt-out → lève ContactOptedOut

    # Ajouter le footer opt-out obligatoire RGPD
    full_msg = f"{message}\n\n_Répondez STOP pour ne plus recevoir de messages._"

    payload = json.dumps({"to": contact_id, "message": full_msg}).encode()
    req = urllib.request.Request(
        f"{DEFAULT_HOST}/send",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e), "contact": contact_id}


def broadcast(
    leads: list[dict],
    template: str,
    delay_seconds: float = 3.0,
    dry_run: bool = True,
) -> dict:
    """
    Envoie en masse depuis une liste de leads.
    leads = [{"contact_id": "+336...", "name": "...", ...}]
    template = "Bonjour {name}, ..."
    dry_run=True par défaut — mettre False pour envoyer réellement.

    Retourne {"sent": N, "skipped_optout": N, "errors": N}
    """
    results = {"sent": 0, "skipped_optout": 0, "errors": 0, "dry_run": dry_run}
    mgr = get_opt_out_manager()

    for lead in leads:
        cid = lead.get("contact_id", "")
        if not cid:
            results["errors"] += 1
            continue
        if mgr.is_blocked(cid):
            results["skipped_optout"] += 1
            continue
        msg = template.format(**lead)
        if dry_run:
            print(f"[DRY-RUN] → {cid}: {msg[:60]}…")
            results["sent"] += 1
        else:
            r = send(cid, msg)
            if "error" in r:
                results["errors"] += 1
            else:
                results["sent"] += 1
            time.sleep(delay_seconds)  # anti-ban throttle

    return results


def handle_incoming(contact_id: str, text: str) -> bool:
    """
    À appeler sur chaque message entrant pour détecter les opt-outs.
    Retourne True si opt-out déclenché (ne pas traiter la suite).
    """
    mgr = get_opt_out_manager()
    return mgr.detect_and_register(contact_id, text, channel="whatsapp")


# ponytail: wrapper subprocess mince + opt-out obligatoire.
# Production scale → Meta Business API (oAuth, rate limits officiels).
if __name__ == "__main__":
    mgr = get_opt_out_manager()
    mgr.register_optout("+33699999999", "test", "self-check whatsapp_agent")
    try:
        send("+33699999999", "test")
        print("FAIL: devrait être bloqué")
    except ContactOptedOut as e:
        print(f"OK — opt-out vérifié: {e}")
    print("whatsapp_agent: self-check OK")
