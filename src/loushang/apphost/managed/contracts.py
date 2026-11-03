"""Pure values for the optional Linux managed-deployment boundary.

These values neither admit filesystem paths nor authorize processes/connections.
An owner must validate native facts and CAS transitions under its lifecycle fence.
No facade import, environment read, native IO or Product construction occurs here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256
from pathlib import PurePosixPath

MANAGED_DEPLOYMENT_VERSION = "loushang.managed/v1"
MANAGED_LOCAL_PROFILE = "local-managed/v1"
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MUX_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")


class ManagedContractError(ValueError):
    """A bounded error that never includes caller-controlled fields."""

    def __init__(self) -> None:
        super().__init__("invalid_managed_contract")


def require_mux_name(value: str) -> str:
    """Validate a global display name; it must never become a raw path segment."""
    _match(value, _MUX_NAME)
    return value


def require_service_alias(value: str) -> str:
    """A separate namespace of display names, never an ambiguous service ID."""
    require_mux_name(value)
    if _HEX64.fullmatch(value.lower()) is not None:
        raise ManagedContractError()
    return value


@dataclass(frozen=True, slots=True)
class ManagedNamespaceV1:
    """Injected local identity; home is lexical, not yet filesystem-admitted."""

    platform_home: str = field(repr=False)
    user_id: int
    machine_id: str

    def __post_init__(self) -> None:
        _path(self.platform_home)
        if self.platform_home == "/":
            raise ManagedContractError()
        if type(self.user_id) is not int or not 0 <= self.user_id < 2**32:
            raise ManagedContractError()
        _match(self.machine_id, _HEX32)

    @property
    def namespace_key(self) -> str:
        return _digest(
            "namespace/v1", self.platform_home, str(self.user_id), self.machine_id
        )


@dataclass(frozen=True, slots=True)
class ManagedServiceKeyV1:
    """One Product/workspace/profile reuse key, independent of Mux or instance."""

    product_id: str
    workspace: str = field(repr=False)
    profile: str = MANAGED_LOCAL_PROFILE

    def __post_init__(self) -> None:
        _match(self.product_id, _ID)
        _path(self.workspace)
        if type(self.profile) is not str or self.profile != MANAGED_LOCAL_PROFILE:
            raise ManagedContractError()

    @property
    def service_id(self) -> str:
        return _digest("service/v1", self.product_id, self.workspace, self.profile)


@dataclass(frozen=True, slots=True)
class ManagedInstanceRefV1:
    """A stale-detectable lookup reference, never an authority token."""

    namespace_key: str
    service_id: str
    instance_id: str

    def __post_init__(self) -> None:
        _match(self.namespace_key, _HEX64)
        _match(self.service_id, _HEX64)
        _match(self.instance_id, _HEX32)


class ManagedHandoffPhaseV1(str, Enum):
    PROVISIONAL = "provisional"
    COMMITTED = "committed"
    ABORTING = "aborting"


@dataclass(frozen=True, slots=True)
class ManagedHandoffV1:
    """An immutable transition model, not an in-memory replacement for CAS.

    Only the child may propose commit. An owner persists a returned next value if
    the complete previous value still matches under the stable lifecycle fence.
    Missing acknowledgement never changes this model to ABORTING automatically.
    """

    instance: ManagedInstanceRefV1
    attempt_id: str
    phase: ManagedHandoffPhaseV1 = ManagedHandoffPhaseV1.PROVISIONAL
    stop_requested: bool = False

    def __post_init__(self) -> None:
        if type(self.instance) is not ManagedInstanceRefV1:
            raise ManagedContractError()
        _match(self.attempt_id, _HEX32)
        if type(self.phase) is not ManagedHandoffPhaseV1:
            raise ManagedContractError()
        if type(self.stop_requested) is not bool:
            raise ManagedContractError()

    def request_stop(self) -> ManagedHandoffV1:
        return replace(self, stop_requested=True)

    def commit(self) -> ManagedHandoffV1:
        if self.stop_requested or self.phase is ManagedHandoffPhaseV1.ABORTING:
            raise ManagedContractError()
        return replace(self, phase=ManagedHandoffPhaseV1.COMMITTED)

    def abort(self) -> ManagedHandoffV1:
        if self.phase is ManagedHandoffPhaseV1.COMMITTED:
            raise ManagedContractError()
        return replace(self, phase=ManagedHandoffPhaseV1.ABORTING)


@dataclass(frozen=True, slots=True)
class ManagedStopEvidenceV1:
    """Separate native exit and consumer cleanup facts for one exact instance.

    Constructed only by the observing owner, not decoded as trusted peer input.
    No PID/socket absence inference or mixing facts from different epochs is allowed.
    """

    instance: ManagedInstanceRefV1
    process_exited: bool
    application_cleanup_completed: bool
    process_scope_settled: bool

    def __post_init__(self) -> None:
        if type(self.instance) is not ManagedInstanceRefV1:
            raise ManagedContractError()
        if (
            type(self.process_exited) is not bool
            or type(self.application_cleanup_completed) is not bool
            or type(self.process_scope_settled) is not bool
        ):
            raise ManagedContractError()

    @property
    def cleanly_stopped(self) -> bool:
        return (
            self.process_exited
            and self.application_cleanup_completed
            and self.process_scope_settled
        )


def _match(value: str, pattern: re.Pattern[str]) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ManagedContractError()


def _path(value: str) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 4096
        or _UNSAFE_TEXT.search(value) is not None
    ):
        raise ManagedContractError()
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or value.startswith("//")
        or ".." in path.parts
        or str(path) != value
    ):
        raise ManagedContractError()


def _digest(*parts: str) -> str:
    return sha256("\0".join((MANAGED_DEPLOYMENT_VERSION, *parts)).encode()).hexdigest()


__all__ = [
    "MANAGED_DEPLOYMENT_VERSION",
    "MANAGED_LOCAL_PROFILE",
    "ManagedContractError",
    "ManagedHandoffPhaseV1",
    "ManagedHandoffV1",
    "ManagedInstanceRefV1",
    "ManagedNamespaceV1",
    "ManagedServiceKeyV1",
    "ManagedStopEvidenceV1",
    "require_mux_name",
    "require_service_alias",
]
