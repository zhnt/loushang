"""Product-neutral structural contracts for delegated command execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class RuntimeExecResult(Protocol):
    """Result facts consumed across the Runtime boundary."""

    @property
    def exit_code(self) -> int: ...

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...

    @property
    def timed_out(self) -> bool: ...

    @property
    def cancelled(self) -> bool: ...


RuntimeExecUpdateCallback = Callable[..., Awaitable[None] | None]


__all__ = ["RuntimeExecResult", "RuntimeExecUpdateCallback"]
