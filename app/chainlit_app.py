import chainlit as cl
from agents.graph import AgentHub

hub = AgentHub()

@cl.on_chat_start
async def start():
    await cl.Message(
        content="AgentOps Hub ready. Ask about IT support, policies, or create tickets."
    ).send()
    hub.ingest("rag/documents")

@cl.on_message
async def handle(message: cl.Message):
    # Show thinking step (agent routing visible to user)
    async with cl.Step(name="Routing request...") as step:
        result = hub.chat(message.content)
        step.output = f"Routed to: **{result['handled_by']}** (confidence: {result['routing']['confidence']:.0%})"

    # Stream the answer
    sources = result.get("sources", [])
    source_text = "\n".join(
        f"- `{s['source']}` (relevance: {s['score']:.3f})"
        for s in sources
    ) if sources else ""

    await cl.Message(
        content=result["answer"] + (f"\n\n**Sources:**\n{source_text}" if source_text else "")
    ).send()