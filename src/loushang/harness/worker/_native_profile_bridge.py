"""Confined Product-to-H6 native profile binding.

The public protocol is deliberately authority-free and handle-free.  Trusted
Harness composition binds one immutable Product receipt and Worker request to
one private Linux H6 capture specification.  Hosting still owns every native
resource and the unique process effect.
"""

from __future__ import annotations

import hashlib
import platform
import re
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from loushang.hosting import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)

from .contracts import ManagedWorkerLaunchRequestV1, WorkerBindingError
from .product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

_POSIX_CONTAINED_PROFILE_ID = "posix-static-contained-elf-v1"
_POSIX_PLATFORM_IDENTITY = "platform:linux-x86_64-syscall-abi"
_CONTAINMENT_ARGUMENT_PROTOCOL = "loushang-static-containment-launch/v1"
_EXECUTION_CLOSURE_DOMAIN = "loushang.worker.native-execution-closure/v1"
_SUPPORTED_MACHINES = frozenset({"amd64", "x86_64"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_PLATFORM_FACT_BYTES = 256

_PlatformProbe = Callable[[], tuple[str, str, str, str]]
_NativeCapture = Callable[[object], Awaitable[object]]


@runtime_checkable
class ProductWorkerNativeProfilePort(Protocol):
    """One receipt/request-bound, single-use native preparation capability.

    The capture result is opaque because it belongs to Hosting.  Product code
    may pass this capability to the Worker composition root but cannot inspect
    or manufacture native material.
    """

    @property
    def receipt_fingerprint(self) -> str: ...

    @property
    def worker_request_fingerprint(self) -> str: ...

    @property
    def native_profile_id(self) -> str: ...

    @property
    def native_profile_catalog_revision(self) -> str: ...

    @property
    def realized_native_policy_closure_fingerprint(self) -> str: ...

    @property
    def execution_closure_fingerprint(self) -> str: ...

    async def capture_native(
        self,
        request: ProcessLaunchRequest,
        *,
        capture: _NativeCapture,
    ) -> object: ...

    async def verify_current(self) -> None: ...

    async def close(self) -> None: ...


class _PosixStaticContainedProductWorkerProfile(ProductWorkerNativeProfilePort):
    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        native_profile_catalog_revision: str,
        launcher_path: Path,
        launcher_sha256: str,
        containment_profile_sha256: str,
        platform_probe: _PlatformProbe,
    ) -> None:
        _require_exact_binding(receipt=receipt, worker_request=worker_request)
        policy = receipt.policy
        if native_profile_catalog_revision != policy.native_profile_catalog_revision:
            raise WorkerBindingError(
                "Worker native profile catalog changed",
                code="worker_native_profile_catalog_mismatch",
            )
        if policy.native_profile_id != _POSIX_CONTAINED_PROFILE_ID:
            raise WorkerBindingError(
                "Worker native profile is unsupported",
                code="worker_native_profile_unsupported",
            )
        if (
            not launcher_path.is_absolute()
            or "\0" in str(launcher_path)
            or not str(launcher_path)
        ):
            raise ValueError("Worker native launcher path is invalid")
        _require_sha256(launcher_sha256, name="launcher")
        _require_sha256(containment_profile_sha256, name="containment profile")
        if not callable(platform_probe):
            raise TypeError("Worker native profile requires a platform probe")
        if worker_request.runtime.cwd_inode < 1:
            raise WorkerBindingError(
                "Worker native cwd identity is unavailable",
                code="worker_native_cwd_identity_unavailable",
            )

        realized_policy_closure = (
            ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
                native_profile_catalog_revision=native_profile_catalog_revision,
                native_profile_id=policy.native_profile_id,
                payload_sha256=worker_request.runtime.executable_digest,
                containment_launcher_sha256=launcher_sha256,
                containment_profile_sha256=containment_profile_sha256,
            )
        )
        if realized_policy_closure != policy.expected_native_policy_closure_fingerprint:
            raise WorkerBindingError(
                "Worker native policy closure changed",
                code="worker_native_policy_closure_mismatch",
            )

        execution_closure = (
            f"containment-launcher-static-elf:sha256:{launcher_sha256}",
            (
                "payload-static-elf:sha256:"
                f"{worker_request.runtime.executable_digest}"
            ),
            (
                "cwd:posix:"
                f"{worker_request.runtime.cwd_device}:"
                f"{worker_request.runtime.cwd_inode}"
            ),
            f"containment-profile:sha256:{containment_profile_sha256}",
            f"invocation:{_CONTAINMENT_ARGUMENT_PROTOCOL}",
            _POSIX_PLATFORM_IDENTITY,
        )
        self._receipt = receipt
        self._worker_request = worker_request
        self._catalog_revision = native_profile_catalog_revision
        self._launcher_path = launcher_path
        self._launcher_sha256 = launcher_sha256
        self._containment_profile_sha256 = containment_profile_sha256
        self._platform_probe = platform_probe
        self._realized_policy_closure = realized_policy_closure
        self._execution_closure = execution_closure
        self._execution_closure_fingerprint = _closure_fingerprint(execution_closure)
        self._state = "ready"
        self._captured = False
        self._lock = threading.Lock()

    @property
    def receipt_fingerprint(self) -> str:
        return self._receipt.fingerprint

    @property
    def worker_request_fingerprint(self) -> str:
        return self._worker_request.fingerprint

    @property
    def native_profile_id(self) -> str:
        return self._receipt.policy.native_profile_id

    @property
    def native_profile_catalog_revision(self) -> str:
        return self._catalog_revision

    @property
    def realized_native_policy_closure_fingerprint(self) -> str:
        return self._realized_policy_closure

    @property
    def execution_closure_fingerprint(self) -> str:
        return self._execution_closure_fingerprint

    async def capture_native(
        self,
        request: ProcessLaunchRequest,
        *,
        capture: _NativeCapture,
    ) -> object:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("Worker native profile requires a process request")
        if not callable(capture):
            raise TypeError("Worker native profile requires a capture capability")
        with self._lock:
            if self._state != "ready":
                raise WorkerBindingError(
                    "Worker native profile is no longer available",
                    code="worker_native_profile_consumed",
                )
            _require_process_request(request, worker_request=self._worker_request)
            self._state = "capturing"

        try:
            _require_linux_x86_64(self._platform_probe)
            spec = self._capture_spec(request)
            binding = await capture(spec)
        except BaseException:
            with self._lock:
                if self._state == "capturing":
                    self._state = "faulted"
            raise

        with self._lock:
            if self._state != "capturing":
                raise WorkerBindingError(
                    "Worker native profile was closed during capture",
                    code="worker_native_profile_consumed",
                )
            self._state = "captured"
            self._captured = True
        return binding

    def _capture_spec(self, request: ProcessLaunchRequest) -> object:
        # These are the only private platform symbols this friend boundary may
        # load.  Loading occurs after Product selection and the non-WSL gate.
        from loushang.hosting._posix_launch_preparation import (
            _PosixStaticContainedLaunchCaptureSpec,
            _PosixStaticLaunchCaptureBackend,
        )

        if _PosixStaticLaunchCaptureBackend.backend_id != "posix-process-group-v1":
            raise WorkerBindingError(
                "Worker native backend identity changed",
                code="worker_native_backend_mismatch",
            )
        return _PosixStaticContainedLaunchCaptureSpec(
            request=request,
            profile_id=_POSIX_CONTAINED_PROFILE_ID,
            execution_closure=self._execution_closure,
            launcher_path=str(self._launcher_path),
            launcher_sha256=self._launcher_sha256,
            executable_sha256=self._worker_request.runtime.executable_digest,
            cwd_device=self._worker_request.runtime.cwd_device,
            cwd_inode=self._worker_request.runtime.cwd_inode,
            containment_profile_sha256=self._containment_profile_sha256,
        )

    async def verify_current(self) -> None:
        with self._lock:
            if self._state != "captured" or not self._captured:
                raise WorkerBindingError(
                    "Worker native profile is not captured",
                    code="worker_native_profile_not_captured",
                )
        _require_exact_binding(
            receipt=self._receipt,
            worker_request=self._worker_request,
        )

    async def close(self) -> None:
        with self._lock:
            self._state = "closed"


def _bind_posix_static_contained_product_worker_profile(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    worker_request: ManagedWorkerLaunchRequestV1,
    native_profile_catalog_revision: str,
    launcher_path: str | Path,
    launcher_sha256: str,
    containment_profile_sha256: str,
    _platform_probe: _PlatformProbe | None = None,
) -> ProductWorkerNativeProfilePort:
    """Bind one trusted Linux profile without activating a Product route."""

    return _PosixStaticContainedProductWorkerProfile(
        receipt=receipt,
        worker_request=worker_request,
        native_profile_catalog_revision=native_profile_catalog_revision,
        launcher_path=Path(launcher_path),
        launcher_sha256=launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
        platform_probe=_platform_probe or _observe_platform,
    )


def _require_exact_binding(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    worker_request: ManagedWorkerLaunchRequestV1,
) -> None:
    if not isinstance(receipt, ProductWorkerActivationReceiptV1):
        raise TypeError("Worker native profile requires an activation receipt")
    if not isinstance(worker_request, ManagedWorkerLaunchRequestV1):
        raise TypeError("Worker native profile requires a managed Worker request")
    policy = receipt.policy
    identity = worker_request.identity
    expected = (
        policy.product_id,
        policy.product_scope_id,
        policy.plugin_id,
        policy.plugin_revision_digest,
        policy.contribution_id,
        policy.declaration_fingerprint,
        policy.worker_configuration_fingerprint,
    )
    actual = (
        identity.product_id,
        identity.scope_id,
        identity.plugin_id,
        identity.plugin_revision_digest,
        identity.contribution_id,
        identity.declaration_fingerprint,
        identity.worker_configuration_fingerprint,
    )
    if expected != actual:
        raise WorkerBindingError(
            "Worker native receipt targets a different request",
            code="worker_native_receipt_mismatch",
        )
    if not policy.enabled or policy.requested_owner != "hosting" or not policy.no_fallback:
        raise WorkerBindingError(
            "Worker native profile is disabled",
            code="worker_native_profile_disabled",
        )


def _require_process_request(
    request: ProcessLaunchRequest,
    *,
    worker_request: ManagedWorkerLaunchRequestV1,
) -> None:
    runtime = worker_request.runtime
    if (
        request.argv != (str(runtime.executable),)
        or request.cwd != str(runtime.package_root)
        or request.effective_environment
        or request.streams.stdin is not ProcessStdinMode.CLOSED
        or request.streams.stdout is not ProcessStdoutMode.DISCARD
        or request.streams.stderr is not ProcessStderrMode.PIPE
    ):
        raise WorkerBindingError(
            "Worker native execution closure changed",
            code="worker_native_execution_closure_mismatch",
        )


def _observe_platform() -> tuple[str, str, str, str]:
    return (
        platform.system(),
        platform.machine(),
        platform.release(),
        platform.version(),
    )


def _require_linux_x86_64(probe: _PlatformProbe) -> None:
    try:
        observation = probe()
    except BaseException as exc:
        raise WorkerBindingError(
            "Worker native platform could not be classified",
            code="worker_native_platform_unknown",
        ) from exc
    if (
        not isinstance(observation, tuple)
        or len(observation) != 4
        or any(
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > _MAX_PLATFORM_FACT_BYTES
            or "\0" in value
            for value in observation
        )
    ):
        raise WorkerBindingError(
            "Worker native platform could not be classified",
            code="worker_native_platform_unknown",
        )
    system, machine, release, version = observation
    if system.casefold() != "linux":
        raise WorkerBindingError(
            "Worker native platform is unsupported",
            code="worker_native_platform_unsupported",
        )
    if machine.casefold() not in _SUPPORTED_MACHINES:
        raise WorkerBindingError(
            "Worker native architecture is unsupported",
            code="worker_native_architecture_unsupported",
        )
    kernel = f"{release}\n{version}".casefold()
    if "microsoft" in kernel or "wsl" in kernel:
        raise WorkerBindingError(
            "Worker native platform is unsupported",
            code="worker_native_platform_wsl_unsupported",
        )


def _closure_fingerprint(closure: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(_EXECUTION_CLOSURE_DOMAIN.encode("ascii"))
    for value in closure:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _require_sha256(value: object, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Worker native {name} digest is invalid")


__all__ = ["ProductWorkerNativeProfilePort"]
