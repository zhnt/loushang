"""First-B review of scoped legacy disables without adoption authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_classification import CodingScopedLegacyDisableV1
from .package_legacy_snapshot_member import (
    CodingLegacyInventoryDomain,
    list_coding_first_b_snapshot_domain_members,
)
from .package_legacy_source_evidence import read_coding_legacy_source_evidence

_OLD_STATE_DOMAINS: tuple[CodingLegacyInventoryDomain, ...] = (
    "binding_history",
    "desired_state",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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
        object.__setattr__(
            self, "review_id", sha256(canonical_json_bytes(self._identity_dict())).hexdigest()
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "firstFenceId": self.first_fence_id,
            "snapshotReceiptId": self.snapshot_receipt_id,
            "sourceProjectionDigest": self.source_projection_digest,
            "reviewVersion": self.review_version,
            "disabledPlugins": [
                {"scope": item.scope, "pluginId": item.plugin_id}
                for item in self.disabled_plugins
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {"reviewId": self.review_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyDisabledOnlyReviewV1:
        if type(value) is not dict or set(value) != {
            "reviewId", "storeId", "namespaceId", "scopeId", "firstFenceId",
            "snapshotReceiptId", "sourceProjectionDigest", "reviewVersion",
            "disabledPlugins",
        }:
            raise ValueError("Coding disabled-only review record is invalid")
        disabled = value["disabledPlugins"]
        if not isinstance(disabled, list) or any(
            type(item) is not dict
            or set(item) != {"scope", "pluginId"}
            or item["scope"] not in ("global", "project")
            or not isinstance(item["pluginId"], str)
            or not item["pluginId"]
            for item in disabled
        ):
            raise ValueError("Coding disabled-only review entries are invalid")
        for name in ("namespaceId", "firstFenceId", "snapshotReceiptId", "sourceProjectionDigest", "reviewId"):
            if not isinstance(value[name], str) or _SHA256.fullmatch(value[name]) is None:
                raise ValueError("Coding disabled-only review digest is invalid")
        for name in ("storeId", "scopeId"):
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError("Coding disabled-only review authority is invalid")
        if type(value["reviewVersion"]) is not int or value["reviewVersion"] != 1:
            raise ValueError("Coding disabled-only review version is invalid")
        if len({(item["scope"], item["pluginId"]) for item in disabled}) != len(disabled):
            raise ValueError("Coding disabled-only review entries are duplicated")
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
            raise ValueError("Coding disabled-only review identity changed")
        return review


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
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    if fence is None or switch is None:
        raise CodingLegacyDisabledOnlyReviewError(
            "Coding first-B fence is unavailable"
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
    for domain in _OLD_STATE_DOMAINS:
        if list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        ):
            raise CodingLegacyDisabledOnlyReviewError(
                "Coding first-B snapshot contains old Plugin state"
            )
    epoch_runtime.assert_current()
    return CodingLegacyDisabledOnlyReviewV1(
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
        source_projection_digest=source.projection_digest,
        disabled_plugins=source.classification.disabled_plugins,
    )


__all__ = [
    "CodingLegacyDisabledOnlyReviewError",
    "CodingLegacyDisabledOnlyReviewV1",
    "review_coding_first_b_disabled_only",
]
