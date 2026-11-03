"""Read-only proof that an old Instance journal has no live references."""

from __future__ import annotations

from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeError,
    PluginInstanceRuntimeInventorySnapshotV1,
    decode_plugin_instance_runtime_capture,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementError,
    decode_plugin_retirement_intent_capture,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetError,
    decode_plugin_retirement_set_capture,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_desired_evidence import CodingLegacyDesiredEvidenceV1

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
    try:
        intents = decode_plugin_retirement_intent_capture(
            intents_raw.decode("utf-8"), path=lifecycle.retirement_intents
        )
        sets = decode_plugin_retirement_set_capture(
            sets_raw.decode("utf-8"),
            path=lifecycle.retirement_sets,
            intents=intents,
        )
        runtime = decode_plugin_instance_runtime_capture(
            runtime_raw.decode("utf-8"),
            path=lifecycle.instance_runtime,
            desired_snapshot=desired.snapshot,
            desired_transitions=desired.transitions,
            retirement_intents=intents,
            retirement_sets=sets,
        )
    except (
        UnicodeError,
        PluginRetirementError,
        PluginRetirementSetError,
        PluginInstanceRuntimeError,
    ) as exc:
        raise CodingLegacyInstanceEvidenceError(
            "Old Instance capture cannot be verified"
        ) from exc
    if (
        not runtime.instances
        or runtime.open_families
        or any(
            item.state != "RETIRED"
            or item.open_family_ids
            or item.completion is None
            or item.completion.completion_kind != "graceful"
            for item in runtime.instances
        )
    ):
        raise CodingLegacyInstanceEvidenceError(
            "Old Instance capture retains a live or unproven reference"
        )
    return runtime


__all__ = [
    "CodingLegacyInstanceEvidenceError",
    "parse_coding_legacy_retired_instance_capture",
]
