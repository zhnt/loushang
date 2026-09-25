"""Product-configured, digest-pinned POSIX local Wheel Source adapter."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
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

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK_SIZE = 64 * 1024


class PackagePinnedLocalWheelSourceAuthority:
    """Authorize only exact Product-listed local paths with pinned contents.

    This adapter deliberately supports no network URL, credentials, or Windows
    path. The Package owner remains responsible for bounded streaming and
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
        if os.name != "posix" or not all(
            hasattr(os, name)
            for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_CLOEXEC")
        ):
            raise RuntimeError("Rooted local Package Source requires POSIX no-follow")
        if not isinstance(source_root, Path) or source_root.anchor != "/":
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


class _LocalWheelStream:
    def __init__(
        self, *, source: Path, envelope: AuthenticatedSourceEnvelopeV1
    ) -> None:
        self._source = source
        self.envelope = envelope

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        try:
            fd = _open_regular_no_follow(self._source)
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
        path.anchor != "/"
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


def _open_regular_no_follow(path: Path) -> int:
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


__all__ = ["PackagePinnedLocalWheelSourceAuthority"]
