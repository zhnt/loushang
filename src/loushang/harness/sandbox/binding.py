from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.environment import (
    HostEnvironmentProbe,
    LocalHostEnvironmentProbe,
)
from loushang.harness.workspace.exec import ExecBackend, LocalExecBackend

from .backends import default_sandbox_backend_registry
from .exec_backend import SandboxExecBackend, SandboxScopeRequestFactory
from .protocols import SandboxService
from .registry import (
    SandboxBackendRegistry,
    SandboxBackendResolution,
)
from .service import LocalSandboxService, SandboxDiagnosticSink
from .types import (
    SandboxDiagnostic,
    SandboxSettings,
    SandboxStatus,
    SandboxUnavailableError,
)


@dataclass(slots=True)
class SandboxExecutionBinding:
    exec_backend: ExecBackend
    service: SandboxService | None
    resolution: SandboxBackendResolution | None
    _status: SandboxStatus

    def status(self) -> SandboxStatus:
        if self.service is not None:
            return self.service.status()
        return self._status

    async def close(self) -> None:
        if self.service is not None:
            await self.service.close()


def bind_sandbox_execution(
    *,
    settings: SandboxSettings = SandboxSettings(),
    registry: SandboxBackendRegistry | None = None,
    environment_probe: HostEnvironmentProbe | None = None,
    local_backend: ExecBackend | None = None,
    scope_request_factory: SandboxScopeRequestFactory | None = None,
    diagnostic_sink: SandboxDiagnosticSink | None = None,
) -> SandboxExecutionBinding:
    resolved_local_backend = (
        local_backend if local_backend is not None else LocalExecBackend()
    )
    if not settings.enabled:
        return SandboxExecutionBinding(
            exec_backend=resolved_local_backend,
            service=None,
            resolution=None,
            _status=SandboxStatus(state="disabled"),
        )
    if scope_request_factory is None:
        raise ValueError("enabled sandboxing requires a scope request factory")

    resolved_registry = registry or default_sandbox_backend_registry(
        local_backend=resolved_local_backend
    )
    resolved_probe = environment_probe or LocalHostEnvironmentProbe()
    resolution = resolved_registry.resolve(resolved_probe.detect())
    backend = resolution.backend
    backend_status = resolution.selected_status
    if backend is None or backend_status is None:
        reason = resolution.unavailable_reason()
        if settings.requirement == "required":
            raise SandboxUnavailableError(reason)
        status = SandboxStatus(state="degraded", reason=reason)
        if diagnostic_sink is not None:
            diagnostic_sink(
                SandboxDiagnostic(
                    code="sandbox_unavailable",
                    message=reason,
                )
            )
        return SandboxExecutionBinding(
            exec_backend=resolved_local_backend,
            service=None,
            resolution=resolution,
            _status=status,
        )

    service = LocalSandboxService(
        backend=backend,
        backend_status=backend_status,
        requirement=settings.requirement,
        local_backend=resolved_local_backend,
        diagnostic_sink=diagnostic_sink,
    )
    return SandboxExecutionBinding(
        exec_backend=SandboxExecBackend(
            service=service,
            scope_request_factory=scope_request_factory,
        ),
        service=service,
        resolution=resolution,
        _status=service.status(),
    )


__all__ = ["SandboxExecutionBinding", "bind_sandbox_execution"]
