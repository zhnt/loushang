"""Build an inert, snapshot-bound review record for one old local Installation."""

from __future__ import annotations

import json as json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_inventory import (
    LEGACY_REVIEW_DIGEST,
    LEGACY_REVIEW_ID,
    legacy_review_scalar_schema,
)
from loushang.harness.package_product._legacy_local_review import (
    LegacyLocalReviewEvidence,
    LegacyLocalReviewRecord,
    read_live_legacy_local_review,
)
from loushang.harness.package_product._plugin_bootstrap import ReviewedPluginChoices
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    LEGACY_SOURCE_WHEEL_FILENAME as _WHEEL_NAME,
)

from .legacy_classification import (
    CodingLegacySourceConfigurationV1,
    CodingScopedLegacyDisableV1,
)
from .legacy_classification import (
    classify_coding_legacy_source_configuration as classify_coding_legacy_source_configuration,
)
from .legacy_configured_source import CodingLegacyLocalConfiguredSourceV1
from .legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source as match_coding_legacy_local_skill_configured_source,
)
from .legacy_installation_inventory import (
    _BUILTINS as _BUILTINS,
)
from .legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstalledState,
    _legacy_inventory_query,
)
from .legacy_installation_inventory import (
    CodingLegacyInventoryError as CodingLegacyInventoryError,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_local_wheel import _new_wheel_candidate
from .legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source as reacquire_coding_legacy_installed_local_source,
)
from .legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver as CodingFirstBLegacyStateObserver,
)
from .legacy_snapshot_member import _snapshot_reader
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)
from .source_snapshot import _PROJECTION_NAME

if TYPE_CHECKING:
    from .legacy_builtin_review import CodingLegacyBuiltinOnlyReviewV1
    from .legacy_removed_review import CodingLegacyRemovedReviewV1


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalAdoptionReviewV1(LegacyLocalReviewRecord):
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
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...] = ()
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...] = ()
    removed_builtin_ids: tuple[str, ...] = ()
    configured_plugin_source_scope: str | None = None
    review_id: str = field(init=False)

    _review_label = "Coding legacy review"
    _wheel_name = _WHEEL_NAME
    _builtin_ids = _BUILTINS
    _disable_type = CodingScopedLegacyDisableV1
    _builtin_intent_type = CodingLegacyBuiltinIntentV1

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        """Stable Product tombstone command for a reviewed old removal."""

        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is absent from the legacy review")
        return shared_coding_legacy_builtin_removal_operation_id(
            self.first_fence_id, plugin_id
        )


CodingLegacyLocalAdoptionReviewV1._schema = legacy_review_scalar_schema(
    CodingLegacyLocalAdoptionReviewV1,
    "disabled_plugins",
    "builtin_intent",
    "removed_builtin_ids",
    "configured_plugin_source_scope",
    "review_id",
)


def shared_coding_legacy_builtin_removal_operation_id(
    first_fence_id: str, plugin_id: str
) -> str:
    """Use one tombstone across separately reviewed active local Installations."""

    if (
        not isinstance(first_fence_id, str)
        or LEGACY_REVIEW_DIGEST.fullmatch(first_fence_id) is None
        or plugin_id not in _BUILTINS
    ):
        raise ValueError("Coding legacy builtin removal identity is invalid")
    return (
        "coding-legacy-builtin-remove:"
        + sha256(
            b"loushang.coding-legacy-builtin-removal/v1\0"
            + first_fence_id.encode("ascii")
            + b"\0"
            + plugin_id.encode("ascii")
        ).hexdigest()
    )


def review_coding_legacy_installed_local_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAdoptionReviewV1:
    """Fetch the original Source again before producing a review identity."""

    if (
        not isinstance(policy_revision, str)
        or LEGACY_REVIEW_ID.fullmatch(policy_revision) is None
    ):
        raise ValueError("Coding Product policy revision is required")
    epoch_runtime.assert_current()
    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding legacy Plugin identity is required")
    query = _legacy_inventory_query(lifecycle, epoch_runtime)
    evidence, desired_digest, artifact_digest = read_live_legacy_local_review(
        _snapshot_reader(lifecycle, epoch_runtime),
        query,
        legacy_package_root=lifecycle.package_root,
        plugin_id=plugin_id,
        source_member=_PROJECTION_NAME,
        staging_prefix="loushang-legacy-review-",
        result_factory=_new_wheel_candidate,
        inventory_error=CodingLegacyInventoryError,
        label="Coding",
    )
    source, configured = _review_source_choices(evidence)
    builtin_intent, removed_builtins = _review_builtin_intent(evidence)
    epoch_runtime.assert_current()
    return CodingLegacyLocalAdoptionReviewV1(
        **evidence.identity,
        scope_id=lifecycle.scope_id,
        legacy_desired_journal_digest=desired_digest,
        wheel_artifact_digest=artifact_digest,
        policy_revision=policy_revision,
        disabled_plugins=source.disabled_plugins,
        builtin_intent=builtin_intent,
        removed_builtin_ids=removed_builtins,
        configured_plugin_source_scope=None if configured is None else configured.scope,
    )


def _review_source_choices(
    evidence: LegacyLocalReviewEvidence,
) -> tuple[
    CodingLegacySourceConfigurationV1, CodingLegacyLocalConfiguredSourceV1 | None
]:
    projection = evidence.source_projection
    source = classify_coding_legacy_source_configuration(projection)
    configured = match_coding_legacy_local_skill_configured_source(
        projection,
        source_identity=evidence.identity["legacy_source_identity"],
        installed_source_identities=tuple(
            binding.source_identity
            for binding, _, _ in evidence.inventory.inventory.active_local
        ),
    )
    return source, configured


def _review_builtin_intent(
    evidence: LegacyLocalReviewEvidence,
) -> tuple[tuple[CodingLegacyBuiltinIntentV1, ...], tuple[str, ...]]:
    inventory = evidence.inventory.inventory
    return (
        tuple(CodingLegacyBuiltinIntentV1(*item) for item in inventory.builtin_intent),
        tuple(item for item in inventory.removed_plugin_ids if item in _BUILTINS),
    )


def _reviewed_disabled_ids(
    review: CodingLegacyBuiltinOnlyReviewV1
    | CodingLegacyLocalAdoptionReviewV1
    | CodingLegacyRemovedReviewV1,
) -> set[str]:
    disabled = {item.plugin_id for item in review.disabled_plugins}
    disabled.update(
        item.plugin_id
        for item in review.builtin_intent
        if item.desired_state == "installed_disabled"
    )
    return disabled


def _reviewed_local_builtin_choices(
    review: CodingLegacyLocalAdoptionReviewV1,
) -> ReviewedPluginChoices:
    return ReviewedPluginChoices(
        disabled_ids=_reviewed_disabled_ids(review),
        removed_ids=review.removed_builtin_ids,
        operation_id_for=review.removed_builtin_operation_id,
    )


__all__ = [
    "CodingLegacyLocalAdoptionReviewV1",
    "review_coding_legacy_installed_local_source",
]
