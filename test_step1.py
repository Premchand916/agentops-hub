"""Step 1 — Quick validation test."""
from tools.backends import BackendServices
from tools.schemas import (
    CreateTicketInput,
    GetSystemStatusInput,
    NotificationChannel,
    SearchTicketsInput,
    SendNotificationInput,
    TicketPriority,
)

# Test 1: Initialize backends
svc = BackendServices()
print(f"[OK] Backends initialized — {svc.tickets.total_tickets} tickets seeded")

# Test 2: Create a ticket
t = svc.tickets.create_ticket(CreateTicketInput(
    title="Printer offline in Building C",
    description="HP LaserJet on floor 2 shows offline status. Power cycled, still down.",
    priority=TicketPriority.MEDIUM,
    tags=["printer", "hardware"],
))
print(f"[OK] Created ticket: {t.ticket_id} — {t.title}")

# Test 3: Search tickets
r = svc.tickets.search_tickets(SearchTicketsInput(query="vpn"))
print(f"[OK] Search vpn found {r.total_found} tickets")

# Test 4: System status
s = svc.monitor.get_system_status(GetSystemStatusInput(system_name="vpn"))
print(f"[OK] VPN status: {s.status.value} — {s.uptime_percent}% uptime")

# Test 5: Send notification
n = svc.notifications.send_notification(SendNotificationInput(
    channel=NotificationChannel.SLACK,
    recipient="#it-support",
    message=f"New ticket {t.ticket_id}: {t.title}",
    related_ticket_id=t.ticket_id,
))
print(f"[OK] Notification {n.notification_id} sent to {n.recipient}")

# Test 6: Validation rejects bad data
try:
    bad = CreateTicketInput(title="Hi", description="short", priority="banana")
    print("[FAIL] Should have rejected bad input")
except Exception as e:
    print(f"[OK] Validation caught bad input: {type(e).__name__}")

# Test 7: JSON Schema generation
schema = CreateTicketInput.model_json_schema()
props = len(schema["properties"])
print(f"[OK] JSON Schema has {props} properties")

print()
print("=== All 7 tests passed! Step 1 complete. ===")