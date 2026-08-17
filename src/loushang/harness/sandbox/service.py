from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from loushang.harness.workspace.exec import (
    ExecBackend,
    ExecRequest,
    ExecResult,
    ExecUpdateCallback,
)

from .protocols import SandboxBackend, SandboxScope
from .types import (
    SandboxBackendStatus,
    SandboxDiagnostic,
    SandboxRequirement,
    SandboxScopeDescriptor,
    SandboxScopeRequest,
    SandboxStatus,
    SandboxUnavailableError,
)

SandboxDiagnosticSink = Callable[[SandboxDiagnostic], None]


class LocalSandboxService:
    """Own one selected backend and its per-execution sandbox scopes."""

    def __init__(
        self,
        *,
        backend: SandboxBackend,
        backend_status: SandboxBackendStatus,
        requirement: SandboxRequirement,
        local_backend: ExecBackend,
        diagnostic_sink: SandboxDiagnosticSink | None = None,
    ) -> None:
        if backend_status.state != "available":
            raise ValueError("sandbox service requires an available backend")
        if backend_status.backend_id != backend.backend_id:
            raise ValueError("sandbox service backend status identity mismatch")
        if requirement not in {"best_effort", "required"}:
            raise ValueError(f"unsupported sandbox requirement: {requirement!r}")
        self._backend = backend
        self._requirement = requirement
        self._local_backend = local_backend
        self._diagnostic_sink = diagnostic_sink
        self._status = SandboxStatus(
            state="enabled",
            backend_id=backend.backend_id,
            enforced_capabilities=backend_status.enforced_capabilities,
        )
        self._scopes: set[_TrackedSandboxScope] = set()
        self._closed = False
        self._lifecycle_lock = asyncio.Lock()
        self._degraded_diagnostic_emitted = False

    def status(self) -> SandboxStatus:
        return self._status

    async def open_scope(
        self,
        request: SandboxScopeRequest,
    ) -> SandboxScope:
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("sandbox service is closed")
            try:
                scope = await self._backend.open_scope(request)
            except Exception as error:
                return self._handle_scope_failure(str(error), cause=error)

            if scope.descriptor.state == "degraded":
                if self._requirement == "required":
                    await scope.close()
                    raise SandboxUnavailableError(
                        scope.descriptor.reason
                        or f"sandbox backend {self._backend.backend_id!r} degraded"
                    )
                self._record_degraded(
                    scope.descriptor.reason
                    or f"sandbox backend {self._backend.backend_id!r} degraded"
                )

            tracked = _TrackedSandboxScope(scope, self._discard_scope)
            self._scopes.add(tracked)
            return tracked

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            first_error: BaseException | None = None
            for scope in tuple(self._scopes):
                try:
                    await scope.close()
                except BaseException as error:
                    if first_error is None:
                        first_error = error
            try:
                await self._backend.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
            if first_error is None:
                return
            raise first_error

    def _handle_scope_failure(
        self,
        reason: str,
        *,
        cause: Exception,
    ) -> SandboxScope:
        message = reason or f"sandbox backend {self._backend.backend_id!r} failed"
        if self._requirement == "required":
            raise SandboxUnavailableError(message) from cause
        self._record_degraded(message)
        scope = _LocalFallbackScope(
            local_backend=self._local_backend,
            descriptor=SandboxScopeDescriptor(
                state="degraded",
                backend_id=self._backend.backend_id,
                reason=message,
            ),
        )
        tracked = _TrackedSandboxScope(scope, self._discard_scope)
        self._scopes.add(tracked)
        return tracked

    def _record_degraded(self, reason: str) -> None:
        self._status = SandboxStatus(
            state="degraded",
            backend_id=self._backend.backend_id,
            reason=reason,
        )
        if self._degraded_diagnostic_emitted:
            return
        self._degraded_diagnostic_emitted = True
        if self._diagnostic_sink is not None:
            self._diagnostic_sink(
                SandboxDiagnostic(
                    code="sandbox_degraded",
                    message=reason,
                    backend_id=self._backend.backend_id,
                )
            )

    def _discard_scope(self, scope: _TrackedSandboxScope) -> None:
        self._scopes.discard(scope)


class _TrackedSandboxScope:
    def __init__(
        self,
        delegate: SandboxScope,
        on_close: Callable[["_TrackedSandboxScope"], None],
    ) -> None:
        self._delegate = delegate
        self._on_close = on_close
        self._closed = False

    @property
    def descriptor(self) -> SandboxScopeDescriptor:
        return self._delegate.descriptor

    def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> Awaitable[ExecResult] | ExecResult:
        return self._delegate(request, signal=signal, on_update=on_update)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._delegate.close()
        finally:
            self._on_close(self)


class _LocalFallbackScope:
    def __init__(
        self,
        *,
        local_backend: ExecBackend,
        descriptor: SandboxScopeDescriptor,
    ) -> None:
        self._local_backend = local_backend
        self._descriptor = descriptor

    @property
    def descriptor(self) -> SandboxScopeDescriptor:
        return self._descriptor

    async def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> ExecResult:
        result = self._local_backend(
            request,
            signal=signal,
            on_update=on_update,
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    async def close(self) -> None:
        return None


__all__ = ["LocalSandboxService", "SandboxDiagnosticSink"]
