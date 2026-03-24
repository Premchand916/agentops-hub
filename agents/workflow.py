"""Workflow agent for actions like tickets, status checks, and notifications."""

import json
import re
from pathlib import Path

import yaml
from langchain_core.messages import AIMessage
from rich import print as rprint

from agents.state import AgentState
from config.llm_factory import get_llm
from tools.registry import ToolRegistry

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)


class WorkflowAgent:
    """Takes actions using tools."""

    def __init__(self, tool_registry: ToolRegistry):
        self.registry = tool_registry
        self.name = "WORKFLOW"
        self.llm = get_llm(temperature=0.0, format="json", num_ctx=2048)
        self.system_prompt = self._build_system_prompt()

    def handle(self, state: AgentState) -> AgentState:
        messages = state["messages"]
        user_message = messages[-1].content if messages else ""

        rprint("[magenta]  Workflow Agent: Processing action request...[/magenta]")

        tool_call = self._rule_based_tool_call(user_message)
        if not tool_call:
            tool_call = self._llm_tool_call(user_message)

        if tool_call["tool_name"] == "none":
            rprint("[yellow]    No matching tool found[/yellow]")
            return self._error_response(
                "I understand you want to take an action, but I could not map it to an available tool. "
                "Try asking to create a ticket, search tickets, check system status, or send a notification."
            )

        tool_name = tool_call["tool_name"]
        arguments = tool_call["arguments"]

        rprint(f"[magenta]   Calling tool: {tool_name}[/magenta]")
        rprint(f"[dim]   Args: {json.dumps(arguments, indent=2, default=str)[:200]}[/dim]")

        result = self.registry.execute_tool_safe(tool_name, arguments)
        if not result["success"]:
            rprint(f"[yellow]    First attempt failed: {result['error'][:100]}[/yellow]")
            rprint("[yellow]   Retrying with error context...[/yellow]")
            result = self._retry_with_error(user_message, tool_name, arguments, result["error"])

        if result["success"]:
            answer = self._format_success(tool_name, result["result"])
            rprint("[magenta]   Workflow Agent: Action completed[/magenta]")
        else:
            answer = self._format_failure(tool_name, result.get("error", "Unknown error"))
            rprint("[red]   Workflow Agent: Action failed[/red]")

        return {
            "messages": [AIMessage(content=answer)],
            "final_answer": answer,
            "sources": [],
            "handled_by": self.name,
        }

    def _rule_based_tool_call(self, user_message: str) -> dict | None:
        text = user_message.lower()

        if any(phrase in text for phrase in ("create a ticket", "open a ticket", "raise a ticket", "submit a ticket", "create ticket")):
            return {
                "tool_name": "create_ticket",
                "arguments": {
                    "title": self._build_ticket_title(user_message),
                    "description": user_message,
                    "priority": self._detect_priority(text),
                    "assignee": "IT Support",
                    "tags": self._extract_tags(text),
                },
                "reasoning": "Matched ticket-creation keywords.",
            }

        if any(phrase in text for phrase in ("search tickets", "find tickets", "find ticket", "search ticket")):
            query = self._extract_ticket_search_query(user_message)
            return {
                "tool_name": "search_tickets",
                "arguments": {
                    "query": query,
                    "max_results": 5,
                },
                "reasoning": "Matched ticket-search keywords.",
            }

        if "status" in text or "working" in text or "outage" in text:
            system_name = self._detect_system(text)
            if system_name:
                return {
                    "tool_name": "get_system_status",
                    "arguments": {"system_name": system_name},
                    "reasoning": "Matched system-status keywords.",
                }

        if any(phrase in text for phrase in ("send notification", "notify", "send alert", "send message")):
            return {
                "tool_name": "send_notification",
                "arguments": {
                    "channel": "slack",
                    "recipient": "it-team",
                    "message": user_message,
                },
                "reasoning": "Matched notification keywords.",
            }

        return None

    def _extract_ticket_search_query(self, user_message: str) -> str:
        """Remove command phrasing so ticket search uses the real keywords."""
        query = re.sub(
            r"^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?",
            "",
            user_message,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"^\s*(?:search|find)\s+tickets?\s*(?:for|about)?\s*[:\-]?\s*",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = query.strip().rstrip(".?!")
        return query or user_message.strip()

    def _llm_tool_call(self, user_message: str) -> dict:
        prompt = (
            f"{self.system_prompt}\n\n"
            f"User request: {user_message}\n\n"
            f"Respond with JSON only:\n"
            f'{{"tool_name":"name_of_tool","arguments":{{}},"reasoning":"short reason"}}'
        )

        try:
            response = self.llm.invoke(prompt)
            content = response.content
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            return self._parse_tool_call(content)
        except Exception as e:
            rprint(f"[red]   Workflow Agent LLM error: {e}[/red]")
            return {"tool_name": "none", "arguments": {}, "reasoning": str(e)}

    def _parse_tool_call(self, response_text: str) -> dict:
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
                    "tool_name": parsed.get("tool_name", "none"),
                    "arguments": parsed.get("arguments", {}),
                    "reasoning": parsed.get("reasoning", ""),
                }
            except json.JSONDecodeError:
                pass

        return {
            "tool_name": "none",
            "arguments": {},
            "reasoning": f"Could not parse tool call from LLM response: {text[:100]}",
        }

    def _retry_with_error(self, user_message: str, tool_name: str, original_args: dict, error: str) -> dict:
        retry_prompt = (
            f"{self.system_prompt}\n\n"
            f"User request: {user_message}\n\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(original_args, indent=2, default=str)}\n"
            f"Error: {error}\n\n"
            f"Respond with JSON only:\n"
            f'{{"tool_name":"{tool_name}","arguments":{{}}}}'
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
                return self.registry.execute_tool_safe(tool_call["tool_name"], tool_call["arguments"])
        except Exception as e:
            rprint(f"[red]   Retry also failed: {e}[/red]")

        return {"success": False, "error": f"Tool call failed after retry: {error}"}

    def _detect_priority(self, text: str) -> str:
        if any(word in text for word in ("critical", "sev1", "outage", "down", "urgent")):
            return "high"
        if any(word in text for word in ("asap", "important", "blocked")):
            return "high"
        return "medium"

    def _detect_system(self, text: str) -> str | None:
        for system_name in ("vpn", "email", "erp", "crm", "active_directory", "wifi"):
            if system_name.replace("_", " ") in text or system_name in text:
                return system_name
        return None

    def _extract_tags(self, text: str) -> list[str]:
        tags = []
        for tag in ("vpn", "email", "erp", "crm", "wifi", "password", "access"):
            if tag in text:
                tags.append(tag)
        if not tags:
            tags.append("general")
        return tags

    def _build_ticket_title(self, user_message: str) -> str:
        title = user_message.strip().rstrip(".?!")
        for prefix in ("create a ticket for", "open a ticket for", "raise a ticket for", "submit a ticket for", "create ticket for"):
            if title.lower().startswith(prefix):
                title = title[len(prefix):].strip()
                break
        if not title.lower().startswith("ticket:"):
            title = f"Ticket: {title}"
        return title[:120]

    def _format_success(self, tool_name: str, result: dict) -> str:
        if tool_name == "create_ticket":
            return (
                f"Ticket created successfully.\n\n"
                f"- Ticket ID: {result.get('ticket_id', 'N/A')}\n"
                f"- Title: {result.get('title', 'N/A')}\n"
                f"- Priority: {result.get('priority', 'N/A')}\n"
                f"- Status: {result.get('status', 'N/A')}\n"
                f"- Assigned to: {result.get('assignee', 'Unassigned')}"
            )

        if tool_name == "search_tickets":
            tickets = result.get("tickets", [])
            if not tickets:
                return f"No tickets found matching '{result.get('query', '')}'."
            lines = [f"Found {result.get('total_found', 0)} ticket(s) matching '{result.get('query', '')}':"]
            for ticket in tickets:
                lines.append(
                    f"- {ticket.get('ticket_id', '')} [{ticket.get('priority', '')}] {ticket.get('title', '')} (status: {ticket.get('status', '')})"
                )
            return "\n".join(lines)

        if tool_name == "get_system_status":
            return (
                f"System Status: {result.get('system_name', 'N/A')}\n\n"
                f"- Status: {result.get('status', 'unknown')}\n"
                f"- Details: {result.get('message', 'No details')}\n"
                f"- Uptime (30d): {result.get('uptime_percent', 0):.1f}%"
            )

        if tool_name == "send_notification":
            return (
                f"Notification sent.\n\n"
                f"- Channel: {result.get('channel', 'N/A')}\n"
                f"- To: {result.get('recipient', 'N/A')}\n"
                f"- ID: {result.get('notification_id', 'N/A')}"
            )

        return f"Tool `{tool_name}` executed successfully.\n\nResult: {json.dumps(result, indent=2, default=str)}"

    def _format_failure(self, tool_name: str, error: str) -> str:
        return (
            f"Action failed.\n\n"
            f"I tried to use the `{tool_name}` tool but got this error:\n{error}"
        )

    def _error_response(self, message: str) -> dict:
        return {
            "messages": [AIMessage(content=message)],
            "final_answer": message,
            "sources": [],
            "handled_by": self.name,
        }

    def _build_system_prompt(self) -> str:
        base_prompt = self._load_prompt("workflow")
        tool_descriptions = self.registry.format_tools_for_prompt()
        return f"{base_prompt}\n\n{tool_descriptions}"

    def _load_prompt(self, prompt_name: str) -> str:
        prompts_path = Path("config/prompts/system_prompts.yaml")
        if not prompts_path.exists():
            return "You are a workflow agent that takes actions using tools."

        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f)

        return prompts.get(prompt_name, {}).get("system_prompt", "You are a workflow agent.")
