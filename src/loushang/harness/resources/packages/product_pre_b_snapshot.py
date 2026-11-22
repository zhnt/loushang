"""Product-facing owner for a complete POSIX pre-B Package snapshot."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.private_directory import create_private_directory_chain
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_coordination import (
    PackagePosixEpochCutoverCoordination,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverOwner,
    PackagePosixEpochCutoverRequestV1,
    PackagePosixEpochCutoverResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
    PackagePosixEpochSnapshotOwner,
    PackagePosixSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_pre_fence_registration import (
    PackagePosixPreFenceRegistrationOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.snapshot_records import (
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _hold_windows_private_cutover_directory,
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_control_root,
)


@dataclass(frozen=True, slots=True)
class PackageProductPreBSnapshotSharedMemberV1:
    source_root: Path
    member_name: str
    domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackageProductPosixCutoverAttemptV1:
    request: PackagePosixEpochCutoverRequestV1
    result: PackagePosixEpochCutoverResultV1


def inspect_legacy_product_member_names(
    root: Path,
    *,
    allowed_members: Collection[str],
    directory_members: Collection[str],
    label: str,
) -> set[str]:
    """Inventory old root members using the Product's exact historical shape.

    This is a read-only observation, not snapshot or publication authority.
    Preserve legacy lstat/no-hardlink checks without imposing new admission.
    """
    try:
        metadata = root.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{label} root is not a directory")
        names = set(os.listdir(root))
        if names - set(allowed_members):
            raise ValueError(f"{label} root has unmapped members")
        for name in names:
            member = (root / name).lstat()
            expected = stat.S_ISDIR if name in directory_members else stat.S_ISREG
            if not expected(member.st_mode) or (
                stat.S_ISREG(member.st_mode) and member.st_nlink != 1
            ):
                raise ValueError(f"{label} member is unsafe")
    except OSError as exc:
        raise ValueError(f"{label} source is unavailable") from exc
    return names


def inspect_legacy_product_domain_members(
    root: Path,
    *,
    domains_by_member: Mapping[str, tuple[str, ...]],
    directory_members: Collection[str],
    label: str,
) -> dict[str, tuple[str, ...]]:
    """Inspect the root once, then include each member in its declared domains."""
    names = inspect_legacy_product_member_names(
        root,
        allowed_members=domains_by_member,
        directory_members=directory_members,
        label=label,
    )
    observed_by_domain: dict[str, list[str]] = {}
    for name in sorted(names):
        for domain in domains_by_member[name]:
            observed_by_domain.setdefault(domain, []).append(name)
    return {domain: tuple(members) for domain, members in observed_by_domain.items()}


def read_posix_product_pre_b_snapshot(
    *,
    snapshot_root: Path,
    store_id: str,
    snapshot_receipt_id: str,
) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
    """Verify one fenced Product backup through its native snapshot owner."""

    return PackagePosixEpochSnapshotEvidenceStore(
        snapshot_root, store_id=store_id
    ).snapshot(snapshot_receipt_id)


def reopen_posix_product_cutover(
    *,
    authority_root: Path,
    control_root: Path,
    store_id: str,
    epochs_root_name: str,
    read_only: bool = False,
) -> PackagePosixEpochCutoverResultV1:
    """Reopen the fenced Product root using durable evidence, without old Source."""

    if any(
        not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
        for path in (authority_root, control_root)
    ):
        raise ValueError("Package Product epoch roots must be absolute")
    if control_root != control_root.resolve(strict=True):
        raise ValueError("Package Product control root is not canonical")
    metadata = control_root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Package Product control root is not private")
    journal_path = control_root / "epoch.jsonl"
    journal = PackageEpochFenceJournal(journal_path, read_only=read_only)
    if journal.path != journal_path:
        raise ValueError("Package Product fence journal is not canonical")
    result = PackagePosixEpochCutoverOwner.reopen_fenced(
        authority_root,
        store_id=store_id,
        epoch_journal=journal,
        epochs_root_name=epochs_root_name,
    )
    observed = control_root.lstat()
    if (
        control_root != control_root.resolve(strict=True)
        or journal.path != journal_path
        or (observed.st_dev, observed.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        raise ValueError("Package Product control root changed during reopen")
    return result


class PackageProductPreBSnapshotOwner:
    """Keep native snapshot publication behind the Product Package boundary."""

    def __init__(
        self,
        snapshot_root: Path,
        *,
        store_id: str,
        domain_roots: Mapping[str, Path],
        domain_members: Mapping[str, tuple[str, ...] | None],
        legacy_root_pointer_name: str,
        shared_members: tuple[PackageProductPreBSnapshotSharedMemberV1, ...] = (),
    ) -> None:
        self._store_id = store_id
        self._owner = PackagePosixEpochSnapshotOwner(
            snapshot_root,
            store_id=store_id,
            domain_roots=domain_roots,
            domain_members=domain_members,
            legacy_root_pointer_name=legacy_root_pointer_name,
            shared_members=tuple(
                PackagePosixSnapshotSharedMemberV1(
                    source_root=item.source_root,
                    member_name=item.member_name,
                    domains=item.domains,
                )
                for item in shared_members
            ),
        )

    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        return self._owner.capture(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
        )

    def snapshot(
        self, snapshot_receipt_id: str
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        return self._owner.snapshot(snapshot_receipt_id)

    def read_regular_member(
        self,
        snapshot_receipt_id: str,
        *,
        domain: str,
        member_name: str,
        maximum_bytes: int = 2 * 1024 * 1024,
    ) -> bytes | None:
        """Read one verified member before the Product decides to fence."""

        return self._owner.read_regular_member(
            snapshot_receipt_id,
            domain=domain,
            member_name=member_name,
            maximum_bytes=maximum_bytes,
        )

    def list_domain_members(
        self, snapshot_receipt_id: str, *, domain: str
    ) -> tuple[str, ...] | None:
        """List one verified domain before the Product decides to fence."""

        return self._owner.list_domain_members(snapshot_receipt_id, domain=domain)

    def cutover_from_legacy(
        self,
        *,
        authority_root: Path,
        control_root: Path,
        legacy_root_name: str,
        epochs_root_name: str,
        namespace_id: str,
        minimum_runtime_version: str,
        minimum_runtime_protocol_epoch: int,
        snapshot_admission: Callable[[PackageEpochCutoverSnapshotReceiptV1], None]
        | None = None,
    ) -> PackageProductPosixCutoverAttemptV1:
        """Fence a quiescent legacy Store against this exact snapshot owner."""

        if os.name != "posix" or any(
            not hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
        ):
            raise RuntimeError("POSIX Package Product cutover is required")
        if any(
            not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
            for path in (authority_root, control_root)
        ):
            raise ValueError("Package Product cutover roots must be absolute")
        fences = PackageEpochFenceJournal(control_root / "epoch.jsonl")
        pre_fence = PackagePosixPreFenceRegistrationOwner(
            authority_root, store_id=self._store_id, fences=fences
        )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(control_root, flags)
        file_io = None
        try:
            file_io = RootedFileIO(control_root, descriptor)
            leases = PackageEpochRuntimeLeaseRegistry(
                path=control_root / "runtime-leases.jsonl",
                coordination_lock=control_root / "coordination",
                file_io=file_io,
                fences=fences,
                store_id=self._store_id,
            )
            owner = PackagePosixEpochCutoverOwner(
                authority_root,
                store_id=self._store_id,
                epoch_journal=fences,
                legacy_root_name=legacy_root_name,
                epochs_root_name=epochs_root_name,
                coordination=PackagePosixEpochCutoverCoordination(
                    leases=leases,
                    pre_fence=pre_fence,
                ),
                snapshots=self,
                snapshot_admission=snapshot_admission,
            )
            current = fences.current(self._store_id)
            request = PackagePosixEpochCutoverRequestV1.create(
                store_id=self._store_id,
                prior_fence=None,
                expected_legacy_root_identity=(
                    owner.current_root_identity()
                    if current is None
                    else current.request.legacy_root_identity
                ),
                namespace_id=namespace_id,
                minimum_runtime_version=minimum_runtime_version,
                minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            )
            return PackageProductPosixCutoverAttemptV1(
                request=request,
                result=owner.cutover(request),
            )
        finally:
            try:
                if file_io is not None:
                    file_io.cleanup()
            finally:
                os.close(descriptor)


__all__ = [
    "PackagePosixEpochCutoverResultV1",
    "PackageProductPreBSnapshotOwner",
    "PackageProductPreBSnapshotSharedMemberV1",
    "PackageProductPosixCutoverAttemptV1",
    "read_posix_product_pre_b_snapshot",
    "reopen_posix_product_cutover",
]


def write_legacy_product_projection(
    root: Path, *, projection_name: str, contents: bytes
) -> None:
    """Publish one exclusive projection in an already-private temporary root."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        descriptor = os.open(
            projection_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=root_fd,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(contents)
                handle.flush()
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def prepare_legacy_product_cutover_root(
    root: Path, *, private_base: Path, windows: bool, label: str
) -> None:
    """Prepare missing roots without chmod-repairing existing unsafe levels."""
    if not private_base.is_absolute() or not root.is_absolute():
        raise ValueError(f"{label} cutover roots must be absolute")
    try:
        relative = root.relative_to(private_base)
    except ValueError:
        raise ValueError(f"{label} cutover root is outside its private base") from None
    if windows:
        create_private_directory_chain(root.parent)
        prepare_windows_product_control_root(root)
        return
    create_private_directory_chain(private_base)
    current = private_base
    _require_legacy_cutover_directory(current, label=label)
    for part in relative.parts:
        current /= part
        create_private_directory_chain(current)
        _require_legacy_cutover_directory(current, label=label)


def _require_legacy_cutover_directory(path: Path, *, label: str) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError(f"{label} cutover directory is not private")


@contextmanager
def hold_legacy_product_projection_root(
    parent: Path, *, prefix: str, projection_name: str, projection_label: str
) -> Iterator[Path]:
    """Borrow the original native temporary root through exact exit cleanup."""
    if os.name == "nt":
        with _hold_windows_private_cutover_directory(
            parent,
            prefix=prefix,
            projection_name=projection_name,
            projection_label=projection_label,
        ) as root:
            yield root
    else:
        with TemporaryDirectory(prefix=prefix, dir=parent) as raw:
            yield Path(raw)


def read_legacy_product_projection(source_root: Path, *, name: str) -> bytes:
    if os.name != "nt":
        return (source_root / name).read_bytes()
    pinned = _PinnedWindowsAuthority.open(source_root, read_control=True)
    try:
        descriptor = open_windows_regular_file_at(
            pinned.descriptor,
            name,
            create_new=False,
            write=False,
        )
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()
    finally:
        pinned.close()
