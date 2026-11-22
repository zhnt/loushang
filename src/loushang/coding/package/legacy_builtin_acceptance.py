"""One-way Product acceptance of a frozen builtin-only migration review."""

from __future__ import annotations

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
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout,
)
from .legacy_builtin_review import (
    CodingLegacyBuiltinOnlyReviewV1,
    review_coding_first_b_builtin_only,
)
from .legacy_disabled_acceptance import CodingLegacyDisabledOnlyAcceptanceError
from .legacy_windows_receipt import _receipt_io, write_windows_private_receipt


class CodingLegacyBuiltinOnlyAcceptanceError(RuntimeError):
    """The reviewed builtin-only Product acceptance is inconsistent."""


_envelope = _FirstAcceptanceEnvelope(
    invalid_message="Invalid Coding builtin-only acceptance",
    invalid_code="coding_builtin_acceptance_invalid",
    version_error="Unsupported builtin-only acceptance version",
    identity_error="Builtin-only acceptance identity changed",
)


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinOnlyAcceptanceV1(
    _FirstAcceptanceRecord[CodingLegacyBuiltinOnlyReviewV1]
):
    review: CodingLegacyBuiltinOnlyReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    _envelope = _envelope
    _review_type = CodingLegacyBuiltinOnlyReviewV1
    _review_required = "Coding builtin-only review is required"


_acceptance_journal = _FirstAcceptanceJournal(
    filename="legacy-builtin-acceptance.jsonl",
    codec=CodingLegacyBuiltinOnlyAcceptanceV1._record_codec(),
    error_type=CodingLegacyBuiltinOnlyAcceptanceError,
    directory_label="Builtin-only Product state directory",
    posix_read_error_type=CodingLegacyDisabledOnlyAcceptanceError,
    posix_read_label="Disabled-only Product",
    untouched_message="Disabled-only adoption requires an untouched Product Desired State",
    create=CodingLegacyBuiltinOnlyAcceptanceV1.create,
    changed_review="Builtin-only review ID changed",
    accept_conflict="Builtin-only acceptance conflicts with prior review",
    read_conflict="Builtin-only acceptance conflicts with first-B review",
    check_epoch_before_read=True,
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

    return _acceptance_journal.accept_review(
        epoch_runtime,
        accepted_review_id=accepted_review_id,
        review=lambda: review_coding_first_b_builtin_only(
            lifecycle, epoch_runtime, settings_manager=settings_manager
        ),
        expected_store_id=lambda: resolve_coding_package_epoch_layout(lifecycle).store_id,
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

    return _acceptance_journal.read_acceptance(
        epoch_runtime,
        expected_store_id=resolve_coding_package_epoch_layout(lifecycle).store_id,
        review=lambda: review_coding_first_b_builtin_only(
            lifecycle, epoch_runtime, settings_manager=settings_manager
        ),
    )


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
