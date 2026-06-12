# app/a2a/policy.py

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TRACE_FILE = Path("traces") / "traces.jsonl"


# ── Policy rules ──────────────────────────────────────────────────────────────

@dataclass
class PolicyRule:
    rule_id: str
    description: str
    pattern: str   # regex, matched case-insensitively against the request text


@dataclass
class PolicyDecision:
    requires_approval: bool
    rule_id: str | None = None
    reason: str | None = None


DEFAULT_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="destructive-ops",
        description="Destructive operation detected",
        pattern=r"\b(delete|remove|drop|purge|wipe|terminate|shutdown|destroy)\b",
    ),
    PolicyRule(
        rule_id="admin-override",
        description="Privileged access or override requested",
        pattern=r"\b(admin|root|sudo|override|bypass)\b",
    ),
    PolicyRule(
        rule_id="bulk-action",
        description="Bulk action targeting all users or systems",
        pattern=r"\b(all users|everyone|mass|bulk)\b",
    ),
]


# ── Engine ────────────────────────────────────────────────────────────────────

class PolicyEngine:
    def __init__(self, rules: list[PolicyRule] | None = None):
        self._rules = rules if rules is not None else DEFAULT_RULES
        self._pending: dict[str, str] = {}   # task_id → original message

    def evaluate(self, message: str) -> PolicyDecision:
        for rule in self._rules:
            if re.search(rule.pattern, message, re.IGNORECASE):
                return PolicyDecision(
                    requires_approval=True,
                    rule_id=rule.rule_id,
                    reason=rule.description,
                )
        return PolicyDecision(requires_approval=False)

    def store_pending(self, task_id: str, message: str) -> None:
        self._pending[task_id] = message

    def pop_pending(self, task_id: str) -> str | None:
        return self._pending.pop(task_id, None)


# ── HITL tracing ──────────────────────────────────────────────────────────────

def record_hitl_event(
    task_id: str,
    event_type: str,
    rule_id: str | None = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    """Append a HITL trace event to traces/traces.jsonl. Never raises."""
    event = {
        "trace_id": f"hitl-{str(uuid.uuid4())[:8]}",
        "event_type": event_type,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rule_id": rule_id,
        "reason": reason,
        **extra,
    }
    try:
        _TRACE_FILE.parent.mkdir(exist_ok=True)
        with open(_TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # tracing must never crash the app


# ── Singleton ─────────────────────────────────────────────────────────────────

policy_engine = PolicyEngine()
