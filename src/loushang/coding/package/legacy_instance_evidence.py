"""Read-only proof that an old Instance journal has no live references."""

from __future__ import annotations

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_management_evidence import (
    LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
    LegacyManagementCapturePaths,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeInventorySnapshotV1,
    inspect_gracefully_retired_instance_capture,
)

from .legacy_desired_evidence import CodingLegacyDesiredEvidenceV1
from .legacy_operation_evidence import (
    CodingLegacyRetirementCaptureV1,
)

_MAX_CAPTURE_BYTES = LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES


class CodingLegacyInstanceEvidenceError(ValueError):
    """Frozen old Instance references are not safe for first-B adoption."""


def _management_capture_paths(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> LegacyManagementCapturePaths:
    return LegacyManagementCapturePaths(
        lifecycle.management_operations,
        lifecycle.retirement_intents,
        lifecycle.retirement_sets,
        lifecycle.instance_runtime,
    )


def parse_coding_legacy_retired_instance_capture(
    runtime_raw: bytes,
    *,
    intents_raw: bytes,
    sets_raw: bytes,
    desired: CodingLegacyDesiredEvidenceV1,
    lifecycle: CodingPluginLifecycleStateLayout,
) -> PluginInstanceRuntimeInventorySnapshotV1:
    """Prove every frozen old Instance retired gracefully with no open lease."""

    if (
        any(
            not isinstance(raw, bytes) or len(raw) > _MAX_CAPTURE_BYTES
            for raw in (runtime_raw, intents_raw, sets_raw)
        )
        or not isinstance(desired, CodingLegacyDesiredEvidenceV1)
        or not isinstance(lifecycle, CodingPluginLifecycleStateLayout)
    ):
        raise CodingLegacyInstanceEvidenceError("Old Instance capture is invalid")
    return inspect_gracefully_retired_instance_capture(
        runtime_raw,
        runtime_path=lifecycle.instance_runtime,
        desired_snapshot=desired.snapshot,
        desired_transitions=desired.transitions,
        retirements=CodingLegacyRetirementCaptureV1(
            intents_raw,
            sets_raw,
            lifecycle.retirement_intents,
            lifecycle.retirement_sets,
        ),
        error_type=CodingLegacyInstanceEvidenceError,
        label="Old Instance",
    )


__all__ = [
    "CodingLegacyInstanceEvidenceError",
    "parse_coding_legacy_retired_instance_capture",
]
