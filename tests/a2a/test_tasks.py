import pytest
import asyncio
from app.a2a.tasks import TaskStore, TaskState
from app.a2a.state_machine import InvalidTransitionError


@pytest.mark.asyncio
async def test_create_task_returns_submitted():
    store = TaskStore()
    task = await store.create("task-001")
    assert task.status.state == TaskState.SUBMITTED


@pytest.mark.asyncio
async def test_create_idempotent():
    store = TaskStore()
    t1 = await store.create("task-002")
    t2 = await store.create("task-002")   # same id
    assert t1.id == t2.id                 # same task returned


@pytest.mark.asyncio
async def test_valid_transition():
    store = TaskStore()
    await store.create("task-003")
    task = await store.transition("task-003", TaskState.WORKING)
    assert task.status.state == TaskState.WORKING


@pytest.mark.asyncio
async def test_invalid_transition_raises():
    store = TaskStore()
    await store.create("task-004")
    await store.transition("task-004", TaskState.WORKING)
    await store.transition("task-004", TaskState.COMPLETED)
    with pytest.raises(InvalidTransitionError):
        await store.transition("task-004", TaskState.WORKING)  # completed → working = invalid


@pytest.mark.asyncio
async def test_concurrent_create_idempotency():
    """Race condition test — two coroutines create same task_id simultaneously."""
    store = TaskStore()
    results = await asyncio.gather(
        store.create("task-race"),
        store.create("task-race"),
    )
    # Both return same task — only one created
    assert results[0].id == results[1].id
    assert len(store._tasks) == 1
