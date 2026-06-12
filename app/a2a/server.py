# app/a2a/server.py

import asyncio

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from app.a2a.tasks import task_store, TaskState
from app.a2a.agent_card import get_agent_card
from app.a2a.webhooks import webhook_dispatcher
from app.a2a.signing import get_key_pair, sign_agent_card, get_jwks
from app.a2a.policy import policy_engine, record_hitl_event
from sse_starlette.sse import EventSourceResponse
from app.a2a.streaming import task_event_generator

app = FastAPI()


@app.get("/")
async def root():
    return {
        "name": "AgentOps Hub A2A Server",
        "status": "ok",
        "agent_card_url": "/.well-known/agent.json",
    }


@app.get("/.well-known/agent.json")
async def agent_card():
    card = get_agent_card()
    card_dict = card.model_dump()
    card_dict["signature"] = sign_agent_card(card_dict, get_key_pair())
    return card_dict


@app.get("/.well-known/jwks.json")
async def jwks():
    return get_jwks(get_key_pair())


from app.a2a.jsonrpc import jsonrpc_router, get_agent_hub

@app.post("/rpc")
async def rpc_endpoint(raw: dict):
    response = await jsonrpc_router(raw)
    if response is None:
        return Response(status_code=204)
    return response.model_dump(exclude_none=True)


@app.get("/tasks/{task_id}/subscribe")
async def subscribe_task(task_id: str):
    """SSE endpoint — streams task state changes until terminal state or timeout."""
    task = task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return EventSourceResponse(task_event_generator(task_id))


# ── Webhook endpoints ─────────────────────────────────────────────────────────

class WebhookRegisterRequest(BaseModel):
    url: str
    secret: str | None = None


@app.post("/tasks/{task_id}/webhooks", status_code=201)
async def register_webhook(task_id: str, body: WebhookRegisterRequest):
    """Register a webhook subscription for a task."""
    sub_id = webhook_dispatcher.register(task_id, body.url, body.secret)
    return {"subscription_id": sub_id}


@app.delete("/tasks/{task_id}/webhooks/{subscription_id}", status_code=204)
async def unregister_webhook(task_id: str, subscription_id: str):
    """Unregister a webhook subscription."""
    removed = webhook_dispatcher.unregister(task_id, subscription_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return Response(status_code=204)


# ── HITL approval endpoints ───────────────────────────────────────────────────

@app.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str):
    """Approve a HITL-gated task. Resumes execution from WAITING → WORKING."""
    task = task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.status.state != TaskState.WAITING:
        raise HTTPException(
            status_code=409,
            detail=f"Task is not awaiting approval (state: {task.status.state.value})",
        )

    text = policy_engine.pop_pending(task_id)
    if text is None:
        raise HTTPException(status_code=409, detail="No pending message found for this task")

    record_hitl_event(task_id, "hitl.approved")
    await task_store.transition(task_id, TaskState.WORKING)
    await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "working"}})

    hub = get_agent_hub()
    try:
        result = await asyncio.to_thread(hub.chat, text)
        await task_store.set_result(task_id, result)
        await task_store.transition(task_id, TaskState.COMPLETED)
        await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "completed"}, "result": result})
        return {"id": task_id, "status": {"state": "completed"}, "result": result}
    except Exception as e:
        await task_store.transition(task_id, TaskState.FAILED)
        await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "failed"}})
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks/{task_id}/reject")
async def reject_task(task_id: str):
    """Reject a HITL-gated task. Marks it as failed."""
    task = task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.status.state != TaskState.WAITING:
        raise HTTPException(
            status_code=409,
            detail=f"Task is not awaiting approval (state: {task.status.state.value})",
        )

    policy_engine.pop_pending(task_id)
    record_hitl_event(task_id, "hitl.rejected")
    await task_store.transition(task_id, TaskState.FAILED)
    await webhook_dispatcher.notify(task_id, {"id": task_id, "status": {"state": "failed"}})
    return {"id": task_id, "status": {"state": "failed"}}