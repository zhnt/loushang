"""Canonical Windows Worker history preparation, without cutover authority.

The record binds a complete guarded source inventory to one semantic read. It
cannot replace the original journals, permit a fresh attempt, or delete bytes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from hashlib import sha256

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
    _capture_coding_windows_worker_desired_history_under_gc_guard,
    _capture_coding_windows_worker_history_sources_under_gc_guard,
)
from .package_product_worker_windows_recovery_inventory import (
    _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RECORD_BYTES = 8 * 1024 * 1024
_PREPARATION_NAME = "worker-history-preparation-v1.json"


def _semantic_digest(semantic: CodingWindowsWorkerHistorySemanticReadV1) -> str:
    if type(semantic) is not CodingWindowsWorkerHistorySemanticReadV1:
        raise ValueError("Windows Worker history semantic read is invalid")
    recovery = semantic.offline_recovery
    facts = {
        "activationStateOwnerPresent": recovery.activation_state_owner_present,
        "activationStateRevision": recovery.activation_state_revision,
        "activationStateRecords": [
            item.to_dict() for item in recovery.activation_state_records
        ],
        "attempts": [asdict(item) for item in recovery.attempts],
        "desiredHistoryDigest": semantic.desired_history_digest,
        "desiredInventoryRevision": semantic.desired_inventory_revision,
        "backupObservations": [
            asdict(item) for item in recovery.worker_backup_observations
        ],
        "gcReservationRevision": recovery.gc_reservation_revision,
        "leaseOwnerRevision": recovery.lease_owner_revision,
        "launchIntents": [item.to_dict() for item in recovery.launch_intents],
        "nativeJobAbsence": [list(item) for item in recovery.native_job_absence],
        "nativeProvisioningAttempts": [
            {
                "attemptId": item.attempt_id,
                "records": [record.to_dict() for record in item.records],
            }
            for item in recovery.native_provisioning_attempts
        ],
        "optInDecisions": [item.to_dict() for item in recovery.opt_in_decisions],
        "receiptRecords": [item.to_dict() for item in recovery.receipt_records],
        "retainedActivationAttempts": [
            asdict(item) for item in recovery.retained_activation_attempts
        ],
        "storeId": recovery.store_id,
        "supervisorRecords": [item.to_dict() for item in recovery.supervisor_records],
    }
    return sha256(canonical_json_bytes(facts)).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryPreparationV1:
    """A no-authority commitment to exact source and semantic identities."""

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    semantic_digest: str
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not CodingWindowsWorkerHistorySourceSnapshotV1
            or type(self.semantic_digest) is not str
            or _DIGEST.fullmatch(self.semantic_digest) is None
            or type(self.record_version) is not int
            or self.record_version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history preparation is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "recordVersion": self.record_version,
            "semanticDigest": self.semantic_digest,
            "sourceSnapshot": self.source_snapshot.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(self.to_dict())
        if len(raw) > _MAX_RECORD_BYTES:
            raise ValueError("Windows Worker history preparation is invalid")
        return raw

    @classmethod
    def create(
        cls, semantic: CodingWindowsWorkerHistorySemanticReadV1
    ) -> CodingWindowsWorkerHistoryPreparationV1:
        digest = _semantic_digest(semantic)
        unsigned = {
            "recordVersion": 1,
            "semanticDigest": digest,
            "sourceSnapshot": semantic.source_snapshot.to_dict(),
        }
        return cls(
            source_snapshot=semantic.source_snapshot,
            semantic_digest=digest,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerHistoryPreparationV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_RECORD_BYTES:
            raise ValueError("Windows Worker history preparation is invalid")
        try:
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {
                "recordVersion",
                "semanticDigest",
                "sourceSnapshot",
                "recordDigest",
            }:
                raise ValueError("Windows Worker history preparation is invalid")
            record = cls(
                source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(
                    value["sourceSnapshot"]
                ),
                semantic_digest=value["semanticDigest"],
                record_digest=value["recordDigest"],
                record_version=value["recordVersion"],
            )
            if record.to_bytes() != raw:
                raise ValueError("Windows Worker history preparation is invalid")
            return record
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Worker history preparation is invalid") from exc

    def require_semantic_read(
        self, semantic: CodingWindowsWorkerHistorySemanticReadV1
    ) -> None:
        if (
            type(semantic) is not CodingWindowsWorkerHistorySemanticReadV1
            or semantic.source_snapshot != self.source_snapshot
            or _semantic_digest(semantic) != self.semantic_digest
        ):
            raise ValueError("Windows Worker history semantic read changed")


def prepare_coding_windows_worker_history(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryPreparationV1:
    """Durably bind guarded source/semantic proof without switching authority."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker history preparation requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker history runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            gc_snapshot = product.gc_gate.snapshot()
            if gc_snapshot.active:
                raise ValueError("Windows Worker history GC reservation remains")
            path = product.state_root / _PREPARATION_NAME
            published = read_windows_private_receipt(
                path,
                maximum_bytes=_MAX_RECORD_BYTES,
                allow_unpublished_stage=True,
            )
            staged = read_windows_private_receipt(
                path.with_name(_PREPARATION_NAME + ".stage"),
                maximum_bytes=_MAX_RECORD_BYTES,
            )
            if staged is not None:
                CodingWindowsWorkerHistoryPreparationV1.from_bytes(staged)
            source_snapshot = (
                _capture_coding_windows_worker_history_sources_under_gc_guard(
                    product,
                    store_id=registry.store_id,
                    lease_owner_revision=quiescence.owner_revision,
                    require_settled_history=True,
                    allow_preparation_stage=staged is not None,
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
                    allow_preparation_stage=staged is not None,
                )
            ):
                raise ValueError("Windows Worker history sources changed")
            semantic = CodingWindowsWorkerHistorySemanticReadV1(
                source_snapshot=source_snapshot,
                offline_recovery=offline_recovery,
                desired_inventory_revision=desired_snapshot.inventory_revision,
                desired_history_digest=desired_digest,
                desired_snapshot=desired_snapshot,
                desired_transitions=desired_transitions,
            )
            prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
            for existing in (published, staged):
                if existing is not None:
                    CodingWindowsWorkerHistoryPreparationV1.from_bytes(
                        existing
                    ).require_semantic_read(semantic)
            if staged is not None:
                write_windows_private_receipt(
                    path, staged, maximum_bytes=_MAX_RECORD_BYTES
                )
            if published is None and staged is None:
                write_windows_private_receipt(
                    path, prepared.to_bytes(), maximum_bytes=_MAX_RECORD_BYTES
                )
            retained = read_windows_private_receipt(
                path, maximum_bytes=_MAX_RECORD_BYTES
            )
            if retained != prepared.to_bytes():
                raise ValueError("Windows Worker history preparation changed")
            product.assert_root_gc_authority_current()
        return prepared


__all__ = [
    "CodingWindowsWorkerHistoryPreparationV1",
    "prepare_coding_windows_worker_history",
]
