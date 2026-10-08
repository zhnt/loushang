"""Consumer-owned close permission; AppService owns membership and settlement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from loushang.appserver.managed_mux import ManagedMuxCreatedV1
from loushang.appserver.managed_mux_close import (
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)

if TYPE_CHECKING:
    from .continuity import ApplicationContinuityRecordV1


class ManagedMuxCloseUseV1(str, Enum):
    ADMIT = "admit"
    OBSERVE = "observe"
    SETTLE = "settle"


class ManagedMuxCloseAdmissionV1(Protocol):
    """Retained original permission for one short local commit or observation.

    ADMIT rejects stop. SETTLE permits only previously admitted exact-instance
    debt, including after stop. OBSERVE grants no mutation or cleanup. The
    consumer fences instance replacement and verifies purpose-specific tokens;
    AppService releases the physical fence before waiting for Session cleanup.
    Failed acquire/close retains this original owner for cleanup, never a copy.
    """

    async def acquire(self) -> None: ...

    def check_closure(self, creation: ManagedMuxCreatedV1, previous: ManagedMuxCloseStateV1 | None) -> str:
        """Validate and return immutable operation origin, not serving identity.

        Continuing an unaccepted old intent requires the consumer's original
        startup proof and current live admission. Old pending still requires
        startup recovery unless this exact manager admitted it in this run.
        """
        ...

    async def close(self) -> None: ...


class ManagedMuxCloseRecoveryAdmissionV1(Protocol):
    """Original startup fence: prove prior clean stop before any Session IO.

    ADMIT checks the current startup instance and previous cleanly_stopped
    facts. SETTLE admits only this same instance's accepted recovery, including
    after stop_requested. Neither permits crossing an instance replacement.
    None also requires admission: missing continuity must not erase confirmed
    managed history. A genuinely empty initial startup needs no predecessor.
    Factories are effect-free; the attempt retains this owner before acquire.
    """

    async def acquire(self) -> None: ...

    def check_record(self, record: ApplicationContinuityRecordV1 | None) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ManagedMuxCloseRecoveryBindingV1:
    prepare: Callable[[ApplicationContinuityRecordV1 | None, ManagedMuxCloseUseV1], ManagedMuxCloseRecoveryAdmissionV1] = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(self.prepare):
            raise TypeError("invalid managed Mux close recovery factory")


@dataclass(frozen=True, slots=True)
class ManagedMuxCloseBindingV1:
    prepare: Callable[[ManagedMuxCloseV1, ManagedMuxCloseUseV1], ManagedMuxCloseAdmissionV1] = field(repr=False)
    recovery: ManagedMuxCloseRecoveryBindingV1 | None = field(default=None, repr=False, kw_only=True)

    def __post_init__(self) -> None:
        if not callable(self.prepare):
            raise TypeError("invalid managed Mux close admission factory")
        if self.recovery is not None and type(self.recovery) is not ManagedMuxCloseRecoveryBindingV1:
            raise TypeError("invalid managed Mux close recovery activation")
