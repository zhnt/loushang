"""Coding Product owner for the fenced legacy enablement downgrade view."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    project_coding_plugin_enablement_compatibility,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.journal import journal_file_lock
from loushang.harness.plugin_management import (
    PluginEnablementMigrationJournal,
    PluginInstallationKeyV1,
)

_COMPATIBILITY_AUTHORITY_VERSION = "coding-plugin-enablement-compatibility-v1"
CompatibilityPublisher = Callable[[Iterable[str], str], None]


@dataclass(slots=True)
class CodingPluginEnablementCompatibilityWriter:
    """Serialize projection publication and fence independent legacy writers."""

    layout: CodingPluginLifecycleStateLayout
    settings_manager: object = field(repr=False)
    _publish: CompatibilityPublisher = field(init=False, repr=False)

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
        authority_id = f"{_COMPATIBILITY_AUTHORITY_VERSION}:{self.layout.scope_id}"
        self._publish = bind(authority_id, self._assert_legacy_mutation_allowed)

    def reconcile(self) -> None:
        """Publish the latest canonical view under the Product coordination lock."""

        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            projection, migrated = project_coding_plugin_enablement_compatibility(
                self.layout
            )
            current = self._current_disabled_plugins()
            retained = {item for item in current if item not in migrated}
            disabled = tuple(sorted(retained | set(projection.disabled_plugin_ids)))
            if disabled != current:
                self._publish(disabled, "project")

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

    def _current_disabled_plugins(self) -> tuple[str, ...]:
        get_settings = getattr(self.settings_manager, "get_settings", None)
        if not callable(get_settings):
            raise TypeError("Coding Plugin compatibility settings read is unavailable")
        values = getattr(get_settings(), "disabled_plugins", ())
        if not isinstance(values, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in values
        ):
            raise TypeError("Coding Plugin compatibility settings are invalid")
        return tuple(values)


def bind_coding_plugin_enablement_compatibility(
    layout: CodingPluginLifecycleStateLayout,
    settings_manager: object | None,
) -> CodingPluginEnablementCompatibilityWriter | None:
    """Bind the writer when the Product settings owner supports the fence."""

    if settings_manager is None:
        return None
    bind = getattr(
        settings_manager,
        "bind_plugin_enablement_legacy_mutation_guard",
        None,
    )
    if not callable(bind):
        return None
    return CodingPluginEnablementCompatibilityWriter(layout, settings_manager)


__all__ = [
    "CodingPluginEnablementCompatibilityWriter",
    "bind_coding_plugin_enablement_compatibility",
]
