"""Coding Product owner for the fenced legacy enablement downgrade view."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from threading import RLock

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    _validate_existing_private_state_layout,
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
_COMPATIBILITY_BIND_LOCK = RLock()


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
    _bind_on_init: bool = field(default=True, repr=False)
    _publish: object | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self._bind_on_init:
            self.bind()

    def bind(self) -> None:
        """Claim the settings owner after the caller has published the cache."""

        if self._publish is not None:
            return
        bind = getattr(
            self.settings_manager,
            "bind_plugin_enablement_legacy_mutation_guard",
            None,
        )
        if not callable(bind):
            raise TypeError(
                "Coding Plugin compatibility requires a fence-aware settings owner"
            )
        publish = bind(self, self._assert_legacy_mutation_allowed)
        if not callable(publish):
            raise TypeError("Coding Plugin compatibility publisher is unavailable")
        self._publish = publish

    def reconcile(self) -> None:
        """Publish the latest canonical view under the Product coordination lock."""

        defer = getattr(
            self.settings_manager,
            "defer_plugin_enablement_compatibility_notifications",
            None,
        )
        notifications = defer() if callable(defer) else nullcontext()
        with notifications:
            if not _validate_existing_private_state_layout(self.layout):
                return
            try:
                with journal_file_lock(
                    self.layout.coordination_lock,
                    "exclusive",
                    create=False,
                ):
                    if not _validate_existing_private_state_layout(self.layout):
                        return
                    projection, migrated = (
                        project_coding_plugin_enablement_compatibility(self.layout)
                    )
                    if not migrated:
                        return
                    publish = self._publish
                    assert callable(publish)
                    publish(
                        LegacyPluginCompatibilityProjectionV1(
                            disabled_plugin_ids=projection.disabled_plugin_ids,
                            migrated_plugin_ids=tuple(sorted(migrated)),
                            desired_inventory_revision=(
                                projection.desired_inventory_revision
                            ),
                            migration_journal_revision=(
                                projection.migration_journal_revision
                            ),
                        )
                    )
            except FileNotFoundError:
                if not _validate_existing_private_state_layout(self.layout):
                    return
                raise CodingPluginEnablementCompatibilityError(
                    "Coding Plugin lifecycle coordination evidence disappeared",
                    code="coding_plugin_compatibility_coordination_missing",
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


@dataclass(slots=True)
class _CodingPluginEnablementCompatibilityRegistry:
    writers: dict[
        CodingPluginLifecycleStateLayout,
        CodingPluginEnablementCompatibilityWriter,
    ] = field(default_factory=dict)


def bind_coding_plugin_enablement_compatibility(
    layout: CodingPluginLifecycleStateLayout,
    settings_manager: object | None,
) -> CodingPluginEnablementCompatibilityWriter | None:
    """Bind one exact writer or fail closed for an existing legacy peer."""

    if settings_manager is None:
        return None
    with _COMPATIBILITY_BIND_LOCK:
        cached = getattr(settings_manager, _COMPATIBILITY_CACHE_ATTRIBUTE, None)
        registry: _CodingPluginEnablementCompatibilityRegistry
        if cached is None:
            registry = _CodingPluginEnablementCompatibilityRegistry()
        elif isinstance(cached, _CodingPluginEnablementCompatibilityRegistry):
            registry = cached
            existing = registry.writers.get(layout)
            if existing is not None:
                return existing
        else:
            raise CodingPluginEnablementCompatibilityError(
                "Coding Plugin compatibility authority cache is invalid",
                code="coding_plugin_compatibility_authority_conflict",
            )
        bind = getattr(
            settings_manager,
            "bind_plugin_enablement_legacy_mutation_guard",
            None,
        )
        if not callable(bind):
            _projection, migrated = project_coding_plugin_enablement_compatibility(
                layout
            )
            if migrated:
                raise CodingPluginEnablementCompatibilityError(
                    "Existing Plugin migration requires a fence-aware settings owner",
                    code="coding_plugin_compatibility_fence_unavailable",
                )
            return None
        writer = CodingPluginEnablementCompatibilityWriter(
            layout,
            settings_manager,
            _bind_on_init=False,
        )
        try:
            if cached is None:
                setattr(settings_manager, _COMPATIBILITY_CACHE_ATTRIBUTE, registry)
            registry.writers[layout] = writer
        except (AttributeError, TypeError) as exc:
            raise CodingPluginEnablementCompatibilityError(
                "Fence-aware settings owner cannot retain its compatibility authority",
                code="coding_plugin_compatibility_authority_unavailable",
            ) from exc
        try:
            writer.bind()
        except BaseException:
            try:
                registry.writers.pop(layout, None)
                if (
                    not registry.writers
                    and cached is None
                    and getattr(
                        settings_manager,
                        _COMPATIBILITY_CACHE_ATTRIBUTE,
                        None,
                    )
                    is registry
                ):
                    delattr(settings_manager, _COMPATIBILITY_CACHE_ATTRIBUTE)
            except (AttributeError, TypeError):
                pass
            raise
        return writer


__all__ = [
    "CodingPluginEnablementCompatibilityError",
    "CodingPluginEnablementCompatibilityWriter",
    "bind_coding_plugin_enablement_compatibility",
]
