# app/a2a/tasks.py

import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any


# ── Task state machine ─────────────────────────────────────────────────────

class TaskState(str, Enum):
    SUBMITTED       = "submitted"
    WORKING         = "working"
    INPUT_REQUIRED  = "input-required"
    COMPLETED       = "completed"
    FAILED          = "failed"


# ── Valid transitions (what state can go to what) ──────────────────────────
VALID_TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.SUBMITTED:      [TaskState.WORKING, TaskState.FAILED],
    TaskState.WORKING:        [TaskState.COMPLETED, TaskState.FAILED, TaskState.INPUT_REQUIRED],
    TaskState.INPUT_REQUIRED: [TaskState.WORKING, TaskState.FAILED],
    TaskState.COMPLETED:      [],   # terminal — no exits
    TaskState.FAILED:         [],   # terminal — no exits
}


# ── Data models ────────────────────────────────────────────────────────────

class TaskStatus(BaseModel):
    state: TaskState
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Task(BaseModel):
    id: str
    status: TaskStatus
    result: Any = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── In-memory task store ───────────────────────────────────────────────────

class TaskStore:
    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def create(self, task_id: str) -> Task:
        """Create task in SUBMITTED state. Idempotent — returns existing if id seen."""
        if task_id in self._tasks:
            return self._tasks[task_id]          # ← idempotency: same id = same task

        task = Task(
            id=task_id,
            status=TaskStatus(state=TaskState.SUBMITTED)
        )
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def transition(self, task_id: str, new_state: TaskState) -> Task:
        """Move task to new state. Raises if transition is invalid."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        current = task.status.state
        allowed = VALID_TRANSITIONS[current]

        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {current} → {new_state}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        task.status = TaskStatus(state=new_state)
        return task

    def set_result(self, task_id: str, result: Any) -> Task:
        task = self._tasks[task_id]
        task.result = result
        return task


# ── Singleton instance (shared across the app) ─────────────────────────────
task_store = TaskStore()