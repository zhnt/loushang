"""Canonical Windows Worker history checkpoint record.

The record binds source bytes, semantic bases, and Product reference closure.
Publication and an eventual owner switch must provide separate authority.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1,
)
from .package_product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from .package_product_worker_windows_native_approval_journal import (
    CodingWindowsWorkerNativeApprovalJournal,
)
from .package_product_worker_windows_package_references import (
    CodingWindowsWorkerPackageReferenceReviewV1,
    _review_coding_windows_worker_package_references_under_guard,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BYTES = 8 * 1024 * 1024
_CHECKPOINT_NAME = "worker-history-checkpoint-v1.json"
_PREPARATION_NAME = "worker-history-preparation-v1.json"
_BASE_NAMES = (
    "optIn",
    "receipt",
    "supervisor",
    "c5",
    "launchIntent",
    "nativeProvisioning",
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryCheckpointV1:
    """An exact pre-cutover commitment to six source-bound semantic bases."""

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    preparation_digest: str
    package_reference_digest: str
    desired_history_digest: str
    backup_topology_revision: str
    gc_reservation_revision: int
    base_digests: tuple[tuple[str, str], ...]
    native_approval_record_digests: tuple[str, ...]
    native_approval_operation_ids: tuple[str, ...]
    native_approval_generation: int
    opt_in_operation_ids: tuple[str, ...]
    receipt_fingerprints: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    native_provisioning_attempt_ids: tuple[str, ...]
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not CodingWindowsWorkerHistorySourceSnapshotV1
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.preparation_digest,
                    self.package_reference_digest,
                    self.desired_history_digest,
                    self.record_digest,
                )
            )
            or type(self.backup_topology_revision) is not str
            or not self.backup_topology_revision.startswith(
                "coding-product-backup-types:"
            )
            or _DIGEST.fullmatch(
                self.backup_topology_revision.removeprefix(
                    "coding-product-backup-types:"
                )
            )
            is None
            or type(self.gc_reservation_revision) is not int
            or self.gc_reservation_revision < 0
            or type(self.base_digests) is not tuple
            or tuple(name for name, _ in self.base_digests) != _BASE_NAMES
            or any(_DIGEST.fullmatch(digest) is None for _, digest in self.base_digests)
            or type(self.native_approval_record_digests) is not tuple
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in self.native_approval_record_digests
            )
            or type(self.native_approval_operation_ids) is not tuple
            or self.native_approval_operation_ids
            != tuple(sorted(set(self.native_approval_operation_ids)))
            or len(self.native_approval_operation_ids)
            != len(self.native_approval_record_digests)
            or any(
                type(value) is not str or not value or len(value) > 128
                for value in self.native_approval_operation_ids
            )
            or type(self.native_approval_generation) is not int
            or self.native_approval_generation
            != len(self.native_approval_record_digests)
            or self.opt_in_operation_ids
            != tuple(sorted(set(self.opt_in_operation_ids)))
            or any(
                type(value) is not str or not value or len(value) > 128
                for value in self.opt_in_operation_ids
            )
            or self.receipt_fingerprints
            != tuple(sorted(set(self.receipt_fingerprints)))
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in self.receipt_fingerprints
            )
            or self.attempt_ids != tuple(sorted(set(self.attempt_ids)))
            or any(
                type(value) is not str or _ATTEMPT.fullmatch(value) is None
                for value in self.attempt_ids
            )
            or self.native_provisioning_attempt_ids
            != tuple(sorted(set(self.native_provisioning_attempt_ids)))
            or not set(self.native_provisioning_attempt_ids).issubset(self.attempt_ids)
            or type(self.record_version) is not int
            or self.record_version != 1
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history checkpoint is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "attemptIds": list(self.attempt_ids),
            "backupTopologyRevision": self.backup_topology_revision,
            "baseDigests": [list(item) for item in self.base_digests],
            "desiredHistoryDigest": self.desired_history_digest,
            "gcReservationRevision": self.gc_reservation_revision,
            "nativeProvisioningAttemptIds": list(self.native_provisioning_attempt_ids),
            "nativeApprovalGeneration": self.native_approval_generation,
            "nativeApprovalOperationIds": list(self.native_approval_operation_ids),
            "nativeApprovalRecordDigests": list(self.native_approval_record_digests),
            "optInOperationIds": list(self.opt_in_operation_ids),
            "packageReferenceDigest": self.package_reference_digest,
            "preparationDigest": self.preparation_digest,
            "receiptFingerprints": list(self.receipt_fingerprints),
            "recordVersion": self.record_version,
            "sourceSnapshot": self.source_snapshot.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(self.to_dict())
        if len(raw) > _MAX_BYTES:
            raise ValueError("Windows Worker history checkpoint exceeds bound")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerHistoryCheckpointV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise ValueError("Windows Worker history checkpoint is invalid")
        try:
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {
                "attemptIds",
                "backupTopologyRevision",
                "baseDigests",
                "desiredHistoryDigest",
                "gcReservationRevision",
                "nativeProvisioningAttemptIds",
                "nativeApprovalGeneration",
                "nativeApprovalOperationIds",
                "nativeApprovalRecordDigests",
                "optInOperationIds",
                "packageReferenceDigest",
                "preparationDigest",
                "receiptFingerprints",
                "recordVersion",
                "sourceSnapshot",
                "recordDigest",
            }:
                raise ValueError("Windows Worker history checkpoint is invalid")
            record = cls(
                source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(
                    value["sourceSnapshot"]
                ),
                preparation_digest=value["preparationDigest"],
                package_reference_digest=value["packageReferenceDigest"],
                desired_history_digest=value["desiredHistoryDigest"],
                backup_topology_revision=value["backupTopologyRevision"],
                gc_reservation_revision=value["gcReservationRevision"],
                base_digests=tuple(tuple(item) for item in value["baseDigests"]),
                native_approval_record_digests=tuple(
                    value["nativeApprovalRecordDigests"]
                ),
                native_approval_operation_ids=tuple(
                    value["nativeApprovalOperationIds"]
                ),
                native_approval_generation=value["nativeApprovalGeneration"],
                opt_in_operation_ids=tuple(value["optInOperationIds"]),
                receipt_fingerprints=tuple(value["receiptFingerprints"]),
                attempt_ids=tuple(value["attemptIds"]),
                native_provisioning_attempt_ids=tuple(
                    value["nativeProvisioningAttemptIds"]
                ),
                record_digest=value["recordDigest"],
                record_version=value["recordVersion"],
            )
            if record.to_bytes() != raw:
                raise ValueError("Windows Worker history checkpoint is invalid")
            return record
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Worker history checkpoint is invalid") from exc

    @classmethod
    def from_guarded_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
        package_review: CodingWindowsWorkerPackageReferenceReviewV1,
        native_approvals: tuple[CodingWorkerNativeApprovalDecisionV1, ...],
    ) -> CodingWindowsWorkerHistoryCheckpointV1:
        """Derive the canonical record from one held Product preflight read."""

        prepared.require_semantic_read(semantic)
        joined = CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
            prepared, semantic
        )
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        if (
            type(package_review) is not CodingWindowsWorkerPackageReferenceReviewV1
            or package_review.source_snapshot_digest != source.snapshot_digest
            or package_review.semantic_digest != prepared.semantic_digest
            or package_review.history_join_digest != joined.review_digest
            or package_review.lease_owner_revision != source.lease_owner_revision
            or package_review.store_id != source.store_id
            or package_review.scope_id != source.scope_id
            or semantic.desired_history_digest is None
            or type(native_approvals) is not tuple
            or any(
                type(item) is not CodingWorkerNativeApprovalDecisionV1
                or item.scope_id != source.scope_id
                or item.journal_revision != index
                or item.generation != index
                for index, item in enumerate(native_approvals, start=1)
            )
            or len({item.operation_id for item in native_approvals})
            != len(native_approvals)
        ):
            raise ValueError("Windows Worker checkpoint references changed")
        raw_approvals = b"".join(
            canonical_json_bytes(item.to_dict()) + b"\n" for item in native_approvals
        )
        approval_source = next(
            (
                item
                for item in source.files
                if item.name == "worker-native-release-approvals.jsonl"
            ),
            None,
        )
        if (approval_source is None) != (not native_approvals) or (
            approval_source is not None
            and (
                approval_source.size != len(raw_approvals)
                or approval_source.sha256_digest != sha256(raw_approvals).hexdigest()
            )
        ):
            raise ValueError("Windows Worker native approval history changed")
        bases = (
            ("optIn", joined.opt_in.record_digest),
            ("receipt", joined.receipt.record_digest),
            ("supervisor", joined.supervisor.record_digest),
            ("c5", joined.c5.record_digest),
            ("launchIntent", joined.launch_intent.record_digest),
            ("nativeProvisioning", joined.native_provisioning.record_digest),
        )
        unsigned = {
            "attemptIds": list(joined.observed_attempt_ids),
            "backupTopologyRevision": package_review.backup_topology_revision,
            "baseDigests": [list(item) for item in bases],
            "desiredHistoryDigest": semantic.desired_history_digest,
            "gcReservationRevision": recovery.gc_reservation_revision,
            "nativeProvisioningAttemptIds": list(
                joined.native_provisioning.attempt_ids
            ),
            "nativeApprovalGeneration": len(native_approvals),
            "nativeApprovalOperationIds": sorted(
                item.operation_id for item in native_approvals
            ),
            "nativeApprovalRecordDigests": [
                item.record_digest for item in native_approvals
            ],
            "optInOperationIds": list(recovery.retained_opt_in_operation_ids),
            "packageReferenceDigest": package_review.review_digest,
            "preparationDigest": prepared.record_digest,
            "receiptFingerprints": list(recovery.retained_receipt_fingerprints),
            "recordVersion": 1,
            "sourceSnapshot": source.to_dict(),
        }
        return cls(
            source_snapshot=source,
            preparation_digest=prepared.record_digest,
            package_reference_digest=package_review.review_digest,
            desired_history_digest=semantic.desired_history_digest,
            backup_topology_revision=package_review.backup_topology_revision,
            gc_reservation_revision=recovery.gc_reservation_revision,
            base_digests=bases,
            native_approval_record_digests=tuple(
                item.record_digest for item in native_approvals
            ),
            native_approval_operation_ids=tuple(
                sorted(item.operation_id for item in native_approvals)
            ),
            native_approval_generation=len(native_approvals),
            opt_in_operation_ids=recovery.retained_opt_in_operation_ids,
            receipt_fingerprints=recovery.retained_receipt_fingerprints,
            attempt_ids=joined.observed_attempt_ids,
            native_provisioning_attempt_ids=joined.native_provisioning.attempt_ids,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


def _current_checkpoint_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
    allow_checkpoint_stage: bool,
    allow_base_stage: bool = False,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    review, prepared, semantic = (
        _review_coding_windows_worker_package_references_under_guard(
            product,
            quiescence=quiescence,
            gc_snapshot=gc_snapshot,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        )
    )
    retained_preparation = read_windows_private_receipt(
        product.state_root / _PREPARATION_NAME,
        maximum_bytes=_MAX_BYTES,
    )
    if retained_preparation != prepared.to_bytes():
        raise ValueError("Windows Worker checkpoint preparation changed")
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        native_approvals = CodingWindowsWorkerNativeApprovalJournal(
            product.state_root / "worker-native-release-approvals.jsonl",
            scope_id=product.policy.project_scope_id,
        ).history_read_only(directory_fd=root)
    return CodingWindowsWorkerHistoryCheckpointV1.from_guarded_read(
        prepared, semantic, review, native_approvals
    )


def read_coding_windows_worker_history_checkpoint(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Reprove published checkpoint bytes against the current guarded Product."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker checkpoint requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker checkpoint runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            published = read_windows_private_receipt(
                product.state_root / _CHECKPOINT_NAME,
                maximum_bytes=_MAX_BYTES,
            )
            if published is None:
                raise ValueError("Windows Worker checkpoint is absent")
            checkpoint = CodingWindowsWorkerHistoryCheckpointV1.from_bytes(published)
            current = _current_checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=product.gc_gate.snapshot(),
                allow_checkpoint_stage=False,
            )
            if checkpoint != current:
                raise ValueError("Windows Worker checkpoint source changed")
            retained = read_windows_private_receipt(
                product.state_root / _CHECKPOINT_NAME,
                maximum_bytes=_MAX_BYTES,
            )
            if retained != published:
                raise ValueError("Windows Worker checkpoint publication changed")
            product.assert_root_gc_authority_current()
            return checkpoint


def publish_coding_windows_worker_history_checkpoint(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Publish exact pre-cutover bytes under Package quiescence and the GC gate.

    The old journals remain authoritative. A staged retry is completed only
    when its full record still equals the freshly joined Product state.
    """

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker checkpoint requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker checkpoint runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            gc_snapshot = product.gc_gate.snapshot()
            path = product.state_root / _CHECKPOINT_NAME
            published = read_windows_private_receipt(
                path, maximum_bytes=_MAX_BYTES, allow_unpublished_stage=True
            )
            staged = read_windows_private_receipt(
                path.with_name(_CHECKPOINT_NAME + ".stage"),
                maximum_bytes=_MAX_BYTES,
            )
            for raw in (published, staged):
                if raw is not None:
                    CodingWindowsWorkerHistoryCheckpointV1.from_bytes(raw)
            checkpoint = _current_checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_checkpoint_stage=staged is not None,
            )
            candidate = checkpoint.to_bytes()
            if any(raw is not None and raw != candidate for raw in (published, staged)):
                raise ValueError("Windows Worker checkpoint source changed")
            if published is None:
                write_windows_private_receipt(path, candidate, maximum_bytes=_MAX_BYTES)
            retained = read_windows_private_receipt(path, maximum_bytes=_MAX_BYTES)
            if retained != candidate:
                raise ValueError("Windows Worker checkpoint publication changed")
            product.assert_root_gc_authority_current()
            return checkpoint


__all__ = [
    "CodingWindowsWorkerHistoryCheckpointV1",
    "read_coding_windows_worker_history_checkpoint",
    "publish_coding_windows_worker_history_checkpoint",
]
