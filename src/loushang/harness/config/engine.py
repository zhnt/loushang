from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Generic, TypeVar

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
        return self._value

    @property
    def layers(self) -> tuple[ConfigLayer, ...]:
        return self._layers

    def encode(self, value: T) -> dict[str, object]:
        return deepcopy(dict(self._codec.encode(value)))

    def snapshot(self) -> ConfigSnapshot[T]:
        return ConfigSnapshot(
            value=self._value,
            patches={name: deepcopy(patch) for name, patch in self._patches.items()},
        )

    def layer_path(self, layer_name: str) -> Path | None:
        return self._require_layer(layer_name).path

    def patch(self, layer_name: str) -> dict[str, object]:
        self._require_layer(layer_name)
        return deepcopy(self._patches[layer_name])

    def reload(self, *, strict: bool = False, notify: bool = True) -> None:
        patches, load_issues = self._load_persistent_layers(self._patches)
        if strict and load_issues:
            self._issues.extend(load_issues)
            raise load_issues[0].error
        value, compose_issues = self._compose(patches)
        self._patches = patches
        self._value = value
        self._issues.extend(load_issues)
        self._issues.extend(compose_issues)
        if notify:
            self._notify()

    def update(
        self,
        layer_name: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> None:
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
        self._patches = patches
        self._value = value
        self._issues.extend(issues)
        self._notify()

    def replace(
        self,
        layer_name: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> None:
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
        self._patches = patches
        self._value = value
        self._issues.extend(issues)
        self._notify()

    def subscribe(self, listener: ConfigListener[T]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                return

        return unsubscribe

    def drain_issues(self) -> tuple[ConfigIssue, ...]:
        issues = tuple(self._issues)
        self._issues.clear()
        return issues

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

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self._value)

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


__all__ = ["LayeredConfig", "merge_config_patch"]
