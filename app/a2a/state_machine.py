# app/a2a/state_machine.py

from enum import Enum


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"


# Rule book — every valid transition explicitly listed
# Anything NOT in this table = invalid = rejected
VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED:       {TaskState.WORKING, TaskState.FAILED},
    TaskState.WORKING:         {TaskState.COMPLETED, TaskState.FAILED, TaskState.INPUT_REQUIRED},
    TaskState.INPUT_REQUIRED:  {TaskState.WORKING, TaskState.FAILED},
    TaskState.COMPLETED:       set(),   # terminal — no exits
    TaskState.FAILED:          set(),   # terminal — no exits
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""
    def __init__(self, from_state: TaskState, to_state: TaskState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition: {from_state.value} → {to_state.value}"
        )


def validate_transition(from_state: TaskState, to_state: TaskState) -> bool:
    """Pure function. No side effects. Just checks the rule book."""
    return to_state in VALID_TRANSITIONS[from_state]

def assert_transition(from_state: TaskState, to_state: TaskState) -> None:
    """Raises InvalidTransitionError if transition not allowed."""
    if not validate_transition(from_state, to_state):
        raise InvalidTransitionError(from_state, to_state)