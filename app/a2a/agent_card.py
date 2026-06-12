# app/a2a/agent_card.py

from pydantic import BaseModel, HttpUrl
from typing import List
import json

class Skill(BaseModel):
    id: str
    name: str
    description: str
    tags: List[str]
    examples: List[str]

class AgentCapabilities(BaseModel):
    streaming: bool = False
    push_notifications: bool = False

class AgentCard(BaseModel):
    name: str
    description: str
    version: str
    url: str
    skills: List[Skill]
    default_input_modes: List[str]
    default_output_modes: List[str]
    capabilities: AgentCapabilities

def get_agent_card() -> AgentCard:
    return AgentCard(
        name="AgentOps Hub",
        description="Multi-agent IT operations assistant with hybrid RAG and workflow automation",
        version="2.0.0",
        url="http://localhost:8000",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=True,
        ),
        skills=[
            Skill(
                id="it-help",
                name="IT Help",
                description="Handle IT support requests — VPN, hardware, software, access issues",
                tags=["it", "support", "tickets", "vpn", "hardware"],
                examples=[
                    "My VPN is not connecting",
                    "I can't access the shared drive",
                    "My laptop screen is flickering"
                ]
            ),
            Skill(
                id="knowledge-query",
                name="Knowledge Query",
                description="Search internal knowledge base and policy documents using RAG",
                tags=["knowledge", "rag", "policy", "search", "documents"],
                examples=[
                    "What is the password reset policy?",
                    "How do I request VPN access?",
                    "What are the WFH guidelines?"
                ]
            ),
            Skill(
                id="workflow",
                name="Workflow Automation",
                description="Create and manage IT tickets, check status, send notifications",
                tags=["workflow", "tickets", "automation", "notifications"],
                examples=[
                    "Create a ticket for my monitor issue",
                    "What is the status of ticket IT-1042?",
                    "Notify the IT team about server downtime"
                ]
            )
        ]
    )