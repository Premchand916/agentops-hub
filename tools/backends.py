"""
Simulated Backends  In-memory services that mimic real operational tools.

Think of these as "mock kitchens" for development:
- TicketStore  simulates Jira/ServiceNow (stores tickets in a dict)
- SystemMonitor  simulates PagerDuty/Datadog (returns fake health data)
- NotificationService  simulates Slack/Email (logs messages)

Why simulate?
1. Build and test agent plumbing without external dependencies
2. Predictable behavior for testing and evals (Session 4)
3. Swap in real APIs later  the interface (schemas) stays the same

Each backend class:
- Accepts a validated Pydantic input model
- Returns a validated Pydantic output model
- Maintains state in memory (resets on restart)
"""

from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timezone
from typing import Optional

from tools.schemas import (
    CreateTicketInput,
    GetSystemStatusInput,
    NotificationChannel,
    NotificationResult,
    SearchTicketsInput,
    SearchTicketsResult,
    SendNotificationInput,
    SystemStatus,
    SystemStatusResult,
    TicketPriority,
    TicketResult,
    TicketStatus,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Current UTC time  single source of truth for timestamps."""
    return datetime.now(timezone.utc)


def _random_id(prefix: str, length: int = 4) -> str:
    """Generate a random ID like 'HELP-1234' or 'NOTIF-AB12'."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=length))
    return f"{prefix}-{suffix}"


# 
# Ticket Store  simulates Jira / ServiceNow
# 

class TicketStore:
    """In-memory ticket management system.
    
    Hospital analogy: This is the "patient records system."
    Doctors (agents) create records, search them, and update them.
    
    In production, this would be replaced by a Jira API client,
    ServiceNow connector, or any ITSM tool  but the method
    signatures stay identical.
    """

    def __init__(self) -> None:
        self._tickets: dict[str, TicketResult] = {}
        self._counter: int = 0
        self._seed_sample_tickets()

    def _seed_sample_tickets(self) -> None:
        """Pre-populate with sample tickets so search has data to find."""
        samples = [
            CreateTicketInput(
                title="VPN disconnects randomly on Windows 11",
                description="Users report VPN client v3.2 drops connection every "
                "15-20 minutes. Affects building A, floor 3. Error code E-4012.",
                priority=TicketPriority.HIGH,
                assignee="Network Team",
                tags=["vpn", "networking", "windows"],
            ),
            CreateTicketInput(
                title="Cannot access shared drive after password reset",
                description="After quarterly password rotation, several users "
                "unable to access \\\\fileserver\\shared. Getting 'Access Denied'. "
                "Re-mapping the drive doesn't help.",
                priority=TicketPriority.MEDIUM,
                assignee="IT Support",
                tags=["file-share", "access", "password"],
            ),
            CreateTicketInput(
                title="Email sync delay on mobile devices",
                description="Emails taking 30+ minutes to sync on iOS and Android. "
                "Exchange server shows normal load. Started after last update.",
                priority=TicketPriority.LOW,
                assignee="Email Team",
                tags=["email", "mobile", "exchange"],
            ),
            CreateTicketInput(
                title="ERP system slow during month-end close",
                description="SAP response times exceed 30 seconds during month-end "
                "batch processing. Finance team unable to complete reconciliation.",
                priority=TicketPriority.CRITICAL,
                assignee="ERP Team",
                tags=["erp", "performance", "sap"],
            ),
        ]
        for sample in samples:
            self.create_ticket(sample)
        logger.info(f"Seeded {len(samples)} sample tickets")

    def create_ticket(self, params: CreateTicketInput) -> TicketResult:
        """Create a new ticket. Returns the created ticket with ID."""
        self._counter += 1
        ticket_id = f"HELP-{self._counter:04d}"
        now = _now()

        ticket = TicketResult(
            ticket_id=ticket_id,
            title=params.title,
            description=params.description,
            priority=params.priority,
            status=TicketStatus.OPEN,
            assignee=params.assignee,
            tags=params.tags,
            created_at=now,
            updated_at=now,
        )
        self._tickets[ticket_id] = ticket
        logger.info(f"Created ticket {ticket_id}: {params.title}")
        return ticket

    def search_tickets(self, params: SearchTicketsInput) -> SearchTicketsResult:
        """Search tickets by keyword matching on title, description, and tags.
        
        Simple substring matching  in production you'd use
        Elasticsearch, Jira JQL, or similar.
        """
        query_lower = params.query.lower()
        matches: list[TicketResult] = []

        for ticket in self._tickets.values():
            # Check status filter first
            if params.status_filter and ticket.status != params.status_filter:
                continue

            # Substring search across multiple fields
            searchable = (
                f"{ticket.title} {ticket.description} "
                f"{' '.join(ticket.tags)} {ticket.assignee or ''}"
            ).lower()

            if query_lower in searchable:
                matches.append(ticket)

        # Limit results
        limited = matches[: params.max_results]
        logger.info(
            f"Search '{params.query}' found {len(matches)} tickets, "
            f"returning {len(limited)}"
        )

        return SearchTicketsResult(
            tickets=limited,
            total_found=len(matches),
            query=params.query,
        )

    def get_ticket(self, ticket_id: str) -> Optional[TicketResult]:
        """Retrieve a single ticket by ID."""
        return self._tickets.get(ticket_id)

    @property
    def total_tickets(self) -> int:
        return len(self._tickets)


# 
# System Monitor  simulates PagerDuty / Datadog
# 

class SystemMonitor:
    """Simulated infrastructure monitoring dashboard.
    
    Hospital analogy: The vital signs monitor on each ward.
    Shows whether each "organ" (system) is healthy or failing.
    
    In production  Datadog API, PagerDuty, AWS CloudWatch, etc.
    """

    # Simulated system states  in production these come from real monitoring
    _SYSTEMS: dict[str, dict] = {
        "vpn": {
            "status": SystemStatus.DEGRADED,
            "message": "VPN gateway experiencing intermittent packet loss. "
            "Network team investigating. ETA: 2 hours.",
            "uptime": 94.5,
        },
        "email": {
            "status": SystemStatus.OPERATIONAL,
            "message": "All email services running normally. "
            "Exchange Online and SMTP relay healthy.",
            "uptime": 99.9,
        },
        "erp": {
            "status": SystemStatus.OPERATIONAL,
            "message": "SAP S/4HANA responding within normal parameters. "
            "Batch jobs on schedule.",
            "uptime": 99.2,
        },
        "crm": {
            "status": SystemStatus.OPERATIONAL,
            "message": "Salesforce instance healthy. All integrations active.",
            "uptime": 99.8,
        },
        "active_directory": {
            "status": SystemStatus.OPERATIONAL,
            "message": "AD replication healthy across all domain controllers.",
            "uptime": 99.99,
        },
        "wifi": {
            "status": SystemStatus.MAINTENANCE,
            "message": "Building B access points undergoing firmware upgrade. "
            "Expected completion: 6:00 PM today.",
            "uptime": 97.1,
        },
    }

    def get_system_status(self, params: GetSystemStatusInput) -> SystemStatusResult:
        """Check a system's current health status."""
        system_key = params.system_name.lower().replace(" ", "_")

        if system_key in self._SYSTEMS:
            info = self._SYSTEMS[system_key]
            result = SystemStatusResult(
                system_name=params.system_name,
                status=info["status"],
                message=info["message"],
                last_checked=_now(),
                uptime_percent=info["uptime"],
            )
        else:
            # Unknown system  return a helpful "not found" instead of crashing
            known = ", ".join(sorted(self._SYSTEMS.keys()))
            result = SystemStatusResult(
                system_name=params.system_name,
                status=SystemStatus.OPERATIONAL,
                message=f"System '{params.system_name}' not found in monitoring. "
                f"Known systems: {known}",
                last_checked=_now(),
                uptime_percent=0.0,
            )
            logger.warning(f"Unknown system requested: {params.system_name}")

        logger.info(
            f"Status check [{params.system_name}]: {result.status.value}"
        )
        return result

    def list_systems(self) -> list[str]:
        """List all monitored system names."""
        return sorted(self._SYSTEMS.keys())


# 
# Notification Service  simulates Slack / Email
# 

class NotificationService:
    """Simulated notification delivery system.
    
    Hospital analogy: The intercom/paging system. When a doctor
    needs to alert a ward or call a specialist, they use this.
    
    In production  Slack API, SendGrid, Microsoft Teams webhooks, etc.
    """

    def __init__(self) -> None:
        self._sent: list[NotificationResult] = []

    def send_notification(
        self, params: SendNotificationInput
    ) -> NotificationResult:
        """Send a notification to a channel/recipient.
        
        In simulation mode, we just log it and store in memory.
        In production, this would call Slack/email/Teams APIs.
        """
        result = NotificationResult(
            success=True,
            notification_id=_random_id("NOTIF"),
            channel=params.channel,
            recipient=params.recipient,
            message=params.message,
            sent_at=_now(),
        )
        self._sent.append(result)
        logger.info(
            f"Notification {result.notification_id} sent via "
            f"{params.channel.value} to {params.recipient}"
        )
        return result

    @property
    def sent_count(self) -> int:
        return len(self._sent)

    @property
    def history(self) -> list[NotificationResult]:
        return list(self._sent)


# 
# Singleton-style factory  one instance per backend
# 

class BackendServices:
    """Central access point for all simulated backends.
    
    Why a container class? 
    - Single initialization point (backends share lifecycle)
    - Easy to swap implementations (inject real clients later)
    - Agents get backends through one interface, not scattered globals
    
    This is the Dependency Injection pattern  backends are "injected"
    into agents rather than agents creating their own connections.
    """

    def __init__(self) -> None:
        self.tickets = TicketStore()
        self.monitor = SystemMonitor()
        self.notifications = NotificationService()
        logger.info(
            "Backend services initialized  "
            f"tickets: {self.tickets.total_tickets} seeded, "
            f"systems: {len(self.monitor.list_systems())} monitored"
        )

    def health_check(self) -> dict[str, bool]:
        """Quick health check of all backends."""
        return {
            "tickets": True,  # In-memory, always healthy
            "monitor": True,
            "notifications": True,
        }
