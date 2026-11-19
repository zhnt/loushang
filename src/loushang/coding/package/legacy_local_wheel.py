"""Reacquire one exact legacy local Plugin tree as a Product Wheel candidate."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyLocalWheelFields,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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

    if os.name != "posix":
        raise RuntimeError("POSIX local Plugin Source reacquisition is required")
    if not isinstance(plugin_id, str) or _SAFE_ID.fullmatch(plugin_id) is None:
        raise ValueError("Legacy Plugin identity is invalid")
    if any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None
        for value in (expected_content_digest, expected_manifest_digest)
    ):
        raise ValueError("Legacy Plugin revision evidence is invalid")
    if (
        not isinstance(expected_dependency_lock, PluginDependencyClosureLock)
        or expected_dependency_lock.package_content_digest != expected_content_digest
        or expected_dependency_lock.python_distributions
    ):
        raise ValueError("Legacy Plugin dependency closure is unsupported")
    from loushang.harness.resources.packages.product_legacy_source_wheel import (
        _reacquire_legacy_local_plugin_wheel,
    )

    return _reacquire_legacy_local_plugin_wheel(
        source_root,
        legacy_package_root=legacy_package_root,
        staging_parent=staging_parent,
        plugin_id=plugin_id,
        expected_source_identity=expected_source_identity,
        expected_content_digest=expected_content_digest,
        expected_manifest_digest=expected_manifest_digest,
        result_factory=lambda values: CodingLegacyLocalWheelCandidateV1(
            plugin_id=values[0],
            original_source_identity=values[1],
            source_content_digest=values[2],
            manifest_digest=values[3],
            requested_package=values[4],
            plugin_manifest_path=values[5],
            filename=values[6],
            artifact_digest=values[7],
            wheel_bytes=values[8],
        ),
    )


__all__ = [
    "CodingLegacyLocalWheelCandidateV1",
    "reacquire_coding_legacy_local_plugin_wheel",
]
