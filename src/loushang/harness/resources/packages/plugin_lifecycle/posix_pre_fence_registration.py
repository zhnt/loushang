"""Linux pre-fence process liveness under the native cutover authority root.

Registrations must be acquired before a legacy runtime touches Package state
and held for its lifetime. The cutover owner must use this same authority root
so its native root revalidation also covers the held launch barrier.
This owner cannot discover binaries that bypass registration; Product launch
coverage and supervisor downgrade refusal are separate deployment gates.
"""

from __future__ import annotations

import errno
import os
import re
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from hashlib import sha256
from pathlib import Path
from threading import Lock

from loushang.harness.journal import (
    JournalLockUnavailable,
    journal_file_lock_at,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_coordination import (
    PackagePreFenceRegistrationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore import (
    _native_identity,
    _open_directory_at,
    _PinnedRoot,
    _require_private_directory,
    _supports_posix_rooted_io,
    _validated_root_path,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

if os.name == "posix":
    import fcntl as _fcntl
else:  # pragma: no cover - imported during Windows collection
    _fcntl = None  # type: ignore[assignment]

_REGISTRATIONS_NAME = "pre-fence-registrations"
_REGISTRATION_NAME = re.compile(r"([0-9a-f]{64})\.lease\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class PackagePosixPreFenceRegistrationError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackagePosixPreFenceRegistrationHandle:
    """Process-held liveness capability; release only after old writes stop."""

    def __init__(
        self,
        registration_id: str,
        lock: AbstractContextManager[None],
    ) -> None:
        self.registration_id = registration_id
        self._lock = lock
        self._mutex = Lock()
        self._released = False

    def release(self) -> None:
        with self._mutex:
            if not self._released:
                self._lock.__exit__(None, None, None)
                self._released = True

    def __enter__(self) -> PackagePosixPreFenceRegistrationHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PackagePosixPreFenceRegistrationOwner:
    """Block cooperative launches and project their complete live set."""

    def __init__(
        self,
        authority_root: str | Path,
        *,
        store_id: str,
        fences: PackageEpochFenceJournal,
    ) -> None:
        if not sys.platform.startswith("linux") or not _supports_posix_rooted_io():
            raise OSError("Linux pre-fence registration is unavailable")
        if not isinstance(store_id, str) or _SAFE_ID.fullmatch(store_id) is None:
            raise ValueError("Pre-fence Store identity is invalid")
        if not isinstance(fences, PackageEpochFenceJournal):
            raise TypeError("Pre-fence epoch journal is required")
        self.authority_root = _validated_root_path(
            authority_root, name="pre-fence authority"
        )
        self.store_id = store_id
        self._fences = fences
        root = _PinnedRoot.open(self.authority_root)
        try:
            with suppress(FileExistsError):
                os.mkdir(_REGISTRATIONS_NAME, mode=0o700, dir_fd=root.descriptor)
            registrations_fd = _open_directory_at(
                root.descriptor, _REGISTRATIONS_NAME
            )
            try:
                _require_private_directory(registrations_fd)
                self._registration_identity = _native_identity(
                    os.fstat(registrations_fd)
                )
            finally:
                os.close(registrations_fd)
            os.fsync(root.descriptor)
            root.assert_visible()
            self._root_identities = root.identities
        finally:
            root.close()

    def register(
        self, *, startup_id: str
    ) -> PackagePosixPreFenceRegistrationHandle:
        if not isinstance(startup_id, str) or _SAFE_ID.fullmatch(startup_id) is None:
            raise ValueError("Pre-fence startup identity is invalid")
        registration_id = sha256(
            canonical_json_bytes(
                {
                    "domain": "loushang.package-pre-fence-registration/v1",
                    "storeId": self.store_id,
                    "startupId": startup_id,
                }
            )
        ).hexdigest()
        root, registrations_fd = self._open()
        lock: AbstractContextManager[None] | None = None
        acquired = False
        try:
            _flock(root.descriptor, exclusive=False, blocking=False)
            try:
                if self._fences.current(self.store_id) is not None:
                    raise PackagePosixPreFenceRegistrationError(
                        "Legacy Package runtime is fenced",
                        code="package_runtime_epoch_unsupported",
                    )
                lock = journal_file_lock_at(
                    registrations_fd,
                    registration_id + ".lease",
                    "exclusive",
                    blocking=False,
                    create=True,
                )
                try:
                    lock.__enter__()
                except JournalLockUnavailable as exc:
                    raise PackagePosixPreFenceRegistrationError(
                        "Pre-fence startup is already registered",
                        code="package_pre_fence_registration_active",
                    ) from exc
                acquired = True
                if self._fences.current(self.store_id) is not None:
                    raise PackagePosixPreFenceRegistrationError(
                        "Legacy Package runtime became fenced",
                        code="package_runtime_epoch_unsupported",
                    )
                root.assert_visible()
                return PackagePosixPreFenceRegistrationHandle(
                    registration_id, lock
                )
            finally:
                _unlock(root.descriptor)
        except BaseException:
            if acquired and lock is not None:
                lock.__exit__(None, None, None)
            raise
        finally:
            os.close(registrations_fd)
            root.close()

    @contextmanager
    def exclusive_quiescence(
        self, *, store_id: str
    ) -> Iterator[PackagePreFenceRegistrationSnapshotV1]:
        if store_id != self.store_id:
            raise ValueError("Pre-fence Store changed")
        root, registrations_fd = self._open()
        try:
            _flock(root.descriptor, exclusive=True, blocking=False)
            try:
                names = sorted(os.listdir(registrations_fd))
                active = []
                for name in names:
                    matched = _REGISTRATION_NAME.fullmatch(name)
                    if matched is None:
                        raise OSError("Pre-fence registration set is invalid")
                    try:
                        with journal_file_lock_at(
                            registrations_fd,
                            name,
                            "exclusive",
                            blocking=False,
                        ):
                            pass
                    except JournalLockUnavailable:
                        active.append(matched.group(1))
                root.assert_visible()
                yield PackagePreFenceRegistrationSnapshotV1(
                    store_id=self.store_id,
                    owner_revision=len(names) + 1,
                    active_registration_ids=tuple(active),
                )
            finally:
                _unlock(root.descriptor)
        finally:
            os.close(registrations_fd)
            root.close()

    def _open(self) -> tuple[_PinnedRoot, int]:
        root = _PinnedRoot.open(
            self.authority_root, expected_identities=self._root_identities
        )
        registrations_fd: int | None = None
        try:
            registrations_fd = _open_directory_at(
                root.descriptor, _REGISTRATIONS_NAME
            )
            if _native_identity(os.fstat(registrations_fd)) != self._registration_identity:
                raise OSError("Pre-fence registration root changed")
            _require_private_directory(registrations_fd)
            return root, registrations_fd
        except BaseException:
            if registrations_fd is not None:
                os.close(registrations_fd)
            root.close()
            raise


def _flock(descriptor: int, *, exclusive: bool, blocking: bool) -> None:
    if _fcntl is None:
        raise OSError("Linux directory flock is unavailable")
    operation = _fcntl.LOCK_EX if exclusive else _fcntl.LOCK_SH
    if not blocking:
        operation |= _fcntl.LOCK_NB
    try:
        _fcntl.flock(descriptor, operation)
    except OSError as exc:
        if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}:
            raise PackagePosixPreFenceRegistrationError(
                "Pre-fence launch barrier is busy",
                code="package_pre_fence_launch_busy",
            ) from exc
        raise


def _unlock(descriptor: int) -> None:
    if _fcntl is None:
        raise OSError("Linux directory flock is unavailable")
    _fcntl.flock(descriptor, _fcntl.LOCK_UN)


__all__ = [
    "PackagePosixPreFenceRegistrationError",
    "PackagePosixPreFenceRegistrationHandle",
    "PackagePosixPreFenceRegistrationOwner",
]
