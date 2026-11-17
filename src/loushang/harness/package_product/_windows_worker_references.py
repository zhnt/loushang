"""Desired/Package reference closure for already captured Windows Worker facts.

Product selection and backup support are supplied by the Product's existing
policy/value family. These proofs do not read IO, grant GC authority or switch
journal owners; canonical Worker history and Package lease records stay in their
original components.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Protocol, Self, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import PluginInstallationStateV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.worker.history._windows_checkpoint import (
    _WindowsHistoryPreparationMethods,
    _WindowsHistorySemanticFacts,
)
from loushang.harness.worker.history._windows_history_join import (
    _WindowsHistoryJoinMethods,
)
from loushang.harness.worker.history._windows_receipt_base import (
    _WindowsReceiptBaseMethods,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _DIGEST,
    _WorkerBackupObservationFacts,
)


class _WindowsProductHistorySemanticFacts(_WindowsHistorySemanticFacts, Protocol):
    @property
    def desired_snapshot(self) -> PluginDesiredStateSnapshotV1 | None: ...
    @property
    def desired_transitions(
        self,
    ) -> tuple[PluginDesiredStateJournalTransition, ...] | None: ...


class _WindowsDesiredReferenceMethods:
    __slots__ = ()
    _product_id: ClassVar[str]
    _installation_scope: ClassVar[str]
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    desired_history_digest: str
    desired_inventory_revision: int
    receipt_base_digest: str
    historical_package_revisions: tuple[tuple[str, str], ...]
    current_package_revisions: tuple[tuple[str, str], ...]
    retained_receipt_revisions: tuple[tuple[str, str, str], ...]
    review_digest: str

    def __post_init__(self) -> None:
        if any(
            type(collection) is not tuple
            or any(
                type(values) is not tuple
                or len(values) != width
                or any(type(value) is not str or not value for value in values)
                for values in collection
            )
            for collection, width in (
                (self.historical_package_revisions, 2),
                (self.current_package_revisions, 2),
                (self.retained_receipt_revisions, 3),
            )
        ):
            raise ValueError("Windows Worker Desired reference review is invalid")
        historical = set(self.historical_package_revisions)
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or type(self.store_id) is not str
            or not self.store_id
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or type(self.desired_history_digest) is not str
            or _DIGEST.fullmatch(self.desired_history_digest) is None
            or type(self.receipt_base_digest) is not str
            or _DIGEST.fullmatch(self.receipt_base_digest) is None
            or type(self.desired_inventory_revision) is not int
            or self.desired_inventory_revision < 0
            or self.historical_package_revisions != tuple(sorted(historical))
            or any(_DIGEST.fullmatch(digest) is None for _, digest in historical)
            or self.current_package_revisions
            != tuple(sorted(set(self.current_package_revisions)))
            or self.retained_receipt_revisions
            != tuple(sorted(set(self.retained_receipt_revisions)))
            or not set(self.current_package_revisions).issubset(historical)
            or any(
                (plugin_id, artifact_digest) not in historical
                or _DIGEST.fullmatch(artifact_digest) is None
                or _DIGEST.fullmatch(fingerprint) is None
                for fingerprint, plugin_id, artifact_digest in self.retained_receipt_revisions
            )
            or type(self.review_digest) is not str
            or self.review_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker Desired reference review is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "currentPackageRevisions": [
                list(item) for item in self.current_package_revisions
            ],
            "desiredHistoryDigest": self.desired_history_digest,
            "desiredInventoryRevision": self.desired_inventory_revision,
            "historicalPackageRevisions": [
                list(item) for item in self.historical_package_revisions
            ],
            "retainedReceiptRevisions": [
                list(item) for item in self.retained_receipt_revisions
            ],
            "receiptBaseDigest": self.receipt_base_digest,
            "scopeId": self.scope_id,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
            "version": 1,
        }

    @classmethod
    def _from_captured_desired(
        cls,
        semantic: _WindowsProductHistorySemanticFacts,
        receipt_base: _WindowsReceiptBaseMethods,
    ) -> Self:
        desired_snapshot = semantic.desired_snapshot
        desired_transitions = semantic.desired_transitions
        if (
            desired_snapshot is None
            or desired_transitions is None
            or semantic.desired_history_digest is None
        ):
            raise ValueError("Windows Worker Desired history changed")
        if (
            type(desired_snapshot) is not PluginDesiredStateSnapshotV1
            or type(desired_transitions) is not tuple
            or semantic.desired_inventory_revision
            != desired_snapshot.inventory_revision
        ):
            raise ValueError("Windows Worker Desired history changed")
        scope_id = semantic.source_snapshot.scope_id

        def selected_revision(
            state: PluginInstallationStateV1,
        ) -> tuple[str, str] | None:
            key = state.installation_key
            revision = state.selection.package_revision
            if (
                key.product_id != cls._product_id
                or key.installation_scope != cls._installation_scope
                or key.scope_id != scope_id
                or revision is None
            ):
                return None
            return key.plugin_id, revision.package_content_digest

        latest = {
            transition.committed_state.installation_key: transition.committed_state
            for transition in desired_transitions
        }
        if (
            tuple(item.inventory_revision for item in desired_transitions)
            != tuple(range(1, desired_snapshot.inventory_revision + 1))
            or tuple(sorted(latest.values(), key=lambda item: item.installation_key))
            != desired_snapshot.installations
        ):
            raise ValueError("Windows Worker Desired projection changed")
        historical = tuple(
            sorted(
                {
                    revision
                    for transition in desired_transitions
                    if (revision := selected_revision(transition.committed_state))
                    is not None
                }
            )
        )
        current = tuple(
            sorted(
                {
                    revision
                    for state in desired_snapshot.installations
                    if (revision := selected_revision(state)) is not None
                }
            )
        )
        receipts = tuple(
            sorted(
                (
                    record.receipt.fingerprint,
                    record.receipt.policy.plugin_id,
                    record.receipt.policy.plugin_revision_digest,
                )
                for record in semantic.offline_recovery.receipt_records
            )
        )
        if any(
            (plugin_id, digest) not in historical for _, plugin_id, digest in receipts
        ):
            raise ValueError("Windows Worker receipt lacks Desired selection")
        unsigned = {
            "currentPackageRevisions": [list(item) for item in current],
            "desiredHistoryDigest": semantic.desired_history_digest,
            "desiredInventoryRevision": desired_snapshot.inventory_revision,
            "historicalPackageRevisions": [list(item) for item in historical],
            "retainedReceiptRevisions": [list(item) for item in receipts],
            "receiptBaseDigest": receipt_base.record_digest,
            "scopeId": scope_id,
            "sourceSnapshotDigest": semantic.source_snapshot.snapshot_digest,
            "storeId": semantic.source_snapshot.store_id,
            "version": 1,
        }
        return cast(Callable[..., Self], cls)(
            scope_id=scope_id,
            store_id=semantic.source_snapshot.store_id,
            source_snapshot_digest=semantic.source_snapshot.snapshot_digest,
            desired_history_digest=semantic.desired_history_digest,
            desired_inventory_revision=desired_snapshot.inventory_revision,
            receipt_base_digest=receipt_base.record_digest,
            historical_package_revisions=historical,
            current_package_revisions=current,
            retained_receipt_revisions=receipts,
            review_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


class _WindowsPackageReferenceMethods:
    __slots__ = ()
    _backup_observation_type: ClassVar[type[_WorkerBackupObservationFacts]]
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    semantic_digest: str
    desired_review_digest: str
    history_join_digest: str
    lease_owner_revision: int
    backup_topology_revision: str
    repaired_runtime_leases: tuple[tuple[str, str, int], ...]
    worker_backup_observations: tuple[tuple[str, str], ...]
    review_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or type(self.store_id) is not str
            or not self.store_id
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.source_snapshot_digest,
                    self.semantic_digest,
                    self.desired_review_digest,
                    self.history_join_digest,
                    self.review_digest,
                )
            )
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or type(self.backup_topology_revision) is not str
            or not self.backup_topology_revision
            or self.repaired_runtime_leases
            != tuple(sorted(set(self.repaired_runtime_leases)))
            or any(
                type(runtime_id) is not str
                or not runtime_id
                or type(lease_id) is not str
                or _DIGEST.fullmatch(lease_id) is None
                or type(revision) is not int
                or not 0 < revision < self.lease_owner_revision
                for runtime_id, lease_id, revision in self.repaired_runtime_leases
            )
            or self.worker_backup_observations
            != tuple(sorted(set(self.worker_backup_observations)))
            or any(
                type(attempt_id) is not str
                or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None
                or type(owner_revision) is not str
                or not owner_revision
                for attempt_id, owner_revision in self.worker_backup_observations
            )
            or self.review_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker Package reference review is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "backupTopologyRevision": self.backup_topology_revision,
            "desiredReviewDigest": self.desired_review_digest,
            "historyJoinDigest": self.history_join_digest,
            "leaseOwnerRevision": self.lease_owner_revision,
            "repairedRuntimeLeases": [
                list(item) for item in self.repaired_runtime_leases
            ],
            "scopeId": self.scope_id,
            "semanticDigest": self.semantic_digest,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
            "version": 1,
            "workerBackupObservations": [
                list(item) for item in self.worker_backup_observations
            ],
        }

    @classmethod
    def _require_reference_inputs(
        cls,
        semantic: _WindowsProductHistorySemanticFacts,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        backup_topology: _WorkerBackupObservationFacts,
    ) -> None:
        recovery = semantic.offline_recovery
        if (
            type(quiescence) is not PackageWindowsRuntimeQuiescenceV1
            or quiescence.store_id != semantic.source_snapshot.store_id
            or quiescence.owner_revision
            != semantic.source_snapshot.lease_owner_revision
            or quiescence.active_runtime_lease_ids
            or recovery.gc_revision_refs
            or type(backup_topology) is not cls._backup_observation_type
            or backup_topology.attempt_id != "0" * 32
            or backup_topology.worker_backup_supported
            or backup_topology.references
        ):
            raise ValueError("Windows Worker Package reference closure changed")

    @classmethod
    def _from_closed_references(
        cls,
        prepared: _WindowsHistoryPreparationMethods,
        semantic: _WindowsProductHistorySemanticFacts,
        *,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        backup_topology: _WorkerBackupObservationFacts,
        desired: _WindowsDesiredReferenceMethods,
        joined: _WindowsHistoryJoinMethods,
    ) -> Self:
        recovery = semantic.offline_recovery
        attempts = tuple(sorted(item.attempt_id for item in recovery.attempts))
        observations = recovery.worker_backup_observations
        if (
            len(observations) != len(attempts)
            or tuple(sorted(item.attempt_id for item in observations)) != attempts
            or any(
                item.worker_backup_supported or item.references for item in observations
            )
            or any(
                item.owner_revision != backup_topology.owner_revision
                for item in observations
            )
        ):
            raise ValueError("Windows Worker backup references are not closed")
        receipts = {
            record.receipt.fingerprint: record.receipt
            for record in recovery.receipt_records
        }
        runtime_ids = {
            receipt.policy.product_runtime_id for receipt in receipts.values()
        }
        repaired_records = quiescence.repaired_runtime_records
        if any(
            record.store_id != quiescence.store_id
            or record.kind != "orphan_repaired"
            or record.record_revision >= quiescence.owner_revision
            for record in repaired_records
        ):
            raise ValueError("Windows Worker Package lease repair changed")
        relevant_repairs = tuple(
            sorted(
                (
                    record.lease.runtime_id,
                    record.lease.lease_id,
                    record.record_revision,
                )
                for record in repaired_records
                if record.lease.runtime_id in runtime_ids
            )
        )
        if len({item[0] for item in relevant_repairs}) != len(relevant_repairs):
            raise ValueError("Windows Worker Package lease repair is ambiguous")
        backups = tuple(
            sorted((item.attempt_id, item.owner_revision) for item in observations)
        )
        unsigned = {
            "backupTopologyRevision": backup_topology.owner_revision,
            "desiredReviewDigest": desired.review_digest,
            "historyJoinDigest": joined.review_digest,
            "leaseOwnerRevision": quiescence.owner_revision,
            "repairedRuntimeLeases": [list(item) for item in relevant_repairs],
            "scopeId": semantic.source_snapshot.scope_id,
            "semanticDigest": prepared.semantic_digest,
            "sourceSnapshotDigest": semantic.source_snapshot.snapshot_digest,
            "storeId": quiescence.store_id,
            "version": 1,
            "workerBackupObservations": [list(item) for item in backups],
        }
        return cast(Callable[..., Self], cls)(
            scope_id=semantic.source_snapshot.scope_id,
            store_id=quiescence.store_id,
            source_snapshot_digest=semantic.source_snapshot.snapshot_digest,
            semantic_digest=prepared.semantic_digest,
            desired_review_digest=desired.review_digest,
            history_join_digest=joined.review_digest,
            lease_owner_revision=quiescence.owner_revision,
            backup_topology_revision=backup_topology.owner_revision,
            repaired_runtime_leases=relevant_repairs,
            worker_backup_observations=backups,
            review_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


def windows_worker_desired_history_digest(
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


def capture_windows_product_worker_desired_history(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[
    PluginDesiredStateSnapshotV1,
    tuple[PluginDesiredStateJournalTransition, ...],
    str,
]:
    """Bind current Desired selection and its complete transition provenance."""

    product.assert_root_gc_authority_current()
    snapshot, transitions = product.desired_state.capture_read_only()
    digest = windows_worker_desired_history_digest(snapshot, transitions)
    product.assert_root_gc_authority_current()
    return snapshot, transitions, digest
