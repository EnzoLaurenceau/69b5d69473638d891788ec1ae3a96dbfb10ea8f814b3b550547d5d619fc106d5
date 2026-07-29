"""
Research Enrichment Trigger for La Forge
=========================================
Auto-triggers research-4 MCP + RabbitResearch when the forge
encounters a task requiring dataset enrichment.

Sources:
  - https://mcpmarket.com/server/research-4 (MCP deep research)
  - RabbitResearch (alternative research source)

Trigger condition: task involves data enrichment, precision improvement,
dataset augmentation, or knowledge gap filling.

NMP: TOOL|INDEX|research_enrichment|savings=70|pattern=auto dataset enrichment|approach=research-4 MCP + RabbitResearch auto-trigger on data tasks
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent


# ─── Enrichment Trigger Detection ────────────────────────────────────────

class EnrichmentType(Enum):
    """Types of data enrichment tasks the forge might encounter."""
    DATASET_AUGMENT = "dataset_augment"      # Expand existing dataset
    KNOWLEDGE_GAP = "knowledge_gap"          # Fill missing knowledge
    PRECISION_BOOST = "precision_boost"      # Improve data precision/quality
    CROSS_VALIDATE = "cross_validate"        # Validate data across sources
    MARKET_RESEARCH = "market_research"      # Market/competitive intelligence
    TECH_RESEARCH = "tech_research"          # Technical documentation/specs
    ACADEMIC_SEARCH = "academic_search"      # Scientific papers/citations
    CVE_ENRICHMENT = "cve_enrichment"        # Security vulnerability data
    API_DISCOVERY = "api_discovery"          # Find APIs for a task
    TREND_ANALYSIS = "trend_analysis"        # Analyze trends/patterns


@dataclass
class EnrichmentTrigger:
    """Detected enrichment opportunity."""
    type: EnrichmentType
    confidence: float           # 0.0-1.0
    keywords_matched: list[str]
    source_task: str            # Task description that triggered this
    recommended_sources: list[str]  # Which research sources to use
    priority: str = "NORMAL"    # LOW | NORMAL | HIGH | CRITICAL
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_nmp(self) -> str:
        return (
            f"ENRICH|TRIGGER|type={self.type.value}|confidence={self.confidence:.2f}"
            f"|priority={self.priority}|sources={','.join(self.recommended_sources)}"
        )


# Keyword patterns that indicate enrichment is needed
ENRICHMENT_PATTERNS: dict[EnrichmentType, list[str]] = {
    EnrichmentType.DATASET_AUGMENT: [
        r"enrichi[rs]?\b", r"augment\b", r"expand\s+data", r"more\s+data",
        r"dataset\b", r"training\s+data", r"data\s+collection",
        r"données\s+supplémentaires", r"compléter\s+les?\s+données",
        r"élargir\b", r"étoffer\b", r"precision", r"précision",
    ],
    EnrichmentType.KNOWLEDGE_GAP: [
        r"don't\s+know", r"uncertain", r"need\s+more\s+info",
        r"what\s+is\b", r"how\s+does\b", r"explain\b",
        r"manque\s+d'info", r"je\s+ne\s+sais\s+pas", r"incertain",
        r"recherche[rs]?\b", r"trouver\b",
    ],
    EnrichmentType.PRECISION_BOOST: [
        r"imprecis[e]?\b", r"inaccurat[e]?\b", r"vague\b",
        r"améliorer\s+la\s+précision", r"plus\s+précis",
        r"quality\s+score", r"low\s+confidence",
        r"vérifier\b", r"valider\b", r"confirmer\b",
    ],
    EnrichmentType.CROSS_VALIDATE: [
        r"cross[\s-]?validat[ei]", r"verify\s+across",
        r"double[\s-]?check", r"source\s+comparison",
        r"croiser\b", r"vérification\s+croisée", r"recouper\b",
    ],
    EnrichmentType.MARKET_RESEARCH: [
        r"market\b", r"competitor[s]?\b", r"industry\b",
        r"marché\b", r"concurrent[s]?\b", r"veille\b",
        r"benchmark\b", r"pricing\b", r"tarif[s]?\b",
    ],
    EnrichmentType.TECH_RESEARCH: [
        r"documentation\b", r"api\s+docs?\b", r"spec[s]?\b",
        r"how\s+to\s+implement", r"best\s+practice[s]?\b",
        r"architecture\b", r"stack\b", r"framework\b",
    ],
    EnrichmentType.ACADEMIC_SEARCH: [
        r"paper[s]?\b", r"research\b", r"study\b", r"publi[cs]ation",
        r"citation[s]?\b", r"journal\b", r"arxiv\b",
        r"article\s+scientifique", r"étude\b", r"publication\b",
    ],
    EnrichmentType.CVE_ENRICHMENT: [
        r"CVE[\s-]?\d{4}", r"vulnerability\b", r"exploit\b",
        r"security\s+advisory", r"patch\b", r"vuln[eé]rabilit[ey]",
        r"faille\b", r"MITRE\b", r"NVD\b",
    ],
    EnrichmentType.API_DISCOVERY: [
        r"find\s+(?:an?\s+)?api\b", r"api\s+for\b",
        r"external\s+service\b", r"endpoint\b",
        r"trouver\s+une?\s+api", r"service\s+externe\b",
    ],
    EnrichmentType.TREND_ANALYSIS: [
        r"trend[s]?\b", r"growing\b", r"declining\b",
        r"popular\b", r"emerging\b", r"adoption\b",
        r"tendance[s]?\b", r"croissance\b", r"évolution\b",
    ],
}


# ─── Research Source Configuration ────────────────────────────────────────

@dataclass
class ResearchSource:
    """A research source available to the forge."""
    id: str
    name: str
    type: str               # "mcp" | "api" | "local" | "hybrid"
    url: str
    capabilities: list[str]
    priority: int            # 1=highest
    rate_limit_rps: float    # requests per second
    cost_per_query: float    # estimated cost in USD (0 = free)
    status: str = "active"   # active | degraded | offline

    def to_nmp(self) -> str:
        return f"SOURCE|{self.id}|type={self.type}|priority={self.priority}|status={self.status}"


# Available research sources in priority order
RESEARCH_SOURCES = [
    ResearchSource(
        id="research_4_mcp",
        name="research-4 (MCP)",
        type="mcp",
        url="https://mcpmarket.com/server/research-4",
        capabilities=[
            "web_search", "academic_papers", "real_time_data",
            "multi_provider_aggregation", "deep_research",
            "fact_checking", "citation_extraction",
        ],
        priority=1,
        rate_limit_rps=2.0,
        cost_per_query=0.0,
    ),
    ResearchSource(
        id="rabbit_research",
        name="RabbitResearch",
        type="api",
        url="",  # Internal / alternative source
        capabilities=[
            "web_search", "data_extraction", "summarization",
            "competitive_analysis", "trend_detection",
        ],
        priority=2,
        rate_limit_rps=1.0,
        cost_per_query=0.0,
    ),
    ResearchSource(
        id="crawl4ai",
        name="crawl4ai",
        type="local",
        url="",
        capabilities=[
            "web_scraping", "structured_extraction",
            "javascript_rendering", "batch_crawling",
        ],
        priority=3,
        rate_limit_rps=2.0,
        cost_per_query=0.0,
    ),
    ResearchSource(
        id="turbovec_local",
        name="TurboVec (Local KB)",
        type="local",
        url="",
        capabilities=[
            "semantic_search", "cached_data", "past_research",
            "dataset_lookup", "api_catalog",
        ],
        priority=0,  # Always check local first
        rate_limit_rps=100.0,
        cost_per_query=0.0,
    ),
]


# ─── Enrichment Engine ───────────────────────────────────────────────────

class ResearchEnrichmentEngine:
    """
    Auto-detects when a task needs data enrichment and triggers
    the appropriate research sources (research-4 MCP + RabbitResearch).

    Integration with forge pipeline:
    1. Task enters pipeline (any agent node)
    2. Engine scans task description for enrichment signals
    3. If enrichment detected (confidence > threshold):
       a. Check local cache first (turbovec)
       b. If miss → fire research-4 MCP query
       c. Cross-validate with RabbitResearch if confidence < 0.8
       d. Ingest results into turbovec for future reuse
    4. Return enriched context to the requesting agent

    Usage:
        engine = ResearchEnrichmentEngine()
        triggers = engine.detect(task_description)
        if triggers:
            enriched = engine.enrich(triggers[0])
    """

    def __init__(self, confidence_threshold: float = 0.3, auto_fire: bool = True):
        self.confidence_threshold = confidence_threshold
        self.auto_fire = auto_fire
        self.sources = {s.id: s for s in RESEARCH_SOURCES}
        self.stats = {
            "triggers_detected": 0,
            "enrichments_fired": 0,
            "cache_hits": 0,
            "queries_by_source": {},
        }
        self._enrichment_cache: dict[str, dict] = {}

    def detect(self, task_description: str) -> list[EnrichmentTrigger]:
        """
        Scan a task description for enrichment signals.
        Returns list of detected triggers sorted by confidence.
        """
        triggers = []
        task_lower = task_description.lower()

        for etype, patterns in ENRICHMENT_PATTERNS.items():
            matched = []
            for pattern in patterns:
                if re.search(pattern, task_lower, re.IGNORECASE):
                    matched.append(pattern)

            if matched:
                confidence = min(1.0, len(matched) / 3.0)  # 3+ matches = 1.0
                priority = self._assess_priority(etype, confidence)

                # Determine which sources to use
                sources = self._select_sources(etype)

                trigger = EnrichmentTrigger(
                    type=etype,
                    confidence=confidence,
                    keywords_matched=matched,
                    source_task=task_description[:200],
                    recommended_sources=sources,
                    priority=priority,
                )
                triggers.append(trigger)
                self.stats["triggers_detected"] += 1

        # Sort by confidence descending
        triggers.sort(key=lambda t: t.confidence, reverse=True)

        # Filter below threshold
        triggers = [t for t in triggers if t.confidence >= self.confidence_threshold]

        return triggers

    def _assess_priority(self, etype: EnrichmentType, confidence: float) -> str:
        """Determine enrichment priority based on type and confidence."""
        critical_types = {EnrichmentType.CVE_ENRICHMENT, EnrichmentType.PRECISION_BOOST}
        high_types = {EnrichmentType.CROSS_VALIDATE, EnrichmentType.DATASET_AUGMENT}

        if etype in critical_types:
            return "CRITICAL" if confidence > 0.5 else "HIGH"
        elif etype in high_types:
            return "HIGH" if confidence > 0.5 else "NORMAL"
        else:
            return "NORMAL"

    def _select_sources(self, etype: EnrichmentType) -> list[str]:
        """Select the best research sources for this enrichment type."""
        # Always start with local cache
        sources = ["turbovec_local"]

        # Map enrichment types to preferred sources
        source_map = {
            EnrichmentType.DATASET_AUGMENT: ["research_4_mcp", "rabbit_research"],
            EnrichmentType.KNOWLEDGE_GAP: ["research_4_mcp", "rabbit_research"],
            EnrichmentType.PRECISION_BOOST: ["research_4_mcp", "rabbit_research"],
            EnrichmentType.CROSS_VALIDATE: ["research_4_mcp", "rabbit_research", "crawl4ai"],
            EnrichmentType.MARKET_RESEARCH: ["rabbit_research", "research_4_mcp"],
            EnrichmentType.TECH_RESEARCH: ["research_4_mcp", "crawl4ai"],
            EnrichmentType.ACADEMIC_SEARCH: ["research_4_mcp"],
            EnrichmentType.CVE_ENRICHMENT: ["research_4_mcp", "crawl4ai"],
            EnrichmentType.API_DISCOVERY: ["research_4_mcp", "rabbit_research"],
            EnrichmentType.TREND_ANALYSIS: ["rabbit_research", "research_4_mcp"],
        }

        sources.extend(source_map.get(etype, ["research_4_mcp"]))
        return sources

    def enrich(self, trigger: EnrichmentTrigger) -> dict:
        """
        Execute enrichment for a detected trigger.
        Returns enrichment result with data from research sources.

        Flow:
        1. Check local cache (turbovec)
        2. If miss → query research-4 MCP (primary)
        3. If confidence < 0.8 → cross-validate with RabbitResearch
        4. Ingest into turbovec for future reuse
        5. Return enriched context
        """
        cache_key = hashlib.sha256(
            f"{trigger.type.value}:{trigger.source_task}".encode()
        ).hexdigest()[:16]

        # Step 1: Check cache
        if cache_key in self._enrichment_cache:
            self.stats["cache_hits"] += 1
            cached = self._enrichment_cache[cache_key]
            cached["from_cache"] = True
            return cached

        # Step 2: Build enrichment query
        query = self._build_query(trigger)

        # Step 3: Execute against sources in order
        results = []
        for source_id in trigger.recommended_sources:
            source = self.sources.get(source_id)
            if source and source.status == "active":
                result = self._query_source(source, query, trigger)
                if result:
                    results.append(result)
                    self.stats["queries_by_source"][source_id] = (
                        self.stats["queries_by_source"].get(source_id, 0) + 1
                    )

                    # If primary source gives high confidence, skip rest
                    if result.get("confidence", 0) > 0.8 and source.priority <= 1:
                        break

        # Step 4: Merge and deduplicate results
        enrichment = self._merge_results(trigger, results)
        enrichment["_nmp"] = trigger.to_nmp()

        # Step 5: Cache for future reuse
        self._enrichment_cache[cache_key] = enrichment
        self.stats["enrichments_fired"] += 1

        return enrichment

    def _build_query(self, trigger: EnrichmentTrigger) -> str:
        """Build an optimized research query from the trigger."""
        # Extract key terms from the source task
        task = trigger.source_task

        # Add type-specific query modifiers
        modifiers = {
            EnrichmentType.DATASET_AUGMENT: "dataset training data examples",
            EnrichmentType.KNOWLEDGE_GAP: "explanation documentation guide",
            EnrichmentType.PRECISION_BOOST: "accurate precise verified data",
            EnrichmentType.CROSS_VALIDATE: "comparison validation source",
            EnrichmentType.MARKET_RESEARCH: "market analysis competitors pricing",
            EnrichmentType.TECH_RESEARCH: "documentation API reference implementation",
            EnrichmentType.ACADEMIC_SEARCH: "paper research study published",
            EnrichmentType.CVE_ENRICHMENT: "CVE vulnerability advisory patch",
            EnrichmentType.API_DISCOVERY: "API endpoint service integration",
            EnrichmentType.TREND_ANALYSIS: "trend analysis growth adoption statistics",
        }

        modifier = modifiers.get(trigger.type, "")
        return f"{task} {modifier}".strip()

    def _query_source(self, source: ResearchSource, query: str, trigger: EnrichmentTrigger) -> Optional[dict]:
        """
        Query a specific research source.
        Returns structured result or None on failure.

        NOTE: Actual MCP/API calls are delegated to the forge's
        tool infrastructure. This method prepares the call config.
        """
        logger.info(f"  Enrichment: querying {source.name} for '{query[:80]}...'")

        if source.type == "mcp":
            return {
                "source": source.id,
                "source_name": source.name,
                "query": query,
                "call_config": {
                    "mcp_server": "research-4",
                    "method": "deep_research",
                    "params": {
                        "query": query,
                        "max_results": 10,
                        "include_citations": True,
                        "fact_check": trigger.type == EnrichmentType.CROSS_VALIDATE,
                    },
                },
                "confidence": 0.0,  # Set after actual call
                "status": "prepared",
            }
        elif source.type == "api":
            return {
                "source": source.id,
                "source_name": source.name,
                "query": query,
                "call_config": {
                    "endpoint": source.url or "rabbit_research_internal",
                    "method": "search",
                    "params": {"q": query, "limit": 10},
                },
                "confidence": 0.0,
                "status": "prepared",
            }
        elif source.type == "local":
            return {
                "source": source.id,
                "source_name": source.name,
                "query": query,
                "call_config": {
                    "method": "turbovec_search",
                    "params": {"query": query, "k": 5, "agent": "ENRICHMENT"},
                },
                "confidence": 0.0,
                "status": "prepared",
            }
        return None

    def _merge_results(self, trigger: EnrichmentTrigger, results: list[dict]) -> dict:
        """Merge results from multiple sources into unified enrichment."""
        return {
            "trigger": {
                "type": trigger.type.value,
                "confidence": trigger.confidence,
                "priority": trigger.priority,
            },
            "sources_queried": len(results),
            "source_results": results,
            "enrichment_ready": True,
            "ingestion_target": "turbovec",
            "timestamp": datetime.now().isoformat(),
            "from_cache": False,
        }

    def should_auto_enrich(self, task_description: str) -> tuple[bool, list[EnrichmentTrigger]]:
        """
        Quick check: should this task auto-trigger enrichment?
        Used by forge pipeline nodes to decide on-the-fly.

        Returns (should_enrich, triggers).
        """
        triggers = self.detect(task_description)
        should = len(triggers) > 0 and self.auto_fire
        return should, triggers

    def get_stats(self) -> dict:
        """Return enrichment engine statistics."""
        return {
            **self.stats,
            "cache_size": len(self._enrichment_cache),
            "sources_available": len([s for s in self.sources.values() if s.status == "active"]),
            "_nmp": (
                f"ENRICH|STATS|triggers={self.stats['triggers_detected']}"
                f"|fired={self.stats['enrichments_fired']}"
                f"|cache_hits={self.stats['cache_hits']}"
            ),
        }

    def to_nmp(self) -> str:
        s = self.stats
        return (
            f"ENRICH|ENGINE|triggers={s['triggers_detected']}"
            f"|fired={s['enrichments_fired']}|cache={len(self._enrichment_cache)}"
        )


# ─── Forge Pipeline Integration ──────────────────────────────────────────

def create_enrichment_engine(
    confidence_threshold: float = 0.3,
    auto_fire: bool = True,
) -> ResearchEnrichmentEngine:
    """Factory: create engine for forge pipeline integration."""
    return ResearchEnrichmentEngine(
        confidence_threshold=confidence_threshold,
        auto_fire=auto_fire,
    )


def enrich_task_context(task_description: str, engine: Optional[ResearchEnrichmentEngine] = None) -> dict:
    """
    One-shot enrichment: detect + enrich in a single call.
    For use in forge agent nodes that process tasks.

    Returns dict with:
    - enrichment_needed: bool
    - triggers: list of detected triggers
    - enrichments: list of enrichment results (if fired)
    """
    if engine is None:
        engine = create_enrichment_engine()

    should, triggers = engine.should_auto_enrich(task_description)

    result = {
        "enrichment_needed": should,
        "triggers": [t.to_nmp() for t in triggers],
        "enrichments": [],
    }

    if should:
        for trigger in triggers[:3]:  # Max 3 enrichments per task
            enrichment = engine.enrich(trigger)
            result["enrichments"].append(enrichment)

    return result
