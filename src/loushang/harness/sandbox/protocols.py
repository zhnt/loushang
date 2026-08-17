from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from loushang.harness.environment import HostEnvironment
from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecResult,
    ExecUpdateCallback,
)

from .types import (
    SandboxBackendStatus,
    SandboxScopeDescriptor,
    SandboxScopeRequest,
    SandboxStatus,
)


class SandboxScope(Protocol):
    @property
    def descriptor(self) -> SandboxScopeDescriptor: ...

    def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> Awaitable[ExecResult] | ExecResult: ...

    async def close(self) -> None: ...


class SandboxBackend(Protocol):
    backend_id: str

    def probe(self, environment: HostEnvironment) -> SandboxBackendStatus: ...

    async def open_scope(
        self,
        request: SandboxScopeRequest,
    ) -> SandboxScope: ...

    async def close(self) -> None: ...


class SandboxService(Protocol):
    def status(self) -> SandboxStatus: ...

    async def open_scope(
        self,
        request: SandboxScopeRequest,
    ) -> SandboxScope: ...

    async def close(self) -> None: ...


__all__ = ["SandboxBackend", "SandboxScope", "SandboxService"]
