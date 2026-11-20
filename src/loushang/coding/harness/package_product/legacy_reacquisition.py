"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_reacquisition as _binding


def reacquire_installed_source(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> _binding.CodingLegacyReacquiredInstallationV1:
    """Fetch the live original Source for one exact installed old revision.

    The old Store snapshot corroborates selection but never supplies bytes for
    the Wheel. An operator approval and Product transaction remain separate.
    """

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_001"])
    inventory = _binding.read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    )
    installation = next(
        (
            item
            for item in inventory.inventory.active_local
            if item.binding.plugin_id == plugin_id
        ),
        None,
    )
    if installation is None:
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    binding = installation.binding
    if not binding.source_identity.startswith("local:/"):
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_ADOPTION_VALUES["value_003"]
        )
    # Review can run under a read-only Product epoch. The verified revision is
    # built in a disposable private directory; it never becomes Product Source
    # authorization until a separate admission owner accepts it.
    with _binding.TemporaryDirectory(prefix="loushang-legacy-review-") as staging:
        wheel = _binding.reacquire_coding_legacy_local_plugin_wheel(
            _binding.Path(binding.source_identity.removeprefix("local:")),
            legacy_package_root=lifecycle.package_root,
            staging_parent=_binding.Path(staging),
            plugin_id=binding.plugin_id,
            expected_source_identity=binding.source_identity,
            expected_content_digest=binding.content_digest,
            expected_manifest_digest=binding.manifest_digest,
            expected_dependency_lock=binding.dependency_lock,
        )
    if (
        _binding.read_coding_legacy_installation_inventory(lifecycle, epoch_runtime)
        != inventory
    ):
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_ADOPTION_VALUES["value_004"]
        )
    epoch_runtime.assert_current()
    return _binding.CodingLegacyReacquiredInstallationV1(inventory, installation, wheel)
