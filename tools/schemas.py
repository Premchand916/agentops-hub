"""
Tool Schemas  Pydantic models defining inputs and outputs for all agent tools.

Think of these as "contracts" between agents and tools:
- Input schemas = "What info does the tool need?"
- Output schemas = "What does the tool return?"

The LLM sees these schemas (as JSON Schema) and generates valid
arguments to call the tool. Pydantic validates everything automatically.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# 
# Enums  constrained choices (the LLM picks from these)
# 

class TicketPriority(str, Enum):
    """Priority levels for support tickets.
    
    Using str + Enum so values serialize as strings in JSON,
    which LLMs handle more reliably than integer codes.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(str, Enum):
    """Lifecycle states of a ticket."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SystemStatus(str, Enum):
    """Health states for monitored systems."""
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    DOWN = "down"
    MAINTENANCE = "maintenance"


class NotificationChannel(str, Enum):
    """Supported notification delivery channels."""
    EMAIL = "email"
    SLACK = "slack"
    TEAMS = "teams"


# 
# Tool Input Schemas  what the agent must provide
# 

class CreateTicketInput(BaseModel):
    """Input schema for creating a support ticket.
    
    Field descriptions are critical  they become part of the JSON Schema
    that the LLM reads to understand what each parameter means.
    """
    title: str = Field(
        ...,
        description="Short summary of the issue (e.g., 'VPN connection error E-4012')",
        min_length=5,
        max_length=200,
    )
    description: str = Field(
        ...,
        description="Detailed description of the issue, including steps to reproduce",
        min_length=10,
        max_length=2000,
    )
    priority: TicketPriority = Field(
        default=TicketPriority.MEDIUM,
        description="Urgency level: low, medium, high, or critical",
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Team or person to assign the ticket to (optional)",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Labels for categorization (e.g., ['vpn', 'networking'])",
    )


class SearchTicketsInput(BaseModel):
    """Input schema for searching existing tickets."""
    query: str = Field(
        ...,
        description="Search query to find matching tickets",
        min_length=2,
    )
    status_filter: Optional[TicketStatus] = Field(
        default=None,
        description="Filter by ticket status (optional)",
    )
    max_results: int = Field(
        default=5,
        description="Maximum number of results to return",
        ge=1,
        le=20,
    )


class GetSystemStatusInput(BaseModel):
    """Input schema for checking a system's health status."""
    system_name: str = Field(
        ...,
        description="Name of the system to check (e.g., 'vpn', 'email', 'erp', 'crm')",
    )


class SendNotificationInput(BaseModel):
    """Input schema for sending a notification."""
    channel: NotificationChannel = Field(
        ...,
        description="Delivery channel: email, slack, or teams",
    )
    recipient: str = Field(
        ...,
        description="Who to notify (email address, channel name, or team name)",
    )
    message: str = Field(
        ...,
        description="Notification message content",
        min_length=1,
        max_length=1000,
    )
    related_ticket_id: Optional[str] = Field(
        default=None,
        description="Link to a related ticket ID (optional)",
    )


# 
# Tool Output Schemas  what the tool returns
# 

class TicketResult(BaseModel):
    """Output from creating or retrieving a ticket."""
    ticket_id: str = Field(description="Unique ticket identifier (e.g., 'HELP-1234')")
    title: str
    description: str
    priority: TicketPriority
    status: TicketStatus
    assignee: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SearchTicketsResult(BaseModel):
    """Output from searching tickets."""
    tickets: list[TicketResult]
    total_found: int
    query: str


class SystemStatusResult(BaseModel):
    """Output from a system health check."""
    system_name: str
    status: SystemStatus
    message: str = Field(description="Human-readable status description")
    last_checked: datetime
    uptime_percent: float = Field(
        description="Uptime percentage over last 30 days",
        ge=0.0,
        le=100.0,
    )


class NotificationResult(BaseModel):
    """Output from sending a notification."""
    success: bool
    notification_id: str
    channel: NotificationChannel
    recipient: str
    message: str
    sent_at: datetime


# 
# Tool Metadata  used by the tool registry (Step 3)
# 

class ToolDefinition(BaseModel):
    """Describes a tool for the registry and LLM function calling.
    
    This is the "menu item"  name, description, and what
    input schema it expects. The LLM reads this to decide
    which tool to call and how to fill the arguments.
    """
    name: str = Field(description="Unique tool identifier")
    description: str = Field(description="What this tool does (shown to LLM)")
    input_schema: type[BaseModel] = Field(
        description="Pydantic model class for input validation"
    )
    # We store the class itself, not an instance  we'll use it
    # to validate inputs and generate JSON Schema for the LLM.

    model_config = ConfigDict(arbitrary_types_allowed=True)  # Needed to store type references
