"""Host-owned port for exact co-distributed Plugin dependency grants."""

from __future__ import annotations

from typing import Protocol


class PluginDependencyGrantError(ValueError):
    """Stable Product-policy rejection at the dependency-grant boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PluginDependencyGrantResolver(Protocol):
    """Return normalized distribution names for one exact Plugin source."""

    def resolve(
        self,
        *,
        plugin_id: str,
        source_identity: str,
    ) -> tuple[str, ...]: ...


__all__ = [
    "PluginDependencyGrantError",
    "PluginDependencyGrantResolver",
]
