"""Opt-in, transport-neutral managed Mux values; no deployment authority here."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MUX_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,511}\Z")
_AUTHORITY = re.compile(r"[A-Za-z0-9._~-]{1,1024}\Z")


def _match(value: str, pattern: re.Pattern[str]) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError("invalid managed Mux value")


@dataclass(frozen=True, slots=True)
class ManagedMuxCreateV1:
    service_id: str
    instance_id: str
    operation_id: str
    name: str
    authority: str = field(repr=False)

    def __post_init__(self) -> None:
        _match(self.service_id, _HEX64)
        _match(self.instance_id, _HEX32)
        _match(self.operation_id, _HEX32)
        _match(self.name, _NAME)
        _match(self.authority, _AUTHORITY)


@dataclass(frozen=True, slots=True)
class ManagedMuxCreatedV1:
    """Immutable creation fact, not a claim the Mux is still open or online.

    The instance is the original committing instance. Reconciliation after
    restart needs fresh authority but returns this same historical result.
    """

    operation_id: str
    instance_id: str
    name: str
    mux_space_id: str

    def __post_init__(self) -> None:
        _match(self.operation_id, _HEX32)
        _match(self.instance_id, _HEX32)
        _match(self.name, _NAME)
        _match(self.mux_space_id, _MUX_ID)


class ManagedMuxCreationClientV1(Protocol):
    """Optional capability; does not extend the legacy AppClient algebra."""

    async def create_managed_mux(self, request: ManagedMuxCreateV1) -> ManagedMuxCreatedV1: ...
