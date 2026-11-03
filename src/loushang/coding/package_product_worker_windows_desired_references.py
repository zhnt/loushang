"""Read-only Desired State reference join for Windows Worker history cutover.

The Product must supply the Desired capture behind its GC guard. This review
binds historical receipts to selected Package revisions but cannot commit a
checkpoint, switch readers, or retire source bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import PluginInstallationStateV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerDesiredReferenceReviewV1:
    """Exact selected-revision references from one retained Desired history."""

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
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerDesiredReferenceReviewV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker Desired preparation is invalid")
        prepared.require_semantic_read(semantic)
        receipt_base = CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
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
                key.product_id != "coding"
                or key.installation_scope != "workspace"
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
        return cls(
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


__all__ = ["CodingWindowsWorkerDesiredReferenceReviewV1"]
