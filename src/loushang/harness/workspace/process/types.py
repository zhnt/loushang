"""Public, Product-neutral contracts for hosted workspace processes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a string sequence, not a shell string")
    try:
        normalized: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a string sequence") from exc
    if not normalized or any(
        not isinstance(item, str) or not item for item in normalized
    ):
        raise ValueError(f"{field_name} must be a non-empty string sequence")
    return tuple(item for item in normalized if isinstance(item, str))


def _environment_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        raise TypeError("effective_environment must contain string pairs")
    try:
        items: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError("effective_environment must contain string pairs") from exc
    normalized: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, str) or not isinstance(item, Iterable):
            raise TypeError("effective_environment must contain string pairs")
        pair: tuple[object, ...] = tuple(item)
        if (
            len(pair) != 2
            or not isinstance(pair[0], str)
            or not pair[0]
            or not isinstance(pair[1], str)
        ):
            raise TypeError("effective_environment must contain string pairs")
        normalized.append((pair[0], pair[1]))
    names = tuple(name for name, _ in normalized)
    if len(set(names)) != len(names):
        raise ValueError("effective_environment names must be unique")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ProcessLaunchRequest:
    """One fully materialized, shell-free process launch request."""

    command: tuple[str, ...]
    cwd: str
    effective_environment: tuple[tuple[str, str], ...] = field(repr=False)

    def __post_init__(self) -> None:
        command = _string_tuple(self.command, field_name="command")
        requested_cwd = Path(self.cwd).expanduser()
        if not requested_cwd.is_absolute():
            raise ValueError("process cwd must be an absolute path")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "cwd", str(requested_cwd.resolve()))
        object.__setattr__(
            self,
            "effective_environment",
            _environment_tuple(self.effective_environment),
        )


@dataclass(frozen=True, slots=True)
class ProcessExit:
    return_code: int


@dataclass(frozen=True, slots=True)
class ProcessStderrTail:
    content: bytes = b""
    truncated: bool = False


class ProcessHandle(Protocol):
    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes: ...

    async def write_stdin(self, data: bytes) -> None: ...

    async def close_stdin(self) -> None: ...

    async def wait(self) -> ProcessExit: ...

    async def terminate(self) -> ProcessExit: ...

    async def close(self) -> None: ...

    def stderr_tail(self) -> ProcessStderrTail: ...


class AuthorizedProcessLauncher(Protocol):
    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle: ...


__all__ = [
    "AuthorizedProcessLauncher",
    "ProcessExit",
    "ProcessHandle",
    "ProcessLaunchRequest",
    "ProcessStderrTail",
]
