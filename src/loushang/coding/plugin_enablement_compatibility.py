"""Coding Product owner for the fenced legacy enablement downgrade view."""

from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass, field
from threading import Condition, RLock

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    _capture_existing_plugin_enablement_state,
    project_coding_plugin_enablement_compatibility,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.config.agent.manager import (
    LegacyPluginCompatibilityProjectionV1,
)
from loushang.harness.plugin_management import (
    PluginEnablementMigrationError,
    PluginInstallationKeyV1,
    decode_plugin_enablement_migration_snapshots,
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
    _registry: _CodingPluginEnablementCompatibilityRegistry = field(repr=False)

    def reconcile(self) -> None:
        """Publish the latest canonical view under the Product coordination lock."""

        defer = getattr(
            self._registry.settings_manager,
            "defer_plugin_enablement_compatibility_notifications",
            None,
        )
        notifications = defer() if callable(defer) else nullcontext()
        with notifications:
            try:
                with _capture_existing_plugin_enablement_state(self.layout) as capture:
                    if capture is None:
                        return
                    projection, migrated = (
                        project_coding_plugin_enablement_compatibility(
                            self.layout,
                            _capture=capture,
                        )
                    )
                    if not migrated:
                        return
                    compatibility = LegacyPluginCompatibilityProjectionV1(
                        disabled_plugin_ids=projection.disabled_plugin_ids,
                        migrated_plugin_ids=tuple(sorted(migrated)),
                        desired_inventory_revision=projection.desired_inventory_revision,
                        migration_journal_revision=(
                            projection.migration_journal_revision
                        ),
                    )
                self._registry.publish(self, compatibility)
            except FileNotFoundError:
                raise CodingPluginEnablementCompatibilityError(
                    "Coding Plugin lifecycle coordination evidence disappeared",
                    code="coding_plugin_compatibility_coordination_missing",
                )

    def _assert_legacy_mutation_allowed(self, plugin_id: str) -> None:
        key = PluginInstallationKeyV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=plugin_id,
        )
        with _capture_existing_plugin_enablement_state(self.layout) as capture:
            if capture is None:
                return
            snapshots = decode_plugin_enablement_migration_snapshots(
                capture.migration_raw,
                path=self.layout.enablement_migration,
            )
            if any(item.request.installation_key == key for item in snapshots):
                raise PluginEnablementMigrationError(
                    "Legacy Plugin enablement is read-only after migration acceptance",
                    code="plugin_enablement_legacy_mutation_rejected",
                    path=self.layout.enablement_migration,
                )


@dataclass(slots=True)
class _CompatibilityPublication:
    projection: LegacyPluginCompatibilityProjectionV1
    done: bool = False
    error: BaseException | None = None


@dataclass(slots=True)
class _CodingPluginEnablementCompatibilityRegistry:
    settings_manager: object = field(repr=False)
    writers: dict[
        CodingPluginLifecycleStateLayout,
        CodingPluginEnablementCompatibilityWriter,
    ] = field(default_factory=dict)
    projections: dict[
        CodingPluginLifecycleStateLayout,
        LegacyPluginCompatibilityProjectionV1,
    ] = field(default_factory=dict)
    _publish: object | None = field(default=None, init=False, repr=False)
    _pending: deque[_CompatibilityPublication] = field(
        default_factory=deque,
        init=False,
        repr=False,
    )
    _publishing: bool = field(default=False, init=False, repr=False)
    _condition: Condition = field(default_factory=Condition, init=False, repr=False)

    def bind(self) -> None:
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

    def writer(
        self,
        layout: CodingPluginLifecycleStateLayout,
    ) -> CodingPluginEnablementCompatibilityWriter:
        with self._condition:
            existing = self.writers.get(layout)
            if existing is not None:
                return existing
            writer = CodingPluginEnablementCompatibilityWriter(layout, self)
            self.writers[layout] = writer
            return writer

    def publish(
        self,
        writer: CodingPluginEnablementCompatibilityWriter,
        projection: LegacyPluginCompatibilityProjectionV1,
    ) -> None:
        with self._condition:
            if self.writers.get(writer.layout) is not writer:
                raise RuntimeError("Coding Plugin compatibility writer is unbound")
            current = self.projections.get(writer.layout)
            if current is not None and (
                projection.desired_inventory_revision
                < current.desired_inventory_revision
                or projection.migration_journal_revision
                < current.migration_journal_revision
            ):
                return
            self.projections[writer.layout] = projection
            aggregate = LegacyPluginCompatibilityProjectionV1(
                disabled_plugin_ids=tuple(
                    sorted(
                        {
                            plugin_id
                            for item in self.projections.values()
                            for plugin_id in item.disabled_plugin_ids
                        }
                    )
                ),
                migrated_plugin_ids=tuple(
                    sorted(
                        {
                            plugin_id
                            for item in self.projections.values()
                            for plugin_id in item.migrated_plugin_ids
                        }
                    )
                ),
                desired_inventory_revision=max(
                    item.desired_inventory_revision
                    for item in self.projections.values()
                ),
                migration_journal_revision=max(
                    item.migration_journal_revision
                    for item in self.projections.values()
                ),
            )
            request = _CompatibilityPublication(aggregate)
            self._pending.append(request)
            drain = not self._publishing
            if drain:
                self._publishing = True
        if drain:
            self._drain_publications()
        else:
            with self._condition:
                while not request.done:
                    self._condition.wait()
        if request.error is not None:
            raise request.error

    def _drain_publications(self) -> None:
        while True:
            with self._condition:
                if not self._pending:
                    self._publishing = False
                    self._condition.notify_all()
                    return
                request = self._pending[0]
                publish = self._publish
                assert callable(publish)
            try:
                publish(request.projection)
            except BaseException as exc:
                request.error = exc
            finally:
                with self._condition:
                    popped = self._pending.popleft()
                    assert popped is request
                    request.done = True
                    self._condition.notify_all()

    def _assert_legacy_mutation_allowed(self, plugin_id: str) -> None:
        with self._condition:
            writers = tuple(self.writers.values())
        for writer in writers:
            writer._assert_legacy_mutation_allowed(plugin_id)


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
            registry = _CodingPluginEnablementCompatibilityRegistry(settings_manager)
        elif isinstance(cached, _CodingPluginEnablementCompatibilityRegistry):
            registry = cached
            if registry.settings_manager is not settings_manager:
                raise CodingPluginEnablementCompatibilityError(
                    "Coding Plugin compatibility settings owner changed",
                    code="coding_plugin_compatibility_authority_conflict",
                )
            return registry.writer(layout)
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
        try:
            setattr(settings_manager, _COMPATIBILITY_CACHE_ATTRIBUTE, registry)
        except (AttributeError, TypeError) as exc:
            raise CodingPluginEnablementCompatibilityError(
                "Fence-aware settings owner cannot retain its compatibility authority",
                code="coding_plugin_compatibility_authority_unavailable",
            ) from exc
        try:
            registry.bind()
        except BaseException:
            try:
                if (
                    getattr(
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
        return registry.writer(layout)


__all__ = [
    "CodingPluginEnablementCompatibilityError",
    "CodingPluginEnablementCompatibilityWriter",
    "bind_coding_plugin_enablement_compatibility",
]
