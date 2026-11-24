"""Legacy Product runtime registration and authenticated old-state observation."""

from __future__ import annotations

import os
import stat
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypedDict, TypeVar, Unpack

from loushang.harness.journal import JournalLockUnavailable, journal_file_lock
from loushang.harness.resources.packages._private_directory import (
    prepare_private_directory_tree,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverError,
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
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackagePosixEpochCutoverResultV1,
    PackageProductPreBSnapshotOwner,
    PackageProductPreBSnapshotSharedMemberV1,
    prepare_legacy_product_cutover_root,
    read_posix_product_pre_b_snapshot,
    reopen_posix_product_cutover,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsPreBSnapshotOwner,
    PackageWindowsEpochCutoverResultV1,
    read_windows_product_pre_b_snapshot,
    reopen_windows_product_cutover,
)

_FencedRuntime = (
    PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
)
_SnapshotStore = (
    PackagePosixEpochSnapshotEvidenceStore | PackageWindowsEpochSnapshotEvidenceStore
)


class FencedRuntimeOpenKwargs(TypedDict):
    authority_root: Path
    control_root: Path
    store_id: str
    epochs_root_name: str


class LegacyReviewFenceIdentity(TypedDict):
    store_id: str
    namespace_id: str
    first_fence_id: str
    snapshot_receipt_id: str


def legacy_review_fence_identity(
    runtime: _FencedRuntime, *, missing: ValueError,
) -> LegacyReviewFenceIdentity:
    """Project the native first-cutover receipts used by review records."""
    result = runtime.cutover_result
    fence, switch = result.fence, result.switch_receipt
    if fence is None or switch is None:
        raise missing
    return LegacyReviewFenceIdentity(
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
    )


def open_native_fenced_product_epoch(
    *,
    windows: bool | None = None,
    posix_read_only: bool = False,
    **roots: Unpack[FencedRuntimeOpenKwargs],
) -> _FencedRuntime:
    """Open the selected native owner, with read-only reopen on POSIX when required."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return PackageProductWindowsFencedRuntimeOwner.open(**roots)
    return PackageProductPosixFencedRuntimeOwner.open(**roots, read_only=posix_read_only)


@contextmanager
def open_read_only_fenced_product(
    **roots: Unpack[FencedRuntimeOpenKwargs],
) -> Iterator[PackageProductPosixFencedRuntimeOwner]:
    """Transfer a POSIX read authority only after assembly succeeds."""
    runtime = PackageProductPosixFencedRuntimeOwner.open(**roots, read_only=True)
    try:
        yield runtime
    except BaseException:
        runtime.close()
        raise


def inspect_fresh_product_epoch(
    roots: FencedRuntimeOpenKwargs,
    *,
    windows: bool,
    verify_snapshot: Callable[[_FencedRuntime], bool],
) -> bool:
    """Check original snapshot evidence within one native epoch lifetime."""
    with closing(
        open_native_fenced_product_epoch(windows=windows, posix_read_only=True, **roots)
    ) as runtime:
        return verify_snapshot(runtime)


@dataclass(frozen=True, slots=True)
class _LegacyFirstSnapshot:
    """Reauthenticate the first fence and its receipt for each observation."""

    runtime: _FencedRuntime
    store_id: str
    control_root: Path
    snapshot_root: Path
    error_type: type[Exception]
    label: str

    def _open(self) -> tuple[_SnapshotStore, PackageOfflineRestoreSnapshotEvidenceV1]:
        runtime = self.runtime
        runtime.assert_current()
        fence = runtime.cutover_result.fence
        if (
            runtime.registry.store_id != self.store_id
            or runtime.control_root != self.control_root
            or fence is None
            or fence.store_id != self.store_id
            or fence.epoch != 1
            or fence.request.prior_epoch != 0
        ):
            raise self.error_type(f"{self.label} first fence is unsupported")
        snapshot_owner = (
            PackageWindowsEpochSnapshotEvidenceStore
            if isinstance(runtime, PackageProductWindowsFencedRuntimeOwner)
            else PackagePosixEpochSnapshotEvidenceStore
        )
        snapshots = snapshot_owner(self.snapshot_root, store_id=self.store_id)
        receipt_id = fence.request.snapshot_receipt_id
        evidence = snapshots.snapshot(receipt_id)
        if (
            evidence is None
            or evidence.snapshot.receipt_id != receipt_id
            or evidence.snapshot.legacy_root_identity
            != fence.request.legacy_root_identity
        ):
            raise self.error_type(f"{self.label} snapshot is unavailable")
        return snapshots, evidence

    def read_member(
        self, *, domain: str, member_name: str, maximum_bytes: int
    ) -> bytes | None:
        snapshots, evidence = self._open()
        raw = snapshots.read_regular_member(
            evidence.snapshot.receipt_id,
            domain=domain,
            member_name=member_name,
            maximum_bytes=maximum_bytes,
        )
        self.runtime.assert_current()
        return raw

    def assert_snapshot_current(self, snapshot_receipt_id: str) -> None:
        """Verify the original receipt and entire bundle without reopening a member."""
        _, evidence = self._open()
        if evidence.snapshot.receipt_id != snapshot_receipt_id:
            raise self.error_type(f"{self.label} snapshot is unavailable")
        self.runtime.assert_current()

    def list_members(self, *, domain: str) -> tuple[str, ...]:
        snapshots, evidence = self._open()
        members = snapshots.list_domain_members(
            evidence.snapshot.receipt_id, domain=domain
        )
        if members is None:
            raise self.error_type(f"{self.label} snapshot disappeared")
        self.runtime.assert_current()
        return members

    def observe(
        self, *, store_id: str, legacy_root_identity: str
    ) -> PackageLegacyStateEvidenceV1:
        _, evidence = self._open()
        fence = self.runtime.cutover_result.fence
        if (
            fence is None
            or store_id != fence.store_id
            or legacy_root_identity != fence.request.legacy_root_identity
            or evidence.snapshot.store_id != store_id
        ):
            raise self.error_type(f"{self.label} observation authority changed")
        self.runtime.assert_current()
        return PackageLegacyStateEvidenceV1.create(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            state_digest=evidence.snapshot_tree_digest,
            entry_count=evidence.snapshot.entry_count,
            byte_count=evidence.snapshot.byte_count,
        )


LEGACY_PRODUCT_STATE_DOMAINS = (
    "binding_history",
    "desired_state",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)


def read_fresh_product_source_snapshot(
    reader: _LegacyFirstSnapshot,
    *,
    namespace_id: str,
    source_member: str,
    maximum_bytes: int,
    label: str,
) -> bytes | None:
    """Read fresh settings evidence only from the matching, empty first fence."""
    fence = reader.runtime.cutover_result.fence
    if fence is None or fence.request.namespace_id != namespace_id:
        return None
    for domain in LEGACY_PRODUCT_STATE_DOMAINS:
        if reader.list_members(domain=domain):
            return None
    if reader.list_members(domain="source_configuration") != (source_member,):
        raise RuntimeError(f"{label} fresh Product snapshot is incomplete")
    raw = reader.read_member(
        domain="source_configuration",
        member_name=source_member,
        maximum_bytes=maximum_bytes,
    )
    if raw is None:
        raise RuntimeError(f"{label} fresh Product snapshot is unavailable")
    return raw


def require_legacy_snapshot_members(
    list_members: Callable[..., tuple[str, ...] | None],
    expected: Mapping[str, tuple[str, ...]],
    *,
    error: Exception,
) -> None:
    """Check observed membership in order, without treating absence as empty."""
    if any(list_members(domain=domain) != names for domain, names in expected.items()):
        raise error


@contextmanager
def guard_legacy_snapshot_admission(
    message: str, *, code: str, extra_errors: tuple[type[Exception], ...] = ()
) -> Iterator[None]:
    """Report inadmissible evidence while preserving native cutover failures."""
    wrapped_errors = (OSError, ValueError, TypeError) + extra_errors
    try:
        yield
    except PackagePosixEpochCutoverError:
        raise
    except wrapped_errors as exc:
        raise PackagePosixEpochCutoverError(message, code=code) from exc


def legacy_product_projection_parent(lifecycle_root: Path) -> Path:
    """Keep the deployed native location of the private cutover projections."""
    if os.name == "nt":
        return lifecycle_root.parent / f"{lifecycle_root.name}.pre-b-projections"
    return lifecycle_root.parent


def legacy_product_state_has_inputs(
    roots: Iterable[tuple[Path, Callable[[], Mapping[str, tuple[str, ...]]]]],
    *,
    skip_missing: bool,
) -> bool:
    """Observe historical state without acquiring write or repair authority."""
    for root, domain_members in roots:
        if skip_missing:
            try:
                root.lstat()
            except FileNotFoundError:
                continue
        if any(domain_members().values()):
            return True
    return False


class _LegacyCutoverRoots(Protocol):
    @property
    def control_root(self) -> Path: ...
    @property
    def snapshot_root(self) -> Path: ...
    @property
    def epochs_root(self) -> Path: ...


_CutoverRootsT = TypeVar("_CutoverRootsT", bound=_LegacyCutoverRoots)


def prepare_legacy_product_cutover_roots(
    lifecycle: _LegacyStateRoots,
    *,
    resolve_epoch: Callable[[], _CutoverRootsT],
    label: str,
) -> _CutoverRootsT:
    """Prepare the state roots before either Package data root."""
    if os.name not in {"posix", "nt"}:
        raise RuntimeError("Native Package cutover preparation is required")
    epoch = resolve_epoch()
    windows = os.name == "nt"
    state_roots: tuple[Path, ...] = (lifecycle.root, epoch.control_root, epoch.snapshot_root)
    if windows:
        state_roots += (legacy_product_projection_parent(lifecycle.root),)
    for root in state_roots:
        prepare_legacy_product_cutover_root(
            root, private_base=lifecycle.private_state_base, windows=windows, label=label
        )
    for root in (lifecycle.package_root, epoch.epochs_root):
        prepare_legacy_product_cutover_root(
            root, private_base=lifecycle.private_data_base, windows=windows, label=label
        )
    return epoch


def legacy_product_fence_exists(control_root: Path) -> bool:
    """Observe the journal name only; the native owner validates its contents."""
    try:
        (control_root / "epoch.jsonl").lstat()
    except FileNotFoundError:
        return False
    return True


def bind_legacy_pre_b_snapshot_owner(
    snapshot_root: Path,
    *,
    store_id: str,
    observed_roots: Iterable[tuple[Path, Mapping[str, tuple[str, ...]]]],
    fence_root: Path,
    source_configuration_root: Path,
    legacy_pointer_root: Path,
    legacy_root_pointer_name: str,
    shared_members: tuple[PackageProductPreBSnapshotSharedMemberV1, ...],
) -> PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner:
    """Bind observed store and lifecycle members to the native cutover inputs."""
    domain_roots: dict[str, Path] = {}
    domain_members: dict[str, tuple[str, ...] | None] = {}
    for root, members in observed_roots:
        if domain_roots.keys() & members.keys():
            raise ValueError("Legacy Product snapshot domains overlap")
        domain_roots.update(dict.fromkeys(members, root))
        domain_members.update(members)
    inert_roots = {
        "fence_record": fence_root,
        "source_configuration": source_configuration_root,
        "legacy_root_pointer": legacy_pointer_root,
    }
    if domain_roots.keys() & inert_roots.keys():
        raise ValueError("Legacy Product snapshot domains overlap")
    domain_roots.update(inert_roots)
    domain_members.update(dict.fromkeys(inert_roots))
    owner_type = (
        PackageProductWindowsPreBSnapshotOwner
        if os.name == "nt"
        else PackageProductPreBSnapshotOwner
    )
    return owner_type(
        snapshot_root,
        store_id=store_id,
        domain_roots=domain_roots,
        domain_members=domain_members,
        legacy_root_pointer_name=legacy_root_pointer_name,
        shared_members=shared_members,
    )


def reopen_legacy_product_cutover(
    *,
    read_only: bool,
    expected_namespace: str | None = None,
    label: str = "Package Product",
    **roots: Unpack[FencedRuntimeOpenKwargs],
) -> PackagePosixEpochCutoverResultV1:
    reopen = (
        reopen_windows_product_cutover
        if os.name == "nt"
        else reopen_posix_product_cutover
    )
    result = reopen(**roots, read_only=read_only)
    switch = result.switch_receipt
    if expected_namespace is not None and (
        switch is None or switch.namespace_id != expected_namespace
    ):
        raise RuntimeError(f"{label} fence belongs to another cutover")
    return result


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


def matches_epoch_layout(runtime: _FencedRuntime, epoch: _LegacyEpoch) -> bool:
    return (
        runtime.registry.store_id == epoch.store_id
        and runtime.control_root == epoch.control_root
    )


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


@contextmanager
def legacy_plugin_management_startup(
    layout: _LegacyStateRoots,
    *,
    policy: _LegacyStartupPolicy,
    hold_startup: Callable[[], bool],
    release_startup: Callable[[], None],
    read_only: bool,
    lifecycle: bool,
) -> Iterator[bool]:
    """Release only the process startup lease acquired by a failed assembly."""

    owns_startup = (
        not read_only
        and (lifecycle or sys.platform.startswith("linux") or os.name == "nt")
        and hold_startup()
    )
    try:
        if not read_only and not owns_startup:
            prepare_private_state_layout(layout, policy=policy)
        yield owns_startup
    except BaseException:
        if owns_startup:
            release_startup()
        raise


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


LegacyCutoverBackupStatus = Literal["retained", "unknown"]
LegacyCutoverBackupReason = Literal[
    "snapshot_verified",
    "snapshot_evidence_missing",
    "snapshot_owner_unavailable",
]
_BackupRecordT = TypeVar("_BackupRecordT")


class _LegacyCutoverBackupFacts:
    """Shared value invariants without slots or nominal Product record ownership."""

    __slots__ = ()
    _backup_label = "Product"

    store_id: str
    namespace_id: str
    snapshot_receipt_id: str
    status: LegacyCutoverBackupStatus
    reason: LegacyCutoverBackupReason
    evidence_id: str | None
    entry_count: int | None
    byte_count: int | None
    status_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.status_version) is not int
            or self.status_version != 1
            or not all((self.store_id, self.namespace_id, self.snapshot_receipt_id))
        ):
            raise ValueError(
                f"{self._backup_label} cutover backup status identity is invalid"
            )
        if self.status == "retained":
            if (
                self.reason != "snapshot_verified"
                or self.evidence_id is None
                or self.entry_count is None
                or self.byte_count is None
            ):
                raise ValueError("Retained cutover backup requires owner evidence")
        elif self.status == "unknown":
            if (
                self.reason
                not in {"snapshot_evidence_missing", "snapshot_owner_unavailable"}
                or self.evidence_id is not None
                or self.entry_count is not None
                or self.byte_count is not None
            ):
                raise ValueError("Unknown cutover backup cannot claim evidence")
        else:
            raise ValueError("Unsupported cutover backup status")


def inspect_legacy_cutover_backup(
    cutover: PackagePosixEpochCutoverResultV1 | PackageWindowsEpochCutoverResultV1,
    *,
    snapshot_root: Path,
    store_id: str,
    status_factory: Callable[..., _BackupRecordT],
    product_label: str,
) -> _BackupRecordT:
    """Correlate the current native fence, switch and retained snapshot owner."""
    if cutover.disposition != "fenced" or cutover.fence is None:
        raise RuntimeError(f"{product_label} Package Product fence is unavailable")
    fence = cutover.fence
    receipt_id = fence.request.snapshot_receipt_id
    reason: LegacyCutoverBackupReason
    snapshot_reader = (
        read_windows_product_pre_b_snapshot
        if os.name == "nt"
        else read_posix_product_pre_b_snapshot
    )
    try:
        evidence = snapshot_reader(
            snapshot_root=snapshot_root,
            store_id=store_id,
            snapshot_receipt_id=receipt_id,
        )
    except FileNotFoundError:
        evidence = None
        reason = "snapshot_owner_unavailable"
    else:
        reason = "snapshot_evidence_missing"
    if evidence is None:
        return status_factory(
            store_id=store_id,
            namespace_id=fence.request.namespace_id,
            snapshot_receipt_id=receipt_id,
            status="unknown",
            reason=reason,
            evidence_id=None,
            entry_count=None,
            byte_count=None,
        )
    snapshot = evidence.snapshot
    if (
        snapshot.store_id != store_id
        or snapshot.legacy_root_identity != fence.request.legacy_root_identity
        or snapshot.quiescence_receipt_id != fence.request.quiescence_receipt_id
        or cutover.switch_receipt is None
        or cutover.switch_receipt.snapshot_receipt_id != receipt_id
    ):
        raise ValueError(
            f"{product_label} cutover backup does not match the current fence"
        )
    return status_factory(
        store_id=store_id,
        namespace_id=fence.request.namespace_id,
        snapshot_receipt_id=receipt_id,
        status="retained",
        reason="snapshot_verified",
        evidence_id=evidence.evidence_id,
        entry_count=snapshot.entry_count,
        byte_count=snapshot.byte_count,
    )
