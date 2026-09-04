"""Immutable public contracts for Product-neutral local Hosting."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from .errors import HostingFailureCategory, InvalidHostingRequestError

HOSTING_CONTRACT_VERSION = "loushang.hosting/v1"
_MAX_OPAQUE_ID_LENGTH = 128


class ProcessStdinMode(str, Enum):
    """Explicit child stdin attachment; ambient inheritance is not available."""

    PIPE = "pipe"
    CLOSED = "closed"


class ProcessStdoutMode(str, Enum):
    """Explicit child stdout attachment; semantic stdout is never inspected."""

    PIPE = "pipe"
    DISCARD = "discard"


class ProcessStderrMode(str, Enum):
    """Explicit child stderr handling owned by the process lease."""

    PIPE = "pipe"
    CAPTURE_TAIL = "capture_tail"
    DISCARD = "discard"


@dataclass(frozen=True, slots=True)
class ProcessStreamSpec:
    """Complete stdio intent with no implicit parent-stream inheritance."""

    stdin: ProcessStdinMode
    stdout: ProcessStdoutMode
    stderr: ProcessStderrMode

    def __post_init__(self) -> None:
        _require_enum("streams.stdin", self.stdin, ProcessStdinMode)
        _require_enum("streams.stdout", self.stdout, ProcessStdoutMode)
        _require_enum("streams.stderr", self.stderr, ProcessStderrMode)


@dataclass(frozen=True, slots=True)
class ProcessLaunchRequest:
    """One shell-free launch request with complete effective environment."""

    argv: tuple[str, ...]
    cwd: str
    effective_environment: tuple[tuple[str, str], ...] = field(repr=False)
    streams: ProcessStreamSpec

    def __post_init__(self) -> None:
        argv = _argv_tuple(self.argv)
        cwd = _absolute_path(self.cwd)
        environment = _environment_tuple(self.effective_environment)
        if not isinstance(self.streams, ProcessStreamSpec):
            raise InvalidHostingRequestError("streams", "must be a ProcessStreamSpec")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "effective_environment", environment)


@dataclass(frozen=True, slots=True)
class ChildSessionRequest:
    """Request an inherited peer endpoint joined to one process lifetime."""

    process: ProcessLaunchRequest

    def __post_init__(self) -> None:
        if not isinstance(self.process, ProcessLaunchRequest):
            raise InvalidHostingRequestError(
                "process", "must be a ProcessLaunchRequest"
            )


@dataclass(frozen=True, slots=True)
class ProcessExit:
    """Raw local process exit fact; it carries no domain-success meaning."""

    return_code: int

    def __post_init__(self) -> None:
        if type(self.return_code) is not int:
            raise TypeError("return_code must be an integer")


@dataclass(frozen=True, slots=True)
class ProcessStderrTail:
    """Bounded stderr suffix retained by an owning Process Lease."""

    content: bytes = field(default=b"", repr=False)
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes")
        if not isinstance(self.truncated, bool):
            raise TypeError("truncated must be a boolean")


class HostingComponent(str, Enum):
    CONTRACT = "contract"
    PROCESS = "process"
    ENDPOINT = "endpoint"
    SESSION = "session"
    PLATFORM = "platform"


class HostingLifecycleTransition(str, Enum):
    CAPACITY_RESERVED = "capacity_reserved"
    PREPARING = "preparing"
    SPAWNING = "spawning"
    PUBLISHED = "published"
    EXITED = "exited"
    CLEANING = "cleaning"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HostingObservation:
    """Bounded mechanism fact without arbitrary payload or security claims."""

    component: HostingComponent
    transition: HostingLifecycleTransition
    owner_id: str
    session_id: str | None = None
    backend_id: str | None = None
    failure: HostingFailureCategory | None = None

    def __post_init__(self) -> None:
        _require_enum("component", self.component, HostingComponent)
        _require_enum("transition", self.transition, HostingLifecycleTransition)
        _opaque_id("owner_id", self.owner_id)
        _optional_opaque_id("session_id", self.session_id)
        _optional_opaque_id("backend_id", self.backend_id)
        if self.transition is HostingLifecycleTransition.FAILED:
            if not isinstance(self.failure, HostingFailureCategory):
                raise ValueError("failed observations require a failure category")
        elif self.failure is not None:
            raise ValueError("only failed observations may carry a failure category")


@runtime_checkable
class HostingObservationSink(Protocol):
    """Optional non-owning sink; implementations must not control lifecycle."""

    def observe(self, observation: HostingObservation) -> None: ...


@runtime_checkable
class LaunchPreparationLease(Protocol):
    """Caller-owned prepared launch material and its cleanup capability."""

    @property
    def request(self) -> ProcessLaunchRequest: ...

    async def verify_current(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class LaunchPreparationPort(Protocol):
    """Required consumer port for one-shot preparation before local spawn."""

    async def prepare(
        self, request: ProcessLaunchRequest
    ) -> LaunchPreparationLease: ...


@runtime_checkable
class ProcessLease(Protocol):
    """Exclusive capability for one Hosting-owned process lifetime."""

    @property
    def lease_id(self) -> str: ...

    async def read_stdout(self, max_bytes: int) -> bytes: ...

    async def read_stderr(self, max_bytes: int) -> bytes: ...

    async def write_stdin(self, data: bytes) -> None: ...

    async def close_stdin(self) -> None: ...

    async def wait(self) -> ProcessExit: ...

    async def terminate(self) -> ProcessExit: ...

    async def close(self) -> None: ...

    def stderr_tail(self) -> ProcessStderrTail: ...


@runtime_checkable
class ProcessHostingPort(Protocol):
    """Provided port for a bounded, attached local process."""

    async def start(
        self,
        request: ProcessLaunchRequest,
        preparation: LaunchPreparationPort,
    ) -> ProcessLease: ...

    async def close(self) -> None: ...


@runtime_checkable
class HostByteEndpoint(Protocol):
    """Host side of one inherited, protocol-neutral byte endpoint."""

    async def read(self, max_bytes: int) -> bytes: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ChildSessionLease(Protocol):
    """Atomic aggregate of one process lease and one host byte endpoint."""

    @property
    def session_id(self) -> str: ...

    @property
    def process(self) -> ProcessLease: ...

    @property
    def endpoint(self) -> HostByteEndpoint: ...

    async def close(self) -> None: ...


@runtime_checkable
class ChildSessionHostingPort(Protocol):
    """Provided port publishing process and endpoint together or neither."""

    async def start(
        self,
        request: ChildSessionRequest,
        preparation: LaunchPreparationPort,
    ) -> ChildSessionLease: ...

    async def close(self) -> None: ...


def _argv_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise InvalidHostingRequestError(
            "argv", "must be a sequence, not a shell string"
        )
    argv = tuple(value)
    if not argv:
        raise InvalidHostingRequestError("argv", "must not be empty")
    for item in argv:
        if not isinstance(item, str):
            raise InvalidHostingRequestError("argv", "must contain only strings")
        if "\0" in item:
            raise InvalidHostingRequestError("argv", "must not contain NUL")
    if not argv[0]:
        raise InvalidHostingRequestError("argv[0]", "must not be empty")
    if not Path(argv[0]).is_absolute():
        raise InvalidHostingRequestError(
            "argv[0]", "must be an absolute executable path"
        )
    return argv


def _absolute_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidHostingRequestError("cwd", "must be non-empty text")
    if "\0" in value:
        raise InvalidHostingRequestError("cwd", "must not contain NUL")
    if not Path(value).is_absolute():
        raise InvalidHostingRequestError("cwd", "must be an absolute path")
    return value


def _environment_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise InvalidHostingRequestError(
            "effective_environment", "must contain string pairs"
        )
    result: list[tuple[str, str]] = []
    folded_names: set[str] = set()
    for item in value:
        if isinstance(item, (str, bytes)) or not isinstance(item, Iterable):
            raise InvalidHostingRequestError(
                "effective_environment", "must contain string pairs"
            )
        pair = tuple(item)
        if len(pair) != 2 or not all(isinstance(part, str) for part in pair):
            raise InvalidHostingRequestError(
                "effective_environment", "must contain string pairs"
            )
        name, environment_value = pair
        if not name or "=" in name or "\0" in name:
            raise InvalidHostingRequestError(
                "effective_environment", "contains an invalid variable name"
            )
        if "\0" in environment_value:
            raise InvalidHostingRequestError(
                "effective_environment", "contains a NUL variable value"
            )
        folded_name = name.casefold()
        if folded_name in folded_names:
            raise InvalidHostingRequestError(
                "effective_environment", "contains duplicate variable names"
            )
        folded_names.add(folded_name)
        result.append((name, environment_value))
    return tuple(result)


def _require_enum(field_name: str, value: object, enum_type: type[Enum]) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _opaque_id(field_name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_OPAQUE_ID_LENGTH
        or "\0" in value
    ):
        raise ValueError(
            f"{field_name} must be 1-{_MAX_OPAQUE_ID_LENGTH} NUL-free characters"
        )


def _optional_opaque_id(field_name: str, value: object) -> None:
    if value is not None:
        _opaque_id(field_name, value)


__all__ = [
    "HOSTING_CONTRACT_VERSION",
    "ChildSessionHostingPort",
    "ChildSessionLease",
    "ChildSessionRequest",
    "HostByteEndpoint",
    "HostingComponent",
    "HostingLifecycleTransition",
    "HostingObservation",
    "HostingObservationSink",
    "LaunchPreparationLease",
    "LaunchPreparationPort",
    "ProcessExit",
    "ProcessHostingPort",
    "ProcessLaunchRequest",
    "ProcessLease",
    "ProcessStderrMode",
    "ProcessStderrTail",
    "ProcessStdinMode",
    "ProcessStdoutMode",
    "ProcessStreamSpec",
]
