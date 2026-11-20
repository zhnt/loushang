"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_removed_acceptance as _binding


def accept_removed_review(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: _binding.SettingsManager,
    accepted_review_id: str,
) -> _binding.CodingLegacyRemovedAcceptanceV1:
    """Commit acceptance before the first Product Desired mutation."""

    review = _binding.review_coding_first_b_removed_local(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if accepted_review_id != review.review_id:
        raise _binding.CodingLegacyRemovedAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_001"]
        )
    proposed = _binding.CodingLegacyRemovedAcceptanceV1.create(review)
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise _binding.CodingLegacyRemovedAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    return _binding._acceptance_journal.accept(
        epoch_runtime,
        proposed,
        conflict_message="Old removal acceptance conflicts with prior review",
    )


def read_removed_acceptance(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: _binding.SettingsManager,
) -> _binding.CodingLegacyRemovedAcceptanceV1 | None:
    """Reopen acceptance against the current authenticated first-B review."""

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise _binding.CodingLegacyRemovedAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    path = (
        epoch_runtime.control_root
        / "product-state"
        / _binding._acceptance_journal.filename
    )
    records = _binding._acceptance_journal.records(path)
    if not records:
        return None
    review = _binding.review_coding_first_b_removed_local(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[
        0
    ] != _binding.CodingLegacyRemovedAcceptanceV1.create(review):
        raise _binding.CodingLegacyRemovedAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_003"]
        )
    epoch_runtime.assert_current()
    return records[0]
