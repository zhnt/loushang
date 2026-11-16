"""Legacy Product runtime registration and authenticated old-state observation."""

from __future__ import annotations

import os
import stat
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harness.journal import JournalLockUnavailable, journal_file_lock
from loushang.harness.resources.packages._private_directory import (
    prepare_private_directory_tree,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.snapshot_records import (
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_snapshot import (
    PackageWindowsEpochSnapshotEvidenceStore,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

_FencedRuntime = (
    PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
)
_SnapshotStore = (
    PackagePosixEpochSnapshotEvidenceStore | PackageWindowsEpochSnapshotEvidenceStore
)


@dataclass(frozen=True)
class _LegacyFirstSnapshot:
    """Borrow one fenced runtime to read its authenticated, immutable first snapshot."""

    runtime: _FencedRuntime
    snapshots: _SnapshotStore
    receipt_id: str
    evidence: PackageOfflineRestoreSnapshotEvidenceV1
    error_type: type[Exception]
    label: str

    @classmethod
    def open(
        cls,
        runtime: _FencedRuntime,
        *,
        store_id: str,
        control_root: Path,
        snapshot_root: Path,
        error_type: type[Exception],
        label: str,
    ) -> _LegacyFirstSnapshot:
        runtime.assert_current()
        fence = runtime.cutover_result.fence
        if (
            runtime.registry.store_id != store_id
            or runtime.control_root != control_root
            or fence is None
            or fence.store_id != store_id
            or fence.epoch != 1
            or fence.request.prior_epoch != 0
        ):
            raise error_type(f"{label} first fence is unsupported")
        snapshot_owner = (
            PackageWindowsEpochSnapshotEvidenceStore
            if isinstance(runtime, PackageProductWindowsFencedRuntimeOwner)
            else PackagePosixEpochSnapshotEvidenceStore
        )
        snapshots = snapshot_owner(snapshot_root, store_id=store_id)
        receipt_id = fence.request.snapshot_receipt_id
        evidence = snapshots.snapshot(receipt_id)
        if (
            evidence is None
            or evidence.snapshot.receipt_id != receipt_id
            or evidence.snapshot.legacy_root_identity
            != fence.request.legacy_root_identity
        ):
            raise error_type(f"{label} snapshot is unavailable")
        return cls(runtime, snapshots, receipt_id, evidence, error_type, label)

    def read_member(
        self, *, domain: str, member_name: str, maximum_bytes: int
    ) -> bytes | None:
        raw = self.snapshots.read_regular_member(
            self.receipt_id,
            domain=domain,
            member_name=member_name,
            maximum_bytes=maximum_bytes,
        )
        self.runtime.assert_current()
        return raw

    def list_members(self, *, domain: str) -> tuple[str, ...]:
        members = self.snapshots.list_domain_members(self.receipt_id, domain=domain)
        if members is None:
            raise self.error_type(f"{self.label} snapshot disappeared")
        self.runtime.assert_current()
        return members

    def observe(
        self, *, store_id: str, legacy_root_identity: str
    ) -> PackageLegacyStateEvidenceV1:
        fence = self.runtime.cutover_result.fence
        if (
            fence is None
            or store_id != fence.store_id
            or legacy_root_identity != fence.request.legacy_root_identity
            or self.evidence.snapshot.store_id != store_id
        ):
            raise self.error_type(f"{self.label} observation authority changed")
        self.runtime.assert_current()
        return PackageLegacyStateEvidenceV1.create(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            state_digest=self.evidence.snapshot_tree_digest,
            entry_count=self.evidence.snapshot.entry_count,
            byte_count=self.evidence.snapshot.byte_count,
        )


class _LegacyStateRoots(Protocol):
    @property
    def root(self) -> Path: ...
    @property
    def private_state_base(self) -> Path: ...
    @property
    def package_root(self) -> Path: ...
    @property
    def private_data_base(self) -> Path: ...
    @property
    def coordination_lock(self) -> Path: ...


class _LegacyEpoch(Protocol):
    @property
    def authority_root(self) -> Path: ...
    @property
    def control_root(self) -> Path: ...
    @property
    def store_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class _LegacyStartupPolicy:
    product_label: str
    error_code_prefix: str
    make_error: Callable[[str, str], RuntimeError]
    registration_identity: Callable[[str], str]


_PROCESS_STARTUP_LEASES_LOCK = threading.Lock()
_PROCESS_STARTUP_LEASES: dict[Path, AbstractContextManager[None]] = {}


def _prepare_tree(
    path: Path, *, private_base: Path, label: str, policy: _LegacyStartupPolicy
) -> None:
    prepare_private_directory_tree(
        path,
        private_base=private_base,
        outside_base_error=lambda: policy.make_error(
            f"{policy.product_label} Plugin {label} root is outside its private base",
            f"{policy.error_code_prefix}_state_permissions_failed",
        ),
        private_error=lambda: policy.make_error(
            f"{policy.product_label} Plugin state root is not private",
            f"{policy.error_code_prefix}_state_permissions_failed",
        ),
    )


def prepare_private_state_layout(
    layout: _LegacyStateRoots, *, policy: _LegacyStartupPolicy
) -> None:
    _prepare_tree(
        layout.root,
        private_base=layout.private_state_base,
        label="state",
        policy=policy,
    )
    _prepare_tree(
        layout.package_root,
        private_base=layout.private_data_base,
        label="data",
        policy=policy,
    )
    with journal_file_lock(layout.coordination_lock, "exclusive"):
        pass


def _hold_process_startup_lease(
    layout: _LegacyStateRoots,
    *,
    startup_id: str,
    lease_path: Path,
    resolve_epoch: Callable[[], _LegacyEpoch],
    policy: _LegacyStartupPolicy,
) -> bool:
    with _PROCESS_STARTUP_LEASES_LOCK:
        if lease_path in _PROCESS_STARTUP_LEASES:
            return False
        lease = _legacy_process_startup_scope(
            layout,
            startup_id=startup_id,
            lease_path=lease_path,
            resolve_epoch=resolve_epoch,
            policy=policy,
        )
        try:
            lease.__enter__()
        except JournalLockUnavailable as exc:
            raise policy.make_error(
                f"{policy.product_label} Plugin startup id is active in another process",
                f"{policy.error_code_prefix}_startup_already_active",
            ) from exc
        _PROCESS_STARTUP_LEASES[lease_path] = lease
        return True


@contextmanager
def _legacy_process_startup_scope(
    layout: _LegacyStateRoots,
    *,
    startup_id: str,
    lease_path: Path,
    resolve_epoch: Callable[[], _LegacyEpoch],
    policy: _LegacyStartupPolicy,
) -> Iterator[None]:
    registration = None
    if sys.platform.startswith("linux"):
        from loushang.harness.resources.packages.product_epoch_guard import (
            PackageProductLegacyPreFenceAdmissionError,
            register_package_product_legacy_runtime,
        )

        epoch = resolve_epoch()
        _prepare_tree(
            epoch.authority_root,
            private_base=layout.private_data_base,
            label="data",
            policy=policy,
        )
        _prepare_tree(
            epoch.control_root,
            private_base=layout.private_state_base,
            label="state",
            policy=policy,
        )
        try:
            registration = register_package_product_legacy_runtime(
                epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                startup_id=policy.registration_identity(startup_id),
            )
        except PackageProductLegacyPreFenceAdmissionError as exc:
            raise policy.make_error(str(exc), exc.code) from exc
    elif os.name == "nt":
        from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
            PackageEpochFenceJournal,
        )
        from loushang.harness.resources.packages.plugin_lifecycle.windows_pre_fence_registration import (
            PackageWindowsPreFenceRegistrationError,
            PackageWindowsPreFenceRegistrationOwner,
        )
        from loushang.harness.resources.packages.product_windows_epoch_guard import (
            prepare_windows_product_control_root,
        )

        epoch = resolve_epoch()
        _prepare_tree(
            epoch.control_root.parent,
            private_base=layout.private_state_base,
            label="state",
            policy=policy,
        )
        try:
            prepare_windows_product_control_root(epoch.control_root)
            registration = PackageWindowsPreFenceRegistrationOwner(
                epoch.control_root,
                store_id=epoch.store_id,
                fences=PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl"),
            ).register(
                startup_id=policy.registration_identity(startup_id),
            )
        except (OSError, ValueError, PackageWindowsPreFenceRegistrationError) as exc:
            raise policy.make_error(
                f"{policy.product_label} Windows legacy Package admission failed",
                getattr(
                    exc, "code", f"{policy.error_code_prefix}_state_permissions_failed"
                ),
            ) from exc
    try:
        prepare_private_state_layout(layout, policy=policy)
        with journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        ):
            yield
    finally:
        if registration is not None:
            registration.release()


def _release_process_startup_lease(
    lease_path: Path,
) -> None:
    with _PROCESS_STARTUP_LEASES_LOCK:
        lease = _PROCESS_STARTUP_LEASES.pop(lease_path, None)
    if lease is not None:
        lease.__exit__(None, None, None)


def _startup_lease_is_inactive(
    lease_path: Path,
    *,
    policy: _LegacyStartupPolicy,
) -> bool:
    with _PROCESS_STARTUP_LEASES_LOCK:
        if lease_path in _PROCESS_STARTUP_LEASES:
            return False
    try:
        metadata = lease_path.lstat()
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_reparse_tag", 0))
            or (os.name == "posix" and callable(getuid) and metadata.st_uid != getuid())
        ):
            raise OSError("startup lease is not a private regular file")
        with journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        ):
            return True
    except JournalLockUnavailable:
        return False
    except OSError as exc:
        raise policy.make_error(
            f"{policy.product_label} Plugin startup liveness evidence is invalid",
            f"{policy.error_code_prefix}_startup_evidence_invalid",
        ) from exc
