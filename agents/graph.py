"""
AgentOps Hub  Agent Graph (Updated with Workflow Agent)
==========================================================

WHAT CHANGED FROM SESSION 2:
- Added WORKFLOW agent node
- Added BackendServices + ToolRegistry initialization
- Updated conditional routing to include WORKFLOW
- AgentHub now creates tool infrastructure on init

The graph now looks like:

    START
      
      
  orchestrator   classifies intent
      
       "IT_HELP"     it_help_agent
       "KNOWLEDGE"   knowledge_agent
       "WORKFLOW"    workflow_agent   NEW
       "TRIAGE"      triage_agent
      
      
     END
"""

from langgraph.graph import StateGraph, END
from agents.state import AgentState
from agents.orchestrator import OrchestratorAgent
from agents.specialists import ITHelpAgent, KnowledgeAgent, TriageAgent
from agents.workflow import WorkflowAgent
from rag.rag_chain import RAGChain
from tools.backends import BackendServices
from tools.registry import ToolRegistry
from langchain_core.messages import HumanMessage
from rich import print as rprint


def build_agent_graph(
    rag_chain: RAGChain,
    tool_registry: ToolRegistry,
) -> StateGraph:
    """
    Build the complete multi-agent graph with tool support.
    
    Args:
        rag_chain: Initialized RAGChain (documents ingested)
        tool_registry: Initialized ToolRegistry (tools registered)
        
    Returns:
        A compiled LangGraph
    """
    # Initialize agents
    orchestrator = OrchestratorAgent()
    it_help = ITHelpAgent(rag_chain)
    knowledge = KnowledgeAgent(rag_chain)
    triage = TriageAgent(rag_chain)
    workflow = WorkflowAgent(tool_registry)  # NEW  uses tools, not RAG
    
    # Create graph
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("orchestrator", orchestrator.route)
    graph.add_node("it_help", it_help.handle)
    graph.add_node("knowledge", knowledge.handle)
    graph.add_node("triage", triage.handle)
    graph.add_node("workflow", workflow.handle)  # NEW
    
    # Entry point
    graph.set_entry_point("orchestrator")
    
    # Conditional routing  now includes WORKFLOW
    graph.add_conditional_edges(
        "orchestrator",
        route_to_specialist,
        {
            "IT_HELP": "it_help",
            "KNOWLEDGE": "knowledge",
            "TRIAGE": "triage",
            "WORKFLOW": "workflow",  # NEW
        }
    )
    
    # All specialists lead to END
    graph.add_edge("it_help", END)
    graph.add_edge("knowledge", END)
    graph.add_edge("triage", END)
    graph.add_edge("workflow", END)  # NEW
    
    compiled = graph.compile()
    rprint("[green] Agent graph compiled (4 specialist agents)[/green]")
    
    return compiled


def route_to_specialist(state: AgentState) -> str:
    """Conditional routing function  reads target_agent from state."""
    target = state.get("target_agent", "TRIAGE")
    
    # Safety: prevent infinite loops
    if state.get("routing_attempts", 0) > 3:
        rprint("[red]    Max routing attempts  forcing TRIAGE[/red]")
        return "TRIAGE"
    
    valid_agents = {"IT_HELP", "KNOWLEDGE", "TRIAGE", "WORKFLOW"}
    
    if target not in valid_agents:
        rprint(f"[yellow]    Unknown agent '{target}'  TRIAGE[/yellow]")
        return "TRIAGE"
    
    return target


class AgentHub:
    """
    Main entry point for the multi-agent system.
    
    Updated to include tool infrastructure:
    - BackendServices (simulated Jira, PagerDuty, Slack)
    - ToolRegistry (tool discovery + execution)
    - WorkflowAgent (takes actions via tools)
    """
    
    def __init__(self):
        rprint("[bold] Initializing AgentOps Hub...[/bold]")
        
        # RAG for knowledge retrieval
        self.rag_chain = RAGChain()
        
        # Tool infrastructure
        self.backends = BackendServices()
        self.tool_registry = ToolRegistry(self.backends)
        
        self.graph = None
        self._is_ready = False
    
    def ingest(self, documents_path: str) -> dict:
        """Ingest documents and build the agent graph."""
        stats = self.rag_chain.ingest(documents_path)
        
        if stats["status"] == "success":
            self.graph = build_agent_graph(self.rag_chain, self.tool_registry)
            self._is_ready = True
        
        return stats
    
    def chat(self, user_message: str) -> dict:
        """
        Send a message through the multi-agent system.
        
        Returns dict with answer, sources, handled_by, routing info.
        """
        if not self._is_ready:
            return {
                "answer": "System not ready. Call ingest() first.",
                "handled_by": "SYSTEM",
                "sources": [],
            }
        
        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "target_agent": "",
            "routing_confidence": 0.0,
            "routing_reasoning": "",
            "final_answer": "",
            "sources": [],
            "handled_by": "",
            "routing_attempts": 0,
        }
        
        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as e:
            rprint(f"[red] Agent graph error: {e}[/red]")
            return {
                "answer": "I encountered an error processing your request. Please try again.",
                "handled_by": "ERROR",
                "sources": [],
                "error": str(e),
            }
        
        return {
            "answer": final_state.get("final_answer", "No response generated."),
            "sources": final_state.get("sources", []),
            "handled_by": final_state.get("handled_by", "UNKNOWN"),
            "routing": {
                "target": final_state.get("target_agent", ""),
                "confidence": final_state.get("routing_confidence", 0),
                "reasoning": final_state.get("routing_reasoning", ""),
            },
        }
