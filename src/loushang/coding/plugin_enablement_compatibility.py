"""Coding Product owner for the fenced legacy enablement downgrade view."""

from __future__ import annotations

from dataclasses import dataclass, field

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    project_coding_plugin_enablement_compatibility,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.config.agent.manager import (
    LegacyPluginCompatibilityProjectionV1,
)
from loushang.harness.journal import journal_file_lock
from loushang.harness.plugin_management import (
    PluginEnablementMigrationJournal,
    PluginInstallationKeyV1,
)

_COMPATIBILITY_CACHE_ATTRIBUTE = (
    "_loushang_coding_plugin_enablement_compatibility_writer"
)


class CodingPluginEnablementCompatibilityError(RuntimeError):
    """Stable failure to establish the minimum fence-aware runtime."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CodingPluginEnablementCompatibilityWriter:
    """Serialize projection publication and fence independent legacy writers."""

    layout: CodingPluginLifecycleStateLayout
    settings_manager: object = field(repr=False)
    _publish: object = field(init=False, repr=False)

    def __post_init__(self) -> None:
        bind = getattr(
            self.settings_manager,
            "bind_plugin_enablement_legacy_mutation_guard",
            None,
        )
        if not callable(bind):
            raise TypeError(
                "Coding Plugin compatibility requires a fence-aware settings owner"
            )
        self._publish = bind(self, self._assert_legacy_mutation_allowed)
        if not callable(self._publish):
            raise TypeError("Coding Plugin compatibility publisher is unavailable")

    def reconcile(self) -> None:
        """Publish the latest canonical view under the Product coordination lock."""

        if not self.layout.root.exists():
            return
        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            projection, migrated = project_coding_plugin_enablement_compatibility(
                self.layout
            )
            if not migrated:
                return
            publish = self._publish
            assert callable(publish)
            publish(
                LegacyPluginCompatibilityProjectionV1(
                    disabled_plugin_ids=projection.disabled_plugin_ids,
                    migrated_plugin_ids=tuple(sorted(migrated)),
                    desired_inventory_revision=projection.desired_inventory_revision,
                    migration_journal_revision=(projection.migration_journal_revision),
                )
            )

    def _assert_legacy_mutation_allowed(self, plugin_id: str) -> None:
        journal = PluginEnablementMigrationJournal(self.layout.enablement_migration)
        journal.assert_legacy_mutation_allowed(
            PluginInstallationKeyV1(
                product_id=CODING_PRODUCT_ID,
                installation_scope="workspace",
                scope_id=self.layout.scope_id,
                plugin_id=plugin_id,
            )
        )


def bind_coding_plugin_enablement_compatibility(
    layout: CodingPluginLifecycleStateLayout,
    settings_manager: object | None,
) -> CodingPluginEnablementCompatibilityWriter | None:
    """Bind one exact writer or fail closed for an existing legacy peer."""

    if settings_manager is None:
        return None
    cached = getattr(settings_manager, _COMPATIBILITY_CACHE_ATTRIBUTE, None)
    if cached is not None:
        if not isinstance(cached, CodingPluginEnablementCompatibilityWriter):
            raise CodingPluginEnablementCompatibilityError(
                "Coding Plugin compatibility authority cache is invalid",
                code="coding_plugin_compatibility_authority_conflict",
            )
        if cached.layout != layout:
            raise CodingPluginEnablementCompatibilityError(
                "Settings owner is already bound to another Plugin workspace",
                code="coding_plugin_compatibility_scope_conflict",
            )
        return cached
    bind = getattr(
        settings_manager,
        "bind_plugin_enablement_legacy_mutation_guard",
        None,
    )
    if not callable(bind):
        _projection, migrated = project_coding_plugin_enablement_compatibility(layout)
        if migrated:
            raise CodingPluginEnablementCompatibilityError(
                "Existing Plugin migration requires a fence-aware settings owner",
                code="coding_plugin_compatibility_fence_unavailable",
            )
        return None
    writer = CodingPluginEnablementCompatibilityWriter(layout, settings_manager)
    try:
        setattr(settings_manager, _COMPATIBILITY_CACHE_ATTRIBUTE, writer)
    except (AttributeError, TypeError) as exc:
        raise CodingPluginEnablementCompatibilityError(
            "Fence-aware settings owner cannot retain its compatibility authority",
            code="coding_plugin_compatibility_authority_unavailable",
        ) from exc
    return writer


__all__ = [
    "CodingPluginEnablementCompatibilityError",
    "CodingPluginEnablementCompatibilityWriter",
    "bind_coding_plugin_enablement_compatibility",
]
