"""One-way Product acceptance of a frozen builtin-only migration review."""

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
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_builtin_review import (
    CodingLegacyBuiltinOnlyReviewV1,
    review_coding_first_b_builtin_only,
)
from .package_legacy_disabled_acceptance import (
    CodingLegacyDisabledOnlyAcceptanceError,
)
from .package_legacy_windows_receipt import (
    _receipt_io,
    write_windows_private_receipt,
)


class CodingLegacyBuiltinOnlyAcceptanceError(RuntimeError):
    """The reviewed builtin-only Product acceptance is inconsistent."""


_envelope = _FirstAcceptanceEnvelope(
    invalid_message="Invalid Coding builtin-only acceptance",
    invalid_code="coding_builtin_acceptance_invalid",
    version_error="Unsupported builtin-only acceptance version",
    identity_error="Builtin-only acceptance identity changed",
)


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinOnlyAcceptanceV1:
    review: CodingLegacyBuiltinOnlyReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    @classmethod
    def create(
        cls, review: CodingLegacyBuiltinOnlyReviewV1
    ) -> CodingLegacyBuiltinOnlyAcceptanceV1:
        if not isinstance(review, CodingLegacyBuiltinOnlyReviewV1):
            raise TypeError("Coding builtin-only review is required")
        acceptance_id = _envelope.identity(review.review_id)
        return cls(review=review, acceptance_id=acceptance_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyBuiltinOnlyAcceptanceV1:
        return _envelope.decode(
            value, CodingLegacyBuiltinOnlyReviewV1.from_dict, cls.create
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyBuiltinOnlyAcceptanceV1.to_dict,
    decoder=CodingLegacyBuiltinOnlyAcceptanceV1.from_dict,
)

_acceptance_journal = _FirstAcceptanceJournal(
    filename="legacy-builtin-acceptance.jsonl",
    codec=_CODEC,
    error_type=CodingLegacyBuiltinOnlyAcceptanceError,
    directory_label="Builtin-only Product state directory",
    posix_read_error_type=CodingLegacyDisabledOnlyAcceptanceError,
    posix_read_label="Disabled-only Product",
    untouched_message="Disabled-only adoption requires an untouched Product Desired State",
    windows_receipts=_receipt_io,
    windows_untouched_message="Builtin-only adoption requires untouched Windows Product Desired State",
    check_replay_epoch=True,
)


def accept_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyBuiltinOnlyAcceptanceV1:
    """Accept exactly one review before mutating the Product Desired ledger."""

    review = review_coding_first_b_builtin_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if accepted_review_id != review.review_id:
        raise CodingLegacyBuiltinOnlyAcceptanceError("Builtin-only review ID changed")
    proposed = CodingLegacyBuiltinOnlyAcceptanceV1.create(review)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyBuiltinOnlyAcceptanceError("Product Store changed")
    return _acceptance_journal.accept(
        epoch_runtime,
        proposed,
        conflict_message="Builtin-only acceptance conflicts with prior review",
    )


def read_coding_first_b_builtin_only_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyBuiltinOnlyAcceptanceV1 | None:
    """Reopen the accepted review without creating Product state."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyBuiltinOnlyAcceptanceError("Product Store changed")
    epoch_runtime.assert_current()
    path = (
        epoch_runtime.control_root / "product-state" / "legacy-builtin-acceptance.jsonl"
    )
    records = _acceptance_journal.records(
        path,
        windows=isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner),
    )
    if not records:
        epoch_runtime.assert_current()
        return None
    review = review_coding_first_b_builtin_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[0] != CodingLegacyBuiltinOnlyAcceptanceV1.create(
        review
    ):
        raise CodingLegacyBuiltinOnlyAcceptanceError(
            "Builtin-only acceptance conflicts with first-B review"
        )
    epoch_runtime.assert_current()
    return records[0]


def _write_windows_builtin_acceptance(
    path: Path, record: CodingLegacyBuiltinOnlyAcceptanceV1
) -> None:
    write_windows_private_receipt(path, _acceptance_journal.encode(record))


def _write_private_acceptance(
    path: Path, record: CodingLegacyBuiltinOnlyAcceptanceV1
) -> None:
    _acceptance_journal.publish(path, record)


__all__ = [
    "CodingLegacyBuiltinOnlyAcceptanceError",
    "CodingLegacyBuiltinOnlyAcceptanceV1",
    "accept_coding_first_b_builtin_only",
    "read_coding_first_b_builtin_only_acceptance",
]
