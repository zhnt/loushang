"""Read frozen pre-B Coding settings without trusting mutable current settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout

from .legacy_classification import (
    CodingLegacySourceConfigurationV1,
    classify_coding_legacy_source_configuration,
)
from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    read_coding_first_b_snapshot_member,
)
from .source_snapshot import _source_projection

_MAX_PROJECTION_BYTES = 8 * 1024 * 1024


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
        member_name=_source_projection.projection_name,
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

    classification, digest = _source_projection.verify_snapshot(
        raw,
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
        classify=classify_coding_legacy_source_configuration,
        maximum_bytes=_MAX_PROJECTION_BYTES,
        error_type=CodingLegacySourceEvidenceError,
    )
    return CodingLegacySourceEvidenceV1(raw, classification, digest)


__all__ = [
    "CodingLegacySourceEvidenceError",
    "CodingLegacySourceEvidenceV1",
    "parse_coding_legacy_source_evidence",
    "read_coding_legacy_source_evidence",
]
