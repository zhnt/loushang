"""Durable Product acceptance of one frozen old local removal review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
class CodingLegacyRemovedAcceptanceV1:
    review: CodingLegacyRemovedReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    @classmethod
    def create(
        cls, review: CodingLegacyRemovedReviewV1
    ) -> CodingLegacyRemovedAcceptanceV1:
        if not isinstance(review, CodingLegacyRemovedReviewV1):
            raise TypeError("Old local removal review is required")
        acceptance_id = _envelope.identity(review.review_id)
        return cls(review=review, acceptance_id=acceptance_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyRemovedAcceptanceV1:
        return _envelope.decode(
            value, CodingLegacyRemovedReviewV1.from_dict, cls.create
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyRemovedAcceptanceV1.to_dict,
    decoder=CodingLegacyRemovedAcceptanceV1.from_dict,
)

_acceptance_journal = _FirstAcceptanceJournal(
    filename="legacy-removed-acceptance.jsonl",
    codec=_CODEC,
    error_type=CodingLegacyRemovedAcceptanceError,
    directory_label="Old removal Product state directory",
    posix_read_error_type=CodingLegacyDisabledOnlyAcceptanceError,
    posix_read_label="Disabled-only Product",
    untouched_message="Disabled-only adoption requires an untouched Product Desired State",
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

    review = review_coding_first_b_removed_local(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    return _acceptance_journal.accept_review(
        epoch_runtime,
        accepted_review_id=accepted_review_id,
        current_review_id=review.review_id,
        create=lambda: CodingLegacyRemovedAcceptanceV1.create(review),
        expected_store_id=lambda: (
            resolve_coding_package_epoch_layout(lifecycle).store_id
        ),
        changed_review="Old removal review ID changed",
        conflict_message="Old removal acceptance conflicts with prior review",
    )


def read_coding_first_b_removed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyRemovedAcceptanceV1 | None:
    """Reopen acceptance against the current authenticated first-B review."""

    return _acceptance_journal.read_acceptance(
        epoch_runtime,
        expected_store_id=resolve_coding_package_epoch_layout(lifecycle).store_id,
        review=lambda: review_coding_first_b_removed_local(
            lifecycle, epoch_runtime, settings_manager=settings_manager
        ),
        create=CodingLegacyRemovedAcceptanceV1.create,
        conflict_message="Old removal acceptance conflicts with first-B review",
    )


def _write_private_acceptance(
    path: Path, record: CodingLegacyRemovedAcceptanceV1
) -> None:
    _acceptance_journal.publish(path, record)


__all__ = [
    "CodingLegacyRemovedAcceptanceError",
    "CodingLegacyRemovedAcceptanceV1",
    "accept_coding_first_b_removed_local",
    "read_coding_first_b_removed_local_acceptance",
]
