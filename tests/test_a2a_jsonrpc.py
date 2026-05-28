# tests/test_a2a_jsonrpc.py

import pytest
from app.a2a.jsonrpc import jsonrpc_router, ErrorCode


# ── Test 1: valid request returns submitted→completed task ─────────────────

@pytest.mark.asyncio
async def test_tasks_send_request():
    raw = {
        "jsonrpc": "2.0",
        "id": "req-001",
        "method": "tasks/send",
        "params": {
            "id": "task-001",
            "message": {
                "role": "user",
                "parts": [{"text": "My laptop won't connect to VPN"}]
            }
        }
    }

    response = await jsonrpc_router(raw)

    assert response is not None               # request → must get response
    assert response.id == "req-001"           # id mirrors request
    assert response.error is None             # no error
    assert response.result["id"] == "task-001"
    assert response.result["status"]["state"] in ("completed", "failed")


# ── Test 2: notification returns None ─────────────────────────────────────

@pytest.mark.asyncio
async def test_tasks_cancel_notification():
    # First create a task
    await jsonrpc_router({
        "jsonrpc": "2.0",
        "id": "req-002",
        "method": "tasks/send",
        "params": {
            "id": "task-002",
            "message": {"role": "user", "parts": [{"text": "test"}]}
        }
    })

    # Cancel as notification (no id)
    raw = {
        "jsonrpc": "2.0",
        "method": "tasks/cancel",
        "params": {"id": "task-002"}
    }

    response = await jsonrpc_router(raw)
    assert response is None                   # notification → silence


# ── Test 3: unknown method returns -32601 ─────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_method():
    raw = {
        "jsonrpc": "2.0",
        "id": "req-003",
        "method": "tasks/delete",
        "params": {}
    }

    response = await jsonrpc_router(raw)

    assert response.error is not None
    assert response.error.code == ErrorCode.METHOD_NOT_FOUND
    assert response.id == "req-003"