"""Independent retained backup owner for one Coding Arch Installation.

The archive is a private immutable file tree with its own manifest. It never
deletes source data or expires backups, and Package removal/GC cannot infer
retention from their own receipts.
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionRecordV1,
    PluginBackupRetentionSnapshotV1,
    PluginBackupRetentionStatus,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _rename_directory_noreplace,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout, _prepare_private_tree
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
)
from .package_private_data_backup_records import (
    backup_id as _backup_id,
)
from .package_private_data_backup_records import (
    backup_parent as _backup_parent,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _capture_target_snapshot,
    _identity,
)
from .package_product_backup_types import require_coding_arch_backup_writer

if os.name == "posix":
    _FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    _FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
else:
    _FLAGS = os.O_RDONLY
    _FILE_READ_FLAGS = os.O_RDONLY
_PLUGIN_ID = "coding.arch.default"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX backup owner is unavailable")
        require_coding_arch_backup_writer(self.product)
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)

    def retain(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataBackupReceiptV1:
        source_root = coding_arch_installation_private_data_root(self.layout, key)
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            state = self.product.desired_state.snapshot().installation(key)
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Coding Arch backup Installation has no Product history"
                )
            source = _capture_target_snapshot(
                source_root, private_base=self.layout.private_data_base
            )
            if source.root_identity is None:
                raise ValueError("Coding Arch private-data source is absent")
            backup_id = _backup_id(key, source)
            receipt = CodingArchPrivateDataBackupReceiptV1(
                installation_key=key,
                source_target_id=source.target_id,
                backup_id=backup_id,
                file_count=sum(item.kind == "file" for item in source.members),
                byte_count=sum(
                    item.identity[3] for item in source.members if item.kind == "file"
                ),
                receipt_id="arch-backup:" + backup_id,
            )
            backup_parent = _backup_parent(self.layout, key)
            _prepare_private_tree(
                backup_parent,
                private_base=self.layout.private_data_base,
                label="backup",
            )
            parent_fd = _open_private_path(self.layout.private_data_base, backup_parent)
            try:
                if _identity(os.fstat(parent_fd)) != _identity(backup_parent.lstat()):
                    raise ValueError("Coding Arch backup parent changed")
                final_name = backup_id
                stage_name = backup_id + ".staging"
                if _exists_at(parent_fd, final_name):
                    _verify_archive(parent_fd, final_name, key, source, receipt)
                    return receipt
                _mkdir_at(parent_fd, stage_name)
                stage_fd = _open_private_dir(parent_fd, stage_name)
                try:
                    _mkdir_at(stage_fd, "files")
                    files_fd = _open_private_dir(stage_fd, "files")
                    try:
                        _copy_members(
                            source_root,
                            source,
                            files_fd,
                            private_base=self.layout.private_data_base,
                        )
                        if (
                            _capture_target_snapshot(
                                source_root, private_base=self.layout.private_data_base
                            )
                            != source
                        ):
                            raise ValueError("Coding Arch backup source changed")
                        _verify_files(files_fd, source)
                    finally:
                        os.close(files_fd)
                    _write_or_verify_manifest(stage_fd, key, source, receipt)
                    os.fsync(stage_fd)
                finally:
                    os.close(stage_fd)
                _rename_directory_noreplace(
                    parent_fd, stage_name, parent_fd, final_name
                )
                os.fsync(parent_fd)
                _verify_archive(parent_fd, final_name, key, source, receipt)
                return receipt
            finally:
                os.close(parent_fd)

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            return CodingArchPrivateDataBackupReadSource(
                self.layout, self.product.epoch_runtime
            ).snapshot()

    def verify(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        """Reopen one exact archive without requiring its source to survive."""

        if not _digest(backup_id):
            raise ValueError("Coding Arch backup ID is invalid")
        parent = _backup_parent(self.layout, key)
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            parent_fd = _open_private_path(self.layout.private_data_base, parent)
            try:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch backup Installation changed")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
                return receipt
            finally:
                os.close(parent_fd)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupReadSource:
    """Read-only Product projection of verified per-Installation backups."""

    layout: CodingPluginLifecycleStateLayout
    epoch_runtime: PackageProductPosixFencedRuntimeOwner

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX backup source is unavailable")
        epoch = resolve_coding_package_epoch_layout(self.layout)
        if (
            not isinstance(self.epoch_runtime, PackageProductPosixFencedRuntimeOwner)
            or self.epoch_runtime.registry.store_id != epoch.store_id
            or self.epoch_runtime.control_root != epoch.control_root
        ):
            raise ValueError("Coding Arch backup Product authority changed")

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        from .package_private_data_backup_expiry import _tombstone_name
        from .package_private_data_backup_expiry_journal import (
            CodingArchPrivateDataBackupExpiryJournal,
        )

        self.epoch_runtime.assert_current()
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=_PLUGIN_ID,
        )
        expiry_phase: PluginBackupRetentionStatus = "unknown"
        expiry_receipt_id: str | None = None
        try:
            events = CodingArchPrivateDataBackupExpiryJournal(
                self.epoch_runtime.control_root / "product-state"
            ).events()
            latest = events[-1] if events else None
            pending = latest is not None and latest.phase in {"started", "renamed"}
            allowed_tombstone = (
                _tombstone_name(latest.plan, latest.confirmation)
                if pending and latest is not None
                else None
            )
            receipts = _retained_receipts(
                self.layout, key, allowed_tombstone=allowed_tombstone
            )
            if (
                latest is not None
                and latest.phase == "completed"
                and any(item.backup_id == latest.plan.backup_id for item in receipts)
            ):
                raise ValueError("Coding Arch expired backup reappeared")
            if pending:
                expiry_phase = "expiry_pending"
            elif receipts:
                expiry_phase = "retained"
            elif latest is not None and latest.phase == "completed":
                if latest.receipt is None or latest.plan.installation_key != key:
                    raise ValueError("Coding Arch backup expiry receipt changed")
                expiry_phase = "expired"
                expiry_receipt_id = latest.receipt.receipt_id
            trust = "verified"
        except (OSError, ValueError):
            receipts = ()
            trust = "untrusted"
            expiry_phase = "unknown"
        self.epoch_runtime.assert_current()
        revision = sha256(
            b"loushang.coding-arch-backup-retention/v1\0"
            + canonical_json_bytes(
                {
                    "expiryPhase": expiry_phase,
                    "expiryReceiptId": expiry_receipt_id,
                    "receipts": [item.to_dict() for item in receipts],
                    "trust": trust,
                }
            )
        ).hexdigest()
        return PluginBackupRetentionSnapshotV1(
            owner_revision="coding-arch-backup:" + revision,
            records=(
                PluginBackupRetentionRecordV1(
                    installation_key=key,
                    status=expiry_phase,
                    expiry_receipt_id=expiry_receipt_id,
                ),
            ),
        )


def _retained_receipts(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    allowed_tombstone: str | None = None,
) -> tuple[CodingArchPrivateDataBackupReceiptV1, ...]:
    parent = _backup_parent(layout, key)
    try:
        parent_fd = _open_private_path(layout.private_data_base, parent)
    except FileNotFoundError:
        return ()
    try:
        receipts: list[CodingArchPrivateDataBackupReceiptV1] = []
        for name in sorted(os.listdir(parent_fd)):
            if name.endswith(".staging") or name == allowed_tombstone:
                continue
            if not _digest(name):
                raise ValueError("Coding Arch backup member is unexpected")
            receipt, source = _read_manifest(parent_fd, name)
            if receipt.installation_key != key or receipt.backup_id != name:
                raise ValueError("Coding Arch backup identity changed")
            _verify_archive(parent_fd, name, key, source, receipt)
            receipts.append(receipt)
        return tuple(receipts)
    finally:
        os.close(parent_fd)


def _copy_members(
    source_root: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
    destination_fd: int,
    *,
    private_base: Path,
) -> None:
    source_fd = _open_private_path(private_base, source_root)
    try:
        if _identity(os.fstat(source_fd)) != source.root_identity:
            raise ValueError("Coding Arch backup source root changed")
        expected = {item.relative_path: item for item in source.members}
        for item in source.members:
            parts = item.relative_path.split("/")
            if item.kind == "directory":
                parent_fd = _open_chain(destination_fd, parts[:-1], create=True)
                try:
                    _mkdir_at(parent_fd, parts[-1])
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                continue
            source_parent = _open_source_parent(source_fd, parts[:-1], expected)
            destination_parent = _open_chain(destination_fd, parts[:-1], create=False)
            try:
                source_file = os.open(parts[-1], _FILE_READ_FLAGS, dir_fd=source_parent)
                try:
                    if _identity(os.fstat(source_file)) != item.identity:
                        raise ValueError("Coding Arch backup source file changed")
                    content = _read_bounded(
                        source_file, item.identity[3], exact_size=item.identity[3]
                    )
                    if sha256(content).hexdigest() != item.content_sha256:
                        raise ValueError("Coding Arch backup source content changed")
                    if _identity(os.fstat(source_file)) != item.identity:
                        raise ValueError("Coding Arch backup source file changed")
                finally:
                    os.close(source_file)
                _write_or_verify_file(destination_parent, parts[-1], content)
                os.fsync(destination_parent)
            finally:
                os.close(source_parent)
                os.close(destination_parent)
    finally:
        os.close(source_fd)


def _verify_archive(
    parent_fd: int,
    name: str,
    key: PluginInstallationKeyV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> None:
    archive_fd = _open_private_dir(parent_fd, name)
    try:
        if set(os.listdir(archive_fd)) != {"files", "manifest.json"}:
            raise ValueError("Coding Arch backup archive members changed")
        actual_receipt, actual_source = _read_manifest(parent_fd, name)
        if (
            actual_receipt != receipt
            or actual_source != source
            or receipt.installation_key != key
        ):
            raise ValueError("Coding Arch backup manifest changed")
        files_fd = _open_private_dir(archive_fd, "files")
        try:
            _verify_files(files_fd, source)
        finally:
            os.close(files_fd)
    finally:
        os.close(archive_fd)


def _read_manifest(
    parent_fd: int, name: str
) -> tuple[CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1]:
    archive_fd = _open_private_dir(parent_fd, name)
    try:
        file_fd = os.open("manifest.json", _FILE_READ_FLAGS, dir_fd=archive_fd)
        try:
            metadata = os.fstat(file_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
            ):
                raise ValueError("Coding Arch backup manifest is unsafe")
            document = json.loads(
                _read_bounded(file_fd, 4 * 1024 * 1024).decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
        finally:
            os.close(file_fd)
    finally:
        os.close(archive_fd)
    if type(document) is not dict or set(document) != {"receipt", "source"}:
        raise ValueError("Coding Arch backup manifest fields are invalid")
    source = CodingArchPrivateDataTargetSnapshotV1.from_dict(document["source"])
    receipt = CodingArchPrivateDataBackupReceiptV1.from_dict(document["receipt"])
    if receipt.source_target_id != source.target_id or receipt.backup_id != _backup_id(
        receipt.installation_key, source
    ):
        raise ValueError("Coding Arch backup manifest target changed")
    return receipt, source


def _write_or_verify_manifest(
    stage_fd: int,
    key: PluginInstallationKeyV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> None:
    if receipt.installation_key != key:
        raise ValueError("Coding Arch backup Installation changed")
    content = (
        canonical_json_bytes({"receipt": receipt.to_dict(), "source": source.to_dict()})
        + b"\n"
    )
    _write_or_verify_file(stage_fd, "manifest.json", content)


def _verify_files(root_fd: int, source: CodingArchPrivateDataTargetSnapshotV1) -> None:
    expected = {item.relative_path: item for item in source.members}
    observed: set[str] = set()
    for current_path, directories, files, directory_fd in os.fwalk(
        ".", dir_fd=root_fd, follow_symlinks=False
    ):
        for name in (*directories, *files):
            path = (Path(current_path) / name).as_posix()
            item = expected.get(path)
            if item is None or path in observed:
                raise ValueError("Coding Arch backup has an unexpected member")
            observed.add(path)
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if item.kind == "directory":
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_mode & 0o077
                ):
                    raise ValueError("Coding Arch backup directory changed")
                continue
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
            ):
                raise ValueError("Coding Arch backup file changed")
            file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
            try:
                if _identity(os.fstat(file_fd)) != _identity(metadata):
                    raise ValueError("Coding Arch backup file changed during open")
                content = _read_bounded(
                    file_fd, item.identity[3], exact_size=item.identity[3]
                )
                if sha256(content).hexdigest() != item.content_sha256:
                    raise ValueError("Coding Arch backup content changed")
                if _identity(os.fstat(file_fd)) != _identity(metadata):
                    raise ValueError("Coding Arch backup file changed during read")
            finally:
                os.close(file_fd)
    if observed != set(expected):
        raise ValueError("Coding Arch backup is incomplete")


def _open_source_parent(
    root_fd: int,
    parts: list[str],
    expected: dict[str, CodingArchPrivateDataMemberV1],
) -> int:
    current_fd = os.dup(root_fd)
    path = ""
    try:
        for part in parts:
            path = part if not path else path + "/" + part
            next_fd = _open_private_dir(current_fd, part)
            item = expected[path]
            if (
                item.kind != "directory"
                or _identity(os.fstat(next_fd))[:3] != item.identity[:3]
            ):
                os.close(next_fd)
                raise ValueError("Coding Arch backup source directory changed")
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_chain(root_fd: int, parts: list[str], *, create: bool) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            if create:
                _mkdir_at(current_fd, part)
            next_fd = _open_private_dir(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _mkdir_at(parent_fd: int, name: str) -> None:
    with suppress(FileExistsError):
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    opened = _open_private_dir(parent_fd, name)
    os.close(opened)


def _open_private_dir(parent_fd: int, name: str) -> int:
    opened = os.open(name, _FLAGS, dir_fd=parent_fd)
    try:
        _require_private_fd(opened)
    except BaseException:
        os.close(opened)
        raise
    return opened


def _open_private_path(private_base: Path, path: Path) -> int:
    base = private_base.absolute()
    relative = path.absolute().relative_to(base)
    current_fd = os.open(base, _FLAGS)
    try:
        _require_private_fd(current_fd)
        for part in relative.parts:
            next_fd = _open_private_dir(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _require_private_fd(directory_fd: int) -> None:
    metadata = os.fstat(directory_fd)
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise ValueError("Coding Arch backup directory is not private")


def _write_or_verify_file(parent_fd: int, name: str, content: bytes) -> None:
    try:
        file_fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode=0o600,
            dir_fd=parent_fd,
        )
    except FileExistsError:
        file_fd = os.open(
            name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
        )
        try:
            metadata = os.fstat(file_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
            ):
                raise ValueError("Coding Arch backup file is unsafe")
            existing = _read_bounded(file_fd, len(content))
            if existing != content[: len(existing)]:
                raise ValueError("Coding Arch backup existing content changed")
            if _identity(os.fstat(file_fd)) != _identity(metadata):
                raise ValueError("Coding Arch backup file changed during read")
            _write_all(file_fd, content, offset=len(existing))
            os.fsync(file_fd)
            os.lseek(file_fd, 0, os.SEEK_SET)
            if _read_bounded(file_fd, len(content), exact_size=len(content)) != content:
                raise ValueError("Coding Arch backup file changed during write")
        finally:
            os.close(file_fd)
        return
    try:
        _write_all(file_fd, content)
        os.fsync(file_fd)
    finally:
        os.close(file_fd)


def _write_all(file_fd: int, content: bytes, *, offset: int = 0) -> None:
    while offset < len(content):
        written = os.write(file_fd, content[offset:])
        if written <= 0:
            raise OSError("Coding Arch backup write made no progress")
        offset += written


def _read_bounded(
    file_fd: int, max_bytes: int, *, exact_size: int | None = None
) -> bytes:
    if max_bytes < 0 or max_bytes > 64 * 1024 * 1024:
        raise ValueError("Coding Arch backup file exceeds its limit")
    content = bytearray()
    while chunk := os.read(file_fd, min(1024 * 1024, max_bytes + 1 - len(content))):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise ValueError("Coding Arch backup file grew")
    if exact_size is not None and len(content) != exact_size:
        raise ValueError("Coding Arch backup file size changed")
    return bytes(content)


def _exists_at(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding Arch backup manifest has a duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "CodingArchPrivateDataBackupOwner",
    "CodingArchPrivateDataBackupReadSource",
    "CodingArchPrivateDataBackupReceiptV1",
]
