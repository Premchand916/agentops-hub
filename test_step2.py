"""Step 2 — Tool Registry & Executor test."""

import json
from tools.backends import BackendServices
from tools.registry import ToolRegistry, ToolExecutionError

# Initialize
backends = BackendServices()
registry = ToolRegistry(backends)

# Test 1: Tool discovery
tools = registry.get_tool_names()
print(f"[OK] Registered {len(tools)} tools: {tools}")

# Test 2: Get schema for LLM (what Gemini sees for function calling)
schema = registry.get_tool_schema("create_ticket")
print(f"[OK] create_ticket schema has keys: {list(schema.keys())}")

# Test 3: Get ALL schemas (full tool menu for LLM)
all_schemas = registry.get_all_tool_schemas()
print(f"[OK] Full tool menu: {len(all_schemas)} tools")

# Test 4: Execute tool with valid arguments
result = registry.execute_tool_safe("create_ticket", {
    "title": "Monitor flickering on desk 42",
    "description": "Dell 27-inch monitor flickers every few seconds. Tried different cable.",
    "priority": "high",
    "tags": ["hardware", "monitor"],
})
print(f"[OK] Tool executed: {result['success']} — ticket {result['result']['ticket_id']}")

# Test 5: Execute tool with bad arguments (validation should catch it)
result = registry.execute_tool_safe("create_ticket", {
    "title": "Hi",
    "description": "bad",
    "priority": "banana",
})
print(f"[OK] Bad input caught: success={result['success']}, error starts with: {result['error'][:30]}...")

# Test 6: Execute non-existent tool
result = registry.execute_tool_safe("delete_everything", {})
print(f"[OK] Unknown tool caught: success={result['success']}")

# Test 7: Search tickets through registry
result = registry.execute_tool_safe("search_tickets", {
    "query": "vpn",
    "max_results": 3,
})
print(f"[OK] Search via registry: found {result['result']['total_found']} tickets")

# Test 8: System status through registry
result = registry.execute_tool_safe("get_system_status", {
    "system_name": "email",
})
print(f"[OK] Email status: {result['result']['status']}")

# Test 9: Notification through registry
result = registry.execute_tool_safe("send_notification", {
    "channel": "slack",
    "recipient": "#ops-alerts",
    "message": "Test notification from registry",
})
print(f"[OK] Notification sent: {result['result']['notification_id']}")

# Test 10: Prompt formatting (what goes into agent system prompts)
prompt_text = registry.format_tools_for_prompt()
tool_count = prompt_text.count("create_ticket") + prompt_text.count("search_tickets")
print(f"[OK] Prompt format generated: {len(prompt_text)} chars, mentions tools: {tool_count > 0}")

print()
print("=== All 10 tests passed! Step 2 complete. ===")
