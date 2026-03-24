"""Route user requests to the correct specialist agent."""

import json
from pathlib import Path

import yaml
from rich import print as rprint

from agents.state import AgentState
from config.llm_factory import get_llm

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)


class OrchestratorAgent:
    """Routes user requests to the appropriate specialist agent."""

    def __init__(self):
        self.llm = get_llm(temperature=0.0, format="json", num_ctx=2048)
        self.system_prompt = self._load_prompt("orchestrator")
        self.confidence_threshold = 0.7

    def route(self, state: AgentState) -> AgentState:
        """Analyze the latest message and choose a target agent."""
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""

        rprint("[cyan] Orchestrator: Analyzing request...[/cyan]")

        quick_route = self._keyword_route(user_message)
        if quick_route:
            return self._finalize_route(state, quick_route)

        prompt = f"{self.system_prompt}\n\nUser request: {user_message}"

        try:
            response = self.llm.invoke(prompt)
            content = response.content
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            routing = self._parse_routing(content)
        except Exception as e:
            rprint(f"[yellow]  Orchestrator error: {e}. Routing to TRIAGE.[/yellow]")
            routing = {
                "agent": "TRIAGE",
                "confidence": 0.0,
                "reasoning": f"Routing failed with error: {e}",
            }

        return self._finalize_route(state, routing)

    def _finalize_route(self, state: AgentState, routing: dict) -> AgentState:
        agent = routing["agent"]
        confidence = routing["confidence"]

        if confidence < self.confidence_threshold and agent != "TRIAGE":
            rprint(f"[yellow]    Low confidence ({confidence:.2f}) -> redirecting to TRIAGE[/yellow]")
            agent = "TRIAGE"

        reasoning = routing.get("reasoning", "No reasoning provided")
        rprint(f"[cyan]   Route: {agent} (confidence: {confidence:.2f})[/cyan]")
        rprint(f"[dim]   Reason: {reasoning}[/dim]")

        return {
            "target_agent": agent,
            "routing_confidence": confidence,
            "routing_reasoning": reasoning,
            "routing_attempts": state.get("routing_attempts", 0) + 1,
        }

    def _keyword_route(self, user_message: str) -> dict | None:
        text = user_message.lower()

        workflow_verbs = (
            "create", "open", "raise", "submit", "send", "notify", "search",
            "find", "update", "schedule", "book", "check status", "status of"
        )
        workflow_objects = (
            "ticket", "tickets", "notification", "message", "meeting", "status",
            "alert", "incident"
        )
        if any(verb in text for verb in workflow_verbs) and any(obj in text for obj in workflow_objects):
            return {
                "agent": "WORKFLOW",
                "confidence": 0.98,
                "reasoning": "Matched a direct action request with workflow keywords.",
            }

        knowledge_keywords = (
            "policy", "policies", "procedure", "procedures", "handbook", "documentation",
            "runbook", "wiki", "pto", "leave", "vacation", "benefits"
        )
        if any(keyword in text for keyword in knowledge_keywords):
            return {
                "agent": "KNOWLEDGE",
                "confidence": 0.92,
                "reasoning": "Matched policy or documentation keywords.",
            }

        technical_keywords = (
            "vpn", "password", "wifi", "network", "login", "log in", "email",
            "outlook", "install", "error", "laptop", "printer", "access", "docker"
        )
        if any(keyword in text for keyword in technical_keywords):
            return {
                "agent": "IT_HELP",
                "confidence": 0.88,
                "reasoning": "Matched technical troubleshooting keywords.",
            }

        return None

    def _parse_routing(self, response_text: str) -> dict:
        text = response_text.strip()

        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

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

        text_upper = text.upper()
        for agent in ["IT_HELP", "KNOWLEDGE", "WORKFLOW", "TRIAGE"]:
            if agent in text_upper:
                return {
                    "agent": agent,
                    "confidence": 0.5,
                    "reasoning": f"Parsed from response text: {text[:100]}",
                }

        return {
            "agent": "TRIAGE",
            "confidence": 0.0,
            "reasoning": f"Could not parse routing from LLM response: {text[:100]}",
        }

    def _load_prompt(self, prompt_name: str) -> str:
        prompts_path = Path("config/prompts/system_prompts.yaml")
        if not prompts_path.exists():
            return "Route the user request to the appropriate agent. Return JSON with agent, confidence, reasoning."

        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f)

        return prompts.get(prompt_name, {}).get("system_prompt", "Route to the appropriate agent.")
