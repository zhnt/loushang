"""Generation-scoped access to captured workspace operation facets."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from loushang.harness.runtime.bindings import RuntimeBindingLease, RuntimeBindingState


class GenerationBoundOperationSet:
    """Own immutable operation facets and revoke every captured proxy together."""

    def __init__(
        self,
        operations: Mapping[str, object],
        *,
        stale_message: str = "Workspace operation generation is stale.",
    ) -> None:
        values = dict(operations)
        if not values or any(
            not isinstance(name, str) or not name or value is None
            for name, value in values.items()
        ):
            raise ValueError("Workspace operation generation requires named facets")
        self._state = RuntimeBindingState[Mapping[str, object]](
            MappingProxyType(values),
            stale_message=stale_message,
        )
        self._invalidated = False

    def capture(self, name: str) -> object:
        if self._invalidated:
            raise RuntimeError(self._state.stale_message)
        if name not in self._state.require():
            raise KeyError(f"Unknown workspace operation facet: {name}")
        return _GenerationBoundOperations(self._state.capture(), name)

    def invalidate(self, message: str | None = None) -> None:
        if self._invalidated:
            return
        self._invalidated = True
        self._state.invalidate(message)


class _GenerationBoundOperations:
    __slots__ = ("_lease", "_name")

    def __init__(
        self,
        lease: RuntimeBindingLease[Mapping[str, object]],
        name: str,
    ) -> None:
        self._lease = lease
        self._name = name

    def __getattr__(self, name: str) -> object:
        target = self._lease.require()[self._name]
        try:
            return getattr(target, name)
        except AttributeError as exc:
            raise AttributeError(
                f"Workspace operation facet {self._name!r} has no attribute {name!r}"
            ) from exc


__all__ = ["GenerationBoundOperationSet"]
