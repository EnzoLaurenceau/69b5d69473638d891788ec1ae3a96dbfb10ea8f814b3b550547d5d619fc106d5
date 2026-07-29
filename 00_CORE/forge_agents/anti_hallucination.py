"""
Anti-Hallucination Engine — Semantic Gravity + Iteration Limits
Based on: Semantic Gravity Framework, Antigravity Retry, Chain-of-Verification
"""

import json
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import hashlib


class HallucinationType(Enum):
    FACTUAL_ERROR = "factual_error"
    LOGICAL_CONTRADICTION = "logical_contradiction"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    FABRICATED_REFERENCE = "fabricated_reference"
    CONFABULATION = "confabulation"


@dataclass
class HallucinationDetection:
    """Detection result for a single hallucination."""
    text: str
    hallucination_type: HallucinationType
    confidence: float
    explanation: str
    grounding_source: Optional[str]
    suggestion: str


@dataclass
class AntiHallucinationResult:
    """Result of anti-hallucination analysis."""
    original_text: str
    cleaned_text: str
    hallucinations_detected: List[HallucinationDetection]
    hallucination_score: float
    is_safe: bool
    iterations_used: int
    verification_chain: List[Dict]


class AntiHallucinationEngine:
    """
    Engine to prevent AI hallucinations using multiple strategies:
    1. Semantic Gravity - Ground claims in authoritative sources
    2. Iteration Limits - Prevent correction treadmills
    3. Step-Back Verification - Force broad evaluation
    4. Chain-of-Verification - Require explanation of reasoning
    """
    
    def __init__(self, max_iterations: int = 3):
        self.max_iterations = max_iterations
        self.iteration_count = 0
        self.verification_history = []
        self.authoritative_sources = self._load_authoritative_sources()
        
    def _load_authoritative_sources(self) -> Dict:
        """Load authoritative sources for grounding."""
        return {
            "security": {
                "sources": [
                    "OWASP Top 10",
                    "CWE/SANS Top 25",
                    "NIST Cybersecurity Framework",
                    "MITRE ATT&CK",
                    "CVE Details"
                ],
                "keywords": ["vulnerability", "exploit", "attack", "security", "threat"]
            },
            "algorithms": {
                "sources": [
                    "Introduction to Algorithms (CLRS)",
                    "Algorithm Design Manual (Skiena)",
                    "Big-O Cheat Sheet",
                    "GeeksforGeeks",
                    "LeetCode"
                ],
                "keywords": ["algorithm", "complexity", "data structure", "optimization"]
            },
            "programming": {
                "sources": [
                    "Official documentation",
                    "MDN Web Docs",
                    "Python.org",
                    "Stack Overflow (verified answers)",
                    "GitHub Issues"
                ],
                "keywords": ["function", "method", "API", "library", "framework"]
            },
            "science": {
                "sources": [
                    "Peer-reviewed journals",
                    "arXiv",
                    "Nature",
                    "Science",
                    "IEEE"
                ],
                "keywords": ["research", "study", "experiment", "theory", "hypothesis"]
            }
        }
    
    def analyze_response(self, response: str, context: Dict = None) -> AntiHallucinationResult:
        """
        Analyze response for hallucinations using multiple strategies.
        Implements iterative verification with limits.
        """
        self.iteration_count = 0
        verification_chain = []
        hallucinations = []
        
        current_text = response
        
        # Iterative verification loop
        while self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            
            # Strategy 1: Semantic Gravity Check
            gravity_result = self._check_semantic_gravity(current_text, context)
            verification_chain.append({
                "iteration": self.iteration_count,
                "strategy": "semantic_gravity",
                "result": gravity_result
            })
            
            if gravity_result["hallucinations"]:
                hallucinations.extend(gravity_result["hallucinations"])
                current_text = self._apply_gravity_corrections(
                    current_text, gravity_result["hallucinations"]
                )
            
            # Strategy 2: Step-Back Verification
            stepback_result = self._step_back_verification(current_text, context)
            verification_chain.append({
                "iteration": self.iteration_count,
                "strategy": "step_back",
                "result": stepback_result
            })
            
            if stepback_result["needs_correction"]:
                hallucinations.extend(stepback_result["hallucinations"])
                current_text = stepback_result["corrected_text"]
            
            # Strategy 3: Chain-of-Verification
            chain_result = self._chain_of_verification(current_text, context)
            verification_chain.append({
                "iteration": self.iteration_count,
                "strategy": "chain_verification",
                "result": chain_result
            })
            
            if chain_result["hallucinations"]:
                hallucinations.extend(chain_result["hallucinations"])
                current_text = self._apply_chain_corrections(
                    current_text, chain_result["hallucinations"]
                )
            
            # If no hallucinations found, break
            if not hallucinations:
                break
        
        # Calculate hallucination score
        hallucination_score = self._calculate_hallucination_score(hallucinations)
        
        return AntiHallucinationResult(
            original_text=response,
            cleaned_text=current_text,
            hallucinations_detected=hallucinations,
            hallucination_score=hallucination_score,
            is_safe=hallucination_score < 0.3,
            iterations_used=self.iteration_count,
            verification_chain=verification_chain
        )
    
    def _check_semantic_gravity(self, text: str, context: Dict = None) -> Dict:
        """
        Check if claims are grounded in authoritative sources.
        Implements 'According to' pattern.
        """
        hallucinations = []
        
        # Extract claims from text
        claims = self._extract_claims(text)
        
        for claim in claims:
            # Check if claim has attribution
            has_attribution = self._check_attribution(claim)
            
            if not has_attribution:
                # Check if claim needs attribution
                if self._needs_attribution(claim):
                    hallucinations.append(HallucinationDetection(
                        text=claim,
                        hallucination_type=HallucinationType.UNSUPPORTED_CLAIM,
                        confidence=0.8,
                        explanation="Claim lacks attribution to authoritative source",
                        grounding_source=None,
                        suggestion=f"Add 'According to [source]' or remove claim"
                    ))
        
        return {
            "hallucinations": hallucinations,
            "grounded_claims": len(claims) - len(hallucinations),
            "total_claims": len(claims)
        }
    
    def _step_back_verification(self, text: str, context: Dict = None) -> Dict:
        """
        Force step-back evaluation of fundamental facts.
        Breaks recursive thought patterns.
        """
        hallucinations = []
        needs_correction = False
        
        # Extract key assertions
        assertions = self._extract_assertions(text)
        
        for assertion in assertions:
            # Check against fundamental rules
            if self._contradicts_fundamentals(assertion):
                hallucinations.append(HallucinationDetection(
                    text=assertion,
                    hallucination_type=HallucinationType.LOGICAL_CONTRADICTION,
                    confidence=0.9,
                    explanation="Contradicts fundamental rules or principles",
                    grounding_source="fundamental_principles",
                    suggestion="Revise assertion to align with fundamentals"
                ))
                needs_correction = True
        
        corrected_text = text
        if needs_correction:
            corrected_text = self._apply_stepback_corrections(text, hallucinations)
        
        return {
            "hallucinations": hallucinations,
            "needs_correction": needs_correction,
            "corrected_text": corrected_text
        }
    
    def _chain_of_verification(self, text: str, context: Dict = None) -> Dict:
        """
        Mandate chain-of-verification for explanations.
        Model must explain why it took an action.
        """
        hallucinations = []
        
        # Check for explanation chains
        explanations = self._extract_explanations(text)
        
        for explanation in explanations:
            # Verify explanation has logical chain
            if not self._has_logical_chain(explanation):
                hallucinations.append(HallucinationDetection(
                    text=explanation,
                    hallucination_type=HallucinationType.CONFABULATION,
                    confidence=0.7,
                    explanation="Explanation lacks logical chain of reasoning",
                    grounding_source=None,
                    suggestion="Add step-by-step reasoning or remove explanation"
                ))
        
        return {
            "hallucinations": hallucinations,
            "explanations_checked": len(explanations)
        }
    
    def _extract_claims(self, text: str) -> List[str]:
        """Extract verifiable claims from text."""
        claims = []
        
        # Split by sentences
        sentences = re.split(r'[.!?]+', text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 15:
                # Look for factual claims
                if any(keyword in sentence.lower() for keyword in [
                    "is", "are", "was", "were", "has", "have", "will",
                    "can", "could", "should", "must", "always", "never"
                ]):
                    claims.append(sentence)
        
        return claims[:15]  # Limit for efficiency
    
    def _check_attribution(self, claim: str) -> bool:
        """Check if claim has attribution."""
        attribution_patterns = [
            r'according to\s+',
            r'as stated in\s+',
            r'per\s+',
            r'based on\s+',
            r'from\s+',
            r'source:\s+',
            r'reference:\s+'
        ]
        
        for pattern in attribution_patterns:
            if re.search(pattern, claim.lower()):
                return True
        
        return False
    
    def _needs_attribution(self, claim: str) -> bool:
        """Check if claim needs attribution."""
        # Claims that are common knowledge don't need attribution
        common_knowledge = [
            "the sky is blue",
            "water is h2o",
            "1+1=2",
            "earth revolves around sun"
        ]
        
        claim_lower = claim.lower()
        for knowledge in common_knowledge:
            if knowledge in claim_lower:
                return False
        
        # Technical claims need attribution
        technical_keywords = [
            "algorithm", "protocol", "standard", "specification",
            "research shows", "studies indicate", "experts say"
        ]
        
        for keyword in technical_keywords:
            if keyword in claim_lower:
                return True
        
        return False
    
    def _extract_assertions(self, text: str) -> List[str]:
        """Extract key assertions from text."""
        assertions = []
        
        # Look for strong assertions
        assertion_patterns = [
            r'this (is|will|must|should)\s+',
            r'we (need|must|should)\s+',
            r'it (is|will|must)\s+',
            r'the (correct|right|only)\s+'
        ]
        
        for pattern in assertion_patterns:
            matches = re.findall(pattern + r'[^.!?]+[.!?]', text, re.IGNORECASE)
            assertions.extend(matches)
        
        return assertions[:10]
    
    def _contradicts_fundamentals(self, assertion: str) -> bool:
        """Check if assertion contradicts fundamental principles."""
        assertion_lower = assertion.lower()
        
        # Security fundamentals
        security_contradictions = [
            ("plaintext passwords are secure", "plaintext passwords"),
            ("sql injection is not a threat", "sql injection"),
            ("xss cannot be prevented", "xss"),
            ("firewalls are unnecessary", "firewall")
        ]
        
        for contradiction, keyword in security_contradictions:
            if keyword in assertion_lower and "not" in assertion_lower:
                return True
        
        # Logic fundamentals
        logic_contradictions = [
            ("always never", "always.*never"),
            ("all none", "all.*none"),
            ("true false", "true.*false")
        ]
        
        for contradiction, pattern in logic_contradictions:
            if re.search(pattern, assertion_lower):
                return True
        
        return False
    
    def _extract_explanations(self, text: str) -> List[str]:
        """Extract explanations from text."""
        explanations = []
        
        # Look for explanation patterns
        explanation_patterns = [
            r'because\s+[^.!?]+[.!?]',
            r'since\s+[^.!?]+[.!?]',
            r'therefore\s+[^.!?]+[.!?]',
            r'thus\s+[^.^.!?]+[.!?]',
            r'hence\s+[^.!?]+[.!?]'
        ]
        
        for pattern in explanation_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            explanations.extend(matches)
        
        return explanations[:10]
    
    def _has_logical_chain(self, explanation: str) -> bool:
        """Check if explanation has logical chain."""
        # Look for logical connectors
        logical_connectors = [
            "because", "since", "therefore", "thus", "hence",
            "consequently", "as a result", "it follows that"
        ]
        
        explanation_lower = explanation.lower()
        connector_count = sum(1 for connector in logical_connectors 
                            if connector in explanation_lower)
        
        return connector_count >= 1
    
    def _apply_gravity_corrections(self, text: str, 
                                  hallucinations: List[HallucinationDetection]) -> str:
        """Apply corrections based on gravity check."""
        corrected = text
        
        for hallucination in hallucinations:
            if hallucination.hallucination_type == HallucinationType.UNSUPPORTED_CLAIM:
                # Add attribution placeholder
                corrected = corrected.replace(
                    hallucination.text,
                    f"[NEEDS SOURCE: {hallucination.text}]"
                )
        
        return corrected
    
    def _apply_stepback_corrections(self, text: str,
                                   hallucinations: List[HallucinationDetection]) -> str:
        """Apply corrections based on step-back verification."""
        corrected = text
        
        for hallucination in hallucinations:
            if hallucination.hallucination_type == HallucinationType.LOGICAL_CONTRADICTION:
                # Mark contradiction
                corrected = corrected.replace(
                    hallucination.text,
                    f"[CONTRADICTION: {hallucination.text}]"
                )
        
        return corrected
    
    def _apply_chain_corrections(self, text: str,
                                hallucinations: List[HallucinationDetection]) -> str:
        """Apply corrections based on chain verification."""
        corrected = text
        
        for hallucination in hallucinations:
            if hallucination.hallucination_type == HallucinationType.CONFABULATION:
                # Mark confabulation
                corrected = corrected.replace(
                    hallucination.text,
                    f"[UNVERIFIED: {hallucination.text}]"
                )
        
        return corrected
    
    def _calculate_hallucination_score(self, 
                                      hallucinations: List[HallucinationDetection]) -> float:
        """Calculate overall hallucination score."""
        if not hallucinations:
            return 0.0
        
        # Weight by confidence and type
        total_score = 0.0
        for hallucination in hallucinations:
            weight = {
                HallucinationType.FACTUAL_ERROR: 1.0,
                HallucinationType.LOGICAL_CONTRADICTION: 0.9,
                HallucinationType.UNSUPPORTED_CLAIM: 0.7,
                HallucinationType.FABRICATED_REFERENCE: 1.0,
                HallucinationType.CONFABULATION: 0.8
            }.get(hallucination.hallucination_type, 0.5)
            
            total_score += hallucination.confidence * weight
        
        # Normalize to 0-1 range
        return min(1.0, total_score / len(hallucinations))
    
    def get_safe_response(self, response: str, context: Dict = None) -> Dict:
        """
        Get safe response with hallucinations removed/flagged.
        Main entry point for integration.
        """
        result = self.analyze_response(response, context)
        
        return {
            "original": result.original_text,
            "safe_response": result.cleaned_text,
            "is_safe": result.is_safe,
            "hallucination_score": result.hallucination_score,
            "hallucinations_count": len(result.hallucinations_detected),
            "iterations_used": result.iterations_used,
            "verification_summary": self._get_verification_summary(result)
        }
    
    def _get_verification_summary(self, result: AntiHallucinationResult) -> Dict:
        """Get summary of verification process."""
        return {
            "strategies_used": ["semantic_gravity", "step_back", "chain_verification"],
            "iterations": result.iterations_used,
            "hallucinations_by_type": self._group_hallucinations_by_type(
                result.hallucinations_detected
            ),
            "grounding_sources_checked": self._get_checked_sources(result)
        }
    
    def _group_hallucinations_by_type(self, 
                                     hallucinations: List[HallucinationDetection]) -> Dict:
        """Group hallucinations by type."""
        grouped = {}
        for hallucination in hallucinations:
            h_type = hallucination.hallucination_type.value
            if h_type not in grouped:
                grouped[h_type] = 0
            grouped[h_type] += 1
        return grouped
    
    def _get_checked_sources(self, result: AntiHallucinationResult) -> List[str]:
        """Get sources checked during verification."""
        sources = set()
        for step in result.verification_chain:
            if "result" in step and "grounding_source" in step["result"]:
                source = step["result"]["grounding_source"]
                if source:
                    sources.add(source)
        return list(sources)


# Integration with Forge
def anti_hallucination_node(state: Dict) -> Dict:
    """
    LangGraph node for anti-hallucination checking.
    Integrates with ForgeState.
    """
    engine = AntiHallucinationEngine(max_iterations=3)
    
    # Get response to check
    response = state.get("current_response", "")
    context = state.get("context", {})
    
    if not response:
        return state
    
    # Check for hallucinations
    result = engine.get_safe_response(response, context)
    
    # Update state
    if "hallucination_checks" not in state:
        state["hallucination_checks"] = []
    
    state["hallucination_checks"].append({
        "source": "anti_hallucination_engine",
        "result": result,
        "timestamp": datetime.now().isoformat()
    })
    
    # If not safe, flag for revision
    if not result["is_safe"]:
        state["needs_revision"] = True
        state["revision_reason"] = f"Hallucination score: {result['hallucination_score']:.1%}"
        state["safe_response"] = result["safe_response"]
    
    return state


if __name__ == "__main__":
    # Test the anti-hallucination engine
    engine = AntiHallucinationEngine()
    
    test_responses = [
        "SQL injection is always prevented by using parameterized queries.",
        "According to OWASP, input validation is a primary defense against injection.",
        "This algorithm is O(1) because it uses nested loops.",
        "Firewalls are unnecessary for modern web applications."
    ]
    
    for response in test_responses:
        print(f"\nOriginal: {response}")
        result = engine.get_safe_response(response)
        print(f"Safe: {result['is_safe']}")
        print(f"Score: {result['hallucination_score']:.1%}")
        print(f"Hallucinations: {result['hallucinations_count']}")
        if result['hallucinations_count'] > 0:
            print(f"Cleaned: {result['safe_response']}")
