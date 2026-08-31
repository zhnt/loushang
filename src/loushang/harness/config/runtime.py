from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Generic, Literal, TypeAlias, TypeVar, cast

from loushang.harness.config.engine import LayeredConfig
from loushang.harness.config.types import (
    ConfigIssue,
    ConfigLayer,
    ConfigSnapshot,
)

T = TypeVar("T")
_NO_TRANSACTION = object()
ConfigOperation = Literal["reload", "update", "replace", "transaction"]
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


@dataclass
class ConfigTransactionResult(Generic[T]):
    change: ConfigChange[T] | None = None


ConfigMutationReceipt: TypeAlias = ConfigChange[T] | ConfigTransactionResult[T]


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
    ) -> ConfigMutationReceipt[T]:
        return self._runtime.update(self.name, patch, persist=persist)

    def replace(
        self,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigMutationReceipt[T]:
        return self._runtime.replace(self.name, patch, persist=persist)

    def transform(
        self,
        transform: ConfigPatchTransform,
        *,
        persist: bool | None = None,
    ) -> ConfigMutationReceipt[T]:
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
        self._engine_authority = object()
        self._config._bind_runtime(self._engine_authority)
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
        self._transaction_operation_count = 0
        self._transaction_layers: set[str | None] = set()
        self._transaction_result: ConfigTransactionResult[T] | None = None
        self._lock = RLock()

    @property
    def value(self) -> T:
        return self._config.value

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def snapshot(self) -> ConfigSnapshot[T]:
        return self._config.snapshot()

    def scope(self, layer: str) -> ConfigScope[T]:
        try:
            resolved = self._layers[layer]
        except KeyError as exc:
            raise KeyError(f"Unknown config layer: {layer}") from exc
        return ConfigScope(self, resolved)

    def scope_patch(self, layer: str) -> dict[str, object]:
        self.scope(layer)
        return self._config.patch(layer)

    def reload(self) -> ConfigChange[T]:
        with self._transaction(strict_reload=False) as transaction:
            self._record_transaction_operation(operation="reload", layer=None)
        assert transaction.change is not None
        return transaction.change

    def transaction(self) -> AbstractContextManager[ConfigTransactionResult[T]]:
        """Refresh and mutate persistent layers as one externally visible change.

        All configured persistent paths are locked in stable order.  The final
        notification is emitted only after the runtime and file locks are gone.
        """

        return self._transaction(strict_reload=True)

    def defer_publications(self) -> AbstractContextManager[None]:
        """Defer runtime listeners while an outer authority lock is held."""

        return self._defer_publications()

    def update(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigMutationReceipt[T]:
        if not self._in_transaction():
            with self.transaction() as transaction:
                self.update(layer, patch, persist=persist)
            assert transaction.change is not None
            return transaction.change
        with self._lock:
            self._require_non_reentrant_write()
            self.scope(layer)
            self._config.update(
                layer,
                patch,
                persist=persist,
                notify=True,
                _authority=self._engine_authority,
            )
            return self._record_transaction_operation(
                operation="update",
                layer=layer,
            )

    def replace(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigMutationReceipt[T]:
        if not self._in_transaction():
            with self.transaction() as transaction:
                self.replace(layer, patch, persist=persist)
            assert transaction.change is not None
            return transaction.change
        with self._lock:
            self._require_non_reentrant_write()
            self.scope(layer)
            self._config.replace(
                layer,
                patch,
                persist=persist,
                notify=True,
                _authority=self._engine_authority,
            )
            return self._record_transaction_operation(
                operation="replace",
                layer=layer,
            )

    def transform(
        self,
        layer: str,
        transform: ConfigPatchTransform,
        *,
        persist: bool | None = None,
    ) -> ConfigMutationReceipt[T]:
        """Read, transform, replace, and enqueue one layer atomically."""

        if not callable(transform):
            raise TypeError("Config patch transform must be callable")
        if not self._in_transaction():
            with self.transaction() as transaction:
                self.transform(layer, transform, persist=persist)
            assert transaction.change is not None
            return transaction.change
        with self._lock:
            self._require_non_reentrant_write()
            self.scope(layer)
            self._patch_transforming = True
            try:
                replacement = transform(self._config.patch(layer))
            finally:
                self._patch_transforming = False
            if not isinstance(replacement, Mapping):
                raise TypeError("Config patch transform must return a mapping")
            self._config.replace(
                layer,
                replacement,
                persist=persist,
                notify=True,
                _authority=self._engine_authority,
            )
            return self._record_transaction_operation(
                operation="replace",
                layer=layer,
            )

    def scope_matches(
        self,
        layer: str,
        expected: Mapping[str, object],
        *,
        keys: Iterable[str],
    ) -> bool:
        """Compare selected layer keys against one engine-locked patch."""

        selected_keys = tuple(keys)
        if any(not isinstance(key, str) for key in selected_keys):
            raise TypeError("Config patch comparison keys must be strings")
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
    ) -> ConfigMutationReceipt[T]:
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
        return self._config.drain_issues()

    def _in_transaction(self) -> bool:
        with self._lock:
            self._require_non_reentrant_write()
            return self._transaction_depth > 0

    def _record_transaction_operation(
        self,
        *,
        operation: ConfigOperation,
        layer: str | None,
    ) -> ConfigTransactionResult[T]:
        with self._lock:
            if not self._transaction_depth:
                raise RuntimeError("Config mutation requires a runtime transaction")
            self._transaction_changed = True
            self._transaction_operation = operation
            self._transaction_operation_count += 1
            self._transaction_layers.add(layer)
            result = self._transaction_result
            assert result is not None
            return result

    def _require_non_reentrant_write(self) -> None:
        if self._patch_transforming:
            raise RuntimeError(
                "Config patch transforms cannot perform re-entrant writes"
            )

    @contextmanager
    def _transaction(
        self,
        *,
        strict_reload: bool,
    ) -> Iterator[ConfigTransactionResult[T]]:
        with self._lock:
            self._require_non_reentrant_write()
            if self._transaction_depth:
                nested_result = self._transaction_result
                assert nested_result is not None
                self._transaction_depth += 1
                try:
                    yield nested_result
                finally:
                    self._transaction_depth -= 1
                return

        publication_held = False
        should_publish = False
        transaction_error: BaseException | None = None
        publication_error: BaseException | None = None
        result: ConfigTransactionResult[T] | None = None
        try:
            with self._config.transaction(
                notify_on_exit=True,
                strict_reload=strict_reload,
                _authority=self._engine_authority,
            ) as engine_transaction:
                self._lock.acquire()
                try:
                    self._publication_holds += 1
                    publication_held = True
                    self._transaction_previous = engine_transaction.previous
                    self._transaction_changed = False
                    self._transaction_operation = "reload"
                    self._transaction_operation_count = 0
                    self._transaction_layers.clear()
                    result = ConfigTransactionResult()
                    self._transaction_result = result
                    self._transaction_depth = 1
                    try:
                        yield result
                    finally:
                        self._transaction_depth = 0
                        previous = cast(T, self._transaction_previous)
                        changed_layer = (
                            next(iter(self._transaction_layers))
                            if len(self._transaction_layers) == 1
                            else None
                        )
                        operation: ConfigOperation = (
                            self._transaction_operation
                            if self._transaction_operation_count <= 1
                            else "transaction"
                        )
                        if self._transaction_changed or self._config.value != previous:
                            self._revision += 1
                            change = ConfigChange(
                                revision=self._revision,
                                operation=operation,
                                layer=changed_layer,
                                previous=previous,
                                current=self._config.value,
                            )
                            self._pending_changes.append(change)
                            assert result is not None
                            result.change = change
                        self._transaction_previous = _NO_TRANSACTION
                        self._transaction_changed = False
                        self._transaction_operation = "reload"
                        self._transaction_operation_count = 0
                        self._transaction_layers.clear()
                        self._transaction_result = None
                finally:
                    self._lock.release()
        except BaseException as exc:
            transaction_error = exc
        if publication_held:
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
                if publication_error is None:
                    publication_error = exc
                else:
                    publication_error.add_note(
                        f"Runtime listener publication also failed: {exc!r}"
                    )
        if transaction_error is not None:
            if publication_error is not None:
                transaction_error.add_note(
                    f"Runtime listener publication also failed: {publication_error!r}"
                )
            raise transaction_error.with_traceback(transaction_error.__traceback__)
        if publication_error is not None:
            raise publication_error

    @contextmanager
    def _defer_publications(self) -> Iterator[None]:
        should_publish = False
        body_error: BaseException | None = None
        publication_error: BaseException | None = None
        with self._lock:
            self._publication_holds += 1
        try:
            yield
        except BaseException as exc:
            body_error = exc
        finally:
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
                    "Deferred config listener publication also failed: "
                    f"{publication_error!r}"
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
    "ConfigMutationReceipt",
    "ConfigOperation",
    "ConfigPatchTransform",
    "ConfigScope",
    "ConfigTransactionResult",
    "ScopedConfigRuntime",
]
