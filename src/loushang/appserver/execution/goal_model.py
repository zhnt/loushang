"""Value contracts for optional Goal observation and control."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from ._validation import _REASON_CODE, _counter, _identifier
from .operation import ExecutionOperationV1

if TYPE_CHECKING:
    from .model import ExecutionCallV1

MAX_GOAL_BATCHES = 16


ExecutionGoalStatusV1 = Literal["active", "paused", "completed", "abandoned", "failed", "superseded"]
ExecutionGoalValidityV1 = Literal["not_checked", "unknown"]


ExecutionGoalWorkStatusV1 = Literal[
    "accepted", "running", "cancelling", "completed", "failed", "cancelled", "orphaned",
]
ExecutionGoalCancellationStatusV1 = Literal[
    "not_requested", "pending", "settled", "unsupported", "failed", "unknown",
]


@dataclass(frozen=True, slots=True)
class ExecutionGoalBatchV1:
    """An observed Work batch with only bounded public facts."""

    batch_id: str
    work_status: ExecutionGoalWorkStatusV1 | None
    recording_available: bool
    cancellation_status: ExecutionGoalCancellationStatusV1 | None
    observation_unavailable: bool

    def __post_init__(self) -> None:
        _identifier(self.batch_id)
        if self.work_status is not None and self.work_status not in get_args(ExecutionGoalWorkStatusV1):
            raise ValueError("invalid Goal batch Work status")
        if self.cancellation_status is not None and self.cancellation_status not in get_args(
            ExecutionGoalCancellationStatusV1
        ):
            raise ValueError("invalid Goal batch cancellation status")
        if type(self.recording_available) is not bool or type(self.observation_unavailable) is not bool:
            raise TypeError("invalid Goal batch availability")


@dataclass(frozen=True, slots=True)
class ExecutionGoalProgressV1:
    """Compact facts from a Product's existing read-only Goal observation."""

    execution_id: str
    presence: Literal["not_started", "initializing", "present", "unavailable"]
    goal_id: str | None
    status: ExecutionGoalStatusV1 | None
    reason_code: str
    validity: ExecutionGoalValidityV1
    execution_unresolved: bool
    advances: int
    model_calls: int
    batch_count: int
    batches: tuple[ExecutionGoalBatchV1, ...]

    def __post_init__(self) -> None:
        _identifier(self.execution_id)
        if type(self.presence) is not str or self.presence not in {
            "not_started", "initializing", "present", "unavailable",
        }:
            raise ValueError("invalid Goal presence")
        self._validate_identity()
        if type(self.reason_code) is not str or _REASON_CODE.fullmatch(self.reason_code) is None:
            raise ValueError("invalid Goal reason code")
        if type(self.validity) is not str or self.validity not in {"not_checked", "unknown"}:
            raise ValueError("invalid Goal validity")
        if type(self.execution_unresolved) is not bool:
            raise TypeError("invalid Goal execution settlement")
        for value in (self.advances, self.model_calls, self.batch_count):
            _counter(value)
        self._validate_batches()

    def _validate_batches(self) -> None:
        if type(self.batches) is not tuple or len(self.batches) != min(self.batch_count, MAX_GOAL_BATCHES):
            raise ValueError("invalid Goal batch count")
        if any(type(batch) is not ExecutionGoalBatchV1 for batch in self.batches):
            raise TypeError("invalid Goal batch summary")
        if len({batch.batch_id for batch in self.batches}) != len(self.batches):
            raise ValueError("duplicate Goal batch ID")

    def _validate_identity(self) -> None:
        if self.presence == "present":
            if self.goal_id is None or self.status not in {
                "active", "paused", "completed", "abandoned", "failed", "superseded",
            }:
                raise ValueError("invalid Goal identity or status")
            _identifier(self.goal_id)
        elif self.goal_id is not None or self.status is not None:
            raise ValueError("unexpected Goal identity or status")


InteractiveGoalActionV1 = Literal["run", "step", "pause", "resume", "cancel"]
InteractiveGoalReviewDecisionV1 = Literal["accept", "reject"]
InteractiveGoalObservedActionV1 = Literal["run", "step", "pause", "resume", "cancel", "accept", "reject"]
InteractiveGoalCommandStatusV1 = Literal["running", "settling", "finished", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class InteractiveGoalCommandV1:
    goal_id: str
    command_id: str
    action: InteractiveGoalActionV1

    def __post_init__(self) -> None:
        _identifier(self.goal_id)
        _identifier(self.command_id)
        if self.action not in get_args(InteractiveGoalActionV1):
            raise ValueError("invalid interactive Goal action")


def _review_token(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid review token")


def is_review_path(value: str) -> bool:
    try:
        return (type(value) is str and len(value.encode("utf-8")) <= 1024
                and all(part not in {"", ".", ".."} for part in value.split("/"))
                and all(ch not in "\\:" and 32 <= ord(ch) != 127 for ch in value))
    except UnicodeError:
        return False


@dataclass(frozen=True, slots=True)
class InteractiveGoalReviewSubmissionV1:
    goal_id: str
    review_token: str
    command_id: str
    decision: InteractiveGoalReviewDecisionV1
    reason: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.goal_id)
        _identifier(self.command_id)
        _review_token(self.review_token)
        if self.decision == "reject":
            if type(self.reason) is not str or not self.reason.strip() or len(self.reason.encode("utf-8")) > 4096:
                raise ValueError("rejection requires specific feedback")
        elif self.decision != "accept" or self.reason is not None:
            raise ValueError("invalid review decision")

    @property
    def action(self) -> InteractiveGoalReviewDecisionV1:
        return self.decision


@dataclass(frozen=True, slots=True)
class InteractiveGoalReviewV1:
    goal_id: str
    revision: int
    epoch: int
    review_token: str
    changed_files: tuple[str, ...]
    files_truncated: bool
    check_count: int
    checks_satisfied: bool

    def __post_init__(self) -> None:
        _identifier(self.goal_id)
        _review_token(self.review_token)
        for counter in (self.revision, self.epoch, self.check_count):
            _counter(counter)
        if not self.revision or not self.epoch or self.check_count > 8:
            raise ValueError("invalid review counters")
        if (type(self.files_truncated) is not bool or type(self.checks_satisfied) is not bool
                or not self.check_count and not self.checks_satisfied):
            raise ValueError("invalid review observations")
        if (type(self.changed_files) is not tuple or len(self.changed_files) > 100
                or any(not is_review_path(path) for path in self.changed_files)
                or len(set(self.changed_files)) != len(self.changed_files)):
            raise ValueError("invalid review paths")


@dataclass(frozen=True, slots=True)
class InteractiveGoalCommandViewV1:
    command_id: str
    action: InteractiveGoalObservedActionV1
    status: InteractiveGoalCommandStatusV1

    def __post_init__(self) -> None:
        _identifier(self.command_id)
        if self.action not in get_args(InteractiveGoalObservedActionV1) or self.status not in get_args(
            InteractiveGoalCommandStatusV1
        ):
            raise ValueError("invalid interactive Goal command observation")
        if self.status == "running" and self.action in {"pause", "cancel"}:
            raise ValueError("invalid interactive Goal running action")
        if self.status == "settling" and self.action not in {"pause", "cancel"}:
            raise ValueError("invalid interactive Goal settling action")


@dataclass(frozen=True, slots=True)
class InteractiveGoalViewV1:
    availability: Literal["ready", "not_ready", "creating", "present", "historical", "cleanup_pending"]
    goal_id: str | None = None
    status: ExecutionGoalStatusV1 | None = None
    revision: int | None = None
    epoch: int | None = None
    execution_unresolved: bool | None = None
    command: InteractiveGoalCommandViewV1 | None = None
    review_available: bool = False

    def __post_init__(self) -> None:
        if self.availability not in {"ready", "not_ready", "creating", "present", "historical", "cleanup_pending"}:
            raise ValueError("invalid interactive Goal availability")
        if type(self.review_available) is not bool or (self.review_available and (
            self.availability != "present" or self.status != "paused" or self.execution_unresolved
            or self.command is not None and self.command.status in {"running", "settling", "unknown"}
        )):
            raise ValueError("invalid review availability")
        if self.availability != "present":
            if any(value is not None for value in (
                self.goal_id, self.status, self.revision, self.epoch, self.execution_unresolved, self.command,
            )):
                raise ValueError("unexpected interactive Goal facts")
            return
        if self.goal_id is None or self.status not in get_args(ExecutionGoalStatusV1):
            raise ValueError("invalid interactive Goal identity or status")
        _identifier(self.goal_id)
        for counter in (self.revision, self.epoch):
            _counter(counter)
            if counter == 0:
                raise ValueError("invalid interactive Goal revision or epoch")
        if type(self.execution_unresolved) is not bool:
            raise TypeError("invalid interactive Goal settlement")
        if self.command is not None and type(self.command) is not InteractiveGoalCommandViewV1:
            raise TypeError("invalid interactive Goal command")


GoalRecoveryHistoryReasonV1 = Literal[
    "created", "review_required", "requirements_satisfied", "user_accepted_current_result", "user_pause", "user_resume",
    "user_review", "user_cancel", "run_interrupted", "batch_limit", "execution_unresolved", "other",
]
GoalRecoveryUnavailableReasonV1 = Literal[
    "source_changed", "goal_journal_invalid", "work_log_invalid", "unsupported_goal", "ambiguous_goal",
]


@dataclass(frozen=True, slots=True)
class InteractiveGoalRecoveryV1:
    presence: Literal["absent", "present", "unavailable"]
    reason_code: Literal[GoalRecoveryHistoryReasonV1, GoalRecoveryUnavailableReasonV1, "no_goal"]
    goal_id: str | None = None
    goal_status: ExecutionGoalStatusV1 | None = None
    revision: int | None = None
    epoch: int | None = None
    batch_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    orphaned_count: int = 0
    execution_unresolved: bool = False
    read_only: bool = True

    def __post_init__(self) -> None:
        if self.read_only is not True or type(self.execution_unresolved) is not bool:
            raise ValueError("invalid recovery ownership")
        counts = (self.batch_count, self.completed_count, self.failed_count, self.cancelled_count, self.orphaned_count)
        for count in counts:
            _counter(count)
        if sum(counts[1:]) > self.batch_count or (self.orphaned_count and not self.execution_unresolved):
            raise ValueError("invalid recovery counts")
        if self.presence == "present":
            if self.goal_id is None or self.goal_status not in get_args(ExecutionGoalStatusV1):
                raise ValueError("invalid recovered Goal identity")
            _identifier(self.goal_id)
            for number in (self.revision, self.epoch):
                _counter(number)
                if number == 0:
                    raise ValueError("invalid recovered Goal revision")
            if self.reason_code not in get_args(GoalRecoveryHistoryReasonV1):
                raise ValueError("invalid recovered Goal reason")
            return
        if any(value is not None for value in (self.goal_id, self.goal_status, self.revision, self.epoch)) or any(counts):
            raise ValueError("unexpected recovered Goal facts")
        if self.presence == "absent" and self.reason_code == "no_goal" and not self.execution_unresolved:
            return
        if (self.presence == "unavailable" and self.execution_unresolved
                and self.reason_code in get_args(GoalRecoveryUnavailableReasonV1)):
            return
        raise ValueError("invalid unavailable recovery")

def validate_goal_fields(self: ExecutionCallV1) -> None:
    create = self.operation is ExecutionOperationV1.INTERACTIVE_GOAL_CREATE
    if (self.goal_target is not None) != create:
        raise ValueError("unexpected interactive Goal target")
    if self.goal_target is not None and (
        type(self.goal_target) is not str or not self.goal_target.strip()
        or len(self.goal_target.encode("utf-8")) > 16_384
    ):
        raise ValueError("invalid interactive Goal target")
    command = self.operation is ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND
    if (self.goal_command is not None) != command or (
        command and type(self.goal_command) is not InteractiveGoalCommandV1
    ):
        raise ValueError("unexpected interactive Goal command")
    if (self.review_goal_id is not None) != (self.operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW):
        raise ValueError("unexpected review identity")
    if self.review_goal_id is not None:
        _identifier(self.review_goal_id)
    if (self.review_submission is not None) != (self.operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW_SUBMIT):
        raise ValueError("unexpected review submission")
    if self.review_submission is not None and type(self.review_submission) is not InteractiveGoalReviewSubmissionV1:
        raise TypeError("invalid review submission")
