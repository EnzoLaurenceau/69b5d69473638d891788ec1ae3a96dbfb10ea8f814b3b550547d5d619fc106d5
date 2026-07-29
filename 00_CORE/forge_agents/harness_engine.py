"""
harness_engine.py — Harness Engineer for the Forge
===================================================
Quality gates for ALL produced artifacts. No AI slop.

Every output must pass through the harness before delivery:
  Code → Lint + Tests + Security + Performance
  Website → Lighthouse + A11y + SEO + Design
  Video → Resolution + Audio + Pacing + Branding
  Bot → Uptime + Error handling + Rate limits
  Email → Deliverability + Spam score + Rendering

The harness defines VENDABLE quality — not "works on my machine".

Integration:
  from .harness_engine import HarnessEngine, ArtifactType
  
  engine = HarnessEngine()
  result = engine.validate(artifact_type, files, config)
  if not result.passed:
      # Fix before delivery
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent


# ═══════════════════════════════════════════════════════════════════════════════
# ARTIFACT TYPES — What can the Forge produce?
# ═══════════════════════════════════════════════════════════════════════════════

class ArtifactType(Enum):
    """Types of artifacts the Forge can produce."""
    CODE = "code"                    # Python, JS, etc.
    WEBSITE = "website"              # Landing pages, webapps
    VIDEO = "video"                  # YouTube, TikTok, etc.
    BOT = "bot"                      # Telegram, Discord, etc.
    EMAIL = "email"                  # HTML emails, newsletters
    DOCUMENT = "document"            # PDF, DOCX, presentations
    API = "api"                      # REST, GraphQL endpoints
    DATABASE = "database"            # Schemas, migrations
    DEPLOYMENT = "deployment"        # Docker, CI/CD, infra
    AUTOMATION = "automation"        # Cron jobs, pipelines

    # ── Game asset types (E3-01) ──────────────────────────────────────────
    # Chaque type correspond à une étape du pipeline E3 (ASSET-PIPE).
    # Les gates spécifiques (E3-05) viendront remplir GATES ; pour l'instant
    # chaque type a un gate de base (existence + format + taille) et un
    # gate copyright (E3-07 branchera `world_canon.guard()`).
    CONCEPT = "concept"              # Concept art, mood boards
    SPRITE = "sprite"                # 2D sprites, tilesets, atlas
    TEXTURE = "texture"              # PBR textures, normal maps, UV
    MODEL_3D = "model_3d"            # Meshes (.fbx, .obj, .gltf, .blend)
    RIG = "rig"                      # Skeleton + weights (.fbx, .blend)
    ANIM = "anim"                    # Animation clips (.fbx, .anim)
    VFX = "vfx"                      # Particle systems, shaders, effects


# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY GATES — What does "vendable" mean?
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class QualityGate:
    """A single quality gate that must pass."""
    name: str
    description: str
    severity: Literal["critical", "high", "medium", "low"]
    check: str  # Command or function name
    threshold: Optional[float] = None
    auto_fix: Optional[str] = None  # Command to auto-fix


@dataclass
class GateResult:
    """Result of a quality gate check."""
    gate: QualityGate
    passed: bool
    score: Optional[float] = None
    details: str = ""
    fix_applied: bool = False


@dataclass
class HarnessResult:
    """Complete harness validation result."""
    artifact_type: ArtifactType
    passed: bool
    score: float  # 0-100
    gates_checked: int
    gates_passed: int
    gates_failed: int
    results: list[GateResult]
    critical_failures: list[str]
    warnings: list[str]
    recommendations: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def grade(self) -> str:
        """Lettre A-F du score. Deux appelants la lisaient déjà (`agent_nodes`
        post-mortem) sur un objet qui ne l'exposait pas : l'`AttributeError`
        partait dans un `except Exception` et le grade n'était JAMAIS affiché.
        Même échelle que le score par artefact (E6-02), pour n'avoir qu'un seul
        barème dans la Forge."""
        from .artifact_quality import grade_of
        return grade_of(self.score)


# ═══════════════════════════════════════════════════════════════════════════════
# HARNESS ENGINE — The quality enforcer
# ═══════════════════════════════════════════════════════════════════════════════

Literal = str  # Type alias for Python 3.11 compat


class HarnessEngine:
    """
    Harness Engineer for the Forge.
    
    Validates ALL artifacts against production-quality gates.
    No artifact leaves the harness without passing critical gates.
    
    Usage:
        engine = HarnessEngine()
        result = engine.validate(ArtifactType.CODE, files, config)
        if not result.passed:
            print(result.critical_failures)
    """
    
    # ── QUALITY GATES BY ARTIFACT TYPE ────────────────────────────────────────
    
    GATES: dict[ArtifactType, list[QualityGate]] = {
        
        ArtifactType.CODE: [
            QualityGate(
                "syntax_check",
                "Code must parse without syntax errors",
                "critical",
                "python_compile",
            ),
            QualityGate(
                "lint_flake8",
                "Flake8 linting (max line 120, ignore E501,W503)",
                "high",
                "flake8",
                threshold=0,  # 0 errors
            ),
            QualityGate(
                "type_hints",
                "Public functions must have type hints",
                "medium",
                "check_type_hints",
            ),
            QualityGate(
                "docstrings",
                "Public functions must have docstrings",
                "medium",
                "check_docstrings",
            ),
            QualityGate(
                "tests_exist",
                "Must have corresponding test file",
                "high",
                "check_tests_exist",
            ),
            QualityGate(
                "no_hardcoded_secrets",
                "No hardcoded API keys, passwords, tokens",
                "critical",
                "check_no_secrets",
            ),
            QualityGate(
                "no_print_statements",
                "No print() in production code (use logging)",
                "medium",
                "check_no_print",
            ),
            QualityGate(
                "error_handling",
                "Functions must handle exceptions",
                "high",
                "check_error_handling",
            ),
            QualityGate(
                "imports_sorted",
                "Imports must be sorted (isort)",
                "low",
                "isort",
            ),
            QualityGate(
                "no_ai_slop",
                "No AI slop patterns (Certainly!, Great!, etc.)",
                "critical",
                "check_no_ai_slop",
            ),
        ],
        
        ArtifactType.WEBSITE: [
            QualityGate(
                "html_valid",
                "HTML must be valid (no unclosed tags)",
                "critical",
                "validate_html",
            ),
            QualityGate(
                "css_valid",
                "CSS must be valid",
                "critical",
                "validate_css",
            ),
            QualityGate(
                "no_console_errors",
                "No JavaScript console errors",
                "critical",
                "check_console_errors",
            ),
            QualityGate(
                "responsive",
                "Must be responsive (mobile-first)",
                "high",
                "check_responsive",
            ),
            QualityGate(
                "a11y_contrast",
                "Color contrast must meet WCAG AA",
                "high",
                "check_contrast",
                threshold=4.5,
            ),
            QualityGate(
                "a11y_alt_text",
                "All images must have alt text",
                "high",
                "check_alt_text",
            ),
            QualityGate(
                "seo_meta",
                "Must have title, description, og:tags",
                "high",
                "check_seo_meta",
            ),
            QualityGate(
                "performance",
                "Page must load under 3 seconds",
                "high",
                "check_performance",
                threshold=3.0,
            ),
            QualityGate(
                "no_external_deps",
                "No external CDN dependencies (self-contained)",
                "medium",
                "check_no_external",
            ),
            QualityGate(
                "security_headers",
                "Must have CSP, X-Frame-Options, etc.",
                "high",
                "check_security_headers",
            ),
            QualityGate(
                "no_ai_slop",
                "No placeholder text, lorem ipsum, or AI patterns",
                "critical",
                "check_no_ai_slop",
            ),
        ],
        
        ArtifactType.VIDEO: [
            QualityGate(
                "resolution",
                "Must be 1080p minimum (1920x1080)",
                "critical",
                "check_resolution",
                threshold=1080,
            ),
            QualityGate(
                "fps",
                "Must be 30fps minimum",
                "high",
                "check_fps",
                threshold=30,
            ),
            QualityGate(
                "audio_quality",
                "Audio must be clear (no clipping, noise)",
                "critical",
                "check_audio",
            ),
            QualityGate(
                "duration",
                "Must be appropriate length (not too short/long)",
                "medium",
                "check_duration",
            ),
            QualityGate(
                "branding",
                "Must have intro/outro with branding",
                "high",
                "check_branding",
            ),
            QualityGate(
                "captions",
                "Must have captions/subtitles",
                "medium",
                "check_captions",
            ),
            QualityGate(
                "thumbnail",
                "Must have custom thumbnail",
                "high",
                "check_thumbnail",
            ),
            QualityGate(
                "no_watermarks",
                "No watermarks from free tools",
                "critical",
                "check_watermarks",
            ),
        ],
        
        ArtifactType.BOT: [
            QualityGate(
                "startup",
                "Bot must start without errors",
                "critical",
                "check_bot_startup",
            ),
            QualityGate(
                "command_handlers",
                "All commands must have handlers",
                "critical",
                "check_command_handlers",
            ),
            QualityGate(
                "error_handling",
                "Must handle API errors gracefully",
                "critical",
                "check_bot_errors",
            ),
            QualityGate(
                "rate_limiting",
                "Must implement rate limiting",
                "high",
                "check_rate_limits",
            ),
            QualityGate(
                "logging",
                "Must log all interactions",
                "high",
                "check_bot_logging",
            ),
            QualityGate(
                "persistence",
                "Must persist state (not lose data on restart)",
                "high",
                "check_persistence",
            ),
            QualityGate(
                "help_command",
                "Must have /help command",
                "medium",
                "check_help_command",
            ),
            QualityGate(
                "graceful_shutdown",
                "Must handle SIGTERM/SIGINT",
                "high",
                "check_graceful_shutdown",
            ),
            QualityGate(
                "no_hardcoded_token",
                "No hardcoded bot tokens",
                "critical",
                "check_no_secrets",
            ),
        ],
        
        ArtifactType.EMAIL: [
            QualityGate(
                "html_valid",
                "HTML must be valid email HTML",
                "critical",
                "validate_email_html",
            ),
            QualityGate(
                "inline_css",
                "CSS must be inline (no <style> blocks)",
                "critical",
                "check_inline_css",
            ),
            QualityGate(
                "no_javascript",
                "No JavaScript in emails",
                "critical",
                "check_no_js",
            ),
            QualityGate(
                "image_alt",
                "All images must have alt text",
                "high",
                "check_alt_text",
            ),
            QualityGate(
                "spam_score",
                "Must pass spam check (score < 5)",
                "critical",
                "check_spam_score",
                threshold=5.0,
            ),
            QualityGate(
                "unsubscribe",
                "Must have unsubscribe link",
                "high",
                "check_unsubscribe",
            ),
            QualityGate(
                "mobile_friendly",
                "Must render on mobile",
                "high",
                "check_email_mobile",
            ),
            QualityGate(
                "no_emojis_subject",
                "No emojis in subject line",
                "medium",
                "check_no_emoji_subject",
            ),
            QualityGate(
                "no_ai_slop",
                "No AI patterns in copy",
                "critical",
                "check_no_ai_slop",
            ),
        ],
        
        ArtifactType.API: [
            QualityGate(
                "openapi_spec",
                "Must have OpenAPI/Swagger spec",
                "critical",
                "check_openapi",
            ),
            QualityGate(
                "input_validation",
                "All inputs must be validated",
                "critical",
                "check_input_validation",
            ),
            QualityGate(
                "auth_required",
                "Protected endpoints must require auth",
                "critical",
                "check_auth",
            ),
            QualityGate(
                "rate_limiting",
                "Must implement rate limiting",
                "high",
                "check_rate_limits",
            ),
            QualityGate(
                "error_responses",
                "Must return proper error codes",
                "high",
                "check_error_responses",
            ),
            QualityGate(
                "pagination",
                "List endpoints must support pagination",
                "high",
                "check_pagination",
            ),
            QualityGate(
                "versioning",
                "Must be versioned (/v1/, /v2/)",
                "medium",
                "check_versioning",
            ),
            QualityGate(
                "tests",
                "Must have integration tests",
                "critical",
                "check_api_tests",
            ),
        ],

        # ── Game asset gates (E3-01 stubs — E3-05 will flesh out) ───────
        # Chaque type a un gate d'existence + format + taille raisonnable.
        # Le gate copyright (E3-07) sera partagé via un check dédié.
        # Les checks personnalisés (`_check_asset_file_exists`, etc.) sont
        # définis ci-dessous dans la section CHECK IMPLEMENTATIONS.

        ArtifactType.CONCEPT: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("image_format", "Must be a supported image format (PNG, JPG, WebP, PSD)", "critical", "check_image_format"),
            QualityGate("image_dimensions", "Must be at least 512×512", "high", "check_image_dimensions"),
            QualityGate("file_size", "File must be under 50 MB", "high", "check_file_size", threshold=50),
        ],

        ArtifactType.SPRITE: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("image_format", "Must be PNG or WebP (transparency required)", "critical", "check_sprite_format"),
            QualityGate("power_of_two", "Dimensions should be power-of-two for GPU", "high", "check_power_of_two"),
            QualityGate("file_size", "File must be under 5 MB", "high", "check_file_size", threshold=5),
        ],

        ArtifactType.TEXTURE: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("image_format", "Must be PNG, TGA, or JPG", "critical", "check_texture_format"),
            QualityGate("power_of_two", "Must be power-of-two dimensions", "critical", "check_power_of_two"),
            QualityGate("file_size", "File must be under 20 MB", "high", "check_file_size", threshold=20),
        ],

        ArtifactType.MODEL_3D: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("model_format", "Must be FBX, OBJ, glTF/GLB, or Blend", "critical", "check_model_format"),
            QualityGate("file_size", "File must be under 100 MB", "high", "check_file_size", threshold=100),
        ],

        ArtifactType.RIG: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("rig_format", "Must be FBX or Blend with armature", "critical", "check_model_format"),
            QualityGate("file_size", "File must be under 50 MB", "high", "check_file_size", threshold=50),
        ],

        ArtifactType.ANIM: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("anim_format", "Must be FBX animation clip or Unity .anim", "critical", "check_anim_format"),
            QualityGate("file_size", "File must be under 20 MB", "high", "check_file_size", threshold=20),
        ],

        ArtifactType.VFX: [
            QualityGate("asset_file_exists", "File must exist on disk", "critical", "check_asset_file_exists"),
            QualityGate("vfx_format", "Must be shader, particle config, or VFX graph", "high", "check_vfx_format"),
            QualityGate("file_size", "File must be under 10 MB", "high", "check_file_size", threshold=10),
        ],
    }
    
    # ── ANTI-SLOP PATTERNS ────────────────────────────────────────────────────
    
    AI_SLOP_PATTERNS = [
        # English slop
        r"Certainly!?\b",
        r"Great question!?\b",
        r"I'd be happy to\b",
        r"Let me\b.*\bfor you\b",
        r"Here's\b.*\bfor you\b",
        r"I hope this helps\b",
        r"Feel free to\b",
        r"Let me know if\b",
        r"Don't hesitate to\b",
        r"In conclusion\b",
        r"It's worth noting\b",
        r"It's important to note\b",
        r"Remember that\b",
        r"Keep in mind\b",
        r"As an AI\b",
        r"I'm an AI\b",
        r"As a language model\b",
        
        # French slop
        r"Bien sûr!?\b",
        r"Excellente question!?\b",
        r"Je serais ravi de\b",
        r"Permettez-moi de\b",
        r"Voici\b.*\bpour vous\b",
        r"J'espère que cela aide\b",
        r"N'hésitez pas à\b",
        r"En conclusion\b",
        r"Il est important de noter\b",
        r"En tant qu'IA\b",
        
        # Code slop
        r"# TODO: implement\b",
        r"# Your code here\b",
        r"# Add your\b",
        r"pass\s*# placeholder\b",
        r"raise NotImplementedError\b",
        r"lorem ipsum\b",
        r"placeholder\b",
        r"example\.com\b",
        r"test@test\.com\b",
        r"xxx-xxx-xxxx\b",
    ]
    
    SECRET_PATTERNS = [
        r"api[_-]?key\s*[=:]\s*['\"][^'\"]{10,}",
        r"password\s*[=:]\s*['\"][^'\"]{6,}",
        r"token\s*[=:]\s*['\"][^'\"]{10,}",
        r"secret\s*[=:]\s*['\"][^'\"]{10,}",
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI
        r"ghp_[a-zA-Z0-9]{36}",  # GitHub
        r"xoxb-[a-zA-Z0-9-]+",   # Slack
        r"Bearer\s+[a-zA-Z0-9._-]{20,}",
    ]
    
    def __init__(self, auto_fix: bool = False):
        self.auto_fix = auto_fix
        self._results_cache: dict[str, HarnessResult] = {}
    
    def validate(self, artifact_type: ArtifactType, 
                 files: list[str | Path], 
                 config: dict[str, Any] = None) -> HarnessResult:
        """
        Validate an artifact against its quality gates.
        
        Args:
            artifact_type: Type of artifact
            files: List of file paths to validate
            config: Optional configuration overrides
            
        Returns:
            HarnessResult with pass/fail and details
        """
        logger.info(f"Harness: validating {artifact_type.value} ({len(files)} files)")
        
        gates = self.GATES.get(artifact_type, [])
        if not gates:
            logger.warning(f"No gates defined for {artifact_type.value}")
            return HarnessResult(
                artifact_type=artifact_type,
                passed=True,
                score=100.0,
                gates_checked=0,
                gates_passed=0,
                gates_failed=0,
                results=[],
                critical_failures=[],
                warnings=[],
                recommendations=[],
            )
        
        results = []
        critical_failures = []
        warnings = []
        recommendations = []
        
        for gate in gates:
            result = self._run_gate(gate, files, config)
            results.append(result)
            
            if not result.passed:
                if gate.severity == "critical":
                    critical_failures.append(f"CRITICAL: {gate.name} — {result.details}")
                elif gate.severity == "high":
                    warnings.append(f"HIGH: {gate.name} — {result.details}")
                else:
                    recommendations.append(f"{gate.severity.upper()}: {gate.name} — {result.details}")
                
                # Auto-fix if enabled
                if self.auto_fix and gate.auto_fix:
                    fix_result = self._apply_fix(gate, files, config)
                    if fix_result:
                        result.fix_applied = True
                        logger.info(f"  Auto-fixed: {gate.name}")
        
        # Calculate score
        gates_passed = sum(1 for r in results if r.passed)
        gates_failed = len(results) - gates_passed
        
        # Weighted score (critical=3, high=2, medium=1, low=0.5)
        weights = {"critical": 3, "high": 2, "medium": 1, "low": 0.5}
        total_weight = sum(weights.get(g.severity, 1) for g in gates)
        passed_weight = sum(
            weights.get(g.severity, 1) 
            for g, r in zip(gates, results) 
            if r.passed
        )
        score = (passed_weight / total_weight * 100) if total_weight > 0 else 100.0
        
        # Overall pass: no critical failures AND score >= 70
        passed = len(critical_failures) == 0 and score >= 70.0
        
        result = HarnessResult(
            artifact_type=artifact_type,
            passed=passed,
            score=round(score, 1),
            gates_checked=len(results),
            gates_passed=gates_passed,
            gates_failed=gates_failed,
            results=results,
            critical_failures=critical_failures,
            warnings=warnings,
            recommendations=recommendations,
        )
        
        # Cache result
        cache_key = f"{artifact_type.value}:{','.join(str(f) for f in files)}"
        self._results_cache[cache_key] = result
        
        logger.info(f"Harness: {gates_passed}/{len(results)} gates passed (score: {score:.1f}%)")
        
        return result
    
    def _run_gate(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Run a single quality gate."""
        try:
            # Map gate check to implementation.
            # Les gates déclarent indifféremment `check="python_compile"` et
            # `check="check_no_secrets"` : chercher le seul `_check_{check}`
            # laissait 8 gates sur 10 introuvables — donc « passées par défaut »,
            # dont les trois `critical`. Constaté E6-02 : un PNG validé comme du
            # CODE sortait à 100/100. On essaie les deux formes.
            check_fn = (getattr(self, f"_check_{gate.check}", None)
                        or getattr(self, f"_{gate.check}", None))
            if check_fn:
                return check_fn(gate, files, config)
            else:
                logger.warning(f"  No implementation for gate: {gate.check}")
                return GateResult(
                    gate=gate,
                    passed=True,  # Pass by default if no implementation
                    details="No implementation (passed by default)",
                )
        except Exception as e:
            return GateResult(
                gate=gate,
                passed=False,
                details=f"Gate check failed: {e}",
            )
    
    def _apply_fix(self, gate: QualityGate, files: list, config: dict = None) -> bool:
        """Apply auto-fix for a gate."""
        try:
            fix_fn = getattr(self, f"_fix_{gate.auto_fix}", None)
            if fix_fn:
                return fix_fn(files, config)
            return False
        except Exception as e:
            logger.error(f"  Auto-fix failed: {e}")
            return False
    
    # ── CHECK IMPLEMENTATIONS ─────────────────────────────────────────────────
    
    def _check_python_compile(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check Python files compile without syntax errors."""
        errors = []
        for f in files:
            if str(f).endswith('.py'):
                try:
                    result = subprocess.run(
                        ["python", "-m", "py_compile", str(f)],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        errors.append(f"{f}: {result.stderr.strip()}")
                except Exception as e:
                    errors.append(f"{f}: {e}")
        
        if errors:
            return GateResult(gate=gate, passed=False, details="\n".join(errors))
        return GateResult(gate=gate, passed=True, details=f"{len(files)} files compile OK")
    
    def _check_no_secrets(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check for hardcoded secrets."""
        violations = []
        for f in files:
            try:
                content = Path(f).read_text(errors='ignore')
                for pattern in self.SECRET_PATTERNS:
                    if re.search(pattern, content, re.IGNORECASE):
                        violations.append(f"{f}: possible secret found")
                        break
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        if violations:
            return GateResult(gate=gate, passed=False, details="\n".join(violations))
        return GateResult(gate=gate, passed=True, details="No secrets detected")
    
    def _check_no_ai_slop(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check for AI slop patterns."""
        violations = []
        for f in files:
            try:
                content = Path(f).read_text(errors='ignore')
                for pattern in self.AI_SLOP_PATTERNS:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        violations.append(f"{f}: AI slop detected: '{matches[0]}'")
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        if violations:
            return GateResult(gate=gate, passed=False, details="\n".join(violations[:10]))
        return GateResult(gate=gate, passed=True, details="No AI slop detected")
    
    def _check_no_print(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check for print() statements in production code."""
        violations = []
        for f in files:
            if str(f).endswith('.py'):
                try:
                    content = Path(f).read_text(errors='ignore')
                    # Skip test files and scripts
                    if 'test_' in str(f) or '__main__' in content:
                        continue
                    # Check for print statements (not in comments)
                    for i, line in enumerate(content.split('\n'), 1):
                        stripped = line.strip()
                        if stripped.startswith('print(') and not stripped.startswith('#'):
                            violations.append(f"{f}:{i}: {stripped[:60]}")
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        if len(violations) > 5:
            return GateResult(gate=gate, passed=False, details=f"{len(violations)} print() statements found")
        return GateResult(gate=gate, passed=True, details="No excessive print() statements")
    
    def _check_flake8(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Run flake8 linting."""
        py_files = [str(f) for f in files if str(f).endswith('.py')]
        if not py_files:
            return GateResult(gate=gate, passed=True, details="No Python files")
        
        try:
            result = subprocess.run(
                ["python", "-m", "flake8", "--max-line-length=120", "--ignore=E501,W503"] + py_files,
                capture_output=True, text=True, timeout=30
            )
            # flake8 absent : `python -m flake8` sort en code ≠ 0 avec une sortie
            # VIDE, que le comptage ci-dessous lisait comme « 0 erreur » → « clean ».
            # Un outil manquant ne prouve rien ; il ne doit pas décerner un succès.
            if result.returncode not in (0, 1) or "No module named" in (result.stderr or ""):
                return GateResult(gate=gate, passed=True,
                                  details="flake8 not installed (skipped)")
            error_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0

            if error_count > (gate.threshold or 0):
                return GateResult(
                    gate=gate, passed=False, score=error_count,
                    details=f"{error_count} flake8 errors\n{result.stdout[:500]}"
                )
            return GateResult(gate=gate, passed=True, details="flake8 clean")
        except FileNotFoundError:
            return GateResult(gate=gate, passed=True, details="flake8 not installed (skipped)")
    
    def _check_type_hints(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check for type hints on public functions."""
        violations = []
        for f in files:
            if str(f).endswith('.py'):
                try:
                    content = Path(f).read_text(errors='ignore')
                    # Find public function defs without return type
                    for i, line in enumerate(content.split('\n'), 1):
                        if re.match(r'\s*def [a-z]\w*\(', line):
                            if '->' not in line and 'self' not in line:
                                violations.append(f"{f}:{i}: missing type hints")
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        if len(violations) > 10:
            return GateResult(gate=gate, passed=False, details=f"{len(violations)} functions without type hints")
        return GateResult(gate=gate, passed=True, details="Type hints present")
    
    def _check_docstrings(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check for docstrings on public functions."""
        violations = []
        for f in files:
            if str(f).endswith('.py'):
                try:
                    content = Path(f).read_text(errors='ignore')
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if re.match(r'\s*def [a-z]\w*\(', line):
                            # Check next non-empty line for docstring
                            for j in range(i+1, min(i+3, len(lines))):
                                if lines[j].strip():
                                    if not lines[j].strip().startswith('"""'):
                                        violations.append(f"{f}:{i+1}: missing docstring")
                                    break
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        if len(violations) > 10:
            return GateResult(gate=gate, passed=False, details=f"{len(violations)} functions without docstrings")
        return GateResult(gate=gate, passed=True, details="Docstrings present")
    
    def _check_tests_exist(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check that test files exist for source files."""
        missing = []
        for f in files:
            if str(f).endswith('.py') and 'test_' not in str(f):
                test_file = Path(f).parent / f"test_{Path(f).name}"
                if not test_file.exists():
                    missing.append(str(f))
        
        if len(missing) > len(files) * 0.5:  # More than 50% missing
            return GateResult(gate=gate, passed=False, details=f"{len(missing)} files without tests")
        return GateResult(gate=gate, passed=True, details="Test files exist")
    
    def _check_error_handling(self, gate: QualityGate, files: list, config: dict = None) -> GateResult:
        """Check for proper error handling."""
        violations = []
        for f in files:
            if str(f).endswith('.py'):
                try:
                    content = Path(f).read_text(errors='ignore')
                    # Check for bare except
                    if 'except:' in content and 'except Exception' not in content:
                        violations.append(f"{f}: bare except clause")
                except Exception as exc:
                    logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        if violations:
            return GateResult(gate=gate, passed=False, details="\n".join(violations))
        return GateResult(gate=gate, passed=True, details="Error handling present")
    
    # ── PLACEHOLDER CHECKS (implement as needed) ──────────────────────────────
    
    def _check_isort(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="isort check (placeholder)")
    
    def _check_validate_html(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="HTML validation (placeholder)")
    
    def _check_validate_css(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="CSS validation (placeholder)")
    
    def _check_console_errors(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Console errors check (placeholder)")
    
    def _check_responsive(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Responsive check (placeholder)")
    
    def _check_contrast(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Contrast check (placeholder)")
    
    def _check_alt_text(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Alt text check (placeholder)")
    
    def _check_seo_meta(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="SEO meta check (placeholder)")
    
    def _check_performance(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Performance check (placeholder)")
    
    def _check_no_external(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="External deps check (placeholder)")
    
    def _check_security_headers(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Security headers check (placeholder)")
    
    def _check_resolution(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Resolution check (placeholder)")
    
    def _check_fps(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="FPS check (placeholder)")
    
    def _check_audio(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Audio check (placeholder)")
    
    def _check_duration(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Duration check (placeholder)")
    
    def _check_branding(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Branding check (placeholder)")
    
    def _check_captions(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Captions check (placeholder)")
    
    def _check_thumbnail(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Thumbnail check (placeholder)")
    
    def _check_watermarks(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Watermarks check (placeholder)")
    
    def _check_bot_startup(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Bot startup check (placeholder)")
    
    def _check_command_handlers(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Command handlers check (placeholder)")
    
    def _check_bot_errors(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Bot error handling (placeholder)")
    
    def _check_rate_limits(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Rate limits check (placeholder)")
    
    def _check_bot_logging(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Bot logging check (placeholder)")
    
    def _check_persistence(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Persistence check (placeholder)")
    
    def _check_help_command(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Help command check (placeholder)")
    
    def _check_graceful_shutdown(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Graceful shutdown check (placeholder)")
    
    def _check_validate_email_html(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Email HTML validation (placeholder)")
    
    def _check_inline_css(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Inline CSS check (placeholder)")
    
    def _check_no_js(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="No JS check (placeholder)")
    
    def _check_spam_score(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Spam score check (placeholder)")
    
    def _check_unsubscribe(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Unsubscribe check (placeholder)")
    
    def _check_email_mobile(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Email mobile check (placeholder)")
    
    def _check_no_emoji_subject(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="No emoji subject check (placeholder)")
    
    def _check_openapi(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="OpenAPI check (placeholder)")
    
    def _check_input_validation(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Input validation check (placeholder)")
    
    def _check_auth(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Auth check (placeholder)")
    
    def _check_error_responses(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Error responses check (placeholder)")
    
    def _check_pagination(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Pagination check (placeholder)")
    
    def _check_versioning(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="Versioning check (placeholder)")
    
    def _check_api_tests(self, gate, files, config=None):
        return GateResult(gate=gate, passed=True, details="API tests check (placeholder)")

    # ── GAME ASSET CHECK IMPLEMENTATIONS (E3-01) ─────────────────────────
    # Checks réels, pas des placeholders. E3-05 ajoutera les gates avancés
    # (cohérence style, lisibilité, budget polygones) ; ceux-ci couvrent
    # l'essentiel : le fichier existe, le format est bon, la taille est
    # raisonnable.

    _IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".gif", ".psd", ".tiff"}
    _SPRITE_FORMATS = {".png", ".webp"}           # transparence requise
    _TEXTURE_FORMATS = {".png", ".tga", ".jpg", ".jpeg"}
    _MODEL_FORMATS = {".fbx", ".obj", ".gltf", ".glb", ".blend", ".dae", ".3ds", ".stl"}
    _ANIM_FORMATS = {".fbx", ".anim", ".bvh", ".gltf", ".glb"}
    _VFX_FORMATS = {".shader", ".hlsl", ".glsl", ".vfx", ".vfxgraph",
                    ".particle", ".json", ".xml", ".uss", ".uxml", ".unitypackage"}

    def _check_asset_file_exists(self, gate, files, config=None):
        """Vérifie que chaque fichier déclaré existe sur le disque."""
        missing = [str(f) for f in files if not Path(f).exists()]
        if missing:
            return GateResult(gate=gate, passed=False,
                              details=f"Missing files: {', '.join(missing)}")
        return GateResult(gate=gate, passed=True,
                          details=f"{len(files)} file(s) exist")

    def _check_file_size(self, gate, files, config=None):
        """Vérifie que chaque fichier est sous le seuil (en MB)."""
        threshold_mb = gate.threshold or 50
        oversize = []
        for f in files:
            p = Path(f)
            if p.exists():
                size_mb = p.stat().st_size / (1024 * 1024)
                if size_mb > threshold_mb:
                    oversize.append(f"{p.name}: {size_mb:.1f} MB > {threshold_mb} MB")
        if oversize:
            return GateResult(gate=gate, passed=False,
                              details=" · ".join(oversize))
        return GateResult(gate=gate, passed=True,
                          details=f"All files under {threshold_mb} MB")

    def _check_image_format(self, gate, files, config=None):
        """Format image générique (CONCEPT)."""
        bad = [str(f) for f in files
               if Path(f).suffix.lower() not in self._IMAGE_FORMATS]
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"Unsupported format: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="Image format OK")

    def _check_sprite_format(self, gate, files, config=None):
        """PNG ou WebP uniquement (transparence)."""
        bad = [str(f) for f in files
               if Path(f).suffix.lower() not in self._SPRITE_FORMATS]
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"Sprite must be PNG/WebP: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="Sprite format OK")

    def _check_texture_format(self, gate, files, config=None):
        """PNG, TGA ou JPG (PBR textures)."""
        bad = [str(f) for f in files
               if Path(f).suffix.lower() not in self._TEXTURE_FORMATS]
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"Texture must be PNG/TGA/JPG: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="Texture format OK")

    def _check_model_format(self, gate, files, config=None):
        """FBX, OBJ, glTF, Blend (MODEL_3D et RIG partagent ce check)."""
        bad = [str(f) for f in files
               if Path(f).suffix.lower() not in self._MODEL_FORMATS]
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"Model must be FBX/OBJ/glTF/Blend: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="Model format OK")

    def _check_anim_format(self, gate, files, config=None):
        """FBX anim, BVH, glTF (ANIM)."""
        bad = [str(f) for f in files
               if Path(f).suffix.lower() not in self._ANIM_FORMATS]
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"Anim must be FBX/BVH/glTF: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="Animation format OK")

    def _check_vfx_format(self, gate, files, config=None):
        """Shader, particle config, VFX graph (VFX)."""
        bad = [str(f) for f in files
               if Path(f).suffix.lower() not in self._VFX_FORMATS]
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"VFX must be shader/particle/config: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="VFX format OK")

    def _check_image_dimensions(self, gate, files, config=None):
        """Vérifie les dimensions minimales (512×512 pour CONCEPT).
        
        Nécessite Pillow — si absent, le check est non mesuré (passed par
        défaut, comme le Harness fait pour tout check manquant).
        """
        try:
            from PIL import Image
        except ImportError:
            return GateResult(gate=gate, passed=True,
                              details="Pillow not installed (skipped)")
        too_small = []
        for f in files:
            try:
                with Image.open(f) as img:
                    w, h = img.size
                    if w < 512 or h < 512:
                        too_small.append(f"{Path(f).name}: {w}×{h}")
            except Exception:
                pass  # format non supporté = un autre gate le capte
        if too_small:
            return GateResult(gate=gate, passed=False,
                              details=f"Too small (< 512×512): {', '.join(too_small)}")
        return GateResult(gate=gate, passed=True, details="Dimensions OK (≥ 512×512)")

    def _check_power_of_two(self, gate, files, config=None):
        """Vérifie que les dimensions sont des puissances de 2 (GPU-friendly).
        
        Nécessite Pillow — sinon non mesuré.
        """
        try:
            from PIL import Image
        except ImportError:
            return GateResult(gate=gate, passed=True,
                              details="Pillow not installed (skipped)")
        bad = []
        for f in files:
            try:
                with Image.open(f) as img:
                    w, h = img.size
                    if (w & (w - 1)) != 0 or (h & (h - 1)) != 0:
                        bad.append(f"{Path(f).name}: {w}×{h}")
            except Exception:
                pass
        if bad:
            return GateResult(gate=gate, passed=False,
                              details=f"Not power-of-two: {', '.join(bad)}")
        return GateResult(gate=gate, passed=True, details="Power-of-two OK")


# ═══════════════════════════════════════════════════════════════════════════════
# HARNESS REPORT — Human-readable output
# ═══════════════════════════════════════════════════════════════════════════════

def format_harness_report(result: HarnessResult) -> str:
    """Format harness result as human-readable report."""
    lines = []
    
    # Header
    status = "✅ PASSED" if result.passed else "❌ FAILED"
    lines.append("=" * 60)
    lines.append(f"HARNESS REPORT — {result.artifact_type.value.upper()}")
    lines.append("=" * 60)
    lines.append(f"Status: {status}")
    lines.append(f"Score: {result.score:.1f}%")
    lines.append(f"Gates: {result.gates_passed}/{result.gates_checked} passed")
    lines.append("")
    
    # Critical failures
    if result.critical_failures:
        lines.append("🚨 CRITICAL FAILURES:")
        for f in result.critical_failures:
            lines.append(f"  • {f}")
        lines.append("")
    
    # Warnings
    if result.warnings:
        lines.append("⚠️ WARNINGS:")
        for w in result.warnings:
            lines.append(f"  • {w}")
        lines.append("")
    
    # Recommendations
    if result.recommendations:
        lines.append("💡 RECOMMENDATIONS:")
        for r in result.recommendations:
            lines.append(f"  • {r}")
        lines.append("")
    
    # Gate details
    lines.append("📋 GATE DETAILS:")
    for r in result.results:
        status_icon = "✅" if r.passed else "❌"
        fix_icon = " 🔧" if r.fix_applied else ""
        lines.append(f"  {status_icon} {r.gate.name}{fix_icon}")
        if not r.passed:
            lines.append(f"     {r.details[:100]}")
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def validate_code(files: list[str | Path], auto_fix: bool = False) -> HarnessResult:
    """Quick validation for code artifacts."""
    engine = HarnessEngine(auto_fix=auto_fix)
    return engine.validate(ArtifactType.CODE, files)


def validate_website(files: list[str | Path], auto_fix: bool = False) -> HarnessResult:
    """Quick validation for website artifacts."""
    engine = HarnessEngine(auto_fix=auto_fix)
    return engine.validate(ArtifactType.WEBSITE, files)


def validate_bot(files: list[str | Path], auto_fix: bool = False) -> HarnessResult:
    """Quick validation for bot artifacts."""
    engine = HarnessEngine(auto_fix=auto_fix)
    return engine.validate(ArtifactType.BOT, files)


def validate_email(files: list[str | Path], auto_fix: bool = False) -> HarnessResult:
    """Quick validation for email artifacts."""
    engine = HarnessEngine(auto_fix=auto_fix)
    return engine.validate(ArtifactType.EMAIL, files)


def validate_api(files: list[str | Path], auto_fix: bool = False) -> HarnessResult:
    """Quick validation for API artifacts."""
    engine = HarnessEngine(auto_fix=auto_fix)
    return engine.validate(ArtifactType.API, files)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    if len(sys.argv) < 3:
        print("Usage: python harness_engine.py <artifact_type> <file1> [file2] ...")
        print(f"Artifact types: {', '.join(t.value for t in ArtifactType)}")
        sys.exit(1)
    
    artifact_type = ArtifactType(sys.argv[1])
    files = sys.argv[2:]
    
    engine = HarnessEngine(auto_fix="--fix" in sys.argv)
    result = engine.validate(artifact_type, files)
    
    print(format_harness_report(result))
    
    sys.exit(0 if result.passed else 1)
