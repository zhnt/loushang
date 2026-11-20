"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_disabled_acceptance as _binding


def accept_disabled_review(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: _binding.SettingsManager,
    accepted_review_id: str,
) -> _binding.CodingLegacyDisabledOnlyAcceptanceV1:
    """Persist exactly one operator-selected review before any Desired mutation."""

    review = _binding.review_coding_first_b_disabled_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if accepted_review_id != review.review_id:
        raise _binding.CodingLegacyDisabledOnlyAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_001"]
        )
    proposed = _binding.CodingLegacyDisabledOnlyAcceptanceV1.create(review)
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise _binding.CodingLegacyDisabledOnlyAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    return _binding._acceptance_journal.accept(
        epoch_runtime,
        proposed,
        conflict_message="Disabled-only Product acceptance conflicts with prior review",
    )


def read_disabled_acceptance(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: _binding.SettingsManager,
) -> _binding.CodingLegacyDisabledOnlyAcceptanceV1 | None:
    """Read a committed acceptance without creating or repairing Product state."""

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise _binding.CodingLegacyDisabledOnlyAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    path = (
        epoch_runtime.control_root
        / "product-state"
        / _binding._LEGACY_ADOPTION_VALUES["value_003"]
    )
    records = _binding._acceptance_journal.records(path)
    if records is None:
        return None
    review = _binding.review_coding_first_b_disabled_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[
        0
    ] != _binding.CodingLegacyDisabledOnlyAcceptanceV1.create(review):
        raise _binding.CodingLegacyDisabledOnlyAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_004"]
        )
    epoch_runtime.assert_current()
    return records[0]
