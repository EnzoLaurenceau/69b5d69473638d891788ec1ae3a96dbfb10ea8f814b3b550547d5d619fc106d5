"""
forge_reuse_engine.py — Intelligent Reuse System for Skills, Tools & Knowledge
================================================================================
Matches current task to existing skills/tools/knowledge.
Suggests what to reuse before building from scratch.

Usage:
    from forge_agents.forge_reuse_engine import get_reuse_engine
    engine = get_reuse_engine()
    suggestions = engine.match_task("build a landing page for a dentist")
    # → [{type: "skill", name: "SKL_marketing_create_landing...", confidence: 0.85, ...}]
    engine.record_reuse("SKL_xxx", success=True, tokens_saved=5000)
"""

from __future__ import annotations
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ReuseEngine")

FORGE_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = FORGE_ROOT / "07_KNOWLEDGE_BASE" / "skills"
TOOLS_INDEX = FORGE_ROOT / "05_STATE" / "tool_index.json"
REUSE_LOG = FORGE_ROOT / "05_STATE" / "reuse_log.json"
REGISTRY_DIR = FORGE_ROOT / "05_STATE" / "system_registry"


@dataclass
class ReuseSuggestion:
    """A suggestion for reusing existing knowledge."""
    type: str  # "skill", "tool", "knowledge", "pattern"
    name: str
    description: str
    confidence: float  # 0.0 - 1.0
    path: str = ""
    tokens_saved: int = 0
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class ForgeReuseEngine:
    """Matches tasks to existing skills/tools/knowledge for intelligent reuse."""

    def __init__(self):
        self._skills: list[dict] = []
        self._tools: list[dict] = []
        self._reuse_history: list[dict] = []
        self._loaded = False

    def _load(self):
        """Lazy-load all indexes."""
        if self._loaded:
            return

        # Load skills
        if SKILLS_DIR.exists():
            for f in SKILLS_DIR.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                    data["_path"] = str(f)
                    self._skills.append(data)
                except Exception:
                    continue

        # Load tools from registry
        nodes_file = REGISTRY_DIR / "nodes.json"
        if nodes_file.exists():
            try:
                nodes = json.loads(nodes_file.read_text(encoding="utf-8"))
                self._tools = [n for n in nodes if n.get("type") == "tool"]
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        # Load reuse history
        if REUSE_LOG.exists():
            try:
                self._reuse_history = json.loads(REUSE_LOG.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

        self._loaded = True
        logger.info(f"[Reuse] Loaded: {len(self._skills)} skills, {len(self._tools)} tools")

    def match_task(self, task: str, top_k: int = 5) -> list[ReuseSuggestion]:
        """
        Match a task to existing skills/tools/knowledge.
        Returns ranked suggestions with confidence scores.
        """
        self._load()
        task_lower = task.lower()
        task_words = set(re.findall(r'\w{3,}', task_lower))
        suggestions: list[ReuseSuggestion] = []

        # 1. Match skills
        for skill in self._skills:
            confidence = self._match_confidence(task_words, task_lower, skill)
            if confidence > 0.3:
                suggestions.append(ReuseSuggestion(
                    type="skill",
                    name=skill.get("name", "unknown"),
                    description=skill.get("prompt", "")[:200],
                    confidence=confidence,
                    path=skill.get("_path", ""),
                    tokens_saved=skill.get("performance", {}).get("uses", 0) * 1000,
                    reason=f"Skill match: {skill.get('task_type', 'general')}",
                    metadata={"id": skill.get("id"), "tier": skill.get("tier")},
                ))

        # 2. Match tools
        for tool in self._tools:
            confidence = self._match_tool_confidence(task_words, task_lower, tool)
            if confidence > 0.3:
                suggestions.append(ReuseSuggestion(
                    type="tool",
                    name=tool.get("name", "unknown"),
                    description=tool.get("description", tool.get("details", ""))[:200],
                    confidence=confidence,
                    path=tool.get("path", ""),
                    reason=f"Tool match: {tool.get('category', 'general')}",
                ))

        # 3. Boost based on reuse history
        for s in suggestions:
            for hist in self._reuse_history:
                if hist.get("name") == s.name and hist.get("success"):
                    s.confidence = min(1.0, s.confidence + 0.1)
                    s.reason += f" (used {hist.get('count', 1)}x before)"
                    break

        # Sort by confidence
        suggestions.sort(key=lambda x: -x.confidence)
        return suggestions[:top_k]

    def _match_confidence(self, task_words: set, task_lower: str, skill: dict) -> float:
        """Calculate match confidence between task and skill."""
        score = 0.0

        # Keyword match
        skill_keywords = set(skill.get("trigger_keywords", []))
        overlap = task_words & skill_keywords
        if skill_keywords:
            score += len(overlap) / max(1, len(skill_keywords)) * 0.5

        # Task type match
        task_type = skill.get("task_type", "")
        if task_type and task_type in task_lower:
            score += 0.3

        # Name similarity
        name = skill.get("name", "").lower()
        name_words = set(re.findall(r'\w{3,}', name))
        name_overlap = task_words & name_words
        if name_words:
            score += len(name_overlap) / max(1, len(name_words)) * 0.2

        return min(1.0, score)

    def _match_tool_confidence(self, task_words: set, task_lower: str, tool: dict) -> float:
        """Calculate match confidence between task and tool."""
        score = 0.0

        name = tool.get("name", "").lower()
        desc = tool.get("description", tool.get("details", "")).lower()
        combined = name + " " + desc
        tool_words = set(re.findall(r'\w{3,}', combined))

        overlap = task_words & tool_words
        if tool_words:
            score += len(overlap) / max(1, len(tool_words)) * 0.6

        # Direct keyword in name
        if any(w in name for w in task_words if len(w) > 4):
            score += 0.3

        return min(1.0, score)

    def record_reuse(self, name: str, success: bool, tokens_saved: int = 0):
        """Record a reuse event for learning."""
        self._load()

        # Find existing entry
        existing = None
        for h in self._reuse_history:
            if h.get("name") == name:
                existing = h
                break

        if existing:
            existing["count"] = existing.get("count", 0) + 1
            existing["success"] = success
            existing["tokens_saved"] = existing.get("tokens_saved", 0) + tokens_saved
            existing["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            self._reuse_history.append({
                "name": name,
                "count": 1,
                "success": success,
                "tokens_saved": tokens_saved,
                "last_used": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

        # Persist
        try:
            REUSE_LOG.parent.mkdir(parents=True, exist_ok=True)
            REUSE_LOG.write_text(json.dumps(self._reuse_history, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def get_stats(self) -> dict:
        """Get reuse statistics."""
        self._load()
        total_uses = sum(h.get("count", 0) for h in self._reuse_history)
        total_saved = sum(h.get("tokens_saved", 0) for h in self._reuse_history)
        success_count = sum(1 for h in self._reuse_history if h.get("success"))

        return {
            "total_skills": len(self._skills),
            "total_tools": len(self._tools),
            "total_reuses": total_uses,
            "tokens_saved": total_saved,
            "success_rate": round(success_count / max(1, len(self._reuse_history)), 2),
        }


# Singleton
_instance: ForgeReuseEngine | None = None


def get_reuse_engine() -> ForgeReuseEngine:
    global _instance
    if _instance is None:
        _instance = ForgeReuseEngine()
    return _instance
