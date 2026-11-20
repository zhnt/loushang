"""Build an inert, snapshot-bound review record for one old local Installation."""

from __future__ import annotations

import json as json
import re
from dataclasses import dataclass, field, fields
from hashlib import sha256

from loushang.coding.harness.package_product import legacy_local_review as _programs
from loushang.coding.harness.package_product import (
    legacy_local_review as _record_programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
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
    CodingScopedLegacyDisableV1,
)
from .legacy_classification import (
    classify_coding_legacy_source_configuration as classify_coding_legacy_source_configuration,
)
from .legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source as match_coding_legacy_local_skill_configured_source,
)
from .legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstalledState,
)
from .legacy_installation_inventory import (
    CodingLegacyInventoryError as CodingLegacyInventoryError,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source as reacquire_coding_legacy_installed_local_source,
)
from .legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver as CodingFirstBLegacyStateObserver,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
_WHEEL_NAME = re.compile(r"loushang_legacy_[0-9a-f]{24}-1-py3-none-any\.whl\Z")


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Coding Product policy revision is required",
    "value_002": "Coding legacy review inputs differ from the first-B Installation",
    "value_003": "coding-source-configuration.json",
    "value_004": "Coding legacy Source configuration is missing from first B",
}


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
        return _record_programs.validate_review(self)

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
        return _record_programs.decode_review(cls, value)


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

    return _programs.review_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )


__all__ = [
    "CodingLegacyLocalAdoptionReviewV1",
    "review_coding_legacy_installed_local_source",
]
