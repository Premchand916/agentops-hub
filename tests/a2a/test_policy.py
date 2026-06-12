# tests/a2a/test_policy.py

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.a2a.policy as pol
from app.a2a.policy import PolicyEngine, PolicyRule, record_hitl_event
from app.a2a.server import app
from app.a2a.state_machine import TaskState, validate_transition
from app.a2a.tasks import Task, TaskStatus, task_store


# ── PolicyEngine evaluation ───────────────────────────────────────────────────

def test_evaluate_clean_message_passes():
    engine = PolicyEngine()
    decision = engine.evaluate("My laptop won't connect to WiFi")
    assert decision.requires_approval is False


def test_evaluate_destructive_keyword_blocked():
    engine = PolicyEngine()
    decision = engine.evaluate("Please delete all old tickets")
    assert decision.requires_approval is True
    assert decision.rule_id == "destructive-ops"


def test_evaluate_admin_keyword_blocked():
    engine = PolicyEngine()
    decision = engine.evaluate("I need to override the admin settings")
    assert decision.requires_approval is True
    assert decision.rule_id == "admin-override"


def test_evaluate_bulk_action_blocked():
    engine = PolicyEngine()
    decision = engine.evaluate("Send notification to all users")
    assert decision.requires_approval is True
    assert decision.rule_id == "bulk-action"


def test_custom_rules_override_defaults():
    custom = [PolicyRule("custom", "custom rule", r"\bforbidden\b")]
    engine = PolicyEngine(rules=custom)
    assert engine.evaluate("this is forbidden").requires_approval is True
    assert engine.evaluate("delete all").requires_approval is False  # default not active


# ── Pending store / pop ───────────────────────────────────────────────────────

def test_pending_store_and_pop():
    engine = PolicyEngine()
    engine.store_pending("task-abc", "delete everything")
    assert engine.pop_pending("task-abc") == "delete everything"


def test_pop_nonexistent_returns_none():
    engine = PolicyEngine()
    assert engine.pop_pending("task-does-not-exist") is None


def test_pop_removes_entry():
    engine = PolicyEngine()
    engine.store_pending("task-xyz", "msg")
    engine.pop_pending("task-xyz")
    assert engine.pop_pending("task-xyz") is None


# ── HITL trace event ──────────────────────────────────────────────────────────

def test_record_hitl_event_writes_to_jsonl(tmp_path, monkeypatch):
    trace_file = tmp_path / "traces.jsonl"
    monkeypatch.setattr(pol, "_TRACE_FILE", trace_file)

    record_hitl_event("task-001", "hitl.required", rule_id="destructive-ops", reason="test reason")

    lines = trace_file.read_text().strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["task_id"] == "task-001"
    assert event["event_type"] == "hitl.required"
    assert event["rule_id"] == "destructive-ops"
    assert "timestamp" in event


# ── State machine WAITING transitions ─────────────────────────────────────────

def test_submitted_to_waiting_is_valid():
    assert validate_transition(TaskState.SUBMITTED, TaskState.WAITING) is True


def test_waiting_to_working_is_valid():
    assert validate_transition(TaskState.WAITING, TaskState.WORKING) is True


def test_waiting_to_failed_is_valid():
    assert validate_transition(TaskState.WAITING, TaskState.FAILED) is True


def test_waiting_is_not_terminal():
    assert validate_transition(TaskState.WAITING, TaskState.WORKING) is True


# ── Server endpoints ──────────────────────────────────────────────────────────

def _insert_waiting_task(task_id: str, message: str) -> None:
    """Directly insert a WAITING task into the singleton store for endpoint tests."""
    from app.a2a.tasks import TaskState as TS
    task_store._tasks[task_id] = Task(
        id=task_id,
        status=TaskStatus(state=TS.WAITING),
    )
    pol.policy_engine.store_pending(task_id, message)


def test_approve_nonexistent_task_returns_404():
    client = TestClient(app)
    resp = client.post(f"/tasks/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


def test_approve_non_waiting_task_returns_409():
    from app.a2a.tasks import TaskState as TS
    task_id = str(uuid.uuid4())
    task_store._tasks[task_id] = Task(
        id=task_id,
        status=TaskStatus(state=TS.SUBMITTED),
    )
    client = TestClient(app)
    resp = client.post(f"/tasks/{task_id}/approve")
    assert resp.status_code == 409


def test_approve_task_runs_agent_and_completes():
    task_id = str(uuid.uuid4())
    _insert_waiting_task(task_id, "help me with wifi")

    mock_hub = MagicMock()
    mock_hub.chat.return_value = "Here is the answer"
    mock_hub._is_ready = True

    with patch("app.a2a.server.get_agent_hub", return_value=mock_hub):
        client = TestClient(app)
        resp = client.post(f"/tasks/{task_id}/approve")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["state"] == "completed"
    assert data["result"] == "Here is the answer"


def test_reject_task_marks_as_failed():
    task_id = str(uuid.uuid4())
    _insert_waiting_task(task_id, "delete all servers")

    client = TestClient(app)
    resp = client.post(f"/tasks/{task_id}/reject")

    assert resp.status_code == 200
    assert resp.json()["status"]["state"] == "failed"


def test_reject_nonexistent_task_returns_404():
    client = TestClient(app)
    resp = client.post(f"/tasks/{uuid.uuid4()}/reject")
    assert resp.status_code == 404
