"""Authority-free records for one exact local Plugin Worker attempt."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.workspace.process._sealed_executable import (
    SealedProcessExecutableUnavailable,
    _stable_process_executable_digest,
)

WORKER_LAUNCH_IDENTITY_VERSION = 1
WORKER_RUNTIME_BINDING_VERSION = 1
WORKER_LAUNCH_REQUEST_VERSION = 1
WORKER_LAUNCH_EVIDENCE_VERSION = 1
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_MAX_IDENTIFIER_LENGTH = 128


class WorkerBindingError(RuntimeError):
    """Stable, redacted failure while binding immutable Worker launch material."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkerLaunchIdentityV1:
    """Exact Product/domain identity bound to one supervised attempt."""

    plugin_id: str
    plugin_revision_digest: str
    contribution_id: str
    owner_id: str
    product_id: str
    scope_id: str
    owner_generation: int
    declaration_fingerprint: str
    worker_configuration_fingerprint: str
    attempt_id: str
    supervisor_epoch: int
    session_nonce: str
    identity_version: int = WORKER_LAUNCH_IDENTITY_VERSION

    def __post_init__(self) -> None:
        for name, text_value in (
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("owner id", self.owner_id),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
        ):
            _require_identifier(text_value, name=name)
        for name, digest_value in (
            ("Plugin revision digest", self.plugin_revision_digest),
            ("declaration fingerprint", self.declaration_fingerprint),
            (
                "Worker configuration fingerprint",
                self.worker_configuration_fingerprint,
            ),
        ):
            _require_sha256(digest_value, name=name)
        for name, integer_value in (
            ("owner generation", self.owner_generation),
            ("supervisor epoch", self.supervisor_epoch),
        ):
            _require_positive_integer(integer_value, name=name)
        _require_hex(self.attempt_id, length=32, name="Worker attempt id")
        _require_hex(self.session_nonce, length=64, name="Worker session nonce")
        _require_exact_version(
            self.identity_version,
            supported=WORKER_LAUNCH_IDENTITY_VERSION,
            name="Worker launch identity",
        )

    @property
    def fingerprint(self) -> str:
        return _digest("loushang.worker-launch-identity/v1", self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "contributionId": self.contribution_id,
            "declarationFingerprint": self.declaration_fingerprint,
            "identityVersion": self.identity_version,
            "ownerGeneration": self.owner_generation,
            "ownerId": self.owner_id,
            "pluginId": self.plugin_id,
            "pluginRevisionDigest": self.plugin_revision_digest,
            "productId": self.product_id,
            "scopeId": self.scope_id,
            "sessionNonce": self.session_nonce,
            "supervisorEpoch": self.supervisor_epoch,
            "workerConfigurationFingerprint": (self.worker_configuration_fingerprint),
        }


@dataclass(frozen=True, slots=True)
class WorkerRuntimeBindingV1:
    """Host-captured executable and cwd identity; never author-provided authority."""

    package_root: Path
    executable: Path
    executable_digest: str
    executable_size: int
    cwd_device: int
    cwd_inode: int
    worker_configuration_fingerprint: str
    protocol: str
    protocol_version: int
    binding_version: int = WORKER_RUNTIME_BINDING_VERSION

    @classmethod
    def capture(
        cls,
        *,
        package_root: str | Path,
        configuration: PluginLocalWorkerConfiguration,
    ) -> WorkerRuntimeBindingV1:
        if not isinstance(configuration, PluginLocalWorkerConfiguration):
            raise TypeError("Worker runtime binding requires Worker configuration")
        try:
            root = Path(package_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkerBindingError(
                "Plugin Worker package root is unavailable",
                code="worker_package_root_invalid",
            ) from exc
        if not root.is_dir():
            raise WorkerBindingError(
                "Plugin Worker package root is not a directory",
                code="worker_package_root_invalid",
            )
        relative = Path(configuration.entrypoint)
        candidate = root / relative
        try:
            executable = candidate.resolve(strict=True)
            executable.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkerBindingError(
                "Plugin Worker entrypoint escaped its package revision",
                code="worker_entrypoint_invalid",
            ) from exc
        if not executable.is_file() or _path_uses_symlink(root, relative):
            raise WorkerBindingError(
                "Plugin Worker entrypoint is not a contained regular file",
                code="worker_entrypoint_invalid",
            )
        try:
            digest, size = _stable_process_executable_digest(executable)
            root_stat = root.stat()
        except (OSError, SealedProcessExecutableUnavailable) as exc:
            raise WorkerBindingError(
                "Plugin Worker runtime identity could not be captured",
                code="worker_runtime_unavailable",
            ) from exc
        return cls(
            package_root=root,
            executable=executable,
            executable_digest=digest,
            executable_size=size,
            cwd_device=root_stat.st_dev,
            cwd_inode=root_stat.st_ino,
            worker_configuration_fingerprint=configuration.fingerprint,
            protocol=configuration.protocol,
            protocol_version=configuration.protocol_version,
        )

    def __post_init__(self) -> None:
        root = Path(self.package_root)
        executable = Path(self.executable)
        if not root.is_absolute() or not executable.is_absolute():
            raise ValueError("Worker runtime paths must be absolute")
        try:
            executable.relative_to(root)
        except ValueError as exc:
            raise ValueError("Worker executable must stay inside its package") from exc
        _require_sha256(self.executable_digest, name="Worker executable digest")
        _require_sha256(
            self.worker_configuration_fingerprint,
            name="Worker configuration fingerprint",
        )
        _require_identifier(self.protocol, name="Worker protocol")
        _require_positive_integer(
            self.protocol_version,
            name="Worker protocol version",
        )
        _require_nonnegative_integer(self.executable_size, name="executable size")
        if self.executable_size < 1:
            raise ValueError("Worker executable size must be positive")
        _require_nonnegative_integer(self.cwd_device, name="cwd device")
        _require_nonnegative_integer(self.cwd_inode, name="cwd inode")
        _require_exact_version(
            self.binding_version,
            supported=WORKER_RUNTIME_BINDING_VERSION,
            name="Worker runtime binding",
        )
        object.__setattr__(self, "package_root", root)
        object.__setattr__(self, "executable", executable)

    def verify(self) -> None:
        try:
            root = self.package_root.resolve(strict=True)
            executable = self.executable.resolve(strict=True)
            executable.relative_to(root)
            root_stat = root.stat()
            digest, size = _stable_process_executable_digest(executable)
        except (
            OSError,
            RuntimeError,
            ValueError,
            SealedProcessExecutableUnavailable,
        ) as exc:
            raise WorkerBindingError(
                "Plugin Worker runtime identity changed",
                code="worker_runtime_changed",
            ) from exc
        if (
            root != self.package_root
            or executable != self.executable
            or _path_uses_symlink(root, executable.relative_to(root))
            or (root_stat.st_dev, root_stat.st_ino) != (self.cwd_device, self.cwd_inode)
            or digest != self.executable_digest
            or size != self.executable_size
        ):
            raise WorkerBindingError(
                "Plugin Worker runtime identity changed",
                code="worker_runtime_changed",
            )

    @property
    def fingerprint(self) -> str:
        return _digest(
            "loushang.worker-runtime-binding/v1",
            {
                "bindingVersion": self.binding_version,
                "cwdDevice": self.cwd_device,
                "cwdInode": self.cwd_inode,
                "executableDigest": self.executable_digest,
                "executableSize": self.executable_size,
                "protocol": self.protocol,
                "protocolVersion": self.protocol_version,
                "workerConfigurationFingerprint": (
                    self.worker_configuration_fingerprint
                ),
            },
        )


@dataclass(frozen=True, slots=True)
class ManagedWorkerLaunchRequestV1:
    identity: WorkerLaunchIdentityV1
    runtime: WorkerRuntimeBindingV1
    validate_current: Callable[[], None] = field(repr=False, compare=False)
    request_version: int = WORKER_LAUNCH_REQUEST_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.identity, WorkerLaunchIdentityV1):
            raise TypeError("Managed Worker launch requires a launch identity")
        if not isinstance(self.runtime, WorkerRuntimeBindingV1):
            raise TypeError("Managed Worker launch requires a runtime binding")
        if (
            self.runtime.worker_configuration_fingerprint
            != self.identity.worker_configuration_fingerprint
        ):
            raise ValueError("Worker runtime and declaration configuration differ")
        if not callable(self.validate_current):
            raise TypeError(
                "Managed Worker launch requires a current-evidence validator"
            )
        _require_exact_version(
            self.request_version,
            supported=WORKER_LAUNCH_REQUEST_VERSION,
            name="Managed Worker launch request",
        )

    @property
    def fingerprint(self) -> str:
        return _digest(
            "loushang.managed-worker-launch-request/v1",
            {
                "identityFingerprint": self.identity.fingerprint,
                "requestVersion": self.request_version,
                "runtimeBindingFingerprint": self.runtime.fingerprint,
            },
        )


@dataclass(frozen=True, slots=True)
class WorkerLaunchEvidenceV1:
    identity_fingerprint: str
    runtime_binding_fingerprint: str
    request_fingerprint: str
    launch_correlation_id: str
    evidence_version: int = WORKER_LAUNCH_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Worker identity fingerprint", self.identity_fingerprint),
            ("Worker runtime binding fingerprint", self.runtime_binding_fingerprint),
            ("Worker request fingerprint", self.request_fingerprint),
        ):
            _require_sha256(value, name=name)
        _require_identifier(
            self.launch_correlation_id,
            name="launch correlation id",
        )
        _require_exact_version(
            self.evidence_version,
            supported=WORKER_LAUNCH_EVIDENCE_VERSION,
            name="Worker launch evidence",
        )

    @property
    def fingerprint(self) -> str:
        return _digest("loushang.worker-launch-evidence/v1", self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "evidenceVersion": self.evidence_version,
            "identityFingerprint": self.identity_fingerprint,
            "launchCorrelationId": self.launch_correlation_id,
            "requestFingerprint": self.request_fingerprint,
            "runtimeBindingFingerprint": self.runtime_binding_fingerprint,
        }


def _path_uses_symlink(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError:
            return True
        if stat.S_ISLNK(metadata.st_mode):
            return True
    return False


def _digest(domain: str, value: object) -> str:
    encoded = json.dumps(
        {"domain": domain, "value": value},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _require_identifier(value: object, *, name: str) -> str:
    result = _require_nonempty(value, name=name)
    if (
        result != value
        or len(result) > _MAX_IDENTIFIER_LENGTH
        or not _IDENTIFIER.fullmatch(result)
    ):
        raise ValueError(f"{name} must be a bounded identifier")
    return result


def _require_hex(value: object, *, length: int, name: str) -> str:
    result = _require_nonempty(value, name=name)
    if len(result) != length or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{name} must be lowercase hexadecimal")
    return result


def _require_sha256(value: object, *, name: str) -> str:
    return _require_hex(value, length=64, name=name)


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _require_positive_integer(value: object, *, name: str) -> int:
    result = _require_nonnegative_integer(value, name=name)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _require_exact_version(value: object, *, supported: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} version must be an integer")
    if value != supported:
        raise ValueError(f"Unsupported {name} version")


__all__ = [
    "WORKER_LAUNCH_EVIDENCE_VERSION",
    "WORKER_LAUNCH_IDENTITY_VERSION",
    "WORKER_LAUNCH_REQUEST_VERSION",
    "WORKER_RUNTIME_BINDING_VERSION",
    "ManagedWorkerLaunchRequestV1",
    "WorkerBindingError",
    "WorkerLaunchEvidenceV1",
    "WorkerLaunchIdentityV1",
    "WorkerRuntimeBindingV1",
]
