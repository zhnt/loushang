"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import enablement_compatibility as _binding


def reconcile(self: _binding.CodingPluginEnablementCompatibilityWriter) -> None:
    """Publish the latest canonical view under the Product coordination lock."""

    defer = getattr(
        self._registry.settings_manager,
        "defer_plugin_enablement_compatibility_notifications",
        None,
    )
    notifications = defer() if callable(defer) else _binding.nullcontext()
    with notifications:
        try:
            with _binding._capture_existing_plugin_enablement_state(
                self.layout
            ) as capture:
                if capture is None:
                    return
                projection, migrated = (
                    _binding.project_coding_plugin_enablement_compatibility(
                        self.layout,
                        _capture=capture,
                    )
                )
                if not migrated:
                    return
                compatibility = _binding.LegacyPluginCompatibilityProjectionV1(
                    disabled_plugin_ids=projection.disabled_plugin_ids,
                    migrated_plugin_ids=tuple(sorted(migrated)),
                    desired_inventory_revision=projection.desired_inventory_revision,
                    migration_journal_revision=(projection.migration_journal_revision),
                )
            self._registry.publish(self, compatibility)
        except FileNotFoundError:
            raise _binding.CodingPluginEnablementCompatibilityError(
                _binding._LIFECYCLE_PROGRAM_VALUES["value_001"],
                code=_binding._LIFECYCLE_PROGRAM_VALUES["value_002"],
            )


def assert_legacy_mutation_allowed(
    self: _binding.CodingPluginEnablementCompatibilityWriter, plugin_id: str
) -> None:
    key = _binding.PluginInstallationKeyV1(
        product_id=_binding.CODING_PRODUCT_ID,
        installation_scope="workspace",
        scope_id=self.layout.scope_id,
        plugin_id=plugin_id,
    )
    with _binding._capture_existing_plugin_enablement_state(self.layout) as capture:
        if capture is None:
            return
        snapshots = _binding.decode_plugin_enablement_migration_snapshots(
            capture.migration_raw,
            path=self.layout.enablement_migration,
        )
        if any(item.request.installation_key == key for item in snapshots):
            raise _binding.PluginEnablementMigrationError(
                _binding._LIFECYCLE_PROGRAM_VALUES["value_003"],
                code=_binding._LIFECYCLE_PROGRAM_VALUES["value_004"],
                path=self.layout.enablement_migration,
            )
