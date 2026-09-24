"""Build an inert, snapshot-bound review record for one old local Installation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_installation_inventory import (
    CodingLegacyInstalledState,
    CodingLegacyInventoryError,
    read_coding_legacy_installation_inventory,
)
from .package_legacy_reacquisition import CodingLegacyReacquiredInstallationV1
from .package_legacy_snapshot_member import CodingFirstBLegacyStateObserver


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalAdoptionReviewV1:
    """Exact inputs to show an operator; this grants no publication authority."""

    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    legacy_root_identity: str
    legacy_state_evidence_id: str
    legacy_state_digest: str
    legacy_entry_count: int
    legacy_byte_count: int
    plugin_id: str
    desired_state: CodingLegacyInstalledState
    legacy_source_identity: str
    legacy_binding_digest: str
    legacy_lockfile_digest: str
    legacy_desired_journal_digest: str
    source_content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    wheel_filename: str
    wheel_artifact_digest: str
    policy_revision: str
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "review_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, str | int]:
        return {
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "firstFenceId": self.first_fence_id,
            "snapshotReceiptId": self.snapshot_receipt_id,
            "legacyRootIdentity": self.legacy_root_identity,
            "legacyStateEvidenceId": self.legacy_state_evidence_id,
            "legacyStateDigest": self.legacy_state_digest,
            "legacyEntryCount": self.legacy_entry_count,
            "legacyByteCount": self.legacy_byte_count,
            "pluginId": self.plugin_id,
            "desiredState": self.desired_state,
            "legacySourceIdentity": self.legacy_source_identity,
            "legacyBindingDigest": self.legacy_binding_digest,
            "legacyLockfileDigest": self.legacy_lockfile_digest,
            "legacyDesiredJournalDigest": self.legacy_desired_journal_digest,
            "sourceContentDigest": self.source_content_digest,
            "manifestDigest": self.manifest_digest,
            "dependencyLockDigest": self.dependency_lock_digest,
            "wheelFilename": self.wheel_filename,
            "wheelArtifactDigest": self.wheel_artifact_digest,
            "policyRevision": self.policy_revision,
        }

    def to_dict(self) -> dict[str, str | int]:
        return {"reviewId": self.review_id, **self._identity_dict()}


def review_coding_legacy_reacquired_installation(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    reacquired: CodingLegacyReacquiredInstallationV1,
    *,
    policy_revision: str,
) -> CodingLegacyLocalAdoptionReviewV1:
    """Recheck immutable and live evidence before producing a review identity."""

    if not isinstance(reacquired, CodingLegacyReacquiredInstallationV1):
        raise TypeError("Reacquired Coding legacy Installation is required")
    if (
        not isinstance(policy_revision, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", policy_revision) is None
    ):
        raise ValueError("Coding Product policy revision is required")
    epoch_runtime.assert_current()
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    inventory = read_coding_legacy_installation_inventory(lifecycle, epoch_runtime)
    selected = reacquired.installation
    binding = selected.binding
    wheel = reacquired.wheel
    if (
        fence is None
        or switch is None
        or inventory != reacquired.inventory_evidence
        or inventory.first_fence_id != fence.fence_id
        or inventory.snapshot_receipt_id != fence.request.snapshot_receipt_id
        or selected not in inventory.inventory.active_local
        or wheel.plugin_id != binding.plugin_id
        or wheel.original_source_identity != binding.source_identity
        or wheel.source_content_digest != binding.content_digest
        or wheel.manifest_digest != binding.manifest_digest
        or sha256(wheel.wheel_bytes).hexdigest() != wheel.artifact_digest
        or inventory.inventory.lockfile_digest != binding.lockfile_digest
        or inventory.inventory.desired_journal_digest is None
    ):
        raise CodingLegacyInventoryError(
            "Coding legacy review inputs differ from the first-B Installation"
        )
    legacy_state = CodingFirstBLegacyStateObserver(lifecycle, epoch_runtime).observe(
        store_id=fence.store_id,
        legacy_root_identity=fence.request.legacy_root_identity,
    )
    epoch_runtime.assert_current()
    return CodingLegacyLocalAdoptionReviewV1(
        store_id=epoch_runtime.registry.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=inventory.first_fence_id,
        snapshot_receipt_id=inventory.snapshot_receipt_id,
        legacy_root_identity=legacy_state.legacy_root_identity,
        legacy_state_evidence_id=legacy_state.evidence_id,
        legacy_state_digest=legacy_state.state_digest,
        legacy_entry_count=legacy_state.entry_count,
        legacy_byte_count=legacy_state.byte_count,
        plugin_id=binding.plugin_id,
        desired_state=selected.desired_state,
        legacy_source_identity=binding.source_identity,
        legacy_binding_digest=binding.binding_digest,
        legacy_lockfile_digest=binding.lockfile_digest,
        legacy_desired_journal_digest=inventory.inventory.desired_journal_digest,
        source_content_digest=binding.content_digest,
        manifest_digest=binding.manifest_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        wheel_filename=wheel.filename,
        wheel_artifact_digest=wheel.artifact_digest,
        policy_revision=policy_revision,
    )


__all__ = [
    "CodingLegacyLocalAdoptionReviewV1",
    "review_coding_legacy_reacquired_installation",
]
