"""Windows-native offline epoch cutover for PLC9B4c2.

The durable head of ``PackageEpochFenceJournal`` remains the only current-root
pointer. A fresh sibling namespace is created through rooted Windows handles;
publishing the adjacent fence is the single atomic visibility edge.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceError,
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverCoordinationPort,
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotPort,
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverFailureV1,
    PackagePosixEpochCutoverRequestV1,
    PackagePosixEpochCutoverResultV1,
    PackagePosixEpochRootSwitchReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_listdir_at,
    windows_rmdir_at,
)

# B4c1 froze a pathless cross-platform wire shape before the Windows backend
# existed. Keep one schema and one fingerprint domain; the platform-specific
# names below are internal aliases, not a second interpretation of the record.
PackageWindowsEpochCutoverRequestV1: TypeAlias = PackagePosixEpochCutoverRequestV1
PackageWindowsEpochRootSwitchReceiptV1: TypeAlias = (
    PackagePosixEpochRootSwitchReceiptV1
)
PackageWindowsEpochCutoverFailureV1: TypeAlias = PackagePosixEpochCutoverFailureV1
PackageWindowsEpochCutoverResultV1: TypeAlias = PackagePosixEpochCutoverResultV1

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_NativeIdentity = tuple[int, int]


class PackageWindowsEpochCutoverError(RuntimeError):
    """Fail-closed Windows cutover refusal with one stable code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageWindowsEpochCutoverOwner:
    """Configured Windows capability owner; public records remain pathless."""

    def __init__(
        self,
        authority_root: str | Path,
        *,
        store_id: str,
        epoch_journal: PackageEpochFenceJournal,
        coordination: PackageEpochCutoverCoordinationPort,
        snapshots: PackageEpochCutoverSnapshotPort,
        legacy_root_name: str = "legacy",
        epochs_root_name: str = "epochs",
        before_fence_probe: Callable[[], None] | None = None,
    ) -> None:
        if os.name != "nt" or not supports_windows_rooted_io():
            raise PackageWindowsEpochCutoverError(
                "Windows Package epoch cutover is unavailable",
                code="package_epoch_cutover_unavailable",
            )
        if not isinstance(authority_root, (str, Path)):
            raise TypeError("Package epoch authority root must be a filesystem path")
        raw_root = Path(authority_root)
        if (
            not raw_root.is_absolute()
            or ".." in raw_root.parts
            or not raw_root.anchor
            or raw_root == Path(raw_root.anchor)
        ):
            raise PackageWindowsEpochCutoverError(
                "Package epoch authority root must be absolute and normalized",
                code="package_epoch_cutover_identity_changed",
            )
        _require_safe_id(store_id, name="Package store identity")
        _require_component(legacy_root_name, name="legacy Package root name")
        _require_component(epochs_root_name, name="Package epochs root name")
        if legacy_root_name == epochs_root_name:
            raise ValueError("Legacy and epoch Package roots must be distinct")
        if not isinstance(epoch_journal, PackageEpochFenceJournal):
            raise TypeError("Package epoch fence journal is required")
        if not callable(getattr(coordination, "exclusive_quiescence", None)):
            raise TypeError("Package epoch coordination owner is required")
        if not callable(getattr(snapshots, "capture", None)):
            raise TypeError("Package epoch snapshot owner is required")
        if before_fence_probe is not None and not callable(before_fence_probe):
            raise TypeError("Package epoch pre-fence probe must be callable")
        self._root = raw_root
        self._store_id = store_id
        self._journal = epoch_journal
        self._coordination = coordination
        self._snapshots = snapshots
        self._legacy_name = legacy_root_name
        self._epochs_name = epochs_root_name
        self._before_fence_probe = before_fence_probe
        pinned = _PinnedWindowsAuthority.open(self._root)
        try:
            legacy_fd = pinned.open_authority_child(self._legacy_name)
            epochs_fd = pinned.open_authority_child(self._epochs_name)
            try:
                self._authority_identities = pinned.identities
                self._legacy_genesis_identity = _directory_identity(legacy_fd)
                self._epochs_identity = _directory_native_identity(epochs_fd)
            finally:
                os.close(epochs_fd)
                os.close(legacy_fd)
        except Exception as exc:
            raise _native_error(exc) from exc
        finally:
            pinned.close()

    def current_root_identity(self) -> str:
        current = self._journal.current(self._store_id)
        pinned = self._open_pinned()
        root_fd: int | None = None
        epochs_fd: int | None = None
        try:
            epochs_fd = pinned.open_authority_child(
                self._epochs_name,
                expected_identity=self._epochs_identity,
            )
            if current is None:
                root_fd = pinned.open_authority_child(self._legacy_name)
                observed = _directory_identity(root_fd)
                if observed != self._legacy_genesis_identity:
                    raise _identity_changed()
                return observed
            root_fd = _open_directory_at(
                epochs_fd,
                current.request.namespace_id,
            )
            observed = _directory_identity(root_fd)
            if observed != current.fenced_root_identity:
                raise _identity_changed()
            return observed
        except PackageWindowsEpochCutoverError:
            raise
        except Exception as exc:
            raise _native_error(exc) from exc
        finally:
            if root_fd is not None:
                os.close(root_fd)
            if epochs_fd is not None:
                os.close(epochs_fd)
            pinned.close()

    def cutover(
        self,
        request: PackageWindowsEpochCutoverRequestV1,
    ) -> PackageWindowsEpochCutoverResultV1:
        if not isinstance(request, PackageWindowsEpochCutoverRequestV1):
            raise TypeError("Windows Package epoch cutover request is required")
        if request.store_id != self._store_id:
            raise PackageWindowsEpochCutoverError(
                "Package epoch cutover store changed",
                code="package_epoch_fence_stale",
            )
        current = self._journal.current(self._store_id)
        replay = self._exact_replay(request, current)
        if replay is not None:
            return replay
        self._validate_prior(request, current)
        try:
            exclusive = self._coordination.exclusive_quiescence(
                store_id=self._store_id
            )
            with exclusive as quiescence:
                locked_current = self._journal.current(self._store_id)
                replay = self._exact_replay(request, locked_current)
                if replay is not None:
                    return replay
                self._validate_prior(request, locked_current)
                return self._cutover_exclusive(
                    request,
                    locked_current,
                    quiescence,
                )
        except PackageWindowsEpochCutoverError:
            raise
        except PackageEpochFenceError as exc:
            raise PackageWindowsEpochCutoverError(
                "Package epoch fence compare-and-swap failed",
                code=exc.code,
            ) from exc
        except Exception as exc:
            raise _native_error(exc) from exc

    def _cutover_exclusive(
        self,
        request: PackageWindowsEpochCutoverRequestV1,
        current: PackageEpochFenceReceiptV1 | None,
        quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    ) -> PackageWindowsEpochCutoverResultV1:
        if not isinstance(quiescence, PackageEpochCutoverQuiescenceReceiptV1):
            raise PackageWindowsEpochCutoverError(
                "Package quiescence evidence is invalid",
                code="package_epoch_cutover_quiescence_unavailable",
            )
        if quiescence.store_id != self._store_id:
            raise PackageWindowsEpochCutoverError(
                "Package quiescence store changed",
                code="package_epoch_cutover_quiescence_unavailable",
            )
        if not quiescence.is_quiescent:
            return PackageWindowsEpochCutoverResultV1.rejected(
                request,
                evidence_ref=quiescence.first_active_evidence,
            )
        if self._journal.current(self._store_id) != current:
            raise PackageWindowsEpochCutoverError(
                "Package epoch changed before native cutover",
                code="package_epoch_fence_stale",
            )

        pinned = self._open_pinned()
        epochs_fd: int | None = None
        legacy_fd: int | None = None
        new_fd: int | None = None
        new_identity: str | None = None
        created = False
        fenced = False
        try:
            epochs_fd = pinned.open_authority_child(
                self._epochs_name,
                expected_identity=self._epochs_identity,
            )
            if current is None:
                legacy_fd = pinned.open_authority_child(self._legacy_name)
            else:
                legacy_fd = _open_directory_at(
                    epochs_fd,
                    current.request.namespace_id,
                )
            observed_legacy = _directory_identity(legacy_fd)
            if observed_legacy != request.expected_legacy_root_identity:
                raise _identity_changed()
            snapshot = self._snapshots.capture(
                store_id=self._store_id,
                legacy_root_identity=observed_legacy,
                quiescence_receipt_id=quiescence.receipt_id,
            )
            _validate_snapshot(snapshot, request, quiescence)
            try:
                new_fd = _open_directory_at(
                    epochs_fd,
                    request.namespace_id,
                    create_new=True,
                    share_delete=True,
                )
                created = True
            except FileExistsError as exc:
                raise PackageWindowsEpochCutoverError(
                    "Package epoch namespace already exists",
                    code="package_epoch_cutover_namespace_conflict",
                ) from exc
            new_identity = _directory_identity(new_fd)
            if new_identity == observed_legacy:
                raise _identity_changed()
            windows_flush_directory(new_fd)
            windows_flush_directory(epochs_fd)
            switch = PackageWindowsEpochRootSwitchReceiptV1.create(
                request,
                fenced_root_identity=new_identity,
                quiescence_receipt_id=quiescence.receipt_id,
                snapshot_receipt_id=snapshot.receipt_id,
            )
            epoch_request = PackageEpochFenceRequestV1.create(
                store_id=self._store_id,
                prior_fence=current,
                legacy_root_identity=observed_legacy,
                fenced_root_identity=new_identity,
                namespace_id=request.namespace_id,
                minimum_runtime_version=request.minimum_runtime_version,
                minimum_runtime_protocol_epoch=(
                    request.minimum_runtime_protocol_epoch
                ),
                quiescence_receipt_id=quiescence.receipt_id,
                snapshot_receipt_id=snapshot.receipt_id,
                root_switch_receipt_id=switch.switch_receipt_id,
            )
            if self._before_fence_probe is not None:
                self._before_fence_probe()
            pinned.assert_visible()
            if _directory_identity(legacy_fd) != observed_legacy:
                raise _identity_changed()
            if _directory_identity(new_fd) != new_identity:
                raise _identity_changed()
            if windows_listdir_at(new_fd):
                raise PackageWindowsEpochCutoverError(
                    "Fresh Package epoch namespace is not empty",
                    code="package_epoch_cutover_namespace_conflict",
                )
            visible_epochs = pinned.open_authority_child(
                self._epochs_name,
                expected_identity=self._epochs_identity,
            )
            try:
                visible_new = _open_directory_at(
                    visible_epochs,
                    request.namespace_id,
                    share_delete=True,
                )
                try:
                    if _directory_identity(visible_new) != new_identity:
                        raise _identity_changed()
                finally:
                    os.close(visible_new)
            finally:
                os.close(visible_epochs)
            if self._journal.current(self._store_id) != current:
                raise PackageWindowsEpochCutoverError(
                    "Package epoch changed before fence publication",
                    code="package_epoch_fence_stale",
                )
            fence = self._journal.publish(epoch_request)
            fenced = True
            if fence.request != epoch_request:
                raise PackageWindowsEpochCutoverError(
                    "Package epoch fence publication changed",
                    code="package_epoch_fence_stale",
                )
            return PackageWindowsEpochCutoverResultV1.fenced(
                request,
                fence=fence,
                switch_receipt=switch,
            )
        except Exception:
            if created and not fenced and epochs_fd is not None and new_identity:
                if new_fd is not None:
                    os.close(new_fd)
                    new_fd = None
                _remove_created_epoch(
                    epochs_fd,
                    request.namespace_id,
                    expected_identity=new_identity,
                )
            raise
        finally:
            if new_fd is not None:
                os.close(new_fd)
            if legacy_fd is not None:
                os.close(legacy_fd)
            if epochs_fd is not None:
                os.close(epochs_fd)
            pinned.close()

    def _exact_replay(
        self,
        request: PackageWindowsEpochCutoverRequestV1,
        current: PackageEpochFenceReceiptV1 | None,
    ) -> PackageWindowsEpochCutoverResultV1 | None:
        if current is None or current.epoch != request.next_epoch:
            return None
        epoch_request = current.request
        if (
            epoch_request.store_id != request.store_id
            or epoch_request.prior_epoch != request.prior_epoch
            or epoch_request.prior_fence_id != request.prior_fence_id
            or epoch_request.prior_fence_revision != request.prior_fence_revision
            or epoch_request.legacy_root_identity
            != request.expected_legacy_root_identity
            or epoch_request.namespace_id != request.namespace_id
            or epoch_request.minimum_runtime_version
            != request.minimum_runtime_version
            or epoch_request.minimum_runtime_protocol_epoch
            != request.minimum_runtime_protocol_epoch
        ):
            return None
        if self.current_root_identity() != epoch_request.fenced_root_identity:
            raise _identity_changed()
        switch = PackageWindowsEpochRootSwitchReceiptV1.create(
            request,
            fenced_root_identity=epoch_request.fenced_root_identity,
            quiescence_receipt_id=epoch_request.quiescence_receipt_id,
            snapshot_receipt_id=epoch_request.snapshot_receipt_id,
        )
        if switch.switch_receipt_id != epoch_request.root_switch_receipt_id:
            raise _identity_changed()
        if self._journal.current(self._store_id) != current:
            raise PackageWindowsEpochCutoverError(
                "Package epoch changed during exact replay",
                code="package_epoch_fence_stale",
            )
        return PackageWindowsEpochCutoverResultV1.fenced(
            request,
            fence=current,
            switch_receipt=switch,
        )

    def _validate_prior(
        self,
        request: PackageWindowsEpochCutoverRequestV1,
        current: PackageEpochFenceReceiptV1 | None,
    ) -> None:
        if current is None:
            valid = (
                request.prior_epoch == 0
                and request.prior_fence_id is None
                and request.prior_fence_revision == 0
            )
        else:
            valid = (
                request.prior_epoch == current.epoch
                and request.prior_fence_id == current.fence_id
                and request.prior_fence_revision == current.fence_revision
                and request.expected_legacy_root_identity
                == current.fenced_root_identity
            )
        if not valid:
            raise PackageWindowsEpochCutoverError(
                "Package epoch cutover compare-and-swap failed",
                code="package_epoch_fence_stale",
            )

    def _open_pinned(self) -> _PinnedWindowsAuthority:
        try:
            return _PinnedWindowsAuthority.open(
                self._root,
                expected_identities=self._authority_identities,
            )
        except Exception as exc:
            raise _native_error(exc) from exc


class _PinnedWindowsAuthority:
    def __init__(
        self,
        root: Path,
        descriptors: tuple[int, ...],
        identities: tuple[_NativeIdentity, ...],
    ) -> None:
        self._root = root
        self._descriptors = descriptors
        self.identities = identities

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        expected_identities: tuple[_NativeIdentity, ...] | None = None,
    ) -> _PinnedWindowsAuthority:
        descriptors = _open_ancestor_chain(root)
        try:
            identities = tuple(
                _directory_native_identity(descriptor)
                for descriptor in descriptors
            )
            if expected_identities is not None and identities != expected_identities:
                raise _identity_changed()
            pinned = cls(root, descriptors, identities)
            pinned.assert_visible()
            return pinned
        except Exception:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            raise

    @property
    def descriptor(self) -> int:
        return self._descriptors[-1]

    def open_authority_child(
        self,
        name: str,
        *,
        expected_identity: _NativeIdentity | None = None,
    ) -> int:
        descriptor = _open_directory_at(self.descriptor, name)
        if (
            expected_identity is not None
            and _directory_native_identity(descriptor) != expected_identity
        ):
            os.close(descriptor)
            raise _identity_changed()
        return descriptor

    def assert_visible(self) -> None:
        for descriptor, expected in zip(
            self._descriptors,
            self.identities,
            strict=True,
        ):
            if _directory_native_identity(descriptor) != expected:
                raise _identity_changed()
        visible = _open_ancestor_chain(self._root)
        try:
            observed = tuple(_directory_native_identity(fd) for fd in visible)
            if observed != self.identities:
                raise _identity_changed()
        finally:
            for descriptor in reversed(visible):
                os.close(descriptor)

    def close(self) -> None:
        while self._descriptors:
            descriptor, self._descriptors = (
                self._descriptors[-1],
                self._descriptors[:-1],
            )
            os.close(descriptor)


def _open_ancestor_chain(root: Path) -> tuple[int, ...]:
    descriptors: list[int] = []
    try:
        current = open_windows_directory(
            Path(root.anchor),
            share_delete=False,
            writable=False,
        )
        descriptors.append(current)
        components = root.parts[1:]
        for index, component in enumerate(components):
            current = open_windows_directory(
                component,
                dir_fd=current,
                share_delete=False,
                writable=index == len(components) - 1,
            )
            descriptors.append(current)
        return tuple(descriptors)
    except Exception:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _open_directory_at(
    parent_fd: int,
    name: str,
    *,
    create_new: bool = False,
    share_delete: bool = False,
) -> int:
    _require_component(name, name="Package namespace component")
    descriptor = open_windows_directory(
        name,
        dir_fd=parent_fd,
        create_new=create_new,
        share_delete=share_delete,
        writable=True,
    )
    try:
        _require_direct_directory(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _remove_created_epoch(
    epochs_fd: int,
    namespace_id: str,
    *,
    expected_identity: str,
) -> None:
    descriptor: int | None = None
    try:
        descriptor = _open_directory_at(
            epochs_fd,
            namespace_id,
            share_delete=True,
        )
        if _directory_identity(descriptor) != expected_identity:
            raise _identity_changed()
        if windows_listdir_at(descriptor):
            raise _identity_changed()
        os.close(descriptor)
        descriptor = None
        windows_rmdir_at(epochs_fd, namespace_id)
        windows_flush_directory(epochs_fd)
    except Exception as exc:
        raise PackageWindowsEpochCutoverError(
            "Unfenced Package epoch residue cannot be removed safely",
            code="package_epoch_cutover_cleanup_failed",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_snapshot(
    snapshot: object,
    request: PackageWindowsEpochCutoverRequestV1,
    quiescence: PackageEpochCutoverQuiescenceReceiptV1,
) -> None:
    if not isinstance(snapshot, PackageEpochCutoverSnapshotReceiptV1) or (
        snapshot.store_id != request.store_id
        or snapshot.legacy_root_identity
        != request.expected_legacy_root_identity
        or snapshot.quiescence_receipt_id != quiescence.receipt_id
    ):
        raise PackageWindowsEpochCutoverError(
            "Package epoch snapshot evidence is invalid",
            code="package_epoch_cutover_snapshot_unavailable",
        )


def _directory_native_identity(descriptor: int) -> _NativeIdentity:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise _identity_changed()
    return int(metadata.st_dev), int(metadata.st_ino)


def _directory_identity(descriptor: int) -> str:
    device, inode = _directory_native_identity(descriptor)
    return _fingerprint(
        {
            "device": device,
            "fileType": "directory",
            "inode": inode,
            "identityVersion": 1,
        }
    )


def _require_direct_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise _identity_changed()


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_reparse_tag", 0)
        or getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _identity_changed() -> PackageWindowsEpochCutoverError:
    return PackageWindowsEpochCutoverError(
        "Windows Package epoch root identity changed",
        code="package_epoch_cutover_identity_changed",
    )


def _native_error(exc: BaseException) -> PackageWindowsEpochCutoverError:
    if isinstance(exc, PackageWindowsEpochCutoverError):
        return exc
    return PackageWindowsEpochCutoverError(
        "Windows Package epoch cutover failed closed",
        code=(
            "package_epoch_cutover_identity_changed"
            if isinstance(exc, OSError)
            else "package_epoch_cutover_unavailable"
        ),
    )


def _fingerprint(value: object) -> str:
    from hashlib import sha256

    return sha256(canonical_json_bytes(value)).hexdigest()


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_component(value: str, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or _SAFE_COMPONENT.fullmatch(value) is None
        or value in {".", ".."}
    ):
        raise ValueError(f"{name} is invalid")


__all__ = [
    "PackageWindowsEpochCutoverError",
    "PackageWindowsEpochCutoverFailureV1",
    "PackageWindowsEpochCutoverOwner",
    "PackageWindowsEpochCutoverRequestV1",
    "PackageWindowsEpochCutoverResultV1",
    "PackageWindowsEpochRootSwitchReceiptV1",
]
