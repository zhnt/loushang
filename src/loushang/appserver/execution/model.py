"""Values for the optional execution profile; the legacy v1 algebra is unchanged."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, get_args

from ..protocol import (
    AckV1,
    AppFailureV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnTextV1,
)
from ..resume_model import ResumeInputLookupQueryV1, ResumeInputLookupResultV1

_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,127}\Z")
MAX_GOAL_BATCHES = 16


def _identifier(value: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("invalid execution identifier")


def _counter(value: object) -> None:
    if type(value) is not int or not 0 <= value <= (1 << 53) - 1:
        raise ValueError("invalid execution counter")


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


@dataclass(frozen=True, slots=True)
class ExecutionRequestV1:
    execution_id: str
    text: str

    def __post_init__(self) -> None:
        _identifier(self.execution_id)
        # Preserve the existing text bounds without extending its wire shape.
        TurnTextV1("validation", 1, "validation", self.text)


@dataclass(frozen=True, slots=True)
class ExecutionOutcomeV1:
    """Product result, separate from the legacy operation's response behavior."""

    status: ExecutionStatusV1
    error_code: str | None = None
    legacy_result: AckV1 | AppFailureV1 = field(default_factory=AckV1)

    def __post_init__(self) -> None:
        if type(self.status) is not ExecutionStatusV1 or not self.status.terminal:
            raise ValueError("execution outcome must be terminal")
        if (self.status is ExecutionStatusV1.FAILED) != (self.error_code is not None):
            raise ValueError("only failed execution has an error code")
        if self.error_code is not None:
            _identifier(self.error_code)
        if type(self.legacy_result) not in (AckV1, AppFailureV1):
            raise TypeError("invalid legacy execution result")


@dataclass(frozen=True, slots=True)
class ExecutionObservationV1:
    """Source fact scoped to one Product binding; empty means initially idle."""

    execution_id: str | None = None
    status: ExecutionStatusV1 | None = None
    final_cursor: int | None = None

    def __post_init__(self) -> None:
        if self.execution_id is None:
            if self.status is not None or self.final_cursor is not None:
                raise ValueError("idle source has no execution outcome")
            return
        _identifier(self.execution_id)
        if type(self.status) is not ExecutionStatusV1 or self.status is (
            ExecutionStatusV1.ACCEPTED
        ):
            raise ValueError("source observation requires Product entry")
        if self.status.terminal:
            _counter(self.final_cursor)
        elif self.final_cursor is not None:
            raise ValueError("active source has no final cursor")


@dataclass(frozen=True, slots=True)
class ExecutionStateV1:
    """One invocation state; revisions are meaningful only for this identity."""

    execution_id: str
    status: ExecutionStatusV1
    revision: int
    interrupt_requested: bool = False
    outcome: ExecutionOutcomeV1 | None = None

    def __post_init__(self) -> None:
        _identifier(self.execution_id)
        _counter(self.revision)
        if type(self.status) is not ExecutionStatusV1:
            raise TypeError("invalid execution status")
        if type(self.interrupt_requested) is not bool:
            raise TypeError("invalid interruption state")
        if self.status.terminal:
            if type(self.outcome) is not ExecutionOutcomeV1 or (
                self.outcome.status is not self.status
            ):
                raise ValueError("terminal execution needs matching outcome")
        elif self.outcome is not None:
            raise ValueError("active execution cannot have an outcome")


@dataclass(frozen=True, slots=True)
class ExecutionSourceSnapshotV1:
    """Coherent bounded Product content and observation, captured at one cut.

    Draft is a replacement projection, never an append instruction. A final
    transcript message includes no duplicate draft. Omission is explicit.
    """

    source: SessionSnapshotV1
    observation: ExecutionObservationV1
    draft: str = ""
    truncated: bool = False

    def __post_init__(self) -> None:
        if type(self.source) is not SessionSnapshotV1 or type(self.observation) is not (
            ExecutionObservationV1
        ):
            raise TypeError("invalid execution source snapshot")
        if type(self.draft) is not str or len(self.draft) > 16_384:
            raise ValueError("invalid bounded draft")
        if type(self.truncated) is not bool:
            raise TypeError("invalid source omission flag")
        if sum(len(record.text) for record in self.source.records) > 65_536:
            raise ValueError("execution source transcript exceeds its frame budget")
        if self.draft and self.observation.status is not ExecutionStatusV1.RUNNING:
            raise ValueError("draft must belong to an active source execution")
        final_cursor = self.observation.final_cursor
        if final_cursor is not None and self.source.cursor < final_cursor:
            raise ValueError("snapshot precedes its completion watermark")


@dataclass(frozen=True, slots=True)
class ExecutionContentEventV1:
    """Source event envelope: preserves the original v1 event and its cursor."""

    source: SessionEventV1
    execution_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.source) is not SessionEventV1:
            raise TypeError("invalid source content event")
        if self.execution_id is not None:
            _identifier(self.execution_id)


@dataclass(frozen=True, slots=True)
class ExecutionUpdateV1:
    """AppService metadata stream position, separate from Product content."""

    revision: int
    execution: ExecutionStateV1

    def __post_init__(self) -> None:
        _counter(self.revision)
        if self.revision == 0 or type(self.execution) is not ExecutionStateV1:
            raise ValueError("invalid execution update")


class ExecutionErrorCodeV1(str, Enum):
    INSTANCE_CHANGED = "service_instance_changed"
    SUBMISSION_CONFLICT = "submission_conflict"
    LEDGER_FULL = "submission_ledger_full"
    BUSY = "execution_busy"
    NOT_RETAINED = "execution_not_retained"
    UNSUPPORTED = "execution_unsupported"


class ExecutionServiceErrorV1(RuntimeError):
    def __init__(self, code: ExecutionErrorCodeV1) -> None:
        if type(code) is not ExecutionErrorCodeV1:
            raise TypeError("invalid execution error")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class ExecutionRecordV1:
    service_instance_id: str
    identity: SessionIdentityV1
    submission_id: str | None
    state: ExecutionStateV1

    def __post_init__(self) -> None:
        _identifier(self.service_instance_id)
        if self.submission_id is not None:
            _identifier(self.submission_id)
        if type(self.identity) is not SessionIdentityV1 or type(self.state) is not (
            ExecutionStateV1
        ):
            raise TypeError("invalid execution record")


@dataclass(frozen=True, slots=True)
class ExecutionSessionViewV1:
    identity: SessionIdentityV1
    revision: int
    quiescent: ExecutionObservationV1
    active: ExecutionStateV1 | None = None
    latest_terminal: ExecutionStateV1 | None = None

    def __post_init__(self) -> None:
        _counter(self.revision)
        if type(self.identity) is not SessionIdentityV1:
            raise TypeError("invalid execution session identity")
        if type(self.quiescent) is not ExecutionObservationV1 or (
            self.quiescent.status is ExecutionStatusV1.RUNNING
        ):
            raise ValueError("invalid quiescent execution observation")
        if self.active is not None and (
            type(self.active) is not ExecutionStateV1 or self.active.status.terminal
        ):
            raise ValueError("invalid active execution")
        if self.latest_terminal is not None and (
            type(self.latest_terminal) is not ExecutionStateV1
            or not self.latest_terminal.status.terminal
        ):
            raise ValueError("invalid latest execution")


@dataclass(frozen=True, slots=True)
class ExecutionSessionSnapshotV1:
    service_instance_id: str
    source: ExecutionSourceSnapshotV1
    executions: ExecutionSessionViewV1
    supports_goal_progress: bool = False
    supports_goal_start: bool = False
    supports_interactive_goal: bool = False
    supports_interactive_goal_commands: bool = False
    supports_interactive_goal_recovery: bool = False

    def __post_init__(self) -> None:
        _identifier(self.service_instance_id)
        if type(self.source) is not ExecutionSourceSnapshotV1 or type(self.executions) is not (
            ExecutionSessionViewV1
        ) or self.source.source.identity != self.executions.identity:
            raise ValueError("invalid execution composite snapshot")
        if any(type(flag) is not bool for flag in (
            self.supports_goal_progress, self.supports_goal_start, self.supports_interactive_goal,
            self.supports_interactive_goal_commands, self.supports_interactive_goal_recovery,
        )):
            raise TypeError("invalid Goal capability")
        if self.supports_interactive_goal_commands and not self.supports_interactive_goal:
            raise ValueError("Goal commands require interactive Goal support")


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
    RESUME_INPUT_LOOKUP = "session/lookup_resume_input"


class ExecutionInterruptDispositionV1(str, Enum):
    REQUESTED = "requested"
    ALREADY_TERMINAL = "already_terminal"


@dataclass(frozen=True, slots=True)
class ExecutionInterruptResultV1:
    record: ExecutionRecordV1
    disposition: ExecutionInterruptDispositionV1

    def __post_init__(self) -> None:
        if type(self.record) is not ExecutionRecordV1 or type(self.disposition) is not ExecutionInterruptDispositionV1:
            raise TypeError("invalid execution interrupt result")
        if self.disposition is ExecutionInterruptDispositionV1.ALREADY_TERMINAL:
            if not self.record.state.status.terminal:
                raise ValueError("execution has not reached terminal state")
        elif not self.record.state.interrupt_requested:
            raise ValueError("execution interrupt was not requested")


@dataclass(frozen=True, slots=True)
class ExecutionCallV1:
    request_id: str
    operation: ExecutionOperationV1
    control: SessionSnapshotRequestV1
    expected_instance_id: str
    submission_id: str | None = None
    execution_id: str | None = None
    text: str | None = None
    resume_query: ResumeInputLookupQueryV1 | None = None
    include_goal_batches: bool = False
    goal_target: str | None = None
    goal_command: InteractiveGoalCommandV1 | None = None
    review_goal_id: str | None = None
    review_submission: InteractiveGoalReviewSubmissionV1 | None = None

    def __post_init__(self) -> None:
        _identifier(self.request_id)
        _identifier(self.expected_instance_id)
        if type(self.operation) is not ExecutionOperationV1 or type(self.control) is not (
            SessionSnapshotRequestV1
        ):
            raise TypeError("invalid execution call")
        submission = self.operation in {
            ExecutionOperationV1.SUBMIT, ExecutionOperationV1.FIND, ExecutionOperationV1.GOAL_START,
        }
        execution = self.operation in {
            ExecutionOperationV1.GET, ExecutionOperationV1.INTERRUPT, ExecutionOperationV1.GOAL_PROGRESS,
        }
        text = self.operation is ExecutionOperationV1.SUBMIT
        if type(self.include_goal_batches) is not bool or (
            self.include_goal_batches and self.operation is not ExecutionOperationV1.GOAL_PROGRESS
        ):
            raise ValueError("unexpected Goal batch opt-in")
        if (self.resume_query is not None) != (self.operation is ExecutionOperationV1.RESUME_INPUT_LOOKUP):
            raise ValueError("unexpected Resume lookup query")
        if self.resume_query is not None and type(self.resume_query) is not ResumeInputLookupQueryV1:
            raise TypeError("invalid Resume lookup query")
        if (self.submission_id is not None) != submission or (
            self.execution_id is not None
        ) != execution or (self.text is not None) != text:
            raise ValueError("unexpected execution call fields")
        if self.submission_id is not None:
            _identifier(self.submission_id)
        if self.execution_id is not None:
            _identifier(self.execution_id)
        if self.text is not None:
            ExecutionRequestV1("validation", self.text)
        self._validate_goal_target()
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

    def _validate_goal_target(self) -> None:
        create = self.operation is ExecutionOperationV1.INTERACTIVE_GOAL_CREATE
        if (self.goal_target is not None) != create:
            raise ValueError("unexpected interactive Goal target")
        if self.goal_target is not None and (
            type(self.goal_target) is not str or not self.goal_target.strip()
            or len(self.goal_target.encode("utf-8")) > 16_384
        ):
            raise ValueError("invalid interactive Goal target")


@dataclass(frozen=True, slots=True)
class ExecutionEventsV1:
    events: tuple[ExecutionContentEventV1 | ExecutionUpdateV1, ...]

    def __post_init__(self) -> None:
        if type(self.events) is not tuple or len(self.events) > 256 or any(
            type(event) not in (ExecutionContentEventV1, ExecutionUpdateV1) for event in self.events
        ):
            raise ValueError("invalid execution event batch")


@dataclass(frozen=True, slots=True)
class ExecutionFailureV1:
    code: ExecutionErrorCodeV1

    def __post_init__(self) -> None:
        if type(self.code) is not ExecutionErrorCodeV1:
            raise TypeError("invalid execution failure")


ExecutionResultV1 = (
    ExecutionRecordV1 | ExecutionSessionSnapshotV1 | ExecutionEventsV1
    | ExecutionInterruptResultV1 | ExecutionFailureV1 | AppFailureV1 | None
    | ResumeInputLookupResultV1 | ExecutionGoalProgressV1 | InteractiveGoalViewV1 | InteractiveGoalReviewV1 | InteractiveGoalRecoveryV1
)


@dataclass(frozen=True, slots=True)
class ExecutionResponseV1:
    request_id: str
    result: ExecutionResultV1

    def __post_init__(self) -> None:
        _identifier(self.request_id)
        if self.result is not None and type(self.result) not in (
            ExecutionRecordV1, ExecutionSessionSnapshotV1, ExecutionEventsV1,
            ExecutionFailureV1, AppFailureV1,
            ExecutionInterruptResultV1,
            ResumeInputLookupResultV1, ExecutionGoalProgressV1, InteractiveGoalViewV1, InteractiveGoalReviewV1, InteractiveGoalRecoveryV1,
        ):
            raise TypeError("invalid execution response")
