"""Session-owned state and coordination for a bound extension runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ExtensionRuntimeController(Protocol):
    """Narrow controller surface required by the session bridge."""

    @property
    def is_refreshing(self) -> bool: ...

    async def bind(self, *, reason: str) -> None: ...

    def bind_bindings(self) -> None: ...

    async def refresh(self, *, reason: str) -> None: ...

    def refresh_bindings(self) -> None: ...

    def invalidate_contexts(self, message: str) -> None: ...


@dataclass
class AgentSessionExtensionBridge:
    """Expose one stable session boundary around extension runtime rebinding.

    Composition still constructs the runtime controller.  The bridge owns the
    host/UI context visible to extensions and is the only session-side object
    that drives bind, refresh, and context invalidation after assembly.
    """

    _runtime: ExtensionRuntimeController | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _runtime_host: object | None = field(default=None, init=False, repr=False)
    _ui_context: object | None = field(default=None, init=False, repr=False)

    @property
    def runtime_host(self) -> object | None:
        return self._runtime_host

    @property
    def ui_context(self) -> object | None:
        return self._ui_context

    @property
    def is_refreshing(self) -> bool:
        runtime = self._runtime
        return runtime is not None and runtime.is_refreshing

    def attach_runtime(
        self,
        runtime: ExtensionRuntimeController,
    ) -> None:
        """Attach the controller created by session composition exactly once."""

        current = self._runtime
        if current is not None and current is not runtime:
            raise RuntimeError("Extension bridge runtime is already attached")
        self._runtime = runtime

    async def bind(self, *, reason: str) -> None:
        await self._require_runtime().bind(reason=reason)

    def bind_bindings(self) -> None:
        self._require_runtime().bind_bindings()

    async def refresh(self, *, reason: str) -> None:
        await self._require_runtime().refresh(reason=reason)

    def refresh_bindings(self) -> None:
        self._require_runtime().refresh_bindings()

    def set_ui_context(self, ui_context: object | None) -> None:
        self._ui_context = ui_context
        self._refresh_attached_bindings()

    def set_runtime_host(self, runtime_host: object | None) -> None:
        self._runtime_host = runtime_host
        self._refresh_attached_bindings()

    def invalidate_contexts(self, message: str) -> None:
        self._require_runtime().invalidate_contexts(message)

    def _refresh_attached_bindings(self) -> None:
        runtime = self._runtime
        if runtime is not None:
            runtime.refresh_bindings()

    def _require_runtime(self) -> ExtensionRuntimeController:
        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("Extension bridge runtime is not attached")
        return runtime


__all__ = ["AgentSessionExtensionBridge", "ExtensionRuntimeController"]
