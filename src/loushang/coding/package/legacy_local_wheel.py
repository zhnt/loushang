"""Reacquire one exact legacy local Plugin tree as a Product Wheel candidate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyLocalWheelFields,
    _LegacyWheelValues,
    _reacquire_legacy_local_plugin_wheel,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalWheelCandidateV1(_LegacyLocalWheelFields):
    """Inert bytes; only a later Product policy can authorize publication."""

    plugin_id: str
    original_source_identity: str
    source_content_digest: str
    manifest_digest: str
    requested_package: str
    plugin_manifest_path: str
    filename: str
    artifact_digest: str
    wheel_bytes: bytes


def _new_wheel_candidate(
    values: _LegacyWheelValues,
) -> CodingLegacyLocalWheelCandidateV1:
    return CodingLegacyLocalWheelCandidateV1(*values)


def reacquire_coding_legacy_local_plugin_wheel(
    source_root: Path,
    *,
    legacy_package_root: Path,
    staging_parent: Path,
    plugin_id: str,
    expected_source_identity: str,
    expected_content_digest: str,
    expected_manifest_digest: str,
    expected_dependency_lock: PluginDependencyClosureLock,
) -> CodingLegacyLocalWheelCandidateV1:
    """Capture the original local Source again; never import old Store bytes.

    A matching old binding is corroborating evidence only. This function does
    not authorize the resulting Wheel or commit a Product transaction.
    """

    return _reacquire_legacy_local_plugin_wheel(
        source_root,
        legacy_package_root=legacy_package_root,
        staging_parent=staging_parent,
        plugin_id=plugin_id,
        expected_source_identity=expected_source_identity,
        expected_content_digest=expected_content_digest,
        expected_manifest_digest=expected_manifest_digest,
        expected_dependency_lock=expected_dependency_lock,
        result_factory=_new_wheel_candidate,
    )


__all__ = [
    "CodingLegacyLocalWheelCandidateV1",
    "reacquire_coding_legacy_local_plugin_wheel",
]
