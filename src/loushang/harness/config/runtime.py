from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Generic, Literal, TypeVar

from loushang.harness.config.engine import LayeredConfig
from loushang.harness.config.types import (
    ConfigIssue,
    ConfigLayer,
    ConfigSnapshot,
)

T = TypeVar("T")
ConfigOperation = Literal["reload", "update", "replace"]
ConfigChangeListener = Callable[["ConfigChange[T]"], None]
ConfigValueListener = Callable[[T], None]
ConfigPatchTransform = Callable[[dict[str, object]], Mapping[str, object]]


@dataclass(frozen=True)
class ConfigChange(Generic[T]):
    revision: int
    operation: ConfigOperation
    layer: str | None
    previous: T
    current: T


class ConfigScope(Generic[T]):
    def __init__(self, runtime: ScopedConfigRuntime[T], layer: ConfigLayer) -> None:
        self._runtime = runtime
        self._layer = layer

    @property
    def name(self) -> str:
        return self._layer.name

    @property
    def path(self) -> Path | None:
        return self._layer.path

    @property
    def base_dir(self) -> Path | None:
        return self.path.parent if self.path is not None else None

    @property
    def persistent(self) -> bool:
        return self._layer.persistent

    @property
    def patch(self) -> dict[str, object]:
        return self._runtime.scope_patch(self.name)

    def update(
        self,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        return self._runtime.update(self.name, patch, persist=persist)

    def replace(
        self,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        return self._runtime.replace(self.name, patch, persist=persist)

    def transform(
        self,
        transform: ConfigPatchTransform,
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        """Atomically transform this layer's current patch under one lock."""

        return self._runtime.transform(self.name, transform, persist=persist)


class ScopedConfigRuntime(Generic[T]):
    """Expose typed config scopes and revisioned changes over LayeredConfig."""

    def __init__(self, config: LayeredConfig[T]) -> None:
        self._config = config
        self._layers = {layer.name: layer for layer in config.layers}
        self._revision = 0
        self._change_listeners: list[ConfigChangeListener[T]] = []
        self._value_listeners: list[ConfigValueListener[T]] = []
        self._pending_changes: deque[ConfigChange[T]] = deque()
        self._publishing = False
        self._lock = RLock()

    @property
    def value(self) -> T:
        with self._lock:
            return self._config.value

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def snapshot(self) -> ConfigSnapshot[T]:
        with self._lock:
            return self._config.snapshot()

    def scope(self, layer: str) -> ConfigScope[T]:
        try:
            resolved = self._layers[layer]
        except KeyError as exc:
            raise KeyError(f"Unknown config layer: {layer}") from exc
        return ConfigScope(self, resolved)

    def scope_patch(self, layer: str) -> dict[str, object]:
        with self._lock:
            self.scope(layer)
            return self._config.patch(layer)

    def reload(self) -> ConfigChange[T]:
        with self._lock:
            previous = self._config.value
            self._config.reload()
            change, should_publish = self._enqueue_change(
                operation="reload",
                layer=None,
                previous=previous,
            )
        if should_publish:
            self._drain_publications()
        return change

    def update(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        with self._lock:
            self.scope(layer)
            previous = self._config.value
            self._config.update(layer, patch, persist=persist)
            change, should_publish = self._enqueue_change(
                operation="update",
                layer=layer,
                previous=previous,
            )
        if should_publish:
            self._drain_publications()
        return change

    def replace(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        with self._lock:
            self.scope(layer)
            previous = self._config.value
            self._config.replace(layer, patch, persist=persist)
            change, should_publish = self._enqueue_change(
                operation="replace",
                layer=layer,
                previous=previous,
            )
        if should_publish:
            self._drain_publications()
        return change

    def transform(
        self,
        layer: str,
        transform: ConfigPatchTransform,
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        """Read, transform, replace, and enqueue one layer atomically."""

        if not callable(transform):
            raise TypeError("Config patch transform must be callable")
        with self._lock:
            self.scope(layer)
            previous = self._config.value
            replacement = transform(self._config.patch(layer))
            if not isinstance(replacement, Mapping):
                raise TypeError("Config patch transform must return a mapping")
            self._config.replace(layer, replacement, persist=persist)
            change, should_publish = self._enqueue_change(
                operation="replace",
                layer=layer,
                previous=previous,
            )
        if should_publish:
            self._drain_publications()
        return change

    def apply_overrides(
        self,
        layer: str,
        overrides: Mapping[str, object] | T,
    ) -> ConfigChange[T]:
        patch = (
            dict(overrides)
            if isinstance(overrides, Mapping)
            else self._config.encode(overrides)
        )
        return self.update(layer, patch, persist=False)

    def subscribe_change(
        self,
        listener: ConfigChangeListener[T],
    ) -> Callable[[], None]:
        with self._lock:
            self._change_listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._change_listeners.remove(listener)
                except ValueError:
                    return

        return unsubscribe

    def subscribe(self, listener: ConfigValueListener[T]) -> Callable[[], None]:
        with self._lock:
            self._value_listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._value_listeners.remove(listener)
                except ValueError:
                    return

        return unsubscribe

    def drain_issues(self) -> tuple[ConfigIssue, ...]:
        with self._lock:
            return self._config.drain_issues()

    def _enqueue_change(
        self,
        *,
        operation: ConfigOperation,
        layer: str | None,
        previous: T,
    ) -> tuple[ConfigChange[T], bool]:
        self._revision += 1
        change = ConfigChange(
            revision=self._revision,
            operation=operation,
            layer=layer,
            previous=previous,
            current=self._config.value,
        )
        self._pending_changes.append(change)
        if self._publishing:
            return change, False
        self._publishing = True
        return change, True

    def _drain_publications(self) -> None:
        first_error: Exception | None = None
        try:
            while True:
                with self._lock:
                    if not self._pending_changes:
                        self._publishing = False
                        break
                    current = self._pending_changes.popleft()
                    change_listeners = tuple(self._change_listeners)
                    value_listeners = tuple(self._value_listeners)
                for change_listener in change_listeners:
                    try:
                        change_listener(current)
                    except Exception as exc:
                        if first_error is None:
                            first_error = exc
                for value_listener in value_listeners:
                    try:
                        value_listener(current.current)
                    except Exception as exc:
                        if first_error is None:
                            first_error = exc
        except BaseException:
            with self._lock:
                self._pending_changes.clear()
                self._publishing = False
            raise
        if first_error is not None:
            raise first_error


__all__ = [
    "ConfigChange",
    "ConfigOperation",
    "ConfigPatchTransform",
    "ConfigScope",
    "ScopedConfigRuntime",
]
