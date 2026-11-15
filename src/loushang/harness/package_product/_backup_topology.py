"""Backup topology custody and read-only retention evidence for Package Product.

The two stateless operations reuse existing epoch, Journal, native and codec
owners. Topology reads retain their original wire/fence contract; retention
borrows the Product's read/GC authority without adding a store or manager.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        WindowsLocalWheelProductSessionOwner,
    )
    from loushang.harness.plugin_management._private_data_expiry import ExpiryPlan
    from loushang.harness.plugin_management.application import (
        PluginBackupRetentionSnapshotV1,
        PluginBackupRetentionStatus,
    )
    from loushang.harness.plugin_management.private_data_backup import R
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1
    from loushang.harness.resources.packages._private_tree_windows import (
        PrivateWindowsTreeIO,
    )

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
    inspect_windows_product_private_directory_identity,
)


def read_backup_topology(
    *,
    state_root: Path,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    | PackageProductWindowsFencedRuntimeOwner,
    expected: bytes,
    create_if_new: bool,
    file_name: str,
    maximum_bytes: int,
    maximum_inventory: int,
    blocking_history_prefix: str,
    label: str,
    absent_message: str,
    windows_receipts: WindowsPrivateReceiptIO,
) -> bytes:
    """Read, or durably publish and reread, one exact topology under its epoch."""
    epoch_runtime.assert_current()
    path = state_root / file_name
    if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
            windows_listdir_at,
        )

        with epoch_runtime.borrow_product_state_root_descriptor() as root:
            raw = windows_receipts.read_private_receipt(
                path,
                maximum_bytes=maximum_bytes,
                allow_unpublished_stage=create_if_new,
            )
            if raw is None:
                if not create_if_new or any(
                    name.casefold().startswith(blocking_history_prefix)
                    for name in windows_listdir_at(root)
                ):
                    raise ValueError(absent_message)
                windows_receipts.write_private_receipt(
                    path, expected, maximum_bytes=maximum_bytes
                )
                raw = windows_receipts.read_private_receipt(
                    path, maximum_bytes=maximum_bytes
                )
    elif isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        metadata = state_root.lstat()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        with closing_descriptor(os.open(state_root, flags)) as root_fd:
            opened = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise ValueError(f"{label} state root changed")
            with RootedFileIO(state_root, root_fd) as io:
                with io.bind(path, durable=True) as rooted:
                    try:
                        raw = rooted.read_bytes(max_bytes=maximum_bytes)
                    except FileNotFoundError:
                        names, complete = rooted.scan_sibling_names(
                            limit=maximum_inventory
                        )
                        if (
                            not create_if_new
                            or not complete
                            or any(
                                name.startswith(blocking_history_prefix)
                                for name in names
                            )
                        ):
                            raise ValueError(absent_message) from None
                        rooted.create_new(expected)
                        raw = rooted.read_bytes(max_bytes=maximum_bytes)
    else:
        raise TypeError(f"{label} requires a Product epoch")
    epoch_runtime.assert_current()
    if raw != expected:
        raise ValueError(f"{label} changed")
    return raw


class _BackupProductOwner(Protocol):
    @property
    def product(self) -> WindowsLocalWheelProductSessionOwner: ...


class _RestoreReadScope(Protocol):
    def _close(self) -> None: ...


class _ExpiryRetentionReceipt(Protocol):
    @property
    def receipt_id(self) -> str: ...


class _ExpiryRetentionEvent(Protocol):
    @property
    def phase(self) -> str: ...
    @property
    def plan(self) -> ExpiryPlan: ...
    @property
    def receipt(self) -> _ExpiryRetentionReceipt | None: ...


_RestoreT = TypeVar("_RestoreT", bound=_RestoreReadScope)
_EventT = TypeVar("_EventT", bound=_ExpiryRetentionEvent)


def read_windows_private_backup_retention(
    owner: _BackupProductOwner,
    key: PluginInstallationKeyV1,
    *,
    tree_io: PrivateWindowsTreeIO,
    restore_factory: Callable[[int], _RestoreT],
    scan_expiry: Callable[[_RestoreT], tuple[tuple[_EventT, ...], int | None]],
    tombstone_name: Callable[[_EventT], str],
    retained_receipts: Callable[
        [PluginInstallationKeyV1, str | None, str | None], tuple[R, ...]
    ],
    revision_for: Callable[
        [PluginBackupRetentionStatus, str | None, tuple[R, ...], str], str
    ],
    revision_prefix: str,
    label: str,
) -> PluginBackupRetentionSnapshotV1:
    """Read one Product's complete receipt-backed retention under its GC scope."""
    from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
    from loushang.harness.plugin_management.application import (
        PluginBackupRetentionRecordV1,
        PluginBackupRetentionSnapshotV1,
    )
    from loushang.harness.resources.packages._private_tree_windows import (
        private_windows_directory,
    )

    status: PluginBackupRetentionStatus = "unknown"
    expiry_receipt_id: str | None = None
    trust = "verified"
    receipts: tuple[R, ...] = ()
    owner.product.assert_private_data_read_authority_current()
    with owner.product.gc_gate.read_guard():
        try:
            state = owner.product.desired_state.snapshot().installation(key)
            state_identity = inspect_windows_product_private_directory_identity(
                owner.product.state_root
            )
            with WindowsPrivateDirectoryAcl() as state_acl:
                with private_windows_directory(
                    owner.product.state_root, acl=state_acl
                ) as fd:
                    if tree_io.directory_identity(fd) != state_identity:
                        raise ValueError(f"{label} expiry state changed")
                    restore = restore_factory(fd)
                    try:
                        events, staged = scan_expiry(restore)
                    finally:
                        restore._close()
            if (
                inspect_windows_product_private_directory_identity(
                    owner.product.state_root
                )
                != state_identity
            ):
                raise ValueError(f"{label} expiry state changed")
            if staged is not None:
                raise ValueError(f"{label} expiry event needs recovery")
            latest = events[-1] if events else None
            if latest is not None and latest.plan.installation_key != key:
                raise ValueError(f"{label} expiry Installation changed")
            if latest is not None and state.latest_instance_revision_ref is None:
                raise ValueError(f"{label} expiry Product history changed")
            pending = latest is not None and latest.phase in {"started", "renamed"}
            allowed_tombstone = (
                tombstone_name(latest) if pending and latest is not None else None
            )
            if state.latest_instance_revision_ref is not None:
                receipts = retained_receipts(
                    key,
                    allowed_tombstone,
                    latest.plan.backup_id if pending and latest is not None else None,
                )
            if (
                latest is not None
                and latest.phase in {"renamed", "completed"}
                and any(item.backup_id == latest.plan.backup_id for item in receipts)
            ):
                raise ValueError(f"{label} expired archive reappeared")
            if pending:
                status = "expiry_pending"
            elif receipts:
                status = "retained"
            elif latest is not None and latest.phase == "completed":
                if latest.receipt is None:
                    raise ValueError(f"{label} expiry receipt changed")
                status = "expired"
                expiry_receipt_id = latest.receipt.receipt_id
        except (OSError, ValueError):
            trust = "untrusted"
            receipts = ()
            status = "unknown"
            expiry_receipt_id = None
        revision = revision_for(status, expiry_receipt_id, receipts, trust)
    owner.product.assert_private_data_read_authority_current()
    return PluginBackupRetentionSnapshotV1(
        owner_revision=revision_prefix + revision,
        records=(
            PluginBackupRetentionRecordV1(
                key, status, expiry_receipt_id=expiry_receipt_id
            ),
        ),
    )
