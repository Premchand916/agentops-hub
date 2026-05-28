# tests/a2a/test_state_machine.py

import pytest
from app.a2a.state_machine import (
    TaskState,
    validate_transition,
    assert_transition,
    InvalidTransitionError,
)


def test_valid_submitted_to_working():
    assert validate_transition(TaskState.SUBMITTED, TaskState.WORKING) is True


def test_invalid_completed_to_working():
    assert validate_transition(TaskState.COMPLETED, TaskState.WORKING) is False


def test_terminal_states_have_no_exits():
    assert validate_transition(TaskState.COMPLETED, TaskState.FAILED) is False
    assert validate_transition(TaskState.FAILED, TaskState.WORKING) is False


def test_assert_transition_raises_on_invalid():
    with pytest.raises(InvalidTransitionError) as exc_info:
        assert_transition(TaskState.COMPLETED, TaskState.WORKING)
    assert "completed" in str(exc_info.value)
    assert "working" in str(exc_info.value)


def test_input_required_can_return_to_working():
    assert validate_transition(TaskState.INPUT_REQUIRED, TaskState.WORKING) is True