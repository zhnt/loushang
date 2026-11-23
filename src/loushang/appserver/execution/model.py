"""Values for the optional execution profile; the legacy v1 algebra is unchanged."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256

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
from ._validation import _counter
from ._validation import _identifier as _identifier
from .goal_model import (
    MAX_GOAL_BATCHES,
    ExecutionGoalBatchV1,
    ExecutionGoalCancellationStatusV1,
    ExecutionGoalProgressV1,
    ExecutionGoalStatusV1,
    ExecutionGoalValidityV1,
    ExecutionGoalWorkStatusV1,
    GoalRecoveryHistoryReasonV1,
    GoalRecoveryUnavailableReasonV1,
    InteractiveGoalActionV1,
    InteractiveGoalCommandStatusV1,
    InteractiveGoalCommandV1,
    InteractiveGoalCommandViewV1,
    InteractiveGoalObservedActionV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewDecisionV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
    is_review_path,
    validate_goal_fields,
)
from .operation import ExecutionOperationV1, ExecutionStatusV1, InterruptModeV1
from .resources import SessionResourceQueryV1, SessionResourceResultV1
from .session_commands import (
    SessionCommandCatalogV1,
    SessionCommandInvocationV1,
    SessionCommandResultV1,
    _bounded_text,
)


@dataclass(frozen=True, slots=True)
class ResourceRefV1:
    id: str
    sha256: str

    def __post_init__(self) -> None:
        _identifier(self.id)
        if type(self.sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", self.sha256) is None:
            raise ValueError("invalid resource content digest")


@dataclass(frozen=True, slots=True)
class ExecutionInputV1:
    text: str
    resource_refs: tuple[ResourceRefV1, ...] = ()
    command: SessionCommandInvocationV1 | None = None

    def __post_init__(self) -> None:
        if (type(self.resource_refs) is not tuple or len(self.resource_refs) > 4
                or any(type(ref) is not ResourceRefV1 for ref in self.resource_refs)
                or len({ref.id for ref in self.resource_refs}) != len(self.resource_refs)):
            raise ValueError("invalid execution resource references")
        if self.command is not None:
            if type(self.command) is not SessionCommandInvocationV1 or self.text != "" or self.resource_refs:
                raise ValueError("invalid command execution input")
            return
        if self.text != "" or not self.resource_refs:
            TurnTextV1("validation", 1, "validation", self.text)

    def digest(self) -> str:
        payload = [self.text, [[ref.id, ref.sha256] for ref in self.resource_refs]]
        if self.command is not None:
            payload = ["command", self.command.name, self.command.args]
        return sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionRequestV1:
    execution_id: str
    text: str
    resource_refs: tuple[ResourceRefV1, ...] = ()
    submission_id: str | None = None
    command: SessionCommandInvocationV1 | None = None

    def __post_init__(self) -> None:
        _identifier(self.execution_id)
        if self.submission_id is not None:
            _identifier(self.submission_id)
        ExecutionInputV1(self.text, self.resource_refs, self.command)


@dataclass(frozen=True, slots=True)
class ExecutionOutcomeV1:
    """Product result, separate from the legacy operation's response behavior."""

    status: ExecutionStatusV1
    error_code: str | None = None
    legacy_result: AckV1 | AppFailureV1 = field(default_factory=AckV1)
    command_result: SessionCommandResultV1 | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if type(self.status) is not ExecutionStatusV1 or not self.status.terminal:
            raise ValueError("execution outcome must be terminal")
        if (self.status is ExecutionStatusV1.FAILED) != (self.error_code is not None):
            raise ValueError("only failed execution has an error code")
        if self.error_code is not None:
            _identifier(self.error_code)
        if type(self.legacy_result) not in (AckV1, AppFailureV1):
            raise TypeError("invalid legacy execution result")
        if self.command_result is not None and type(self.command_result) is not SessionCommandResultV1:
            raise TypeError("invalid command execution result")


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
    resource_query: SessionResourceQueryV1 | None = None
    resource_refs: tuple[ResourceRefV1, ...] = ()
    command: SessionCommandInvocationV1 | None = None
    command_prefix: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.request_id)
        _identifier(self.expected_instance_id)
        if type(self.operation) is not ExecutionOperationV1 or type(self.control) is not (
            SessionSnapshotRequestV1
        ):
            raise TypeError("invalid execution call")
        submission = self.operation in {
            ExecutionOperationV1.SUBMIT, ExecutionOperationV1.FIND, ExecutionOperationV1.GOAL_START,
            ExecutionOperationV1.COMMAND_SUBMIT,
        }
        execution = self.operation in {
            ExecutionOperationV1.GET, ExecutionOperationV1.INTERRUPT, ExecutionOperationV1.GOAL_PROGRESS,
            ExecutionOperationV1.COMMAND_RESULT,
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
            ExecutionInputV1(self.text, self.resource_refs)
        elif self.resource_refs:
            raise ValueError("unexpected resource references")
        if (type(self.resource_query) is SessionResourceQueryV1) != (self.operation is ExecutionOperationV1.RESOURCE):
            raise ValueError("unexpected resource query")
        if (self.command is not None) != (self.operation in {ExecutionOperationV1.COMMAND_SUBMIT, ExecutionOperationV1.COMMAND_READ}):
            raise ValueError("unexpected Session command")
        if self.command is not None:
            ExecutionInputV1("", command=self.command)
        if (self.command_prefix is not None) != (self.operation is ExecutionOperationV1.COMMAND_CATALOG):
            raise ValueError("unexpected command prefix")
        if self.command_prefix is not None:
            _bounded_text(self.command_prefix, 512)
        validate_goal_fields(self)

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
    | SessionCommandCatalogV1 | SessionCommandResultV1
    | SessionResourceResultV1 | ResumeInputLookupResultV1 | ExecutionGoalProgressV1 | InteractiveGoalViewV1 | InteractiveGoalReviewV1 | InteractiveGoalRecoveryV1
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
            ExecutionInterruptResultV1, SessionResourceResultV1,
            SessionCommandCatalogV1, SessionCommandResultV1,
            ResumeInputLookupResultV1, ExecutionGoalProgressV1, InteractiveGoalViewV1, InteractiveGoalReviewV1, InteractiveGoalRecoveryV1,
        ):
            raise TypeError("invalid execution response")

__all__ = [
    "MAX_GOAL_BATCHES", "ExecutionGoalBatchV1", "ExecutionGoalCancellationStatusV1",
    "ExecutionGoalProgressV1", "ExecutionGoalStatusV1", "ExecutionGoalValidityV1",
    "ExecutionGoalWorkStatusV1", "GoalRecoveryHistoryReasonV1", "GoalRecoveryUnavailableReasonV1",
    "InteractiveGoalActionV1", "InteractiveGoalCommandStatusV1", "InteractiveGoalCommandV1",
    "InteractiveGoalCommandViewV1", "InteractiveGoalObservedActionV1", "InteractiveGoalRecoveryV1",
    "InteractiveGoalReviewDecisionV1", "InteractiveGoalReviewSubmissionV1", "InteractiveGoalReviewV1",
    "InteractiveGoalViewV1", "is_review_path", "ExecutionStatusV1",
    "InterruptModeV1", "ExecutionRequestV1", "ExecutionOutcomeV1", "ExecutionInputV1", "ResourceRefV1",
    "ExecutionObservationV1", "ExecutionStateV1", "ExecutionSourceSnapshotV1",
    "ExecutionContentEventV1", "ExecutionUpdateV1", "ExecutionErrorCodeV1",
    "ExecutionServiceErrorV1", "ExecutionRecordV1", "ExecutionSessionViewV1",
    "ExecutionSessionSnapshotV1", "ExecutionInterruptDispositionV1", "ExecutionInterruptResultV1",
    "ExecutionCallV1", "ExecutionEventsV1", "ExecutionFailureV1",
    "ExecutionResponseV1", "ExecutionOperationV1", "ExecutionResultV1",
]
