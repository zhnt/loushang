"""Frozen first-B review for old Coding builtin-only Desired State."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path as Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_inventory import (
    LegacyBuiltinReviewRecord,
    classify_legacy_builtin_snapshot,
    legacy_review_scalar_schema,
)
from loushang.harness.package_product._legacy_runtime import (
    guard_legacy_snapshot_admission,
    legacy_review_fence_identity,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverError as PackagePosixEpochCutoverError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)

from .legacy_classification import CodingScopedLegacyDisableV1
from .legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence as parse_coding_legacy_desired_evidence,
)
from .legacy_installation_inventory import (
    _BUILTINS,
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstallationInventoryV1,
    _legacy_inventory_reader,
    _project_inventory_facts,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_installations as classify_coding_legacy_installations,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_operation_evidence import CodingLegacyOperationEvidenceError
from .legacy_operation_evidence import (
    classify_coding_legacy_management_members as classify_coding_legacy_management_members,
)
from .legacy_operation_evidence import (
    parse_coding_legacy_operation_evidence as parse_coding_legacy_operation_evidence,
)
from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    _snapshot_reader,
)
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_source_evidence import (
    read_coding_legacy_source_evidence as read_coding_legacy_source_evidence,
)
from .pre_b_snapshot import CodingPreBSnapshotPreparation
from .source_snapshot import _PROJECTION_NAME

_REMOVABLE = _BUILTINS
_EXPECTED = {
    "binding_history": (),
    "source_configuration": (_PROJECTION_NAME,),
    "enablement_state": (),
    "lock_history": (),
    "store_bytes": (),
}


class CodingLegacyBuiltinOnlyReviewError(ValueError):
    """The frozen old snapshot cannot become a builtin-only Product review."""


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinOnlyReviewV1(LegacyBuiltinReviewRecord):
    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    source_projection_digest: str
    desired_journal_digest: str
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...]
    removed_builtin_ids: tuple[str, ...]
    review_version: int = 1
    review_id: str = field(init=False)

    _disable_type = CodingScopedLegacyDisableV1
    _error_type = CodingLegacyBuiltinOnlyReviewError
    _builtin_ids = _BUILTINS
    _removable_builtin_ids = _REMOVABLE
    _builtin_intent_type = CodingLegacyBuiltinIntentV1

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is not reviewed")
        return (
            "coding-legacy-builtin-remove:"
            + sha256(
                f"{self.store_id}\0{self.review_id}\0{plugin_id}".encode()
            ).hexdigest()
        )


CodingLegacyBuiltinOnlyReviewV1._schema = legacy_review_scalar_schema(
    CodingLegacyBuiltinOnlyReviewV1,
    "disabled_plugins",
    "builtin_intent",
    "removed_builtin_ids",
    "review_version",
    "review_id",
)


def _require_builtin_only_inventory(
    inventory: CodingLegacyInstallationInventoryV1,
) -> None:
    if (
        inventory.active_local
        or inventory.unselected_source_identities
        or inventory.lockfile_digest is not None
        or inventory.desired_journal_digest is None
        or not (inventory.builtin_intent or inventory.removed_plugin_ids)
        or any(item not in _REMOVABLE for item in inventory.removed_plugin_ids)
    ):
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding old Desired State is not builtin-only"
        )


def admit_coding_builtin_only_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    prepared: CodingPreBSnapshotPreparation,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
) -> None:
    """Refuse unsupported old state before the irreversible first fence."""

    with guard_legacy_snapshot_admission(
        "Coding builtin-only snapshot cannot be admitted before first fence",
        code="coding_legacy_builtin_snapshot_refused",
    ):
        classification = prepared.legacy_classification
        if (
            classification.kind != "legacy_state"
            or classification.configured_source_keys
            or any(
                item.plugin_id not in _BUILTINS
                for item in classification.disabled_plugins
            )
        ):
            raise CodingLegacyBuiltinOnlyReviewError(
                "Coding old snapshot is not builtin-only"
            )
        inventory, digest = _legacy_inventory_reader(lifecycle).read_builtin_admission(
            prepared.owner,
            snapshot,
            expected=_EXPECTED,
            review_error=CodingLegacyBuiltinOnlyReviewError,
        )
        _require_builtin_only_inventory(
            _project_inventory_facts(inventory, desired_journal_digest=digest)
        )


def review_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyBuiltinOnlyReviewV1:
    """Review only the authenticated snapshot and exact old builtin intent."""

    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    identity = legacy_review_fence_identity(
        epoch_runtime,
        missing=CodingLegacyBuiltinOnlyReviewError("Coding first-B fence is missing"),
    )
    if not isinstance(global_path, Path) or not isinstance(project_path, Path):
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding legacy settings paths are unavailable"
        )
    classify_legacy_builtin_snapshot(
        _snapshot_reader(lifecycle, epoch_runtime).list_members,
        _EXPECTED,
        shape_error=CodingLegacyBuiltinOnlyReviewError(
            "Coding first-B snapshot is not builtin-only"
        ),
        operation_error=CodingLegacyOperationEvidenceError,
        label="Coding",
    )
    source = read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    if source.classification.configured_source_keys:
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding first-B snapshot has configured Sources"
        )
    inventory = read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    ).inventory
    _require_builtin_only_inventory(inventory)
    epoch_runtime.assert_current()
    return CodingLegacyBuiltinOnlyReviewV1(
        **identity,
        scope_id=lifecycle.scope_id,
        source_projection_digest=source.projection_digest,
        desired_journal_digest=inventory.desired_journal_digest or "",
        disabled_plugins=source.classification.disabled_plugins,
        builtin_intent=inventory.builtin_intent,
        removed_builtin_ids=inventory.removed_plugin_ids,
    )


__all__ = [
    "CodingLegacyBuiltinOnlyReviewError",
    "CodingLegacyBuiltinOnlyReviewV1",
    "admit_coding_builtin_only_snapshot",
    "review_coding_first_b_builtin_only",
]
