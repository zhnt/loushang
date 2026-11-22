"""Read-only proof that an old Instance journal has no live references."""

from __future__ import annotations

from collections.abc import Callable

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_management_evidence import (
    LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
    LegacyManagementCapturePaths,
    read_settled_management_history,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeInventorySnapshotV1,
    inspect_gracefully_retired_instance_capture,
)

from .legacy_desired_evidence import CodingLegacyDesiredEvidenceV1
from .legacy_operation_evidence import (
    CodingLegacyOperationEvidenceError,
    CodingLegacyRetirementCaptureV1,
)

_MAX_CAPTURE_BYTES = LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES


class CodingLegacyInstanceEvidenceError(ValueError):
    """Frozen old Instance references are not safe for first-B adoption."""


def _read_management_history(
    lifecycle: CodingPluginLifecycleStateLayout,
    instance_members: tuple[str, ...],
    desired: CodingLegacyDesiredEvidenceV1,
    read_member: Callable[..., bytes | None],
    *,
    error_type: type[ValueError],
    missing_messages: tuple[str, str, str],
    operation_maximum_bytes: int | None = LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
    retain_operation_digest: bool = False,
) -> str | None:
    return read_settled_management_history(
        read_member,
        paths=LegacyManagementCapturePaths(
            lifecycle.management_operations,
            lifecycle.retirement_intents,
            lifecycle.retirement_sets,
            lifecycle.instance_runtime,
        ),
        instance_members=instance_members,
        desired_snapshot=desired.snapshot,
        desired_transitions=desired.transitions,
        error_type=error_type,
        missing_messages=missing_messages,
        operation_error=CodingLegacyOperationEvidenceError,
        operation_label="Coding old",
        instance_error=CodingLegacyInstanceEvidenceError,
        operation_maximum_bytes=operation_maximum_bytes,
        retain_operation_digest=retain_operation_digest,
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
