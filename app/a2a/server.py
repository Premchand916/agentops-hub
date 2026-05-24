# app/a2a/server.py

from fastapi import FastAPI
from app.a2a.agent_card import get_agent_card

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
