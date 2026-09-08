"""Optional, in-process Product execution values; not a v1 wire extension."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from loushang.appserver.protocol import (
    AckV1,
    AppFailureV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionSnapshotV1,
    TurnTextV1,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,127}\Z")


def _identifier(value: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("invalid execution identifier")


def _counter(value: object) -> None:
    if type(value) is not int or value < 0:
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
        if self.draft and self.observation.status is not ExecutionStatusV1.RUNNING:
            raise ValueError("draft must belong to an active source execution")
        final_cursor = self.observation.final_cursor
        if final_cursor is not None and self.source.cursor < final_cursor:
            raise ValueError("snapshot precedes its completion watermark")


@dataclass(frozen=True, slots=True)
class ExecutionBindingViewV1:
    """Application-side view; binding token is private and never serialized.

    Reading the view also validates caller authority. Revision increments on
    every view change. Q is retained separately from displayed terminal state.
    """

    binding: object
    identity: SessionIdentityV1
    revision: int
    quiescent: ExecutionObservationV1
    active: ExecutionStateV1 | None = None
    latest_terminal: ExecutionStateV1 | None = None

    def __post_init__(self) -> None:
        _counter(self.revision)
        if type(self.identity) is not SessionIdentityV1:
            raise TypeError("invalid execution Session identity")
        if type(self.quiescent) is not ExecutionObservationV1 or (
            self.quiescent.status is ExecutionStatusV1.RUNNING
        ):
            raise ValueError("binding baseline must be quiescent")
        if self.active is not None and (
            type(self.active) is not ExecutionStateV1 or self.active.status.terminal
        ):
            raise ValueError("invalid active execution")
        if self.latest_terminal is not None and (
            type(self.latest_terminal) is not ExecutionStateV1
            or not self.latest_terminal.status.terminal
        ):
            raise ValueError("invalid latest terminal execution")


@dataclass(frozen=True, slots=True)
class CompositeExecutionSnapshotV1:
    source: ExecutionSourceSnapshotV1
    executions: ExecutionBindingViewV1


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
