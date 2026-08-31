from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Generic, TypeVar

from loushang.harness.config._file_transaction import (
    config_file_transaction_lock,
    normalized_config_path,
)
from loushang.harness.config.store import JsonConfigStore
from loushang.harness.config.types import (
    ConfigCodec,
    ConfigIssue,
    ConfigLayer,
    ConfigSnapshot,
    ConfigStore,
)

T = TypeVar("T")
ConfigListener = Callable[[T], None]


@dataclass
class LayeredConfigTransaction(Generic[T]):
    previous: T
    current: T
    changed: bool = False


class LayeredConfig(Generic[T]):
    def __init__(
        self,
        *,
        codec: ConfigCodec[T],
        layers: Sequence[ConfigLayer],
        initial: Mapping[str, Mapping[str, object] | T] | None = None,
        store: ConfigStore | None = None,
    ) -> None:
        self._codec = codec
        self._layers = tuple(layers)
        self._layers_by_name = {layer.name: layer for layer in self._layers}
        if len(self._layers_by_name) != len(self._layers):
            raise ValueError("config layer names must be unique")
        self._store = store or JsonConfigStore()
        self._patches: dict[str, dict[str, object]] = {
            layer.name: {} for layer in self._layers
        }
        self._issues: list[ConfigIssue] = []
        self._listeners: list[ConfigListener[T]] = []
        self._lock = RLock()
        self._pending_publications: deque[T] = deque()
        self._publishing = False
        self._runtime_authority: object | None = None
        self._transaction_depth = 0
        self._transaction_changed = False
        self._transaction_handle: LayeredConfigTransaction[T] | None = None
        self._transaction_authority: object | None = None
        with self._path_locks():
            self._patches, load_issues = self._load_persistent_layers(self._patches)
        self._issues.extend(load_issues)
        for layer_name, value in (initial or {}).items():
            self._require_layer(layer_name)
            patch = value if isinstance(value, Mapping) else self._codec.encode(value)
            self._patches[layer_name] = merge_config_patch(
                self._patches[layer_name], patch
            )
        self._value, compose_issues = self._compose(self._patches)
        self._issues.extend(compose_issues)

    @property
    def value(self) -> T:
        with self._lock:
            return self._value

    @property
    def layers(self) -> tuple[ConfigLayer, ...]:
        return self._layers

    def encode(self, value: T) -> dict[str, object]:
        with self._lock:
            return deepcopy(dict(self._codec.encode(value)))

    def snapshot(self) -> ConfigSnapshot[T]:
        with self._lock:
            return ConfigSnapshot(
                value=self._value,
                patches={
                    name: deepcopy(patch) for name, patch in self._patches.items()
                },
            )

    def layer_path(self, layer_name: str) -> Path | None:
        return self._require_layer(layer_name).path

    def patch(self, layer_name: str) -> dict[str, object]:
        with self._lock:
            self._require_layer(layer_name)
            return deepcopy(self._patches[layer_name])

    def reload(
        self,
        *,
        strict: bool = False,
        notify: bool = True,
        _authority: object | None = None,
    ) -> None:
        self._require_mutation_authority(_authority)
        with self._lock:
            nested = self._transaction_depth > 0
        if not nested:
            with self._transaction(
                notify_on_exit=notify,
                reload_strict=strict,
                _authority=_authority,
            ):
                pass
            return
        with self._lock:
            self._require_mutation_authority(_authority)
            changed = self._reload_unlocked(strict=strict)
            if self._transaction_depth and changed:
                self._transaction_changed = True

    def transaction(
        self,
        *,
        notify_on_exit: bool = True,
        strict_reload: bool = True,
        _authority: object | None = None,
    ) -> AbstractContextManager[LayeredConfigTransaction[T]]:
        """Serialize a strict refresh plus one or more config mutations."""

        self._require_mutation_authority(_authority)
        return self._transaction(
            notify_on_exit=notify_on_exit,
            reload_strict=strict_reload,
            _authority=_authority,
        )

    def _reload_unlocked(self, *, strict: bool) -> bool:
        previous = self.snapshot()
        patches, load_issues = self._load_persistent_layers(self._patches)
        if strict and load_issues:
            self._issues.extend(load_issues)
            raise load_issues[0].error
        value, compose_issues = self._compose(patches)
        self._patches = patches
        self._value = value
        self._issues.extend(load_issues)
        self._issues.extend(compose_issues)
        return previous.value != self._value or previous.patches != self._patches

    def update(
        self,
        layer_name: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
        notify: bool = True,
        _authority: object | None = None,
    ) -> None:
        self._require_mutation_authority(_authority)
        if self._requires_transaction(layer_name, persist=persist):
            with self.transaction(
                notify_on_exit=notify,
                _authority=_authority,
            ):
                self.update(
                    layer_name,
                    patch,
                    persist=persist,
                    notify=notify,
                    _authority=_authority,
                )
            return
        with self._lock:
            self._require_mutation_authority(_authority)
            layer = self._require_layer(layer_name)
            merged = merge_config_patch(self._patches[layer_name], patch)
            patches = self._candidate_patches(layer_name, merged)
            value, issues = self._compose(patches)
            should_persist = layer.persistent if persist is None else persist
            if should_persist:
                if layer.path is None:
                    raise ValueError(
                        f"Config layer {layer_name!r} requires a path for persistence"
                    )
                self._store.save(layer.path, merged)
            changed = self._patches[layer_name] != merged or self._value != value
            self._patches = patches
            self._value = value
            self._issues.extend(issues)
            if self._transaction_depth and changed:
                self._transaction_changed = True
            should_notify = notify and self._transaction_depth == 0 and changed
            should_drain = should_notify and self._enqueue_publication_unlocked(value)
        if should_drain:
            self._drain_publications()

    def replace(
        self,
        layer_name: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
        notify: bool = True,
        _authority: object | None = None,
    ) -> None:
        self._require_mutation_authority(_authority)
        if self._requires_transaction(layer_name, persist=persist):
            with self.transaction(
                notify_on_exit=notify,
                _authority=_authority,
            ):
                self.replace(
                    layer_name,
                    patch,
                    persist=persist,
                    notify=notify,
                    _authority=_authority,
                )
            return
        with self._lock:
            self._require_mutation_authority(_authority)
            layer = self._require_layer(layer_name)
            replacement = deepcopy(dict(patch))
            patches = self._candidate_patches(layer_name, replacement)
            value, issues = self._compose(patches)
            should_persist = layer.persistent if persist is None else persist
            if should_persist:
                if layer.path is None:
                    raise ValueError(
                        f"Config layer {layer_name!r} requires a path for persistence"
                    )
                self._store.save(layer.path, replacement)
            changed = self._patches[layer_name] != replacement or self._value != value
            self._patches = patches
            self._value = value
            self._issues.extend(issues)
            if self._transaction_depth and changed:
                self._transaction_changed = True
            should_notify = notify and self._transaction_depth == 0 and changed
            should_drain = should_notify and self._enqueue_publication_unlocked(value)
        if should_drain:
            self._drain_publications()

    def subscribe(self, listener: ConfigListener[T]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    return

        return unsubscribe

    def drain_issues(self) -> tuple[ConfigIssue, ...]:
        with self._lock:
            issues = tuple(self._issues)
            self._issues.clear()
            return issues

    def publish(self, *, _authority: object | None = None) -> None:
        """Publish the current immutable value snapshot in commit order."""

        self._require_mutation_authority(_authority)
        with self._lock:
            self._require_mutation_authority(_authority)
            value = self._value
            should_drain = self._enqueue_publication_unlocked(value)
        if should_drain:
            self._drain_publications()

    def _bind_runtime(self, authority: object) -> None:
        """Give one runtime exclusive mutation/projection ownership."""

        if authority is None:
            raise ValueError("Config runtime authority is required")
        with self._lock:
            if self._runtime_authority is None:
                self._runtime_authority = authority
                return
            if self._runtime_authority is not authority:
                raise RuntimeError("Layered config already has a runtime owner")

    def _require_mutation_authority(self, authority: object | None) -> None:
        with self._lock:
            owner = self._runtime_authority
            if owner is None or authority is owner:
                return
        raise RuntimeError("Layered config mutation is owned by its scoped runtime")

    def _requires_transaction(
        self,
        layer_name: str,
        *,
        persist: bool | None,
    ) -> bool:
        with self._lock:
            layer = self._require_layer(layer_name)
            should_persist = layer.persistent if persist is None else persist
            if should_persist and layer.path is None:
                raise ValueError(
                    f"Config layer {layer_name!r} requires a path for persistence"
                )
            return bool(should_persist and self._transaction_depth == 0)

    @contextmanager
    def _transaction(
        self,
        *,
        notify_on_exit: bool,
        reload_strict: bool,
        _authority: object | None,
    ) -> Iterator[LayeredConfigTransaction[T]]:
        stack = ExitStack()
        locked = False
        outermost = False
        body_error: BaseException | None = None
        publication_error: BaseException | None = None
        handle: LayeredConfigTransaction[T] | None = None
        should_drain = False
        try:
            stack.enter_context(self._path_locks())
            self._lock.acquire()
            locked = True
            self._require_mutation_authority(_authority)
            outermost = self._transaction_depth == 0
            if outermost:
                self._transaction_authority = _authority
                handle = LayeredConfigTransaction(
                    previous=self._value,
                    current=self._value,
                )
                self._transaction_handle = handle
                self._transaction_changed = False
                if self._reload_unlocked(strict=reload_strict):
                    self._transaction_changed = True
            else:
                if (
                    self._transaction_authority is not None
                    and _authority is not None
                    and self._transaction_authority is not _authority
                ):
                    raise RuntimeError("Config transaction authority changed")
                handle = self._transaction_handle
                assert handle is not None
            self._transaction_depth += 1
            try:
                yield handle
            except BaseException as exc:
                body_error = exc
        finally:
            if locked:
                if self._transaction_depth:
                    self._transaction_depth -= 1
                if outermost:
                    assert handle is not None
                    handle.current = self._value
                    handle.changed = self._transaction_changed
                    if notify_on_exit and handle.changed:
                        should_drain = self._enqueue_publication_unlocked(
                            handle.current
                        )
                    self._transaction_handle = None
                    self._transaction_changed = False
                    self._transaction_authority = None
                self._lock.release()
            stack.close()
        if should_drain:
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

    @contextmanager
    def _path_locks(self) -> Iterator[None]:
        paths = tuple(
            sorted(
                {
                    normalized_config_path(layer.path)
                    for layer in self._layers
                    if layer.path is not None
                },
                key=str,
            )
        )
        with ExitStack() as stack:
            for path in paths:
                stack.enter_context(config_file_transaction_lock(path))
            yield

    def _enqueue_publication_unlocked(self, value: T) -> bool:
        self._pending_publications.append(value)
        if self._publishing:
            return False
        self._publishing = True
        return True

    def _drain_publications(self) -> None:
        first_error: Exception | None = None
        try:
            while True:
                with self._lock:
                    if not self._pending_publications:
                        self._publishing = False
                        break
                    value = self._pending_publications.popleft()
                    listeners = tuple(self._listeners)
                for listener in listeners:
                    try:
                        listener(value)
                    except Exception as exc:
                        if first_error is None:
                            first_error = exc
        except BaseException:
            with self._lock:
                self._pending_publications.clear()
                self._publishing = False
            raise
        if first_error is not None:
            raise first_error

    def _load_persistent_layers(
        self,
        current: Mapping[str, Mapping[str, object]],
    ) -> tuple[dict[str, dict[str, object]], list[ConfigIssue]]:
        patches = {name: deepcopy(dict(patch)) for name, patch in current.items()}
        issues: list[ConfigIssue] = []
        for layer in self._layers:
            if layer.path is None:
                continue
            try:
                loaded = deepcopy(dict(self._store.load(layer.path)))
                candidate = {
                    name: deepcopy(dict(patch)) for name, patch in patches.items()
                }
                candidate[layer.name] = loaded
                self._compose(candidate)
            except Exception as exc:
                issues.append(
                    ConfigIssue(
                        layer=layer.name,
                        message=str(exc),
                        error=exc,
                        code="config_layer_load_failed",
                    )
                )
                continue
            patches = candidate
        return patches, issues

    def _compose(
        self,
        patches: Mapping[str, Mapping[str, object]],
    ) -> tuple[T, tuple[ConfigIssue, ...]]:
        value = self._codec.default()
        issues: list[ConfigIssue] = []
        for layer in self._layers:
            result = self._codec.apply(
                value,
                patches[layer.name],
                layer=layer.name,
            )
            value = result.value
            issues.extend(result.issues)
        return value, tuple(issues)

    def _candidate_patches(
        self,
        layer_name: str,
        patch: Mapping[str, object],
    ) -> dict[str, dict[str, object]]:
        patches = {name: deepcopy(value) for name, value in self._patches.items()}
        patches[layer_name] = deepcopy(dict(patch))
        return patches

    def _require_layer(self, layer_name: str) -> ConfigLayer:
        try:
            return self._layers_by_name[layer_name]
        except KeyError as exc:
            raise KeyError(f"Unknown config layer: {layer_name}") from exc


def merge_config_patch(
    base: Mapping[str, object],
    updates: Mapping[str, object],
) -> dict[str, object]:
    merged = deepcopy(dict(base))
    for key, value in updates.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = merge_config_patch(current, value)
        else:
            merged[key] = deepcopy(value)
    return merged


__all__ = ["LayeredConfig", "LayeredConfigTransaction", "merge_config_patch"]
