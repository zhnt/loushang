"""Durable Product acceptance of one reviewed old local Installation.

Acceptance records the operator's exact review choice. It does not authorize
Source publication, mutate Desired State, or run a Package transaction.
"""

from __future__ import annotations

import os as os
from dataclasses import dataclass
from hashlib import sha256 as sha256
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.journal import (
    JournalCodecError as JournalCodecError,
)
from loushang.harness.package_product._legacy_local_migration import (
    LegacyLocalAcceptanceRecord,
    _FirstAcceptanceEnvelope,
    _LocalAcceptanceProtocol,
)
from loushang.harness.package_product._legacy_local_review import (
    read_frozen_legacy_local_review,
)
from loushang.harness.package_product._legacy_runtime import matches_epoch_layout
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_installation_inventory import _legacy_inventory_query
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_review import (
    _BUILTINS as _BUILTINS,
)
from .legacy_review import (
    CodingLegacyLocalAdoptionReviewV1,
    _review_builtin_intent,
    _review_source_choices,
)
from .legacy_review import (
    review_coding_legacy_installed_local_source as review_coding_legacy_installed_local_source,
)
from .legacy_snapshot_member import _snapshot_reader
from .source_snapshot import _PROJECTION_NAME

_MAX_ACCEPTANCE_BYTES = 1024 * 1024
_MAX_DESIRED_BYTES = 32 * 1024 * 1024


_PRODUCT_ID = "coding"
_ACCEPTANCE_LABEL = "Coding legacy local"
_ACCEPTANCE_CODEC_ERROR_CODE = "coding_legacy_local_acceptance_invalid"


class CodingLegacyLocalAcceptanceError(RuntimeError):
    """An operator review choice or its Product receipt is inconsistent."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalAcceptanceV1(
    LegacyLocalAcceptanceRecord[CodingLegacyLocalAdoptionReviewV1]
):
    review: CodingLegacyLocalAdoptionReviewV1
    acceptance_id: str
    acceptance_version: int = 1
    resource_kind: Literal["skill", "prompt", "theme"] = "skill"

    _label = _ACCEPTANCE_LABEL
    _review_type = CodingLegacyLocalAdoptionReviewV1
    _review_required = f"{_ACCEPTANCE_LABEL} review is required"
    _envelope = _FirstAcceptanceEnvelope(
        invalid_message=f"Invalid {_ACCEPTANCE_LABEL} acceptance",
        invalid_code=_ACCEPTANCE_CODEC_ERROR_CODE,
        version_error=f"Unsupported {_ACCEPTANCE_LABEL} acceptance version",
        identity_error=f"{_ACCEPTANCE_LABEL} acceptance identity changed",
    )

    @classmethod
    def _check_review(cls, review: CodingLegacyLocalAdoptionReviewV1) -> None:
        if any(item.plugin_id not in _BUILTINS for item in review.disabled_plugins):
            raise ValueError("Legacy local adoption supports built-in disables only")


_CODEC = CodingLegacyLocalAcceptanceV1._record_codec()


def accept_coding_legacy_installed_local_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
    accepted_review_id: str,
    resource_kind: Literal["skill", "prompt", "theme"] = "skill",
) -> CodingLegacyLocalAcceptanceV1:
    """Accept one exact current review while that Installation is untouched in B."""

    review = review_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )
    if accepted_review_id != review.review_id:
        raise _acceptance_error("review ID changed")
    _require_current_epoch(lifecycle, epoch_runtime)
    proposed = CodingLegacyLocalAcceptanceV1.create(review, resource_kind=resource_kind)

    def require_current_review() -> None:
        _require_live_resource_kind(
            lifecycle, epoch_runtime, plugin_id=plugin_id, resource_kind=resource_kind
        )
        if (
            review_coding_legacy_installed_local_source(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                policy_revision=policy_revision,
            )
            != review
        ):
            raise _acceptance_error("review changed before acceptance")

    return _acceptance_protocol(epoch_runtime).accept(
        proposed,
        plugin_id=review.plugin_id,
        installation_key=lambda: PluginInstallationKeyV1.workspace(
            _PRODUCT_ID, review.scope_id, review.plugin_id
        ),
        require_current_review=require_current_review,
    )


def reopen_coding_legacy_installed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    """Reopen a receipt against frozen first-B evidence without live Source."""

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError(f"{_ACCEPTANCE_LABEL} Plugin identity is required")
    _require_current_epoch(lifecycle, epoch_runtime)
    record = _acceptance_protocol(epoch_runtime).reopen(plugin_id)
    if record is None:
        return None
    _require_frozen_review(
        lifecycle,
        epoch_runtime,
        record.review,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    epoch_runtime.assert_current()
    return record


def read_coding_legacy_installed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    """Additionally require that the original live Source still matches."""

    record = reopen_coding_legacy_installed_local_acceptance(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    if record is None:
        return None
    review = review_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )
    if record != CodingLegacyLocalAcceptanceV1.create(
        review, resource_kind=record.resource_kind
    ):
        raise _acceptance_error("acceptance conflicts with current review")
    epoch_runtime.assert_current()
    return record


def _require_current_epoch(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
) -> None:
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if not matches_epoch_layout(epoch_runtime, epoch):
        raise _acceptance_error("Product epoch changed")


def _acceptance_error(reason: str) -> CodingLegacyLocalAcceptanceError:
    return CodingLegacyLocalAcceptanceError(f"{_ACCEPTANCE_LABEL} {reason}")


def _acceptance_protocol(
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
) -> _LocalAcceptanceProtocol[CodingLegacyLocalAcceptanceV1]:
    return _LocalAcceptanceProtocol(
        epoch_runtime,
        _CODEC,
        CodingLegacyLocalAcceptanceError,
        _ACCEPTANCE_LABEL,
        _MAX_ACCEPTANCE_BYTES,
        _MAX_DESIRED_BYTES,
    )


def _require_frozen_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    review: CodingLegacyLocalAdoptionReviewV1,
    *,
    plugin_id: str,
    policy_revision: str,
) -> None:
    query = _legacy_inventory_query(lifecycle, epoch_runtime)
    evidence = read_frozen_legacy_local_review(
        _snapshot_reader(lifecycle, epoch_runtime),
        query,
        plugin_id=plugin_id,
        source_member=_PROJECTION_NAME,
        error_type=CodingLegacyLocalAcceptanceError,
        label=_ACCEPTANCE_LABEL,
    )
    source, configured = _review_source_choices(evidence)
    builtin_intent, removed_builtins = _review_builtin_intent(evidence)
    if (
        any(getattr(review, key) != value for key, value in evidence.identity.items())
        or review.scope_id != lifecycle.scope_id
        or review.legacy_desired_journal_digest
        != evidence.inventory.desired_journal_digest
        or review.policy_revision != policy_revision
        or review.disabled_plugins != source.disabled_plugins
        or review.builtin_intent != builtin_intent
        or review.removed_builtin_ids != removed_builtins
        or review.configured_plugin_source_scope
        != (None if configured is None else configured.scope)
    ):
        raise _acceptance_error("acceptance changed first-B evidence")


def _require_live_resource_kind(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    # Keep the cutover inspector out of the acceptance codec's import path.
    from loushang.coding.package.legacy_reacquisition import (
        reacquire_coding_legacy_installed_local_source,
    )
    from loushang.coding.package.legacy_skill_cutover_admission import (
        inspect_coding_legacy_local_data_wheel,
    )

    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    try:
        inspected = inspect_coding_legacy_local_data_wheel(reacquired.wheel)
    except (OSError, ValueError) as exc:
        raise _acceptance_error("Resource type is unsupported") from exc
    if inspected.resource_kind != resource_kind:
        raise _acceptance_error("Resource type differs from accepted route")


__all__ = [
    "CodingLegacyLocalAcceptanceError",
    "CodingLegacyLocalAcceptanceV1",
    "accept_coding_legacy_installed_local_review",
    "read_coding_legacy_installed_local_acceptance",
    "reopen_coding_legacy_installed_local_acceptance",
]
