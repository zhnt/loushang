"""Owner-only local Worker launch adapter over Process and Sandbox owners."""

from __future__ import annotations

import asyncio
from typing import Protocol

from loushang.harness.tools.process_hosting import (
    ScopeBoundProcessLauncher,
    _managed_process_launch_request,
)
from loushang.harness.workspace.process import (
    ProcessExit,
    ProcessHandle,
    ProcessStderrTail,
)
from loushang.harness.workspace.process._sealed_executable import (
    SealedProcessExecutableUnavailable,
    _BoundProcessDirectory,
    _capture_bound_process_directory,
    _capture_sealed_process_executable,
    _SealedProcessExecutable,
)

from .contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerLaunchEvidenceV1,
)

WORKER_DIAGNOSTIC_READ_MAX_BYTES = 64 * 1024


class ManagedWorkerLaunchPort(Protocol):
    """Narrow owner capability; it accepts no arbitrary command or environment."""

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ManagedWorkerProcess: ...


class ManagedWorkerProcess:
    """Worker-specific lifetime handle without exposing the generic launcher."""

    def __init__(
        self,
        handle: ProcessHandle,
        *,
        evidence: WorkerLaunchEvidenceV1,
        executable: _SealedProcessExecutable,
        cwd: _BoundProcessDirectory,
    ) -> None:
        self._handle = handle
        self._executable = executable
        self._cwd = cwd
        self._release_lock = asyncio.Lock()
        self._released = False
        self.evidence = evidence

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        """Read bounded diagnostics; Worker protocol never uses stdout."""

        _require_diagnostic_read_bound(max_bytes)
        return await self._handle.read_stdout(max_bytes)

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        """Read bounded diagnostics; Worker protocol never uses stderr."""

        _require_diagnostic_read_bound(max_bytes)
        return await self._handle.read_stderr(max_bytes)

    async def wait(self) -> ProcessExit:
        try:
            return await self._handle.wait()
        finally:
            await self._release_artifacts()

    async def terminate(self) -> ProcessExit:
        try:
            return await self._handle.terminate()
        finally:
            await self._release_artifacts()

    async def close(self) -> None:
        try:
            await self._handle.close()
        finally:
            await self._release_artifacts()

    def stderr_tail(self) -> ProcessStderrTail:
        return self._handle.stderr_tail()

    async def _release_artifacts(self) -> None:
        async with self._release_lock:
            if self._released:
                return
            self._released = True
            self._cwd.close()
            self._executable.close()


class _ManagedWorkerLaunchPort:
    def __init__(self, launcher: ScopeBoundProcessLauncher) -> None:
        if type(launcher) is not ScopeBoundProcessLauncher:
            raise TypeError(
                "Managed Worker launch port requires the exact Process owner launcher"
            )
        launcher._verify_managed_start_authority()
        self._launcher = launcher

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ManagedWorkerProcess:
        if not isinstance(request, ManagedWorkerLaunchRequestV1):
            raise TypeError("Managed Worker launch port requires a typed request")
        evidence = WorkerLaunchEvidenceV1(
            identity_fingerprint=request.identity.fingerprint,
            runtime_binding_fingerprint=request.runtime.fingerprint,
            request_fingerprint=request.fingerprint,
            launch_correlation_id=correlation_id,
        )
        request.validate_current()
        request.runtime.verify()
        executable: _SealedProcessExecutable | None = None
        cwd: _BoundProcessDirectory | None = None
        published = False
        try:
            executable = _capture_sealed_process_executable(
                request.runtime.executable,
                expected_digest=request.runtime.executable_digest,
            )
            cwd = _capture_bound_process_directory(
                request.runtime.package_root,
                expected_identity=(
                    request.runtime.cwd_device,
                    request.runtime.cwd_inode,
                ),
            )

            def validate_start_evidence() -> None:
                executable.verify()
                cwd.verify()
                request.runtime.verify()
                request.validate_current()

            process_request = _managed_process_launch_request(
                command=(str(request.runtime.executable),),
                cwd=str(request.runtime.package_root),
                effective_environment=(),
                declared_effects=(),
                authorization_metadata={
                    "attemptId": request.identity.attempt_id,
                    "contributionId": request.identity.contribution_id,
                    "cwdDevice": cwd.device,
                    "cwdInode": cwd.inode,
                    "declarationFingerprint": (
                        request.identity.declaration_fingerprint
                    ),
                    "identityFingerprint": request.identity.fingerprint,
                    "ownerGeneration": request.identity.owner_generation,
                    "ownerId": request.identity.owner_id,
                    "pluginId": request.identity.plugin_id,
                    "pluginRevisionDigest": (request.identity.plugin_revision_digest),
                    "productId": request.identity.product_id,
                    "runtimeDigest": request.runtime.executable_digest,
                    "runtimeSize": executable.size,
                    "scopeId": request.identity.scope_id,
                    "supervisorEpoch": request.identity.supervisor_epoch,
                    "workerConfigurationFingerprint": (
                        request.identity.worker_configuration_fingerprint
                    ),
                    "workerLaunchRequestFingerprint": request.fingerprint,
                },
                pre_start_validator=validate_start_evidence,
                sealed_executable=executable,
                bound_cwd_directory=cwd,
            )
            handle = await self._launcher._start_managed(
                process_request,
                correlation_id=correlation_id,
                signal=signal,
            )
            process = ManagedWorkerProcess(
                handle,
                evidence=evidence,
                executable=executable,
                cwd=cwd,
            )
            published = True
            return process
        except SealedProcessExecutableUnavailable as exc:
            raise WorkerBindingError(
                "Managed Worker runtime could not be sealed",
                code="worker_runtime_unsealable",
            ) from exc
        finally:
            if not published:
                if cwd is not None:
                    cwd.close()
                if executable is not None:
                    executable.close()


def _bind_managed_worker_launch_port(
    launcher: ScopeBoundProcessLauncher,
) -> ManagedWorkerLaunchPort:
    """Mint the Worker capability only at the Sandbox/Process composition root."""

    return _ManagedWorkerLaunchPort(launcher)


def _require_diagnostic_read_bound(max_bytes: int) -> None:
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
        or max_bytes > WORKER_DIAGNOSTIC_READ_MAX_BYTES
    ):
        raise ValueError("Worker diagnostic read size is outside its bound")


__all__ = [
    "WORKER_DIAGNOSTIC_READ_MAX_BYTES",
    "ManagedWorkerLaunchPort",
    "ManagedWorkerProcess",
]
