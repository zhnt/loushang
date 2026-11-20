"""Execution wire operation names."""

from enum import Enum


class ExecutionOperationV1(str, Enum):
    SUBMIT = "execution/submit"
    GET = "execution/get"
    GOAL_PROGRESS = "execution/goal_progress"
    GOAL_START = "execution/goal_start"
    INTERACTIVE_GOAL_CREATE = "session/interactive_goal_create"
    INTERACTIVE_GOAL_STATUS = "session/interactive_goal_status"
    INTERACTIVE_GOAL_COMMAND = "session/interactive_goal_command"
    INTERACTIVE_GOAL_RECOVERY = "session/interactive_goal_recovery"
    INTERACTIVE_GOAL_REVIEW = "session/interactive_goal_review"
    INTERACTIVE_GOAL_REVIEW_SUBMIT = "session/interactive_goal_review_submit"
    FIND = "execution/find_submission"
    INTERRUPT = "execution/interrupt"
    SNAPSHOT = "execution/snapshot"
    EVENTS = "execution/read_events"
    RESOURCE = "session/resource"
    RESUME_INPUT_LOOKUP = "session/lookup_resume_input"


class ExecutionStatusV1(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.INTERRUPTED}


class InterruptModeV1(str, Enum):
    LEGACY_TURN_ONLY = "legacy_turn_only"
    WHOLE_EXECUTION = "whole_execution"
