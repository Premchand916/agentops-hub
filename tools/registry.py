"""
Tool Registry & Executor  MCP-inspired tool management layer.

This is the "equipment rack" in our hospital analogy. It:
1. REGISTERS tools (what's available, what each does)
2. EXPOSES schemas (so the LLM knows how to call them)
3. EXECUTES tool calls (validates input  runs backend  returns output)

Architecture:
    Agent  "What tools do I have?"  Registry  [list of tool schemas]
    Agent  "Call create_ticket with {...}"  Executor  Backend  Result

Why this pattern?
- Agents don't know about backends directly (decoupled)
- Adding a new tool = register it, agents auto-discover it
- Validation happens at the registry layer, not in each agent
- Easy to swap simulated backends for real APIs later

In production, this would be a full MCP server using the `mcp` SDK.
For our learning purposes, this gives you the same patterns without
the server/client networking complexity.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from tools.backends import BackendServices
from tools.schemas import (
    CreateTicketInput,
    GetSystemStatusInput,
    SearchTicketsInput,
    SendNotificationInput,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Raised when a tool call fails.
    
    Wraps underlying errors with context about which tool
    failed and why  much more debuggable than raw exceptions.
    """

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        self.message = message
        super().__init__(f"Tool '{tool_name}' failed: {message}")


class ToolRegistry:
    """Central registry for all available tools.
    
    Hospital analogy: The equipment catalog. When a doctor (agent)
    needs a tool, they check the catalog to find:
    - What tools exist (list_tools)
    - What each tool needs (get_tool_schema)
    - How to use it (execute_tool)
    
    The registry owns the connection between:
    - Tool definitions (schemas)  what the LLM sees
    - Tool handlers (functions)  what actually runs
    
    This separation is key: the LLM generates arguments based on
    the schema, and the registry validates + routes to the handler.
    """

    def __init__(self, backends: BackendServices) -> None:
        self._backends = backends
        # Maps tool name  (definition, handler function)
        self._tools: dict[str, tuple[ToolDefinition, Callable]] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register all built-in tools with their backend handlers.
        
        Each registration connects:
        1. A ToolDefinition (name + description + input schema)
        2. A handler function (the backend method that does the work)
        
        The handler receives a validated Pydantic model and returns one.
        """
        self.register(
            definition=ToolDefinition(
                name="create_ticket",
                description=(
                    "Create a new IT support ticket. Use this when a user "
                    "reports an issue that needs tracking, like a VPN error, "
                    "hardware failure, or access problem."
                ),
                input_schema=CreateTicketInput,
            ),
            handler=self._backends.tickets.create_ticket,
        )

        self.register(
            definition=ToolDefinition(
                name="search_tickets",
                description=(
                    "Search existing support tickets by keyword. Use this to "
                    "find related or duplicate issues before creating new ones."
                ),
                input_schema=SearchTicketsInput,
            ),
            handler=self._backends.tickets.search_tickets,
        )

        self.register(
            definition=ToolDefinition(
                name="get_system_status",
                description=(
                    "Check the current health status of an IT system. Use this "
                    "when a user asks about system outages, uptime, or whether "
                    "a service is operational. Known systems: vpn, email, erp, "
                    "crm, active_directory, wifi."
                ),
                input_schema=GetSystemStatusInput,
            ),
            handler=self._backends.monitor.get_system_status,
        )

        self.register(
            definition=ToolDefinition(
                name="send_notification",
                description=(
                    "Send a notification via email, Slack, or Teams. Use this "
                    "to alert teams about new tickets, outages, or updates."
                ),
                input_schema=SendNotificationInput,
            ),
            handler=self._backends.notifications.send_notification,
        )

        logger.info(f"Registered {len(self._tools)} tools: {list(self._tools.keys())}")

    # 
    # Public API  what agents interact with
    # 

    def register(self, definition: ToolDefinition, handler: Callable) -> None:
        """Register a new tool with its handler.
        
        This is how you'd add custom tools:
            registry.register(
                definition=ToolDefinition(name="my_tool", ...),
                handler=my_function,
            )
        """
        if definition.name in self._tools:
            logger.warning(f"Overwriting existing tool: {definition.name}")
        self._tools[definition.name] = (definition, handler)
        logger.debug(f"Registered tool: {definition.name}")

    def list_tools(self) -> list[ToolDefinition]:
        """List all available tools. Agents call this to discover capabilities."""
        return [defn for defn, _ in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Get just the tool names (convenience method)."""
        return list(self._tools.keys())

    def get_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Get the JSON Schema for a tool's input.
        
        This is what gets sent to the LLM for function calling.
        The LLM reads this schema and generates valid JSON arguments.
        
        Returns a format that works well for prompt-based tool calling:
        {
            "name": "create_ticket",
            "description": "Create a new IT support ticket...",
            "parameters": { ...JSON Schema... }
        }
        """
        if tool_name not in self._tools:
            return None
        defn, _ = self._tools[tool_name]
        return {
            "name": defn.name,
            "description": defn.description,
            "parameters": defn.input_schema.model_json_schema(),
        }

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        """Get JSON Schemas for ALL tools  sent to LLM in one batch.
        
        This is the complete "tool menu" the LLM sees when deciding
        which tool to call and how to fill its arguments.
        """
        return [
            self.get_tool_schema(name)
            for name in self._tools
        ]

    def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> BaseModel:
        """Execute a tool call with validated arguments.
        
        This is the core execution pipeline:
        1. Look up the tool by name
        2. Validate arguments against the Pydantic input schema
        3. Call the backend handler
        4. Return the result (also a Pydantic model)
        
        If anything fails, raise ToolExecutionError with clear context.
        
        Args:
            tool_name: Which tool to call (e.g., "create_ticket")
            arguments: Raw dict of arguments (typically from LLM output)
        
        Returns:
            Pydantic model with the tool's result
        
        Raises:
            ToolExecutionError: If tool not found, validation fails, or execution errors
        """
        # Step 1: Find the tool
        if tool_name not in self._tools:
            available = ", ".join(self._tools.keys())
            raise ToolExecutionError(
                tool_name,
                f"Tool not found. Available tools: {available}",
            )

        defn, handler = self._tools[tool_name]

        # Step 2: Validate arguments against the input schema
        try:
            validated_input = defn.input_schema(**arguments)
        except ValidationError as e:
            # Format validation errors in a way the LLM can understand
            # and potentially self-correct
            error_details = []
            for err in e.errors():
                field = "  ".join(str(loc) for loc in err["loc"])
                error_details.append(f"  - {field}: {err['msg']}")
            error_msg = "Invalid arguments:\n" + "\n".join(error_details)
            logger.warning(f"Tool '{tool_name}' validation failed: {error_msg}")
            raise ToolExecutionError(tool_name, error_msg) from e

        # Step 3: Execute the handler
        try:
            result = handler(validated_input)
            logger.info(
                f"Tool '{tool_name}' executed successfully"
            )
            return result
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution error: {e}")
            raise ToolExecutionError(
                tool_name, f"Execution error: {str(e)}"
            ) from e

    def execute_tool_safe(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool and return a dict (safe version for agents).
        
        Unlike execute_tool(), this:
        - Never raises exceptions (returns error info in the dict)
        - Returns dicts instead of Pydantic models (easier for LLM context)
        - Always includes success/error status
        
        This is what agents actually call  they need predictable
        output format regardless of success or failure.
        """
        try:
            result = self.execute_tool(tool_name, arguments)
            return {
                "success": True,
                "tool": tool_name,
                "result": result.model_dump(mode="json"),
            }
        except ToolExecutionError as e:
            return {
                "success": False,
                "tool": tool_name,
                "error": e.message,
            }
        except Exception as e:
            return {
                "success": False,
                "tool": tool_name,
                "error": f"Unexpected error: {str(e)}",
            }

    def format_tools_for_prompt(self) -> str:
        """Format tool descriptions for inclusion in an agent's system prompt.
        
        When we can't use native function calling (or want a fallback),
        we describe tools in the system prompt so the LLM can output
        structured JSON to invoke them.
        
        Returns a clean, readable description of all available tools
        that the LLM can understand and use.
        """
        lines = ["Available tools:\n"]
        for defn, _ in self._tools.values():
            schema = defn.input_schema.model_json_schema()
            properties = schema.get("properties", {})

            # Build parameter descriptions
            params = []
            required = schema.get("required", [])
            for param_name, param_info in properties.items():
                req = "(required)" if param_name in required else "(optional)"
                desc = param_info.get("description", "No description")

                # Include enum values if present
                if "enum" in param_info:
                    desc += f"  options: {param_info['enum']}"
                elif "allOf" in param_info or "$ref" in param_info:
                    # Handle Pydantic v2 enum references
                    desc += "  see enum values in schema"

                params.append(f"    - {param_name} {req}: {desc}")

            param_block = "\n".join(params) if params else "    (no parameters)"

            lines.append(
                f"  {defn.name}: {defn.description}\n"
                f"  Parameters:\n{param_block}\n"
            )

        return "\n".join(lines)

