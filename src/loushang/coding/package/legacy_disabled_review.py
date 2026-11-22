"""First-B review of scoped legacy disables without adoption authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path as Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_inventory import (
    LEGACY_REVIEW_DIGEST,
    legacy_disabled_plugins_wire,
    legacy_record_digest,
    legacy_review_scalar_schema,
    read_legacy_disabled_plugins,
)
from loushang.harness.package_product._legacy_runtime import (
    LEGACY_PRODUCT_STATE_DOMAINS,
    legacy_review_fence_identity,
    require_legacy_snapshot_members,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_classification import CodingScopedLegacyDisableV1
from .legacy_snapshot_member import (
    _snapshot_reader,
)
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_source_evidence import (
    read_coding_legacy_source_evidence as read_coding_legacy_source_evidence,
)

_LEGACY_RECORD_VALUES = {
    "value_001": "Coding disabled-only review record is invalid",
    "value_002": "Coding disabled-only review entries are invalid",
    "value_003": "Coding disabled-only review version is invalid",
    "value_004": "Coding disabled-only review entries are duplicated",
    "value_005": "Coding disabled-only review identity changed",
    "value_006": "Coding disabled-only review digest is invalid",
    "value_007": "Coding disabled-only review authority is invalid",
}


class CodingLegacyDisabledOnlyReviewError(ValueError):
    """The first-B snapshot cannot be treated as disabled-only input."""


@dataclass(frozen=True, slots=True)
class CodingLegacyDisabledOnlyReviewV1:
    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    source_projection_digest: str
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    review_version: Literal[1] = 1
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.disabled_plugins:
            raise ValueError("Disabled-only review requires scoped disabled Plugins")
        if self.review_version != 1:
            raise ValueError("Unsupported disabled-only review version")
        object.__setattr__(self, "review_id", legacy_record_digest(self._identity_dict()))

    def _identity_dict(self) -> dict[str, object]:
        return {
            **_REVIEW_SCHEMA.encode(self),
            "disabledPlugins": legacy_disabled_plugins_wire(self.disabled_plugins),
        }

    def to_dict(self) -> dict[str, object]:
        return {"reviewId": self.review_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyDisabledOnlyReviewV1:
        if type(value) is not dict or set(value) != _REVIEW_SCHEMA.keys | {
            "reviewId",
            "disabledPlugins",
        }:
            raise ValueError(_LEGACY_RECORD_VALUES["value_001"])
        disabled = read_legacy_disabled_plugins(
            value["disabledPlugins"],
            plugin_id_is_text=lambda item: isinstance(item, str) and bool(item),
            error=ValueError(_LEGACY_RECORD_VALUES["value_002"]),
        )
        for name in (
            "namespaceId",
            "firstFenceId",
            "snapshotReceiptId",
            "sourceProjectionDigest",
            "reviewId",
        ):
            if (
                not isinstance(value[name], str)
                or LEGACY_REVIEW_DIGEST.fullmatch(value[name]) is None
            ):
                raise ValueError(_LEGACY_RECORD_VALUES["value_006"])
        for name in ("storeId", "scopeId"):
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError(_LEGACY_RECORD_VALUES["value_007"])
        if type(value["reviewVersion"]) is not int or value["reviewVersion"] != 1:
            raise ValueError(_LEGACY_RECORD_VALUES["value_003"])
        if len({(item["scope"], item["pluginId"]) for item in disabled}) != len(
            disabled
        ):
            raise ValueError(_LEGACY_RECORD_VALUES["value_004"])
        review = cls(
            store_id=value["storeId"],
            namespace_id=value["namespaceId"],
            scope_id=value["scopeId"],
            first_fence_id=value["firstFenceId"],
            snapshot_receipt_id=value["snapshotReceiptId"],
            source_projection_digest=value["sourceProjectionDigest"],
            disabled_plugins=tuple(
                CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                for item in disabled
            ),
        )
        if review.review_id != value["reviewId"]:
            raise ValueError(_LEGACY_RECORD_VALUES["value_005"])
        return review


_REVIEW_SCHEMA = legacy_review_scalar_schema(
    CodingLegacyDisabledOnlyReviewV1, "disabled_plugins", "review_id"
)


def review_coding_first_b_disabled_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyDisabledOnlyReviewV1:
    """Review only the immutable first-fence snapshot, never live settings."""

    if not isinstance(settings_manager, SettingsManager):
        raise TypeError("Coding legacy settings owner is required")
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if not isinstance(global_path, Path) or not isinstance(project_path, Path):
        raise CodingLegacyDisabledOnlyReviewError(
            "Coding legacy settings paths are unavailable"
        )
    identity = legacy_review_fence_identity(
        epoch_runtime,
        missing=CodingLegacyDisabledOnlyReviewError("Coding first-B fence is unavailable"),
    )
    source = read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    if (
        not source.classification.disabled_plugins
        or source.classification.configured_source_keys
    ):
        raise CodingLegacyDisabledOnlyReviewError(
            "Coding first-B snapshot is not disabled-only"
        )
    require_legacy_snapshot_members(
        _snapshot_reader(lifecycle, epoch_runtime).list_members,
        dict.fromkeys(LEGACY_PRODUCT_STATE_DOMAINS, ()),
        error=CodingLegacyDisabledOnlyReviewError(
            "Coding first-B snapshot contains old Plugin state"
        ),
    )
    epoch_runtime.assert_current()
    return CodingLegacyDisabledOnlyReviewV1(
        **identity,
        scope_id=lifecycle.scope_id,
        source_projection_digest=source.projection_digest,
        disabled_plugins=source.classification.disabled_plugins,
    )


__all__ = [
    "CodingLegacyDisabledOnlyReviewError",
    "CodingLegacyDisabledOnlyReviewV1",
    "review_coding_first_b_disabled_only",
]
