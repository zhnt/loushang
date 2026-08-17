"""Private long-lived process containment planning over Sandbox backends."""

from __future__ import annotations

import asyncio
import inspect

from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.workspace.exec import ExecRequest
from loushang.harness.workspace.process import ProcessLaunchRequest
from loushang.harness.workspace.process.local import ProcessContainmentPlan

from .exec_backend import SandboxScopeRequestFactory
from .registry import SandboxBackendResolution
from .service import SandboxDiagnosticSink
from .types import (
    SandboxDiagnostic,
    SandboxScopeRequest,
    SandboxSettings,
    SandboxStatus,
    SandboxUnavailableError,
)


class HostedProcessContainmentPlanner:
    """Track private process plans until Host or Sandbox fallback closes them."""

    def __init__(
        self,
        *,
        settings: SandboxSettings,
        resolution: SandboxBackendResolution | None,
        scope_request_factory: SandboxScopeRequestFactory | None,
        diagnostic_sink: SandboxDiagnosticSink | None = None,
    ) -> None:
        self._settings = settings
        self._resolution = resolution
        self._scope_request_factory = scope_request_factory
        self._diagnostic_sink = diagnostic_sink
        self._status_override: SandboxStatus | None = None
        self._diagnostic_emitted = False
        self._plans: set[ProcessContainmentPlan] = set()
        self._state = "open"
        self._lock = asyncio.Lock()

    def status_override(self) -> SandboxStatus | None:
        return self._status_override

    async def plan(
        self,
        request: ProcessLaunchRequest,
        *,
        execution_profile: EffectiveExecutionProfile | None,
    ) -> ProcessContainmentPlan:
        async with self._lock:
            if self._state != "open":
                raise RuntimeError("hosted-process containment planner is closed")
        if not self._settings.enabled or self._resolution is None:
            return await self._track(ProcessContainmentPlan(request))
        backend = self._resolution.backend
        if backend is None:
            return await self._track(ProcessContainmentPlan(request))
        if execution_profile is None:
            return await self._degrade_or_raise(
                request,
                "hosted process has no effective execution profile",
                backend_id=backend.backend_id,
            )
        factory = self._scope_request_factory
        if factory is None:
            return await self._degrade_or_raise(
                request,
                "hosted process sandbox has no scope request factory",
                backend_id=backend.backend_id,
            )
        exec_request = ExecRequest(
            command=request.command,
            cwd=request.cwd,
            effective_environment=request.effective_environment,
            execution_profile=execution_profile,
        )
        try:
            scope = factory(exec_request)
            if not isinstance(scope, SandboxScopeRequest):
                raise TypeError(
                    "sandbox scope request factory must return SandboxScopeRequest"
                )
            provider = getattr(backend, "_plan_hosted_process", None)
            if not callable(provider):
                raise SandboxUnavailableError(
                    f"sandbox backend {backend.backend_id!r} cannot host live processes"
                )
            plan = provider(request, scope)
            if inspect.isawaitable(plan):
                plan = await plan
            if not isinstance(plan, ProcessContainmentPlan):
                raise TypeError(
                    "hosted process containment provider must return "
                    "ProcessContainmentPlan"
                )
        except Exception as exc:
            return await self._degrade_or_raise(
                request,
                str(exc) or type(exc).__name__,
                backend_id=backend.backend_id,
                cause=exc,
            )
        return await self._track(plan)

    async def close(self) -> None:
        async with self._lock:
            if self._state == "closed":
                return
            self._state = "closing"
            plans = tuple(self._plans)
        results = await asyncio.gather(
            *(plan.close() for plan in plans),
            return_exceptions=True,
        )
        async with self._lock:
            self._plans.clear()
            self._state = "closed"
        errors = tuple(
            result for result in results if isinstance(result, BaseException)
        )
        if errors:
            raise RuntimeError("hosted-process containment cleanup failed") from errors[
                0
            ]

    async def _track(
        self,
        plan: ProcessContainmentPlan,
    ) -> ProcessContainmentPlan:
        tracked: ProcessContainmentPlan | None = None

        async def close_tracked() -> None:
            try:
                await plan.close()
            finally:
                assert tracked is not None
                async with self._lock:
                    self._plans.discard(tracked)

        tracked = ProcessContainmentPlan(plan.request, close=close_tracked)
        async with self._lock:
            if self._state == "open":
                self._plans.add(tracked)
                return tracked
        await tracked.close()
        raise RuntimeError("hosted-process containment planner closed during planning")

    async def _degrade_or_raise(
        self,
        request: ProcessLaunchRequest,
        reason: str,
        *,
        backend_id: str,
        cause: Exception | None = None,
    ) -> ProcessContainmentPlan:
        message = f"hosted-process sandbox unavailable: {reason}"
        if self._settings.requirement == "required":
            error = SandboxUnavailableError(message)
            if cause is not None:
                raise error from cause
            raise error
        self._status_override = SandboxStatus(
            state="degraded",
            backend_id=backend_id,
            reason=message,
        )
        if not self._diagnostic_emitted and self._diagnostic_sink is not None:
            self._diagnostic_emitted = True
            self._diagnostic_sink(
                SandboxDiagnostic(
                    code="sandbox_process_hosting_degraded",
                    message=message,
                    backend_id=backend_id,
                )
            )
        return await self._track(ProcessContainmentPlan(request))


__all__: list[str] = []
