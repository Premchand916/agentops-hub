"""
AgentOps Hub — Agent State
============================

WHAT THIS IS:
The "shared memory" that flows between all agents in our system.
Every agent can READ from this state and WRITE to it.

WHY STATE MATTERS (THE KEY INSIGHT):

In a single chatbot, there's no state problem — user asks, bot answers.
In a MULTI-AGENT system, agents need to share information:

  1. User says: "My VPN is broken and I need to submit a ticket"
  2. Orchestrator reads the message → routes to IT_HELP
  3. IT Help Agent reads the message + retrieves from RAG → writes answer
  4. BUT the user also said "submit a ticket" → needs WORKFLOW agent too
  5. The state carries the FULL context between agents

Without shared state, each agent would start from scratch.
With shared state, agents build on each other's work.

REAL-WORLD ANALOGY:
Think of a patient's medical chart in a hospital.
  - The receptionist writes: "Patient complains of chest pain"
  - The nurse adds: "Blood pressure: 140/90, temperature: normal"
  - The doctor reads ALL of this, adds: "ECG ordered, suspected angina"
  - The pharmacist reads the doctor's notes, dispenses medication

The chart IS the state. Everyone reads it. Everyone writes to it.
That's exactly what AgentState is for our agents.

LANGGRAPH CONCEPT:
In LangGraph, state is a TypedDict that gets passed through a graph.
Each node (agent) receives the state, does its work, and returns
updates to the state. LangGraph handles merging automatically.

INTERVIEW TIP:
Q: "How do agents communicate in your multi-agent system?"
A: "Through a shared typed state object managed by LangGraph's StateGraph.
   Each agent receives the current state, performs its task, and returns
   state updates. LangGraph handles state merging and ensures consistency.
   This is better than agents messaging each other directly because it
   creates a clear audit trail and makes debugging straightforward."

Q: "Why TypedDict and not a regular dict?"
A: "Type safety. With TypedDict, my IDE catches errors like misspelling
   'mesages' instead of 'messages'. In production with multiple agents
   reading/writing state, type errors are the #1 source of bugs."
"""

from typing import TypedDict, Annotated, Literal
from langchain_core.messages import BaseMessage
import operator


class AgentState(TypedDict):
    """
    Shared state that flows through the entire agent graph.
    
    Every field here is accessible by every agent.
    Think of it as the "patient chart" that all doctors can read and write.
    """
    
    # --- The conversation ---
    # All messages in the conversation (user + agent responses)
    # Annotated with operator.add means: new messages APPEND, not replace
    # So if agent A adds 1 message and agent B adds 1 message,
    # the state has both messages, not just the last one.
    messages: Annotated[list[BaseMessage], operator.add]
    
    # --- Routing decision ---
    # Which agent should handle this request?
    # Set by the orchestrator, read by the router
    target_agent: str  # "IT_HELP", "KNOWLEDGE", "TRIAGE", or "COMPLETE"
    
    # How confident is the orchestrator in its routing decision?
    # If below threshold → route to TRIAGE instead
    routing_confidence: float
    
    # Why did the orchestrator choose this agent?
    # Useful for debugging and observability
    routing_reasoning: str
    
    # --- Agent response ---
    # The final answer from whichever agent handled the request
    final_answer: str
    
    # Sources used (from RAG)
    sources: list[dict]
    
    # --- Metadata ---
    # Which agent actually handled the request (for logging)
    handled_by: str
    
    # Number of routing attempts (prevents infinite loops)
    routing_attempts: int
