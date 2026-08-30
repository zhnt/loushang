"""Exact rollback receipt for one scoped package-source settings mutation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

PackageSourceMutationState = Literal["active", "committed", "rolled_back"]


class PackageSourceSettingsMutation:
    """Own the exact prior settings-layer state until publication commits."""

    def __init__(
        self,
        *,
        source: str,
        scope: str,
        changed: bool,
        restore: Callable[[], None],
        validate: Callable[[], None] | None = None,
    ) -> None:
        if not source:
            raise ValueError("Package source mutation requires a source")
        if not scope:
            raise ValueError("Package source mutation requires a scope")
        if not isinstance(changed, bool):
            raise TypeError("Package source mutation changed flag must be a bool")
        if not callable(restore):
            raise TypeError("Package source mutation restore callback is invalid")
        if validate is not None and not callable(validate):
            raise TypeError("Package source mutation validation callback is invalid")
        self.source = source
        self.scope = scope
        self.changed = changed
        self._restore = restore
        self._validate = validate or (lambda: None)
        self._state: PackageSourceMutationState = "active"

    @property
    def state(self) -> PackageSourceMutationState:
        return self._state

    def commit(self) -> None:
        if self._state != "active":
            raise RuntimeError("Package source mutation is already finalized")
        self._validate()
        self._state = "committed"

    def rollback(self) -> None:
        if self._state == "rolled_back":
            return
        if self._state != "active":
            raise RuntimeError("Committed package source mutation cannot roll back")
        if self.changed:
            self._restore()
        self._state = "rolled_back"


__all__ = ["PackageSourceMutationState", "PackageSourceSettingsMutation"]
