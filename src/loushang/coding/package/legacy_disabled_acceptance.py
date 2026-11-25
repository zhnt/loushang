"""One-way Product acceptance of a reviewed disabled-only first-B snapshot."""

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
from .legacy_disabled_review import (
    CodingLegacyDisabledOnlyReviewV1,
    review_coding_first_b_disabled_only,
)

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})


class CodingLegacyDisabledOnlyAcceptanceError(RuntimeError):
    """The accepted review or its durable Product receipt is inconsistent."""


_envelope = _FirstAcceptanceEnvelope(
    invalid_message="Invalid Coding disabled-only acceptance",
    invalid_code="coding_disabled_acceptance_invalid",
    version_error="Unsupported acceptance version",
    identity_error="Acceptance identity changed",
)


@dataclass(frozen=True, slots=True)
class CodingLegacyDisabledOnlyAcceptanceV1(
    _FirstAcceptanceRecord[CodingLegacyDisabledOnlyReviewV1]
):
    review: CodingLegacyDisabledOnlyReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    _envelope = _envelope
    _review_type = CodingLegacyDisabledOnlyReviewV1
    _review_required = "Coding disabled-only review is required"

    @classmethod
    def _check_review(cls, review: CodingLegacyDisabledOnlyReviewV1) -> None:
        if any(item.plugin_id not in _BUILTINS for item in review.disabled_plugins):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only adoption supports built-in Coding Plugins only"
            )


_acceptance_journal = _FirstAcceptanceJournal(
    review=review_coding_first_b_disabled_only,
    resolve_epoch=resolve_coding_package_epoch_layout,
    filename="legacy-disabled-acceptance.jsonl",
    codec=CodingLegacyDisabledOnlyAcceptanceV1._record_codec(),
    error_type=CodingLegacyDisabledOnlyAcceptanceError,
    directory_label="Disabled-only Product state directory",
    posix_read_error_type=CodingLegacyDisabledOnlyAcceptanceError,
    posix_read_label="Disabled-only Product",
    untouched_message="Disabled-only adoption requires an untouched Product Desired State",
    create=CodingLegacyDisabledOnlyAcceptanceV1.create,
    changed_review="Disabled-only review ID changed",
    accept_conflict="Disabled-only Product acceptance conflicts with prior review",
    read_conflict="Disabled-only Product acceptance conflicts with first-B review",
    empty_is_missing=False,
)


def accept_coding_first_b_disabled_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyDisabledOnlyAcceptanceV1:
    """Persist exactly one operator-selected review before any Desired mutation."""

    return _acceptance_journal.accept_review(
        lifecycle,
        epoch_runtime,
        settings_manager=settings_manager,
        accepted_review_id=accepted_review_id,
    )


def read_coding_first_b_disabled_only_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyDisabledOnlyAcceptanceV1 | None:
    """Read a committed acceptance without creating or repairing Product state."""

    return _acceptance_journal.read_acceptance(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )


__all__ = [
    "CodingLegacyDisabledOnlyAcceptanceError",
    "CodingLegacyDisabledOnlyAcceptanceV1",
    "accept_coding_first_b_disabled_only",
    "read_coding_first_b_disabled_only_acceptance",
]
