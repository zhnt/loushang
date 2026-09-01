"""PLC9B2 bounded Source acquisition into owner-created quarantine."""

from __future__ import annotations

import os
import re
import stat
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
    canonicalize_source_identity,
)

PACKAGE_ACQUISITION_REQUEST_VERSION = 1
AUTHENTICATED_SOURCE_ENVELOPE_VERSION = 1
SOURCE_ADAPTER_RESULT_VERSION = 1
PACKAGE_ACQUISITION_BUDGET_VERSION = 1
BOUNDED_ACQUISITION_RECEIPT_VERSION = 1

SourceOriginKind = Literal["https", "registry", "git", "local"]
SourceAuthenticationDecision = Literal["authorized", "denied"]
SourceAdapterDisposition = Literal["complete"]
AcquisitionStage = Literal["acquiring", "acquired"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ORIGIN_KINDS = {"https", "registry", "git", "local"}
_WINDOWS_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


class PackageAcquisitionError(RuntimeError):
    """Bounded, secret-free acquisition failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: AcquisitionStage,
        retryable: bool,
        consumed_bytes: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.consumed_bytes = consumed_bytes


@dataclass(frozen=True, slots=True)
class PackageAcquisitionRequestV1:
    operation_id: str
    attempt_epoch: int
    node_id: str
    canonical_source_identity: str
    request_fingerprint: str
    requested_locator_digest: str
    policy_revision: str
    credential_reference: str | None = field(default=None, repr=False, compare=False)
    request_version: int = PACKAGE_ACQUISITION_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.canonical_source_identity, "canonical Source identity"),
        ):
            _require_nonempty(value, name=name)
        for value, name in (
            (self.operation_id, "operation id"),
            (self.node_id, "node id"),
            (self.policy_revision, "Source policy revision"),
        ):
            _require_safe_label(value, name=name)
        _require_positive(self.attempt_epoch, name="attempt epoch")
        _require_sha256(self.request_fingerprint, name="request fingerprint")
        _require_sha256(
            self.requested_locator_digest,
            name="requested locator digest",
        )
        if canonicalize_source_identity(self.canonical_source_identity) != (
            self.canonical_source_identity
        ):
            raise ValueError("Canonical Source identity contains secret-bearing parts")
        if self.credential_reference is not None:
            _require_nonempty(
                self.credential_reference,
                name="credential reference",
            )
        if self.request_version != PACKAGE_ACQUISITION_REQUEST_VERSION:
            raise ValueError("Unsupported Package acquisition request")


@dataclass(frozen=True, slots=True)
class AuthenticatedSourceEnvelopeV1:
    operation_id: str
    node_id: str
    canonical_source_identity: str
    origin_kind: SourceOriginKind
    authentication_decision: SourceAuthenticationDecision
    authority_id: str
    requested_locator_digest: str
    expected_artifact_digest: str | None
    redirect_policy_revision: str
    policy_revision: str
    capture_epoch: int
    envelope_version: int = AUTHENTICATED_SOURCE_ENVELOPE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.canonical_source_identity, "canonical Source identity"),
        ):
            _require_nonempty(value, name=name)
        for value, name in (
            (self.operation_id, "operation id"),
            (self.node_id, "node id"),
            (self.authority_id, "Source authority id"),
            (self.redirect_policy_revision, "redirect policy revision"),
            (self.policy_revision, "Source policy revision"),
        ):
            _require_safe_label(value, name=name)
        if canonicalize_source_identity(self.canonical_source_identity) != (
            self.canonical_source_identity
        ):
            raise ValueError("Authenticated Source identity is not canonical")
        if self.origin_kind not in _ORIGIN_KINDS:
            raise ValueError("Unsupported authenticated Source origin kind")
        if self.authentication_decision not in {"authorized", "denied"}:
            raise ValueError("Unsupported Source authentication decision")
        _require_sha256(
            self.requested_locator_digest,
            name="requested locator digest",
        )
        if self.expected_artifact_digest is not None:
            _require_sha256(
                self.expected_artifact_digest,
                name="expected artifact digest",
            )
        _require_positive(self.capture_epoch, name="Source capture epoch")
        if self.envelope_version != AUTHENTICATED_SOURCE_ENVELOPE_VERSION:
            raise ValueError("Unsupported authenticated Source envelope")

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "authenticationDecision": self.authentication_decision,
            "authorityId": self.authority_id,
            "canonicalSourceIdentity": self.canonical_source_identity,
            "captureEpoch": self.capture_epoch,
            "envelopeVersion": self.envelope_version,
            "expectedArtifactDigest": self.expected_artifact_digest,
            "nodeId": self.node_id,
            "operationId": self.operation_id,
            "originKind": self.origin_kind,
            "policyRevision": self.policy_revision,
            "redirectPolicyRevision": self.redirect_policy_revision,
            "requestedLocatorDigest": self.requested_locator_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> AuthenticatedSourceEnvelopeV1:
        document = _exact_dict(
            value,
            fields={
                "authenticationDecision",
                "authorityId",
                "canonicalSourceIdentity",
                "captureEpoch",
                "envelopeVersion",
                "expectedArtifactDigest",
                "nodeId",
                "operationId",
                "originKind",
                "policyRevision",
                "redirectPolicyRevision",
                "requestedLocatorDigest",
            },
            name="authenticated Source envelope",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            node_id=_wire_string(document["nodeId"], name="node id"),
            canonical_source_identity=_wire_string(
                document["canonicalSourceIdentity"],
                name="canonical Source identity",
            ),
            origin_kind=cast(
                SourceOriginKind,
                _wire_string(document["originKind"], name="Source origin kind"),
            ),
            authentication_decision=cast(
                SourceAuthenticationDecision,
                _wire_string(
                    document["authenticationDecision"],
                    name="Source authentication decision",
                ),
            ),
            authority_id=_wire_string(
                document["authorityId"], name="Source authority id"
            ),
            requested_locator_digest=_wire_string(
                document["requestedLocatorDigest"],
                name="requested locator digest",
            ),
            expected_artifact_digest=_wire_optional_string(
                document["expectedArtifactDigest"],
                name="expected artifact digest",
            ),
            redirect_policy_revision=_wire_string(
                document["redirectPolicyRevision"],
                name="redirect policy revision",
            ),
            policy_revision=_wire_string(
                document["policyRevision"], name="Source policy revision"
            ),
            capture_epoch=_wire_positive(
                document["captureEpoch"], name="Source capture epoch"
            ),
            envelope_version=_wire_int(
                document["envelopeVersion"], name="Source envelope version"
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceAdapterResultV1:
    disposition: SourceAdapterDisposition
    adapter_revision: str = "source-adapter:v1"
    result_version: int = SOURCE_ADAPTER_RESULT_VERSION

    def __post_init__(self) -> None:
        if self.disposition != "complete":
            raise ValueError("Unsupported Source adapter disposition")
        _require_safe_label(self.adapter_revision, name="Source adapter revision")
        if self.result_version != SOURCE_ADAPTER_RESULT_VERSION:
            raise ValueError("Unsupported Source adapter result")

    def to_dict(self) -> dict[str, object]:
        return {
            "adapterRevision": self.adapter_revision,
            "disposition": self.disposition,
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceAdapterResultV1:
        document = _exact_dict(
            value,
            fields={"adapterRevision", "disposition", "resultVersion"},
            name="Source adapter result",
        )
        return cls(
            disposition=cast(
                SourceAdapterDisposition,
                _wire_string(
                    document["disposition"], name="Source adapter disposition"
                ),
            ),
            adapter_revision=_wire_string(
                document["adapterRevision"], name="Source adapter revision"
            ),
            result_version=_wire_int(
                document["resultVersion"], name="Source adapter result version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageAcquisitionBudgetV1:
    max_transport_bytes: int
    max_requests: int
    max_redirects: int
    max_wall_time_ms: int
    budget_version: int = PACKAGE_ACQUISITION_BUDGET_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.max_transport_bytes, name="transport byte budget")
        _require_positive(self.max_requests, name="request budget")
        _require_nonnegative(self.max_redirects, name="redirect budget")
        _require_positive(self.max_wall_time_ms, name="wall-clock budget")
        if self.budget_version != PACKAGE_ACQUISITION_BUDGET_VERSION:
            raise ValueError("Unsupported Package acquisition budget")

    def to_dict(self) -> dict[str, object]:
        return {
            "budgetVersion": self.budget_version,
            "maxRedirects": self.max_redirects,
            "maxRequests": self.max_requests,
            "maxTransportBytes": self.max_transport_bytes,
            "maxWallTimeMs": self.max_wall_time_ms,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageAcquisitionBudgetV1:
        document = _exact_dict(
            value,
            fields={
                "budgetVersion",
                "maxRedirects",
                "maxRequests",
                "maxTransportBytes",
                "maxWallTimeMs",
            },
            name="Package acquisition budget",
        )
        return cls(
            max_transport_bytes=_wire_positive(
                document["maxTransportBytes"], name="transport byte budget"
            ),
            max_requests=_wire_positive(
                document["maxRequests"], name="request budget"
            ),
            max_redirects=_wire_nonnegative(
                document["maxRedirects"], name="redirect budget"
            ),
            max_wall_time_ms=_wire_positive(
                document["maxWallTimeMs"], name="wall-clock budget"
            ),
            budget_version=_wire_int(
                document["budgetVersion"], name="budget version"
            ),
        )


@dataclass(frozen=True, slots=True)
class BoundedAcquisitionReceiptV1:
    operation_id: str
    attempt_epoch: int
    node_id: str
    envelope_fingerprint: str
    actual_byte_digest: str
    actual_byte_count: int
    request_count: int
    redirect_count: int
    budgets: PackageAcquisitionBudgetV1
    sink_identity: str
    adapter_result: SourceAdapterResultV1
    disposition: Literal["complete"] = "complete"
    receipt_version: int = BOUNDED_ACQUISITION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation id"),
            (self.node_id, "node id"),
        ):
            _require_nonempty(value, name=name)
        _require_positive(self.attempt_epoch, name="attempt epoch")
        _require_sha256(self.envelope_fingerprint, name="envelope fingerprint")
        _require_sha256(self.actual_byte_digest, name="actual byte digest")
        _require_nonnegative(self.actual_byte_count, name="actual byte count")
        _require_positive(self.request_count, name="request count")
        _require_nonnegative(self.redirect_count, name="redirect count")
        if self.actual_byte_count > self.budgets.max_transport_bytes:
            raise ValueError("Acquisition receipt exceeds transport budget")
        if self.request_count > self.budgets.max_requests:
            raise ValueError("Acquisition receipt exceeds request budget")
        if self.redirect_count > self.budgets.max_redirects:
            raise ValueError("Acquisition receipt exceeds redirect budget")
        _require_sha256(self.sink_identity, name="sink identity")
        if self.disposition != "complete":
            raise ValueError("Unsupported acquisition disposition")
        if self.receipt_version != BOUNDED_ACQUISITION_RECEIPT_VERSION:
            raise ValueError("Unsupported bounded acquisition receipt")

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "actualByteCount": self.actual_byte_count,
            "actualByteDigest": self.actual_byte_digest,
            "adapterResult": self.adapter_result.to_dict(),
            "attemptEpoch": self.attempt_epoch,
            "budgets": self.budgets.to_dict(),
            "disposition": self.disposition,
            "envelopeFingerprint": self.envelope_fingerprint,
            "nodeId": self.node_id,
            "operationId": self.operation_id,
            "receiptVersion": self.receipt_version,
            "redirectCount": self.redirect_count,
            "requestCount": self.request_count,
            "sinkIdentity": self.sink_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> BoundedAcquisitionReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "actualByteCount",
                "actualByteDigest",
                "adapterResult",
                "attemptEpoch",
                "budgets",
                "disposition",
                "envelopeFingerprint",
                "nodeId",
                "operationId",
                "receiptVersion",
                "redirectCount",
                "requestCount",
                "sinkIdentity",
            },
            name="bounded acquisition receipt",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            attempt_epoch=_wire_positive(
                document["attemptEpoch"], name="attempt epoch"
            ),
            node_id=_wire_string(document["nodeId"], name="node id"),
            envelope_fingerprint=_wire_string(
                document["envelopeFingerprint"], name="envelope fingerprint"
            ),
            actual_byte_digest=_wire_string(
                document["actualByteDigest"], name="actual byte digest"
            ),
            actual_byte_count=_wire_nonnegative(
                document["actualByteCount"], name="actual byte count"
            ),
            request_count=_wire_positive(
                document["requestCount"], name="request count"
            ),
            redirect_count=_wire_nonnegative(
                document["redirectCount"], name="redirect count"
            ),
            budgets=PackageAcquisitionBudgetV1.from_dict(document["budgets"]),
            sink_identity=_wire_string(
                document["sinkIdentity"], name="sink identity"
            ),
            adapter_result=SourceAdapterResultV1.from_dict(
                document["adapterResult"]
            ),
            disposition=cast(
                Literal["complete"],
                _wire_string(document["disposition"], name="disposition"),
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


class BoundedAcquisitionSinkPort(Protocol):
    def begin_request(self) -> None: ...

    def record_redirect(self, canonical_source_identity: str) -> None: ...

    def write(self, chunk: bytes) -> None: ...


class AuthenticatedSourceStreamPort(Protocol):
    envelope: AuthenticatedSourceEnvelopeV1

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1: ...


class PackageSourceAuthorityPort(Protocol):
    def authorize(
        self,
        request: PackageAcquisitionRequestV1,
    ) -> AuthenticatedSourceStreamPort: ...


class PackageQuarantineStore:
    """Owner-created private attempt roots; Source adapters never receive it."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        _require_no_link_ancestors(self.root.parent)
        if self.root.exists() or self.root.is_symlink():
            _require_private_directory(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require_no_link_ancestors(self.root)
        _require_private_directory(self.root)

    def attempt_names(self) -> tuple[str, ...]:
        _require_private_directory(self.root)
        return tuple(
            sorted(
                entry.name
                for entry in os.scandir(self.root)
                if entry.is_dir(follow_symlinks=False)
            )
        )

    def total_residue_bytes(self) -> int:
        total = 0
        for directory, names, files in os.walk(self.root, followlinks=False):
            names[:] = [
                name
                for name in names
                if not (Path(directory) / name).is_symlink()
            ]
            for name in files:
                path = Path(directory) / name
                metadata = path.lstat()
                if stat.S_ISREG(metadata.st_mode) and not _is_reparse(metadata):
                    total += metadata.st_size
        return total

    def _begin(
        self,
        request: PackageAcquisitionRequestV1,
    ) -> _QuarantineAttempt:
        return _QuarantineAttempt.create(self.root, request)


class _QuarantineAttempt:
    def __init__(
        self,
        *,
        store_root: Path,
        attempt_name: str,
        root_fd: int | None,
        attempt_fd: int | None,
        root_identity: tuple[int, int],
        attempt_identity: tuple[int, int],
        artifact_name: str,
    ) -> None:
        self._store_root = store_root
        self._attempt_name = attempt_name
        self._root_fd = root_fd
        self._attempt_fd = attempt_fd
        self._root_identity = root_identity
        self._attempt_identity = attempt_identity
        self._artifact_name = artifact_name
        self._closed = False

    @classmethod
    def create(
        cls,
        store_root: Path,
        request: PackageAcquisitionRequestV1,
    ) -> _QuarantineAttempt:
        seed = canonical_json_bytes(
            {
                "attemptEpoch": request.attempt_epoch,
                "nodeId": request.node_id,
                "operationId": request.operation_id,
            }
        )
        attempt_name = f"attempt-{sha256(seed).hexdigest()}"
        artifact_name = f"artifact-{sha256(request.node_id.encode()).hexdigest()}"
        if _supports_descriptor_relative_io():
            root_fd = _open_directory(store_root)
            try:
                root_identity = _identity(os.fstat(root_fd))
                os.mkdir(attempt_name, mode=0o700, dir_fd=root_fd)
                attempt_fd = _open_directory(attempt_name, dir_fd=root_fd)
            except Exception:
                os.close(root_fd)
                raise
            attempt_identity = _identity(os.fstat(attempt_fd))
            return cls(
                store_root=store_root,
                attempt_name=attempt_name,
                root_fd=root_fd,
                attempt_fd=attempt_fd,
                root_identity=root_identity,
                attempt_identity=attempt_identity,
                artifact_name=artifact_name,
            )
        attempt_path = store_root / attempt_name
        attempt_path.mkdir(mode=0o700, exist_ok=False)
        _require_private_directory(attempt_path)
        return cls(
            store_root=store_root,
            attempt_name=attempt_name,
            root_fd=None,
            attempt_fd=None,
            root_identity=_identity(store_root.lstat()),
            attempt_identity=_identity(attempt_path.lstat()),
            artifact_name=artifact_name,
        )

    @property
    def _sink_identity(self) -> str:
        return sha256(
            canonical_json_bytes(
                {
                    "attemptIdentity": list(self._attempt_identity),
                    "artifactName": self._artifact_name,
                    "rootIdentity": list(self._root_identity),
                }
            )
        ).hexdigest()

    def _open_artifact_for_write(self) -> BinaryIO:
        self._verify()
        if self._attempt_fd is not None:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(
                self._artifact_name,
                flags,
                0o600,
                dir_fd=self._attempt_fd,
            )
            return os.fdopen(descriptor, "wb", buffering=0)
        path = self._attempt_path / self._artifact_name
        return path.open("xb", buffering=0)

    def _open_artifact_for_read(self) -> BinaryIO:
        self._verify()
        if self._attempt_fd is not None:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(
                self._artifact_name,
                flags,
                dir_fd=self._attempt_fd,
            )
            handle = os.fdopen(descriptor, "rb")
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or _is_reparse(metadata):
                handle.close()
                raise OSError("Quarantine artifact is not a regular file")
            return handle
        path = self._attempt_path / self._artifact_name
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or _is_reparse(metadata):
            raise OSError("Quarantine artifact is not a regular file")
        return path.open("rb")

    def _verify(self) -> None:
        if self._closed:
            raise OSError("Quarantine attempt is closed")
        if self._root_fd is not None and self._attempt_fd is not None:
            if _identity(os.fstat(self._root_fd)) != self._root_identity:
                raise OSError("Quarantine root descriptor identity changed")
            visible_root = _open_directory(self._store_root)
            try:
                if _identity(os.fstat(visible_root)) != self._root_identity:
                    raise OSError("Quarantine root path identity changed")
                visible_attempt = _open_directory(
                    self._attempt_name,
                    dir_fd=visible_root,
                )
                try:
                    if _identity(os.fstat(visible_attempt)) != self._attempt_identity:
                        raise OSError("Quarantine attempt path identity changed")
                finally:
                    os.close(visible_attempt)
            finally:
                os.close(visible_root)
            return
        _require_private_directory(self._store_root)
        _require_private_directory(self._attempt_path)
        if _identity(self._store_root.lstat()) != self._root_identity:
            raise OSError("Quarantine root path identity changed")
        if _identity(self._attempt_path.lstat()) != self._attempt_identity:
            raise OSError("Quarantine attempt path identity changed")

    @property
    def _attempt_path(self) -> Path:
        return self._store_root / self._attempt_name

    def _cleanup(self) -> None:
        if self._closed:
            return
        attempt_fd = self._attempt_fd
        root_fd = self._root_fd
        if root_fd is not None:
            if attempt_fd is not None:
                with suppress(FileNotFoundError):
                    os.unlink(self._artifact_name, dir_fd=attempt_fd)
                os.close(attempt_fd)
                self._attempt_fd = None
            try:
                os.rmdir(self._attempt_name, dir_fd=root_fd)
            except OSError:
                raise
            else:
                os.close(root_fd)
                self._root_fd = None
                self._closed = True
                return
        else:
            path = self._attempt_path / self._artifact_name
            with suppress(FileNotFoundError):
                path.unlink()
            self._attempt_path.rmdir()
            self._closed = True


class _BoundedAcquisitionSink:
    def __init__(
        self,
        *,
        attempt: _QuarantineAttempt,
        budgets: PackageAcquisitionBudgetV1,
        clock: Callable[[], float],
    ) -> None:
        self._attempt = attempt
        self._budgets = budgets
        self._clock = clock
        self._started_at = clock()
        self._handle = attempt._open_artifact_for_write()
        self._digest = sha256()
        self._byte_count = 0
        self._request_count = 0
        self._redirect_count = 0
        self._closed = False

    def begin_request(self) -> None:
        self._check_open_and_time()
        if self._request_count + 1 > self._budgets.max_requests:
            self._raise_limit()
        self._request_count += 1

    def record_redirect(self, canonical_source_identity: str) -> None:
        self._check_open_and_time()
        canonical = canonicalize_source_identity(canonical_source_identity)
        if canonical != canonical_source_identity:
            raise PackageAcquisitionError(
                "Redirect Source identity is not canonical",
                code="package_source_provenance_changed",
                stage="acquiring",
                retryable=False,
                consumed_bytes=self._byte_count,
            )
        if self._redirect_count + 1 > self._budgets.max_redirects:
            self._raise_limit()
        self._redirect_count += 1

    def write(self, chunk: bytes) -> None:
        self._check_open_and_time()
        if not isinstance(chunk, bytes):
            raise TypeError("Bounded acquisition sink accepts bytes")
        if self._byte_count + len(chunk) > self._budgets.max_transport_bytes:
            self._raise_limit()
        self._attempt._verify()
        self._handle.write(chunk)
        self._digest.update(chunk)
        self._byte_count += len(chunk)

    def _finish(
        self,
        *,
        expected_digest: str | None,
        adapter_result: SourceAdapterResultV1,
    ) -> tuple[str, int, int, int]:
        self._check_open_and_time()
        if self._request_count < 1:
            raise PackageAcquisitionError(
                "Source adapter completed without a request",
                code="package_source_provenance_changed",
                stage="acquiring",
                retryable=False,
                consumed_bytes=self._byte_count,
            )
        if not isinstance(adapter_result, SourceAdapterResultV1):
            raise TypeError("Source adapter result is required")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._closed = True
        actual_digest = self._digest.hexdigest()
        if expected_digest is not None and actual_digest != expected_digest:
            raise PackageAcquisitionError(
                "Acquired artifact digest does not match Source evidence",
                code="package_acquisition_digest_mismatch",
                stage="acquired",
                retryable=False,
                consumed_bytes=self._byte_count,
            )
        return (
            actual_digest,
            self._byte_count,
            self._request_count,
            self._redirect_count,
        )

    def _abort(self) -> None:
        if not self._closed:
            self._closed = True
            self._handle.close()

    def _check_open_and_time(self) -> None:
        if self._closed:
            raise RuntimeError("Bounded acquisition sink is closed")
        elapsed_ms = (self._clock() - self._started_at) * 1000
        if elapsed_ms > self._budgets.max_wall_time_ms:
            raise PackageAcquisitionError(
                "Package acquisition exceeded the wall-clock budget",
                code="package_operation_timed_out",
                stage="acquiring",
                retryable=True,
                consumed_bytes=self._byte_count,
            )

    def _raise_limit(self) -> None:
        raise PackageAcquisitionError(
            "Package acquisition exceeded a resource budget",
            code="package_acquisition_limit_exceeded",
            stage="acquiring",
            retryable=True,
            consumed_bytes=self._byte_count,
        )


class AcquiredPackageCandidate:
    """Private capability passed only to the inert verifier in the next edge."""

    def __init__(
        self,
        *,
        attempt: _QuarantineAttempt,
        receipt: BoundedAcquisitionReceiptV1,
    ) -> None:
        self._attempt = attempt
        self.receipt = receipt
        self._closed = False

    def __repr__(self) -> str:
        return (
            "AcquiredPackageCandidate("
            f"operation_id={self.receipt.operation_id!r}, "
            f"node_id={self.receipt.node_id!r}, "
            f"digest={self.receipt.actual_byte_digest!r})"
        )

    def open_for_verifier(self) -> BinaryIO:
        if self._closed:
            raise RuntimeError("Acquired Package candidate is closed")
        handle = self._attempt._open_artifact_for_read()
        digest = sha256()
        byte_count = 0
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
        if (
            byte_count != self.receipt.actual_byte_count
            or digest.hexdigest() != self.receipt.actual_byte_digest
        ):
            handle.close()
            raise PackageAcquisitionError(
                "Acquired artifact identity changed before verification",
                code="package_artifact_identity_changed",
                stage="acquired",
                retryable=False,
                consumed_bytes=byte_count,
            )
        handle.seek(0)
        return handle

    def cleanup(self) -> None:
        if self._closed:
            return
        self._attempt._cleanup()
        self._closed = True


class PackageAcquisitionOwner:
    """Authenticate and stream bytes without giving adapters a pathname."""

    def __init__(
        self,
        *,
        source_authority: PackageSourceAuthorityPort,
        quarantine_store: PackageQuarantineStore,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not callable(getattr(source_authority, "authorize", None)):
            raise TypeError("Package Source authority is required")
        if not isinstance(quarantine_store, PackageQuarantineStore):
            raise TypeError("Package quarantine store is required")
        self._source_authority = source_authority
        self._quarantine_store = quarantine_store
        self._clock = clock or time.monotonic

    def acquire(
        self,
        request: PackageAcquisitionRequestV1,
        *,
        budgets: PackageAcquisitionBudgetV1,
    ) -> AcquiredPackageCandidate:
        if not isinstance(request, PackageAcquisitionRequestV1):
            raise TypeError("Package acquisition request is required")
        if not isinstance(budgets, PackageAcquisitionBudgetV1):
            raise TypeError("Package acquisition budgets are required")
        try:
            stream = self._source_authority.authorize(request)
        except PackageAcquisitionError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "package_source_unauthorized",
                    "package_source_provenance_changed",
                }
                else "package_source_unauthorized"
            )
            raise PackageAcquisitionError(
                "Source authority refused acquisition",
                code=code,
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            ) from None
        except Exception:
            raise PackageAcquisitionError(
                "Source authority refused acquisition",
                code="package_source_unauthorized",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            ) from None
        envelope = getattr(stream, "envelope", None)
        if not isinstance(envelope, AuthenticatedSourceEnvelopeV1):
            raise PackageAcquisitionError(
                "Source authority returned no authenticated envelope",
                code="package_source_unauthorized",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            )
        _verify_envelope(request, envelope)
        try:
            attempt = self._quarantine_store._begin(request)
        except FileExistsError:
            raise PackageAcquisitionError(
                "Package acquisition attempt identity already exists",
                code="package_operation_identity_conflict",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            ) from None
        except OSError:
            raise PackageAcquisitionError(
                "Package quarantine identity could not be proved",
                code="package_artifact_identity_changed",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            ) from None
        sink = _BoundedAcquisitionSink(
            attempt=attempt,
            budgets=budgets,
            clock=self._clock,
        )
        try:
            result = stream.transfer_to(sink)
            digest, count, requests, redirects = sink._finish(
                expected_digest=envelope.expected_artifact_digest,
                adapter_result=result,
            )
            receipt = BoundedAcquisitionReceiptV1(
                operation_id=request.operation_id,
                attempt_epoch=request.attempt_epoch,
                node_id=request.node_id,
                envelope_fingerprint=envelope.fingerprint,
                actual_byte_digest=digest,
                actual_byte_count=count,
                request_count=requests,
                redirect_count=redirects,
                budgets=budgets,
                sink_identity=attempt._sink_identity,
                adapter_result=result,
            )
            return AcquiredPackageCandidate(attempt=attempt, receipt=receipt)
        except PackageAcquisitionError:
            sink._abort()
            attempt._cleanup()
            raise
        except Exception:
            sink._abort()
            attempt._cleanup()
            raise PackageAcquisitionError(
                "Source adapter was interrupted",
                code="package_operation_interrupted",
                stage="acquiring",
                retryable=True,
                consumed_bytes=sink._byte_count,
            ) from None


def _verify_envelope(
    request: PackageAcquisitionRequestV1,
    envelope: AuthenticatedSourceEnvelopeV1,
) -> None:
    if envelope.authentication_decision != "authorized":
        raise PackageAcquisitionError(
            "Source authority denied acquisition",
            code="package_source_unauthorized",
            stage="acquiring",
            retryable=False,
            consumed_bytes=0,
        )
    if (
        envelope.operation_id != request.operation_id
        or envelope.node_id != request.node_id
        or envelope.canonical_source_identity
        != request.canonical_source_identity
        or envelope.requested_locator_digest != request.requested_locator_digest
        or envelope.policy_revision != request.policy_revision
    ):
        raise PackageAcquisitionError(
            "Authenticated Source evidence changed before acquisition",
            code="package_source_provenance_changed",
            stage="acquiring",
            retryable=False,
            consumed_bytes=0,
        )


def _supports_descriptor_relative_io() -> bool:
    return (
        os.name == "posix"
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and hasattr(os, "O_NOFOLLOW")
    )


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, dir_fd=dir_fd)


def _require_private_directory(path: Path) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise OSError("Package quarantine root is not a private directory")
    if os.name == "posix" and metadata.st_mode & 0o077:
        raise OSError("Package quarantine root permissions are not private")


def _require_no_link_ancestors(path: Path) -> None:
    for candidate in (path, *path.parents):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise OSError("Package quarantine path traverses a link or reparse point")


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_reparse_tag", 0)
        or (
            _WINDOWS_REPARSE_ATTRIBUTE
            and getattr(metadata, "st_file_attributes", 0)
            & _WINDOWS_REPARSE_ATTRIBUTE
        )
    )


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    document = dict(value)
    if set(document) != fields:
        raise ValueError(f"{name} fields do not match the versioned schema")
    return cast(dict[str, object], document)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_positive(value: object, *, name: str) -> int:
    result = _wire_int(value, name=name)
    _require_positive(result, name=name)
    return result


def _wire_nonnegative(value: object, *, name: str) -> int:
    result = _wire_int(value, name=name)
    _require_nonnegative(result, name=name)
    return result


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_safe_label(value: str, *, name: str) -> None:
    _require_nonempty(value, name=name)
    if len(value) > 128 or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None:
        raise ValueError(f"{name} must be a bounded secret-free label")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = [
    "AcquiredPackageCandidate",
    "AuthenticatedSourceEnvelopeV1",
    "AuthenticatedSourceStreamPort",
    "BoundedAcquisitionReceiptV1",
    "BoundedAcquisitionSinkPort",
    "PackageAcquisitionBudgetV1",
    "PackageAcquisitionError",
    "PackageAcquisitionOwner",
    "PackageAcquisitionRequestV1",
    "PackageQuarantineStore",
    "PackageSourceAuthorityPort",
    "SourceAdapterResultV1",
]
