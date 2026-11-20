"""First-B review of scoped legacy disables without adoption authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path as Path
from typing import Literal

from loushang.coding.harness.package_product import legacy_disabled_review as _programs
from loushang.coding.harness.package_product import (
    legacy_disabled_review as _record_programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_classification import CodingScopedLegacyDisableV1
from .legacy_snapshot_member import (
    CodingLegacyInventoryDomain,
)
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_source_evidence import (
    read_coding_legacy_source_evidence as read_coding_legacy_source_evidence,
)

_OLD_STATE_DOMAINS: tuple[CodingLegacyInventoryDomain, ...] = (
    "binding_history",
    "desired_state",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Coding legacy settings owner is required",
    "value_002": "Coding legacy settings paths are unavailable",
    "value_003": "Coding first-B fence is unavailable",
    "value_004": "Coding first-B snapshot is not disabled-only",
    "value_005": "Coding first-B snapshot contains old Plugin state",
}


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
        object.__setattr__(
            self,
            "review_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
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
        return _record_programs.decode_review(cls, value)


def review_coding_first_b_disabled_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyDisabledOnlyReviewV1:
    """Review only the immutable first-fence snapshot, never live settings."""

    return _programs.review_disabled_snapshot(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )


__all__ = [
    "CodingLegacyDisabledOnlyReviewError",
    "CodingLegacyDisabledOnlyReviewV1",
    "review_coding_first_b_disabled_only",
]
