"""
forge_kernel.py — V6 Kernel Engine
Extrait le plus petit point commun (kernel) d'une tâche.
Tous les agents partagent CE kernel → zéro re-parsing individuel.

Architecture V6 :
  USER REQUEST → KERNEL EXTRACTION → SHARED TO ALL AGENTS

Le kernel contient :
  - core_intent : objectif minimal en 1 phrase
  - entities : entités clés (technos, noms, concepts)
  - constraints : contraintes explicites
  - required_capabilities : ce que la forge doit mobiliser
  - confidence : confiance dans l'extraction (0.0 → 1.0)
  - evidence : sources/justifications
"""

from __future__ import annotations
import json
import hashlib
import datetime
from typing import Any, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class Kernel:
    """Kernel = plus petit point commun d'une tâche. Partagé entre tous les agents."""
    core_intent: str = ""
    entities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    domain: str = ""                    # ex: "web_dev", "security", "data", "product"
    complexity_estimate: float = 0.5    # 0.0 (trivial) → 1.0 (extrême)
    confidence: float = 0.0             # confiance extraction
    evidence: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    kernel_id: str = ""                 # hash unique
    created_at: str = ""
    token_cost: int = 0                 # tokens utilisés pour l'extraction

    def __post_init__(self):
        if not self.kernel_id:
            raw = f"{self.core_intent}|{'|'.join(self.entities)}|{self.domain}"
            self.kernel_id = hashlib.sha256(raw.encode()).hexdigest()[:12]
        if not self.created_at:
            self.created_at = datetime.datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_nmp(self) -> str:
        """Format NMP compact pour inter-agent."""
        caps = ",".join(self.required_capabilities[:5])
        ents = ",".join(self.entities[:5])
        return (
            f"KERNEL|EXTRACTOR|ALL|"
            f"intent={self.core_intent[:120]}|"
            f"domain={self.domain}|"
            f"entities={ents}|"
            f"caps={caps}|"
            f"complexity={self.complexity_estimate:.2f}|"
            f"confidence={self.confidence:.2f}"
        )

    def to_checkpoint(self) -> dict:
        """Checkpoint JSON minimal (anti-hallucination)."""
        return {
            "goal": self.core_intent,
            "known_facts": self.evidence,
            "assumptions": self.assumptions,
            "unknowns": self.unknowns,
            "sources": self.sources,
            "confidence": self.confidence,
        }

    def is_stale(self, max_age_seconds: int = 3600) -> bool:
        """Vérifie si le kernel est périmé."""
        try:
            created = datetime.datetime.fromisoformat(self.created_at)
            return (datetime.datetime.now() - created).total_seconds() > max_age_seconds
        except Exception:
            return True

    def capability_coverage(self, available: list[str]) -> float:
        """Quelle fraction des capabilities requises sont disponibles ?"""
        if not self.required_capabilities:
            return 1.0
        avail_set = set(c.lower() for c in available)
        needed = set(c.lower() for c in self.required_capabilities)
        return len(avail_set & needed) / len(needed) if needed else 1.0


# ── Domain Detection (rapide, sans LLM) ──────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "web_dev": ["website", "landing page", "react", "nextjs", "html", "css", "frontend", "backend", "api rest", "saas"],
    "security": ["pentest", "vulnerability", "cve", "exploit", "hack", "security", "audit", "owasp", "brute"],
    "data": ["dataset", "csv", "pandas", "analysis", "visualization", "pipeline", "etl", "scraper", "scraping"],
    "product": ["saas", "mvp", "feature", "user", "pricing", "launch", "onboarding", "conversion"],
    "bot": ["telegram", "discord", "bot", "webhook", "command", "handler"],
    "devops": ["docker", "deploy", "ci/cd", "nginx", "server", "kubernetes", "monitoring"],
    "design": ["ui", "ux", "figma", "design", "mockup", "wireframe", "brand", "logo"],
    "ai_ml": ["model", "training", "fine-tune", "llm", "embedding", "rag", "inference", "benchmark"],
    "email": ["email", "newsletter", "campaign", "smtp", "template", "inbox"],
    "agency": ["client", "prospect", "outreach", "acquisition", "lead", "conversion", "crm"],
}

# Capability → domain mapping
_CAPABILITY_HINTS: dict[str, str] = {
    "scrape": "data", "analyze": "data", "deploy": "devops",
    "design": "design", "code": "web_dev", "secure": "security",
    "automate": "devops", "research": "data", "market": "product",
}


def detect_domain(task: str) -> tuple[str, float]:
    """Détection rapide du domaine par mots-clés. Retourne (domain, confidence)."""
    task_lower = task.lower()
    scores: dict[str, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in task_lower)
        if score:
            scores[domain] = score

    if not scores:
        return "general", 0.3

    best = max(scores, key=scores.get)
    total = sum(scores.values())
    conf = min(scores[best] / max(total, 1), 1.0)
    return best, round(conf, 2)


def detect_capabilities(task: str) -> list[str]:
    """Détecte les capabilities nécessaires par mots-clés."""
    task_lower = task.lower()
    caps = []
    for cap, hint in _CAPABILITY_HINTS.items():
        if cap in task_lower:
            caps.append(hint)
    # Patterns supplémentaires
    if any(w in task_lower for w in ["créer", "build", "construire", "develop"]):
        caps.append("build")
    if any(w in task_lower for w in ["test", "verify", "validate"]):
        caps.append("verify")
    if any(w in task_lower for w in ["optimize", "improve", "ameliorer"]):
        caps.append("optimize")
    return list(set(caps)) or ["general"]


def estimate_complexity(task: str) -> float:
    """Estimation rapide de la complexité (0.0 → 1.0)."""
    indicators = {
        "length": min(len(task) / 500, 0.3),
        "multi_step": 0.2 if any(w in task.lower() for w in ["then", "ensuite", "puis", "after", "et aussi"]) else 0.0,
        "integration": 0.15 if any(w in task.lower() for w in ["integrate", "connect", "api", "mcp", "webhook"]) else 0.0,
        "security": 0.1 if any(w in task.lower() for w in ["secure", "auth", "encrypt", "token"]) else 0.0,
        "data": 0.1 if any(w in task.lower() for w in ["dataset", "database", "migration", "scrape"]) else 0.0,
        "vague": 0.15 if len(task.split()) < 5 else 0.0,
    }
    return round(min(sum(indicators.values()), 1.0), 2)


# ── Kernel Extractor (fast path — no LLM) ────────────────────────────────────

def extract_kernel_fast(task: str) -> Kernel:
    """
    Extraction rapide du kernel SANS LLM.
    Pour les tâches simples (< seuil complexité), ce path suffit.
    """
    domain, domain_conf = detect_domain(task)
    capabilities = detect_capabilities(task)
    complexity = estimate_complexity(task)

    # Entities = mots significatifs (>3 chars, pas de stopwords)
    _stopwords = frozenset([
        "the", "and", "for", "that", "this", "with", "from", "have", "will",
        "been", "they", "their", "would", "could", "should", "about", "which",
        "when", "what", "there", "than", "them", "then", "into", "also",
        "just", "more", "some", "very", "your", "does", "done", "make",
        "le", "la", "les", "de", "du", "des", "un", "une", "et", "est",
        "que", "qui", "dans", "pour", "par", "sur", "pas", "avec", "ce",
        "il", "elle", "on", "ne", "se", "au", "aux", "ou", "son", "sa",
        "ses", "leur", "cette", "tout", "mais", "comme", "nous", "vous",
        "ils", "elles", "être", "avoir", "faire", "je", "tu", "me", "te",
        "lui", "y", "en", "si", "mon", "ton", "mes", "tes", "nos", "vos",
    ])
    words = [w.strip(".,;:!?()[]{}\"'") for w in task.lower().split()]
    entities = [w for w in words if len(w) > 3 and w not in _stopwords and not w.isdigit()]
    entities = list(dict.fromkeys(entities))[:15]  # dedupe, limit

    # Intent = première phrase significative
    sentences = [s.strip() for s in task.replace("\n", ". ").split(".") if len(s.strip()) > 10]
    intent = sentences[0] if sentences else task[:120]

    return Kernel(
        core_intent=intent,
        entities=entities,
        constraints=[],
        required_capabilities=capabilities,
        domain=domain,
        complexity_estimate=complexity,
        confidence=domain_conf,
        evidence=[],
        assumptions=[],
        unknowns=[],
        sources=["fast_extract"],
    )


# ── Kernel Cache (évite re-extraction) ───────────────────────────────────────

_kernel_cache: dict[str, Kernel] = {}


def get_or_extract_kernel(task: str) -> Kernel:
    """Récupère un kernel en cache ou l'extrait. Anti-duplication V6."""
    task_hash = hashlib.md5(task.encode()).hexdigest()[:16]
    if task_hash in _kernel_cache:
        cached = _kernel_cache[task_hash]
        if not cached.is_stale():
            return cached
    kernel = extract_kernel_fast(task)
    _kernel_cache[task_hash] = kernel
    return kernel


def invalidate_kernel_cache():
    """Vide le cache kernel (appelé en début de session)."""
    _kernel_cache.clear()


# ── Checkpoint anti-hallucination ─────────────────────────────────────────────

def hallucination_checkpoint(kernel: Kernel) -> dict:
    """
    Génère un checkpoint anti-hallucination.
    À injecter tous les X tokens dans le contexte agent.
    """
    return {
        "goal": kernel.core_intent,
        "known_facts": kernel.evidence,
        "assumptions": kernel.assumptions,
        "unknowns": kernel.unknowns,
        "sources": kernel.sources,
        "confidence": kernel.confidence,
    }


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    test_task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Build a Telegram hotel bot with booking API integration"
    kernel = extract_kernel_fast(test_task)
    print(json.dumps(kernel.to_dict(), indent=2, ensure_ascii=False))
    print(f"\nNMP: {kernel.to_nmp()}")
    print(f"Checkpoint: {json.dumps(kernel.to_checkpoint(), indent=2)}")
