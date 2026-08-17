from __future__ import annotations

import inspect
from typing import Protocol

from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecResult,
    ExecUpdateCallback,
)

from .protocols import SandboxService
from .types import SandboxScopeRequest


class SandboxScopeRequestFactory(Protocol):
    def __call__(self, request: ExecRequest) -> SandboxScopeRequest: ...


class SandboxExecBackend:
    """Open and close one sandbox scope around each materialized execution."""

    def __init__(
        self,
        *,
        service: SandboxService,
        scope_request_factory: SandboxScopeRequestFactory,
    ) -> None:
        self._service = service
        self._scope_request_factory = scope_request_factory

    async def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> ExecResult:
        if request.effective_environment is None:
            raise ValueError("sandbox backend requires a materialized ExecRequest")
        scope_request = self._scope_request_factory(request)
        if not isinstance(scope_request, SandboxScopeRequest):
            raise TypeError(
                "sandbox scope request factory must return SandboxScopeRequest"
            )
        scope = await self._service.open_scope(scope_request)
        try:
            result = scope(request, signal=signal, on_update=on_update)
            if inspect.isawaitable(result):
                result = await result
            return result
        finally:
            await scope.close()


__all__ = ["SandboxExecBackend", "SandboxScopeRequestFactory"]
