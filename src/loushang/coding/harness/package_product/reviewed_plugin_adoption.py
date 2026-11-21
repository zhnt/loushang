"""Project and replay already-admitted plugin choices."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from loushang.harness.package_product._plugin_bootstrap import (
    preserve_removed_product_plugin,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

if TYPE_CHECKING:
    from loushang.coding.package.legacy_builtin_review import (
        CodingLegacyBuiltinOnlyReviewV1,
    )
    from loushang.coding.package.legacy_removed_review import (
        CodingLegacyRemovedReviewV1,
    )
    from loushang.coding.package.legacy_review import CodingLegacyLocalAdoptionReviewV1
    from loushang.harness.package_product._plugin_bootstrap import _ProductOwner


def reviewed_disabled_ids(
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


def replay_reviewed_removals(
    product: _ProductOwner,
    plugin_ids: Iterable[str],
    *,
    product_id: str,
    operation_id_for: Callable[[str], str],
    error_prefix: str,
) -> None:
    """Replay each reviewed removal in the caller's order."""
    for plugin_id in plugin_ids:
        key = PluginInstallationKeyV1(
            product_id=product_id,
            installation_scope="workspace",
            scope_id=product.policy.project_scope_id,
            plugin_id=plugin_id,
        )
        preserve_removed_product_plugin(
            product, key, operation_id_for(plugin_id), error_prefix=error_prefix
        )
