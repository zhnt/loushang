"""Consumer-supplied admission for optional managed Mux mutation.

The consumer, not AppService, owns namespace reservations and instance fencing.
An admission holds that permission through commit settlement; a boolean check
before an await is not sufficient. No global registry transaction spans RPC.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from loushang.appserver.managed_mux import ManagedMuxCreatedV1, ManagedMuxCreateV1

from .continuity import require_application_id
from .managed_mux_close import ManagedMuxCloseBindingV1


class ManagedMuxAdmissionV1(Protocol):
    """Original owner, constructed without IO and retained before acquire.

    acquire proves the exact service, instance, operation and reserved name,
    rejecting stopped/revoked requests. Once admitted, stop/replacement must
    join this operation before retiring its authority. close releases only
    this admission, is retryable on the original owner, and never stops a
    service. Failure/cancellation of acquire still requires close.
    """

    async def acquire(self) -> None: ...

    def check_creation(self, previous: ManagedMuxCreatedV1 | None) -> None:
        """Reject missing/conflicting local history against known durable facts.

        Called after acquire and before returning a replay or committing a new
        creation; it neither releases permission nor writes an external result.
        """
        ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ManagedMuxServiceBindingV1:
    application_id: str
    service_id: str
    instance_id: str
    prepare: Callable[[ManagedMuxCreateV1], ManagedMuxAdmissionV1] = field(repr=False)
    closing: ManagedMuxCloseBindingV1 | None = field(default=None, repr=False, kw_only=True)

    def __post_init__(self) -> None:
        require_application_id(self.application_id)
        ManagedMuxCreateV1(self.service_id, self.instance_id, "0" * 32, "check", "check")
        if not callable(self.prepare):
            raise TypeError("invalid managed Mux admission factory")
        if self.closing is not None and type(self.closing) is not ManagedMuxCloseBindingV1:
            raise TypeError("invalid managed Mux close binding")
