"""Read-only Windows Worker history source inventory for a future cutover.

This captures byte identities under Product quiescence. It grants no history
retirement, new Worker attempt, or Package GC authority.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)

from .package_product_worker_windows_base_files import (
    WINDOWS_WORKER_BASE_NAMES,
    WINDOWS_WORKER_BASE_STAGE_NAMES,
)
from .package_product_worker_windows_gc_history import (
    CodingWindowsWorkerGcHistoryAuthority,
    _require_known_windows_worker_state_names,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
    _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_FILES = 8192
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_NON_SOURCE_NAMES = (
    frozenset(
        {
            "worker-history-preparation-v1.json",
            "worker-history-preparation-v1.json.stage",
            "worker-history-checkpoint-v1.json",
            "worker-history-checkpoint-v1.json.stage",
        }
    )
    | WINDOWS_WORKER_BASE_NAMES
    | WINDOWS_WORKER_BASE_STAGE_NAMES
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySourceFileV1:
    name: str
    size: int
    sha256_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or not self.name.casefold().startswith(("worker-", ".worker-"))
            or self.name.casefold().endswith(".stage")
            or self.name in _NON_SOURCE_NAMES
            or type(self.size) is not int
            or not 0 <= self.size <= _MAX_FILE_BYTES
            or type(self.sha256_digest) is not str
            or _DIGEST.fullmatch(self.sha256_digest) is None
        ):
            raise ValueError("Windows Worker history source file is invalid")
        _require_known_windows_worker_state_names((self.name,))

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsWorkerHistorySourceFileV1:
        if type(value) is not dict or set(value) != {"name", "size", "sha256"}:
            raise ValueError("Windows Worker history source file is invalid")
        return cls(
            name=value["name"],
            size=value["size"],
            sha256_digest=value["sha256"],
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySourceSnapshotV1:
    scope_id: str
    store_id: str
    lease_owner_revision: int
    files: tuple[CodingWindowsWorkerHistorySourceFileV1, ...]
    snapshot_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 0
            or type(self.files) is not tuple
            or len(self.files) > _MAX_FILES
            or any(
                type(item) is not CodingWindowsWorkerHistorySourceFileV1
                for item in self.files
            )
            or self.files != tuple(sorted(self.files, key=lambda item: item.name))
            or len({item.name.casefold() for item in self.files}) != len(self.files)
            or sum(item.size for item in self.files) > _MAX_TOTAL_BYTES
            or type(self.snapshot_digest) is not str
            or self.snapshot_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history source snapshot is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "leaseOwnerRevision": self.lease_owner_revision,
            "files": [item.to_dict() for item in self.files],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "snapshotDigest": self.snapshot_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsWorkerHistorySourceSnapshotV1:
        if (
            type(value) is not dict
            or set(value)
            != {
                "scopeId",
                "storeId",
                "leaseOwnerRevision",
                "files",
                "snapshotDigest",
            }
            or type(value["files"]) is not list
        ):
            raise ValueError("Windows Worker history source snapshot is invalid")
        return cls(
            scope_id=value["scopeId"],
            store_id=value["storeId"],
            lease_owner_revision=value["leaseOwnerRevision"],
            files=tuple(
                CodingWindowsWorkerHistorySourceFileV1.from_dict(item)
                for item in value["files"]
            ),
            snapshot_digest=value["snapshotDigest"],
        )

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        store_id: str,
        lease_owner_revision: int,
        files: tuple[CodingWindowsWorkerHistorySourceFileV1, ...],
    ) -> CodingWindowsWorkerHistorySourceSnapshotV1:
        unsigned = {
            "scopeId": scope_id,
            "storeId": store_id,
            "leaseOwnerRevision": lease_owner_revision,
            "files": [item.to_dict() for item in files],
        }
        return cls(
            scope_id=scope_id,
            store_id=store_id,
            lease_owner_revision=lease_owner_revision,
            files=files,
            snapshot_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySettlementReviewV1:
    """Momentary source and settled-attempt proof; grants no cutover."""

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    review_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not CodingWindowsWorkerHistorySourceSnapshotV1
            or type(self.review_digest) is not str
            or self.review_digest
            != sha256(
                canonical_json_bytes(
                    {
                        "reviewKind": "coding-windows-worker-settled-history/v1",
                        "sourceSnapshotDigest": self.source_snapshot.snapshot_digest,
                    }
                )
            ).hexdigest()
        ):
            raise ValueError("Windows Worker history settlement review is invalid")

    @classmethod
    def create(
        cls, source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    ) -> CodingWindowsWorkerHistorySettlementReviewV1:
        return cls(
            source_snapshot=source_snapshot,
            review_digest=sha256(
                canonical_json_bytes(
                    {
                        "reviewKind": "coding-windows-worker-settled-history/v1",
                        "sourceSnapshotDigest": source_snapshot.snapshot_digest,
                    }
                )
            ).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySemanticReadV1:
    """One source/semantic read under shared Product locks, without cutover."""

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    offline_recovery: CodingWindowsWorkerOfflineRecoverySnapshotV1
    desired_inventory_revision: int | None = None
    desired_history_digest: str | None = None
    desired_snapshot: PluginDesiredStateSnapshotV1 | None = None
    desired_transitions: tuple[PluginDesiredStateJournalTransition, ...] | None = None

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not CodingWindowsWorkerHistorySourceSnapshotV1
            or type(self.offline_recovery)
            is not CodingWindowsWorkerOfflineRecoverySnapshotV1
            or self.source_snapshot.store_id != self.offline_recovery.store_id
            or self.source_snapshot.lease_owner_revision
            != self.offline_recovery.lease_owner_revision
            or (
                (self.desired_inventory_revision is None)
                != (self.desired_history_digest is None)
            )
            or ((self.desired_snapshot is None) != (self.desired_transitions is None))
            or (
                (self.desired_snapshot is None) != (self.desired_history_digest is None)
            )
            or (
                self.desired_inventory_revision is not None
                and (
                    type(self.desired_inventory_revision) is not int
                    or self.desired_inventory_revision < 0
                    or type(self.desired_history_digest) is not str
                    or _DIGEST.fullmatch(self.desired_history_digest) is None
                )
            )
            or (
                self.desired_snapshot is not None
                and (
                    type(self.desired_snapshot) is not PluginDesiredStateSnapshotV1
                    or type(self.desired_transitions) is not tuple
                    or self.desired_snapshot.inventory_revision
                    != self.desired_inventory_revision
                    or _coding_windows_worker_desired_history_digest(
                        self.desired_snapshot, self.desired_transitions
                    )
                    != self.desired_history_digest
                )
            )
            or self.offline_recovery.gc_revision_refs
            or any(
                observation.worker_backup_supported or observation.references
                for observation in self.offline_recovery.worker_backup_observations
            )
        ):
            raise ValueError("Windows Worker history semantic read is invalid")


def capture_coding_windows_worker_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistorySourceSnapshotV1:
    """Hash all recognized Worker-owned files without changing Product state."""

    return _capture_coding_windows_worker_history_sources(
        product, require_settled_history=False
    )


def review_coding_windows_worker_settled_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistorySettlementReviewV1:
    """Join source bytes to GC's complete-attempt retirement proof."""

    return CodingWindowsWorkerHistorySettlementReviewV1.create(
        _capture_coding_windows_worker_history_sources(
            product, require_settled_history=True
        )
    )


def read_coding_windows_worker_history_semantics(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistorySemanticReadV1:
    """Join settled source bytes and retained semantics without publication."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker history requires its Product owner")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker history runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            if gc_snapshot.active:
                raise ValueError("Windows Worker history GC reservation remains")
            source_snapshot = (
                _capture_coding_windows_worker_history_sources_under_gc_guard(
                    product,
                    store_id=registry.store_id,
                    lease_owner_revision=quiescence.owner_revision,
                    require_settled_history=True,
                )
            )
            offline_recovery = (
                _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard(
                    product,
                    store_id=registry.store_id,
                    lease_owner_revision=quiescence.owner_revision,
                    gc_snapshot=gc_snapshot,
                )
            )
            desired_snapshot, desired_transitions, desired_digest = (
                _capture_coding_windows_worker_desired_history_under_gc_guard(product)
            )
            if source_snapshot != (
                _capture_coding_windows_worker_history_sources_under_gc_guard(
                    product,
                    store_id=registry.store_id,
                    lease_owner_revision=quiescence.owner_revision,
                    require_settled_history=False,
                )
            ):
                raise ValueError("Windows Worker history sources changed")
        product.assert_root_gc_authority_current()
    return CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source_snapshot,
        offline_recovery=offline_recovery,
        desired_inventory_revision=desired_snapshot.inventory_revision,
        desired_history_digest=desired_digest,
        desired_snapshot=desired_snapshot,
        desired_transitions=desired_transitions,
    )


def _coding_windows_worker_desired_history_digest(
    snapshot: PluginDesiredStateSnapshotV1,
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
) -> str:
    """Hash one complete Desired selection and transition capture."""

    if snapshot.inventory_revision != len(transitions):
        raise ValueError("Windows Worker Desired history revision changed")
    return sha256(
        canonical_json_bytes(
            {
                "inventoryRevision": snapshot.inventory_revision,
                "installations": [item.to_dict() for item in snapshot.installations],
                "transitions": [item.to_dict() for item in transitions],
            }
        )
    ).hexdigest()


def _capture_coding_windows_worker_desired_history_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[
    PluginDesiredStateSnapshotV1,
    tuple[PluginDesiredStateJournalTransition, ...],
    str,
]:
    """Bind current Desired selection and its complete transition provenance."""

    product.assert_root_gc_authority_current()
    snapshot, transitions = product.desired_state.capture_read_only()
    digest = _coding_windows_worker_desired_history_digest(snapshot, transitions)
    product.assert_root_gc_authority_current()
    return snapshot, transitions, digest


def _capture_coding_windows_worker_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    require_settled_history: bool,
) -> CodingWindowsWorkerHistorySourceSnapshotV1:
    """Capture source bytes and optionally verify GC's settlement proof."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker history requires its Product owner")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker history runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            snapshot = _capture_coding_windows_worker_history_sources_under_gc_guard(
                product,
                store_id=registry.store_id,
                lease_owner_revision=quiescence.owner_revision,
                require_settled_history=require_settled_history,
            )
        product.assert_root_gc_authority_current()
    return snapshot


def _capture_coding_windows_worker_history_sources_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    store_id: str,
    lease_owner_revision: int,
    require_settled_history: bool,
    allow_preparation_stage: bool = False,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> CodingWindowsWorkerHistorySourceSnapshotV1:
    """Pin all source bytes while the caller owns quiescence and the GC gate."""

    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(root)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise ValueError("Windows Worker history root changed")
            before = tuple(windows_listdir_at(root))
            _require_known_windows_worker_state_names(before)
            if (
                (
                    "worker-history-preparation-v1.json.stage" in before
                    and not allow_preparation_stage
                )
                or (
                    "worker-history-checkpoint-v1.json.stage" in before
                    and not allow_checkpoint_stage
                )
                or (
                    not allow_base_stage
                    and WINDOWS_WORKER_BASE_STAGE_NAMES.intersection(before)
                )
            ):
                raise ValueError("Windows Worker history stage remains")
            names = tuple(
                sorted(
                    name
                    for name in before
                    if name.casefold().startswith(("worker-", ".worker-"))
                    and name not in _NON_SOURCE_NAMES
                )
            )
            if any(name.casefold().endswith(".stage") for name in names):
                raise ValueError("Windows Worker history stage remains")
            if len(names) > _MAX_FILES:
                raise ValueError("Windows Worker history inventory exceeds bound")
            files: list[CodingWindowsWorkerHistorySourceFileV1] = []
            total = 0
            for name in names:
                descriptor = open_windows_regular_file_at(
                    root, name, create_new=False, write=False, read_control=True
                )
                with os.fdopen(descriptor, "rb") as source:
                    acl.validate(source.fileno())
                    if windows_regular_file_stream_names(source.fileno()) != (
                        "::$DATA",
                    ):
                        raise ValueError("Windows Worker history stream changed")
                    opened = os.fstat(source.fileno())
                    digest = sha256()
                    size = 0
                    while chunk := source.read(64 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > _MAX_FILE_BYTES or total > _MAX_TOTAL_BYTES:
                            raise ValueError(
                                "Windows Worker history bytes exceed bound"
                            )
                        digest.update(chunk)
                    closed = os.fstat(source.fileno())
                    if (
                        opened.st_dev,
                        opened.st_ino,
                        opened.st_size,
                        opened.st_mtime_ns,
                        opened.st_ctime_ns,
                    ) != (
                        closed.st_dev,
                        closed.st_ino,
                        closed.st_size,
                        closed.st_mtime_ns,
                        closed.st_ctime_ns,
                    ) or size != opened.st_size:
                        raise ValueError("Windows Worker history source changed")
                    visible = windows_stat_at(root, name)
                    if (
                        not os.path.samestat(closed, visible)
                        or visible.st_size != size
                        or visible.st_mtime_ns != closed.st_mtime_ns
                        or visible.st_ctime_ns != closed.st_ctime_ns
                    ):
                        raise ValueError("Windows Worker history source changed")
                    files.append(
                        CodingWindowsWorkerHistorySourceFileV1(
                            name=name,
                            size=size,
                            sha256_digest=digest.hexdigest(),
                        )
                    )
            if require_settled_history:
                CodingWindowsWorkerGcHistoryAuthority(product).require_settled(
                    observed_names=before,
                    allow_preparation_stage=allow_preparation_stage,
                    allow_checkpoint_stage=allow_checkpoint_stage,
                    allow_base_stage=allow_base_stage,
                )
            if set(windows_listdir_at(root)) != set(before):
                raise ValueError("Windows Worker history inventory changed")
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise ValueError("Windows Worker history root changed")
    product.assert_root_gc_authority_current()
    return CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id=product.policy.project_scope_id,
        store_id=store_id,
        lease_owner_revision=lease_owner_revision,
        files=tuple(files),
    )


__all__ = [
    "CodingWindowsWorkerHistorySourceFileV1",
    "CodingWindowsWorkerHistorySourceSnapshotV1",
    "CodingWindowsWorkerHistorySettlementReviewV1",
    "CodingWindowsWorkerHistorySemanticReadV1",
    "capture_coding_windows_worker_history_sources",
    "read_coding_windows_worker_history_semantics",
    "review_coding_windows_worker_settled_history_sources",
]
