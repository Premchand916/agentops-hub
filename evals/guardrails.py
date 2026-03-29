"""
AgentOps Hub — Guardrails
===========================

WHAT GUARDRAILS ARE:
Safety checks that run BEFORE the LLM sees the input (input guardrails)
and AFTER the LLM generates output (output guardrails).

REAL-WORLD ANALOGY:
In a hospital, before a doctor prescribes medication:
  - INPUT CHECK: "Is the patient allergic to anything?" (PII = allergy check)
  - OUTPUT CHECK: "Is this dosage safe?" (hallucination = wrong dosage)
  - SCOPE CHECK: "Is this even a medical question?" (topic = wrong department)

WHY GUARDRAILS MATTER IN 2026:
Gartner predicts "death by AI" legal claims will exceed 2,000 by end of 2026.
The #1 cause: AI systems giving wrong, unsafe, or privacy-violating answers
without any quality checks. Guardrails are your legal and ethical safety net.

INTERVIEW TIP:
Q: "How do you prevent your AI system from leaking PII?"
A: "I have input guardrails that scan for PII patterns (SSN, credit cards,
   emails, phone numbers) BEFORE the query reaches the LLM. If PII is detected,
   the system either redacts it or warns the user. This runs as regex + pattern
   matching — no LLM call needed, so it's fast and deterministic."

Q: "How do you prevent hallucinations?"
A: "Three layers: (1) RAG grounding — answers must cite retrieved documents,
   (2) output guardrails check for claims not present in the context,
   (3) confidence scoring — if the reranker scores are all below threshold,
   the system says 'I don't know' instead of guessing."
"""

import re
from dataclasses import dataclass, field
from rich import print as rprint


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    guardrail_name: str
    message: str = ""
    findings: list[str] = field(default_factory=list)
    redacted_text: str = ""  # Input with PII redacted (if applicable)


# ============================================================
# INPUT GUARDRAILS — Run BEFORE the LLM sees the query
# ============================================================

class PIIDetector:
    """
    Detects Personally Identifiable Information in user input.
    
    WHAT COUNTS AS PII:
    - Social Security Numbers (SSN): 123-45-6789
    - Credit card numbers: 4111-1111-1111-1111
    - Email addresses: user@example.com
    - Phone numbers: (555) 123-4567
    - IP addresses: 192.168.1.1
    
    WHY REGEX (not an ML model):
    PII patterns are well-defined and finite. Regex catches them
    deterministically, instantly, with zero false negatives on
    standard formats. An ML model would be overkill and slower.
    
    In production, you'd add tools like Microsoft Presidio or
    AWS Comprehend for more sophisticated PII detection.
    """
    
    # Pattern name → (regex, replacement placeholder)
    PII_PATTERNS: dict[str, tuple[str, str]] = {
        "SSN": (
            r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b',
            "[SSN_REDACTED]"
        ),
        "credit_card": (
            r'\b(?:\d{4}[-.\s]?){3}\d{4}\b',
            "[CC_REDACTED]"
        ),
        "email": (
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "[EMAIL_REDACTED]"
        ),
        "phone": (
            r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
            "[PHONE_REDACTED]"
        ),
        "ip_address": (
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            "[IP_REDACTED]"
        ),
    }
    
    def check(self, text: str) -> GuardrailResult:
        """
        Scan text for PII patterns.
        
        Returns:
            GuardrailResult with:
            - passed=True if no PII found
            - passed=False if PII detected (with findings list)
            - redacted_text with PII replaced by placeholders
        """
        findings = []
        redacted = text
        
        for pii_type, (pattern, replacement) in self.PII_PATTERNS.items():
            matches = re.findall(pattern, text)
            if matches:
                findings.append(f"{pii_type}: {len(matches)} instance(s) found")
                redacted = re.sub(pattern, replacement, redacted)
        
        if findings:
            return GuardrailResult(
                passed=False,
                guardrail_name="PII_DETECTION",
                message=f"⚠️ PII detected in input: {', '.join(findings)}",
                findings=findings,
                redacted_text=redacted,
            )
        
        return GuardrailResult(
            passed=True,
            guardrail_name="PII_DETECTION",
            message="No PII detected",
            redacted_text=text,
        )


class TopicScopeGuard:
    """
    Ensures queries are within the system's domain.
    
    Our system handles: IT support, company policies, workflows.
    It should NOT try to answer: stock prices, weather, recipes, etc.
    
    WHY THIS MATTERS:
    Without scope guarding, an LLM will try to answer ANYTHING.
    Ask it about cooking recipes and it'll happily hallucinate one.
    A scoped system says "That's outside my expertise" — which is
    what a professional would do.
    """
    
    # Keywords that indicate out-of-scope topics
    OUT_OF_SCOPE_PATTERNS = [
        r'\b(?:stock|stocks|share price|market cap|trading|invest)\b',
        r'\b(?:weather|forecast|temperature|rain)\b',
        r'\b(?:recipe|cook|bake|ingredients)\b',
        r'\b(?:sports|score|game|match|team)\b',
        r'\b(?:movie|film|tv show|series|actor|actress)\b',
        r'\b(?:write me a (?:poem|story|song|essay))\b',
        r'\b(?:tell me a joke|funny)\b',
    ]
    
    def check(self, text: str) -> GuardrailResult:
        """Check if the query is within scope."""
        text_lower = text.lower()
        
        # Empty input check
        if not text.strip():
            return GuardrailResult(
                passed=False,
                guardrail_name="TOPIC_SCOPE",
                message="Empty input received",
                findings=["empty_input"],
            )
        
        for pattern in self.OUT_OF_SCOPE_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                return GuardrailResult(
                    passed=False,
                    guardrail_name="TOPIC_SCOPE",
                    message=(
                        "This question appears to be outside my area of expertise. "
                        "I can help with IT support, company policies, and workflow tasks."
                    ),
                    findings=[f"out_of_scope: matched '{match.group()}'"],
                )
        
        return GuardrailResult(
            passed=True,
            guardrail_name="TOPIC_SCOPE",
            message="Query is within scope",
        )


# ============================================================
# OUTPUT GUARDRAILS — Run AFTER the LLM generates a response
# ============================================================

class HallucinationDetector:
    """
    Checks if the LLM's answer is grounded in the retrieved context.
    
    HOW IT WORKS (simple but effective):
    1. Look at the source relevance scores from reranking
    2. If ALL scores are below threshold → the system has no good context
    3. If no good context → the answer is likely hallucinated
    
    This is a "retrieval confidence" check, not a full hallucination
    detector. A production system would use an LLM-as-judge to compare
    the answer against the context. But this catches the worst cases.
    
    INTERVIEW TIP:
    Q: "How do you detect hallucinations in RAG?"
    A: "Multiple layers: (1) Retrieval confidence — if reranker scores
       are all below 0.3, I know the knowledge base doesn't have the answer
       and the LLM is likely making things up. (2) For critical use cases,
       I use LLM-as-judge where a separate model evaluates whether the
       answer is supported by the retrieved context. (3) I track
       hallucination rates as a metric over time."
    """
    
    def __init__(self, min_source_score: float = 0.3):
        """
        Args:
            min_source_score: Minimum rerank score to consider a source relevant.
                              Below this, we consider the answer ungrounded.
        """
        self.min_source_score = min_source_score
    
    def check(self, answer: str, sources: list[dict]) -> GuardrailResult:
        """
        Check if the answer is grounded in retrieved sources.
        
        Args:
            answer: The LLM's generated answer
            sources: List of source dicts with 'rerank_score' from RAG
        """
        if not sources:
            return GuardrailResult(
                passed=False,
                guardrail_name="HALLUCINATION_CHECK",
                message="No sources retrieved — answer may not be grounded",
                findings=["no_sources"],
            )
        
        # Check if any source has a meaningful relevance score
        relevant_sources = [
            s for s in sources
            if s.get("rerank_score", 0) >= self.min_source_score
        ]
        
        if not relevant_sources:
            max_score = max(s.get("rerank_score", 0) for s in sources)
            return GuardrailResult(
                passed=False,
                guardrail_name="HALLUCINATION_CHECK",
                message=(
                    f"Low retrieval confidence (best score: {max_score:.3f}). "
                    f"Answer may not be well-grounded in documents."
                ),
                findings=[f"max_rerank_score={max_score:.3f}"],
            )
        
        best_score = max(s.get("rerank_score", 0) for s in relevant_sources)
        return GuardrailResult(
            passed=True,
            guardrail_name="HALLUCINATION_CHECK",
            message=f"Answer grounded in {len(relevant_sources)} source(s) "
                    f"(best score: {best_score:.3f})",
        )


class ConfidenceGate:
    """
    Blocks low-confidence routing decisions.
    
    If the orchestrator isn't sure which agent to use,
    the response quality will suffer. Better to ask for
    clarification than to guess wrong.
    """
    
    def __init__(self, min_confidence: float = 0.7):
        self.min_confidence = min_confidence
    
    def check(self, confidence: float, agent: str) -> GuardrailResult:
        """Check if routing confidence meets threshold."""
        if confidence < self.min_confidence:
            return GuardrailResult(
                passed=False,
                guardrail_name="CONFIDENCE_GATE",
                message=(
                    f"Routing confidence ({confidence:.0%}) below threshold "
                    f"({self.min_confidence:.0%}) for agent {agent}"
                ),
                findings=[f"confidence={confidence:.3f}", f"agent={agent}"],
            )
        
        return GuardrailResult(
            passed=True,
            guardrail_name="CONFIDENCE_GATE",
            message=f"Routing confidence {confidence:.0%} OK for {agent}",
        )


# ============================================================
# GUARDRAIL PIPELINE — Runs all checks in order
# ============================================================

class GuardrailPipeline:
    """
    Runs all guardrail checks in sequence.
    
    USAGE:
        pipeline = GuardrailPipeline()
        
        # Before LLM call:
        input_results = pipeline.check_input("user message")
        if not input_results["passed"]:
            return input_results["message"]  # Don't call the LLM
        
        # After LLM call:
        output_results = pipeline.check_output(answer, sources, confidence)
    """
    
    def __init__(self):
        self.pii_detector = PIIDetector()
        self.topic_guard = TopicScopeGuard()
        self.hallucination_detector = HallucinationDetector()
        self.confidence_gate = ConfidenceGate()
    
    def check_input(self, text: str) -> dict:
        """
        Run all input guardrails.
        
        Returns:
            {
                "passed": bool,
                "message": str (user-facing message if blocked),
                "redacted_text": str (input with PII replaced),
                "results": [GuardrailResult, ...]
            }
        """
        results = []
        
        # Check 1: PII detection
        pii_result = self.pii_detector.check(text)
        results.append(pii_result)
        
        if not pii_result.passed:
            rprint(f"[yellow]🛡️ Guardrail: {pii_result.message}[/yellow]")
            # Don't block — just redact and warn
            text = pii_result.redacted_text
        
        # Check 2: Topic scope
        scope_result = self.topic_guard.check(text)
        results.append(scope_result)
        
        if not scope_result.passed:
            rprint(f"[yellow]🛡️ Guardrail: {scope_result.message}[/yellow]")
            if "empty_input" in scope_result.findings:
                return {
                    "passed": False,
                    "message": "Please enter a question or request.",
                    "redacted_text": text,
                    "results": results,
                }
            # For out-of-scope, let it through but flag it
            # The triage agent will handle it gracefully
        
        return {
            "passed": True,
            "message": "",
            "redacted_text": text,
            "results": results,
            "pii_detected": not pii_result.passed,
        }
    
    def check_output(
        self,
        answer: str,
        sources: list[dict],
        confidence: float = 1.0,
        agent: str = "",
    ) -> dict:
        """
        Run all output guardrails.
        
        Returns:
            {
                "passed": bool,
                "warnings": [str, ...],
                "results": [GuardrailResult, ...]
            }
        """
        results = []
        warnings = []
        
        # Check 1: Hallucination (only for RAG-based agents)
        if agent in ("IT_HELP", "KNOWLEDGE"):
            hall_result = self.hallucination_detector.check(answer, sources)
            results.append(hall_result)
            if not hall_result.passed:
                warnings.append(f"⚠️ {hall_result.message}")
        
        # Check 2: Confidence gate
        conf_result = self.confidence_gate.check(confidence, agent)
        results.append(conf_result)
        if not conf_result.passed:
            warnings.append(f"⚠️ {conf_result.message}")
        
        return {
            "passed": len(warnings) == 0,
            "warnings": warnings,
            "results": results,
        }


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    rprint("\n[bold]🛡️ Testing Guardrails[/bold]\n")
    
    pipeline = GuardrailPipeline()
    
    # Test PII detection
    test_inputs = [
        "My SSN is 123-45-6789 and I need help",
        "Card number 4111-1111-1111-1111",
        "How do I reset my VPN?",
        "Contact me at john@company.com",
        "",
        "What's the stock price of Apple?",
    ]
    
    for text in test_inputs:
        result = pipeline.check_input(text)
        status = "✅ PASS" if result["passed"] else "❌ BLOCKED"
        pii = " [PII!]" if result.get("pii_detected") else ""
        rprint(f"  {status}{pii}: \"{text[:50]}...\"")
        if result.get("pii_detected"):
            rprint(f"    Redacted: {result['redacted_text'][:50]}...")
    
    rprint("\n[bold]Output guardrail tests:[/bold]")
    
    # Test hallucination detection
    good_sources = [{"rerank_score": 0.95, "file": "runbook.md"}]
    bad_sources = [{"rerank_score": 0.1, "file": "runbook.md"}]
    
    result1 = pipeline.check_output("Good answer", good_sources, 0.95, "IT_HELP")
    result2 = pipeline.check_output("Bad answer", bad_sources, 0.3, "IT_HELP")
    
    rprint(f"  High confidence + good sources: {'✅ PASS' if result1['passed'] else '⚠️ WARN'}")
    rprint(f"  Low confidence + bad sources: {'✅ PASS' if result2['passed'] else '⚠️ WARN'}")
    if result2["warnings"]:
        for w in result2["warnings"]:
            rprint(f"    {w}")