"""Retained private archives over original rooted tree and publication owners."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Protocol, TypeVar

from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_tree_posix import (
    PrivatePosixTreeIO,
    metadata_identity,
    verify_private_tree,
)
from loushang.harness.resources.packages._tree_observation import (
    MetadataIdentity,
    require_tree_subset,
)
from loushang.harness.resources.packages._tree_observation import (
    PrivateTreeSnapshot as PrivateBackupSource,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _entry_exists,
    _rename_directory_noreplace,
)

from ._private_data_expiry import ExpiryHistoryEvent, ExpiryPlan
from .private_data_deletion import (
    PluginPrivateDataDeletionEventV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionTarget,
    latest_deleted_target_receipt,
)
from .private_data_restore_journal import (
    PrivateDataRestoreEvent,
    PrivateDataRestoreJournal,
)
from .records import PluginInstallationKeyV1


class PrivateBackupReceipt(Protocol):
    @property
    def backup_id(self) -> str: ...

    @property
    def installation_key(self) -> PluginInstallationKeyV1: ...


S = TypeVar("S", bound=PrivateBackupSource)
R = TypeVar("R", bound=PrivateBackupReceipt)


class PrivateArchiveCodec(Protocol[S, R]):
    @property
    def max_manifest_bytes(self) -> int: ...

    @property
    def files_name(self) -> str: ...

    @property
    def manifest_name(self) -> str: ...

    @property
    def stage_suffix(self) -> str: ...

    def encode(self, key: PluginInstallationKeyV1, source: S, receipt: R) -> bytes: ...

    def decode(self, raw: bytes) -> tuple[R, S]: ...


class PrivateTreePreparePort(Protocol):
    def __call__(self, path: Path, *, private_base: Path, label: str) -> None: ...


def read_private_archive(
    parent_fd: int,
    name: str,
    *,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, R],
) -> tuple[R, S]:
    return codec.decode(
        io.read_manifest_bytes(
            parent_fd, name, codec.manifest_name, codec.max_manifest_bytes
        )
    )


def verify_private_archive(
    parent_fd: int,
    name: str,
    key: PluginInstallationKeyV1,
    source: S,
    receipt: R,
    *,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, R],
) -> None:
    with closing_descriptor(io.open_directory(parent_fd, name)) as archive_fd:
        if set(os.listdir(archive_fd)) != {codec.files_name, codec.manifest_name}:
            raise ValueError(f"{io.label} backup archive members changed")
        actual_receipt, actual_source = read_private_archive(
            parent_fd, name, io=io, codec=codec
        )
        if (
            actual_receipt != receipt
            or actual_source != source
            or receipt.installation_key != key
        ):
            raise ValueError(f"{io.label} backup manifest changed")
        with closing_descriptor(
            io.open_directory(archive_fd, codec.files_name)
        ) as files_fd:
            verify_private_tree(
                files_fd,
                source.members,
                label=io.label,
                max_read_bytes=io.max_read_bytes,
            )


class _DeletedBackupReceipt(PrivateBackupReceipt, Protocol):
    @property
    def source_target_id(self) -> str: ...


_DeletedReceiptT = TypeVar("_DeletedReceiptT", bound=_DeletedBackupReceipt)


def read_deleted_restore_source(
    private_base: Path,
    parent: Path,
    name: str,
    key: PluginInstallationKeyV1,
    *,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, _DeletedReceiptT],
    deletion_events: Callable[
        [], Sequence[PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]]
    ],
    installation_error: str,
    deletion_error: str,
) -> tuple[S, PluginPrivateDataDeletionReceiptV1]:
    """Bind and verify retained bytes before releasing their parent descriptor."""
    with closing_descriptor(io.open_path(private_base, parent)) as parent_fd:
        receipt, source = read_private_archive(parent_fd, name, io=io, codec=codec)
        if receipt.installation_key != key or receipt.backup_id != name:
            raise ValueError(installation_error)
        deletion = latest_deleted_target_receipt(
            deletion_events(), key, receipt.source_target_id
        )
        if deletion is None:
            raise ValueError(deletion_error)
        verify_private_archive(
            parent_fd, name, key, source, receipt, io=io, codec=codec
        )
    return source, deletion


def inspect_private_expiry_archive(
    private_base: Path,
    parent: Path,
    name: str,
    key: PluginInstallationKeyV1,
    *,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, R],
    recapture: Callable[[], S],
    installation_error: str,
    changed_error: str,
) -> tuple[R, S, MetadataIdentity, S]:
    """Compare the open archive with its visible path, then recapture after close."""
    with closing_descriptor(io.open_path(private_base, parent)) as parent_fd:
        receipt, source = read_private_archive(parent_fd, name, io=io, codec=codec)
        if receipt.installation_key != key or receipt.backup_id != name:
            raise ValueError(installation_error)
        verify_private_archive(
            parent_fd, name, key, source, receipt, io=io, codec=codec
        )
        with closing_descriptor(io.open_directory(parent_fd, name)) as archive_fd:
            identity = metadata_identity(os.fstat(archive_fd))
            if identity != metadata_identity(
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            ):
                raise ValueError(changed_error)
    snapshot = recapture()
    if snapshot.root_identity != identity or snapshot.root_identity is None:
        raise ValueError(changed_error)
    return receipt, source, identity, snapshot


def retain_private_archive(
    source_root: Path,
    source: S,
    receipt: R,
    key: PluginInstallationKeyV1,
    *,
    private_base: Path,
    backup_parent: Path,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, R],
    recapture: Callable[[], S],
    prepare: PrivateTreePreparePort,
    write_file: Callable[[int, str, bytes], None],
) -> R:
    """Caller owns its original maintenance admission and Product selection."""
    prepare(backup_parent, private_base=private_base, label="backup")
    with closing_descriptor(io.open_path(private_base, backup_parent)) as parent_fd:
        if metadata_identity(os.fstat(parent_fd)) != metadata_identity(
            backup_parent.lstat()
        ):
            raise ValueError(f"{io.label} backup parent changed")
        final_name = receipt.backup_id
        stage_name = final_name + codec.stage_suffix
        if _entry_exists(parent_fd, final_name):
            verify_private_archive(
                parent_fd, final_name, key, source, receipt, io=io, codec=codec
            )
            return receipt
        io.mkdir(parent_fd, stage_name)
        with closing_descriptor(io.open_directory(parent_fd, stage_name)) as stage_fd:
            io.mkdir(stage_fd, codec.files_name)
            with closing_descriptor(
                io.open_directory(stage_fd, codec.files_name)
            ) as files_fd:
                io.copy_members(
                    source_root,
                    source.root_identity,
                    source.members,
                    files_fd,
                    private_base=private_base,
                    write_file=write_file,
                )
                if recapture() != source:
                    raise ValueError(f"{io.label} backup source changed")
                verify_private_tree(
                    files_fd,
                    source.members,
                    label=io.label,
                    max_read_bytes=io.max_read_bytes,
                )
            write_file(
                stage_fd, codec.manifest_name, codec.encode(key, source, receipt)
            )
            os.fsync(stage_fd)
        _rename_directory_noreplace(parent_fd, stage_name, parent_fd, final_name)
        os.fsync(parent_fd)
        verify_private_archive(
            parent_fd, final_name, key, source, receipt, io=io, codec=codec
        )
        return receipt


class _Plan(ExpiryPlan, Protocol):
    @property
    def archive_root_identity(self) -> tuple[int, int, int, int, int]: ...


class _Event(ExpiryHistoryEvent, Protocol):
    @property
    def plan(self) -> _Plan: ...
    @property
    def archive(self) -> PrivateBackupSource | None: ...
    @property
    def receipt(self) -> object | None: ...


_PlanT = TypeVar("_PlanT", bound=_Plan)
_ConfirmationT = TypeVar("_ConfirmationT")
_EventT = TypeVar("_EventT", bound=_Event)
_P_contra = TypeVar("_P_contra", contravariant=True)
_C_contra = TypeVar("_C_contra", contravariant=True)
_A_contra = TypeVar("_A_contra", contravariant=True)
_E = TypeVar("_E")
_A_co = TypeVar("_A_co", covariant=True)


class ExpiryJournal(Protocol[_P_contra, _C_contra, _A_contra, _E]):
    def events(self) -> tuple[_E, ...]: ...
    def begin(
        self, plan: _P_contra, confirmation: _C_contra, archive: _A_contra
    ) -> _E: ...
    def advance(self, prior: _E, phase: Literal["renamed", "completed"]) -> _E: ...


class _Authority(Protocol[_P_contra, _A_co]):
    def _require_pre_effect_plan(self, plan: _P_contra) -> _A_co: ...
    def _require_recovery_authority(self, plan: _P_contra) -> None: ...


def execute_posix_expiry(
    plan: _PlanT,
    confirmation: _ConfirmationT,
    journal: ExpiryJournal[_PlanT, _ConfirmationT, S, _EventT],
    *,
    authority: _Authority[_PlanT, S],
    io: PrivatePosixTreeIO,
    private_base: Callable[[], Path],
    backup_parent: Callable[[PluginInstallationKeyV1], Path],
    tombstone_name: Callable[[], str],
    capture: Callable[[PluginInstallationKeyV1, str], PrivateBackupSource],
) -> object:
    events = journal.events()
    if not events or (
        events[-1].plan != plan or events[-1].confirmation != confirmation
    ):
        raise ValueError(f"{io.label} backup expiry is not confirmed")
    current = events[-1]
    parent_path = backup_parent(plan.installation_key)
    parent_fd = io.open_path(private_base(), parent_path)
    tombstone = tombstone_name()
    try:
        if metadata_identity(os.fstat(parent_fd)) != metadata_identity(
            parent_path.lstat()
        ):
            raise ValueError(f"{io.label} backup expiry parent changed")
        if current.phase == "completed":
            if _entry_exists(parent_fd, plan.backup_id) or _entry_exists(
                parent_fd, tombstone
            ):
                raise ValueError(f"{io.label} expired backup reappeared")
            assert current.receipt is not None
            return current.receipt
        if current.phase == "confirmed" or (
            current.phase == "started" and _entry_exists(parent_fd, plan.backup_id)
        ):
            archive = authority._require_pre_effect_plan(plan)
            if current.phase == "confirmed":
                current = journal.begin(plan, confirmation, archive)
            elif current.archive != archive:
                raise ValueError(f"{io.label} backup expiry archive changed")
        authority._require_recovery_authority(plan)
        if current.phase == "started":
            current = _rename_or_recover(
                journal, current, parent_fd, tombstone, io=io, capture=capture
            )
        if current.phase != "renamed" or current.archive is None:
            raise ValueError(f"{io.label} backup expiry checkpoint changed")
        if _entry_exists(parent_fd, tombstone):
            remove_expiry_tombstone(
                parent_fd,
                tombstone,
                current.archive,
                plan.backup_id,
                io=io,
                capture=lambda: capture(plan.installation_key, tombstone),
            )
        elif _entry_exists(parent_fd, plan.backup_id):
            raise ValueError(f"{io.label} backup expiry archive reappeared")
        completed = journal.advance(current, "completed")
        assert completed.receipt is not None
        return completed.receipt
    finally:
        os.close(parent_fd)


def _rename_or_recover(
    journal: ExpiryJournal[_PlanT, _ConfirmationT, S, _EventT],
    started: _EventT,
    parent_fd: int,
    tombstone: str,
    *,
    io: PrivatePosixTreeIO,
    capture: Callable[[PluginInstallationKeyV1, str], PrivateBackupSource],
) -> _EventT:
    plan = started.plan
    assert started.archive is not None
    original_visible = _entry_exists(parent_fd, plan.backup_id)
    tombstone_visible = _entry_exists(parent_fd, tombstone)
    if original_visible and tombstone_visible:
        raise ValueError(f"{io.label} backup expiry tombstone collides")
    if original_visible:
        with closing_descriptor(
            io.open_directory(parent_fd, plan.backup_id)
        ) as archive_fd:
            if metadata_identity(os.fstat(archive_fd)) != plan.archive_root_identity:
                raise ValueError(f"{io.label} backup expiry archive changed")
            _rename_directory_noreplace(parent_fd, plan.backup_id, parent_fd, tombstone)
            os.fsync(parent_fd)
            if (
                metadata_identity(os.fstat(archive_fd))[:3]
                != metadata_identity(
                    os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
                )[:3]
            ):
                raise ValueError(f"{io.label} backup expiry rename changed")
    elif not tombstone_visible:
        raise ValueError(f"{io.label} backup expiry archive disappeared")
    require_expiry_tombstone_subset(
        parent_fd,
        tombstone,
        started.archive,
        io=io,
        capture=lambda: capture(plan.installation_key, tombstone),
    )
    return journal.advance(started, "renamed")


def require_expiry_tombstone_subset(
    parent_fd: int,
    tombstone: str,
    original: PrivateBackupSource,
    *,
    io: PrivatePosixTreeIO,
    capture: Callable[[], PrivateBackupSource],
) -> PrivateBackupSource:
    if original.root_identity is None:
        raise ValueError(f"{io.label} backup expiry archive was absent")
    with closing_descriptor(io.open_directory(parent_fd, tombstone)) as tombstone_fd:
        if (
            metadata_identity(os.fstat(tombstone_fd))[:3] != original.root_identity[:3]
            or metadata_identity(
                os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
            )[:3]
            != original.root_identity[:3]
        ):
            raise ValueError(f"{io.label} backup expiry tombstone changed")
    remaining = capture()
    require_tree_subset(remaining, original, label=f"{io.label} private-data")
    return remaining


def remove_expiry_tombstone(
    parent_fd: int,
    tombstone: str,
    original: PrivateBackupSource,
    backup_id: str,
    *,
    io: PrivatePosixTreeIO,
    capture: Callable[[], PrivateBackupSource],
) -> None:
    if _entry_exists(parent_fd, backup_id):
        raise ValueError(f"{io.label} backup expiry archive reappeared")
    remaining = require_expiry_tombstone_subset(
        parent_fd, tombstone, original, io=io, capture=capture
    )
    with closing_descriptor(io.open_directory(parent_fd, tombstone)) as tombstone_fd:
        if (
            original.root_identity is None
            or metadata_identity(os.fstat(tombstone_fd))[:3]
            != (original.root_identity[:3])
        ):
            raise ValueError(f"{io.label} backup expiry tombstone changed")
        io.remove_members(tombstone_fd, remaining.members, original)
        if os.listdir(tombstone_fd):
            raise ValueError(f"{io.label} backup expiry tombstone is not empty")
        os.fsync(tombstone_fd)
    if (
        original.root_identity is None
        or metadata_identity(
            os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
        )[:3]
        != original.root_identity[:3]
    ):
        raise ValueError(f"{io.label} backup expiry tombstone changed")
    os.rmdir(tombstone, dir_fd=parent_fd)
    os.fsync(parent_fd)
    if _entry_exists(parent_fd, backup_id):
        raise ValueError(f"{io.label} backup expiry archive reappeared")


def enumerate_private_archives(
    private_base: Path,
    parent: Path,
    key: PluginInstallationKeyV1,
    *,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, R],
    is_archive_name: Callable[[str], bool],
    staging_suffix: str,
    allowed_tombstone: str | None = None,
) -> tuple[R, ...]:
    try:
        parent_fd = io.open_path(private_base, parent)
    except FileNotFoundError:
        return ()
    try:
        receipts: list[R] = []
        for name in sorted(os.listdir(parent_fd)):
            if name.endswith(staging_suffix) or name == allowed_tombstone:
                continue
            if not is_archive_name(name):
                raise ValueError(f"{io.label} backup member is unexpected")
            receipt, source = read_private_archive(parent_fd, name, io=io, codec=codec)
            if receipt.installation_key != key or receipt.backup_id != name:
                raise ValueError(f"{io.label} backup identity changed")
            verify_private_archive(
                parent_fd, name, key, source, receipt, io=io, codec=codec
            )
            receipts.append(receipt)
        return tuple(receipts)
    finally:
        os.close(parent_fd)


_RestoreEventT = TypeVar("_RestoreEventT", bound=PrivateDataRestoreEvent)
_RestoreResultT = TypeVar("_RestoreResultT")


def restore_private_archive(
    parent_fd: int,
    name: str,
    key: PluginInstallationKeyV1,
    source: S,
    receipt: R,
    deletion_receipt: PluginPrivateDataDeletionReceiptV1,
    *,
    target: Path,
    private_base: Path,
    io: PrivatePosixTreeIO,
    codec: PrivateArchiveCodec[S, R],
    expected_target_state: Literal["absent", "same_bytes"] | None,
    stage_prefix: str,
    stage_suffix: str,
    prepare: PrivateTreePreparePort,
    verify_files: Callable[[int, S], None],
    write_file_factory: Callable[[], Callable[[int, str, bytes], None]],
    journal_factory: Callable[[], PrivateDataRestoreJournal[_RestoreEventT]],
    identity_for: Callable[[PluginInstallationKeyV1, str, str], str],
    result_factory: Callable[[str, str, str], _RestoreResultT],
) -> _RestoreResultT:
    """Restore one admitted source; caller retains Product and parent custody."""
    archive_identity = metadata_identity(
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    )
    verify_private_archive(parent_fd, name, key, source, receipt, io=io, codec=codec)
    with closing_descriptor(io.open_directory(parent_fd, name)) as archive_fd:
        if metadata_identity(os.fstat(archive_fd)) != archive_identity:
            raise ValueError(f"{io.label} restore archive changed")
        with closing_descriptor(
            io.open_directory(archive_fd, codec.files_name)
        ) as files_fd:
            verify_files(files_fd, source)
            prepare(target.parent, private_base=private_base, label="data")
            existing_target = io.preflight_restore_target(
                private_base,
                target,
                source.members,
                stage_name=stage_prefix + name + stage_suffix,
                stage_prefix=stage_prefix,
                stage_suffix=stage_suffix,
            )
            if expected_target_state == "same_bytes" and not existing_target:
                raise ValueError(f"{io.label} restore target changed")
            journal = journal_factory()
            restore_id = identity_for(key, name, deletion_receipt.receipt_id)
            if existing_target and not any(
                event.restore_id == restore_id for event in journal.events()
            ):
                raise ValueError(f"{io.label} existing data lacks restore start")
            started = journal.begin(
                key=key,
                backup_id=name,
                deletion_receipt_id=deletion_receipt.receipt_id,
            )
            if started.phase == "completed":
                with closing_descriptor(
                    io.open_path(private_base, target)
                ) as target_fd:
                    verify_files(target_fd, source)
                disposition = "already_present"
            else:
                prepare(target.parent, private_base=private_base, label="data")
                disposition = io.restore_verified_tree(
                    private_base,
                    target,
                    source.members,
                    files_fd,
                    stage_name=stage_prefix + name + stage_suffix,
                    stage_prefix=stage_prefix,
                    stage_suffix=stage_suffix,
                    write_file=write_file_factory(),
                )
            verify_files(files_fd, source)
        if metadata_identity(os.fstat(archive_fd)) != metadata_identity(
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        ):
            raise ValueError(f"{io.label} restore archive changed")
        completed = (
            started if started.phase == "completed" else journal.complete(started)
        )
        return result_factory(name, disposition, completed.restore_id)
