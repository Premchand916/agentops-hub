# app/a2a/jsonrpc.py

from pydantic import BaseModel, Field
from typing import Any
import asyncio
from app.a2a.tasks import task_store, TaskState
from app.a2a.state_machine import InvalidTransitionError
from app.a2a.webhooks import webhook_dispatcher
from app.a2a.policy import policy_engine, record_hitl_event

# ── Global AgentHub instance ───────────────────────────────────────────────
_agent_hub = None

def set_agent_hub(hub):
    """Set the global AgentHub instance for JSON-RPC routing."""
    global _agent_hub
    _agent_hub = hub

def get_agent_hub():
    """Get the global AgentHub instance."""
    global _agent_hub
    if _agent_hub is None:
        from agents.graph import AgentHub
        _agent_hub = AgentHub()
    return _agent_hub


# ── Incoming from buyer agent ──────────────────────────────────────────────

class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str | None = None        # None = notification, str = request
    params: dict[str, Any] = {}


# ── Outgoing to buyer agent ────────────────────────────────────────────────

class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | None
    result: Any = None
    error: JSONRPCError | None = None


# ── Standard JSON-RPC error codes (from spec) ─────────────────────────────

class ErrorCode:
    PARSE_ERROR      = -32700   # invalid JSON received
    INVALID_REQUEST  = -32600   # JSON valid but not a valid request object
    METHOD_NOT_FOUND = -32601   # method doesn't exist
    INVALID_PARAMS   = -32602   # invalid method parameters
    INTERNAL_ERROR   = -32603   # internal server error


# ── Helper: build error response fast ─────────────────────────────────────

def error_response(id: str | None, code: int, message: str) -> JSONRPCResponse:
    return JSONRPCResponse(
        id=id,
        error=JSONRPCError(code=code, message=message)
    )


# ── JSON-RPC Router ────────────────────────────────────────────────────────

async def jsonrpc_router(raw: dict[str, Any]) -> JSONRPCResponse | None:
    """
    Route incoming JSON-RPC 2.0 requests to handlers.
    
    - Requests (with id): return JSONRPCResponse
    - Notifications (without id): return None
    - Unknown methods: return METHOD_NOT_FOUND error
    """
    try:
        request = JSONRPCRequest(**raw)
    except Exception as e:
        return error_response(
            raw.get("id"),
            ErrorCode.INVALID_REQUEST,
            f"Invalid request: {str(e)}"
        )

    # Dispatch to handler based on method
    method = request.method
    
    if method == "tasks/send":
        return await _handle_tasks_send(request)
    elif method == "tasks/cancel":
        return await _handle_tasks_cancel(request)
    else:
        # Unknown method
        if request.id is not None:
            return error_response(
                request.id,
                ErrorCode.METHOD_NOT_FOUND,
                f"Method '{method}' not found"
            )
        return None  # notification, no response


async def _handle_tasks_send(request: JSONRPCRequest) -> JSONRPCResponse | None:
    params = request.params
    task_id = params.get("id")

    if not task_id:
        if request.id is not None:
            return error_response(request.id, ErrorCode.INVALID_PARAMS, "Missing task id")
        return None

    # 1. Create task — idempotent, safe for duplicate task_ids
    await task_store.create(task_id)

    # 2. Extract text from message parts
    parts = params.get("message", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))

    # 3. HITL policy check — block destructive/privileged requests before working
    decision = policy_engine.evaluate(text)
    if decision.requires_approval:
        policy_engine.store_pending(task_id, text)
        await task_store.transition(task_id, TaskState.WAITING)
        record_hitl_event(task_id, "hitl.required", rule_id=decision.rule_id, reason=decision.reason)
        if request.id is not None:
            return JSONRPCResponse(
                id=request.id,
                result={
                    "id": task_id,
                    "status": {"state": "waiting"},
                    "approval_required": True,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                },
            )
        return None

    # 4. submitted → working
    await task_store.transition(task_id, TaskState.WORKING)
    await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "working"}})

    hub = get_agent_hub()
    if not hub._is_ready:
        try:
            from pathlib import Path
            doc_path = Path(__file__).parent.parent.parent / "rag" / "Documents"
            if doc_path.exists():
                hub.ingest(str(doc_path))
        except Exception:
            pass

    # 4. Run agent — on failure, transition to failed
    try:
        result = await asyncio.to_thread(hub.chat, text)
        await task_store.set_result(task_id, result)
        await task_store.transition(task_id, TaskState.COMPLETED)  # working → completed
        await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "completed"}, "result": result})
    except Exception as e:
        await task_store.transition(task_id, TaskState.FAILED)     # working → failed
        await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "failed"}})
        if request.id is not None:
            return error_response(request.id, ErrorCode.INTERNAL_ERROR, str(e))
        return None

    # 5. Return actual task state — not hardcoded
    task = task_store.get(task_id)
    if request.id is not None:
        return JSONRPCResponse(
            id=request.id,
            result={
                "id": task_id,
                "status": {
                    "state": task.status.state.value,
                    "updated_at": task.status.updated_at.isoformat(),
                },
                "result": result,
            }
        )
    return None


async def _handle_tasks_cancel(request: JSONRPCRequest) -> JSONRPCResponse | None:
    """Handle tasks/cancel notification: cancel a task."""
    try:
        params = request.params
        task_id = params.get("id")
        # For now, just acknowledge (actual cancellation would require task tracking)
        
        if request.id is not None:
            return JSONRPCResponse(
                id=request.id,
                result={"id": task_id, "status": {"state": "canceled"}}
            )
        return None  # notification
    except Exception as e:
        if request.id is not None:
            return error_response(
                request.id,
                ErrorCode.INTERNAL_ERROR,
                f"Error canceling task: {str(e)}"
            )
        return None