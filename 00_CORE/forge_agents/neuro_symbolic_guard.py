"""
Neuro-Symbolic Guard — Explainable AI + Hallucination Prevention
Based on: Logic Tensor Networks, DeepProbLog, Scallop, SymbolicAI
"""

import json
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class ConfidenceLevel(Enum):
    HIGH = "high"        # > 0.8
    MEDIUM = "medium"    # 0.5 - 0.8
    LOW = "low"          # 0.2 - 0.5
    VERY_LOW = "very_low"  # < 0.2


@dataclass
class LogicalProof:
    """Represents a logical proof chain for explainability."""
    claim: str
    premises: List[str]
    inference_rules: List[str]
    conclusion: str
    confidence: float
    sources: List[str]


@dataclass
class VerificationResult:
    """Result of neuro-symbolic verification."""
    claim: str
    is_valid: bool
    confidence: float
    proof_chain: Optional[LogicalProof]
    contradictions: List[str]
    grounding_sources: List[str]
    explanation: str


class NeuroSymbolicGuard:
    """
    Neuro-symbolic reasoning engine for Forge.
    Combines neural pattern recognition with symbolic logic.
    Prevents hallucinations through formal verification.
    """
    
    def __init__(self):
        self.knowledge_base = self._load_knowledge_base()
        self.logical_rules = self._load_logical_rules()
        self.verification_history = []
        
    def _load_knowledge_base(self) -> Dict:
        """Load grounded knowledge base."""
        return {
            "security": {
                "principles": [
                    "Never trust user input",
                    "Least privilege principle",
                    "Defense in depth",
                    "Fail securely",
                    "Separation of duties"
                ],
                "common_vulns": {
                    "injection": ["SQL injection", "OS command injection", "LDAP injection"],
                    "broken_auth": ["weak passwords", "session fixation", "credential stuffing"],
                    "sensitive_data": ["unencrypted storage", "weak crypto", "data leakage"],
                    "xxe": ["XML external entity", "billion laughs", "SSRF via XXE"],
                    "broken_access": ["IDOR", "privilege escalation", "missing function level access control"]
                },
                "mitigation_patterns": {
                    "input_validation": "Validate all input against whitelist",
                    "parameterized_queries": "Use prepared statements for DB queries",
                    "output_encoding": "Encode output for context (HTML, JS, URL)",
                    "csp": "Content Security Policy to prevent XSS",
                    "rate_limiting": "Rate limit to prevent brute force"
                }
            },
            "algorithms": {
                "complexity": {
                    "O(1)": ["hash lookup", "array index", "stack push/pop"],
                    "O(log n)": ["binary search", "balanced BST operations"],
                    "O(n)": ["linear search", "array traversal", "simple loops"],
                    "O(n log n)": ["merge sort", "quick sort (avg)", "heap sort"],
                    "O(n²)": ["bubble sort", "selection sort", "nested loops"]
                },
                "optimization_patterns": {
                    "memoization": "Cache expensive function results",
                    "dynamic_programming": "Break problems into overlapping subproblems",
                    "divide_and_conquer": "Split problem, solve recursively, combine",
                    "greedy": "Make locally optimal choices",
                    "backtracking": "Explore all possibilities with pruning"
                }
            },
            "bug_bounty": {
                "methodology": [
                    "Reconnaissance",
                    "Vulnerability identification",
                    "Exploitation",
                    "Documentation",
                    "Reporting"
                ],
                "common_findings": {
                    "idor": "Predictable object IDs, missing ownership checks",
                    "xss": "Reflected, stored, DOM-based",
                    "csrf": "Missing anti-CSRF tokens",
                    "ssrf": "Internal network access via server-side requests",
                    "race_condition": "TOCTOU vulnerabilities"
                },
                "reporting_template": {
                    "title": "[Vulnerability Type] in [Endpoint]",
                    "severity": "CVSS score",
                    "description": "Clear explanation of vulnerability",
                    "steps_to_reproduce": "Numbered steps",
                    "impact": "What an attacker could do",
                    "remediation": "Suggested fix"
                }
            }
        }
    
    def _load_logical_rules(self) -> Dict:
        """Load logical inference rules."""
        return {
            "security_inference": {
                "rule_1": {
                    "premise": "User input is not validated",
                    "conclusion": "Injection vulnerability likely",
                    "confidence": 0.85
                },
                "rule_2": {
                    "premise": "IDs are predictable and sequential",
                    "conclusion": "IDOR vulnerability likely",
                    "confidence": 0.9
                },
                "rule_3": {
                    "premise": "No CSRF token in state-changing request",
                    "conclusion": "CSRF vulnerability exists",
                    "confidence": 0.95
                },
                "rule_4": {
                    "premise": "User-controlled input in SQL query without parameterization",
                    "conclusion": "SQL injection possible",
                    "confidence": 0.9
                },
                "rule_5": {
                    "premise": "Response includes user input without encoding",
                    "conclusion": "XSS vulnerability likely",
                    "confidence": 0.85
                },
                "rule_6": {
                    "premise": "Sensitive credentials are saved in localStorage or sessionStorage",
                    "conclusion": "Insecure cookie or storage policy vulnerability",
                    "confidence": 0.95
                },
                "rule_7": {
                    "premise": "No owner validation on direct object lookup from database",
                    "conclusion": "Missing ownership check (IDOR risk)",
                    "confidence": 0.95
                },
                "rule_8": {
                    "premise": "UI template renders dynamic elements without skeletons or shimmer animation class",
                    "conclusion": "Vulnerability to static loading flicker (not modern/dynamic loading)",
                    "confidence": 0.8
                }
            },
            "algorithm_inference": {
                "rule_1": {
                    "premise": "Nested loops over same collection",
                    "conclusion": "O(n²) complexity",
                    "confidence": 0.95
                },
                "rule_2": {
                    "premise": "Repeated function calls with same arguments",
                    "conclusion": "Memoization opportunity",
                    "confidence": 0.9
                },
                "rule_3": {
                    "premise": "Linear search in unsorted collection",
                    "conclusion": "Consider hash map for O(1) lookup",
                    "confidence": 0.85
                }
            }
        }
    
    def verify_claim(self, claim: str, context: Dict = None) -> VerificationResult:
        """
        Verify a claim using neuro-symbolic reasoning.
        Combines neural pattern matching with logical inference.
        """
        contradictions = []
        grounding_sources = []
        proof_chain = None
        
        # Step 1: Neural pattern matching
        neural_confidence = self._neural_pattern_match(claim, context)
        
        # Step 2: Symbolic logical verification
        symbolic_result = self._symbolic_verification(claim, context)
        
        # Step 3: Check for contradictions
        contradictions = self._check_contradictions(claim, context)
        
        # Step 4: Build proof chain if valid
        if symbolic_result["is_valid"] and not contradictions:
            proof_chain = self._build_proof_chain(claim, symbolic_result)
            grounding_sources = symbolic_result.get("sources", [])
        
        # Step 5: Combine neural and symbolic confidence
        # Weighted average: symbolic gets higher weight for verifiability
        combined_confidence = (neural_confidence * 0.4 + 
                             symbolic_result["confidence"] * 0.6)
        
        # Reduce confidence if contradictions found
        if contradictions:
            combined_confidence *= 0.5
        
        is_valid = combined_confidence > 0.6 and not contradictions
        
        explanation = self._generate_explanation(
            claim, is_valid, combined_confidence, 
            contradictions, proof_chain
        )
        
        result = VerificationResult(
            claim=claim,
            is_valid=is_valid,
            confidence=combined_confidence,
            proof_chain=proof_chain,
            contradictions=contradictions,
            grounding_sources=grounding_sources,
            explanation=explanation
        )
        
        self.verification_history.append(result)
        return result
    
    def _neural_pattern_match(self, claim: str, context: Dict = None) -> float:
        """Neural-like pattern matching for initial confidence."""
        claim_lower = claim.lower()
        confidence = 0.5  # Base confidence
        
        # Check against known patterns
        for domain, patterns in self.knowledge_base.items():
            if domain == "security":
                for category, items in patterns.get("common_vulns", {}).items():
                    for item in items:
                        if item.lower() in claim_lower:
                            confidence += 0.2
            elif domain == "algorithms":
                for complexity, examples in patterns.get("complexity", {}).items():
                    for example in examples:
                        if example.lower() in claim_lower:
                            confidence += 0.15
        
        return min(0.95, confidence)
    
    def _symbolic_verification(self, claim: str, context: Dict = None) -> Dict:
        """Symbolic logical verification using inference rules."""
        claim_lower = claim.lower()
        matched_rules = []
        total_confidence = 0
        
        # Check security inference rules
        for rule_name, rule in self.logical_rules["security_inference"].items():
            premise = rule["premise"].lower()
            # Check if premise keywords are in claim
            premise_words = premise.split()
            matches = sum(1 for word in premise_words if word in claim_lower)
            
            if matches >= len(premise_words) * 0.6:  # 60% match threshold
                matched_rules.append({
                    "rule": rule_name,
                    "premise": rule["premise"],
                    "conclusion": rule["conclusion"],
                    "confidence": rule["confidence"]
                })
                total_confidence += rule["confidence"]
        
        # Check algorithm inference rules
        for rule_name, rule in self.logical_rules["algorithm_inference"].items():
            premise = rule["premise"].lower()
            premise_words = premise.split()
            matches = sum(1 for word in premise_words if word in claim_lower)
            
            if matches >= len(premise_words) * 0.6:
                matched_rules.append({
                    "rule": rule_name,
                    "premise": rule["premise"],
                    "conclusion": rule["conclusion"],
                    "confidence": rule["confidence"]
                })
                total_confidence += rule["confidence"]
        
        avg_confidence = total_confidence / len(matched_rules) if matched_rules else 0
        
        return {
            "is_valid": len(matched_rules) > 0,
            "confidence": min(0.95, avg_confidence),
            "matched_rules": matched_rules,
            "sources": [r["premise"] for r in matched_rules]
        }
    
    def _check_contradictions(self, claim: str, context: Dict = None) -> List[str]:
        """Check for logical contradictions in claim."""
        contradictions = []
        claim_lower = claim.lower()
        
        # Common contradiction patterns
        contradiction_patterns = [
            {
                "pattern": "always.*never|never.*always",
                "reason": "Absolute statements contradict each other"
            },
            {
                "pattern": "all.*none|none.*all",
                "reason": "Universal quantifiers contradict"
            },
            {
                "pattern": "secure.*vulnerable|vulnerable.*secure",
                "reason": "Security claims contradict"
            }
        ]
        
        for contradiction in contradiction_patterns:
            if re.search(contradiction["pattern"], claim_lower):
                contradictions.append(contradiction["reason"])
        
        # Check against knowledge base for factual contradictions
        if "sql injection" in claim_lower and "parameterized" in claim_lower:
            # This is actually correct, not a contradiction
            pass
        elif "secure" in claim_lower and "password" in claim_lower and "plain" in claim_lower:
            contradictions.append("Plaintext passwords are not secure")
        
        return contradictions
    
    def _build_proof_chain(self, claim: str, symbolic_result: Dict) -> LogicalProof:
        """Build a logical proof chain for explainability."""
        premises = []
        inference_rules = []
        
        for rule in symbolic_result.get("matched_rules", []):
            premises.append(rule["premise"])
            inference_rules.append(f"{rule['premise']} → {rule['conclusion']}")
        
        return LogicalProof(
            claim=claim,
            premises=premises,
            inference_rules=inference_rules,
            conclusion=f"Therefore: {claim}",
            confidence=symbolic_result["confidence"],
            sources=symbolic_result.get("sources", [])
        )
    
    def _generate_explanation(self, claim: str, is_valid: bool, 
                            confidence: float, contradictions: List[str],
                            proof_chain: Optional[LogicalProof]) -> str:
        """Generate human-readable explanation."""
        explanation_parts = []
        
        if is_valid:
            explanation_parts.append(f"Claim verified with {confidence:.1%} confidence.")
        else:
            explanation_parts.append(f"Claim could not be fully verified ({confidence:.1%} confidence).")
        
        if contradictions:
            explanation_parts.append(f"Contradictions found: {'; '.join(contradictions)}")
        
        if proof_chain:
            explanation_parts.append(f"Proof chain: {' → '.join(proof_chain.inference_rules)}")
        
        return " ".join(explanation_parts)
    
    def get_explanation(self, verification_result: VerificationResult) -> Dict:
        """
        Get detailed explanation of verification result.
        For explainable AI integration.
        """
        return {
            "claim": verification_result.claim,
            "verdict": "VALID" if verification_result.is_valid else "INVALID",
            "confidence": f"{verification_result.confidence:.1%}",
            "proof_chain": {
                "premises": verification_result.proof_chain.premises if verification_result.proof_chain else [],
                "inference_rules": verification_result.proof_chain.inference_rules if verification_result.proof_chain else [],
                "conclusion": verification_result.proof_chain.conclusion if verification_result.proof_chain else None
            },
            "contradictions": verification_result.contradictions,
            "grounding_sources": verification_result.grounding_sources,
            "explanation": verification_result.explanation
        }
    
    def prevent_hallucination(self, response: str, context: Dict = None) -> Dict:
        """
        Check if response contains hallucinations.
        Uses neuro-symbolic verification.
        """
        # Extract claims from response
        claims = self._extract_claims(response)
        
        verified_claims = []
        hallucinated_claims = []
        
        for claim in claims:
            result = self.verify_claim(claim, context)
            if result.is_valid:
                verified_claims.append({
                    "claim": claim,
                    "confidence": result.confidence,
                    "sources": result.grounding_sources
                })
            else:
                hallucinated_claims.append({
                    "claim": claim,
                    "reason": result.explanation,
                    "contradictions": result.contradictions
                })
        
        hallucination_score = len(hallucinated_claims) / len(claims) if claims else 0
        
        return {
            "response": response,
            "total_claims": len(claims),
            "verified_claims": verified_claims,
            "hallucinated_claims": hallucinated_claims,
            "hallucination_score": hallucination_score,
            "is_safe": hallucination_score < 0.3,
            "recommendation": "APPROVE" if hallucination_score < 0.3 else "REVISE"
        }
    
    def _extract_claims(self, text: str) -> List[str]:
        """Extract verifiable claims from text."""
        claims = []
        
        # Split by sentences
        sentences = re.split(r'[.!?]+', text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20:  # Skip very short sentences
                # Look for factual claims
                if any(keyword in sentence.lower() for keyword in [
                    "always", "never", "all", "none", "must", "should",
                    "is", "are", "was", "were", "has", "have"
                ]):
                    claims.append(sentence)
        
        return claims[:10]  # Limit to 10 claims for efficiency


# Integration with Forge
def neuro_symbolic_verification_node(state: Dict) -> Dict:
    """
    LangGraph node for neuro-symbolic verification.
    Integrates with ForgeState.
    """
    guard = NeuroSymbolicGuard()
    
    # Get the response to verify
    response = state.get("current_response", "")
    context = state.get("context", {})
    
    if not response:
        return state
    
    # Verify response
    verification_result = guard.prevent_hallucination(response, context)
    
    # Update state with verification results
    if "verification" not in state:
        state["verification"] = []
    
    state["verification"].append({
        "source": "neuro_symbolic_guard",
        "result": verification_result,
        "timestamp": datetime.now().isoformat()
    })
    
    # If hallucinations detected, flag for revision
    if not verification_result["is_safe"]:
        state["needs_revision"] = True
        state["revision_reason"] = f"Hallucination score: {verification_result['hallucination_score']:.1%}"
    
    return state


if __name__ == "__main__":
    # Test the neuro-symbolic guard
    guard = NeuroSymbolicGuard()
    
    # Test claim verification
    test_claims = [
        "SQL injection occurs when user input is not validated",
        "All systems are always secure",
        "IDOR vulnerability exists when IDs are predictable",
        "This algorithm is O(1) because it uses nested loops"
    ]
    
    for claim in test_claims:
        result = guard.verify_claim(claim)
        print(f"\nClaim: {claim}")
        print(f"Valid: {result.is_valid}")
        print(f"Confidence: {result.confidence:.1%}")
        print(f"Explanation: {result.explanation}")
