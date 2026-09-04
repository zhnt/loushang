"""Private platform seam for the Hosting process-lifetime owner.

The seam intentionally exposes no PID, native handle, or registration API.
Concrete POSIX and Windows adapters belong to H2; H1 exercises this contract
with deterministic fakes only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .contracts import ProcessLaunchRequest


class _ProcessTransport(Protocol):
    """One backend-owned process and its explicitly requested byte streams."""

    @property
    def return_code(self) -> int | None: ...

    async def read_stdout(self, max_bytes: int) -> bytes: ...

    async def read_stderr(self, max_bytes: int) -> bytes: ...

    async def write_stdin(self, data: bytes) -> None: ...

    async def close_stdin(self) -> None: ...

    async def wait(self) -> int: ...


class _ProcessInheritance(Protocol):
    """Private single-use H3 resource passed only by Child Session Host."""

    @property
    def backend_id(self) -> str: ...

    def claim(self, *, backend_id: str) -> tuple[int, ...]: ...

    def mark_transferred(self) -> None: ...

    async def close(self) -> None: ...


class _ProcessBackend(Protocol):
    """Private exact-platform process operations selected by composition."""

    @property
    def backend_id(self) -> str: ...

    async def spawn(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None = None,
    ) -> _ProcessTransport:
        """Create one process and attach ownership before cancellation can land.

        Once an operating-system process exists, ``on_spawn`` must be called
        synchronously before the backend performs another cancellation point.
        Returning a different transport, calling twice with different objects,
        or returning without attachment is a backend contract violation.
        """

    def tree_exited(self, process: _ProcessTransport) -> bool: ...

    async def wait_tree(self, process: _ProcessTransport) -> None: ...

    async def terminate_tree(self, process: _ProcessTransport) -> None: ...

    async def kill_tree(self, process: _ProcessTransport) -> None: ...

    async def close_process_handles(self, process: _ProcessTransport) -> None: ...

    async def close_backend(self) -> None:
        """Release backend-owned executor or platform support resources."""


__all__: list[str] = []
