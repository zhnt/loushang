"""Read-only proof that an old Instance journal has no live references."""

from __future__ import annotations

from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeInventorySnapshotV1,
    inspect_gracefully_retired_instance_capture,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_desired_evidence import CodingLegacyDesiredEvidenceV1
from .package_legacy_operation_evidence import CodingLegacyRetirementCaptureV1

_MAX_CAPTURE_BYTES = 2 * 1024 * 1024


class CodingLegacyInstanceEvidenceError(ValueError):
    """Frozen old Instance references are not safe for first-B adoption."""


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
