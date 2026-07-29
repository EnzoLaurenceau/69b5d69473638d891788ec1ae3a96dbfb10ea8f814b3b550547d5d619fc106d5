"""
Agent Topologies Module for La Forge
=====================================
Implements multi-agent orchestration structures inspired by revfactory/harness.
Supports dynamic topology selection based on task constraints.

NMP: TOOL|INDEX|agent_topology|savings=60|pattern=agent team structures|approach=Select & configure pipeline/expert pool/reviewer topologies
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


class TopologyType(Enum):
    PIPELINE = "pipeline"                 # Linear sequence of agents
    PRODUCER_REVIEWER = "producer_reviewer"  # Generator + Critic loop
    EXPERT_POOL = "expert_pool"           # Specialist selector
    SUPERVISOR = "supervisor"             # Router + Worker hierarchy
    HIERARCHICAL = "hierarchical"         # Nested delegation tree


@dataclass
class AgentRole:
    name: str
    type_name: str
    system_prompt: str
    capabilities: List[str] = field(default_factory=list)


@dataclass
class TopologySpec:
    name: str
    type: TopologyType
    roles: List[AgentRole]
    description: str
    routing_rules: Dict[str, Any] = field(default_factory=dict)


class TopologySelector:
    """Selects and configures agent topologies based on task analysis."""

    def __init__(self):
        self.topologies = {
            TopologyType.PIPELINE: TopologySpec(
                name="SDLC Linear Pipeline",
                type=TopologyType.PIPELINE,
                description="Sequential execution from spec to deployment.",
                roles=[
                    AgentRole("spec_writer", "founder_ceo", "Write functional specifications.", ["defining"]),
                    AgentRole("developer", "senior_dev", "Write source code.", ["writing"]),
                    AgentRole("validator", "critic", "Run test assertions and coverage checks.", ["testing"])
                ]
            ),
            TopologyType.PRODUCER_REVIEWER: TopologySpec(
                name="Producer-Reviewer Alignment",
                type=TopologyType.PRODUCER_REVIEWER,
                description="Paired generation and critique loop to prevent hallucinations.",
                roles=[
                    AgentRole("producer", "senior_dev", "Produce high-quality outputs.", ["writing"]),
                    AgentRole("reviewer", "critic", "Critique quality, security, and edge cases.", ["reviewing"])
                ]
            ),
            TopologyType.EXPERT_POOL: TopologySpec(
                name="Specialist Expert Pool",
                type=TopologyType.EXPERT_POOL,
                description="Query specific specialized agents based on domain needs.",
                roles=[
                    AgentRole("security_expert", "audit_agent", "Vulnerability assessment.", ["security"]),
                    AgentRole("ui_designer", "marketing_digital", "Polish UI components.", ["design"]),
                    AgentRole("data_enricher", "research", "Enrich datasets with web resources.", ["research"])
                ]
            )
        }

    def recommend_topology(self, task_description: str) -> TopologySpec:
        """Analyze the task description to recommend the best topology."""
        import re
        words = set(re.findall(r'\b\w+\b', task_description.lower()))

        # Security audits or UI tweaks require Expert Pool
        expert_keywords = {"security", "cve", "vulnerability", "audit", "ui", "ux", "design", "enrich", "dataset"}
        if words.intersection(expert_keywords):
            return self.topologies[TopologyType.EXPERT_POOL]

        # Critical code creation or optimization requires validation loop (Producer-Reviewer)
        critic_keywords = {"optimize", "fix", "bug", "refactor", "correctness", "performance", "hallucinate"}
        if words.intersection(critic_keywords):
            return self.topologies[TopologyType.PRODUCER_REVIEWER]

        # Multi-step complex projects default to Pipeline
        return self.topologies[TopologyType.PIPELINE]

    def to_nmp(self) -> str:
        return f"TOPOLOGY|SELECTOR|types={len(self.topologies)}|active=pipeline,producer_reviewer,expert_pool"
