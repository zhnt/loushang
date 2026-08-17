from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    constrain_execution_profile,
)
from loushang.harness.environment import HostEnvironmentProbe
from loushang.harness.tools.process_hosting import (
    ProcessExecutionScope,
    ScopeBoundProcessLauncher,
)
from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecService,
    ExecUpdateCallback,
)
from loushang.harness.workspace.process import AuthorizedProcessLauncher
from loushang.harness.workspace.process.host import ProcessHost

from .binding import SandboxExecutionBinding, bind_sandbox_execution
from .exec_backend import SandboxScopeRequestFactory
from .process import HostedProcessContainmentPlanner
from .registry import SandboxBackendRegistry
from .service import SandboxDiagnosticSink
from .types import SandboxSettings, SandboxStatus


@dataclass(slots=True)
class SandboxExecutionRuntime:
    """Session-owned sandbox binding and its effective execution service."""

    binding: SandboxExecutionBinding
    exec_service: ExecService
    _process_host: ProcessHost
    _process_containment: HostedProcessContainmentPlanner
    _closed: bool = False
    _process_launcher: ScopeBoundProcessLauncher | None = None
    _close_task: asyncio.Task[None] | None = None

    def status(self) -> SandboxStatus:
        override = self._process_containment.status_override()
        if override is not None:
            return override
        return self.binding.status()

    def bind_process_launcher(
        self,
        scope: ProcessExecutionScope,
    ) -> AuthorizedProcessLauncher:
        if self._closed or self._close_task is not None:
            raise RuntimeError("sandbox execution runtime is closing")
        if self._process_launcher is not None:
            raise RuntimeError("process launcher is already bound for this runtime")
        launcher = ScopeBoundProcessLauncher(
            scope=scope,
            host=self._process_host,
            containment=self._process_containment,
        )
        self._process_launcher = launcher
        return launcher

    async def close(self) -> None:
        task = self._close_task
        if task is None:
            task = asyncio.create_task(
                self._close_owned(),
                name="harness-sandbox-execution-runtime-close",
            )
            self._close_task = task
        await _await_close_before_propagating_cancellation(task)

    async def _close_owned(self) -> None:
        errors: list[BaseException] = []
        for close in (
            self._process_host.close,
            self._process_containment.close,
            self.binding.close,
        ):
            try:
                await close()
            except BaseException as exc:
                errors.append(exc)
        self._closed = True
        if not errors:
            return
        primary = errors[0]
        for secondary in errors[1:]:
            primary.add_note(f"later cleanup failure: {secondary}")
        raise primary


def bind_sandbox_execution_runtime(
    *,
    base_exec_service: ExecService,
    settings: SandboxSettings = SandboxSettings(),
    scope_request_factory: SandboxScopeRequestFactory | None = None,
    registry: SandboxBackendRegistry | None = None,
    environment_probe: HostEnvironmentProbe | None = None,
    diagnostic_sink: SandboxDiagnosticSink | None = None,
    execution_profile: EffectiveExecutionProfile | None = None,
) -> SandboxExecutionRuntime:
    """Wrap one existing execution service without creating a bypass path."""

    base_profile = getattr(base_exec_service, "execution_profile", None)
    if base_profile is not None and not isinstance(
        base_profile,
        EffectiveExecutionProfile,
    ):
        raise TypeError("base execution profile must be an EffectiveExecutionProfile")
    effective_profile = (
        constrain_execution_profile(base_profile, execution_profile)
        if base_profile is not None and execution_profile is not None
        else execution_profile or base_profile
    )
    local_backend = _ExecServiceBackend(base_exec_service)
    binding = bind_sandbox_execution(
        settings=settings,
        registry=registry,
        environment_probe=environment_probe,
        local_backend=local_backend,
        scope_request_factory=scope_request_factory,
        diagnostic_sink=diagnostic_sink,
    )
    process_containment = HostedProcessContainmentPlanner(
        settings=settings,
        resolution=binding.resolution,
        scope_request_factory=scope_request_factory,
        diagnostic_sink=diagnostic_sink,
    )
    return SandboxExecutionRuntime(
        binding=binding,
        exec_service=(
            base_exec_service
            if binding.status().state == "disabled" and effective_profile is None
            else ExecService(
                backend=binding.exec_backend,
                execution_profile=effective_profile,
            )
        ),
        _process_host=ProcessHost(),
        _process_containment=process_containment,
    )


class _ExecServiceBackend:
    """Adapt an injected ExecService to the common materialized backend shape."""

    def __init__(self, service: ExecService) -> None:
        self._service = service

    async def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ):
        return await self._service.execute(
            request,
            signal=signal,
            on_update=on_update,
        )


async def _await_close_before_propagating_cancellation(
    task: asyncio.Task[None],
) -> None:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = exc
        except BaseException as exc:
            if cancellation is not None:
                raise cancellation from exc
            raise
    if cancellation is not None:
        raise cancellation


__all__ = ["SandboxExecutionRuntime", "bind_sandbox_execution_runtime"]
