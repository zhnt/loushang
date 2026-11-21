"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_source_consumption as _binding
from loushang.harness.package_product._legacy_local_migration import _FrozenSources


def frozen_sources(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    acceptance: _binding.CodingLegacyLocalAcceptanceV1,
    settings: _binding.SettingsManager,
) -> _FrozenSources:
    evidence = _binding.read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=_binding._SourceConsumptionProtocol._settings_paths(
            settings, _binding.CodingLegacySourceConsumptionError
        )[0],
        project_settings_path=_binding._SourceConsumptionProtocol._settings_paths(
            settings, _binding.CodingLegacySourceConsumptionError
        )[1],
    )
    projection = _binding.json.loads(evidence.projection_bytes)
    inventory = _binding.read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    )
    source_identities = tuple(
        item.binding.source_identity for item in inventory.inventory.active_local
    )
    by_plugin = {
        item.binding.plugin_id: _binding.match_coding_legacy_local_skill_configured_source(
            projection,
            source_identity=item.binding.source_identity,
            installed_source_identities=source_identities,
        )
        for item in inventory.inventory.active_local
    }
    if acceptance.review.plugin_id not in by_plugin:
        raise _binding.CodingLegacySourceConsumptionError(
            _binding._LEGACY_PROGRAM_VALUES["value_001"]
        )
    configured = by_plugin[acceptance.review.plugin_id]
    if (
        None if configured is None else configured.scope
    ) != acceptance.review.configured_plugin_source_scope:
        raise _binding.CodingLegacySourceConsumptionError(
            _binding._LEGACY_PROGRAM_VALUES["value_002"]
        )
    ordered_paths: dict[str, tuple[str, ...]] = {}
    raw_digests: dict[str, str] = {}
    for scope in ("global", "project"):
        layer = projection["scopes"][scope]
        paths = tuple(layer["sourcePatch"].get("plugin_sources", ()))
        ordered_paths[scope] = paths
        if paths:
            raw_digest = layer["rawSha256"]
            if not isinstance(raw_digest, str):
                raise _binding.CodingLegacySourceConsumptionError(
                    _binding._LEGACY_PROGRAM_VALUES["value_004"]
                )
            raw_digests[scope] = raw_digest
    matched = {item.path for item in by_plugin.values() if item is not None}
    if matched != set(ordered_paths["global"] + ordered_paths["project"]):
        raise _binding.CodingLegacySourceConsumptionError(
            _binding._LEGACY_PROGRAM_VALUES["value_003"]
        )
    return _FrozenSources(
        projection_digest=evidence.projection_digest,
        by_plugin=by_plugin,
        ordered_paths=ordered_paths,
        raw_digests=raw_digests,
    )
