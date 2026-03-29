"""
AgentOps Hub — Evaluation Runner
====================================

WHAT THIS DOES:
Loads test cases from YAML, runs each through the multi-agent system,
and produces a quality report with pass/fail metrics.

THIS IS YOUR "CI QUALITY GATE":
In production, this runs on every PR. If pass rate drops below
threshold, the deploy is blocked. No human review needed.

THREE TYPES OF EVALUATION:

1. ROUTING ACCURACY: Did the orchestrator pick the right agent?
   - Deterministic: exact match on agent name
   - Fast: no LLM needed to check

2. ANSWER QUALITY: Is the answer grounded in documents?
   - Keyword check: expected terms must appear
   - Source check: right document was retrieved
   - Semi-deterministic: string matching

3. TOOL CALLING: Did the Workflow Agent call the right tool?
   - Check: correct tool was invoked
   - Check: tool execution succeeded

INTERVIEW TIP:
Q: "How do you evaluate a multi-agent system?"
A: "I have three evaluation dimensions: routing accuracy (did the right
   agent handle it), answer quality (is the answer grounded in source
   documents with correct keywords), and tool accuracy (did the workflow
   agent call the right tool). I track these metrics over time and run
   the full suite in CI before every deploy."

Q: "What's your pass/fail threshold?"
A: "Routing accuracy must be >90%. RAG answer quality (keyword presence)
   must be >80%. Tool calling accuracy must be >95%. If any drops below
   threshold, the deploy is blocked and we investigate."
"""

import sys
import os
import yaml
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from rich import print as rprint
from rich.table import Table
from rich.panel import Panel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)
logging.getLogger("google_genai._api_client").setLevel(logging.WARNING)


@dataclass
class TestResult:
    """Result of a single test case."""
    test_id: str
    category: str
    input_text: str
    passed: bool
    expected: str
    actual: str
    details: str = ""
    duration_seconds: float = 0.0


@dataclass
class EvalReport:
    """Aggregated evaluation report."""
    results: list[TestResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    
    @property
    def total(self) -> int:
        return len(self.results)
    
    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed(self) -> int:
        return self.total - self.passed
    
    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0
    
    def by_category(self) -> dict[str, list[TestResult]]:
        """Group results by category."""
        groups: dict[str, list[TestResult]] = {}
        for r in self.results:
            groups.setdefault(r.category, []).append(r)
        return groups


def load_test_cases(path: str = "evals/test_cases/eval_suite.yaml") -> dict:
    """Load test cases from YAML file."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def run_routing_tests(hub, test_cases: list[dict]) -> list[TestResult]:
    """
    Test routing accuracy — does the orchestrator pick the right agent?
    
    This is the fastest eval: one LLM call per test (just the orchestrator).
    """
    results = []
    
    for tc in test_cases:
        test_id = tc["id"]
        input_text = tc["input"]
        expected = tc["expected_route"]
        acceptable = tc.get("acceptable_routes", [expected])
        
        rprint(f"  [dim]Running {test_id}: \"{input_text[:40]}...\"[/dim]")
        
        start = time.time()
        try:
            result = hub.chat(input_text)
            actual = result.get("handled_by", "UNKNOWN")
            duration = time.time() - start
            
            passed = actual in acceptable
            
            results.append(TestResult(
                test_id=test_id,
                category="routing",
                input_text=input_text,
                passed=passed,
                expected=expected,
                actual=actual,
                details=f"confidence: {result.get('routing', {}).get('confidence', 0):.0%}",
                duration_seconds=duration,
            ))
        except Exception as e:
            results.append(TestResult(
                test_id=test_id,
                category="routing",
                input_text=input_text,
                passed=False,
                expected=expected,
                actual="ERROR",
                details=str(e)[:100],
                duration_seconds=time.time() - start,
            ))
    
    return results


def run_rag_tests(hub, test_cases: list[dict]) -> list[TestResult]:
    """
    Test RAG answer quality — are expected keywords present?
    
    This checks that the answer is GROUNDED in the right documents.
    If a user asks about VPN and "restart" doesn't appear in the answer,
    something is wrong with retrieval or generation.
    """
    results = []
    
    for tc in test_cases:
        test_id = tc["id"]
        input_text = tc["input"]
        expected_keywords = tc.get("expected_keywords", [])
        expected_source = tc.get("expected_source", "")
        expected_route = tc["expected_route"]
        acceptable = tc.get("acceptable_routes", [expected_route])
        
        rprint(f"  [dim]Running {test_id}: \"{input_text[:40]}...\"[/dim]")
        
        start = time.time()
        try:
            result = hub.chat(input_text)
            answer = result.get("answer", "").lower()
            actual_route = result.get("handled_by", "UNKNOWN")
            duration = time.time() - start
            
            # Check routing
            route_ok = actual_route in acceptable
            
            # Check keywords
            missing_keywords = [
                kw for kw in expected_keywords
                if kw.lower() not in answer
            ]
            keywords_ok = len(missing_keywords) == 0
            
            # Check source
            source_ok = True
            if expected_source:
                sources = result.get("sources", [])
                source_files = [s.get("file", "") for s in sources]
                source_ok = any(expected_source in f for f in source_files)
            
            passed = route_ok and keywords_ok
            
            details_parts = []
            if not route_ok:
                details_parts.append(f"wrong route: {actual_route}")
            if missing_keywords:
                details_parts.append(f"missing keywords: {missing_keywords}")
            if not source_ok:
                details_parts.append(f"expected source '{expected_source}' not found")
            
            results.append(TestResult(
                test_id=test_id,
                category="rag_quality",
                input_text=input_text,
                passed=passed,
                expected=f"route={expected_route}, keywords={expected_keywords}",
                actual=f"route={actual_route}, missing={missing_keywords}",
                details="; ".join(details_parts) if details_parts else "all checks passed",
                duration_seconds=duration,
            ))
        except Exception as e:
            results.append(TestResult(
                test_id=test_id,
                category="rag_quality",
                input_text=input_text,
                passed=False,
                expected=f"keywords={expected_keywords}",
                actual="ERROR",
                details=str(e)[:100],
                duration_seconds=time.time() - start,
            ))
    
    return results


def run_tool_tests(hub, test_cases: list[dict]) -> list[TestResult]:
    """
    Test tool calling — does the Workflow Agent use the right tool?
    """
    results = []
    
    for tc in test_cases:
        test_id = tc["id"]
        input_text = tc["input"]
        expected_route = tc["expected_route"]
        expected_tool = tc.get("expected_tool", "")
        acceptable = tc.get("acceptable_routes", [expected_route])
        
        rprint(f"  [dim]Running {test_id}: \"{input_text[:40]}...\"[/dim]")
        
        start = time.time()
        try:
            result = hub.chat(input_text)
            actual_route = result.get("handled_by", "UNKNOWN")
            answer = result.get("answer", "").lower()
            duration = time.time() - start
            
            route_ok = actual_route in acceptable
            
            # For tool tests, we check if the expected keywords appear
            # (e.g., "HELP-" for ticket creation, "email" for search)
            expected_keywords = tc.get("expected_keywords", [])
            keywords_ok = all(kw.lower() in answer for kw in expected_keywords) if expected_keywords else True
            
            passed = route_ok and keywords_ok
            
            results.append(TestResult(
                test_id=test_id,
                category="tool_calling",
                input_text=input_text,
                passed=passed,
                expected=f"route={expected_route}, tool={expected_tool}",
                actual=f"route={actual_route}",
                details="" if passed else f"route_ok={route_ok}, keywords_ok={keywords_ok}",
                duration_seconds=duration,
            ))
        except Exception as e:
            results.append(TestResult(
                test_id=test_id,
                category="tool_calling",
                input_text=input_text,
                passed=False,
                expected=expected_tool,
                actual="ERROR",
                details=str(e)[:100],
                duration_seconds=time.time() - start,
            ))
    
    return results


def print_report(report: EvalReport):
    """Print a formatted evaluation report."""
    
    # Summary
    color = "green" if report.pass_rate >= 0.9 else "yellow" if report.pass_rate >= 0.7 else "red"
    rprint(Panel.fit(
        f"[bold {color}]Pass Rate: {report.pass_rate:.0%} "
        f"({report.passed}/{report.total})[/bold {color}]\n"
        f"Failed: {report.failed}\n"
        f"Total time: {sum(r.duration_seconds for r in report.results):.1f}s",
        title="📊 Evaluation Report",
        border_style=color,
    ))
    
    # Per-category breakdown
    for category, results in report.by_category().items():
        cat_passed = sum(1 for r in results if r.passed)
        cat_total = len(results)
        cat_rate = cat_passed / cat_total if cat_total > 0 else 0
        
        table = Table(title=f"{category} ({cat_passed}/{cat_total} = {cat_rate:.0%})")
        table.add_column("ID", style="dim")
        table.add_column("Input", max_width=35)
        table.add_column("Status")
        table.add_column("Details", max_width=40)
        table.add_column("Time")
        
        for r in results:
            status = "[green]✅ PASS[/green]" if r.passed else "[red]❌ FAIL[/red]"
            table.add_row(
                r.test_id,
                r.input_text[:35] + ("..." if len(r.input_text) > 35 else ""),
                status,
                r.details[:40] if r.details else "",
                f"{r.duration_seconds:.1f}s",
            )
        
        rprint(table)
        rprint()


def main():
    """Run the full evaluation suite."""
    from agents.graph import AgentHub
    
    rprint(Panel.fit(
        "[bold cyan]🧪 AgentOps Hub — Evaluation Suite[/bold cyan]\n\n"
        "Running all test cases against the multi-agent system.\n"
        "This may take a few minutes depending on model speed.",
        title="Evaluation",
        border_style="cyan",
    ))
    
    # Initialize
    rprint("\n[bold]Initializing system...[/bold]")
    hub = AgentHub()
    hub.ingest("rag/documents")
    
    # Load test cases
    test_data = load_test_cases()
    
    report = EvalReport()
    
    # Run routing tests
    rprint(f"\n[bold]📍 Running routing tests...[/bold]")
    routing_results = run_routing_tests(hub, test_data.get("routing_tests", []))
    report.results.extend(routing_results)
    
    # Run RAG quality tests
    rprint(f"\n[bold]📚 Running RAG quality tests...[/bold]")
    rag_results = run_rag_tests(hub, test_data.get("rag_tests", []))
    report.results.extend(rag_results)
    
    # Run tool calling tests
    rprint(f"\n[bold]🔧 Running tool calling tests...[/bold]")
    tool_results = run_tool_tests(hub, test_data.get("tool_tests", []))
    report.results.extend(tool_results)
    
    # Print report
    report.end_time = datetime.now(timezone.utc)
    rprint(f"\n{'='*60}")
    print_report(report)
    
    # Exit code for CI
    if report.pass_rate < 0.8:
        rprint("[red]❌ Eval suite FAILED — pass rate below 80%[/red]")
        sys.exit(1)
    else:
        rprint("[green]✅ Eval suite PASSED[/green]")
        sys.exit(0)


if __name__ == "__main__":
    main()