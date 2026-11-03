"""Windows pre-fence process registration under the native Product control.

Every cooperative legacy process holds a liveness lock before touching old
Package state. First-B cutover must hold the same control coordination lock
while checking the complete registration set and publishing its first fence.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import BinaryIO

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import JournalLockUnavailable, journal_file_lock_at
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_coordination import (
    PackagePreFenceRegistrationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _directory_native_identity,
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_listdir_at,
)

_REGISTRATIONS_PREFIX = "pre-fence-registrations-"
_REGISTRATION_NAME = re.compile(r"([0-9a-f]{64})\.lease\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_COORDINATION_NAME = "coordination.lock"
_RUNTIME_JOURNAL_NAME = "runtime-leases.jsonl"


class PackageWindowsPreFenceRegistrationError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageWindowsPreFenceRegistrationHandle:
    """Keep one old process's native liveness lock until it stops writing."""

    def __init__(
        self, registration_id: str, lock: AbstractContextManager[BinaryIO]
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

    def __enter__(self) -> PackageWindowsPreFenceRegistrationHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PackageWindowsPreFenceRegistrationOwner:
    """Block new legacy launches during first-B cutover and prove liveness."""

    def __init__(
        self,
        control_root: Path,
        *,
        store_id: str,
        fences: PackageEpochFenceJournal,
    ) -> None:
        if os.name != "nt" or not supports_windows_rooted_io():
            raise OSError("Windows pre-fence registration is unavailable")
        if (
            not isinstance(control_root, Path)
            or not control_root.is_absolute()
            or ".." in control_root.parts
            or control_root == Path(control_root.anchor)
            or not isinstance(store_id, str)
            or _SAFE_ID.fullmatch(store_id) is None
            or not isinstance(fences, PackageEpochFenceJournal)
            or fences.path != control_root / "epoch.jsonl"
        ):
            raise ValueError("Windows pre-fence authority is invalid")
        self.control_root = control_root
        self.store_id = store_id
        self.fences = fences
        self._registrations_name = (
            _REGISTRATIONS_PREFIX + sha256(store_id.encode("utf-8")).hexdigest()
        )
        with WindowsPrivateDirectoryAcl() as acl:
            root = _PinnedWindowsAuthority.open(control_root, read_control=True)
            try:
                acl.validate(root.descriptor)
                created = False
                try:
                    descriptor = open_windows_directory(
                        self._registrations_name,
                        dir_fd=root.descriptor,
                        create_new=True,
                        share_delete=False,
                        security_descriptor=acl.security_descriptor,
                        read_control=True,
                    )
                    created = True
                except FileExistsError:
                    descriptor = open_windows_directory(
                        self._registrations_name,
                        dir_fd=root.descriptor,
                        share_delete=False,
                        read_control=True,
                    )
                try:
                    acl.validate(descriptor)
                    self._registrations_identity = _directory_native_identity(
                        descriptor
                    )
                    if created:
                        windows_flush_directory(root.descriptor)
                    root.assert_visible()
                    self._root_identities = root.identities
                finally:
                    os.close(descriptor)
            finally:
                root.close()

    def register(self, *, startup_id: str) -> PackageWindowsPreFenceRegistrationHandle:
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
        root, registrations = self._open()
        lock: AbstractContextManager[BinaryIO] | None = None
        acquired = False
        try:
            with journal_file_lock_at(
                root.descriptor, _COORDINATION_NAME, "exclusive", create=True
            ):
                if self.fences.current(self.store_id) is not None:
                    raise PackageWindowsPreFenceRegistrationError(
                        "Legacy Package runtime is fenced",
                        code="package_runtime_epoch_unsupported",
                    )
                lock = journal_file_lock_at(
                    registrations,
                    registration_id + ".lease",
                    "exclusive",
                    blocking=False,
                    create=True,
                )
                try:
                    lock.__enter__()
                except JournalLockUnavailable as exc:
                    raise PackageWindowsPreFenceRegistrationError(
                        "Pre-fence startup is already registered",
                        code="package_pre_fence_registration_active",
                    ) from exc
                acquired = True
                if self.fences.current(self.store_id) is not None:
                    raise PackageWindowsPreFenceRegistrationError(
                        "Legacy Package runtime became fenced",
                        code="package_runtime_epoch_unsupported",
                    )
                root.assert_visible()
                return PackageWindowsPreFenceRegistrationHandle(registration_id, lock)
        except BaseException:
            if acquired and lock is not None:
                lock.__exit__(None, None, None)
            raise
        finally:
            os.close(registrations)
            root.close()

    @contextmanager
    def exclusive_quiescence(
        self, *, store_id: str
    ) -> Iterator[PackagePreFenceRegistrationSnapshotV1]:
        if store_id != self.store_id:
            raise ValueError("Pre-fence Store changed")
        root, registrations = self._open()
        try:
            with journal_file_lock_at(
                root.descriptor, _COORDINATION_NAME, "exclusive", create=True
            ):
                if self.fences.current(store_id) is not None:
                    raise PackageWindowsPreFenceRegistrationError(
                        "First-B cutover already has a fence",
                        code="package_runtime_epoch_unsupported",
                    )
                try:
                    stale_runtime = open_windows_regular_file_at(
                        root.descriptor,
                        _RUNTIME_JOURNAL_NAME,
                        create_new=False,
                        write=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    os.close(stale_runtime)
                    raise PackageWindowsPreFenceRegistrationError(
                        "First-B runtime lease history is unexpected",
                        code="package_pre_fence_runtime_history_present",
                    )
                names = tuple(sorted(windows_listdir_at(registrations)))
                active: list[str] = []
                for name in names:
                    matched = _REGISTRATION_NAME.fullmatch(name)
                    if matched is None:
                        raise OSError("Pre-fence registration set is invalid")
                    try:
                        with journal_file_lock_at(
                            registrations, name, "exclusive", blocking=False
                        ):
                            pass
                    except JournalLockUnavailable:
                        active.append(matched.group(1))
                root.assert_visible()
                yield PackagePreFenceRegistrationSnapshotV1(
                    store_id=store_id,
                    owner_revision=len(names) + 1,
                    active_registration_ids=tuple(active),
                )
        finally:
            os.close(registrations)
            root.close()

    def _open(self) -> tuple[_PinnedWindowsAuthority, int]:
        with WindowsPrivateDirectoryAcl() as acl:
            root = _PinnedWindowsAuthority.open(
                self.control_root,
                expected_identities=self._root_identities,
                read_control=True,
            )
            registrations: int | None = None
            try:
                acl.validate(root.descriptor)
                registrations = open_windows_directory(
                    self._registrations_name,
                    dir_fd=root.descriptor,
                    share_delete=False,
                    read_control=True,
                )
                acl.validate(registrations)
                if (
                    _directory_native_identity(registrations)
                    != self._registrations_identity
                ):
                    raise OSError("Pre-fence registration root changed")
                root.assert_visible()
                return root, registrations
            except BaseException:
                if registrations is not None:
                    os.close(registrations)
                root.close()
                raise


__all__ = [
    "PackageWindowsPreFenceRegistrationError",
    "PackageWindowsPreFenceRegistrationHandle",
    "PackageWindowsPreFenceRegistrationOwner",
]
