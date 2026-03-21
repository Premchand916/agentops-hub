"""
AgentOps Hub — Workflow Agent
================================

WHAT THIS DOES:
Unlike IT Help and Knowledge agents (which ANSWER questions),
the Workflow Agent TAKES ACTIONS — creates tickets, checks system
status, sends notifications.

THIS IS THE KEY DIFFERENCE:
- IT Help Agent: "Here's how to fix your VPN" (information)
- Workflow Agent: "I've created ticket HELP-0005 for your VPN issue" (action)

HOW IT WORKS:
1. Receives user request (e.g., "Create a ticket for my VPN issue")
2. LLM reads available tool descriptions and decides which tool to call
3. LLM generates structured arguments for the tool
4. ToolRegistry validates and executes the tool
5. Agent formats the result into a human-readable response

DESIGN PATTERN — PROMPT-BASED TOOL CALLING:
Instead of using Gemini's native function calling API (which has
format quirks), we use a prompt-based approach:
- Tool descriptions go into the system prompt
- LLM outputs JSON with tool_name and arguments
- We parse and execute via the registry

This is more portable (works with any LLM) and easier to debug.
In production, you might use native function calling for speed.

INTERVIEW TIP:
Q: "How does your agent decide which tool to call?"
A: "The agent's system prompt includes descriptions of all available
   tools with their parameter schemas. The LLM reads these and outputs
   a JSON object specifying the tool name and arguments. The registry
   validates the arguments against Pydantic schemas before execution.
   If validation fails, the error is fed back to the LLM for self-correction."

Q: "What happens if the LLM generates invalid tool arguments?"
A: "Three layers of defense: (1) Pydantic validates types and constraints,
   (2) the registry returns structured error messages, (3) the agent can
   retry once with the error context so the LLM self-corrects."
"""

import json
import yaml
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage
from config.settings import get_settings
from agents.state import AgentState
from tools.registry import ToolRegistry
from rich import print as rprint

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


class WorkflowAgent:
    """
    Takes actions using tools — creates tickets, checks status, sends notifications.
    
    THE HOSPITAL ADMINISTRATOR:
    While doctors diagnose, the administrator handles paperwork:
    filing reports, ordering equipment, notifying departments.
    """
    
    def __init__(self, tool_registry: ToolRegistry):
        """
        Args:
            tool_registry: The ToolRegistry with all available tools registered
        """
        self.registry = tool_registry
        self.name = "WORKFLOW"
        
        settings = get_settings()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=0.0,  # Zero temp — tool calls must be precise
        )
        
        # Build system prompt with tool descriptions
        self.system_prompt = self._build_system_prompt()
    
    def handle(self, state: AgentState) -> AgentState:
        """
        Process a workflow/action request.
        
        FLOW:
        1. Send user message + tool descriptions to LLM
        2. LLM decides which tool to call and generates arguments
        3. Parse the LLM's tool call decision
        4. Execute via registry
        5. Format result for the user
        6. If tool call fails, retry ONCE with error context
        """
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""
        
        rprint(f"[magenta]⚙️  Workflow Agent: Processing action request...[/magenta]")
        
        # Step 1: Ask LLM to decide which tool to call
        prompt = (
            f"{self.system_prompt}\n\n"
            f"User request: {user_message}\n\n"
            f"Analyze the request and respond with a JSON object:\n"
            f'{{\n'
            f'  "tool_name": "name_of_tool_to_call",\n'
            f'  "arguments": {{...tool arguments...}},\n'
            f'  "reasoning": "why this tool and these arguments"\n'
            f'}}\n\n'
            f"If no tool fits the request, respond with:\n"
            f'{{\n'
            f'  "tool_name": "none",\n'
            f'  "arguments": {{}},\n'
            f'  "reasoning": "why no tool is appropriate"\n'
            f'}}'
        )
        
        try:
            response = self.llm.invoke(prompt)
            content = response.content
            
            # Handle list response format
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            
            # Parse the tool call decision
            tool_call = self._parse_tool_call(content)
            
        except Exception as e:
            rprint(f"[red]  ❌ Workflow Agent LLM error: {e}[/red]")
            return self._error_response(
                f"I had trouble understanding your request. Could you rephrase what action you'd like me to take?"
            )
        
        # Step 2: Handle "no tool" case
        if tool_call["tool_name"] == "none":
            rprint(f"[yellow]  ⚠️  No matching tool found[/yellow]")
            return self._error_response(
                f"I understand you want to take an action, but I'm not sure which one. "
                f"I can help with:\n"
                f"- **Creating support tickets** (e.g., 'Create a ticket for my VPN issue')\n"
                f"- **Searching existing tickets** (e.g., 'Find tickets about email problems')\n"
                f"- **Checking system status** (e.g., 'Is the VPN working?')\n"
                f"- **Sending notifications** (e.g., 'Notify the IT team about the outage')\n\n"
                f"What would you like to do?"
            )
        
        # Step 3: Execute the tool
        tool_name = tool_call["tool_name"]
        arguments = tool_call["arguments"]
        
        rprint(f"[magenta]  🔧 Calling tool: {tool_name}[/magenta]")
        rprint(f"[dim]  📋 Args: {json.dumps(arguments, indent=2, default=str)[:200]}[/dim]")
        
        result = self.registry.execute_tool_safe(tool_name, arguments)
        
        # Step 4: If failed, retry once with error context
        if not result["success"]:
            rprint(f"[yellow]  ⚠️  First attempt failed: {result['error'][:100]}[/yellow]")
            rprint(f"[yellow]  🔄 Retrying with error context...[/yellow]")
            
            result = self._retry_with_error(user_message, tool_name, arguments, result["error"])
        
        # Step 5: Format the result for the user
        if result["success"]:
            answer = self._format_success(tool_name, result["result"])
            rprint(f"[magenta]  ✅ Workflow Agent: Action completed[/magenta]")
        else:
            answer = self._format_failure(tool_name, result.get("error", "Unknown error"))
            rprint(f"[red]  ❌ Workflow Agent: Action failed[/red]")
        
        return {
            "messages": [AIMessage(content=answer)],
            "final_answer": answer,
            "sources": [],  # Workflow doesn't use RAG sources
            "handled_by": self.name,
        }
    
    def _parse_tool_call(self, response_text: str) -> dict:
        """
        Parse the LLM's tool call decision from its response.
        
        Handles various LLM output formats gracefully:
        - Clean JSON
        - JSON wrapped in markdown code blocks
        - JSON embedded in explanatory text
        """
        text = response_text.strip()
        
        # Remove markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start:end])
                return {
                    "tool_name": parsed.get("tool_name", "none"),
                    "arguments": parsed.get("arguments", {}),
                    "reasoning": parsed.get("reasoning", ""),
                }
            except json.JSONDecodeError:
                pass
        
        # Fallback: couldn't parse
        return {
            "tool_name": "none",
            "arguments": {},
            "reasoning": f"Could not parse tool call from LLM response: {text[:100]}",
        }
    
    def _retry_with_error(
        self, user_message: str, tool_name: str, 
        original_args: dict, error: str
    ) -> dict:
        """
        Retry a failed tool call by giving the LLM the error context.
        
        WHY RETRY:
        LLMs sometimes generate slightly wrong arguments (e.g., missing
        a required field, wrong enum value). Showing them the error often
        lets them self-correct on the second try.
        
        This is a common production pattern called "self-healing."
        """
        retry_prompt = (
            f"{self.system_prompt}\n\n"
            f"User request: {user_message}\n\n"
            f"I tried calling tool '{tool_name}' with these arguments:\n"
            f"{json.dumps(original_args, indent=2, default=str)}\n\n"
            f"But it failed with this error:\n{error}\n\n"
            f"Please fix the arguments and try again. Respond with JSON:\n"
            f'{{"tool_name": "{tool_name}", "arguments": {{...fixed args...}}}}'
        )
        
        try:
            response = self.llm.invoke(retry_prompt)
            content = response.content
            
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            
            tool_call = self._parse_tool_call(content)
            
            if tool_call["tool_name"] != "none":
                return self.registry.execute_tool_safe(
                    tool_call["tool_name"], tool_call["arguments"]
                )
        except Exception as e:
            rprint(f"[red]  ❌ Retry also failed: {e}[/red]")
        
        return {"success": False, "error": f"Tool call failed after retry: {error}"}
    
    def _format_success(self, tool_name: str, result: dict) -> str:
        """Format a successful tool result into a human-readable message."""
        
        if tool_name == "create_ticket":
            return (
                f"✅ **Ticket Created Successfully**\n\n"
                f"- **Ticket ID:** {result.get('ticket_id', 'N/A')}\n"
                f"- **Title:** {result.get('title', 'N/A')}\n"
                f"- **Priority:** {result.get('priority', 'N/A')}\n"
                f"- **Status:** {result.get('status', 'N/A')}\n"
                f"- **Assigned to:** {result.get('assignee', 'Unassigned')}\n\n"
                f"You can track this ticket using ID **{result.get('ticket_id', '')}**."
            )
        
        elif tool_name == "search_tickets":
            tickets = result.get("tickets", [])
            if not tickets:
                return f"🔍 No tickets found matching '{result.get('query', '')}'."
            
            lines = [f"🔍 **Found {result.get('total_found', 0)} ticket(s)** matching '{result.get('query', '')}':\n"]
            for t in tickets:
                lines.append(
                    f"- **{t.get('ticket_id', '')}** [{t.get('priority', '')}] "
                    f"{t.get('title', '')} — Status: {t.get('status', '')}"
                )
            return "\n".join(lines)
        
        elif tool_name == "get_system_status":
            status = result.get("status", "unknown")
            emoji = {"operational": "🟢", "degraded": "🟡", "down": "🔴", "maintenance": "🔵"}.get(status, "⚪")
            return (
                f"{emoji} **System Status: {result.get('system_name', 'N/A')}**\n\n"
                f"- **Status:** {status}\n"
                f"- **Details:** {result.get('message', 'No details')}\n"
                f"- **Uptime (30d):** {result.get('uptime_percent', 0):.1f}%"
            )
        
        elif tool_name == "send_notification":
            return (
                f"📨 **Notification Sent**\n\n"
                f"- **Channel:** {result.get('channel', 'N/A')}\n"
                f"- **To:** {result.get('recipient', 'N/A')}\n"
                f"- **Message:** {result.get('message', 'N/A')}\n"
                f"- **ID:** {result.get('notification_id', 'N/A')}"
            )
        
        else:
            return f"✅ Tool `{tool_name}` executed successfully.\n\nResult: {json.dumps(result, indent=2, default=str)}"
    
    def _format_failure(self, tool_name: str, error: str) -> str:
        """Format a failed tool result."""
        return (
            f"❌ **Action Failed**\n\n"
            f"I tried to use the `{tool_name}` tool but encountered an error:\n"
            f"{error}\n\n"
            f"Would you like me to try again with different parameters, "
            f"or would you prefer to describe your request differently?"
        )
    
    def _error_response(self, message: str) -> dict:
        """Create an error state update."""
        return {
            "messages": [AIMessage(content=message)],
            "final_answer": message,
            "sources": [],
            "handled_by": self.name,
        }
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt with tool descriptions."""
        # Load base prompt from YAML
        base_prompt = self._load_prompt("workflow")
        
        # Add tool descriptions from registry
        tool_descriptions = self.registry.format_tools_for_prompt()
        
        return f"{base_prompt}\n\n{tool_descriptions}"
    
    def _load_prompt(self, prompt_name: str) -> str:
        """Load system prompt from YAML config."""
        prompts_path = Path("config/prompts/system_prompts.yaml")
        
        if not prompts_path.exists():
            return "You are a workflow agent that takes actions using tools."
        
        with open(prompts_path, "r") as f:
            prompts = yaml.safe_load(f)
        
        return prompts.get(prompt_name, {}).get("system_prompt", "You are a workflow agent.")