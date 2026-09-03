from __future__ import annotations

import inspect
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from loushang.harness.environment import HostEnvironment
from loushang.harness.workspace.exec import (
    ExecBackend,
    ExecRequest,
    ExecResult,
    ExecUpdateCallback,
    LocalExecBackend,
)
from loushang.harness.workspace.process import ProcessLaunchRequest
from loushang.harness.workspace.process._sealed_executable import (
    _bound_process_directory_from_request,
    _contained_process_launch_request,
    _sealed_process_executable_from_request,
)
from loushang.harness.workspace.process.local import ProcessContainmentPlan

from ..types import (
    SandboxBackendStatus,
    SandboxScopeDescriptor,
    SandboxScopeRequest,
    SandboxUnavailableError,
)
from ._bubblewrap import (
    build_bubblewrap_command,
    validate_bubblewrap_scope_request,
)

_CAPABILITIES = frozenset(
    {
        "filesystem_roots",
        "filesystem_denied_roots",
        "network_isolation",
        "private_temporary_directory",
        "subprocess_inheritance",
    }
)
_PROBE_TIMEOUT_SECONDS = 3.0
_MANAGED_BIND_OPTIONS = ("--ro-bind-data", "--ro-bind-fd")

BubblewrapFinder = Callable[[str], str | None]
BubblewrapProbeRunner = Callable[
    [tuple[str, ...], float],
    subprocess.CompletedProcess[str],
]


class LinuxBubblewrapBackend:
    """Linux namespace sandbox implemented by wrapping the common exec backend."""

    backend_id = "linux-bubblewrap"

    def __init__(
        self,
        *,
        bwrap_path: str | Path | None = None,
        executable_finder: BubblewrapFinder = shutil.which,
        probe_runner: BubblewrapProbeRunner | None = None,
        local_backend: ExecBackend | None = None,
    ) -> None:
        self._configured_path = Path(bwrap_path) if bwrap_path is not None else None
        self._executable_finder = executable_finder
        self._probe_runner = probe_runner or _run_probe
        self._local_backend = (
            local_backend if local_backend is not None else LocalExecBackend()
        )
        self._resolved_path: Path | None = None
        self._available = False
        self._managed_process_bindings = False
        self._managed_process_unavailable_reason: str | None = (
            "bubblewrap managed-process features have not been probed"
        )
        self._closed = False

    def probe(self, environment: HostEnvironment) -> SandboxBackendStatus:
        self._available = False
        self._resolved_path = None
        self._managed_process_bindings = False
        self._managed_process_unavailable_reason = (
            "bubblewrap managed-process features have not been probed"
        )
        if environment.os_family != "linux":
            return SandboxBackendStatus(
                backend_id=self.backend_id,
                state="not_applicable",
                reason=f"bubblewrap requires Linux, not {environment.platform_name}",
            )

        path = self._resolve_executable()
        if path is None:
            return SandboxBackendStatus(
                backend_id=self.backend_id,
                state="unavailable",
                reason="bubblewrap executable was not found",
            )
        if not path.is_file() or not os.access(path, os.X_OK):
            return SandboxBackendStatus(
                backend_id=self.backend_id,
                state="unavailable",
                reason=f"bubblewrap executable is not runnable: {path}",
            )

        argv = _build_probe_command(path)
        try:
            completed = self._probe_runner(argv, _PROBE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return SandboxBackendStatus(
                backend_id=self.backend_id,
                state="unavailable",
                reason="bubblewrap namespace probe timed out",
            )
        except OSError as error:
            return SandboxBackendStatus(
                backend_id=self.backend_id,
                state="unavailable",
                reason=f"bubblewrap namespace probe failed: {error}",
            )
        if completed.returncode != 0:
            detail = _safe_probe_detail(completed.stderr)
            reason = "bubblewrap cannot create the required namespaces"
            if detail:
                reason = f"{reason}: {detail}"
            return SandboxBackendStatus(
                backend_id=self.backend_id,
                state="unavailable",
                reason=reason,
            )

        self._resolved_path = path
        self._available = True
        feature_reason = self._probe_managed_process_bindings(path)
        self._managed_process_bindings = feature_reason is None
        self._managed_process_unavailable_reason = feature_reason
        return SandboxBackendStatus(
            backend_id=self.backend_id,
            state="available",
            enforced_capabilities=_CAPABILITIES,
        )

    def _probe_managed_process_bindings(self, path: Path) -> str | None:
        try:
            completed = self._probe_runner(
                (str(path), "--help"),
                _PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return "bubblewrap managed-process feature probe timed out"
        except OSError as error:
            return f"bubblewrap managed-process feature probe failed: {error}"
        if completed.returncode != 0:
            detail = _safe_probe_detail(completed.stderr)
            reason = "bubblewrap managed-process feature probe failed"
            return f"{reason}: {detail}" if detail else reason
        help_text = completed.stdout or ""
        missing_options = tuple(
            option for option in _MANAGED_BIND_OPTIONS if option not in help_text
        )
        if missing_options:
            return (
                "bubblewrap lacks required managed-process bind options: "
                + ", ".join(missing_options)
            )
        return None

    async def open_scope(
        self,
        request: SandboxScopeRequest,
    ) -> _LinuxBubblewrapScope:
        if self._closed:
            raise RuntimeError("bubblewrap backend is closed")
        if not self._available or self._resolved_path is None:
            raise SandboxUnavailableError(
                "bubblewrap backend must pass its namespace probe before use"
            )
        validate_bubblewrap_scope_request(request)
        return _LinuxBubblewrapScope(
            bwrap_path=self._resolved_path,
            request=request,
            local_backend=self._local_backend,
        )

    def _prepare_guarded_command(
        self,
        request: SandboxScopeRequest,
        command: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Prepare one internal guarded command after the native probe passed."""

        if self._closed:
            raise RuntimeError("bubblewrap backend is closed")
        if not self._available or self._resolved_path is None:
            raise SandboxUnavailableError(
                "bubblewrap backend must pass its namespace probe before use"
            )
        if not command or any(
            not isinstance(value, str) or not value for value in command
        ):
            raise ValueError("bubblewrap command must contain non-empty strings")
        validate_bubblewrap_scope_request(request)
        return build_bubblewrap_command(self._resolved_path, request, command)

    async def _plan_hosted_process(
        self,
        request: ProcessLaunchRequest,
        scope: SandboxScopeRequest,
    ) -> ProcessContainmentPlan:
        if self._closed:
            raise RuntimeError("bubblewrap backend is closed")
        if not self._available or self._resolved_path is None:
            raise SandboxUnavailableError(
                "bubblewrap backend must pass its namespace probe before use"
            )
        validate_bubblewrap_scope_request(scope)
        artifact = _sealed_process_executable_from_request(request)
        bound_cwd = _bound_process_directory_from_request(request)
        return ProcessContainmentPlan(
            _contained_process_launch_request(
                request,
                command=build_bubblewrap_command(
                    self._resolved_path,
                    scope,
                    request.command,
                    sealed_executable=(
                        (artifact.descriptor, artifact.logical_path)
                        if artifact is not None
                        else None
                    ),
                    bound_cwd_directory=(
                        (bound_cwd.descriptor, bound_cwd.logical_path)
                        if bound_cwd is not None
                        else None
                    ),
                ),
            )
        )

    async def close(self) -> None:
        self._closed = True

    def _resolve_executable(self) -> Path | None:
        if self._configured_path is not None:
            return self._configured_path.expanduser().resolve(strict=False)
        found = self._executable_finder("bwrap")
        if not found:
            return None
        return Path(found).expanduser().resolve(strict=False)


class _LinuxBubblewrapScope:
    def __init__(
        self,
        *,
        bwrap_path: Path,
        request: SandboxScopeRequest,
        local_backend: ExecBackend,
    ) -> None:
        self._bwrap_path = bwrap_path
        self._request = request
        self._local_backend = local_backend
        self._closed = False
        capabilities = set(_CAPABILITIES)
        if request.network == "allowed":
            capabilities.discard("network_isolation")
        self._descriptor = SandboxScopeDescriptor(
            state="enforcing",
            backend_id=LinuxBubblewrapBackend.backend_id,
            enforced_capabilities=frozenset(capabilities),
        )

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
        if self._closed:
            raise RuntimeError("bubblewrap scope is closed")
        if request.effective_environment is None:
            raise ValueError("bubblewrap scope requires a materialized ExecRequest")
        wrapped = replace(
            request,
            command=build_bubblewrap_command(
                self._bwrap_path,
                self._request,
                request.command,
            ),
        )
        result = self._local_backend(
            wrapped,
            signal=signal,
            on_update=on_update,
        )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ExecResult):
            raise TypeError("bubblewrap exec backend must return ExecResult")
        return result

    async def close(self) -> None:
        self._closed = True


def _run_probe(
    argv: tuple[str, ...],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _build_probe_command(bwrap_path: Path) -> tuple[str, ...]:
    true_command = next(
        (
            candidate
            for candidate in ("/usr/bin/true", "/bin/true")
            if Path(candidate).is_file()
        ),
        "/bin/true",
    )
    return (
        str(bwrap_path),
        "--new-session",
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-net",
        "--",
        true_command,
    )


def _safe_probe_detail(stderr: str | None) -> str:
    if not stderr:
        return ""
    return " ".join(stderr.strip().split())[:500]


__all__ = ["LinuxBubblewrapBackend"]
