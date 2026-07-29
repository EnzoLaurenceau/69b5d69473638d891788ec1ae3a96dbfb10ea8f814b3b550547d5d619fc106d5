"""
bbril_pipeline.py — Bug Bounty Report Intelligence Layer
=========================================================
Ingère des rapports publics (HackerOne Hacktivity, YesWeHack disclosures)
et les transforme en exploit_patterns réutilisables pour cibler les vulns
les plus rentables sur un programme donné.

Basé sur : 09_TASKS/agentbugbounty.md §1-§10

Stockage :
  • exploit_patterns  → nexus_bridge (memory) + forge_db (PostgreSQL si up)
  • Fallback          → BBH_ROOT/workflow/brain/bbril_cache.json

Usage :
  from forge_agents.bbril_pipeline import get_patterns_for_target, ingest_h1_hacktivity

  # Avant P5 (vuln scan)
  patterns = get_patterns_for_target(tech_stack=["spring", "react"], limit=5)
  # → liste de patterns exploitables triés par EV_score

  # Sync quotidienne (cron ou run_vps_cycle.sh)
  ingest_h1_hacktivity(limit=50)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
BBH_ROOT   = Path("C:/Users/Enzo/Documents/Claude/Projects/Bug Bounty Hunter")
CACHE_FILE = BBH_ROOT / "workflow" / "brain" / "bbril_cache.json"

# ─── Schema exploit_pattern ───────────────────────────────────────────────────

@dataclass
class ExploitPattern:
    """
    Pattern de vulnérabilité réutilisable issu de rapports payés.
    Champ ev_score = Expected Value = fréquence × bounty_moyen × reproductibilité.
    """
    id: str                          # hash déterministe du pattern_name
    pattern_name: str                # ex: "IDOR via UUID prediction"
    category: str                    # ex: "IDOR", "SSRF", "CORS"
    description: str
    attack_vector: str               # ex: "API parameter manipulation"
    auth_context: str                # ex: "authenticated", "unauthenticated"
    tech_stack: list[str]            # ex: ["spring", "java", "api"]
    exploit_chain: list[str]         # étapes de l'exploit
    avg_bounty: float                # USD
    frequency: int                   # nombre de rapports similaires
    reproductibility: float          # 0.0–1.0
    ev_score: float                  # calculé : frequency × avg_bounty × reproductibility
    cwe: str                         # ex: "CWE-639"
    severity: str                    # low/medium/high/critical
    source_urls: list[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    @classmethod
    def compute_id(cls, pattern_name: str) -> str:
        return "PAT-" + hashlib.sha256(pattern_name.encode()).hexdigest()[:8].upper()

    def update_ev(self):
        self.ev_score = round(self.frequency * self.avg_bounty * self.reproductibility, 2)


# ─── Cache local JSON ─────────────────────────────────────────────────────────

def _load_cache() -> list[dict]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return []

def _save_cache(patterns: list[dict]):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(patterns, indent=2, ensure_ascii=False), encoding="utf-8")

# ─── Seeds — patterns issus des rapports existants dans BBH_ROOT ──────────────
# ponytail: seed statique basé sur patterns.md existant — zéro LLM requis

SEED_PATTERNS: list[ExploitPattern] = [
    ExploitPattern(
        id="PAT-CORS001",
        pattern_name="CORS misconfiguration with ACAC + authenticated endpoint",
        category="CORS",
        description="ACAO reflects origin + ACAC=true on authenticated API endpoint returning user data",
        attack_vector="Cross-origin request with real session cookie",
        auth_context="authenticated",
        tech_stack=["api", "rest", "saas"],
        exploit_chain=["obtain valid session cookie", "send cross-origin request with credentials",
                       "verify 200 + sensitive data in response body"],
        avg_bounty=1500.0, frequency=23, reproductibility=0.85,
        ev_score=0.0, cwe="CWE-942", severity="medium",
    ),
    ExploitPattern(
        id="PAT-IDOR001",
        pattern_name="IDOR via sequential or UUID object ID",
        category="IDOR",
        description="Object ID predictable or enumerable, missing ownership check in multi-tenant context",
        attack_vector="API parameter manipulation",
        auth_context="authenticated",
        tech_stack=["api", "rest", "saas", "multitenant"],
        exploit_chain=["enumerate object IDs", "access object with different account",
                       "verify cross-account data exposure"],
        avg_bounty=3000.0, frequency=41, reproductibility=0.90,
        ev_score=0.0, cwe="CWE-639", severity="high",
    ),
    ExploitPattern(
        id="PAT-SSRF001",
        pattern_name="SSRF via webhook or URL fetch feature",
        category="SSRF",
        description="URL fetch or webhook endpoint reaching internal services / cloud IMDS",
        attack_vector="URL parameter pointing to internal host",
        auth_context="authenticated",
        tech_stack=["api", "cloud", "aws", "webhook"],
        exploit_chain=["identify URL fetch feature", "point to http://169.254.169.254/",
                       "retrieve cloud metadata / credentials"],
        avg_bounty=5000.0, frequency=18, reproductibility=0.75,
        ev_score=0.0, cwe="CWE-918", severity="critical",
    ),
    ExploitPattern(
        id="PAT-ACT001",
        pattern_name="Spring Boot Actuator exposure + WAF bypass",
        category="Actuator",
        description="Actuator endpoints (env, heapdump, mappings) accessible despite WAF inconsistency",
        attack_vector="Direct request to /actuator/env bypassing WAF path filter",
        auth_context="unauthenticated",
        tech_stack=["spring", "java", "springboot"],
        exploit_chain=["detect Spring via httpx tech-detect", "test /actuator/*",
                       "find WAF bypass via path variation"],
        avg_bounty=2500.0, frequency=12, reproductibility=0.80,
        ev_score=0.0, cwe="CWE-200", severity="high",
    ),
    ExploitPattern(
        id="PAT-AND001",
        pattern_name="Android insecure external storage — health/finance app",
        category="Mobile",
        description="App writes sensitive files to world-readable external storage",
        attack_vector="ADB pull from /sdcard/Download/ after triggering download in-app",
        auth_context="device access",
        tech_stack=["android", "mobile", "health", "finance"],
        exploit_chain=["static analysis (smali grep)", "dynamic ADB validation",
                       "screenshot ls /sdcard/Download/ before+after", "adb pull proof"],
        avg_bounty=1800.0, frequency=8, reproductibility=0.95,
        ev_score=0.0, cwe="CWE-312", severity="medium",
    ),
    ExploitPattern(
        id="PAT-CHAIN001",
        pattern_name="CORS + Open Redirect → ATO chain",
        category="Chain",
        description="Low CORS + Low open redirect combine to full Account Takeover",
        attack_vector="Redirect victim to attacker-controlled origin, extract auth token",
        auth_context="social-engineering-required",
        tech_stack=["web", "saas", "oauth"],
        exploit_chain=["find open redirect", "find CORS reflected", "chain to ATO",
                       "submit as single High/Critical report"],
        avg_bounty=7500.0, frequency=6, reproductibility=0.70,
        ev_score=0.0, cwe="CWE-601", severity="high",
    ),
    ExploitPattern(
        id="PAT-GQL001",
        pattern_name="GraphQL introspection + hidden field + BOLA",
        category="GraphQL",
        description="Introspection exposes hidden fields, BOLA on object access",
        attack_vector="GraphQL query with introspection + cross-account object ID",
        auth_context="authenticated",
        tech_stack=["graphql", "api"],
        exploit_chain=["enable introspection", "find hidden fields",
                       "enumerate object IDs", "cross-account access"],
        avg_bounty=4000.0, frequency=9, reproductibility=0.80,
        ev_score=0.0, cwe="CWE-284", severity="high",
    ),
    # ── Patterns ajoutés depuis session Maya/paymaya (YWH) 2026-06-17 ──
    ExploitPattern(
        id="PAT-JWT001",
        pattern_name="OIDC server advertises alg:none in id_token_signing_alg",
        category="JWT/OIDC",
        description="OIDC /.well-known/openid-configuration lists 'none' in id_token_signing_alg_values_supported. "
                    "Violates OIDC Security BCP (RFC 9700). Client libs trusting metadata may accept unsigned tokens. "
                    "Confirmed on connect.paymaya.com (scopes: transfer, bill, kyc, escrow, balance).",
        attack_vector="Craft JWT with alg:none header, empty signature, modified claims",
        auth_context="unauthenticated",
        tech_stack=["oauth", "oidc", "jwt", "spring", "java", "fintech"],
        exploit_chain=[
            "GET /.well-known/openid-configuration → verify 'none' in id_token_signing_alg_values_supported",
            "Obtain valid client_id (from SDK docs or app traffic)",
            "Request token with alg:none via /token endpoint",
            "Verify if server issues or accepts unsigned token",
        ],
        avg_bounty=1200.0, frequency=14, reproductibility=0.65,
        ev_score=0.0, cwe="CWE-347", severity="medium",
        source_urls=[
            "https://connect.paymaya.com/.well-known/openid-configuration",
            "https://hackerone.com/reports/321937",
            "https://auth0.com/blog/critical-vulnerabilities-in-json-web-token-libraries/",
        ],
    ),
    ExploitPattern(
        id="PAT-COOK001",
        pattern_name="Session cookie missing Secure flag on OAuth/payment server",
        category="Cookie",
        description="JSESSIONID issued without Secure attribute on OAuth/OIDC server. "
                    "Cookie transmitted over HTTP if any *.domain resource serves HTTP, "
                    "or via MitM/downgrade. Higher impact when server manages financial scopes "
                    "(transfer, bill, kyc). Confirmed on connect.paymaya.com.",
        attack_vector="Network interception (MitM) or HTTP subdomain resource → steal JSESSIONID",
        auth_context="unauthenticated",
        tech_stack=["spring", "java", "oauth", "oidc", "fintech", "payment"],
        exploit_chain=[
            "curl -sk https://TARGET/ -D - | grep JSESSIONID",
            "Confirm absence of Secure flag",
            "Verify any *.domain serves HTTP (subdomain scan)",
            "Optionally intercept via MitM on non-HTTPS resource",
        ],
        avg_bounty=350.0, frequency=31, reproductibility=0.99,
        ev_score=0.0, cwe="CWE-614", severity="low",
        source_urls=[
            "https://hackerone.com/reports/204406",
            "https://owasp.org/www-community/controls/SecureCookieAttribute",
        ],
    ),
    ExploitPattern(
        id="PAT-ACT002",
        pattern_name="Spring Boot Actuator /health only — info leak + internal URL",
        category="Actuator",
        description="Only /actuator and /actuator/health accessible without auth. "
                    "Reveals service liveness (UP) and internal http:// URL in _links (HTTPS downgrade info). "
                    "Lower severity than full /env exposure but still reportable. "
                    "Confirmed on paymayabiller-prod.paymaya.com (biller gateway).",
        attack_vector="Direct unauthenticated GET to /actuator/health",
        auth_context="unauthenticated",
        tech_stack=["spring", "java", "springboot", "api", "payment"],
        exploit_chain=[
            "curl https://TARGET/actuator → HTTP 200, lists available endpoints",
            "curl https://TARGET/actuator/health → {status:UP}",
            "Note: _links.self.href uses http:// (internal URL scheme leak)",
            "Enumerate /actuator/* — confirm only health exposed",
        ],
        avg_bounty=400.0, frequency=19, reproductibility=0.99,
        ev_score=0.0, cwe="CWE-306", severity="low",
        source_urls=[
            "https://paymayabiller-prod.paymaya.com/actuator/health",
            "https://hackerone.com/reports/780021",
        ],
    ),
]

# Calculer EV scores
for _p in SEED_PATTERNS:
    _p.update_ev()


# ─── Ingest HackerOne Hacktivity public ───────────────────────────────────────

def ingest_h1_hacktivity(limit: int = 50) -> int:
    """
    Scrappe les rapports publics HackerOne Hacktivity (pas d'auth requise).
    Normalise en ExploitPattern et fusionne dans le cache BBRIL.
    Retourne le nombre de nouveaux patterns ajoutés.
    """
    cache = _load_cache()
    existing_ids = {p["id"] for p in cache}
    new_count = 0

    try:
        # HackerOne GraphQL public endpoint
        query = json.dumps({
            "query": """
            query HacktivityPageQuery($querystring: String, $orderBy: HacktivityItemOrderInput,
                                       $secureOrderBy: FiltersHacktivityItemFilterOrder,
                                       $where: FiltersHacktivityItemFilterInput, $count: Int) {
                hacktivity_items(
                    first: $count
                    orderBy: $orderBy
                    secureOrderBy: $secureOrderBy
                    where: $where
                    query: $querystring
                ) {
                    nodes {
                        ... on HacktivityItem {
                            type: __typename
                            ... on Disclosed {
                                report {
                                    title
                                    disclosed_at
                                    severity { rating }
                                    vulnerability_information
                                    weakness { name external_id }
                                    bounty_amount
                                    url
                                }
                            }
                        }
                    }
                }
            }""",
            "variables": {
                "count": limit,
                "where": {"disclosed_at": {"_gt": "2024-01-01"}},
                "orderBy": {"field": "popular", "direction": "DESC"},
            }
        }).encode()

        req = urllib.request.Request(
            "https://hackerone.com/graphql",
            data=query,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
                "X-Auth-Token": "",
            }
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        items = data.get("data", {}).get("hacktivity_items", {}).get("nodes", [])

        for item in items:
            report = item.get("report", {})
            if not report:
                continue
            title    = report.get("title", "")
            severity = (report.get("severity") or {}).get("rating", "medium")
            bounty   = float(report.get("bounty_amount") or 0)
            weakness = (report.get("weakness") or {})
            cwe      = weakness.get("external_id", "CWE-0")
            vuln_name = weakness.get("name", "Unknown")
            url      = report.get("url", "")

            if not title or bounty < 100:
                continue   # skip non-bounty or uninteresting

            pid = ExploitPattern.compute_id(title[:60])
            if pid in existing_ids:
                continue

            category = _classify_category(title + " " + vuln_name)
            tech_stack = _extract_tech(title + " " + report.get("vulnerability_information", ""))

            pattern = ExploitPattern(
                id=pid,
                pattern_name=title[:120],
                category=category,
                description=vuln_name,
                attack_vector=_extract_vector(title),
                auth_context="authenticated",
                tech_stack=tech_stack,
                exploit_chain=[title],
                avg_bounty=bounty,
                frequency=1,
                reproductibility=0.8,
                ev_score=0.0,
                cwe=cwe,
                severity=severity.lower(),
                source_urls=[url] if url else [],
            )
            pattern.update_ev()
            cache.append(asdict(pattern))
            existing_ids.add(pid)
            new_count += 1

    except Exception as e:
        # Réseau ou API down → pas bloquant
        import logging
        logging.getLogger("BBRIL").debug(f"H1 ingest err: {e}")

    _save_cache(cache)

    # Sync dans nexus_bridge memory
    try:
        from .nexus_bridge import memory_store
        for p in cache[-new_count:] if new_count else []:
            memory_store(f"bbril_{p['id']}", json.dumps(p))
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    return new_count


# ─── Query patterns pour un target ───────────────────────────────────────────

def get_patterns_for_target(
    tech_stack: list[str] | None = None,
    categories: list[str] | None = None,
    min_ev: float = 0.0,
    limit: int = 5,
) -> list[ExploitPattern]:
    """
    Retourne les patterns les plus rentables pour un tech_stack donné.
    Utilisé avant P5 pour orienter le vuln scan.
    """
    # Charger seeds + cache
    all_patterns = list(SEED_PATTERNS)
    cache = _load_cache()
    for p in cache:
        try:
            obj = ExploitPattern(**p)
            if obj.id not in {x.id for x in all_patterns}:
                all_patterns.append(obj)
        except Exception:
            continue

    # Filtrer
    tech_lower   = [t.lower() for t in (tech_stack or [])]
    cat_lower    = [c.lower() for c in (categories or [])]

    scored = []
    for pat in all_patterns:
        if pat.ev_score < min_ev:
            continue
        if cat_lower and pat.category.lower() not in cat_lower:
            continue
        if tech_lower:
            match = sum(1 for t in tech_lower if any(t in ts for ts in pat.tech_stack))
            if match == 0 and tech_lower:
                continue
        scored.append((pat.ev_score, pat))

    scored.sort(reverse=True)
    return [p for _, p in scored[:limit]]


def format_patterns_for_prompt(patterns: list[ExploitPattern]) -> str:
    """Formate les patterns pour injection dans un prompt agent (compact)."""
    lines = ["[BBRIL — Exploit Intelligence]"]
    for p in patterns:
        lines.append(
            f"• {p.category} | {p.pattern_name} | "
            f"avg_bounty=${p.avg_bounty:.0f} | ev={p.ev_score:.0f} | cwe={p.cwe}"
        )
        lines.append(f"  vector: {p.attack_vector}")
        lines.append(f"  chain: {' → '.join(p.exploit_chain[:3])}")
    return "\n".join(lines)


# ─── Classification helpers ───────────────────────────────────────────────────

_CATEGORY_KEYWORDS = {
    "IDOR":     ["idor", "insecure direct", "object reference", "bola", "bfla"],
    "SSRF":     ["ssrf", "server-side request", "request forgery", "metadata"],
    "CORS":     ["cors", "cross-origin", "acao"],
    "XSS":      ["xss", "cross-site scripting", "script inject"],
    "SQLi":     ["sqli", "sql injection", "sql", "blind sqli"],
    "RCE":      ["rce", "remote code", "command injection", "code execution"],
    "LFI":      ["lfi", "local file", "path traversal", "directory traversal"],
    "SSTI":     ["ssti", "template injection", "server-side template"],
    "Auth":     ["auth bypass", "authentication bypass", "jwt", "oauth", "token"],
    "Takeover": ["takeover", "subdomain takeover", "dangling dns"],
    "Mobile":   ["android", "ios", "apk", "mobile", "insecure storage"],
    "GraphQL":  ["graphql", "introspection", "graphql injection"],
    "Chain":    ["chain", "combination", "escalat"],
    "Actuator": ["actuator", "spring boot", "heapdump"],
}

def _classify_category(text: str) -> str:
    text_lower = text.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return "Other"

_TECH_KEYWORDS = ["java", "spring", "python", "django", "rails", "ruby", "php",
                  "node", "react", "angular", "vue", "graphql", "rest", "soap",
                  "android", "ios", "aws", "gcp", "azure", "kubernetes", "docker",
                  "nginx", "apache", "wordpress", "oauth", "saml", "jwt"]

def _extract_tech(text: str) -> list[str]:
    text_lower = text.lower()
    return [t for t in _TECH_KEYWORDS if t in text_lower] or ["web"]

def _extract_vector(title: str) -> str:
    title_lower = title.lower()
    if "parameter" in title_lower or "param" in title_lower:
        return "Parameter manipulation"
    if "header" in title_lower:
        return "HTTP header injection"
    if "upload" in title_lower:
        return "File upload"
    if "redirect" in title_lower:
        return "Open redirect"
    if "api" in title_lower or "endpoint" in title_lower:
        return "API endpoint"
    return "Web request"


# ─── CLI self-check ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    patterns = get_patterns_for_target(tech_stack=["api", "spring"], limit=3)
    assert len(patterns) > 0, "Doit retourner au moins 1 pattern"
    assert all(p.ev_score > 0 for p in patterns), "EV score doit être > 0"

    print("bbril_pipeline: OK")
    print(format_patterns_for_prompt(patterns))
