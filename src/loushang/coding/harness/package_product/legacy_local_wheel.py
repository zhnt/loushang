"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_local_wheel as _binding


def reacquire_local_wheel(
    source_root: _binding.Path,
    *,
    legacy_package_root: _binding.Path,
    staging_parent: _binding.Path,
    plugin_id: str,
    expected_source_identity: str,
    expected_content_digest: str,
    expected_manifest_digest: str,
    expected_dependency_lock: _binding.PluginDependencyClosureLock,
) -> _binding.CodingLegacyLocalWheelCandidateV1:
    """Capture the original local Source again; never import old Store bytes.

    A matching old binding is corroborating evidence only. This function does
    not authorize the resulting Wheel or commit a Product transaction.
    """

    if _binding.os.name != "posix":
        raise RuntimeError(_binding._LEGACY_ADOPTION_VALUES["value_001"])
    if not isinstance(plugin_id, str) or _binding._SAFE_ID.fullmatch(plugin_id) is None:
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_002"])
    if any(
        not isinstance(value, str) or _binding._SHA256.fullmatch(value) is None
        for value in (expected_content_digest, expected_manifest_digest)
    ):
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_003"])
    if (
        not isinstance(expected_dependency_lock, _binding.PluginDependencyClosureLock)
        or expected_dependency_lock.package_content_digest != expected_content_digest
        or expected_dependency_lock.python_distributions
    ):
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_004"])
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
        result_factory=lambda values: _binding.CodingLegacyLocalWheelCandidateV1(
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
