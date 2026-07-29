"""
GEO-SEO Module for La Forge
=============================
Evaluates website structures, metadata, and robots.txt configurations
to optimize citability and visibility in Generative Search Engines (GEO).

NMP: TOOL|INDEX|geo_seo|savings=65|pattern=generative engine optimization|approach=Citability audits + robots.txt verification
"""

import re
from typing import Dict, Any, List


class GeoSeoOptimizer:
    """Audits webpages for AI search crawler compatibility and citations."""

    def __init__(self):
        self.ai_crawlers = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "Anthropic-AI"]

    def audit_robots_txt(self, content: str) -> Dict[str, Any]:
        """Verify if AI search crawlers are allowed in robots.txt."""
        disallowed = []
        allowed = []
        
        for crawler in self.ai_crawlers:
            # Simple check to see if User-agent is disallowed
            pattern = rf"User-agent:\s*{re.escape(crawler)}.*?Disallow:\s*/\s*$"
            if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
                disallowed.append(crawler)
            else:
                allowed.append(crawler)

        score = (len(allowed) / len(self.ai_crawlers)) * 100
        return {
            "score": score,
            "allowed_crawlers": allowed,
            "disallowed_crawlers": disallowed,
            "is_crawlable": len(disallowed) == 0
        }

    def evaluate_citability(self, html_content: str) -> Dict[str, Any]:
        """Score webpage contents based on standard LLM citation triggers."""
        triggers = {
            "schema_markup": r'type="application/ld\+json"',
            "structured_tables": r'<table',
            "bulleted_summaries": r'<ul|<ol',
            "semantic_headers": r'<h[1-3]',
            "canonical_links": r'rel="canonical"'
        }
        
        matches = {}
        found_count = 0
        for name, regex in triggers.items():
            found = bool(re.search(regex, html_content, re.IGNORECASE))
            matches[name] = found
            if found:
                found_count += 1
                
        score = (found_count / len(triggers)) * 10
        return {
            "score": score,
            "checks": matches,
            "citability_grade": "HIGH" if score >= 8.0 else ("MEDIUM" if score >= 5.0 else "LOW")
        }

    def generate_recommendations(self, audit_results: Dict[str, Any]) -> List[str]:
        """Generate actionable optimization advice."""
        recs = []
        checks = audit_results.get("checks", {})
        
        if not checks.get("schema_markup"):
            recs.append("Add structured Schema JSON-LD metadata markup to enhance entity parsing.")
        if not checks.get("bulleted_summaries"):
            recs.append("Include concise bulleted summary sections at the top of content blocks.")
        if not checks.get("canonical_links"):
            recs.append("Define canonical tags to prevent citation dilution.")
            
        return recs

    def to_nmp(self) -> str:
        return f"SEO|GEO|crawlers={len(self.ai_crawlers)}|optimization=citability,schema,robots_txt"
