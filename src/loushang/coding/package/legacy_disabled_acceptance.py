"""One-way Product acceptance of a reviewed disabled-only first-B snapshot."""

from __future__ import annotations

import os as os
from dataclasses import dataclass
from pathlib import Path

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
    filename="legacy-disabled-acceptance.jsonl",
    codec=CodingLegacyDisabledOnlyAcceptanceV1._record_codec(),
    error_type=CodingLegacyDisabledOnlyAcceptanceError,
    directory_label="Disabled-only Product state directory",
    posix_read_error_type=CodingLegacyDisabledOnlyAcceptanceError,
    posix_read_label="Disabled-only Product",
    untouched_message="Disabled-only adoption requires an untouched Product Desired State",
)


def accept_coding_first_b_disabled_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyDisabledOnlyAcceptanceV1:
    """Persist exactly one operator-selected review before any Desired mutation."""

    review = review_coding_first_b_disabled_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    return _acceptance_journal.accept_review(
        epoch_runtime,
        accepted_review_id=accepted_review_id,
        review=review,
        create=CodingLegacyDisabledOnlyAcceptanceV1.create,
        expected_store_id=lambda: (
            resolve_coding_package_epoch_layout(lifecycle).store_id
        ),
        changed_review="Disabled-only review ID changed",
        conflict_message="Disabled-only Product acceptance conflicts with prior review",
    )


def read_coding_first_b_disabled_only_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyDisabledOnlyAcceptanceV1 | None:
    """Read a committed acceptance without creating or repairing Product state."""

    return _acceptance_journal.read_acceptance(
        epoch_runtime,
        expected_store_id=resolve_coding_package_epoch_layout(lifecycle).store_id,
        review=lambda: review_coding_first_b_disabled_only(
            lifecycle, epoch_runtime, settings_manager=settings_manager
        ),
        create=CodingLegacyDisabledOnlyAcceptanceV1.create,
        conflict_message="Disabled-only Product acceptance conflicts with first-B review",
        empty_is_missing=False,
    )


def _read_private_acceptance(path: Path) -> str | None:
    return _acceptance_journal.read_private(path)


def _write_private_acceptance(
    path: Path, record: CodingLegacyDisabledOnlyAcceptanceV1
) -> None:
    _acceptance_journal.publish(path, record)


__all__ = [
    "CodingLegacyDisabledOnlyAcceptanceError",
    "CodingLegacyDisabledOnlyAcceptanceV1",
    "accept_coding_first_b_disabled_only",
    "read_coding_first_b_disabled_only_acceptance",
]
