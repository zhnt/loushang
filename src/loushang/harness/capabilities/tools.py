from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

ToolNameResolver = Callable[[T], str]
ToolActivationPredicate = Callable[[str, T], bool]


@dataclass(frozen=True)
class ToolActivationSnapshot:
    revision: int
    available_names: tuple[str, ...]
    requested_names: tuple[str, ...]
    active_names: tuple[str, ...]
    missing_requested_names: tuple[str, ...]


@dataclass(frozen=True)
class ToolActivationDiff:
    available_added: tuple[str, ...] = ()
    available_removed: tuple[str, ...] = ()
    available_replaced: tuple[str, ...] = ()
    requested_added: tuple[str, ...] = ()
    requested_removed: tuple[str, ...] = ()
    activated: tuple[str, ...] = ()
    deactivated: tuple[str, ...] = ()
    available_order_changed: bool = False
    requested_order_changed: bool = False
    active_order_changed: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.available_added
            or self.available_removed
            or self.available_replaced
            or self.requested_added
            or self.requested_removed
            or self.activated
            or self.deactivated
            or self.available_order_changed
            or self.requested_order_changed
            or self.active_order_changed
        )


@dataclass(frozen=True)
class ToolActivationResolution(Generic[T]):
    names: tuple[str, ...]
    items: tuple[T, ...]
    missing_names: tuple[str, ...]


@dataclass(frozen=True)
class ToolActivationChange(Generic[T]):
    previous: ToolActivationSnapshot
    current: ToolActivationSnapshot
    diff: ToolActivationDiff
    active_items: tuple[T, ...]


ToolRebinder = Callable[[ToolActivationChange[T]], None]


class ToolActivationCoordinator(Generic[T]):
    """Own tool availability and activation while products apply side effects."""

    def __init__(
        self,
        *,
        available: Iterable[T] = (),
        requested_names: Iterable[str] = (),
        name_of: ToolNameResolver[T] | None = None,
        allowed_names: Iterable[str] | None = None,
        should_activate_new: ToolActivationPredicate[T] | None = None,
        rebind: ToolRebinder[T] | None = None,
    ) -> None:
        self._name_of = name_of or _default_name
        self._allowed_names = (
            frozenset(_unique_names(allowed_names))
            if allowed_names is not None
            else None
        )
        self._should_activate_new = should_activate_new
        self._rebind = rebind
        self._available = self._index_available(available)
        self._requested_names = self.filter_names(requested_names)
        self._active_names = self._resolve_names(self._requested_names)
        self._revision = 0

    def snapshot(self) -> ToolActivationSnapshot:
        active_set = set(self._active_names)
        return ToolActivationSnapshot(
            revision=self._revision,
            available_names=tuple(self._available),
            requested_names=self._requested_names,
            active_names=self._active_names,
            missing_requested_names=tuple(
                name for name in self._requested_names if name not in active_set
            ),
        )

    def is_allowed(self, name: str) -> bool:
        return self._allowed_names is None or name in self._allowed_names

    def filter_names(self, names: Iterable[str]) -> tuple[str, ...]:
        return tuple(name for name in _unique_names(names) if self.is_allowed(name))

    def filter_items(self, items: Iterable[T]) -> tuple[T, ...]:
        return tuple(
            item for item in items if self.is_allowed(self._validated_name(item))
        )

    def resolve(self, names: Iterable[str]) -> ToolActivationResolution[T]:
        filtered_names = self.filter_names(names)
        resolved_names = tuple(
            name for name in filtered_names if name in self._available
        )
        resolved_set = set(resolved_names)
        return ToolActivationResolution(
            names=resolved_names,
            items=tuple(self._available[name] for name in resolved_names),
            missing_names=tuple(
                name for name in filtered_names if name not in resolved_set
            ),
        )

    def active_items(self) -> tuple[T, ...]:
        return tuple(self._available[name] for name in self._active_names)

    def request(
        self,
        names: Iterable[str],
        *,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        previous_available = dict(self._available)
        previous = self.snapshot()
        self._requested_names = self.filter_names(names)
        self._active_names = self._resolve_names(self._requested_names)
        return self._finish_transition(
            previous,
            previous_available=previous_available,
            rebind=rebind,
        )

    def activate(
        self,
        names: Iterable[str],
        *,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        """Add requested names without discarding deferred activation intent."""

        return self.request(
            (*self._requested_names, *names),
            rebind=rebind,
        )

    def refresh(
        self,
        available: Iterable[T],
        *,
        activate_new: bool = True,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        previous_available = dict(self._available)
        previous = self.snapshot()
        self._available = self._index_available(available)
        if activate_new and self._should_activate_new is not None:
            requested = list(self._requested_names)
            requested_set = set(requested)
            for name, item in self._available.items():
                if name in previous_available or name in requested_set:
                    continue
                if self._should_activate_new(name, item):
                    requested.append(name)
                    requested_set.add(name)
            self._requested_names = tuple(requested)
        self._active_names = self._resolve_names(self._requested_names)
        return self._finish_transition(
            previous,
            previous_available=previous_available,
            rebind=rebind,
        )

    def rebind(self) -> ToolActivationChange[T]:
        snapshot = self.snapshot()
        change = ToolActivationChange(
            previous=snapshot,
            current=snapshot,
            diff=ToolActivationDiff(),
            active_items=self.active_items(),
        )
        if self._rebind is not None:
            self._rebind(change)
        return change

    def _finish_transition(
        self,
        previous: ToolActivationSnapshot,
        *,
        previous_available: dict[str, T],
        rebind: bool,
    ) -> ToolActivationChange[T]:
        current_without_revision = self.snapshot()
        diff = _activation_diff(
            previous,
            current_without_revision,
            previous_available=previous_available,
            current_available=self._available,
        )
        if diff.changed:
            self._revision += 1
        current = self.snapshot()
        change = ToolActivationChange(
            previous=previous,
            current=current,
            diff=diff,
            active_items=self.active_items(),
        )
        if rebind and self._rebind is not None:
            self._rebind(change)
        return change

    def _resolve_names(self, names: Iterable[str]) -> tuple[str, ...]:
        return tuple(name for name in names if name in self._available)

    def _index_available(self, items: Iterable[T]) -> dict[str, T]:
        indexed: dict[str, T] = {}
        for item in items:
            name = self._validated_name(item)
            if not self.is_allowed(name):
                continue
            if name in indexed:
                raise ValueError(f"duplicate available tool name: {name}")
            indexed[name] = item
        return indexed

    def _validated_name(self, item: T) -> str:
        name = self._name_of(item)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool names must be non-empty strings")
        return name


def _activation_diff(
    previous: ToolActivationSnapshot,
    current: ToolActivationSnapshot,
    *,
    previous_available: dict[str, T],
    current_available: dict[str, T],
) -> ToolActivationDiff:
    previous_available_names = set(previous.available_names)
    current_available_names = set(current.available_names)
    previous_requested_names = set(previous.requested_names)
    current_requested_names = set(current.requested_names)
    previous_active_names = set(previous.active_names)
    current_active_names = set(current.active_names)
    common_available = previous_available_names & current_available_names
    return ToolActivationDiff(
        available_added=tuple(
            name
            for name in current.available_names
            if name not in previous_available_names
        ),
        available_removed=tuple(
            name
            for name in previous.available_names
            if name not in current_available_names
        ),
        available_replaced=tuple(
            name
            for name in current.available_names
            if name in common_available
            and previous_available[name] is not current_available[name]
        ),
        requested_added=tuple(
            name
            for name in current.requested_names
            if name not in previous_requested_names
        ),
        requested_removed=tuple(
            name
            for name in previous.requested_names
            if name not in current_requested_names
        ),
        activated=tuple(
            name for name in current.active_names if name not in previous_active_names
        ),
        deactivated=tuple(
            name for name in previous.active_names if name not in current_active_names
        ),
        available_order_changed=(
            previous.available_names != current.available_names
            and previous_available_names == current_available_names
        ),
        requested_order_changed=(
            previous.requested_names != current.requested_names
            and previous_requested_names == current_requested_names
        ),
        active_order_changed=(
            previous.active_names != current.active_names
            and previous_active_names == current_active_names
        ),
    )


def _unique_names(names: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str):
            raise TypeError("tool names must be strings")
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return tuple(unique)


def _default_name(item: T) -> str:
    return getattr(item, "name", "")


__all__ = [
    "ToolActivationChange",
    "ToolActivationCoordinator",
    "ToolActivationDiff",
    "ToolActivationResolution",
    "ToolActivationSnapshot",
]
