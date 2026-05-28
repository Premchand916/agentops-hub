# app/a2a/streaming.py

import asyncio
import json
from collections.abc import AsyncGenerator
from app.a2a.tasks import task_store, TaskState


# Terminal states — stop streaming when reached
TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED}


async def task_event_generator(
    task_id: str,
    poll_interval: float = 0.5,
    timeout: float = 60.0,
) -> AsyncGenerator[dict, None]:
    """
    Async generator — yields SSE events as task state changes.
    Stops when task reaches terminal state or timeout expires.

    poll_interval: how often to check task state (seconds)
    timeout:       max time to stream before giving up (seconds)
    """
    elapsed = 0.0
    last_state = None

    while elapsed < timeout:
        task = task_store.get(task_id)

        if task is None:
            # Task not found — yield error event and stop
            yield {
                "event": "error",
                "data": json.dumps({"error": f"Task {task_id} not found"}),
                "id": "0",
            }
            return

        current_state = task.status.state

        # Only push event when state changes
        if current_state != last_state:
            yield {
                "event": "task_update",
                "data": json.dumps({
                    "id": task_id,
                    "status": {
                        "state": current_state.value,
                        "updated_at": task.status.updated_at.isoformat(),
                    },
                }),
                "id": str(int(elapsed * 1000)),  # milliseconds as event id
            }
            last_state = current_state

        # Stop streaming at terminal state
        if current_state in TERMINAL_STATES:
            return

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    # Timeout — yield timeout event
    yield {
        "event": "timeout",
        "data": json.dumps({"error": "Stream timeout", "task_id": task_id}),
        "id": "timeout",
    }