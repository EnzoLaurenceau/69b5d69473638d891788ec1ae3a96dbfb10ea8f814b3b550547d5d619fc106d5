"""
cashclaw.py — Wrapper CashClaw (couche revenu autonome de la Forge)
===================================================================
Source : github.com/ertugrulakben/cashclaw  (npm: cashclaw, MIT)

CashClaw = pack de skills OpenClaw + CLI `cashclaw` qui transforme un agent
en business freelance : missions HYRVE marketplace → livraison → Stripe.
Runtime ici = **Hermes** (lit les SKILL.md, exécute les missions).

Architecture câblée :
    HYRVE (missions)  ──►  cashclaw CLI  ──►  Hermes (exécute la skill)
                                          └─► livrable files ─► cashclaw deliver
                                          Stripe (encaisse) ◄─┘
    Guard = cost cap + recursion kill + tool firewall (cashclaw guard).

⚠️ HITL : accept / deliver / complete / withdraw exigent approve=True.
   Sans approbation → renvoyé "gated", AUCUN appel CLI (pas de sortie d'argent).
   auto_accept reste OFF par défaut (blueprint Forge : pas d'auto-confirmation d'argent).

DO NOT INVENT (règle #5) : on appelle la CLI cashclaw, on ne réimplémente ni
HYRVE ni Stripe. Wrapper = subprocess mince, jamais d'exception propagée.

Usage :
    from tools.money import cashclaw
    cashclaw.ensure()                       # npm i -g cashclaw si absent
    cashclaw.setup()                        # config Stripe+HYRVE depuis l'env + guard init
    cashclaw.wire_hermes()                  # installe les skills dans le runtime Hermes
    cashclaw.gigs()                         # missions dispo (lecture, libre)
    cashclaw.accept(gig_id, approve=True)   # HITL : accepter une mission
    cashclaw.deliver(gig_id, "deliverables/", approve=True)
    cashclaw.withdraw(50, approve=True)     # HITL : sortie d'argent
    cashclaw.poll(interval=60)              # daemon, auto_accept OFF par défaut
"""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

REPO = "https://github.com/ertugrulakben/cashclaw"
INSTALL_CMD = ["npm", "install", "-g", "cashclaw"]

# Runtime agent qui exécute réellement les missions (lit les SKILL.md).
# CashClaw n'est PAS lié à un agent : le CLI `cashclaw` est agent-agnostique
# (Node, lancé depuis n'importe quel dossier) ; seuls les SKILL.md vont dans le
# dossier skills que l'agent scanne. Tout agent au standard Agent Skills marche.
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
# ponytail: dossier skills de Hermes supposé ~/.hermes/skills ; override via env.
HERMES_SKILLS_DIR = Path(os.environ.get("HERMES_SKILLS_DIR", HERMES_HOME / "skills"))

# Où chaque runtime auto-découvre les SKILL.md (standard Agent Skills).
# Les chemins relatifs = dans le dossier courant (= dossier de la Forge d'où tu lances l'agent).
AGENT_SKILL_DIRS = {
    "hermes":      HERMES_SKILLS_DIR,                 # ~/.hermes/skills
    "gemini":      Path(".gemini") / "skills",        # gemini-cli workspace (ou ~/.gemini/skills global)
    "antigravity": Path(".agents") / "skills",        # Antigravity workspace
    "standard":    Path(".agents") / "skills",        # lu par gemini-cli ET antigravity → 1 drop, 2 runtimes
}

# Bridge livraison : skill CashClaw → outil Forge qui produit le livrable.
# Hermes lit la SKILL.md ; ces hints disent QUEL outil Forge appeler pour le travail.
FORGE_DELIVERY = {
    "seo_audit":            "semrush MCP (siteaudit/organic_research)",
    "content_writing":      "forge_call(tier=FREE)  # RTK, jamais dans le contexte Claude",
    "lead_generation":      "tools.research.open_osint + tools.research.public_apis",
    "whatsapp_management":  "tools.outreach.whatsapp_agent (+ opt_out_manager)",
    "social_media":         "skill canva-creator + content-strategy",
    "auto_invoicing":       "tools.product_bricks.documents.stirling_pdf",
    "email_outreach":       "tools.outreach + forge_agents.opt_out_manager (RGPD)",
    "competitor_analysis":  "semrush MCP + firecrawl-competitive-intel",
    "landing_page_builder": "skill website-builder → tools.delivery.coolify",
    "data_scraping":        "scrapling_connector / tools.automation.browser_use",
    "reputation_mgmt":      "tools.research.open_osint + skill customer-pulse",
}

# Opérations à enjeu argent → gate humain obligatoire (HITL).
MONEY_OPS = {"accept", "deliver", "complete", "withdraw", "counter"}


# ── Subprocess mince (fallback, jamais de raise) ──────────────────────────────

def _cc(*args: str, timeout: int = 120) -> dict:
    """Appelle la CLI cashclaw (globale sinon `npx cashclaw`). Ne lève jamais."""
    base = ["cashclaw"] if shutil.which("cashclaw") else ["npx", "cashclaw"]
    try:
        r = subprocess.run(
            base + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": r.returncode == 0, "code": r.returncode,
                "out": r.stdout.strip(), "err": r.stderr.strip(), "cmd": " ".join(args)}
    except Exception as e:  # cashclaw absent, npx absent, timeout…
        return {"ok": False, "code": -1, "out": "", "err": str(e), "cmd": " ".join(args)}


def _gate(op: str, **ctx) -> dict:
    """Refus HITL : décrit l'action d'argent sans l'exécuter."""
    return {"gated": True, "op": op, "context": ctx,
            "message": f"HITL: '{op}' touche à l'argent → rappeler avec approve=True pour exécuter."}


# ── Install / setup / câblage Hermes ──────────────────────────────────────────

def ensure() -> dict:
    """Installe cashclaw globalement si la CLI est absente. Idempotent."""
    if shutil.which("cashclaw"):
        return {"ok": True, "already": True}
    try:
        r = subprocess.run(INSTALL_CMD, capture_output=True, text=True, timeout=600)
        return {"ok": r.returncode == 0, "out": r.stdout.strip(), "err": r.stderr.strip()}
    except Exception as e:
        return {"ok": False, "err": str(e), "hint": f"npm requis — {REPO}"}


def setup(currency: str = "usd") -> dict:
    """
    Configure cashclaw depuis l'environnement + active Guard (cost cap).
    Clés lues : STRIPE_API_KEY, HYRVE_API_KEY (via .env / nopeek).
    """
    out = {}
    stripe = os.environ.get("STRIPE_API_KEY", "")
    hyrve = os.environ.get("HYRVE_API_KEY", "")
    if stripe:
        out["stripe"] = _cc("config", "--stripe-key", stripe)
    if hyrve:
        out["hyrve_key"] = _cc("config", "--hyrve-key", hyrve)
        out["connect"] = _cc("hyrve", "connect", "--api-key", hyrve)
    out["currency"] = _cc("config", "--currency", currency)
    out["guard"] = _cc("guard", "init")  # cost cap + recursion kill + firewall
    out["auto_accept_off"] = _cc("hyrve", "auto-accept", "off")  # HITL par défaut
    missing = [k for k, v in {"STRIPE_API_KEY": stripe, "HYRVE_API_KEY": hyrve}.items() if not v]
    if missing:
        out["warning"] = f"clés manquantes dans l'env : {missing}"
    return out


def wire_agent(agent: str = "hermes", skills_dir: Optional[Path] = None) -> dict:
    """
    Câble CashClaw à un runtime : copie les SKILL.md cashclaw dans le dossier
    skills que l'agent scanne. L'agent devient le runtime qui exécute les missions.

    agent : "hermes" | "gemini" | "antigravity" | "standard"  (ou skills_dir explicite).
            "standard" (.agents/skills) est lu à la fois par gemini-cli et antigravity.
    """
    dest = Path(skills_dir) if skills_dir else AGENT_SKILL_DIRS.get(agent)
    if dest is None:
        return {"ok": False, "err": f"agent inconnu: {agent}", "known": list(AGENT_SKILL_DIRS)}
    src = _cashclaw_skills_src()
    if not src:
        return {"ok": False, "err": "skills cashclaw introuvables — lancer ensure() d'abord",
                "looked_for": "`npm root -g`/cashclaw/skills"}
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for skill in src.iterdir():
        if skill.is_dir() and (skill / "SKILL.md").exists():
            shutil.copytree(skill, dest / skill.name, dirs_exist_ok=True)
            copied.append(skill.name)
    return {"ok": bool(copied), "runtime": agent, "dest": str(dest), "skills": copied}


def wire_hermes(skills_dir: Optional[Path] = None) -> dict:
    """Alias historique — câble sur Hermes. Voir wire_agent()."""
    return wire_agent("hermes", skills_dir)


def _cashclaw_skills_src() -> Optional[Path]:
    """Localise les skills dans le package npm global de cashclaw."""
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True,
                              text=True, timeout=30).stdout.strip()
        cand = Path(root) / "cashclaw" / "skills"
        return cand if cand.exists() else None
    except Exception:
        return None


# ── Lecture (libre, aucun argent en jeu) ──────────────────────────────────────

def gigs() -> dict:       return _cc("hyrve", "gigs")
def orders(status: str = "active") -> dict: return _cc("hyrve", "orders", "--status", status)
def wallet() -> dict:     return _cc("hyrve", "wallet")
def stats() -> dict:      return _cc("hyrve", "stats")
def guard_status() -> dict: return _cc("guard", "status")
def delivery_hint(skill: str) -> str:
    """Quel outil Forge produit le livrable pour une skill CashClaw donnée."""
    return FORGE_DELIVERY.get(skill, "forge_call(tier=FREE) — pas de mapping dédié")


# ── Opérations d'argent (HITL obligatoire) ────────────────────────────────────

def accept(gig_id: str, approve: bool = False) -> dict:
    if not approve:
        return _gate("accept", gig=gig_id)
    return _cc("hyrve", "accept", "--gig", gig_id)


def deliver(gig_id: str, files_dir: str, approve: bool = False) -> dict:
    if not approve:
        return _gate("deliver", gig=gig_id, files=files_dir)
    return _cc("hyrve", "deliver", "--gig", gig_id, "--files", files_dir)


def complete(order_id: str, approve: bool = False) -> dict:
    if not approve:
        return _gate("complete", order=order_id)
    return _cc("hyrve", "complete", order_id)


def withdraw(amount: float, approve: bool = False) -> dict:
    if not approve:
        return _gate("withdraw", amount=amount)
    return _cc("hyrve", "withdraw", str(amount))


def poll(interval: int = 60, auto_accept: bool = False) -> dict:
    """
    Daemon de polling des missions. auto_accept=False (défaut) : Hermes détecte
    les gigs mais l'acceptation reste manuelle (HITL). True = autonomie totale
    (sous garde-fou Guard cost cap) — à n'activer qu'explicitement.
    """
    _cc("hyrve", "auto-accept", "on" if auto_accept else "off")
    return _cc("hyrve", "poll", "--interval", str(interval), timeout=10)


# ponytail: wrapper subprocess mince autour de la CLI cashclaw + gate HITL sur l'argent.
#           Hermes = runtime (exécute les SKILL.md) ; la Forge fournit les outils de livraison.
if __name__ == "__main__":
    # Self-check chemin argent : une sortie d'argent SANS approve ne doit JAMAIS s'exécuter.
    g = withdraw(100)                       # pas d'approve
    assert g.get("gated") and "cmd" not in g, "FAIL: withdraw a contourné le gate HITL"
    assert accept("gig_x").get("gated"), "FAIL: accept non gardé"
    assert deliver("gig_x", "out/").get("gated"), "FAIL: deliver non gardé"
    assert delivery_hint("seo_audit").startswith("semrush"), "FAIL: bridge livraison cassé"
    # Runtime-agnostique : un agent inconnu est rejeté sans toucher au disque.
    assert wire_agent("bogus").get("ok") is False, "FAIL: agent inconnu non rejeté"
    assert set(AGENT_SKILL_DIRS) >= {"hermes", "gemini", "antigravity"}, "FAIL: runtimes manquants"
    print("cashclaw: self-check OK — gate HITL + multi-runtime (hermes/gemini/antigravity)")
