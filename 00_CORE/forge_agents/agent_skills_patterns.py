"""
Agent Skills Patterns Module for La Forge
==========================================
Production-grade SDLC workflow patterns from Addy Osmani's agent-skills.
Maps 6 lifecycle stages into forge-compatible skill definitions.

Source: https://github.com/addyosmani/agent-skills
Priority: HIGH — Governs agent quality gates & anti-rationalization.

NMP: TOOL|INDEX|agent_skills_patterns|savings=65|pattern=sdlc governance|approach=Define→Plan→Build→Verify→Review→Ship lifecycle with exit criteria
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LifecycleStage(Enum):
    DEFINE = "define"     # /spec — requirements & scope
    PLAN = "plan"         # /plan — architecture & approach
    BUILD = "build"       # /build — implementation with TDD
    VERIFY = "verify"     # /test — testing & validation
    REVIEW = "review"     # /review — security & code review
    SHIP = "ship"         # /ship — deploy & monitor


@dataclass
class ExitCriteria:
    """Conditions that MUST be met before moving to next stage."""
    description: str
    checks: list[str]
    blockers: list[str] = field(default_factory=list)

    def evaluate(self, results: dict) -> bool:
        """Check if all exit criteria are satisfied."""
        return all(results.get(check, False) for check in self.checks)


@dataclass
class AntiRationalization:
    """
    Prevents AI agents from cutting corners.
    From agent-skills: explicit patterns that agents must NOT rationalize away.
    Maps to forge's anti_hallucination engine.
    """
    pattern: str          # What the agent might try to skip
    rationalization: str  # How the agent justifies skipping it
    enforcement: str      # What to do instead
    severity: str = "HIGH"  # HIGH | CRITICAL


@dataclass
class AgentSkill:
    """Single SDLC skill with triggers, process, and verification."""
    name: str
    stage: LifecycleStage
    slash_command: str
    description: str
    triggers: list[str]
    process_steps: list[str]
    exit_criteria: ExitCriteria
    anti_rationalizations: list[AntiRationalization] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    estimated_tokens: int = 0


# ─── Core SDLC Skills ───────────────────────────────────────────────────

SKILLS_CATALOG: dict[str, AgentSkill] = {
    "spec": AgentSkill(
        name="Specification & Requirements",
        stage=LifecycleStage.DEFINE,
        slash_command="/spec",
        description="Define clear requirements, acceptance criteria, and scope before any code is written.",
        triggers=[
            "new feature request",
            "unclear requirements",
            "ambiguous user story",
            "scope creep detected",
            "missing acceptance criteria",
        ],
        process_steps=[
            "1. Gather context: read existing code, docs, and related issues",
            "2. Identify stakeholders and constraints",
            "3. Write user stories with acceptance criteria (Given/When/Then)",
            "4. Define scope boundaries: what IS and IS NOT included",
            "5. List assumptions and open questions",
            "6. Estimate complexity (S/M/L/XL)",
            "7. Get explicit approval before proceeding",
        ],
        exit_criteria=ExitCriteria(
            description="Requirements are clear, complete, and approved",
            checks=[
                "acceptance_criteria_defined",
                "scope_boundaries_set",
                "complexity_estimated",
                "stakeholder_approved",
            ],
        ),
        anti_rationalizations=[
            AntiRationalization(
                pattern="Skipping spec for 'simple' changes",
                rationalization="This is too simple to need a spec",
                enforcement="Even simple changes need explicit acceptance criteria. Write at least 3 Given/When/Then statements.",
                severity="HIGH",
            ),
        ],
        red_flags=[
            "Vague requirements like 'make it better'",
            "No acceptance criteria defined",
            "Scope keeps expanding during spec phase",
        ],
    ),

    "plan": AgentSkill(
        name="Architecture & Planning",
        stage=LifecycleStage.PLAN,
        slash_command="/plan",
        description="Design the technical approach with clear architecture decisions before building.",
        triggers=[
            "spec approved",
            "architecture decision needed",
            "multiple approaches possible",
            "cross-system changes",
            "performance-critical feature",
        ],
        process_steps=[
            "1. Analyze spec requirements and constraints",
            "2. Research existing patterns in codebase",
            "3. Identify 2-3 viable approaches with tradeoffs",
            "4. Select approach with rationale",
            "5. Design component boundaries and interfaces",
            "6. Plan data model changes if any",
            "7. Identify risks and mitigations",
            "8. Create implementation checklist",
        ],
        exit_criteria=ExitCriteria(
            description="Architecture is documented, reviewed, and approved",
            checks=[
                "approach_selected_with_rationale",
                "component_boundaries_defined",
                "risks_identified",
                "implementation_checklist_created",
            ],
        ),
        anti_rationalizations=[
            AntiRationalization(
                pattern="Jumping to code without planning",
                rationalization="I already know what to do, planning is overhead",
                enforcement="Write at minimum: approach rationale, component list, risk assessment. 10 minutes of planning saves hours of refactoring.",
                severity="CRITICAL",
            ),
        ],
        red_flags=[
            "No alternatives considered",
            "Missing risk assessment",
            "Plan doesn't address edge cases",
        ],
    ),

    "build": AgentSkill(
        name="Implementation with TDD",
        stage=LifecycleStage.BUILD,
        slash_command="/build",
        description="Build the feature with test-driven development, incremental commits, and clean code.",
        triggers=[
            "plan approved",
            "implementation phase",
            "coding task",
            "feature development",
        ],
        process_steps=[
            "1. Set up test infrastructure if needed",
            "2. Write failing test for first acceptance criterion",
            "3. Implement minimal code to pass the test",
            "4. Refactor while keeping tests green",
            "5. Repeat for each acceptance criterion",
            "6. Handle edge cases with explicit tests",
            "7. Add error handling and logging",
            "8. Write inline documentation for non-obvious code",
            "9. Commit incrementally with descriptive messages",
        ],
        exit_criteria=ExitCriteria(
            description="All acceptance criteria have passing tests, code is clean",
            checks=[
                "all_acceptance_criteria_tested",
                "tests_passing",
                "error_handling_complete",
                "code_documented",
            ],
        ),
        anti_rationalizations=[
            AntiRationalization(
                pattern="Writing tests after implementation",
                rationalization="I'll write the code first and add tests later",
                enforcement="Write the test FIRST. If you can't write the test, you don't understand the requirement.",
                severity="HIGH",
            ),
            AntiRationalization(
                pattern="Skipping error handling",
                rationalization="Happy path works, edge cases are unlikely",
                enforcement="Every external call needs error handling. Every user input needs validation.",
                severity="HIGH",
            ),
        ],
        red_flags=[
            "Large commits with multiple unrelated changes",
            "No test coverage for new code",
            "Hardcoded values instead of configuration",
        ],
    ),

    "verify": AgentSkill(
        name="Testing & Validation",
        stage=LifecycleStage.VERIFY,
        slash_command="/test",
        description="Comprehensive testing: unit, integration, edge cases, performance, security.",
        triggers=[
            "build complete",
            "pre-review validation",
            "regression testing",
            "performance concern",
        ],
        process_steps=[
            "1. Run full test suite — all tests must pass",
            "2. Check test coverage (target: >80%)",
            "3. Test edge cases and error paths",
            "4. Run integration tests if applicable",
            "5. Performance test critical paths",
            "6. Verify backward compatibility",
            "7. Test with production-like data/config",
            "8. Document test results",
        ],
        exit_criteria=ExitCriteria(
            description="All tests pass, coverage adequate, no regressions",
            checks=[
                "all_tests_passing",
                "coverage_above_threshold",
                "no_regressions",
                "edge_cases_covered",
            ],
        ),
        anti_rationalizations=[
            AntiRationalization(
                pattern="Marking flaky tests as known issues",
                rationalization="This test is flaky, it's a known issue",
                enforcement="Fix flaky tests immediately. Flaky tests erode trust in the entire test suite.",
                severity="CRITICAL",
            ),
        ],
    ),

    "review": AgentSkill(
        name="Security & Code Review",
        stage=LifecycleStage.REVIEW,
        slash_command="/review",
        description="Security audit, code quality review, and vulnerability scanning.",
        triggers=[
            "verification complete",
            "security review needed",
            "code review requested",
            "pre-merge check",
        ],
        process_steps=[
            "1. Run static analysis (semgrep, eslint, etc.)",
            "2. Check OWASP Top 10 vulnerabilities",
            "3. Review authentication/authorization paths",
            "4. Check for secret/credential exposure",
            "5. Validate input sanitization",
            "6. Review dependency versions for CVEs",
            "7. Check for injection vectors (SQLi, XSS, SSRF)",
            "8. Verify error messages don't leak internals",
            "9. Review logging (no PII, adequate audit trail)",
        ],
        exit_criteria=ExitCriteria(
            description="No critical/high security issues, code quality acceptable",
            checks=[
                "no_critical_vulnerabilities",
                "no_secret_exposure",
                "input_validation_complete",
                "dependencies_scanned",
            ],
        ),
        anti_rationalizations=[
            AntiRationalization(
                pattern="Skipping security review for internal tools",
                rationalization="This is internal only, security doesn't matter",
                enforcement="Internal tools get compromised too. Run OWASP checks regardless. The forge's ZSL cyber engine must validate.",
                severity="CRITICAL",
            ),
        ],
    ),

    "ship": AgentSkill(
        name="Deployment & Monitoring",
        stage=LifecycleStage.SHIP,
        slash_command="/ship",
        description="Deploy with rollback plan, monitoring, and post-deploy verification.",
        triggers=[
            "review approved",
            "ready to deploy",
            "release candidate",
        ],
        process_steps=[
            "1. Create rollback plan",
            "2. Document deployment steps",
            "3. Set up monitoring/alerts for new features",
            "4. Deploy to staging first",
            "5. Run smoke tests on staging",
            "6. Deploy to production with feature flags if applicable",
            "7. Monitor error rates, latency, and key metrics",
            "8. Keep rollback ready for 24h",
        ],
        exit_criteria=ExitCriteria(
            description="Deployed, monitored, stable for 24h",
            checks=[
                "rollback_plan_ready",
                "staging_validated",
                "production_deployed",
                "monitoring_active",
            ],
        ),
    ),
}


# ─── Meta-Skill Router ──────────────────────────────────────────────────

class SkillRouter:
    """
    Meta-skill: routes tasks to the appropriate lifecycle stage.
    Maps to forge orchestrator's task routing logic.
    """

    def __init__(self):
        self.skills = SKILLS_CATALOG
        self.current_stage: Optional[LifecycleStage] = None
        self.stage_history: list[LifecycleStage] = []

    def detect_stage(self, task_description: str) -> AgentSkill:
        """Detect which lifecycle stage a task belongs to."""
        task_lower = task_description.lower()

        # Priority-ordered keyword matching
        stage_keywords = {
            LifecycleStage.DEFINE: ["spec", "requirement", "scope", "define", "acceptance criteria", "user story"],
            LifecycleStage.PLAN: ["plan", "architect", "design", "approach", "tradeoff", "rfc"],
            LifecycleStage.BUILD: ["build", "implement", "code", "develop", "create", "add feature"],
            LifecycleStage.VERIFY: ["test", "verify", "validate", "coverage", "regression", "qa"],
            LifecycleStage.REVIEW: ["review", "security", "audit", "vulnerability", "owasp", "scan"],
            LifecycleStage.SHIP: ["ship", "deploy", "release", "launch", "rollout", "production"],
        }

        for stage, keywords in stage_keywords.items():
            if any(kw in task_lower for kw in keywords):
                skill_key = {
                    LifecycleStage.DEFINE: "spec",
                    LifecycleStage.PLAN: "plan",
                    LifecycleStage.BUILD: "build",
                    LifecycleStage.VERIFY: "verify",
                    LifecycleStage.REVIEW: "review",
                    LifecycleStage.SHIP: "ship",
                }[stage]
                return self.skills[skill_key]

        # Default: if no match, start at spec
        return self.skills["spec"]

    def enforce_order(self, requested_stage: LifecycleStage) -> tuple[bool, str]:
        """
        Enforce stage ordering: DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP.
        Returns (allowed, reason).
        """
        stage_order = list(LifecycleStage)
        if self.current_stage is None:
            if requested_stage != LifecycleStage.DEFINE:
                return False, f"Must start at DEFINE stage. Requested: {requested_stage.value}"
            return True, "OK"

        current_idx = stage_order.index(self.current_stage)
        requested_idx = stage_order.index(requested_stage)

        # Allow same stage (re-iteration) or next stage
        if requested_idx <= current_idx + 1:
            return True, "OK"

        return False, f"Cannot skip from {self.current_stage.value} to {requested_stage.value}. Complete intermediate stages first."

    def advance(self, stage: LifecycleStage):
        """Record stage transition."""
        self.current_stage = stage
        self.stage_history.append(stage)

    def check_anti_rationalizations(self, stage: LifecycleStage, agent_output: str) -> list[str]:
        """
        Scan agent output for rationalization patterns.
        Returns list of warnings if rationalization detected.
        """
        skill = self.skills.get({
            LifecycleStage.DEFINE: "spec",
            LifecycleStage.PLAN: "plan",
            LifecycleStage.BUILD: "build",
            LifecycleStage.VERIFY: "verify",
            LifecycleStage.REVIEW: "review",
            LifecycleStage.SHIP: "ship",
        }.get(stage, "spec"))

        warnings = []
        output_lower = agent_output.lower()
        for ar in skill.anti_rationalizations:
            # Check for rationalization language
            rationalization_signals = [
                "too simple", "don't need", "skip", "later",
                "obvious", "overhead", "just this once", "unlikely",
                "internal only", "known issue",
            ]
            if any(signal in output_lower for signal in rationalization_signals):
                warnings.append(
                    f"⚠️ ANTI-RATIONALIZATION [{ar.severity}]: {ar.pattern}\n"
                    f"   Detected: '{ar.rationalization}'\n"
                    f"   Enforcement: {ar.enforcement}"
                )
        return warnings

    def get_status_nmp(self) -> str:
        """NMP-encoded current state."""
        stage = self.current_stage.value if self.current_stage else "none"
        history = ",".join(s.value for s in self.stage_history[-5:])
        return f"SKILL|ROUTER|stage={stage}|history={history}|skills={len(self.skills)}"


# ─── Forge Integration ──────────────────────────────────────────────────

def create_forge_skill_router() -> SkillRouter:
    """Factory: create router pre-configured for forge's pipeline."""
    return SkillRouter()


def get_skill_for_forge_agent(agent_type: str) -> list[AgentSkill]:
    """Map forge agent types to their relevant SDLC skills."""
    agent_skill_map = {
        "scraper": ["spec", "build"],
        "research": ["spec", "plan"],
        "critic": ["verify", "review"],
        "senior_dev": ["plan", "build", "verify"],
        "audit_agent": ["review"],
        "prompt_engineer": ["spec", "build"],
        "closer_pro": ["ship"],
        "founder_ceo": ["spec", "plan", "ship"],
        "marketing_digital": ["spec", "build", "ship"],
    }
    skill_keys = agent_skill_map.get(agent_type, ["spec"])
    return [SKILLS_CATALOG[k] for k in skill_keys if k in SKILLS_CATALOG]


def get_quality_gates() -> dict:
    """
    Extract all exit criteria as quality gates for MiroFish jury alignment.
    Maps each stage's exit criteria to jury scoring dimensions.
    """
    gates = {}
    for key, skill in SKILLS_CATALOG.items():
        gates[skill.stage.value] = {
            "description": skill.exit_criteria.description,
            "checks": skill.exit_criteria.checks,
            "slash_command": skill.slash_command,
            "red_flags": skill.red_flags,
        }
    return gates
