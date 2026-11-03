"""Product-configured, digest-pinned rooted local Wheel Source adapter."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionError,
    PackageAcquisitionRequestV1,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonicalize_source_identity,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    supports_windows_rooted_io,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK_SIZE = 64 * 1024


class PackagePinnedSourceProofError(ValueError):
    """A read-only check could not prove the Product-pinned Source bytes."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackagePinnedLocalWheelSourceProofV1:
    """Path-free observation of the exact bytes pinned by Product policy."""

    source_ref: str
    artifact_digest: str
    byte_count: int
    policy_revision: str
    authority_id: str
    capture_epoch: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and _SHA256.fullmatch(value) is not None
            for value in (self.source_ref, self.artifact_digest)
        ):
            raise ValueError("Pinned Source proof digest is invalid")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("Pinned Source proof byte count is invalid")
        if not self.policy_revision or not self.authority_id:
            raise ValueError("Pinned Source proof authority is invalid")
        if type(self.capture_epoch) is not int or self.capture_epoch < 1:
            raise ValueError("Pinned Source proof epoch is invalid")


class PackagePinnedLocalWheelSourceAuthority:
    """Authorize only exact Product-listed local paths with pinned contents.

    This adapter deliberately supports no network URL or credentials. The
    Package owner remains responsible for bounded streaming and
    quarantine; the Source adapter never receives an owner pathname.
    """

    def __init__(
        self,
        *,
        source_root: Path,
        allowed_digests: Mapping[str, str],
        policy_revision: str,
        authority_id: str,
        capture_epoch: int = 1,
    ) -> None:
        if os.name == "posix":
            if not all(
                hasattr(os, name)
                for name in (
                    "O_NOFOLLOW",
                    "O_DIRECTORY",
                    "O_NONBLOCK",
                    "O_CLOEXEC",
                )
            ):
                raise RuntimeError("Rooted local Package Source requires POSIX no-follow")
        elif os.name != "nt" or not supports_windows_rooted_io():
            raise RuntimeError("Rooted local Package Source is unavailable")
        if (
            not isinstance(source_root, Path)
            or not source_root.is_absolute()
            or (os.name == "posix" and source_root.anchor != "/")
        ):
            raise ValueError("Local Package Source root must be absolute")
        if not isinstance(policy_revision, str) or not policy_revision:
            raise ValueError("Local Package Source policy revision is required")
        if not isinstance(authority_id, str) or not authority_id:
            raise ValueError("Local Package Source authority id is required")
        if type(capture_epoch) is not int or capture_epoch < 1:
            raise ValueError("Local Package Source capture epoch is invalid")
        self._source_root = source_root
        self._policy_revision = policy_revision
        self._authority_id = authority_id
        self._capture_epoch = capture_epoch
        self._allowed_digests: dict[str, str] = {}
        for identity, digest in allowed_digests.items():
            if not isinstance(identity, str):
                raise ValueError("Local Package Source identity is invalid")
            _validate_path(identity, source_root)
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                raise ValueError("Local Package Source digest is invalid")
            self._allowed_digests[identity] = digest

    def authorize(self, request: PackageAcquisitionRequestV1) -> _LocalWheelStream:
        if not isinstance(request, PackageAcquisitionRequestV1):
            raise TypeError("Package acquisition request is required")
        identity = request.canonical_source_identity
        digest = self._allowed_digests.get(identity)
        if (
            digest is None
            or request.policy_revision != self._policy_revision
            or request.credential_reference is not None
            or request.requested_locator_digest
            != sha256(identity.encode("utf-8")).hexdigest()
        ):
            raise _source_refusal("Local Package Source is not authorized")
        return _LocalWheelStream(
            source=Path(identity),
            envelope=AuthenticatedSourceEnvelopeV1(
                operation_id=request.operation_id,
                node_id=request.node_id,
                canonical_source_identity=identity,
                origin_kind="local",
                authentication_decision="authorized",
                authority_id=self._authority_id,
                requested_locator_digest=request.requested_locator_digest,
                expected_artifact_digest=digest,
                redirect_policy_revision="local-source:no-redirects:1",
                policy_revision=self._policy_revision,
                capture_epoch=self._capture_epoch,
            ),
        )

    def verify_pinned_bytes(
        self, canonical_source_identity: str, *, max_bytes: int
    ) -> PackagePinnedLocalWheelSourceProofV1:
        """Read without owner writes; acquisition must reverify after this check."""

        if type(max_bytes) is not int or not 0 < max_bytes <= 1024 * 1024 * 1024:
            raise ValueError("Pinned Source proof byte limit is invalid")
        if not isinstance(canonical_source_identity, str):
            raise ValueError("Pinned Source proof identity is invalid")
        expected = self._allowed_digests.get(canonical_source_identity)
        if expected is None:
            raise PackagePinnedSourceProofError(
                "Local Package Source is not authorized",
                code="package_source_unauthorized",
            )
        digest = sha256()
        byte_count = 0
        try:
            descriptor = open_regular_no_follow(Path(canonical_source_identity))
            with os.fdopen(descriptor, "rb") as source:
                while chunk := source.read(min(_CHUNK_SIZE, max_bytes - byte_count + 1)):
                    byte_count += len(chunk)
                    if byte_count > max_bytes:
                        raise PackagePinnedSourceProofError(
                            "Local Package Source exceeds the proof byte limit",
                            code="package_source_size_limit",
                        )
                    digest.update(chunk)
        except OSError as exc:
            raise PackagePinnedSourceProofError(
                "Local Package Source identity changed",
                code="package_source_provenance_changed",
            ) from exc
        actual = digest.hexdigest()
        if actual != expected:
            raise PackagePinnedSourceProofError(
                "Local Package Source bytes changed",
                code="package_source_digest_mismatch",
            )
        return PackagePinnedLocalWheelSourceProofV1(
            source_ref=sha256(canonical_source_identity.encode("utf-8")).hexdigest(),
            artifact_digest=actual,
            byte_count=byte_count,
            policy_revision=self._policy_revision,
            authority_id=self._authority_id,
            capture_epoch=self._capture_epoch,
        )


class _LocalWheelStream:
    def __init__(
        self, *, source: Path, envelope: AuthenticatedSourceEnvelopeV1
    ) -> None:
        self._source = source
        self.envelope = envelope

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        try:
            fd = open_regular_no_follow(self._source)
        except OSError as exc:
            raise PackageAcquisitionError(
                "Local Package Source identity changed",
                code="package_source_provenance_changed",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            ) from exc
        with os.fdopen(fd, "rb") as source:
            sink.begin_request()
            while chunk := source.read(_CHUNK_SIZE):
                sink.write(chunk)
        return SourceAdapterResultV1(
            disposition="complete", adapter_revision="local-wheel-source:1"
        )


def _validate_path(identity: str, root: Path) -> None:
    path = Path(identity)
    if (
        not path.is_absolute()
        or (os.name == "posix" and path.anchor != "/")
        or os.path.normpath(identity) != identity
        or canonicalize_source_identity(identity) != identity
        or path.suffix != ".whl"
    ):
        raise ValueError("Local Package Source identity is not a canonical Wheel path")
    if os.path.normpath(str(root)) != str(root):
        raise ValueError("Local Package Source root is not canonical")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Local Package Source escapes configured root") from exc
    if not relative.parts:
        raise ValueError("Local Package Source must be below configured root")


def open_regular_no_follow(path: Path) -> int:
    """Open a regular file through native no-follow directory descriptors."""

    if os.name == "nt":
        if (
            not supports_windows_rooted_io()
            or not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
        ):
            raise OSError("Windows local Package Source path is invalid")
        parent = _PinnedWindowsAuthority.open(path.parent)
        try:
            descriptor = open_windows_regular_file_at(
                parent.descriptor,
                path.name,
                create_new=False,
                write=False,
            )
            try:
                parent.assert_visible()
                return descriptor
            except BaseException:
                os.close(descriptor)
                raise
        finally:
            parent.close()
    if os.name != "posix":
        raise OSError("Rooted local Package Source is unavailable")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    parent_fd = os.open("/", directory_flags)
    try:
        for component in path.parts[1:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        file_fd = os.open(path.name, file_flags, dir_fd=parent_fd)
        try:
            regular = stat.S_ISREG(os.fstat(file_fd).st_mode)
        except BaseException:
            os.close(file_fd)
            raise
        if not regular:
            os.close(file_fd)
            raise OSError("Local Package Source is not a regular file")
        return file_fd
    finally:
        os.close(parent_fd)


def _source_refusal(message: str) -> PackageAcquisitionError:
    return PackageAcquisitionError(
        message,
        code="package_source_unauthorized",
        stage="acquiring",
        retryable=False,
        consumed_bytes=0,
    )


__all__ = [
    "PackagePinnedLocalWheelSourceAuthority",
    "PackagePinnedLocalWheelSourceProofV1",
    "PackagePinnedSourceProofError",
    "open_regular_no_follow",
]
