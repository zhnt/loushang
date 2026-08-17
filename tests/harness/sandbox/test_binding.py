from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.sandbox import (
    SandboxBackendRegistration,
    SandboxBackendRegistry,
    SandboxBackendStatus,
    SandboxDiagnostic,
    SandboxExecutionRuntime,
    SandboxScopeDescriptor,
    SandboxScopeRequest,
    SandboxSettings,
    SandboxStatus,
    SandboxUnavailableError,
    bind_sandbox_execution,
    bind_sandbox_execution_runtime,
)
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecResult,
    ExecService,
)
from loushang.harness.workspace.process import (
    ProcessLaunchRequest,
)


@dataclass
class _Scope:
    descriptor: SandboxScopeDescriptor
    result: ExecResult = ExecResult(exit_code=0, stdout="sandboxed")
    requests: list[ExecRequest] = field(default_factory=list)
    close_count: int = 0

    async def __call__(self, request, *, signal=None, on_update=None):
        del signal, on_update
        self.requests.append(request)
        return self.result

    async def close(self) -> None:
        self.close_count += 1


@dataclass
class _Backend:
    backend_id: str = "fake-linux"
    fail_open: bool = False
    descriptor_state: str = "enforcing"
    scopes: list[_Scope] = field(default_factory=list)
    close_count: int = 0

    def probe(self, environment: HostEnvironment) -> SandboxBackendStatus:
        assert environment.os_family == "linux"
        return SandboxBackendStatus(
            backend_id=self.backend_id,
            state="available",
            enforced_capabilities=frozenset({"filesystem"}),
        )

    async def open_scope(self, request: SandboxScopeRequest) -> _Scope:
        if self.fail_open:
            raise RuntimeError("sandbox scope failed")
        scope = _Scope(
            SandboxScopeDescriptor(
                state=self.descriptor_state,
                backend_id=self.backend_id,
                enforced_capabilities=frozenset({"filesystem"})
                if self.descriptor_state == "enforcing"
                else frozenset(),
                reason="backend degraded"
                if self.descriptor_state == "degraded"
                else None,
            )
        )
        self.scopes.append(scope)
        return scope

    async def close(self) -> None:
        self.close_count += 1


def _registry(backend: _Backend) -> SandboxBackendRegistry:
    return SandboxBackendRegistry(
        (
            SandboxBackendRegistration(
                backend_id=backend.backend_id,
                os_families=frozenset({"linux"}),
                factory=lambda: backend,
            ),
        )
    )


def _scope_request_factory(root: Path):
    def create(request: ExecRequest) -> SandboxScopeRequest:
        assert request.cwd is not None
        return SandboxScopeRequest(
            cwd=Path(request.cwd),
            readable_roots=(root,),
            writable_roots=(root,),
        )

    return create


def test_default_binding_is_disabled_and_preserves_local_backend() -> None:
    calls: list[ExecRequest] = []

    async def local_backend(request, **kwargs):
        del kwargs
        calls.append(request)
        return ExecResult(exit_code=0, stdout="local")

    binding = bind_sandbox_execution(local_backend=local_backend)
    result = asyncio.run(
        ExecService(backend=binding.exec_backend).execute(
            ExecRequest(command=("local",))
        )
    )

    assert result.stdout == "local"
    assert len(calls) == 1
    assert calls[0].effective_environment is not None
    assert binding.service is None
    assert binding.resolution is None
    assert binding.status().state == "disabled"


def test_disabled_runtime_preserves_the_injected_execution_service() -> None:
    base_service = ExecService()

    runtime = bind_sandbox_execution_runtime(base_exec_service=base_service)

    assert runtime.exec_service is base_service
    assert runtime.status().state == "disabled"
    asyncio.run(runtime.close())
    asyncio.run(runtime.close())


def test_disabled_runtime_retains_the_intersected_execution_ceiling(
    tmp_path: Path,
) -> None:
    child_root = tmp_path / "child"
    child_root.mkdir()
    base_service = ExecService(
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            writable_roots=(tmp_path,),
            network="restricted",
        )
    )

    runtime = bind_sandbox_execution_runtime(
        base_exec_service=base_service,
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(child_root,),
            writable_roots=(child_root,),
            network="allowed",
        ),
    )

    assert runtime.exec_service is not base_service
    assert runtime.exec_service.execution_profile == EffectiveExecutionProfile(
        readable_roots=(child_root,),
        writable_roots=(child_root,),
        network="restricted",
    )
    assert runtime.status().state == "disabled"


def test_disabled_runtime_binds_one_owned_local_process_launcher(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = bind_sandbox_execution_runtime(base_exec_service=ExecService())
        ceiling = EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            writable_roots=(tmp_path,),
        )
        launcher = runtime.bind_process_launcher(
            ProcessExecutionScope(execution_profile_ceiling=ceiling)
        )
        with pytest.raises(RuntimeError, match="already bound"):
            runtime.bind_process_launcher(ProcessExecutionScope())

        handle = await launcher.start(
            ProcessLaunchRequest(
                command=(
                    sys.executable,
                    "-c",
                    (
                        "import sys,time; "
                        "sys.stdout.buffer.write(b'raw-bytes'); "
                        "sys.stdout.buffer.flush(); time.sleep(60)"
                    ),
                ),
                cwd=str(tmp_path),
                effective_environment=tuple(os.environ.items()),
            ),
            correlation_id="runtime-smoke",
        )
        assert await handle.read_stdout() == b"raw-bytes"
        await runtime.close()
        assert (await handle.wait()).return_code != 0

    asyncio.run(scenario())


def test_hosted_process_required_fails_and_best_effort_degrades_before_spawn(
    tmp_path: Path,
) -> None:
    async def scenario(requirement: str):
        diagnostics: list[SandboxDiagnostic] = []
        backend = _Backend()
        runtime = bind_sandbox_execution_runtime(
            base_exec_service=ExecService(),
            settings=SandboxSettings(
                enabled=True,
                requirement=requirement,  # type: ignore[arg-type]
            ),
            registry=_registry(backend),
            environment_probe=LocalHostEnvironmentProbe(
                platform_name="linux",
                architecture="x86_64",
                environ={},
            ),
            scope_request_factory=_scope_request_factory(tmp_path),
            diagnostic_sink=diagnostics.append,
        )
        launcher = runtime.bind_process_launcher(
            ProcessExecutionScope(
                execution_profile_ceiling=EffectiveExecutionProfile(
                    readable_roots=(tmp_path,),
                    writable_roots=(tmp_path,),
                )
            )
        )
        request = ProcessLaunchRequest(
            command=(sys.executable, "-c", "import time; time.sleep(60)"),
            cwd=str(tmp_path),
            effective_environment=tuple(os.environ.items()),
        )
        if requirement == "required":
            with pytest.raises(SandboxUnavailableError, match="cannot host"):
                await launcher.start(request, correlation_id="required")
            assert runtime.status().state == "enabled"
            await runtime.close()
        else:
            handle = await launcher.start(request, correlation_id="best-effort")
            assert runtime.status().state == "degraded"
            assert [item.code for item in diagnostics] == [
                "sandbox_process_hosting_degraded"
            ]
            await runtime.close()
            assert (await handle.wait()).return_code != 0

    asyncio.run(scenario("required"))
    asyncio.run(scenario("best_effort"))


def test_runtime_close_delays_cancellation_through_host_and_sandbox_order() -> None:
    events: list[str] = []

    class _HostOwner:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def close(self) -> None:
            events.append("host-start")
            self.entered.set()
            await self.release.wait()
            events.append("host-end")

    class _ContainmentOwner:
        def status_override(self):
            return None

        async def close(self) -> None:
            events.append("containment")

    class _BindingOwner:
        def status(self):
            return SandboxStatus(state="disabled")

        async def close(self) -> None:
            events.append("sandbox")

    async def scenario() -> None:
        host = _HostOwner()
        runtime = SandboxExecutionRuntime(
            binding=_BindingOwner(),  # type: ignore[arg-type]
            exec_service=ExecService(),
            _process_host=host,  # type: ignore[arg-type]
            _process_containment=_ContainmentOwner(),  # type: ignore[arg-type]
        )
        close_task = asyncio.create_task(runtime.close())
        await host.entered.wait()
        close_task.cancel()
        await asyncio.sleep(0)
        assert close_task.done() is False
        host.release.set()

        with pytest.raises(asyncio.CancelledError):
            await close_task
        assert events == ["host-start", "host-end", "containment", "sandbox"]
        await runtime.close()
        assert events == ["host-start", "host-end", "containment", "sandbox"]

    asyncio.run(scenario())


def test_runtime_close_continues_after_failures_and_preserves_first_error() -> None:
    events: list[str] = []

    class _FailingOwner:
        def __init__(self, name: str, error: BaseException) -> None:
            self.name = name
            self.error = error

        async def close(self) -> None:
            events.append(self.name)
            raise self.error

    class _ContainmentOwner(_FailingOwner):
        def status_override(self):
            return None

    class _BindingOwner(_FailingOwner):
        def status(self):
            return SandboxStatus(state="disabled")

    async def scenario() -> None:
        primary = RuntimeError("host failed")
        runtime = SandboxExecutionRuntime(
            binding=_BindingOwner(  # type: ignore[arg-type]
                "sandbox",
                OSError("sandbox failed"),
            ),
            exec_service=ExecService(),
            _process_host=_FailingOwner(  # type: ignore[arg-type]
                "host",
                primary,
            ),
            _process_containment=_ContainmentOwner(  # type: ignore[arg-type]
                "containment",
                ValueError("containment failed"),
            ),
        )

        with pytest.raises(RuntimeError, match="host failed") as captured:
            await runtime.close()
        assert captured.value is primary
        assert captured.value.__notes__ == [
            "later cleanup failure: containment failed",
            "later cleanup failure: sandbox failed",
        ]
        assert events == ["host", "containment", "sandbox"]

        with pytest.raises(RuntimeError) as repeated:
            await runtime.close()
        assert repeated.value is primary
        assert events == ["host", "containment", "sandbox"]

    asyncio.run(scenario())


def test_degraded_runtime_falls_back_through_the_injected_execution_service(
    tmp_path: Path,
) -> None:
    calls: list[ExecRequest] = []

    async def base_backend(request, **kwargs):
        del kwargs
        calls.append(request)
        return ExecResult(exit_code=0, stdout="injected")

    backend = _Backend(fail_open=True)
    runtime = bind_sandbox_execution_runtime(
        base_exec_service=ExecService(backend=base_backend),
        settings=SandboxSettings(enabled=True),
        registry=_registry(backend),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        scope_request_factory=_scope_request_factory(tmp_path),
    )

    result = asyncio.run(
        runtime.exec_service.execute(ExecRequest(command=("tool",), cwd=str(tmp_path)))
    )

    assert result.stdout == "injected"
    assert len(calls) == 1
    assert runtime.status().state == "degraded"
    asyncio.run(runtime.close())
    assert backend.close_count == 1


def test_disabled_binding_does_not_probe_host_or_backend() -> None:
    class _UnexpectedProbe:
        def detect(self) -> HostEnvironment:
            raise AssertionError("disabled sandbox must not probe the host")

    def unexpected_factory():
        raise AssertionError("disabled sandbox must not create a backend")

    registry = SandboxBackendRegistry(
        (
            SandboxBackendRegistration(
                backend_id="unexpected",
                os_families=frozenset({"linux"}),
                factory=unexpected_factory,
            ),
        )
    )

    binding = bind_sandbox_execution(
        registry=registry,
        environment_probe=_UnexpectedProbe(),
    )

    assert binding.status().state == "disabled"


def test_required_sandbox_cannot_be_configured_as_disabled() -> None:
    with pytest.raises(ValueError, match="cannot be disabled"):
        SandboxSettings(enabled=False, requirement="required")


def test_enabled_best_effort_binding_degrades_when_no_backend_applies(
    tmp_path: Path,
) -> None:
    diagnostics: list[SandboxDiagnostic] = []

    async def local_backend(request, **kwargs):
        del request, kwargs
        return ExecResult(exit_code=0, stdout="fallback")

    binding = bind_sandbox_execution(
        settings=SandboxSettings(enabled=True),
        registry=SandboxBackendRegistry(),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        local_backend=local_backend,
        scope_request_factory=_scope_request_factory(tmp_path),
        diagnostic_sink=diagnostics.append,
    )
    result = asyncio.run(
        ExecService(backend=binding.exec_backend).execute(
            ExecRequest(command=("fallback",), cwd=str(tmp_path))
        )
    )

    assert result.stdout == "fallback"
    assert binding.service is None
    assert binding.status().state == "degraded"
    assert [diagnostic.code for diagnostic in diagnostics] == ["sandbox_unavailable"]


def test_enabled_required_binding_fails_when_no_backend_applies(
    tmp_path: Path,
) -> None:
    with pytest.raises(SandboxUnavailableError, match="no sandbox backend"):
        bind_sandbox_execution(
            settings=SandboxSettings(enabled=True, requirement="required"),
            registry=SandboxBackendRegistry(),
            environment_probe=LocalHostEnvironmentProbe(
                platform_name="linux",
                architecture="x86_64",
                environ={},
            ),
            scope_request_factory=_scope_request_factory(tmp_path),
        )


def test_sandbox_exec_backend_opens_and_closes_one_scope_per_execution(
    tmp_path: Path,
) -> None:
    backend = _Backend()
    binding = bind_sandbox_execution(
        settings=SandboxSettings(enabled=True),
        registry=_registry(backend),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        scope_request_factory=_scope_request_factory(tmp_path),
    )
    service = ExecService(backend=binding.exec_backend)

    first = asyncio.run(
        service.execute(ExecRequest(command=("one",), cwd=str(tmp_path)))
    )
    second = asyncio.run(
        service.execute(ExecRequest(command=("two",), cwd=str(tmp_path)))
    )
    asyncio.run(binding.close())

    assert first.stdout == "sandboxed"
    assert second.stdout == "sandboxed"
    assert len(backend.scopes) == 2
    assert [scope.close_count for scope in backend.scopes] == [1, 1]
    assert [scope.requests[0].command for scope in backend.scopes] == [
        ("one",),
        ("two",),
    ]
    assert all(
        scope.requests[0].effective_environment is not None for scope in backend.scopes
    )
    assert backend.close_count == 1


def test_best_effort_scope_failure_falls_back_and_warns_once(
    tmp_path: Path,
) -> None:
    backend = _Backend(fail_open=True)
    diagnostics: list[SandboxDiagnostic] = []
    local_calls: list[ExecRequest] = []

    async def local_backend(request, **kwargs):
        del kwargs
        local_calls.append(request)
        return ExecResult(exit_code=0, stdout="fallback")

    binding = bind_sandbox_execution(
        settings=SandboxSettings(enabled=True),
        registry=_registry(backend),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        local_backend=local_backend,
        scope_request_factory=_scope_request_factory(tmp_path),
        diagnostic_sink=diagnostics.append,
    )
    service = ExecService(backend=binding.exec_backend)

    first = asyncio.run(
        service.execute(ExecRequest(command=("one",), cwd=str(tmp_path)))
    )
    second = asyncio.run(
        service.execute(ExecRequest(command=("two",), cwd=str(tmp_path)))
    )

    assert first.stdout == second.stdout == "fallback"
    assert [request.command for request in local_calls] == [("one",), ("two",)]
    assert binding.status().state == "degraded"
    assert [diagnostic.code for diagnostic in diagnostics] == ["sandbox_degraded"]


def test_required_scope_failure_does_not_spawn_local_process(
    tmp_path: Path,
) -> None:
    backend = _Backend(fail_open=True)
    local_called = False

    async def local_backend(request, **kwargs):
        nonlocal local_called
        del request, kwargs
        local_called = True
        return ExecResult(exit_code=0)

    binding = bind_sandbox_execution(
        settings=SandboxSettings(enabled=True, requirement="required"),
        registry=_registry(backend),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        local_backend=local_backend,
        scope_request_factory=_scope_request_factory(tmp_path),
    )

    with pytest.raises(SandboxUnavailableError, match="scope failed"):
        asyncio.run(
            ExecService(backend=binding.exec_backend).execute(
                ExecRequest(command=("blocked",), cwd=str(tmp_path))
            )
        )

    assert local_called is False


def test_required_service_rejects_backend_reported_degraded_scope(
    tmp_path: Path,
) -> None:
    backend = _Backend(descriptor_state="degraded")
    binding = bind_sandbox_execution(
        settings=SandboxSettings(enabled=True, requirement="required"),
        registry=_registry(backend),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        scope_request_factory=_scope_request_factory(tmp_path),
    )

    with pytest.raises(SandboxUnavailableError, match="backend degraded"):
        asyncio.run(
            ExecService(backend=binding.exec_backend).execute(
                ExecRequest(command=("blocked",), cwd=str(tmp_path))
            )
        )

    assert backend.scopes[0].close_count == 1


def test_binding_close_releases_leaked_scopes_and_backend_once(
    tmp_path: Path,
) -> None:
    backend = _Backend()
    binding = bind_sandbox_execution(
        settings=SandboxSettings(enabled=True),
        registry=_registry(backend),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        scope_request_factory=_scope_request_factory(tmp_path),
    )
    assert binding.service is not None

    async def scenario() -> None:
        await binding.service.open_scope(
            SandboxScopeRequest(
                cwd=tmp_path,
                readable_roots=(tmp_path,),
            )
        )
        await binding.close()
        await binding.close()

    asyncio.run(scenario())

    assert backend.scopes[0].close_count == 1
    assert backend.close_count == 1
