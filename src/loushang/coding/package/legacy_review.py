"""Build an inert, snapshot-bound review record for one old local Installation."""

from __future__ import annotations

import json as json
import re
from dataclasses import dataclass, field, fields
from hashlib import sha256
from typing import TYPE_CHECKING

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_local_review import (
    LegacyLocalReviewEvidence,
    read_live_legacy_local_review,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
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


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_WHEEL_NAME = re.compile(r"loushang_legacy_[0-9a-f]{24}-1-py3-none-any\.whl\Z")


_LEGACY_RECORD_VALUES = {
    "value_001": "Coding legacy review digest is invalid",
    "value_002": "Coding legacy review count is invalid",
    "value_003": "Coding legacy review authority is invalid",
    "value_004": "Coding legacy review disabled Plugins are invalid",
    "value_005": "Coding legacy review builtin intent is invalid",
    "value_006": "Coding legacy review removed builtin IDs are invalid",
    "value_007": "Coding legacy review configured Source scope is invalid",
    "value_011": "Coding legacy review record is invalid",
    "value_012": "Coding legacy review identity changed",
}


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
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...] = ()
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...] = ()
    removed_builtin_ids: tuple[str, ...] = ()
    configured_plugin_source_scope: str | None = None
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
        digests = (
            self.namespace_id,
            self.first_fence_id,
            self.snapshot_receipt_id,
            self.legacy_root_identity,
            self.legacy_state_evidence_id,
            self.legacy_state_digest,
            self.legacy_binding_digest,
            self.legacy_lockfile_digest,
            self.legacy_desired_journal_digest,
            self.source_content_digest,
            self.manifest_digest,
            self.dependency_lock_digest,
            self.wheel_artifact_digest,
        )
        if any(
            type(value) is not str or _SHA256.fullmatch(value) is None
            for value in digests
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_001"])
        if any(
            type(value) is not int or value < 0
            for value in (self.legacy_entry_count, self.legacy_byte_count)
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_002"])
        if (
            type(self.store_id) is not str
            or _SAFE_ID.fullmatch(self.store_id) is None
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.plugin_id) is not str
            or _SAFE_ID.fullmatch(self.plugin_id) is None
            or self.desired_state not in ("installed_disabled", "installed_enabled")
            or type(self.legacy_source_identity) is not str
            or not self.legacy_source_identity.startswith("local:/")
            or type(self.wheel_filename) is not str
            or _WHEEL_NAME.fullmatch(self.wheel_filename) is None
            or type(self.policy_revision) is not str
            or _SAFE_ID.fullmatch(self.policy_revision) is None
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_003"])
        if any(
            not isinstance(item, CodingScopedLegacyDisableV1)
            or item.scope not in ("global", "project")
            or _SAFE_ID.fullmatch(item.plugin_id) is None
            for item in self.disabled_plugins
        ) or len(
            {(item.scope, item.plugin_id) for item in self.disabled_plugins}
        ) != len(self.disabled_plugins):
            raise ValueError(_LEGACY_RECORD_VALUES["value_004"])
        if any(
            not isinstance(item, CodingLegacyBuiltinIntentV1)
            or item.plugin_id not in _BUILTINS
            or item.desired_state not in ("installed_disabled", "installed_enabled")
            for item in self.builtin_intent
        ) or tuple(item.plugin_id for item in self.builtin_intent) != tuple(
            sorted({item.plugin_id for item in self.builtin_intent})
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_005"])
        if (
            any(
                type(item) is not str or item not in _BUILTINS
                for item in self.removed_builtin_ids
            )
            or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_006"])
        if self.configured_plugin_source_scope not in (None, "global", "project"):
            raise ValueError(_LEGACY_RECORD_VALUES["value_007"])
        object.__setattr__(
            self,
            "review_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, object]:
        identity: dict[str, object] = _REVIEW_SCHEMA.encode(self)
        if self.disabled_plugins:
            identity["disabledPlugins"] = [
                {"scope": item.scope, "pluginId": item.plugin_id}
                for item in self.disabled_plugins
            ]
        if self.builtin_intent:
            identity["builtinIntent"] = [
                {"pluginId": item.plugin_id, "desiredState": item.desired_state}
                for item in self.builtin_intent
            ]
        if self.removed_builtin_ids:
            identity["removedBuiltinIds"] = list(self.removed_builtin_ids)
        if self.configured_plugin_source_scope is not None:
            identity["configuredPluginSourceScope"] = (
                self.configured_plugin_source_scope
            )
        return identity

    def to_dict(self) -> dict[str, object]:
        return {"reviewId": self.review_id, **self._identity_dict()}

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        """Stable Product tombstone command for a reviewed old removal."""

        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is absent from the legacy review")
        return shared_coding_legacy_builtin_removal_operation_id(
            self.first_fence_id, plugin_id
        )

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyLocalAdoptionReviewV1:
        optional_keys = {
            "disabledPlugins",
            "builtinIntent",
            "removedBuiltinIds",
            "configuredPluginSourceScope",
        }
        if (
            type(value) is not dict
            or not _REVIEW_WIRE_KEYS.issubset(value)
            or not set(value).issubset(_REVIEW_WIRE_KEYS | optional_keys)
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_011"])
        document = value
        disabled = document.get("disabledPlugins", [])
        if (
            not isinstance(disabled, list)
            or ("disabledPlugins" in document and not disabled)
            or any(
                type(item) is not dict
                or set(item) != {"scope", "pluginId"}
                or item["scope"] not in ("global", "project")
                or not isinstance(item["pluginId"], str)
                for item in disabled
            )
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_004"])
        builtin_intent = document.get("builtinIntent", [])
        if (
            not isinstance(builtin_intent, list)
            or ("builtinIntent" in document and not builtin_intent)
            or any(
                type(item) is not dict
                or set(item) != {"pluginId", "desiredState"}
                or type(item["pluginId"]) is not str
                or type(item["desiredState"]) is not str
                for item in builtin_intent
            )
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_005"])
        removed_builtin_ids = document.get("removedBuiltinIds", [])
        if (
            not isinstance(removed_builtin_ids, list)
            or ("removedBuiltinIds" in document and not removed_builtin_ids)
            or any(type(item) is not str for item in removed_builtin_ids)
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_006"])
        scalar_keys = _REVIEW_WIRE_KEYS - {"legacyEntryCount", "legacyByteCount"}
        if any(type(document[key]) is not str for key in scalar_keys):
            raise ValueError(_LEGACY_RECORD_VALUES["value_011"])
        review = cls(
            **_REVIEW_SCHEMA.decode(dict, document),
            disabled_plugins=tuple(
                CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                for item in disabled
            ),
            builtin_intent=tuple(
                CodingLegacyBuiltinIntentV1(item["pluginId"], item["desiredState"])
                for item in builtin_intent
            ),
            removed_builtin_ids=tuple(removed_builtin_ids),
            configured_plugin_source_scope=document.get("configuredPluginSourceScope"),
        )
        if document["reviewId"] != review.review_id:
            raise ValueError(_LEGACY_RECORD_VALUES["value_012"])
        return review


_REVIEW_SCHEMA = RecordSchema(
    lambda value: value,
    tuple(
        RecordField(item.name)
        for item in fields(CodingLegacyLocalAdoptionReviewV1)
        if item.name
        not in {
            "disabled_plugins",
            "builtin_intent",
            "removed_builtin_ids",
            "configured_plugin_source_scope",
            "review_id",
        }
    ),
)
_REVIEW_WIRE_KEYS = frozenset(_REVIEW_SCHEMA.keys | {"reviewId"})


def shared_coding_legacy_builtin_removal_operation_id(
    first_fence_id: str, plugin_id: str
) -> str:
    """Use one tombstone across separately reviewed active local Installations."""

    if (
        not isinstance(first_fence_id, str)
        or _SHA256.fullmatch(first_fence_id) is None
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
        or _SAFE_ID.fullmatch(policy_revision) is None
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


__all__ = [
    "CodingLegacyLocalAdoptionReviewV1",
    "review_coding_legacy_installed_local_source",
]
