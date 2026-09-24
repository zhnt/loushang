"""Read frozen pre-B Coding settings without trusting mutable current settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_classification import (
    CodingLegacySourceConfigurationV1,
    classify_coding_legacy_source_configuration,
)
from .package_legacy_snapshot_member import read_coding_first_b_snapshot_member

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
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
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

    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_PROJECTION_BYTES:
        raise CodingLegacySourceEvidenceError(
            "Coding legacy Source settings projection exceeds budget"
        )
    for path in (global_settings_path, project_settings_path):
        if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
            raise CodingLegacySourceEvidenceError(
                "Coding legacy Source settings path is invalid"
            )
    if global_settings_path == project_settings_path:
        raise CodingLegacySourceEvidenceError(
            "Coding legacy Source settings scopes overlap"
        )
    try:
        projection = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_json_constant,
        )
        classification = classify_coding_legacy_source_configuration(projection)
        if type(projection) is not dict:
            raise ValueError("Coding Source projection is not an object")
        scopes = projection["scopes"]
        if scopes["global"]["settingsPath"] != str(global_settings_path) or scopes[
            "project"
        ]["settingsPath"] != str(project_settings_path):
            raise ValueError("Coding Source settings path changed")
        canonical = json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if raw != canonical:
            raise ValueError("Coding Source projection bytes changed")
    except (UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise CodingLegacySourceEvidenceError(
            "Coding legacy Source settings projection is invalid"
        ) from exc
    return CodingLegacySourceEvidenceV1(
        projection_bytes=raw,
        classification=classification,
        projection_digest=sha256(raw).hexdigest(),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding Source projection has duplicate JSON keys")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> object:
    raise ValueError(f"Coding Source projection has invalid constant: {value}")


__all__ = [
    "CodingLegacySourceEvidenceError",
    "CodingLegacySourceEvidenceV1",
    "parse_coding_legacy_source_evidence",
    "read_coding_legacy_source_evidence",
]
