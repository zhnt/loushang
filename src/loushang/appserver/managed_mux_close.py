"""Optional exact-target close values, separate from creation permission.

A state is a historical fact supplied by an authenticated application, not an
authority token or permission to release a name. The registry consumer must
check the serving instance and CAS the original reference independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .managed_mux import _AUTHORITY, _HEX32, _HEX64, _MUX_ID, _NAME, _match


class ManagedMuxClosePhaseV1(str, Enum):
    CLEANUP_PENDING = "cleanup_pending"
    CLOSED = "closed"


def _target(operation: str, creation: str, name: str, mux_id: str) -> None:
    _match(operation, _HEX32)
    _match(creation, _HEX32)
    _match(name, _NAME)
    _match(mux_id, _MUX_ID)
    if operation == creation:
        raise ValueError("invalid managed Mux close identity")


@dataclass(frozen=True, slots=True)
class ManagedMuxCloseV1:
    """Current-instance permission request with a frozen, non-name-only target."""

    service_id: str
    instance_id: str
    operation_id: str
    creation_operation_id: str
    name: str
    mux_space_id: str
    authority: str = field(repr=False)

    def __post_init__(self) -> None:
        _match(self.service_id, _HEX64)
        _match(self.instance_id, _HEX32)
        _target(self.operation_id, self.creation_operation_id, self.name, self.mux_space_id)
        _match(self.authority, _AUTHORITY)


@dataclass(frozen=True, slots=True)
class ManagedMuxCloseStateV1:
    """Immutable origin identity and one of two durable settlement phases.

instance_id is the operation origin (first issuing instance), not evidence of
which instance executed it. Only actual cleanup permits pending to become closed; neither
an absent Mux nor transport EOF constitutes this result. No authority is stored.
"""

    operation_id: str
    instance_id: str
    creation_operation_id: str
    name: str
    mux_space_id: str
    phase: ManagedMuxClosePhaseV1

    def __post_init__(self) -> None:
        _match(self.instance_id, _HEX32)
        _target(self.operation_id, self.creation_operation_id, self.name, self.mux_space_id)
        if type(self.phase) is not ManagedMuxClosePhaseV1:
            raise ValueError("invalid managed Mux close phase")


class ManagedMuxCloseClientV1(Protocol):
    """Optional close and read-only result access, never a permit issuer."""

    async def close_managed_mux(self, request: ManagedMuxCloseV1) -> ManagedMuxCloseStateV1: ...

    async def read_managed_mux_close(self, request: ManagedMuxCloseV1) -> ManagedMuxCloseStateV1 | None: ...
