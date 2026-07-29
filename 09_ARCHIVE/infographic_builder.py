"""
AntV Infographic Layout Builder Module for La Forge
===================================================
Translates data structures into AntV Infographic DSL strings and integrates
with image generation utilities to output professional branding visuals.

NMP: TOOL|INDEX|infographic_builder|savings=65|pattern=visual dsl scaffold|approach=DSL compilation + branding styling variables
"""

from typing import Dict, Any, List, Optional


class InfographicBuilder:
    """Compiles infographic DSL and applies design configurations."""

    def __init__(self, theme_palette: Optional[Dict[int, str]] = None):
        # Default fallback palette (indigo)
        self.palette = theme_palette or {
            50: "#f8fafc",
            500: "#6366f1",
            900: "#0f172a"
        }

    def compile_sequence_dsl(self, steps: List[Dict[str, str]], title: str = "Workflow") -> str:
        """
        Generate AntV Infographic DSL structure for sequential flow.
        Example output format required by @antv/infographic engine.
        """
        dsl_parts = [
            f"infographic list-row-simple-horizontal-arrow",
            f"theme primary={self.palette.get(500)} background={self.palette.get(50)}",
            f"title {title}",
            f"data",
            f"lists"
        ]
        
        for step in steps:
            label = step.get("label", "Step")
            desc = step.get("desc", "Description")
            dsl_parts.append(f"  - label {label}")
            dsl_parts.append(f"    desc {desc}")
            
        return "\n".join(dsl_parts)

    def compile_comparison_dsl(self, items: List[Dict[str, Any]], title: str = "Comparison") -> str:
        """Generate AntV Infographic DSL for comparisons (e.g. A vs B)."""
        dsl_parts = [
            f"infographic comparison-columns",
            f"theme primary={self.palette.get(500)} dark={self.palette.get(900)}",
            f"title {title}",
            f"data",
            f"items"
        ]
        
        for item in items:
            name = item.get("name", "Item")
            values = item.get("values", [])
            dsl_parts.append(f"  - name {name}")
            dsl_parts.append(f"    values {';'.join(map(str, values))}")
            
        return "\n".join(dsl_parts)

    def generate_ai_branding_prompt(self, brand_name: str, primary_color: str, concept: str) -> str:
        """Formulate a prompt to generate customized AI visual assets (e.g. logos)."""
        return (
            f"Create a professional, minimalist vector brand visual asset for '{brand_name}' using a clean, "
            f"modern design style. Main accent color to use: {primary_color}. Concept/Focus: {concept}. "
            f"Flat illustration, no background, SVG style, export ready, suitable for modern dashboard embedding."
        )

    def to_nmp(self) -> str:
        return f"VISUAL|INFOGRAPHIC|theme_primary={self.palette.get(500)}|dsl_types=sequence,comparison"
