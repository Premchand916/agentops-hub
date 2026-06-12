"""
A2A v1.0 Protocol Compliance Suite
=====================================
25 tests verifying the complete A2A protocol surface.

Categories:
  AC  Agent Card discovery          (6 tests)
  KP  JWKS key publication          (2 tests)
  RPC JSON-RPC 2.0 protocol         (5 tests)
  TL  Task lifecycle                (3 tests)
  WH  Webhooks                      (3 tests)
  HL  HITL policy & governance      (6 tests)

No Ollama required — the agent hub is mocked.
Run: python -m pytest tests/a2a_compliance/ -v
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.a2a.server import app
from app.a2a.signing import get_key_pair, verify_agent_card

MOCK_ANSWER = "Compliance test agent response"


@pytest.fixture(autouse=True)
def mock_hub():
    """Mock AgentHub for every test — no Ollama or LLM calls made."""
    hub = MagicMock()
    hub.chat.return_value = MOCK_ANSWER
    hub._is_ready = True
    with (
        patch("app.a2a.jsonrpc.get_agent_hub", return_value=hub),
        patch("app.a2a.server.get_agent_hub", return_value=hub),
    ):
        yield hub


@pytest.fixture()
def client():
    return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rpc(method: str, params: dict, req_id: str | None = "req-1") -> dict:
    body: dict = {"jsonrpc": "2.0", "method": method, "params": params}
    if req_id is not None:
        body["id"] = req_id
    return body


def _send(text: str, task_id: str | None = None, req_id: str | None = "req-1") -> dict:
    return _rpc(
        "tasks/send",
        {"id": task_id or str(uuid.uuid4()), "message": {"parts": [{"text": text}]}},
        req_id=req_id,
    )


# ── AC: Agent Card discovery (6) ─────────────────────────────────────────────

def test_ac01_agent_card_returns_200(client):
    assert client.get("/.well-known/agent.json").status_code == 200


def test_ac02_agent_card_has_required_fields(client):
    data = client.get("/.well-known/agent.json").json()
    for field in ("name", "version", "url", "skills", "capabilities"):
        assert field in data, f"Agent Card missing required field: {field}"


def test_ac03_agent_card_capabilities_streaming(client):
    data = client.get("/.well-known/agent.json").json()
    assert data["capabilities"]["streaming"] is True


def test_ac04_agent_card_capabilities_push_notifications(client):
    data = client.get("/.well-known/agent.json").json()
    assert data["capabilities"]["push_notifications"] is True


def test_ac05_agent_card_has_at_least_one_skill(client):
    data = client.get("/.well-known/agent.json").json()
    assert isinstance(data["skills"], list) and len(data["skills"]) >= 1


def test_ac06_agent_card_signature_is_jws_compact(client):
    data = client.get("/.well-known/agent.json").json()
    assert "signature" in data, "Agent Card must include a JWS signature"
    assert data["signature"].count(".") == 2, "Signature must be JWS compact (header.payload.sig)"


# ── KP: JWKS key publication (2) ─────────────────────────────────────────────

def test_kp01_jwks_returns_200_with_keys(client):
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data and len(data["keys"]) >= 1


def test_kp02_jwks_key_is_rsa_rs256(client):
    key = client.get("/.well-known/jwks.json").json()["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert all(f in key for f in ("n", "e", "kid"))


# ── RPC: JSON-RPC 2.0 protocol (5) ───────────────────────────────────────────

def test_rpc01_response_carries_jsonrpc_version(client):
    resp = client.post("/rpc", json=_send("help me with wifi"))
    assert resp.json()["jsonrpc"] == "2.0"


def test_rpc02_request_id_echoed_in_response(client):
    resp = client.post("/rpc", json=_send("wifi policy?", req_id="echo-me"))
    assert resp.json()["id"] == "echo-me"


def test_rpc03_notification_without_id_returns_204(client):
    resp = client.post("/rpc", json=_send("wifi policy?", req_id=None))
    assert resp.status_code == 204


def test_rpc04_unknown_method_returns_minus_32601(client):
    resp = client.post("/rpc", json=_rpc("tasks/bogus", {}))
    assert resp.json()["error"]["code"] == -32601


def test_rpc05_missing_task_id_returns_minus_32602(client):
    body = {"jsonrpc": "2.0", "id": "x", "method": "tasks/send", "params": {}}
    resp = client.post("/rpc", json=body)
    assert resp.json()["error"]["code"] == -32602


# ── TL: Task lifecycle (3) ───────────────────────────────────────────────────

def test_tl01_clean_task_completes_successfully(client):
    resp = client.post("/rpc", json=_send("how do I reset my password?"))
    result = resp.json()["result"]
    assert result["status"]["state"] == "completed"


def test_tl02_completed_task_has_non_empty_result(client):
    resp = client.post("/rpc", json=_send("what is the vpn policy?"))
    assert isinstance(resp.json()["result"]["result"], str)
    assert len(resp.json()["result"]["result"]) > 0


def test_tl03_cancel_returns_canceled_state(client):
    task_id = str(uuid.uuid4())
    resp = client.post("/rpc", json=_rpc("tasks/cancel", {"id": task_id}))
    assert resp.json()["result"]["status"]["state"] == "canceled"


# ── WH: Webhooks (3) ─────────────────────────────────────────────────────────

def test_wh01_register_returns_subscription_id(client):
    task_id = str(uuid.uuid4())
    resp = client.post(f"/tasks/{task_id}/webhooks", json={"url": "https://example.com/hook"})
    assert resp.status_code == 201
    assert "subscription_id" in resp.json()


def test_wh02_unregister_existing_subscription_returns_204(client):
    task_id = str(uuid.uuid4())
    sub_id = client.post(
        f"/tasks/{task_id}/webhooks",
        json={"url": "https://example.com/hook"},
    ).json()["subscription_id"]
    assert client.delete(f"/tasks/{task_id}/webhooks/{sub_id}").status_code == 204


def test_wh03_unregister_unknown_subscription_returns_404(client):
    task_id = str(uuid.uuid4())
    resp = client.delete(f"/tasks/{task_id}/webhooks/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── HL: HITL policy & governance (6) ─────────────────────────────────────────

def test_hl01_destructive_request_blocked_and_returns_waiting(client):
    resp = client.post("/rpc", json=_send("please delete all user accounts"))
    result = resp.json()["result"]
    assert result["approval_required"] is True
    assert result["status"]["state"] == "waiting"


def test_hl02_blocked_task_carries_rule_id(client):
    resp = client.post("/rpc", json=_send("shutdown all servers"))
    assert resp.json()["result"]["rule_id"] is not None


def test_hl03_blocked_task_carries_reason(client):
    resp = client.post("/rpc", json=_send("bypass the admin controls"))
    assert isinstance(resp.json()["result"]["reason"], str)


def test_hl04_approve_waiting_task_completes(client):
    task_id = str(uuid.uuid4())
    client.post("/rpc", json=_send("delete old tickets", task_id=task_id))
    resp = client.post(f"/tasks/{task_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"]["state"] == "completed"


def test_hl05_reject_waiting_task_marks_failed(client):
    task_id = str(uuid.uuid4())
    client.post("/rpc", json=_send("override admin config", task_id=task_id))
    resp = client.post(f"/tasks/{task_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"]["state"] == "failed"


def test_hl06_clean_request_bypasses_hitl_and_completes(client):
    resp = client.post("/rpc", json=_send("how do I connect to the VPN?"))
    result = resp.json()["result"]
    assert result.get("approval_required") is not True
    assert result["status"]["state"] == "completed"
