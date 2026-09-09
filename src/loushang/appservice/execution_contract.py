"""Product execution values and private AppService snapshot proof objects."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.appserver.execution.model import (
    ExecutionContentEventV1 as ExecutionContentEventV1,
)
from loushang.appserver.execution.model import (
    ExecutionObservationV1 as ExecutionObservationV1,
)
from loushang.appserver.execution.model import (
    ExecutionOutcomeV1 as ExecutionOutcomeV1,
)
from loushang.appserver.execution.model import (
    ExecutionRequestV1 as ExecutionRequestV1,
)
from loushang.appserver.execution.model import (
    ExecutionSourceSnapshotV1 as ExecutionSourceSnapshotV1,
)
from loushang.appserver.execution.model import (
    ExecutionStateV1 as ExecutionStateV1,
)
from loushang.appserver.execution.model import (
    ExecutionStatusV1 as ExecutionStatusV1,
)
from loushang.appserver.execution.model import (
    ExecutionUpdateV1 as ExecutionUpdateV1,
)
from loushang.appserver.execution.model import (
    InterruptModeV1 as InterruptModeV1,
)
from loushang.appserver.execution.model import (
    _counter as _counter,
)
from loushang.appserver.execution.model import (
    _identifier as _identifier,
)
from loushang.appserver.protocol import SessionIdentityV1


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
