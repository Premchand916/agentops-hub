"""
Tools package — tool definitions, simulated backends, and registry.

Session 3 builds this in layers:
- schemas.py    → Pydantic models (inputs, outputs, tool definitions)
- backends.py   → Simulated services (tickets, monitoring, notifications)
- registry.py   → Tool registry + executor (MCP-inspired)
"""

from tools.backends import BackendServices, NotificationService, SystemMonitor, TicketStore
from tools.registry import ToolExecutionError, ToolRegistry
from tools.schemas import (
    CreateTicketInput,
    GetSystemStatusInput,
    NotificationChannel,
    NotificationResult,
    SearchTicketsInput,
    SearchTicketsResult,
    SendNotificationInput,
    SystemStatusResult,
    TicketPriority,
    TicketResult,
    TicketStatus,
    ToolDefinition,
)

__all__ = [
    # Backends
    "BackendServices",
    "TicketStore",
    "SystemMonitor",
    "NotificationService",
    # Registry
    "ToolRegistry",
    "ToolExecutionError",
    # Input schemas
    "CreateTicketInput",
    "SearchTicketsInput",
    "GetSystemStatusInput",
    "SendNotificationInput",
    # Output schemas
    "TicketResult",
    "SearchTicketsResult",
    "SystemStatusResult",
    "NotificationResult",
    # Enums
    "TicketPriority",
    "TicketStatus",
    "NotificationChannel",
    # Meta
    "ToolDefinition",
]