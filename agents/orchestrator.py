"""
AgentOps Hub — Orchestrator Agent
====================================

WHAT THIS DOES:
Reads the user's message and decides which specialist agent should handle it.
It does NOT answer questions itself — it only ROUTES.

THIS IS THE MOST IMPORTANT AGENT because:
1. If routing is wrong, the user gets a bad experience
2. If routing is slow, every request is slow
3. If routing fails, nothing works

DESIGN DECISION — WHY LLM-BASED ROUTING (not keyword matching)?

Option 1: Keyword matching ("vpn" → IT_HELP, "pto" → KNOWLEDGE)
  ✗ Fails on: "I can't access anything remotely" (no keyword "vpn")
  ✗ Fails on: "Do I get time off for my wedding?" (no keyword "pto")

Option 2: Classifier model (fine-tuned BERT)
  ✓ Accurate, fast
  ✗ Needs training data, maintenance, separate model

Option 3: LLM-based routing (what we use)
  ✓ Understands intent, not just keywords
  ✓ Can explain its reasoning
  ✓ Easy to update — change the prompt, not the model
  ✗ Slightly slower than keyword matching (but <1 second)

We use Option 3 because it's the most flexible and maintainable.
In production, you might add a fast keyword pre-filter + LLM fallback.

INTERVIEW TIP:
Q: "How does your orchestrator decide which agent to route to?"
A: "It uses the LLM with a structured output prompt that returns a JSON
   with agent name, confidence score, and reasoning. If confidence is
   below 0.7, it routes to the Triage agent for clarification. The prompt
   includes few-shot examples for each agent category to improve accuracy."

Q: "What if the orchestrator routes incorrectly?"
A: "Three safeguards: (1) confidence threshold — low confidence goes to Triage,
   (2) the Triage agent can re-route after clarification, (3) we log every
   routing decision for evaluation. In production, I'd track routing accuracy
   as a metric and retune the prompt based on misroutes."
"""

import json
import yaml
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from config.settings import get_settings
from agents.state import AgentState
from rich import print as rprint

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


class OrchestratorAgent:
    """
    Routes user requests to the appropriate specialist agent.
    
    This is the "reception desk" of our hospital.
    """
    
    def __init__(self):
        settings = get_settings()
        
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=0.0,  # Zero temperature for routing — we want deterministic decisions
        )
        
        self.system_prompt = self._load_prompt("orchestrator")
        self.confidence_threshold = 0.7
    
    def route(self, state: AgentState) -> AgentState:
        """
        Analyze the user's message and decide which agent should handle it.
        
        This function is a LangGraph NODE — it receives state and returns state updates.
        
        FLOW:
        1. Extract the latest user message
        2. Send to LLM with routing prompt
        3. Parse the JSON response
        4. Return state update with routing decision
        """
        # Get the latest user message
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""
        
        rprint(f"[cyan]🔀 Orchestrator: Analyzing request...[/cyan]")
        
        # Ask the LLM to classify the intent
        prompt = f"{self.system_prompt}\n\nUser request: {user_message}"
        
        try:
            response = self.llm.invoke(prompt)
            content = response.content
            
            # Handle list response format from Gemini
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            
            # Parse the JSON routing decision
            routing = self._parse_routing(content)
            
        except Exception as e:
            rprint(f"[yellow]⚠️  Orchestrator error: {e}. Routing to TRIAGE.[/yellow]")
            routing = {
                "agent": "TRIAGE",
                "confidence": 0.0,
                "reasoning": f"Routing failed with error: {str(e)}"
            }
        
        # Apply confidence threshold
        agent = routing["agent"]
        confidence = routing["confidence"]
        
        if confidence < self.confidence_threshold and agent != "TRIAGE":
            rprint(f"[yellow]  ⚠️  Low confidence ({confidence:.2f}) → redirecting to TRIAGE[/yellow]")
            agent = "TRIAGE"
        
        rprint(f"[cyan]  🎯 Route: {agent} (confidence: {confidence:.2f})[/cyan]")
        rprint(f"[dim]  💭 Reason: {routing['reasoning']}[/dim]")
        
        # Return state updates
        return {
            "target_agent": agent,
            "routing_confidence": confidence,
            "routing_reasoning": routing["reasoning"],
            "routing_attempts": state.get("routing_attempts", 0) + 1,
        }
    
    def _parse_routing(self, response_text: str) -> dict:
        """
        Parse the LLM's routing decision from its response.
        
        The LLM should return JSON like:
        {"agent": "IT_HELP", "confidence": 0.95, "reasoning": "..."}
        
        But LLMs are unpredictable — they might add markdown, extra text, etc.
        This method handles all those cases gracefully.
        
        DEFENSIVE PROGRAMMING:
        Never trust LLM output to be perfectly formatted.
        Always have fallbacks. This is a production essential.
        """
        # Try to extract JSON from the response
        text = response_text.strip()
        
        # Remove markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start:end])
                return {
                    "agent": parsed.get("agent", "TRIAGE").upper(),
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "reasoning": parsed.get("reasoning", "No reasoning provided"),
                }
            except json.JSONDecodeError:
                pass
        
        # Fallback: try to detect agent from keywords in the response
        text_upper = text.upper()
        for agent in ["IT_HELP", "KNOWLEDGE", "WORKFLOW", "TRIAGE"]:
            if agent in text_upper:
                return {
                    "agent": agent,
                    "confidence": 0.5,  # Lower confidence for keyword fallback
                    "reasoning": f"Parsed from response text (keyword match): {text[:100]}",
                }
        
        # Ultimate fallback
        return {
            "agent": "TRIAGE",
            "confidence": 0.0,
            "reasoning": f"Could not parse routing from LLM response: {text[:100]}",
        }
    
    def _load_prompt(self, prompt_name: str) -> str:
        """Load system prompt from YAML config."""
        prompts_path = Path("config/prompts/system_prompts.yaml")
        
        if not prompts_path.exists():
            return "Route the user request to the appropriate agent. Return JSON with agent, confidence, reasoning."
        
        with open(prompts_path, "r") as f:
            prompts = yaml.safe_load(f)
        
        return prompts.get(prompt_name, {}).get("system_prompt", "Route to the appropriate agent.")