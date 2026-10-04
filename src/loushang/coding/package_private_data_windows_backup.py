"""Product-bound Windows candidate backup for the current Coding Arch shape.

This owner retains and verifies bytes. It grants no deletion, restore, expiry,
or ordinary Session routing authority. An incomplete stage stays as debt.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionRecordV1,
    PluginBackupRetentionSnapshotV1,
    PluginBackupRetentionStatus,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_rename_at,
    windows_stat_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
    prepare_windows_product_private_directory_chain,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    backup_id,
    backup_parent,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _open_directory_child,
    _require_no_named_directory_streams,
    _require_same_windows_metadata,
    _require_simple_windows_metadata,
)

_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataBackupOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def retain(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataBackupReceiptV1:
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        source_root = coding_arch_installation_private_data_root(self.layout, key)
        state_root = (
            resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        )
        with preview._offline():
            state = self.product.desired_state.snapshot().installation(key)
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Coding Arch backup Installation has no Product history"
                )
            expected_root = inspect_coding_windows_arch_installation_root(
                self.layout, key, state_root=state_root
            )
            if expected_root is None:
                raise ValueError("Coding Arch private-data source is absent")
            source = _capture_windows_target_snapshot(
                source_root, expected_root=expected_root
            )
            receipt = CodingArchPrivateDataBackupReceiptV1(
                installation_key=key,
                source_target_id=source.target_id,
                backup_id=backup_id(key, source),
                file_count=sum(item.kind == "file" for item in source.members),
                byte_count=sum(
                    item.identity[3] for item in source.members if item.kind == "file"
                ),
                receipt_id="arch-backup:" + backup_id(key, source),
            )
            parent_path = backup_parent(self.layout, key)
            prepare_windows_product_private_directory_chain(
                self.layout.package_root, "installation-backups", parent_path.name
            )
            parent_identity = inspect_windows_product_private_directory_identity(
                parent_path
            )
            with (
                WindowsPrivateDirectoryAcl() as exact_acl,
                WindowsPrivateDirectoryAcl(inherit_children=True) as session_acl,
            ):
                parent_fd = open_windows_directory(
                    parent_path, share_delete=False, read_control=True
                )
                try:
                    exact_acl.validate(parent_fd)
                    if _directory_identity(parent_fd) != parent_identity:
                        raise ValueError("Coding Arch backup parent changed")
                    names = set(windows_listdir_at(parent_fd))
                    stage_name = receipt.backup_id + ".staging"
                    if any(
                        name.endswith(".staging") and name != stage_name
                        for name in names
                    ):
                        raise ValueError(
                            "Another Coding Arch backup stage needs recovery"
                        )
                    if stage_name in names and receipt.backup_id in names:
                        raise ValueError("Coding Arch backup stage needs recovery")
                    if receipt.backup_id in names:
                        _verify_archive(
                            parent_fd,
                            parent_path,
                            receipt.backup_id,
                            key,
                            source,
                            receipt,
                            exact_acl,
                        )
                        return receipt
                    if stage_name in names:
                        stage_fd = open_windows_directory(
                            stage_name,
                            dir_fd=parent_fd,
                            share_delete=False,
                            read_control=True,
                        )
                    else:
                        stage_fd = open_windows_directory(
                            stage_name,
                            dir_fd=parent_fd,
                            create_new=True,
                            security_descriptor=exact_acl.security_descriptor,
                            read_control=True,
                        )
                    try:
                        exact_acl.validate(stage_fd)
                        if not set(windows_listdir_at(stage_fd)) <= {
                            "files",
                            "manifest.json",
                        }:
                            raise ValueError(
                                "Coding Arch backup stage has extra members"
                            )
                        files_fd = _open_or_create_directory(
                            stage_fd, "files", exact_acl
                        )
                        try:
                            _copy_members(
                                source_root, source, files_fd, exact_acl, session_acl
                            )
                            windows_flush_directory(files_fd)
                        finally:
                            os.close(files_fd)
                        _write_manifest(stage_fd, source, receipt, exact_acl)
                        windows_flush_directory(stage_fd)
                    finally:
                        os.close(stage_fd)
                    if (
                        _capture_windows_target_snapshot(
                            source_root, expected_root=expected_root
                        )
                        != source
                        or inspect_coding_windows_arch_installation_root(
                            self.layout, key, state_root=state_root
                        )
                        != expected_root
                    ):
                        raise ValueError("Coding Arch backup source changed")
                    try:
                        _verify_archive(
                            parent_fd,
                            parent_path,
                            stage_name,
                            key,
                            source,
                            receipt,
                            exact_acl,
                        )
                    except (OSError, ValueError) as exc:
                        raise ValueError(
                            "Coding Arch backup stage needs recovery"
                        ) from exc
                    windows_rename_at(parent_fd, stage_name, receipt.backup_id)
                    windows_flush_directory(parent_fd)
                    _verify_archive(
                        parent_fd,
                        parent_path,
                        receipt.backup_id,
                        key,
                        source,
                        receipt,
                        exact_acl,
                    )
                    return receipt
                finally:
                    os.close(parent_fd)
                    if (
                        inspect_windows_product_private_directory_identity(parent_path)
                        != parent_identity
                    ):
                        raise ValueError("Coding Arch backup parent changed")

    def verify(
        self, key: PluginInstallationKeyV1, backup_id_value: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        coding_arch_installation_private_data_root(self.layout, key)
        if len(backup_id_value) != 64 or any(
            character not in "0123456789abcdef" for character in backup_id_value
        ):
            raise ValueError("Coding Arch backup ID is invalid")
        with preview._offline(), WindowsPrivateDirectoryAcl() as acl:
            state = self.product.desired_state.snapshot().installation(key)
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Coding Arch backup Installation has no Product history"
                )
            parent_path = backup_parent(self.layout, key)
            parent_identity = inspect_windows_product_private_directory_identity(
                parent_path
            )
            parent_fd = open_windows_directory(
                parent_path, share_delete=False, read_control=True
            )
            try:
                acl.validate(parent_fd)
                if _directory_identity(parent_fd) != parent_identity:
                    raise ValueError("Coding Arch backup parent changed")
                if any(
                    name.endswith(".staging") for name in windows_listdir_at(parent_fd)
                ):
                    raise ValueError("Coding Arch backup stage needs recovery")
                receipt, source = _read_archive_manifest(
                    parent_fd, backup_id_value, acl
                )
                if (
                    receipt.installation_key != key
                    or receipt.backup_id != backup_id_value
                ):
                    raise ValueError("Coding Arch backup Installation changed")
                _verify_archive(
                    parent_fd,
                    parent_path,
                    backup_id_value,
                    key,
                    source,
                    receipt,
                    acl,
                )
                return receipt
            finally:
                os.close(parent_fd)
                if (
                    inspect_windows_product_private_directory_identity(parent_path)
                    != parent_identity
                ):
                    raise ValueError("Coding Arch backup parent changed")

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        """Project verified archives and receipt-backed expiry conservatively."""

        from .package_private_data_windows_backup_expiry_journal import (
            CodingWindowsArchBackupExpiryTransaction,
        )
        from .package_private_data_windows_backup_expiry_owner import _tombstone_name
        from .package_private_data_windows_restore_journal import (
            CodingWindowsArchPrivateDataRestoreTransaction,
        )

        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id="coding.arch.default",
        )
        status: PluginBackupRetentionStatus = "unknown"
        expiry_receipt_id: str | None = None
        trust = "verified"
        receipts: tuple[CodingArchPrivateDataBackupReceiptV1, ...] = ()
        self.product.assert_private_data_read_authority_current()
        with self.product.gc_gate.read_guard():
            try:
                state = self.product.desired_state.snapshot().installation(key)
                state_identity = inspect_windows_product_private_directory_identity(
                    self.product.state_root
                )
                with WindowsPrivateDirectoryAcl() as state_acl:
                    fd = open_windows_directory(
                        self.product.state_root,
                        share_delete=False,
                        read_control=True,
                    )
                    try:
                        state_acl.validate(fd)
                        if _directory_identity(fd) != state_identity:
                            raise ValueError("Windows Coding Arch expiry state changed")
                        restore = CodingWindowsArchPrivateDataRestoreTransaction(
                            self.layout, self.product, fd
                        )
                        try:
                            events, staged = CodingWindowsArchBackupExpiryTransaction(
                                self.layout, self.product, restore
                            )._scan()
                        finally:
                            restore._close()
                    finally:
                        os.close(fd)
                if (
                    inspect_windows_product_private_directory_identity(
                        self.product.state_root
                    )
                    != state_identity
                ):
                    raise ValueError("Windows Coding Arch expiry state changed")
                if staged is not None:
                    raise ValueError("Windows Coding Arch expiry event needs recovery")
                latest = events[-1] if events else None
                if latest is not None and latest.plan.installation_key != key:
                    raise ValueError("Windows Coding Arch expiry Installation changed")
                if latest is not None and state.latest_instance_revision_ref is None:
                    raise ValueError("Windows Coding Arch expiry Product history changed")
                pending = latest is not None and latest.phase in {"started", "renamed"}
                allowed_tombstone = (
                    _tombstone_name(latest.plan, latest.confirmation)
                    if pending and latest is not None
                    else None
                )
                if state.latest_instance_revision_ref is not None:
                    receipts = _retained_receipts(
                        self.layout,
                        key,
                        allowed_tombstone=allowed_tombstone,
                        pending_backup_id=(
                            latest.plan.backup_id
                            if pending and latest is not None
                            else None
                        ),
                    )
                if (
                    latest is not None
                    and latest.phase in {"renamed", "completed"}
                    and any(item.backup_id == latest.plan.backup_id for item in receipts)
                ):
                    raise ValueError("Windows Coding Arch expired archive reappeared")
                if pending:
                    status = "expiry_pending"
                elif receipts:
                    status = "retained"
                elif latest is not None and latest.phase == "completed":
                    if latest.receipt is None:
                        raise ValueError("Windows Coding Arch expiry receipt changed")
                    status = "expired"
                    expiry_receipt_id = latest.receipt.receipt_id
            except (OSError, ValueError):
                trust = "untrusted"
                receipts = ()
                status = "unknown"
                expiry_receipt_id = None
            revision = sha256(
                b"loushang.coding-arch-backup-retention/v1\0"
                + canonical_json_bytes(
                    {
                        "expiryPhase": status,
                        "expiryReceiptId": expiry_receipt_id,
                        "receipts": [item.to_dict() for item in receipts],
                        "trust": trust,
                    }
                )
            ).hexdigest()
        self.product.assert_private_data_read_authority_current()
        return PluginBackupRetentionSnapshotV1(
            owner_revision="coding-arch-backup:" + revision,
            records=(
                PluginBackupRetentionRecordV1(
                    key, status, expiry_receipt_id=expiry_receipt_id
                ),
            ),
        )


def _directory_identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    _require_simple_windows_metadata(metadata, directory=True)
    _require_no_named_directory_streams(descriptor)
    return metadata.st_dev, metadata.st_ino


def _retained_receipts(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    allowed_tombstone: str | None = None,
    pending_backup_id: str | None = None,
) -> tuple[CodingArchPrivateDataBackupReceiptV1, ...]:
    parent_path = backup_parent(layout, key)
    try:
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
    except FileNotFoundError:
        base_path = parent_path.parent
        try:
            inspect_windows_product_private_directory_identity(base_path)
        except FileNotFoundError:
            try:
                base_path.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError("Coding Arch backup base is unsafe") from None
            inspect_windows_product_private_directory_identity(layout.package_root)
            return ()
        try:
            parent_path.lstat()
        except FileNotFoundError:
            return ()
        raise ValueError("Coding Arch backup parent is unsafe")
    with WindowsPrivateDirectoryAcl() as acl:
        parent_fd = open_windows_directory(
            parent_path, share_delete=False, read_control=True
        )
        try:
            acl.validate(parent_fd)
            if _directory_identity(parent_fd) != parent_identity:
                raise ValueError("Coding Arch backup parent changed")
            names = windows_listdir_at(parent_fd)
            if len(set(names)) != len(names):
                raise ValueError("Coding Arch backup members repeat")
            if (
                allowed_tombstone is not None
                and allowed_tombstone in names
                and pending_backup_id in names
            ):
                raise ValueError("Coding Arch backup expiry tombstone collides")
            receipts: list[CodingArchPrivateDataBackupReceiptV1] = []
            for name in sorted(names):
                if name == allowed_tombstone:
                    continue
                if len(name) != 64 or any(
                    character not in "0123456789abcdef" for character in name
                ):
                    raise ValueError("Coding Arch backup member is unexpected")
                receipt, source = _read_archive_manifest(parent_fd, name, acl)
                if receipt.installation_key != key or receipt.backup_id != name:
                    raise ValueError("Coding Arch backup identity changed")
                _verify_archive(parent_fd, parent_path, name, key, source, receipt, acl)
                receipts.append(receipt)
            return tuple(receipts)
        finally:
            os.close(parent_fd)
            if (
                inspect_windows_product_private_directory_identity(parent_path)
                != parent_identity
            ):
                raise ValueError("Coding Arch backup parent changed")


def _open_or_create_directory(
    parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
) -> int:
    created = False
    try:
        child_fd = open_windows_directory(
            name,
            dir_fd=parent_fd,
            create_new=True,
            security_descriptor=acl.security_descriptor,
            read_control=True,
        )
        created = True
    except FileExistsError:
        child_fd = open_windows_directory(
            name, dir_fd=parent_fd, share_delete=False, read_control=True
        )
    try:
        acl.validate(child_fd)
        _directory_identity(child_fd)
        if created:
            windows_flush_directory(parent_fd)
        return child_fd
    except BaseException:
        os.close(child_fd)
        raise


def _open_relative_directory(
    root_fd: int,
    parts: list[str],
    expected: dict[str, CodingArchPrivateDataMemberV1] | None,
    exact_acl: WindowsPrivateDirectoryAcl,
    session_acl: WindowsPrivateDirectoryAcl,
) -> int:
    current_fd = os.dup(root_fd)
    path = ""
    try:
        for depth, part in enumerate(parts, start=1):
            path = part if not path else path + "/" + part
            next_fd, metadata = _open_directory_child(
                current_fd, part, session_acl if depth == 2 else exact_acl
            )
            if expected is not None:
                member = expected.get(path)
                if (
                    member is None
                    or member.kind != "directory"
                    or _identity(metadata) != member.identity
                ):
                    os.close(next_fd)
                    raise ValueError("Coding Arch backup source directory changed")
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _copy_members(
    source_root: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
    destination_fd: int,
    exact_acl: WindowsPrivateDirectoryAcl,
    session_acl: WindowsPrivateDirectoryAcl,
) -> None:
    source_fd = open_windows_directory(
        source_root, share_delete=False, read_control=True
    )
    try:
        exact_acl.validate(source_fd)
        if _identity(os.fstat(source_fd)) != source.root_identity:
            raise ValueError("Coding Arch backup source root changed")
        expected = {item.relative_path: item for item in source.members}
        for item in sorted(
            source.members,
            key=lambda member: (member.relative_path.count("/"), member.relative_path),
        ):
            parts = item.relative_path.split("/")
            if item.kind == "directory":
                parent_fd = _open_relative_directory(
                    destination_fd, parts[:-1], None, exact_acl, session_acl
                )
                try:
                    acl = session_acl if len(parts) == 2 else exact_acl
                    child_fd = _open_or_create_directory(parent_fd, parts[-1], acl)
                    os.close(child_fd)
                    windows_flush_directory(parent_fd)
                finally:
                    os.close(parent_fd)
                continue
            source_parent = _open_relative_directory(
                source_fd, parts[:-1], expected, exact_acl, session_acl
            )
            destination_parent = _open_relative_directory(
                destination_fd, parts[:-1], None, exact_acl, session_acl
            )
            try:
                content = _read_source_file(source_parent, parts[-1], item, session_acl)
                _write_or_verify_archive_file(
                    destination_parent,
                    parts[-1],
                    content,
                    session_acl,
                    inherited_file=True,
                )
                windows_flush_directory(destination_parent)
            finally:
                os.close(source_parent)
                os.close(destination_parent)
    finally:
        os.close(source_fd)


def _write_or_verify_archive_file(
    parent_fd: int,
    name: str,
    content: bytes,
    acl: WindowsPrivateDirectoryAcl,
    *,
    inherited_file: bool,
) -> None:
    try:
        descriptor = open_windows_regular_file_at(
            parent_fd,
            name,
            create_new=True,
            write=True,
            security_descriptor=(None if inherited_file else acl.security_descriptor),
            read_control=True,
        )
    except FileExistsError:
        descriptor = open_windows_regular_file_at(
            parent_fd, name, create_new=False, write=True, read_control=True
        )
        try:
            acl.validate(descriptor, inherited_file=inherited_file)
            before = os.fstat(descriptor)
            _require_simple_windows_metadata(before, directory=False)
            if (
                before.st_nlink != 1
                or before.st_size > len(content)
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError("Coding Arch backup stage file changed")
            raw = _read_bounded(descriptor, len(content))
            current = os.fstat(descriptor)
            visible = windows_stat_at(parent_fd, name)
            _require_same_windows_metadata(current, before, directory=False)
            _require_same_windows_metadata(visible, before, directory=False)
            if (
                len(raw) != before.st_size
                or raw != content[: len(raw)]
                or _identity(current) != _identity(before)
                or _identity(visible) != _identity(before)
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError("Coding Arch backup stage file changed")
            if len(raw) < len(content):
                if os.lseek(descriptor, 0, os.SEEK_END) != len(raw):
                    raise ValueError("Coding Arch backup stage file changed")
                view = memoryview(content)[len(raw) :]
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("Coding Arch backup write stopped")
                    view = view[written:]
                windows_flush_file(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            complete = _read_bounded(descriptor, len(content))
            after = os.fstat(descriptor)
            path_after = windows_stat_at(parent_fd, name)
            _require_simple_windows_metadata(after, directory=False)
            _require_same_windows_metadata(path_after, after, directory=False)
            if (
                complete != content
                or after.st_size != len(content)
                or after.st_nlink != 1
                or (after.st_dev, after.st_ino, after.st_mode)
                != (before.st_dev, before.st_ino, before.st_mode)
                or _identity(path_after) != _identity(after)
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError("Coding Arch backup stage file changed")
            acl.validate(descriptor, inherited_file=inherited_file)
            return
        finally:
            os.close(descriptor)
    try:
        acl.validate(descriptor, inherited_file=inherited_file)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("Coding Arch backup write stopped")
            view = view[written:]
        windows_flush_file(descriptor)
    finally:
        os.close(descriptor)


def _read_bounded(descriptor: int, maximum_bytes: int) -> bytes:
    raw = bytearray()
    while len(raw) <= maximum_bytes:
        chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    if len(raw) > maximum_bytes:
        raise ValueError("Coding Arch backup file is too large")
    return bytes(raw)


def _read_source_file(
    parent_fd: int,
    name: str,
    item: CodingArchPrivateDataMemberV1,
    acl: WindowsPrivateDirectoryAcl,
) -> bytes:
    metadata = windows_stat_at(parent_fd, name)
    descriptor = open_windows_regular_file_at(
        parent_fd, name, create_new=False, write=False, read_control=True
    )
    try:
        acl.validate(descriptor, inherited_file=True)
        _require_same_windows_metadata(os.fstat(descriptor), metadata, directory=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > _MAX_FILE_BYTES
            or _identity(metadata) != item.identity
            or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        ):
            raise ValueError("Coding Arch backup source file changed")
        chunks = bytearray()
        while len(chunks) <= _MAX_FILE_BYTES:
            chunk = os.read(
                descriptor, min(1024 * 1024, _MAX_FILE_BYTES + 1 - len(chunks))
            )
            if not chunk:
                break
            chunks.extend(chunk)
        current = os.fstat(descriptor)
        visible = windows_stat_at(parent_fd, name)
        _require_same_windows_metadata(current, metadata, directory=False)
        _require_same_windows_metadata(visible, metadata, directory=False)
        if (
            len(chunks) != metadata.st_size
            or len(chunks) > _MAX_FILE_BYTES
            or sha256(chunks).hexdigest() != item.content_sha256
            or _identity(current) != item.identity
            or _identity(visible) != item.identity
            or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        ):
            raise ValueError("Coding Arch backup source file changed")
        return bytes(chunks)
    finally:
        os.close(descriptor)


def _write_manifest(
    stage_fd: int,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    content = (
        canonical_json_bytes({"receipt": receipt.to_dict(), "source": source.to_dict()})
        + b"\n"
    )
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError("Coding Arch backup manifest is too large")
    _write_or_verify_archive_file(
        stage_fd, "manifest.json", content, acl, inherited_file=False
    )


def _read_archive_manifest(
    parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
) -> tuple[CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1]:
    archive_fd = open_windows_directory(
        name, dir_fd=parent_fd, share_delete=False, read_control=True
    )
    try:
        acl.validate(archive_fd)
        descriptor = open_windows_regular_file_at(
            archive_fd,
            "manifest.json",
            create_new=False,
            write=False,
            read_control=True,
        )
        try:
            acl.validate(descriptor)
            before = os.fstat(descriptor)
            _require_simple_windows_metadata(before, directory=False)
            if (
                before.st_nlink != 1
                or before.st_size > _MAX_MANIFEST_BYTES
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError("Coding Arch backup manifest is unsafe")
            raw = bytearray()
            while len(raw) <= _MAX_MANIFEST_BYTES:
                chunk = os.read(
                    descriptor, min(65536, _MAX_MANIFEST_BYTES + 1 - len(raw))
                )
                if not chunk:
                    break
                raw.extend(chunk)
            after = os.fstat(descriptor)
            _require_same_windows_metadata(after, before, directory=False)
            if (
                len(raw) != before.st_size
                or len(raw) > _MAX_MANIFEST_BYTES
                or _identity(after) != _identity(before)
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError("Coding Arch backup manifest changed")
        finally:
            os.close(descriptor)
    finally:
        os.close(archive_fd)
    try:
        document = json.loads(
            bytes(raw).decode("utf-8"), object_pairs_hook=_unique_object
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Coding Arch backup manifest is invalid") from exc
    if type(document) is not dict or set(document) != {"receipt", "source"}:
        raise ValueError("Coding Arch backup manifest fields are invalid")
    source = CodingArchPrivateDataTargetSnapshotV1.from_dict(document["source"])
    receipt = CodingArchPrivateDataBackupReceiptV1.from_dict(document["receipt"])
    if (
        receipt.source_target_id != source.target_id
        or receipt.backup_id != backup_id(receipt.installation_key, source)
        or bytes(raw) != canonical_json_bytes(document) + b"\n"
    ):
        raise ValueError("Coding Arch backup manifest identity changed")
    return receipt, source


def _verify_archive(
    parent_fd: int,
    parent_path: Path,
    name: str,
    key: PluginInstallationKeyV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    archive_fd = open_windows_directory(
        name, dir_fd=parent_fd, share_delete=False, read_control=True
    )
    try:
        acl.validate(archive_fd)
        archive_identity = _directory_identity(archive_fd)
        if set(windows_listdir_at(archive_fd)) != {"files", "manifest.json"}:
            raise ValueError("Coding Arch backup archive members changed")
        actual_receipt, actual_source = _read_archive_manifest(parent_fd, name, acl)
        if (
            actual_receipt != receipt
            or actual_source != source
            or receipt.installation_key != key
        ):
            raise ValueError("Coding Arch backup manifest changed")
        files_fd = open_windows_directory(
            "files", dir_fd=archive_fd, share_delete=False, read_control=True
        )
        try:
            acl.validate(files_fd)
            files_identity = _directory_identity(files_fd)
            captured = _capture_windows_target_snapshot(
                parent_path / name / "files", expected_root=files_identity
            )
            if _logical_members(captured) != _logical_members(source):
                raise ValueError("Coding Arch backup files changed")
        finally:
            os.close(files_fd)
        if (
            _directory_identity(archive_fd) != archive_identity
            or _identity(windows_stat_at(parent_fd, name))[:2] != archive_identity
        ):
            raise ValueError("Coding Arch backup archive changed")
    finally:
        os.close(archive_fd)


def _logical_members(
    snapshot: CodingArchPrivateDataTargetSnapshotV1,
) -> tuple[tuple[str, str, int, str | None], ...]:
    return tuple(
        (
            item.relative_path,
            item.kind,
            item.identity[3] if item.kind == "file" else 0,
            item.content_sha256,
        )
        for item in snapshot.members
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding Arch backup manifest has duplicate fields")
        result[key] = value
    return result


__all__ = ["CodingWindowsArchPrivateDataBackupOwner"]
