# tests/a2a/test_webhooks.py

import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.a2a.webhooks import WebhookDispatcher, verify_signature, _sign


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_returns_nonempty_string():
    d = WebhookDispatcher()
    sub_id = d.register("task-001", "https://example.com/hook")
    assert isinstance(sub_id, str) and len(sub_id) > 0


def test_register_returns_unique_ids():
    d = WebhookDispatcher()
    id1 = d.register("task-001", "https://example.com/hook-a")
    id2 = d.register("task-001", "https://example.com/hook-b")
    assert id1 != id2


# ── Dispatch ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_http():
    """Patch httpx.AsyncClient so no real HTTP is sent."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.a2a.webhooks.httpx.AsyncClient", return_value=mock_cm):
        yield mock_client


@pytest.mark.asyncio
async def test_notify_posts_to_registered_url(mock_http):
    d = WebhookDispatcher()
    d.register("task-002", "https://example.com/hook", secret="s3cr3t")

    await d.notify("task-002", {"status": "completed"})

    mock_http.post.assert_called_once()
    url_called = mock_http.post.call_args[0][0]
    assert url_called == "https://example.com/hook"


@pytest.mark.asyncio
async def test_notify_includes_signature_header(mock_http):
    d = WebhookDispatcher()
    d.register("task-003", "https://example.com/hook", secret="mysecret")

    await d.notify("task-003", {"status": "working"})

    _, kwargs = mock_http.post.call_args
    headers = kwargs.get("headers", {})
    assert "X-A2A-Signature" in headers
    assert headers["X-A2A-Signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_notify_without_secret_omits_signature_header(mock_http):
    d = WebhookDispatcher()
    d.register("task-004", "https://example.com/hook")  # no secret

    await d.notify("task-004", {"status": "working"})

    _, kwargs = mock_http.post.call_args
    headers = kwargs.get("headers", {})
    assert "X-A2A-Signature" not in headers


@pytest.mark.asyncio
async def test_notify_no_op_for_unknown_task(mock_http):
    d = WebhookDispatcher()
    await d.notify("task-999", {"status": "working"})
    mock_http.post.assert_not_called()


# ── HMAC verification ─────────────────────────────────────────────────────────

def test_verify_signature_accepts_valid_signature():
    payload = b'{"status": "completed"}'
    secret = "super-secret"
    signature = _sign(payload, secret)
    assert verify_signature(payload, secret, signature) is True


def test_verify_signature_rejects_tampered_payload():
    payload = b'{"status": "completed"}'
    secret = "super-secret"
    signature = _sign(payload, secret)
    tampered = b'{"status": "hacked"}'
    assert verify_signature(tampered, secret, signature) is False


# ── Unregister ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unregister_stops_dispatch(mock_http):
    d = WebhookDispatcher()
    sub_id = d.register("task-005", "https://example.com/hook", secret="s")

    d.unregister("task-005", sub_id)
    await d.notify("task-005", {"status": "completed"})

    mock_http.post.assert_not_called()
