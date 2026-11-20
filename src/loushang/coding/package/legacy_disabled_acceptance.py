"""One-way Product acceptance of a reviewed disabled-only first-B snapshot."""

from __future__ import annotations

import os as os
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.harness.package_product import (
    first_snapshot_acceptance,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.package_product._legacy_local_migration import (
    _FirstAcceptanceEnvelope,
    _FirstAcceptanceJournal,
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
class CodingLegacyDisabledOnlyAcceptanceV1:
    review: CodingLegacyDisabledOnlyReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    @classmethod
    def create(
        cls, review: CodingLegacyDisabledOnlyReviewV1
    ) -> CodingLegacyDisabledOnlyAcceptanceV1:
        if not isinstance(review, CodingLegacyDisabledOnlyReviewV1):
            raise TypeError("Coding disabled-only review is required")
        if any(item.plugin_id not in _BUILTINS for item in review.disabled_plugins):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only adoption supports built-in Coding Plugins only"
            )
        acceptance_id = _envelope.identity(review.review_id)
        return cls(review=review, acceptance_id=acceptance_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyDisabledOnlyAcceptanceV1:
        return _envelope.decode(
            value, CodingLegacyDisabledOnlyReviewV1.from_dict, cls.create
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyDisabledOnlyAcceptanceV1.to_dict,
    decoder=CodingLegacyDisabledOnlyAcceptanceV1.from_dict,
)

_acceptance_journal = _FirstAcceptanceJournal(
    filename="legacy-disabled-acceptance.jsonl",
    codec=_CODEC,
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
    return first_snapshot_acceptance.accept_review(
        epoch_runtime,
        _acceptance_journal,
        accepted_review_id=accepted_review_id,
        current_review_id=review.review_id,
        create=lambda: CodingLegacyDisabledOnlyAcceptanceV1.create(review),
        expected_store_id=lambda: resolve_coding_package_epoch_layout(lifecycle).store_id,
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

    return first_snapshot_acceptance.read_acceptance(
        epoch_runtime,
        _acceptance_journal,
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
