"""First-B review of scoped legacy disables without adoption authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path as Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_inventory import (
    LegacyDisabledReviewRecord,
    legacy_review_scalar_schema,
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


class CodingLegacyDisabledOnlyReviewError(ValueError):
    """The first-B snapshot cannot be treated as disabled-only input."""


@dataclass(frozen=True, slots=True)
class CodingLegacyDisabledOnlyReviewV1(LegacyDisabledReviewRecord):
    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    source_projection_digest: str
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    review_version: Literal[1] = 1
    review_id: str = field(init=False)

    _disable_type = CodingScopedLegacyDisableV1
    _review_label = "Coding disabled-only review"


CodingLegacyDisabledOnlyReviewV1._schema = legacy_review_scalar_schema(
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
