"""
AgentOps Hub — Agent Graph (LangGraph Orchestration)
======================================================

WHAT THIS IS:
The "brain" of the multi-agent system. It defines:
  - NODES: Each agent is a node (orchestrator, it_help, knowledge, triage)
  - EDGES: How agents connect to each other
  - CONDITIONAL ROUTING: Logic that decides which node runs next

THIS IS THE CORE CONCEPT OF LANGGRAPH:

A graph is a set of nodes connected by edges.

    ┌──────────────┐
    │  Orchestrator │ ← Entry point
    └──────┬───────┘
           │
     ┌─────┼──────┐     (conditional edge: routes based on target_agent)
     ▼     ▼      ▼
  IT_HELP KNOW  TRIAGE
     │     │      │
     └─────┼──────┘
           ▼
         END         ← All paths lead here

HOW IT WORKS STEP BY STEP:
1. User sends a message → state is created with the message
2. Orchestrator node runs → reads message, sets target_agent
3. Conditional edge reads target_agent → routes to correct specialist
4. Specialist node runs → queries RAG, generates answer, updates state
5. Graph reaches END → return final state with answer

WHY LANGGRAPH (not just if/else in Python)?

You COULD write: if intent == "IT": it_agent.handle() elif ...
But LangGraph gives you:
  ✓ Visual graph inspection (you can literally see the flow)
  ✓ State persistence (pause/resume conversations)
  ✓ Streaming (stream tokens as agents work)
  ✓ Human-in-the-loop (pause for approval before actions)
  ✓ Retry/error handling per node
  ✓ Easy to add nodes without restructuring code

INTERVIEW TIP:
Q: "Why LangGraph instead of simple Python orchestration?"
A: "For a prototype, if/else works. But LangGraph gives me state
   persistence, streaming, human-in-the-loop hooks, and visual graph
   debugging — all things production multi-agent systems need. The graph
   structure also makes it trivial to add new agents: add a node, add a
   conditional edge, update the orchestrator prompt. Nothing else changes."

Q: "Explain your graph's routing logic."
A: "The orchestrator classifies intent and sets target_agent in the state.
   A conditional edge function reads target_agent and returns the next node
   name. If confidence is below threshold, it routes to Triage. This is a
   supervisor pattern — one coordinator with multiple workers."
"""

from langgraph.graph import StateGraph, END
from agents.state import AgentState
from agents.orchestrator import OrchestratorAgent
from agents.specialists import ITHelpAgent, KnowledgeAgent, TriageAgent
from rag.rag_chain import RAGChain
from langchain_core.messages import HumanMessage
from rich import print as rprint


def build_agent_graph(rag_chain: RAGChain) -> StateGraph:
    """
    Build the complete multi-agent graph.
    
    Args:
        rag_chain: An initialized RAGChain (already ingested documents)
        
    Returns:
        A compiled LangGraph that can process user queries
    
    ARCHITECTURE:
    
        START
          │
          ▼
      orchestrator  ← classifies intent
          │
          ├── "IT_HELP"    → it_help_agent
          ├── "KNOWLEDGE"  → knowledge_agent
          ├── "TRIAGE"     → triage_agent
          │
          ▼
         END
    """
    
    # --- Initialize agents ---
    # All specialist agents share the same RAG chain (efficient!)
    orchestrator = OrchestratorAgent()
    it_help = ITHelpAgent(rag_chain)
    knowledge = KnowledgeAgent(rag_chain)
    triage = TriageAgent(rag_chain)
    
    # --- Create the graph ---
    # StateGraph takes our state schema — it knows what fields to expect
    graph = StateGraph(AgentState)
    
    # --- Add nodes ---
    # Each node is a function that takes state → returns state updates
    # The string name is how we reference the node in edges
    graph.add_node("orchestrator", orchestrator.route)
    graph.add_node("it_help", it_help.handle)
    graph.add_node("knowledge", knowledge.handle)
    graph.add_node("triage", triage.handle)
    
    # --- Set entry point ---
    # Every query starts at the orchestrator
    graph.set_entry_point("orchestrator")
    
    # --- Add conditional routing ---
    # After the orchestrator runs, this function decides the next node
    graph.add_conditional_edges(
        "orchestrator",           # After this node...
        route_to_specialist,      # ...run this function to decide next node
        {
            # Map: function return value → node name
            "IT_HELP": "it_help",
            "KNOWLEDGE": "knowledge",
            "TRIAGE": "triage",
        }
    )
    
    # --- All specialist nodes lead to END ---
    # After any specialist finishes, the graph is done
    graph.add_edge("it_help", END)
    graph.add_edge("knowledge", END)
    graph.add_edge("triage", END)
    
    # --- Compile the graph ---
    # Compilation validates the graph (checks for dead ends, missing edges)
    # and returns a runnable object
    compiled = graph.compile()
    
    rprint("[green]✅ Agent graph compiled successfully[/green]")
    
    return compiled


def route_to_specialist(state: AgentState) -> str:
    """
    Conditional routing function.
    
    This is called AFTER the orchestrator runs.
    It reads the routing decision from state and returns
    the name of the next node.
    
    WHY A SEPARATE FUNCTION (not inside the orchestrator)?
    Because LangGraph's add_conditional_edges expects a pure function
    that takes state and returns a string. Keeping it separate also
    makes it easy to add logging, metrics, or override logic.
    """
    target = state.get("target_agent", "TRIAGE")
    
    # Safety: if routing_attempts > 3, force to triage to prevent loops
    attempts = state.get("routing_attempts", 0)
    if attempts > 3:
        rprint("[red]  ⚠️  Max routing attempts exceeded → forcing TRIAGE[/red]")
        return "TRIAGE"
    
    # Map state value to node name
    valid_agents = {"IT_HELP", "KNOWLEDGE", "TRIAGE"}
    
    if target not in valid_agents:
        rprint(f"[yellow]  ⚠️  Unknown agent '{target}' → defaulting to TRIAGE[/yellow]")
        return "TRIAGE"
    
    return target


class AgentHub:
    """
    The main entry point for the multi-agent system.
    
    This is the clean interface that the CLI (or API, or Slack bot)
    interacts with. It hides all the complexity of the graph.
    
    USAGE:
        hub = AgentHub()
        hub.ingest("rag/documents")
        result = hub.chat("How do I fix my VPN?")
        print(result["answer"])
    """
    
    def __init__(self):
        """Initialize the RAG chain and build the agent graph."""
        rprint("[bold]🏥 Initializing AgentOps Hub...[/bold]")
        
        self.rag_chain = RAGChain()
        self.graph = None  # Built after ingestion
        self._is_ready = False
    
    def ingest(self, documents_path: str) -> dict:
        """
        Ingest documents and build the agent graph.
        
        Must be called before chat().
        """
        # Ingest documents into RAG
        stats = self.rag_chain.ingest(documents_path)
        
        if stats["status"] == "success":
            # Build the graph (agents need RAG to be ready)
            self.graph = build_agent_graph(self.rag_chain)
            self._is_ready = True
        
        return stats
    
    def chat(self, user_message: str) -> dict:
        """
        Send a message through the multi-agent system.
        
        FLOW:
        1. Create initial state with user message
        2. Run the graph (orchestrator → specialist → END)
        3. Extract and return the result
        
        Args:
            user_message: The user's question or request
            
        Returns:
            Dict with 'answer', 'sources', 'handled_by', 'routing'
        """
        if not self._is_ready:
            return {
                "answer": "System not ready. Call ingest() first.",
                "handled_by": "SYSTEM",
                "sources": [],
            }
        
        # Create initial state
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
        
        # Run the graph
        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as e:
            rprint(f"[red]❌ Agent graph error: {e}[/red]")
            return {
                "answer": f"I encountered an error processing your request. Please try again.",
                "handled_by": "ERROR",
                "sources": [],
                "error": str(e),
            }
        
        # Extract results
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