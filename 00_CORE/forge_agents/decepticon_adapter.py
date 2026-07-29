"""
decepticon_adapter.py — Engagement workflow à la Decepticon pour la Forge
=========================================================================
Inspiré de https://github.com/PurpleAILAB/Decepticon (Apache 2.0)

Ce module apporte ce qui manquait au BBH existant :
  1. EngagementBundle  → RoE + ConOps + OPPLAN + MITRE ATT&CK (avant P1)
  2. kill_chain()      → ordonne les findings en kill chain MITRE TA0001→TA0010
  3. mitre_map()       → mappe chaque finding aux techniques ATT&CK
  4. RoEEnforcer       → middleware scope-check au niveau outil (pas juste script)

Utilise forge_llm FREE tier (RTK → VPS → OpenRouter).
Zéro dépendance Decepticon Docker — logique native forge.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Optional

FORGE_ROOT = Path(__file__).parent.parent.parent
BBH_ROOT   = Path("C:/Users/Enzo/Documents/Claude/Projects/Bug Bounty Hunter")


# ─── Enums (alignés sur Decepticon engagement.py) ────────────────────────────

class Phase(StrEnum):
    RECON          = "recon"           # TA0043
    INITIAL_ACCESS = "initial-access"  # TA0001
    POST_EXPLOIT   = "post-exploit"    # TA0003-TA0009
    EXFILTRATION   = "exfiltration"    # TA0010

class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"
    INFO     = "info"

# Mapping CWE / vuln type → MITRE technique (principaux pour bug bounty web)
MITRE_MAP: dict[str, dict] = {
    "cors":          {"id": "T1550.001", "tactic": "TA0001", "name": "Valid Accounts: Default Accounts"},
    "idor":          {"id": "T1078",     "tactic": "TA0001", "name": "Valid Accounts"},
    "ssrf":          {"id": "T1090.002", "tactic": "TA0011", "name": "Proxy: External Proxy"},
    "xss":           {"id": "T1059.007", "tactic": "TA0002", "name": "Command and Scripting: JavaScript"},
    "sqli":          {"id": "T1190",     "tactic": "TA0001", "name": "Exploit Public-Facing Application"},
    "jwt":           {"id": "T1528",     "tactic": "TA0006", "name": "Steal Application Access Token"},
    "oauth":         {"id": "T1550.001", "tactic": "TA0001", "name": "Use Alternate Auth Material"},
    "open_redirect": {"id": "T1566.002", "tactic": "TA0001", "name": "Phishing: Spearphishing Link"},
    "takeover":      {"id": "T1584.001", "tactic": "TA0042", "name": "Compromise Infrastructure: Domains"},
    "lfi":           {"id": "T1083",     "tactic": "TA0007", "name": "File and Directory Discovery"},
    "rce":           {"id": "T1190",     "tactic": "TA0001", "name": "Exploit Public-Facing Application"},
    "xxe":           {"id": "T1190",     "tactic": "TA0001", "name": "Exploit Public-Facing Application"},
    "ssti":          {"id": "T1059",     "tactic": "TA0002", "name": "Command and Scripting Interpreter"},
    "crlf":          {"id": "T1059.007", "tactic": "TA0002", "name": "Command and Scripting: JavaScript"},
    "actuator":      {"id": "T1087",     "tactic": "TA0007", "name": "Account Discovery"},
    "graphql":       {"id": "T1213",     "tactic": "TA0009", "name": "Data from Information Repositories"},
    "default":       {"id": "T1190",     "tactic": "TA0001", "name": "Exploit Public-Facing Application"},
}

# Kill chain phase par tactic MITRE
TACTIC_TO_PHASE: dict[str, Phase] = {
    "TA0043": Phase.RECON,
    "TA0001": Phase.INITIAL_ACCESS,
    "TA0042": Phase.INITIAL_ACCESS,
    "TA0002": Phase.INITIAL_ACCESS,
    "TA0003": Phase.POST_EXPLOIT,
    "TA0004": Phase.POST_EXPLOIT,
    "TA0005": Phase.POST_EXPLOIT,
    "TA0006": Phase.POST_EXPLOIT,
    "TA0007": Phase.POST_EXPLOIT,
    "TA0008": Phase.POST_EXPLOIT,
    "TA0009": Phase.POST_EXPLOIT,
    "TA0011": Phase.POST_EXPLOIT,
    "TA0010": Phase.EXFILTRATION,
}


# ─── Dataclasses RoE + OPPLAN ────────────────────────────────────────────────

@dataclass
class RoE:
    """Rules of Engagement — scope légal, actions interdites."""
    target: str
    platform: str                    # "yeswehack" | "hackerone" | "intigriti"
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    prohibited_actions: list[str] = field(default_factory=lambda: [
        "DoS / DDoS attacks",
        "Social engineering / phishing",
        "Physical attacks",
        "Automated credential stuffing",
        "Data exfiltration beyond PoC",
        "Modifying/deleting user data",
        "Accessing other users' accounts without consent",
    ])
    rate_limit_req_per_sec: int = 50
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def check(self, asset: str) -> bool:
        """True si asset in-scope. Denylist prioritaire."""
        asset = asset.lower()
        for oos in self.out_of_scope:
            if oos.lower() in asset or asset in oos.lower():
                return False
        for ins in self.in_scope:
            if ins.startswith("*."):
                domain = ins[2:]
                if asset.endswith(domain) or asset == domain:
                    return True
            elif ins.lower() in asset or asset in ins.lower():
                return True
        return False


@dataclass
class Objective:
    """Un objectif tactique OPPLAN."""
    id: str
    phase: Phase
    description: str
    mitre_tactic: str
    mitre_technique: str
    status: str = "pending"      # pending | in_progress | done | killed
    finding_id: Optional[str] = None


@dataclass
class OPPLAN:
    """Operational Plan — objectifs tactiques avec MITRE ATT&CK."""
    target: str
    engagement_type: str         # "web-bounty" | "api-bounty" | "mobile-bounty"
    threat_profile: str          # résumé du profil de menace
    objectives: list[Objective] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def next_objective(self) -> Optional[Objective]:
        return next((o for o in self.objectives if o.status == "pending"), None)

    def mark_done(self, obj_id: str, finding_id: str = ""):
        for o in self.objectives:
            if o.id == obj_id:
                o.status = "done"
                o.finding_id = finding_id


@dataclass
class EngagementBundle:
    """Bundle complet avant P1 — Decepticon-style."""
    roe:    RoE
    opplan: OPPLAN
    conops: str    # texte ConOps (objectifs stratégiques)
    saved_to: Optional[str] = None


# ─── RoE Enforcer — middleware scope ─────────────────────────────────────────

class RoEEnforcer:
    """
    Vérifie chaque asset/outil avant exécution.
    Remplace le scope_check() scriptique par un vrai middleware.
    """
    def __init__(self, roe: RoE):
        self._roe = roe

    def allow(self, asset: str, action: str = "") -> tuple[bool, str]:
        """(allowed, reason). Denylist d'abord, puis allowlist."""
        asset_lower = asset.lower()

        # Actions interdites par pattern
        for prohibited in self._roe.prohibited_actions:
            if any(kw in action.lower() for kw in prohibited.lower().split()[:2]):
                return False, f"RoE violation: {prohibited}"

        if not self._roe.check(asset):
            return False, f"Out of scope: {asset}"

        return True, "ok"

    def gate(self, asset: str, action: str = "") -> None:
        """Lève ValueError si hors scope (bloque l'outil)."""
        ok, reason = self.allow(asset, action)
        if not ok:
            raise ValueError(f"[RoE BLOCK] {reason}")


# ─── MITRE mapping ───────────────────────────────────────────────────────────

def mitre_map(vuln_type: str) -> dict:
    """
    Mappe un type de vuln (string libre) vers la technique MITRE ATT&CK.
    Retourne {id, tactic, name}.
    """
    vuln_lower = vuln_type.lower()
    for key, entry in MITRE_MAP.items():
        if key in vuln_lower:
            return entry
    return MITRE_MAP["default"]


def kill_chain(findings: list[dict]) -> list[dict]:
    """
    Ordonne une liste de findings en kill chain MITRE.
    Chaque finding doit avoir au minimum {"type": "...", "severity": "..."}.
    Retourne la liste ordonnée avec phase + technique ajoutées.
    """
    enriched = []
    for f in findings:
        tech = mitre_map(f.get("type", ""))
        phase = TACTIC_TO_PHASE.get(tech["tactic"], Phase.INITIAL_ACCESS)
        enriched.append({**f, "mitre": tech, "kill_chain_phase": phase.value})

    # Ordre kill chain : recon → initial-access → post-exploit → exfil
    phase_order = {p.value: i for i, p in enumerate(Phase)}
    enriched.sort(key=lambda x: phase_order.get(x["kill_chain_phase"], 99))
    return enriched


# ─── Engagement Bundle generator (forge_llm FREE) ────────────────────────────

def generate_engagement_bundle(
    target: str,
    scope_domains: list[str],
    out_of_scope: list[str] | None = None,
    platform: str = "yeswehack",
    engagement_type: str = "web-bounty",
) -> EngagementBundle:
    """
    Génère RoE + ConOps + OPPLAN avant P1.
    Utilise forge_llm FREE (RTK → VPS → OpenRouter).
    Sauvegarde dans BBH_ROOT/targets/<slug>/engagement/
    """
    from .forge_llm import forge_call, LLMTier

    roe = RoE(
        target=target,
        platform=platform,
        in_scope=scope_domains,
        out_of_scope=out_of_scope or [],
    )

    # ConOps — 1 appel LLM gratuit
    conops_prompt = f"""
You are a professional bug bounty hunter. Generate a 3-paragraph ConOps for:
Target: {target}
Platform: {platform}
Type: {engagement_type}
In-scope: {', '.join(scope_domains[:5])}

ConOps must cover: threat profile, attack surface summary, priority objectives.
Format: plain text, no headers, concise.
"""
    conops = forge_call(conops_prompt, tier=LLMTier.HAIKU, task_type="fast_extraction",
                        max_tokens=400)

    # OPPLAN objectives — génération heuristique (zéro LLM, déterministe)
    objectives = _default_objectives(target, engagement_type)

    opplan = OPPLAN(
        target=target,
        engagement_type=engagement_type,
        threat_profile=conops[:200],
        objectives=objectives,
    )

    bundle = EngagementBundle(roe=roe, opplan=opplan, conops=conops)

    # Persistance
    slug = re.sub(r'[^\w]', '_', target.lower())
    out_dir = BBH_ROOT / "targets" / slug / "engagement"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "roe.json").write_text(
        json.dumps(asdict(roe), indent=2, default=str), encoding="utf-8")
    (out_dir / "opplan.json").write_text(
        json.dumps(asdict(opplan), indent=2, default=str), encoding="utf-8")
    (out_dir / "conops.md").write_text(f"# ConOps — {target}\n\n{conops}", encoding="utf-8")
    bundle.saved_to = str(out_dir)

    return bundle


def _default_objectives(target: str, engagement_type: str) -> list[Objective]:
    """Objectifs OPPLAN standards pour web/api/mobile bounty."""
    base = [
        Objective("OBJ-001", Phase.RECON,          f"Passive recon {target}",
                  "TA0043", "T1590"),
        Objective("OBJ-002", Phase.RECON,          f"Active recon + tech fingerprint {target}",
                  "TA0043", "T1592"),
        Objective("OBJ-003", Phase.INITIAL_ACCESS,  "Enumerate endpoints + params",
                  "TA0001", "T1190"),
        Objective("OBJ-004", Phase.INITIAL_ACCESS,  "Vuln scan (nuclei + targeted)",
                  "TA0001", "T1190"),
        Objective("OBJ-005", Phase.INITIAL_ACCESS,  "Auth bypass / IDOR / BOLA",
                  "TA0001", "T1078"),
        Objective("OBJ-006", Phase.POST_EXPLOIT,    "Chain low findings → critical",
                  "TA0008", "T1563"),
        Objective("OBJ-007", Phase.EXFILTRATION,    "PoC + evidence capture",
                  "TA0010", "T1041"),
    ]
    if "mobile" in engagement_type:
        base.insert(3, Objective("OBJ-003b", Phase.RECON,
                                  "APK static analysis + dynamic ADB",
                                  "TA0043", "T1422"))
    return base


# ─── Load/save bundle depuis disque ──────────────────────────────────────────

def load_bundle(target: str) -> Optional[EngagementBundle]:
    """Charge le bundle sauvegardé pour une cible."""
    slug = re.sub(r'[^\w]', '_', target.lower())
    out_dir = BBH_ROOT / "targets" / slug / "engagement"
    if not out_dir.exists():
        return None
    try:
        roe_data   = json.loads((out_dir / "roe.json").read_text(encoding="utf-8"))
        opplan_data = json.loads((out_dir / "opplan.json").read_text(encoding="utf-8"))
        conops     = (out_dir / "conops.md").read_text(encoding="utf-8")
        roe    = RoE(**{k: v for k, v in roe_data.items() if k in RoE.__dataclass_fields__})
        objs   = [Objective(**o) for o in opplan_data.get("objectives", [])]
        opplan = OPPLAN(
            target=opplan_data["target"],
            engagement_type=opplan_data["engagement_type"],
            threat_profile=opplan_data["threat_profile"],
            objectives=objs,
            generated_at=opplan_data.get("generated_at", ""),
        )
        return EngagementBundle(roe=roe, opplan=opplan, conops=conops, saved_to=str(out_dir))
    except Exception:
        return None


# ─── CLI self-check ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ponytail: self-check minimal
    roe = RoE("example.com", "yeswehack",
              in_scope=["*.example.com", "api.example.com"],
              out_of_scope=["admin.example.com"])
    enforcer = RoEEnforcer(roe)

    assert enforcer.allow("api.example.com")[0] is True,  "in-scope doit passer"
    assert enforcer.allow("admin.example.com")[0] is False, "out-of-scope doit bloquer"
    assert enforcer.allow("other.com")[0] is False, "hors scope doit bloquer"

    findings = [
        {"type": "cors", "severity": "medium"},
        {"type": "rce",  "severity": "critical"},
        {"type": "ssrf", "severity": "high"},
    ]
    chain = kill_chain(findings)
    assert chain[0]["kill_chain_phase"] == "initial-access"
    assert chain[-1]["kill_chain_phase"] in ("initial-access", "post-exploit")

    print("decepticon_adapter: all checks OK")
    print("Kill chain:", [(c["type"], c["kill_chain_phase"]) for c in chain])
