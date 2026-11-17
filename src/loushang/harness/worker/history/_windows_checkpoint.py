"""Source-bound Windows preparation and checkpoint proofs, without IO authority.

Nominal Product adapters retain their declared dataclass fields and wire schema.
This module owns canonical reconstruction and validation of already-held facts;
it neither approves a Product operation nor publishes or switches journal owners.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from typing import TYPE_CHECKING, ClassVar, Protocol, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._base_codec import _BaseWireMethods
from loushang.harness.worker.history._native_approval import _NativeDecision
from loushang.harness.worker.history._windows_history_join import (
    _WindowsHistoryJoinMethods,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _ATTEMPT,
    _DIGEST,
    _RecoveryFacts,
    _SourceFacts,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


class _WindowsHistorySemanticFacts(Protocol):
    @property
    def source_snapshot(self) -> _SourceFacts: ...
    @property
    def offline_recovery(self) -> _RecoveryFacts: ...
    @property
    def desired_inventory_revision(self) -> int | None: ...
    @property
    def desired_history_digest(self) -> str | None: ...


class _WindowsPackageReferenceFacts(Protocol):
    @property
    def scope_id(self) -> str: ...
    @property
    def store_id(self) -> str: ...
    @property
    def source_snapshot_digest(self) -> str: ...
    @property
    def semantic_digest(self) -> str: ...
    @property
    def history_join_digest(self) -> str: ...
    @property
    def lease_owner_revision(self) -> int: ...
    @property
    def backup_topology_revision(self) -> str: ...
    @property
    def review_digest(self) -> str: ...


def windows_history_semantic_digest(
    semantic: _WindowsHistorySemanticFacts,
    *,
    expected_type: type[_WindowsHistorySemanticFacts],
) -> str:
    if type(semantic) is not expected_type:
        raise ValueError("Windows Worker history semantic read is invalid")
    recovery = semantic.offline_recovery
    facts = {
        "activationStateOwnerPresent": recovery.activation_state_owner_present,
        "activationStateRevision": recovery.activation_state_revision,
        "activationStateRecords": [
            item.to_dict() for item in recovery.activation_state_records
        ],
        "attempts": [
            asdict(cast("DataclassInstance", item)) for item in recovery.attempts
        ],
        "desiredHistoryDigest": semantic.desired_history_digest,
        "desiredInventoryRevision": semantic.desired_inventory_revision,
        "backupObservations": [
            asdict(cast("DataclassInstance", item))
            for item in recovery.worker_backup_observations
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
            asdict(cast("DataclassInstance", item))
            for item in recovery.retained_activation_attempts
        ],
        "storeId": recovery.store_id,
        "supervisorRecords": [item.to_dict() for item in recovery.supervisor_records],
    }
    return sha256(canonical_json_bytes(facts)).hexdigest()


class _WindowsHistoryPreparationMethods(_BaseWireMethods):
    __slots__ = ()
    _source_snapshot_type: ClassVar[type[_SourceFacts]]
    _semantic_read_type: ClassVar[type[_WindowsHistorySemanticFacts]]
    source_snapshot: _SourceFacts
    semantic_digest: str
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not self._source_snapshot_type
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
        if len(raw) > self._wire_maximum():
            raise ValueError("Windows Worker history preparation is invalid")
        return raw

    @classmethod
    def _create_from_semantic_read(cls, semantic: _WindowsHistorySemanticFacts) -> Self:
        digest = windows_history_semantic_digest(
            semantic, expected_type=cls._semantic_read_type
        )
        unsigned = {
            "recordVersion": 1,
            "semanticDigest": digest,
            "sourceSnapshot": semantic.source_snapshot.to_dict(),
        }
        return cast(Callable[..., Self], cls)(
            source_snapshot=semantic.source_snapshot,
            semantic_digest=digest,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _require_semantic_read(self, semantic: _WindowsHistorySemanticFacts) -> None:
        if (
            type(semantic) is not self._semantic_read_type
            or semantic.source_snapshot != self.source_snapshot
            or windows_history_semantic_digest(
                semantic, expected_type=self._semantic_read_type
            )
            != self.semantic_digest
        ):
            raise ValueError("Windows Worker history semantic read changed")


class _WindowsHistoryCheckpointMethods(_BaseWireMethods):
    __slots__ = ()
    _source_snapshot_type: ClassVar[type[_SourceFacts]]
    _package_reference_type: ClassVar[type[_WindowsPackageReferenceFacts]]
    _native_approval_type: ClassVar[type[_NativeDecision]]
    _backup_topology_prefix: ClassVar[str]
    _base_names: ClassVar[tuple[str, ...]]
    source_snapshot: _SourceFacts
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
            type(self.source_snapshot) is not self._source_snapshot_type
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
                self._backup_topology_prefix
            )
            or _DIGEST.fullmatch(
                self.backup_topology_revision.removeprefix(self._backup_topology_prefix)
            )
            is None
            or type(self.gc_reservation_revision) is not int
            or self.gc_reservation_revision < 0
            or type(self.base_digests) is not tuple
            or tuple(name for name, _ in self.base_digests) != self._base_names
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
        if len(raw) > self._wire_maximum():
            raise ValueError("Windows Worker history checkpoint exceeds bound")
        return raw

    @classmethod
    def _from_guarded_bases(
        cls,
        prepared: _WindowsHistoryPreparationMethods,
        semantic: _WindowsHistorySemanticFacts,
        package_review: _WindowsPackageReferenceFacts,
        native_approvals: tuple[_NativeDecision, ...],
        joined: _WindowsHistoryJoinMethods,
    ) -> Self:
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        if (
            type(package_review) is not cls._package_reference_type
            or package_review.source_snapshot_digest != source.snapshot_digest
            or package_review.semantic_digest != prepared.semantic_digest
            or package_review.history_join_digest != joined.review_digest
            or package_review.lease_owner_revision != source.lease_owner_revision
            or package_review.store_id != source.store_id
            or package_review.scope_id != source.scope_id
            or semantic.desired_history_digest is None
            or type(native_approvals) is not tuple
            or any(
                type(item) is not cls._native_approval_type
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
        return cast(Callable[..., Self], cls)(
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
