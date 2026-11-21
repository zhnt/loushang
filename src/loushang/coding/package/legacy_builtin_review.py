"""Frozen first-B review for old Coding builtin-only Desired State."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from hashlib import sha256
from pathlib import Path as Path

from loushang.coding.harness.package_product import legacy_builtin_review as _programs
from loushang.coding.harness.package_product import (
    legacy_builtin_review as _record_programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
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
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstallationInventoryV1,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_installations as classify_coding_legacy_installations,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_operation_evidence import (
    classify_coding_legacy_management_members as classify_coding_legacy_management_members,
)
from .legacy_operation_evidence import (
    parse_coding_legacy_operation_evidence as parse_coding_legacy_operation_evidence,
)
from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    CodingLegacyInventoryDomain,
)
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_source_evidence import (
    read_coding_legacy_source_evidence as read_coding_legacy_source_evidence,
)
from .pre_b_snapshot import CodingPreBSnapshotPreparation

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
_REMOVABLE = _BUILTINS
_DOMAINS: tuple[CodingLegacyInventoryDomain, ...] = (
    "binding_history",
    "desired_state",
    "source_configuration",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)
_EXPECTED = {
    "binding_history": (),
    "desired_state": ("desired-state.jsonl",),
    "source_configuration": ("coding-source-configuration.json",),
    "enablement_state": (),
    "instance_state": (),
    "lock_history": (),
    "store_bytes": (),
}


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Coding old snapshot is not builtin-only",
    "value_002": "desired-state.jsonl",
    "value_003": "Coding old Desired State is missing",
    "value_004": "Coding builtin-only snapshot cannot be admitted before first fence",
    "value_009": "management-operations.jsonl",
    "value_010": "Coding old management operations are missing",
    "value_011": "coding_legacy_builtin_snapshot_refused",
    "value_012": "Coding old management lock changed",
    "value_013": "Coding first-B fence is missing",
    "value_014": "Coding legacy settings paths are unavailable",
    "value_015": "Coding first-B snapshot is not builtin-only",
    "value_016": "Coding first-B snapshot has configured Sources",
}


class CodingLegacyBuiltinOnlyReviewError(ValueError):
    """The frozen old snapshot cannot become a builtin-only Product review."""


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinOnlyReviewV1:
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

    def __post_init__(self) -> None:
        return _record_programs.validate_review(self)

    def _identity(self) -> dict[str, object]:
        return {
            **_REVIEW_SCHEMA.encode(self),
            "disabledPlugins": [
                {"scope": item.scope, "pluginId": item.plugin_id}
                for item in self.disabled_plugins
            ],
            "builtinIntent": [
                {"pluginId": item.plugin_id, "desiredState": item.desired_state}
                for item in self.builtin_intent
            ],
            "removedBuiltinIds": list(self.removed_builtin_ids),
            "reviewVersion": self.review_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "reviewId": self.review_id}

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyBuiltinOnlyReviewV1:
        return _record_programs.decode_review(cls, value)

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is not reviewed")
        return (
            "coding-legacy-builtin-remove:"
            + sha256(
                f"{self.store_id}\0{self.review_id}\0{plugin_id}".encode()
            ).hexdigest()
        )


_REVIEW_SCHEMA = RecordSchema(
    lambda value: value,
    tuple(
        RecordField(item.name)
        for item in fields(CodingLegacyBuiltinOnlyReviewV1)
        if item.name
        not in {
            "disabled_plugins",
            "builtin_intent",
            "removed_builtin_ids",
            "review_version",
            "review_id",
        }
    ),
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

    return _programs.admit_builtin_snapshot(lifecycle, prepared, snapshot)


def review_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyBuiltinOnlyReviewV1:
    """Review only the authenticated snapshot and exact old builtin intent."""

    return _programs.review_builtin_snapshot(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )


__all__ = [
    "CodingLegacyBuiltinOnlyReviewError",
    "CodingLegacyBuiltinOnlyReviewV1",
    "admit_coding_builtin_only_snapshot",
    "review_coding_first_b_builtin_only",
]
