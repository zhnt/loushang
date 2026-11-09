"""Shared file consumption rules; native writers own physical handles."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Protocol

from loushang.harness.journal._io_loops import write_all

from ._materialization_shared import _root_untrusted
from .tree_transfer import PackagePhysicalStagingError, PackageVerifiedTreeEntryV1


class FileWritePort(Protocol):
    def require_open(self) -> None: ...

    def write(self, view: memoryview) -> int: ...

    def identity_matches(self) -> bool: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...

    def abort(self) -> None: ...


class VerifiedFileSink:
    def __init__(
        self,
        *,
        entry: PackageVerifiedTreeEntryV1,
        writer: FileWritePort,
        on_finished: Callable[[VerifiedFileSink], None],
    ) -> None:
        self._entry = entry
        self._writer = writer
        self._on_finished = on_finished
        self._digest = sha256()
        self._byte_count = 0
        self._finished = False

    def __enter__(self) -> VerifiedFileSink:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def write(self, chunk: bytes) -> None:
        self._require_open()
        if not isinstance(chunk, bytes):
            raise TypeError("Package Store sink accepts only bytes")
        self._byte_count += len(chunk)
        if self._byte_count > self._entry.byte_count:
            raise PackagePhysicalStagingError(
                "Package Store file exceeds verified size",
                code="package_artifact_identity_changed",
            )
        try:
            write_all(
                self._writer.write,
                chunk,
                message="Package Store write made no progress",
            )
        except OSError:
            raise _root_untrusted() from None
        self._digest.update(chunk)

    def finish(self) -> None:
        self._require_open()
        identity_matches = self._writer.identity_matches()
        if (
            self._byte_count != self._entry.byte_count
            or self._digest.hexdigest() != self._entry.content_digest
            or not identity_matches
        ):
            raise PackagePhysicalStagingError(
                "Package Store file changed from verified manifest",
                code="package_artifact_identity_changed",
            )
        try:
            self._writer.flush()
            self._writer.close()
        except OSError:
            raise _root_untrusted() from None
        self._finished = True
        self._on_finished(self)

    def abort(self) -> None:
        self._writer.abort()

    def _require_open(self) -> None:
        if self._finished:
            raise RuntimeError("Package Store file sink is closed")
        self._writer.require_open()


class ReuseFileSink:
    def __init__(
        self,
        *,
        entry: PackageVerifiedTreeEntryV1,
        on_finished: Callable[[ReuseFileSink], None],
    ) -> None:
        self._entry = entry
        self._on_finished = on_finished
        self._digest = sha256()
        self._byte_count = 0
        self._closed = False
        self._finished = False

    def __enter__(self) -> ReuseFileSink:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def write(self, chunk: bytes) -> None:
        if self._closed:
            raise RuntimeError("Package Store reuse sink is closed")
        if not isinstance(chunk, bytes):
            raise TypeError("Package Store sink accepts only bytes")
        self._byte_count += len(chunk)
        if self._byte_count > self._entry.byte_count:
            raise PackagePhysicalStagingError(
                "Reused Package file exceeds verified size",
                code="package_artifact_identity_changed",
            )
        self._digest.update(chunk)

    def finish(self) -> None:
        if self._closed:
            raise RuntimeError("Package Store reuse sink is closed")
        if (
            self._byte_count != self._entry.byte_count
            or self._digest.hexdigest() != self._entry.content_digest
        ):
            raise PackagePhysicalStagingError(
                "Reused Package file changed from verified manifest",
                code="package_artifact_identity_changed",
            )
        self._closed = True
        self._finished = True
        self._on_finished(self)

    def abort(self) -> None:
        self._closed = True
