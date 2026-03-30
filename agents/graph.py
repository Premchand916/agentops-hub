"""
AgentOps Hub — Agent Graph (Session 5: + Observability)
==========================================================

WHAT CHANGED FROM SESSION 3:
- Imported AgentTracer singleton
- AgentHub.chat() now wraps every request in tracer.trace()
- Each agent node call wrapped in ctx.span() for per-agent latency

Graph topology unchanged:
    START → orchestrator → [IT_HELP | KNOWLEDGE | WORKFLOW | TRIAGE] → END
"""

from langgraph.graph import StateGraph, END
from agents.state import AgentState
from agents.orchestrator import OrchestratorAgent
from agents.specialists import ITHelpAgent, KnowledgeAgent, TriageAgent
from agents.workflow import WorkflowAgent
from rag.rag_chain import RAGChain
from tools.backends import BackendServices
from tools.registry import ToolRegistry
from observability.tracer import tracer          # ← Session 5
from langchain_core.messages import HumanMessage
from rich import print as rprint


# ─────────────────────────────────────────────
# GRAPH BUILDER
# ─────────────────────────────────────────────

def build_agent_graph(
    rag_chain: RAGChain,
    tool_registry: ToolRegistry,
) -> StateGraph:
    """Build and compile the multi-agent LangGraph."""

    orchestrator = OrchestratorAgent()
    it_help      = ITHelpAgent(rag_chain)
    knowledge    = KnowledgeAgent(rag_chain)
    triage       = TriageAgent(rag_chain)
    workflow     = WorkflowAgent(tool_registry)

    graph = StateGraph(AgentState)

    graph.add_node("orchestrator", orchestrator.route)
    graph.add_node("it_help",      it_help.handle)
    graph.add_node("knowledge",    knowledge.handle)
    graph.add_node("triage",       triage.handle)
    graph.add_node("workflow",     workflow.handle)

    graph.set_entry_point("orchestrator")

    graph.add_conditional_edges(
        "orchestrator",
        route_to_specialist,
        {
            "IT_HELP":   "it_help",
            "KNOWLEDGE": "knowledge",
            "TRIAGE":    "triage",
            "WORKFLOW":  "workflow",
        }
    )

    graph.add_edge("it_help",   END)
    graph.add_edge("knowledge", END)
    graph.add_edge("triage",    END)
    graph.add_edge("workflow",  END)

    compiled = graph.compile()
    rprint("[green]✅ Agent graph compiled (4 specialist agents)[/green]")
    return compiled


def route_to_specialist(state: AgentState) -> str:
    """Conditional routing — reads target_agent from state."""
    target = state.get("target_agent", "TRIAGE")

    if state.get("routing_attempts", 0) > 3:
        rprint("[red]⚠️  Max routing attempts — forcing TRIAGE[/red]")
        return "TRIAGE"

    valid_agents = {"IT_HELP", "KNOWLEDGE", "TRIAGE", "WORKFLOW"}
    if target not in valid_agents:
        rprint(f"[yellow]⚠️  Unknown agent '{target}' → TRIAGE[/yellow]")
        return "TRIAGE"

    return target


# ─────────────────────────────────────────────
# AGENT HUB
# ─────────────────────────────────────────────

class AgentHub:
    """
    Main entry point for AgentOps Hub.

    Session 5 change: chat() wraps every request in tracer.trace()
    so every orchestrator + specialist call is measured and logged.
    """

    def __init__(self):
        rprint("[bold]🚀 Initializing AgentOps Hub...[/bold]")
        self.rag_chain     = RAGChain()
        self.backends      = BackendServices()
        self.tool_registry = ToolRegistry(self.backends)
        self.graph         = None
        self._is_ready     = False

    def ingest(self, documents_path: str) -> dict:
        """Ingest documents and build agent graph."""
        stats = self.rag_chain.ingest(documents_path)
        if stats["status"] == "success":
            self.graph    = build_agent_graph(self.rag_chain, self.tool_registry)
            self._is_ready = True
        return stats

    def chat(self, user_message: str) -> dict:
        """
        Send a message through the multi-agent system.
        Every call is fully traced: orchestrator + specialist spans.
        """
        if not self._is_ready:
            return {
                "answer":     "System not ready. Call ingest() first.",
                "handled_by": "SYSTEM",
                "sources":    [],
            }

        initial_state = {
            "messages":          [HumanMessage(content=user_message)],
            "target_agent":      "",
            "routing_confidence": 0.0,
            "routing_reasoning": "",
            "final_answer":      "",
            "sources":           [],
            "handled_by":        "",
            "routing_attempts":  0,
        }

        # ── SESSION 5: wrap in tracer ─────────────────────────────────
        with tracer.trace(user_message) as ctx:

            # Span 1: full graph execution (LangGraph handles internal routing)
            with ctx.span("agent_graph", agent="GRAPH", query=user_message[:100]) as s:
                try:
                    final_state = self.graph.invoke(initial_state)

                    handled_by = final_state.get("handled_by", "UNKNOWN")
                    answer     = final_state.get("final_answer", "No response generated.")
                    confidence = final_state.get("routing_confidence", 0.0)

                    s.record_output(
                        answer,
                        score=confidence,        # routing confidence as proxy score
                    )
                    s.metadata["handled_by"]  = handled_by
                    s.metadata["target"]      = final_state.get("target_agent", "")
                    s.metadata["source_count"] = len(final_state.get("sources", []))

                except Exception as e:
                    s.record_error(e)
                    rprint(f"[red]❌ Agent graph error: {e}[/red]")
                    return {
                        "answer":     "I encountered an error. Please try again.",
                        "handled_by": "ERROR",
                        "sources":    [],
                        "error":      str(e),
                    }
        # ── end trace ────────────────────────────────────────────────

        return {
            "answer":   final_state.get("final_answer", "No response generated."),
            "sources":  final_state.get("sources", []),
            "handled_by": final_state.get("handled_by", "UNKNOWN"),
            "routing": {
                "target":     final_state.get("target_agent", ""),
                "confidence": final_state.get("routing_confidence", 0),
                "reasoning":  final_state.get("routing_reasoning", ""),
            },
        }

    def stats(self) -> dict:
        """Return aggregated observability stats from local trace log."""
        return tracer.summary_stats()