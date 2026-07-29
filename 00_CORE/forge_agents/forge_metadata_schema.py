"""
forge_metadata_schema.py — Universal Metadata Schema for Forge Data
=====================================================================
Every piece of data in the Forge gets this metadata.
Saves 90% of search/discovery time.

Metadata Layers:
  1. IDENTITY    — what is it?
  2. TEMPORAL    — when?
  3. PROVENANCE  — who/where?
  4. QUALITY     — how good?
  5. USAGE       — how often?
  6. RELATIONAL  — what connects?
  7. COST        — what price?
  8. SEMANTIC    — what meaning?
"""

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class DataLayer(str, Enum):
    """Memory layer in the Forge architecture."""
    L0_KERNEL = "L0_kernel"      # RAM, in-process
    L1_HOT = "L1_hot"            # Redis cache
    L2_WARM = "L2_warm"          # TurboVec 4-bit index
    L3_DEEP = "L3_deep"          # PostgreSQL
    L4_COLD = "L4_cold"          # Markdown/filesystem


class QualityStatus(str, Enum):
    """Quality verification status."""
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    APPROVED = "approved"      # MiroFish consensus ≥ 0.7
    REJECTED = "rejected"      # MiroFish score < 5
    DEPRECATED = "deprecated"  # Outdated
    ARCHIVED = "archived"      # 30+ days unused


class RelationType(str, Enum):
    """Types of relations between data."""
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    SIMILAR_TO = "similar_to"
    REPLACES = "replaces"
    EXTENDS = "extends"
    CONTRADICTS = "contradicts"
    REQUIRES = "requires"
    PRODUCES = "produces"


@dataclass
class IdentityMeta:
    """Layer 1: What is this data?"""
    id: str = ""
    name: str = ""
    prefix: str = ""           # SKL, FND, TKL, etc.
    domain: str = ""           # sec, dev, res, mkt, dat, opt, frg, gen
    data_type: str = ""        # skill, finding, token_log, etc.
    slug: str = ""             # human-readable short name
    version: int = 1
    description: str = ""      # auto-generated summary
    tags: list[str] = field(default_factory=list)  # searchable tags
    keywords: list[str] = field(default_factory=list)  # extracted keywords
    category: str = ""         # broad category
    subcategory: str = ""      # narrow category


@dataclass
class TemporalMeta:
    """Layer 2: When?"""
    created_at: str = ""       # ISO timestamp
    modified_at: str = ""      # ISO timestamp
    accessed_at: str = ""      # ISO timestamp
    expires_at: str = ""       # ISO timestamp (optional)
    ttl_days: int = 0          # 0 = never expires
    age_days: float = 0.0      # computed: now - created
    staleness: str = ""        # fresh / aging / stale / expired


@dataclass
class ProvenanceMeta:
    """Layer 3: Who/where?"""
    source_agent: str = ""     # agent that created this
    source_session: str = ""   # session ID
    source_task: str = ""      # task description
    source_file: str = ""      # original filename
    source_node: str = ""      # graph node that produced it
    source_provider: str = ""  # LLM provider used
    source_model: str = ""     # model name
    forge_version: str = ""    # forge version when created


@dataclass
class QualityMeta:
    """Layer 4: How good?"""
    score: float = 0.0         # 0-10 scale
    confidence: float = 0.0    # 0-1 scale
    consensus: float = 0.0     # MiroFish consensus
    status: str = "unverified" # QualityStatus value
    verified_by: str = ""      # agent/method that verified
    verified_at: str = ""      # when verified
    issues: list[str] = field(default_factory=list)  # known issues
    improvements: list[str] = field(default_factory=list)  # suggestions


@dataclass
class UsageMeta:
    """Layer 5: How often?"""
    uses_count: int = 0
    last_used_at: str = ""
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0  # computed
    avg_response_ms: float = 0.0
    popular_queries: list[str] = field(default_factory=list)  # top 5 queries


@dataclass
class RelationalMeta:
    """Layer 6: What connects?"""
    related_ids: list[str] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)  # [{id, type, strength}]
    parent_id: str = ""
    children_ids: list[str] = field(default_factory=list)
    supersedes_id: str = ""    # replaces this older version
    contradicts_ids: list[str] = field(default_factory=list)


@dataclass
class CostMeta:
    """Layer 7: What price?"""
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    cost_usd: float = 0.0
    compute_time_ms: int = 0
    provider: str = ""
    model: str = ""
    cache_hit: bool = False
    cost_efficiency: float = 0.0  # quality / cost ratio


@dataclass
class SemanticMeta:
    """Layer 8: What meaning?"""
    embedding_hash: str = ""   # SimHash for dedup
    topic_cluster: str = ""    # auto-detected topic
    sentiment: str = ""        # positive/negative/neutral
    language: str = "fr"       # detected language
    complexity: str = ""       # simple/medium/complex
    action_type: str = ""      # create/read/update/delete/analyze
    entities: list[str] = field(default_factory=list)  # extracted entities
    summary: str = ""          # one-line auto-summary


@dataclass
class ForgeMetadata:
    """Complete metadata for any Forge data."""
    identity: IdentityMeta = field(default_factory=IdentityMeta)
    temporal: TemporalMeta = field(default_factory=TemporalMeta)
    provenance: ProvenanceMeta = field(default_factory=ProvenanceMeta)
    quality: QualityMeta = field(default_factory=QualityMeta)
    usage: UsageMeta = field(default_factory=UsageMeta)
    relational: RelationalMeta = field(default_factory=RelationalMeta)
    cost: CostMeta = field(default_factory=CostMeta)
    semantic: SemanticMeta = field(default_factory=SemanticMeta)

    def to_dict(self) -> dict:
        """Convert to flat dict for JSON storage."""
        d = {}
        for layer_name, layer in [
            ("identity", self.identity),
            ("temporal", self.temporal),
            ("provenance", self.provenance),
            ("quality", self.quality),
            ("usage", self.usage),
            ("relational", self.relational),
            ("cost", self.cost),
            ("semantic", self.semantic),
        ]:
            for k, v in asdict(layer).items():
                # Flatten with layer prefix for top-level fields
                if v and v != "" and v != 0 and v != 0.0 and v != [] and v != False:
                    d[f"{layer_name}_{k}"] = v
                # Also store without prefix for common fields
                if k in ("id", "name", "tags", "score", "status", "created_at"):
                    d[k] = v
        return d

    def to_compact(self) -> dict:
        """Compact version for embedding in files (essential fields only)."""
        return {
            "_meta": {
                "id": self.identity.id,
                "name": self.identity.name,
                "type": self.identity.data_type,
                "domain": self.identity.domain,
                "tags": self.identity.tags,
                "score": self.quality.score,
                "status": self.quality.status,
                "uses": self.usage.uses_count,
                "created": self.temporal.created_at,
                "source": self.provenance.source_agent,
                "cluster": self.semantic.topic_cluster,
                "hash": self.semantic.embedding_hash,
            }
        }

    @staticmethod
    def auto_enrich(data: dict, content: str = "", data_type: str = "") -> "ForgeMetadata":
        """
        Auto-generate metadata from data content.
        Zero LLM — deterministic extraction only.
        """
        import re

        meta = ForgeMetadata()

        # Identity
        meta.identity.id = data.get("id", "")
        meta.identity.name = data.get("name", data.get("title", ""))
        meta.identity.data_type = data_type
        meta.identity.tags = data.get("tags", data.get("trigger_keywords", []))

        # Extract keywords from content
        if content:
            words = re.findall(r'\w{4,}', content.lower())
            stop = {"dans", "pour", "avec", "cette", "sont", "mais", "plus", "comme", "tout", "that", "this", "with", "from", "have", "been"}
            keywords = list(dict.fromkeys(w for w in words if w not in stop))[:20]
            meta.identity.keywords = keywords

        # Temporal
        now = datetime.now().isoformat()
        meta.temporal.created_at = data.get("created_at", now)
        meta.temporal.modified_at = now

        # Quality
        meta.quality.score = data.get("score", data.get("avg_score", 0))
        meta.quality.consensus = data.get("consensus", data.get("mirofish_approval", {}).get("consensus", 0))
        meta.quality.status = data.get("status", "unverified")

        # Usage
        perf = data.get("performance", {})
        meta.usage.uses_count = perf.get("uses", 0)
        meta.usage.last_used_at = perf.get("last_used", "")

        # Provenance
        meta.provenance.source_agent = data.get("source_agent", data.get("agent", ""))
        meta.provenance.source_file = data.get("retro_source", "")

        # Semantic
        if content:
            meta.semantic.embedding_hash = hashlib.md5(content.encode()).hexdigest()[:16]
            meta.semantic.language = "fr" if any(w in content.lower() for w in ("les", "des", "une", "est", "sont")) else "en"

            # Auto-detect complexity
            if len(content) > 2000:
                meta.semantic.complexity = "complex"
            elif len(content) > 500:
                meta.semantic.complexity = "medium"
            else:
                meta.semantic.complexity = "simple"

            # Auto-detect action type
            action_keywords = {
                "create": ["create", "créer", "build", "construire", "generate"],
                "analyze": ["analyze", "analyser", "scan", "audit", "review"],
                "optimize": ["optimize", "optimiser", "improve", "reduce"],
                "fix": ["fix", "repair", "correct", "debug", "troubleshoot"],
            }
            content_lower = content.lower()
            for action, keywords in action_keywords.items():
                if any(kw in content_lower for kw in keywords):
                    meta.semantic.action_type = action
                    break

            # Auto-summary (first meaningful sentence)
            sentences = [s.strip() for s in re.split(r'[.!?]', content) if len(s.strip()) > 20]
            if sentences:
                meta.semantic.summary = sentences[0][:150]

        return meta


def enrich_file(path: str, data_type: str = "") -> dict:
    """
    Enrich a file with full metadata.
    Returns the enriched data dict.
    """
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return {}

    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return data

    content = json.dumps(data, ensure_ascii=False)
    meta = ForgeMetadata.auto_enrich(data, content, data_type or p.stem)

    # Merge into data
    compact = meta.to_compact()
    data.update(compact)

    return data
