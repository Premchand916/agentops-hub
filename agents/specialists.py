"""
AgentOps Hub — Specialist Agents
===================================

WHAT THIS FILE CONTAINS:
Three specialist agents, each with a different role:

1. IT Help Agent    — diagnoses technical issues using RAG
2. Knowledge Agent  — retrieves policy/procedure info using RAG
3. Triage Agent     — handles unclear requests, asks clarifying questions

DESIGN DECISION — WHY ONE FILE (not three separate files)?

For 3 small agents that share 90% of their code, one file is cleaner.
The only real difference between them is:
  - Which system prompt they use
  - How they format their response
  - What they do when RAG has no answer

If agents grew complex (100+ lines each), we'd split them.
This is the YAGNI principle: "You Aren't Gonna Need It" — don't
over-engineer until complexity demands it.

IMPORTANT PATTERN — ALL AGENTS FOLLOW THE SAME INTERFACE:

    def handle(self, state: AgentState) -> AgentState:
        # 1. Read from state
        # 2. Do work (RAG query, LLM call, etc.)
        # 3. Return state updates

This consistent interface is WHY LangGraph works — every node
(agent) has the same signature. You can add new agents without
changing the graph structure.

INTERVIEW TIP:
Q: "How do you add a new agent to your system?"
A: "Three steps: (1) Write the agent class with a handle() method
   that takes state and returns state updates, (2) Add a node in
   the LangGraph StateGraph, (3) Update the orchestrator prompt to
   include the new agent's description. No other code changes needed.
   This is the Open/Closed Principle — open for extension, closed
   for modification."
"""

import yaml
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage
from config.settings import get_settings
from agents.state import AgentState
from rag.rag_chain import RAGChain
from rich import print as rprint

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


class ITHelpAgent:
    """
    Handles technical support questions using RAG.
    
    THE IT DOCTOR:
    - Diagnoses technical issues
    - Provides step-by-step troubleshooting
    - Cites source documents
    - Escalates when unsure
    """
    
    def __init__(self, rag_chain: RAGChain):
        """
        Takes a RAGChain instance (shared across agents).
        
        WHY SHARED RAG:
        All agents query the SAME knowledge base. Creating separate
        RAG instances would waste memory (duplicate embeddings, duplicate
        vector store). Sharing is efficient and consistent.
        """
        self.rag = rag_chain
        self.name = "IT_HELP"
    
    def handle(self, state: AgentState) -> AgentState:
        """
        Process an IT support request.
        
        FLOW:
        1. Extract user question from state
        2. Query RAG for relevant technical docs
        3. Return answer with sources
        """
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""
        
        rprint(f"[green]🔧 IT Help Agent: Processing...[/green]")
        
        # Query RAG (hybrid retrieval + reranking + Gemini generation)
        result = self.rag.query(user_message, show_sources=False)
        
        answer = result["answer"]
        sources = result.get("sources", [])
        
        rprint(f"[green]  ✅ IT Help Agent: Response ready[/green]")
        
        return {
            "messages": [AIMessage(content=answer)],
            "final_answer": answer,
            "sources": sources,
            "handled_by": self.name,
        }


class KnowledgeAgent:
    """
    Handles policy, procedure, and documentation questions using RAG.
    
    THE RECORDS SPECIALIST:
    - Finds relevant company documents
    - Synthesizes information from multiple sources
    - Provides citations
    - Notes when info might be outdated
    """
    
    def __init__(self, rag_chain: RAGChain):
        self.rag = rag_chain
        self.name = "KNOWLEDGE"
    
    def handle(self, state: AgentState) -> AgentState:
        """Process a knowledge retrieval request."""
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""
        
        rprint(f"[blue]📚 Knowledge Agent: Searching documents...[/blue]")
        
        result = self.rag.query(user_message, show_sources=False)
        
        answer = result["answer"]
        sources = result.get("sources", [])
        
        rprint(f"[blue]  ✅ Knowledge Agent: Response ready[/blue]")
        
        return {
            "messages": [AIMessage(content=answer)],
            "final_answer": answer,
            "sources": sources,
            "handled_by": self.name,
        }


class TriageAgent:
    """
    Handles unclear, multi-domain, or sensitive requests.
    
    THE EMERGENCY ROOM:
    - Asks clarifying questions when the request is ambiguous
    - Escalates to human when AI can't help
    - Handles sensitive situations with care
    
    THIS AGENT IS DIFFERENT from IT Help and Knowledge:
    - It does NOT always use RAG
    - Sometimes it just asks the user a clarifying question
    - Sometimes it says "I need to escalate this to a human"
    
    WHY TRIAGE IS ESSENTIAL:
    Without Triage, unclear requests get random answers from wrong agents.
    With Triage, the system asks ONE clarifying question and then routes correctly.
    This is how real support systems work — a human triage nurse doesn't guess.
    """
    
    def __init__(self, rag_chain: RAGChain):
        self.rag = rag_chain
        self.name = "TRIAGE"
        settings = get_settings()
        
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=0.3,  # Slightly creative for natural conversation
        )
        
        self.system_prompt = self._load_prompt("triage")
    
    def handle(self, state: AgentState) -> AgentState:
        """
        Handle an unclear or complex request.
        
        STRATEGY:
        1. If routing confidence was low → ask clarifying question
        2. If routing failed → try to understand and help generically
        3. If sensitive topic → escalate to human
        """
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""
        confidence = state.get("routing_confidence", 0)
        reasoning = state.get("routing_reasoning", "")
        
        rprint(f"[yellow]🔍 Triage Agent: Evaluating request...[/yellow]")
        
        # Build context for triage
        prompt = (
            f"{self.system_prompt}\n\n"
            f"User request: {user_message}\n\n"
            f"Routing context: The orchestrator had {confidence:.0%} confidence.\n"
            f"Reasoning: {reasoning}\n\n"
            f"Based on the above, help the user. Either:\n"
            f"1. Ask ONE specific clarifying question to understand their need\n"
            f"2. Try to answer if you have enough context\n"
            f"3. Suggest escalation to a human if this is sensitive or complex"
        )
        
        try:
            # Try RAG first — maybe we can still find something useful
            rag_result = self.rag.query(user_message, show_sources=False)
            
            if rag_result.get("sources") and any(
                s.get("rerank_score", 0) > 0.5 for s in rag_result.get("sources", [])
            ):
                # RAG found something relevant — use it
                answer = rag_result["answer"]
                sources = rag_result.get("sources", [])
                rprint(f"[yellow]  ✅ Triage Agent: Found relevant info via RAG[/yellow]")
            else:
                # RAG didn't find much — ask clarifying question
                response = self.llm.invoke(prompt)
                content = response.content
                
                if isinstance(content, list):
                    content = " ".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                
                answer = content
                sources = []
                rprint(f"[yellow]  ✅ Triage Agent: Clarification or escalation[/yellow]")
                
        except Exception as e:
            answer = (
                "I'm having trouble processing your request right now. "
                "Could you rephrase your question, or would you like me to "
                "connect you with a human support agent?"
            )
            sources = []
            rprint(f"[red]  ❌ Triage Agent error: {e}[/red]")
        
        return {
            "messages": [AIMessage(content=answer)],
            "final_answer": answer,
            "sources": sources,
            "handled_by": self.name,
        }
    
    def _load_prompt(self, prompt_name: str) -> str:
        """Load system prompt from YAML config."""
        prompts_path = Path("config/prompts/system_prompts.yaml")
        
        if not prompts_path.exists():
            return "You are a triage agent. Help the user or ask clarifying questions."
        
        with open(prompts_path, "r") as f:
            prompts = yaml.safe_load(f)
        
        return prompts.get(prompt_name, {}).get("system_prompt", "Help the user.")