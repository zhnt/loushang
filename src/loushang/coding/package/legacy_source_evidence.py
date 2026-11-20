"""Read frozen pre-B Coding settings without trusting mutable current settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256 as sha256
from pathlib import Path

from loushang.coding.harness.package_product import legacy_source_evidence as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.json import _unique_json_object_hook

from .legacy_classification import (
    CodingLegacySourceConfigurationV1,
)
from .legacy_classification import (
    classify_coding_legacy_source_configuration as classify_coding_legacy_source_configuration,
)
from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    read_coding_first_b_snapshot_member,
)

_MAX_PROJECTION_BYTES = 8 * 1024 * 1024


_LEGACY_EVIDENCE_VALUES = {
    "value_001": "Coding legacy Source settings projection exceeds budget",
    "value_002": "Coding legacy Source settings scopes overlap",
    "value_003": "Coding legacy Source settings path is invalid",
    "value_004": "Coding Source projection is not an object",
    "value_005": "Coding Source settings path changed",
    "value_006": "Coding Source projection bytes changed",
    "value_007": "Coding legacy Source settings projection is invalid",
}


class CodingLegacySourceEvidenceError(ValueError):
    """The first-B Source settings projection cannot be trusted."""


@dataclass(frozen=True, slots=True)
class CodingLegacySourceEvidenceV1:
    projection_bytes: bytes
    classification: CodingLegacySourceConfigurationV1
    projection_digest: str

    def source_patch(self, scope: str) -> dict[str, object]:
        """Return a detached copy; callers cannot mutate authenticated bytes."""

        if scope not in ("global", "project"):
            raise ValueError("Coding legacy Source scope is invalid")
        projection = json.loads(self.projection_bytes)
        return projection["scopes"][scope]["sourcePatch"]


def read_coding_legacy_source_evidence(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    global_settings_path: Path,
    project_settings_path: Path,
) -> CodingLegacySourceEvidenceV1:
    """Read only the settings projection captured at the current first fence."""

    raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name="coding-source-configuration.json",
        maximum_bytes=_MAX_PROJECTION_BYTES,
    )
    if raw is None:
        raise CodingLegacySourceEvidenceError(
            "Coding legacy Source settings snapshot is missing"
        )
    return parse_coding_legacy_source_evidence(
        raw,
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )


def parse_coding_legacy_source_evidence(
    raw: bytes,
    *,
    global_settings_path: Path,
    project_settings_path: Path,
) -> CodingLegacySourceEvidenceV1:
    """Validate the exact settings paths and source patches frozen at cutover."""

    return _programs.parse_source_evidence(
        raw,
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )


_unique_object = _unique_json_object_hook(
    lambda: "Coding Source projection has duplicate JSON keys",
)


def _reject_non_json_constant(value: str) -> object:
    raise ValueError(f"Coding Source projection has invalid constant: {value}")


__all__ = [
    "CodingLegacySourceEvidenceError",
    "CodingLegacySourceEvidenceV1",
    "parse_coding_legacy_source_evidence",
    "read_coding_legacy_source_evidence",
]
