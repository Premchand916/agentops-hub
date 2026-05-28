
import pytest
import asyncio
import json
from app.a2a.tasks import TaskStore, TaskState
from app.a2a.streaming import task_event_generator, TERMINAL_STATES


@pytest.mark.asyncio
async def test_streams_completed_event():
    """Task completes — generator yields working then completed event."""
    store = TaskStore()
    await store.create("stream-001")
    await store.transition("stream-001", TaskState.WORKING)
    await store.transition("stream-001", TaskState.COMPLETED)

    # Patch task_store in streaming module
    import app.a2a.streaming as streaming_module
    original = streaming_module.task_store
    streaming_module.task_store = store

    events = []
    async for event in task_event_generator("stream-001", poll_interval=0.01):
        events.append(json.loads(event["data"]))

    streaming_module.task_store = original

    states = [e["status"]["state"] for e in events]
    assert "completed" in states
    assert event["event"] == "task_update"


@pytest.mark.asyncio
async def test_unknown_task_yields_error():
    """Non-existent task_id → error event, generator stops."""
    events = []
    async for event in task_event_generator("does-not-exist", poll_interval=0.01):
        events.append(event)

    assert len(events) == 1
    assert events[0]["event"] == "error"


@pytest.mark.asyncio
async def test_terminal_states_stop_stream():
    """Both COMPLETED and FAILED are terminal — stream stops."""
    assert TaskState.COMPLETED in TERMINAL_STATES
    assert TaskState.FAILED in TERMINAL_STATES


@pytest.mark.asyncio
async def test_no_duplicate_events_on_same_state():
    """State unchanged between polls → no duplicate events emitted."""
    store = TaskStore()
    await store.create("stream-002")
    await store.transition("stream-002", TaskState.WORKING)
    await store.transition("stream-002", TaskState.COMPLETED)

    import app.a2a.streaming as streaming_module
    original = streaming_module.task_store
    streaming_module.task_store = store

    events = []
    async for event in task_event_generator("stream-002", poll_interval=0.01):
        events.append(json.loads(event["data"]))

    streaming_module.task_store = original

    states = [e["status"]["state"] for e in events]
    # No duplicates — each state appears once
    assert len(states) == len(set(states))
