"""Coding Product owner for the fenced legacy enablement downgrade view."""

from __future__ import annotations

from contextlib import nullcontext as nullcontext
from dataclasses import dataclass, field

from loushang.coding.composition.plan import CODING_PRODUCT_ID as CODING_PRODUCT_ID
from loushang.coding.harness.plugin_management import (
    enablement_projection as _lifecycle_programs,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    project_coding_plugin_enablement_compatibility,
)
from loushang.coding.plugin_manager.lifecycle import (
    _capture_existing_plugin_enablement_state as _capture_existing_plugin_enablement_state,
)
from loushang.harness.config.agent._legacy_compatibility import (
    LegacyPluginCompatibilityRegistry as _ConfigLegacyPluginCompatibilityRegistry,
)
from loushang.harness.config.agent._legacy_compatibility import (
    bind_legacy_plugin_compatibility_registry,
)
from loushang.harness.config.agent.manager import (
    LegacyPluginCompatibilityProjectionV1 as LegacyPluginCompatibilityProjectionV1,
)
from loushang.harness.plugin_management import (
    PluginEnablementMigrationError as PluginEnablementMigrationError,
)
from loushang.harness.plugin_management import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.plugin_management import (
    decode_plugin_enablement_migration_snapshots as decode_plugin_enablement_migration_snapshots,
)

_COMPATIBILITY_CACHE_ATTRIBUTE = (
    "_loushang_coding_plugin_enablement_compatibility_writer"
)


_LIFECYCLE_PROGRAM_VALUES = {
    "value_001": "Coding Plugin lifecycle coordination evidence disappeared",
    "value_002": "coding_plugin_compatibility_coordination_missing",
    "value_003": "Legacy Plugin enablement is read-only after migration acceptance",
    "value_004": "plugin_enablement_legacy_mutation_rejected",
}


class CodingPluginEnablementCompatibilityError(RuntimeError):
    """Stable failure to establish the minimum fence-aware runtime."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CodingPluginEnablementCompatibilityWriter:
    """Serialize projection publication and fence independent legacy writers."""

    layout: CodingPluginLifecycleStateLayout
    _registry: _CodingPluginEnablementCompatibilityRegistry = field(repr=False)

    def reconcile(self) -> None:
        """Publish the latest canonical view under the Product coordination lock."""

        return _lifecycle_programs.reconcile(self)

    def _assert_legacy_mutation_allowed(self, plugin_id: str) -> None:
        return _lifecycle_programs.assert_legacy_mutation_allowed(self, plugin_id)


class _CodingPluginEnablementCompatibilityRegistry(
    _ConfigLegacyPluginCompatibilityRegistry[
        CodingPluginLifecycleStateLayout, CodingPluginEnablementCompatibilityWriter
    ]
):
    __slots__ = ()
    _product_label = "Coding"

    def _make_writer(
        self, layout: CodingPluginLifecycleStateLayout
    ) -> CodingPluginEnablementCompatibilityWriter:
        return CodingPluginEnablementCompatibilityWriter(layout, self)

    def _writer_layout(
        self, writer: CodingPluginEnablementCompatibilityWriter
    ) -> CodingPluginLifecycleStateLayout:
        return writer.layout

    def _guard_writer(
        self, writer: CodingPluginEnablementCompatibilityWriter, plugin_id: str
    ) -> None:
        writer._assert_legacy_mutation_allowed(plugin_id)


def _migrated_compatibility_plugin_ids(
    layout: CodingPluginLifecycleStateLayout,
) -> frozenset[str]:
    _projection, migrated = project_coding_plugin_enablement_compatibility(layout)
    return migrated


def bind_coding_plugin_enablement_compatibility(
    layout: CodingPluginLifecycleStateLayout, settings_manager: object | None
) -> CodingPluginEnablementCompatibilityWriter | None:
    """Bind one exact writer or fail closed for an existing legacy peer."""
    return bind_legacy_plugin_compatibility_registry(
        layout,
        settings_manager,
        registry_type=_CodingPluginEnablementCompatibilityRegistry,
        cache_attribute=_COMPATIBILITY_CACHE_ATTRIBUTE,
        migrated_ids=_migrated_compatibility_plugin_ids,
        error_factory=lambda message, code: CodingPluginEnablementCompatibilityError(
            message, code=code
        ),
        product_label="Coding",
        error_prefix="coding_plugin_compatibility",
    )


__all__ = [
    "CodingPluginEnablementCompatibilityError",
    "CodingPluginEnablementCompatibilityWriter",
    "bind_coding_plugin_enablement_compatibility",
]
