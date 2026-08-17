"""Product-neutral settings runtime over the layered config engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Generic, TypeVar

from loushang.harness.config.runtime import (
    ConfigChange,
    ConfigScope,
    ScopedConfigRuntime,
)
from loushang.harness.config.types import ConfigIssue, ConfigSnapshot

T = TypeVar("T")


class SettingsRuntime(Generic[T]):
    """Expose common settings lifecycle operations without product fields.

    Products own their value type, schema, defaults, and field-level validation.
    This façade owns only the reusable operations around a layered configuration:
    reload, scoped patch application, subscriptions, snapshots, and issue drain.
    """

    def __init__(self, runtime: ScopedConfigRuntime[T]) -> None:
        self._runtime = runtime

    @property
    def value(self) -> T:
        return self._runtime.value

    @property
    def revision(self) -> int:
        return self._runtime.revision

    def snapshot(self) -> ConfigSnapshot[T]:
        return self._runtime.snapshot()

    def scope(self, layer: str) -> ConfigScope[T]:
        return self._runtime.scope(layer)

    def reload(self) -> ConfigChange[T]:
        return self._runtime.reload()

    def update(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        return self._runtime.update(layer, patch, persist=persist)

    def replace(
        self,
        layer: str,
        patch: Mapping[str, object],
        *,
        persist: bool | None = None,
    ) -> ConfigChange[T]:
        return self._runtime.replace(layer, patch, persist=persist)

    def apply_overrides(
        self,
        layer: str,
        overrides: Mapping[str, object] | T,
    ) -> ConfigChange[T]:
        return self._runtime.apply_overrides(layer, overrides)

    def subscribe_change(
        self,
        listener: Callable[[ConfigChange[T]], None],
    ) -> Callable[[], None]:
        return self._runtime.subscribe_change(listener)

    def subscribe(self, listener: Callable[[T], None]) -> Callable[[], None]:
        return self._runtime.subscribe(listener)

    def drain_issues(self) -> tuple[ConfigIssue, ...]:
        return self._runtime.drain_issues()

    @property
    def global_base_dir(self) -> Path | None:
        return self._optional_base_dir("global")

    @property
    def project_base_dir(self) -> Path | None:
        return self._optional_base_dir("project")

    def _optional_base_dir(self, layer: str) -> Path | None:
        try:
            return self.scope(layer).base_dir
        except KeyError:
            return None


__all__ = ["SettingsRuntime"]
