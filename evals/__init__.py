"""
AgentOps Hub — Evaluation & Guardrails Package

Usage:
    # Run guardrails
    from evals.guardrails import GuardrailPipeline
    pipeline = GuardrailPipeline()
    result = pipeline.check_input("user message")
    
    # Run eval suite
    python evals/run_evals.py
"""

from evals.guardrails import (
    GuardrailPipeline,
    PIIDetector,
    TopicScopeGuard,
    HallucinationDetector,
    ConfidenceGate,
    GuardrailResult,
)

__all__ = [
    "GuardrailPipeline",
    "PIIDetector",
    "TopicScopeGuard",
    "HallucinationDetector",
    "ConfidenceGate",
    "GuardrailResult",
]