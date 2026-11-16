"""One legacy compatibility registry, including acknowledged publications.

This is the existing Config agent compatibility authority's Product-side
registry. Its per-request BaseException completion is deliberately distinct
from ordinary settings-listener publication; no interchangeable queue mode is
introduced.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from threading import Condition, RLock
from typing import ClassVar, Generic, TypeVar

from .manager import LegacyPluginCompatibilityProjectionV1

_CompatibilityKeyT = TypeVar("_CompatibilityKeyT", bound=Hashable)
_CompatibilityWriterT = TypeVar("_CompatibilityWriterT")
_COMPATIBILITY_BIND_LOCK = RLock()


@dataclass(slots=True)
class _LegacyCompatibilityPublication:
    projection: LegacyPluginCompatibilityProjectionV1
    done: bool = False
    error: BaseException | None = None


@dataclass(slots=True)
class LegacyPluginCompatibilityRegistry(
    Generic[_CompatibilityKeyT, _CompatibilityWriterT]
):
    settings_manager: object = field(repr=False)
    _product_label: ClassVar[str] = "Product"

    def _make_writer(self, layout: _CompatibilityKeyT) -> _CompatibilityWriterT:
        raise NotImplementedError

    def _writer_layout(self, writer: _CompatibilityWriterT) -> _CompatibilityKeyT:
        raise NotImplementedError

    def _guard_writer(self, writer: _CompatibilityWriterT, plugin_id: str) -> None:
        raise NotImplementedError

    writers: dict[_CompatibilityKeyT, _CompatibilityWriterT] = field(
        default_factory=dict
    )
    projections: dict[_CompatibilityKeyT, LegacyPluginCompatibilityProjectionV1] = (
        field(default_factory=dict)
    )
    _publish: object | None = field(default=None, init=False, repr=False)
    _pending: deque[_LegacyCompatibilityPublication] = field(
        default_factory=deque, init=False, repr=False
    )
    _publishing: bool = field(default=False, init=False, repr=False)
    _condition: Condition = field(default_factory=Condition, init=False, repr=False)

    def bind(self) -> None:
        bind = getattr(
            self.settings_manager, "bind_plugin_enablement_legacy_mutation_guard", None
        )
        if not callable(bind):
            raise TypeError(
                f"{self._product_label} Plugin compatibility requires a fence-aware settings owner"
            )
        publish = bind(self, self._assert_legacy_mutation_allowed)
        if not callable(publish):
            raise TypeError(
                f"{self._product_label} Plugin compatibility publisher is unavailable"
            )
        self._publish = publish

    def writer(self, layout: _CompatibilityKeyT) -> _CompatibilityWriterT:
        with self._condition:
            existing = self.writers.get(layout)
            if existing is not None:
                return existing
            writer = self._make_writer(layout)
            self.writers[layout] = writer
            return writer

    def publish(
        self,
        writer: _CompatibilityWriterT,
        projection: LegacyPluginCompatibilityProjectionV1,
    ) -> None:
        with self._condition:
            if self.writers.get(self._writer_layout(writer)) is not writer:
                raise RuntimeError(
                    f"{self._product_label} Plugin compatibility writer is unbound"
                )
            current = self.projections.get(self._writer_layout(writer))
            if current is not None and (
                projection.desired_inventory_revision
                < current.desired_inventory_revision
                or projection.migration_journal_revision
                < current.migration_journal_revision
            ):
                return
            self.projections[self._writer_layout(writer)] = projection
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
                    (
                        item.desired_inventory_revision
                        for item in self.projections.values()
                    )
                ),
                migration_journal_revision=max(
                    (
                        item.migration_journal_revision
                        for item in self.projections.values()
                    )
                ),
            )
            request = _LegacyCompatibilityPublication(aggregate)
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
            self._guard_writer(writer, plugin_id)


def bind_legacy_plugin_compatibility_registry(
    layout: _CompatibilityKeyT,
    settings_manager: object | None,
    *,
    registry_type: type[
        LegacyPluginCompatibilityRegistry[_CompatibilityKeyT, _CompatibilityWriterT]
    ],
    cache_attribute: str,
    migrated_ids: Callable[[_CompatibilityKeyT], frozenset[str]],
    error_factory: Callable[[str, str], RuntimeError],
    product_label: str,
    error_prefix: str,
) -> _CompatibilityWriterT | None:
    """Bind one exact writer or fail closed for an existing legacy peer."""
    if settings_manager is None:
        return None
    with _COMPATIBILITY_BIND_LOCK:
        cached = getattr(settings_manager, cache_attribute, None)
        registry: LegacyPluginCompatibilityRegistry[
            _CompatibilityKeyT, _CompatibilityWriterT
        ]
        if cached is None:
            registry = registry_type(settings_manager)
        elif isinstance(cached, registry_type):
            registry = cached
            if registry.settings_manager is not settings_manager:
                raise error_factory(
                    f"{product_label} Plugin compatibility settings owner changed",
                    f"{error_prefix}_authority_conflict",
                )
            return registry.writer(layout)
        else:
            raise error_factory(
                f"{product_label} Plugin compatibility authority cache is invalid",
                f"{error_prefix}_authority_conflict",
            )
        bind = getattr(
            settings_manager, "bind_plugin_enablement_legacy_mutation_guard", None
        )
        if not callable(bind):
            migrated = migrated_ids(layout)
            if migrated:
                raise error_factory(
                    "Existing Plugin migration requires a fence-aware settings owner",
                    f"{error_prefix}_fence_unavailable",
                )
            return None
        try:
            setattr(settings_manager, cache_attribute, registry)
        except (AttributeError, TypeError) as exc:
            raise error_factory(
                "Fence-aware settings owner cannot retain its compatibility authority",
                f"{error_prefix}_authority_unavailable",
            ) from exc
        try:
            registry.bind()
        except BaseException:
            try:
                if getattr(settings_manager, cache_attribute, None) is registry:
                    delattr(settings_manager, cache_attribute)
            except (AttributeError, TypeError):
                pass
            raise
        return registry.writer(layout)


__all__ = [
    "LegacyPluginCompatibilityRegistry",
    "bind_legacy_plugin_compatibility_registry",
]
