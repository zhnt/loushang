"""Durable Product acceptance of one frozen old local removal review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_disabled_acceptance import (
    CodingLegacyDisabledOnlyAcceptanceError,
)
from .package_legacy_removed_review import (
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
    if accepted_review_id != review.review_id:
        raise CodingLegacyRemovedAcceptanceError("Old removal review ID changed")
    proposed = CodingLegacyRemovedAcceptanceV1.create(review)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyRemovedAcceptanceError("Product Store changed")
    return _acceptance_journal.accept(
        epoch_runtime,
        proposed,
        conflict_message="Old removal acceptance conflicts with prior review",
    )


def read_coding_first_b_removed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyRemovedAcceptanceV1 | None:
    """Reopen acceptance against the current authenticated first-B review."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyRemovedAcceptanceError("Product Store changed")
    path = epoch_runtime.control_root / "product-state" / _acceptance_journal.filename
    records = _acceptance_journal.records(path)
    if not records:
        return None
    review = review_coding_first_b_removed_local(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[0] != CodingLegacyRemovedAcceptanceV1.create(
        review
    ):
        raise CodingLegacyRemovedAcceptanceError(
            "Old removal acceptance conflicts with first-B review"
        )
    epoch_runtime.assert_current()
    return records[0]


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
