from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Generic, Literal, TypeVar, cast

from loushang.harness.config._file_transaction import (
    config_file_transaction_lock,
    normalized_config_path,
)
from loushang.harness.config.engine import LayeredConfig
from loushang.harness.config.types import (
    ConfigIssue,
    ConfigLayer,
    ConfigSnapshot,
)

T = TypeVar("T")
_NO_TRANSACTION = object()
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

    def matches(
        self,
        expected: Mapping[str, object],
        *,
        keys: Iterable[str],
    ) -> bool:
        """Atomically compare selected keys with an expected layer patch."""

        return self._runtime.scope_matches(self.name, expected, keys=keys)


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
        self._publication_holds = 0
        self._patch_transforming = False
        self._transaction_depth = 0
        self._transaction_previous: T | object = _NO_TRANSACTION
        self._transaction_changed = False
        self._transaction_operation: ConfigOperation = "reload"
        self._transaction_layers: set[str | None] = set()
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
            self._require_non_reentrant_write()
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

    def transaction(self) -> AbstractContextManager[None]:
        """Refresh and mutate persistent layers as one externally visible change.

        All configured persistent paths are locked in stable order.  The final
        notification is emitted only after the runtime and file locks are gone.
        """

        return self._transaction()

    def update(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        if self._requires_persistent_transaction(layer, persist=persist):
            with self.transaction():
                return self.update(layer, patch, persist=persist)
        with self._lock:
            self._require_non_reentrant_write()
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
        if self._requires_persistent_transaction(layer, persist=persist):
            with self.transaction():
                return self.replace(layer, patch, persist=persist)
        with self._lock:
            self._require_non_reentrant_write()
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
        if self._requires_persistent_transaction(layer, persist=persist):
            with self.transaction():
                return self.transform(layer, transform, persist=persist)
        with self._lock:
            self._require_non_reentrant_write()
            self.scope(layer)
            previous = self._config.value
            self._patch_transforming = True
            try:
                replacement = transform(self._config.patch(layer))
            finally:
                self._patch_transforming = False
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

    def scope_matches(
        self,
        layer: str,
        expected: Mapping[str, object],
        *,
        keys: Iterable[str],
    ) -> bool:
        """Compare selected layer keys under the config runtime lock."""

        selected_keys = tuple(keys)
        if any(not isinstance(key, str) for key in selected_keys):
            raise TypeError("Config patch comparison keys must be strings")
        with self._lock:
            self.scope(layer)
            current = self._config.patch(layer)
            return all(
                (key in current) == (key in expected)
                and (key not in current or current[key] == expected[key])
                for key in selected_keys
            )

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
        if self._transaction_depth:
            self._transaction_changed = True
            self._transaction_operation = operation
            self._transaction_layers.add(layer)
            return (
                ConfigChange(
                    revision=self._revision + 1,
                    operation=operation,
                    layer=layer,
                    previous=previous,
                    current=self._config.value,
                ),
                False,
            )
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

    def _require_non_reentrant_write(self) -> None:
        if self._patch_transforming:
            raise RuntimeError(
                "Config patch transforms cannot perform re-entrant writes"
            )

    def _requires_persistent_transaction(
        self,
        layer: str,
        *,
        persist: bool | None,
    ) -> bool:
        with self._lock:
            try:
                resolved = self._layers[layer]
            except KeyError as exc:
                raise KeyError(f"Unknown config layer: {layer}") from exc
            should_persist = resolved.persistent if persist is None else persist
            return bool(should_persist and self._transaction_depth == 0)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        paths = tuple(
            sorted(
                {
                    normalized_config_path(layer.path)
                    for layer in self._layers.values()
                    if layer.persistent and layer.path is not None
                },
                key=str,
            )
        )
        stack = ExitStack()
        runtime_locked = False
        outermost = False
        should_publish = False
        body_error: BaseException | None = None
        publication_error: BaseException | None = None
        try:
            for path in paths:
                stack.enter_context(config_file_transaction_lock(path))
            self._lock.acquire()
            runtime_locked = True
            outermost = self._transaction_depth == 0
            if outermost:
                self._publication_holds += 1
                self._transaction_previous = self._config.value
                self._transaction_changed = False
                self._transaction_operation = "reload"
                self._transaction_layers.clear()
                self._config.reload(strict=True, notify=False)
            self._transaction_depth += 1
            try:
                yield
            except BaseException as exc:
                body_error = exc
        finally:
            if runtime_locked:
                if self._transaction_depth:
                    self._transaction_depth -= 1
                if outermost:
                    previous = self._transaction_previous
                    assert previous is not _NO_TRANSACTION
                    typed_previous = cast(T, previous)
                    changed_layer = (
                        next(iter(self._transaction_layers))
                        if len(self._transaction_layers) == 1
                        else None
                    )
                    if (
                        self._transaction_changed
                        or self._config.value != typed_previous
                    ):
                        self._revision += 1
                        self._pending_changes.append(
                            ConfigChange(
                                revision=self._revision,
                                operation=self._transaction_operation,
                                layer=changed_layer,
                                previous=typed_previous,
                                current=self._config.value,
                            )
                        )
                    self._transaction_previous = _NO_TRANSACTION
                    self._transaction_changed = False
                    self._transaction_operation = "reload"
                    self._transaction_layers.clear()
                self._lock.release()
            try:
                stack.close()
            finally:
                if outermost:
                    with self._lock:
                        self._publication_holds -= 1
                        if (
                            self._pending_changes
                            and not self._publishing
                            and self._publication_holds == 0
                        ):
                            self._publishing = True
                            should_publish = True
        if should_publish:
            try:
                self._drain_publications()
            except BaseException as exc:
                publication_error = exc
        if body_error is not None:
            if publication_error is not None:
                body_error.add_note(
                    f"Config listener publication also failed: {publication_error!r}"
                )
            raise body_error.with_traceback(body_error.__traceback__)
        if publication_error is not None:
            raise publication_error

    def _drain_publications(self) -> None:
        first_error: Exception | None = None
        try:
            while True:
                with self._lock:
                    if self._publication_holds:
                        self._publishing = False
                        break
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
