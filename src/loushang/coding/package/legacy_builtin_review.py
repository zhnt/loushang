"""Frozen first-B review for old Coding builtin-only Desired State."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path as Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_inventory import (
    LegacyReviewWireSelections,
    classify_legacy_builtin_snapshot,
    legacy_record_digest,
    legacy_review_scalar_schema,
    legacy_review_selection_wire,
    read_legacy_builtin_admission,
    valid_legacy_builtin_intent,
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
from .legacy_desired_evidence import CodingLegacyDesiredError
from .legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence as parse_coding_legacy_desired_evidence,
)
from .legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstallationInventoryV1,
    CodingLegacyInventoryError,
    _project_inventory_facts,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_installations as classify_coding_legacy_installations,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_instance_evidence import _management_capture_paths
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

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
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
        if (
            type(self.store_id) is not str
            or not self.store_id
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.review_version) is not int
            or self.review_version != 1
            or type(self.disabled_plugins) is not tuple
            or type(self.builtin_intent) is not tuple
            or type(self.removed_builtin_ids) is not tuple
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in (
                    self.namespace_id,
                    self.first_fence_id,
                    self.snapshot_receipt_id,
                    self.source_projection_digest,
                    self.desired_journal_digest,
                )
            )
            or any(
                not isinstance(item, CodingScopedLegacyDisableV1)
                or item.scope not in ("global", "project")
                or item.plugin_id not in _BUILTINS
                for item in self.disabled_plugins
            )
            or len({(item.scope, item.plugin_id) for item in self.disabled_plugins})
            != len(self.disabled_plugins)
            or not valid_legacy_builtin_intent(
                self.builtin_intent, _BUILTINS, intent_type=CodingLegacyBuiltinIntentV1
            )
            or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
            or any(item not in _REMOVABLE for item in self.removed_builtin_ids)
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
            or not (self.builtin_intent or self.removed_builtin_ids)
        ):
            raise CodingLegacyBuiltinOnlyReviewError("Builtin-only review is invalid")
        object.__setattr__(self, "review_id", legacy_record_digest(self._identity()))

    def _identity(self) -> dict[str, object]:
        return {
            **_REVIEW_SCHEMA.encode(self),
            **legacy_review_selection_wire(
                self.disabled_plugins,
                self.builtin_intent,
                self.removed_builtin_ids,
                include_empty=True,
            ),
            "reviewVersion": self.review_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "reviewId": self.review_id}

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyBuiltinOnlyReviewV1:
        expected = _REVIEW_SCHEMA.keys | {
            "reviewId",
            "reviewVersion",
            "removedBuiltinIds",
            "builtinIntent",
            "disabledPlugins",
        }
        if type(value) is not dict or set(value) != expected:
            raise CodingLegacyBuiltinOnlyReviewError(
                "Builtin-only review record is invalid"
            )
        error = CodingLegacyBuiltinOnlyReviewError("Builtin-only review entries are invalid")
        selections = LegacyReviewWireSelections.read(
            value, required=True, disabled_error=error, intent_error=error, removed_error=error,
        )
        create: Callable[..., CodingLegacyBuiltinOnlyReviewV1] = cls
        try:
            review = create(
                **_REVIEW_SCHEMA.decode(dict, value),
                **selections.decode(CodingScopedLegacyDisableV1, CodingLegacyBuiltinIntentV1),
                review_version=value["reviewVersion"],
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise CodingLegacyBuiltinOnlyReviewError(
                "Builtin-only review record is invalid"
            ) from exc
        if review.review_id != value["reviewId"]:
            raise CodingLegacyBuiltinOnlyReviewError(
                "Builtin-only review identity changed"
            )
        return review

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is not reviewed")
        return (
            "coding-legacy-builtin-remove:"
            + sha256(
                f"{self.store_id}\0{self.review_id}\0{plugin_id}".encode()
            ).hexdigest()
        )


_REVIEW_SCHEMA = legacy_review_scalar_schema(
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

    try:
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
        inventory, digest = read_legacy_builtin_admission(
            prepared.owner,
            snapshot,
            expected=_EXPECTED,
            desired_path=lifecycle.desired_state,
            management_paths=_management_capture_paths(lifecycle),
            product_id="coding",
            scope_id=lifecycle.scope_id,
            builtin_ids=_BUILTINS,
            review_error=CodingLegacyBuiltinOnlyReviewError,
            inventory_error=CodingLegacyInventoryError,
            desired_error=CodingLegacyDesiredError,
            operation_error=CodingLegacyOperationEvidenceError,
            label="Coding",
        )
        _require_builtin_only_inventory(
            _project_inventory_facts(inventory, desired_journal_digest=digest)
        )
    except PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PackagePosixEpochCutoverError(
            "Coding builtin-only snapshot cannot be admitted before first fence",
            code="coding_legacy_builtin_snapshot_refused",
        ) from exc


def review_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyBuiltinOnlyReviewV1:
    """Review only the authenticated snapshot and exact old builtin intent."""

    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if fence is None or switch is None:
        raise CodingLegacyBuiltinOnlyReviewError("Coding first-B fence is missing")
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
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
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
