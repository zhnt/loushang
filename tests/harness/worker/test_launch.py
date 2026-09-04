from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from loushang.harness.authorization import ExecutionAuthorizationError
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.tools.process_hosting import (
    ProcessExecutionScope,
    ScopeBoundProcessLauncher,
    _authorization_metadata,
)
from loushang.harness.worker import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.launch import _bind_managed_worker_launch_port
from loushang.harness.workspace.process import ProcessExit, ProcessStderrTail


class _RequiredContainment:
    requirement = "required"


class _Handle:
    closed = False

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return b"diagnostic"

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return b"warning"

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> ProcessExit:
        return ProcessExit(0)

    async def terminate(self) -> ProcessExit:
        return ProcessExit(-15)

    async def close(self) -> None:
        self.closed = True

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail(content=b"warning")


def _configuration() -> PluginLocalWorkerConfiguration:
    return PluginLocalWorkerConfiguration(
        entrypoint="worker",
        protocol="capability.query",
        protocol_version=1,
    )


def _binding(tmp_path: Path) -> WorkerRuntimeBindingV1:
    executable = tmp_path / "worker"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o500)
    return WorkerRuntimeBindingV1.capture(
        package_root=tmp_path,
        configuration=_configuration(),
    )


def _identity(binding: WorkerRuntimeBindingV1) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="review-pack",
        plugin_revision_digest="a" * 64,
        contribution_id="review-provider",
        owner_id="coding.lsp",
        product_id="coding",
        scope_id="session-one",
        owner_generation=3,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint=(binding.worker_configuration_fingerprint),
        attempt_id="c" * 32,
        supervisor_epoch=7,
        session_nonce="d" * 64,
    )


def _owner_launcher() -> ScopeBoundProcessLauncher:
    launcher = ScopeBoundProcessLauncher(
        scope=ProcessExecutionScope(require_approval=True),
        host=object(),  # type: ignore[arg-type]
        containment=_RequiredContainment(),  # type: ignore[arg-type]
    )
    launcher._managed_owner_authority = object()
    launcher._managed_plan_verifier = lambda plan, authority: None
    return launcher


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux memfd seals")
def test_owner_only_worker_port_seals_identity_and_returns_redacted_evidence(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        binding = _binding(tmp_path)
        identity = _identity(binding)
        validations = 0

        def validate_current() -> None:
            nonlocal validations
            validations += 1

        request = ManagedWorkerLaunchRequestV1(
            identity=identity,
            runtime=binding,
            validate_current=validate_current,
        )
        launcher = _owner_launcher()
        captured: list[object] = []
        handle = _Handle()

        async def start_managed(
            process_request: object,
            *,
            correlation_id: str,
            signal: object | None = None,
        ) -> _Handle:
            del signal
            assert correlation_id == "worker-launch-1"
            captured.append(process_request)
            return handle

        launcher._start_managed = start_managed  # type: ignore[method-assign]
        port = _bind_managed_worker_launch_port(launcher)
        process = await port.start(request, correlation_id="worker-launch-1")

        assert validations == 1
        assert len(captured) == 1
        metadata = _authorization_metadata(captured[0])  # type: ignore[arg-type]
        assert metadata["identityFingerprint"] == identity.fingerprint
        assert metadata["workerLaunchRequestFingerprint"] == request.fingerprint
        assert metadata["runtimeDigest"] == binding.executable_digest
        evidence = json.dumps(process.evidence.to_dict(), sort_keys=True)
        assert str(tmp_path) not in evidence
        assert str(binding.executable) not in evidence
        assert await process.read_stdout() == b"diagnostic"
        with pytest.raises(ValueError, match="outside its bound"):
            await process.read_stderr(64 * 1024 + 1)
        assert not hasattr(process, "write_stdin")
        await process.close()
        assert handle.closed is True

    asyncio.run(scenario())


def test_worker_port_cannot_be_minted_without_mandatory_owner_guards() -> None:
    launcher = ScopeBoundProcessLauncher(
        scope=ProcessExecutionScope(require_approval=False),
        host=object(),  # type: ignore[arg-type]
        containment=_RequiredContainment(),  # type: ignore[arg-type]
    )
    launcher._managed_owner_authority = object()
    launcher._managed_plan_verifier = lambda plan, authority: None

    with pytest.raises(ExecutionAuthorizationError, match="mandatory Approval"):
        _bind_managed_worker_launch_port(launcher)


def test_worker_port_rejects_invalid_correlation_before_launch(tmp_path: Path) -> None:
    async def scenario() -> None:
        binding = _binding(tmp_path)
        launcher = _owner_launcher()
        launched = False

        async def start_managed(*args: object, **kwargs: object) -> _Handle:
            del args, kwargs
            nonlocal launched
            launched = True
            return _Handle()

        launcher._start_managed = start_managed  # type: ignore[method-assign]
        request = ManagedWorkerLaunchRequestV1(
            identity=_identity(binding),
            runtime=binding,
            validate_current=lambda: None,
        )
        with pytest.raises(ValueError, match="bounded identifier"):
            await _bind_managed_worker_launch_port(launcher).start(
                request,
                correlation_id="not a bounded id",
            )
        assert launched is False

    asyncio.run(scenario())


def test_worker_runtime_binding_fails_closed_on_symlink_and_mutation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"worker-v1")
    target.chmod(0o500)
    (tmp_path / "worker").symlink_to(target)
    with pytest.raises(WorkerBindingError) as caught:
        WorkerRuntimeBindingV1.capture(
            package_root=tmp_path,
            configuration=_configuration(),
        )
    assert caught.value.code == "worker_entrypoint_invalid"

    (tmp_path / "worker").unlink()
    binding = _binding(tmp_path)
    binding.executable.chmod(0o700)
    binding.executable.write_bytes(b"worker-v2")
    with pytest.raises(WorkerBindingError) as caught:
        binding.verify()
    assert caught.value.code == "worker_runtime_changed"

    with pytest.raises(WorkerBindingError) as caught:
        WorkerRuntimeBindingV1.capture(
            package_root=tmp_path / "missing",
            configuration=_configuration(),
        )
    assert caught.value.code == "worker_package_root_invalid"
