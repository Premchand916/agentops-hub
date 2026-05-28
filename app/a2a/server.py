# app/a2a/server.py

from fastapi import FastAPI
from app.a2a.tasks import task_store
from app.a2a.agent_card import get_agent_card
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
    return get_agent_card().model_dump()

from app.a2a.jsonrpc import jsonrpc_router

@app.post("/rpc")
async def rpc_endpoint(raw: dict):
    response = await jsonrpc_router(raw)
    if response is None:
        # Notification — HTTP 204 No Content
        from fastapi import Response
        return Response(status_code=204)
    return response.model_dump(exclude_none=True)

@app.get("/tasks/{task_id}/subscribe")
async def subscribe_task(task_id: str):
    """
    SSE endpoint — streams task state changes until terminal state or timeout.
    Client connects once, server pushes updates.
    """
    task = task_store.get(task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return EventSourceResponse(task_event_generator(task_id))