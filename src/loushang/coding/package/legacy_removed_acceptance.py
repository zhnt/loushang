"""Durable Product acceptance of one frozen old local removal review."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    _FirstAcceptanceEnvelope,
    _FirstAcceptanceJournal,
    _FirstAcceptanceRecord,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout,
)
from .legacy_disabled_acceptance import CodingLegacyDisabledOnlyAcceptanceError
from .legacy_removed_review import (
    CodingLegacyRemovedReviewV1,
    review_coding_first_b_removed_local,
)


class CodingLegacyRemovedAcceptanceError(RuntimeError):
    """The accepted old removal does not match the frozen Product input."""


_envelope = _FirstAcceptanceEnvelope(
    invalid_message="Invalid Coding old removal acceptance",
    invalid_code="coding_removed_acceptance_invalid",
    version_error="Unsupported old removal acceptance version",
    identity_error="Old removal acceptance identity changed",
)


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedAcceptanceV1(
    _FirstAcceptanceRecord[CodingLegacyRemovedReviewV1]
):
    review: CodingLegacyRemovedReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    _envelope = _envelope
    _review_type = CodingLegacyRemovedReviewV1
    _review_required = "Old local removal review is required"


_acceptance_journal = _FirstAcceptanceJournal(
    review=review_coding_first_b_removed_local,
    resolve_epoch=resolve_coding_package_epoch_layout,
    filename="legacy-removed-acceptance.jsonl",
    codec=CodingLegacyRemovedAcceptanceV1._record_codec(),
    error_type=CodingLegacyRemovedAcceptanceError,
    directory_label="Old removal Product state directory",
    posix_read_error_type=CodingLegacyDisabledOnlyAcceptanceError,
    posix_read_label="Disabled-only Product",
    untouched_message="Disabled-only adoption requires an untouched Product Desired State",
    create=CodingLegacyRemovedAcceptanceV1.create,
    changed_review="Old removal review ID changed",
    accept_conflict="Old removal acceptance conflicts with prior review",
    read_conflict="Old removal acceptance conflicts with first-B review",
    postcheck="combined",
)


def accept_coding_first_b_removed_local(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyRemovedAcceptanceV1:
    """Commit acceptance before the first Product Desired mutation."""

    return _acceptance_journal.accept_review(
        lifecycle,
        epoch_runtime,
        settings_manager=settings_manager,
        accepted_review_id=accepted_review_id,
    )


def read_coding_first_b_removed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyRemovedAcceptanceV1 | None:
    """Reopen acceptance against the current authenticated first-B review."""

    return _acceptance_journal.read_acceptance(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )


__all__ = [
    "CodingLegacyRemovedAcceptanceError",
    "CodingLegacyRemovedAcceptanceV1",
    "accept_coding_first_b_removed_local",
    "read_coding_first_b_removed_local_acceptance",
]
