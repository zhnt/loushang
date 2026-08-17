from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

B = TypeVar("B")
S = TypeVar("S")
R = TypeVar("R")

ExtensionRuntimeOperation = Literal[
    "resource_refresh",
    "runtime_bind",
    "runtime_refresh",
    "session_start",
    "session_refresh",
]
BuildBindings = Callable[[], B]
BindRuntime = Callable[[B], object]
InvalidateContexts = Callable[[str], object]
EmitEvent = Callable[[object], object | Awaitable[object]]
RefreshResources = Callable[[], object | Awaitable[object]]
ReloadGeneration = Callable[[B], object | Awaitable[object]]
RecordFailure = Callable[[ExtensionRuntimeOperation, Exception], None]
SyncDiagnostics = Callable[[], object]


@dataclass
class ExtensionRuntimeCoordinator(Generic[B, S, R]):
    """Coordinate extension binding, refresh hooks, and context invalidation."""

    build_bindings: BuildBindings[B]
    bind_runtime: BindRuntime[B]
    refresh_runtime: BindRuntime[B]
    emit_session_start: Callable[[S], object | Awaitable[object]]
    emit_session_refresh: Callable[[R], object | Awaitable[object]]
    refresh_resources: RefreshResources
    record_failure: RecordFailure
    sync_diagnostics: SyncDiagnostics
    invalidate_contexts_driver: InvalidateContexts | None = None
    reload_generation: ReloadGeneration[B] | None = None
    _refreshing: bool = False

    @property
    def is_refreshing(self) -> bool:
        return self._refreshing

    async def bind(
        self,
        event: S,
        *,
        reload: bool = False,
        stale_context_message: str = "Runtime context is stale after reload.",
    ) -> bool:
        if reload:
            if self.reload_generation is not None:
                try:
                    bindings = self.build_bindings()
                except Exception as exc:
                    self.record_failure("runtime_bind", exc)
                    return False
                try:
                    refreshed = self.reload_generation(bindings)
                    if inspect.isawaitable(refreshed):
                        await refreshed
                except Exception as exc:
                    self.record_failure("resource_refresh", exc)
                    return False
                return await self._emit_start(event)
            self.invalidate_contexts(stale_context_message)
            try:
                refreshed = self.refresh_resources()
                if inspect.isawaitable(refreshed):
                    await refreshed
            except Exception as exc:
                self.record_failure("resource_refresh", exc)
                return False
        if not self.bind_bindings():
            return False
        return await self._emit_start(event)

    async def _emit_start(self, event: S) -> bool:
        try:
            emitted = self.emit_session_start(event)
            if inspect.isawaitable(emitted):
                await emitted
        except Exception as exc:
            self.record_failure("session_start", exc)
        self.sync_diagnostics()
        return True

    def bind_bindings(self) -> bool:
        try:
            self.bind_runtime(self.build_bindings())
        except Exception as exc:
            self.record_failure("runtime_bind", exc)
            return False
        return True

    async def refresh(self, event: R) -> bool:
        if not self.refresh_bindings():
            return False
        self._refreshing = True
        try:
            emitted = self.emit_session_refresh(event)
            if inspect.isawaitable(emitted):
                await emitted
        except Exception as exc:
            self.record_failure("session_refresh", exc)
        finally:
            self._refreshing = False
        self.sync_diagnostics()
        return True

    def refresh_bindings(self) -> bool:
        try:
            self.refresh_runtime(self.build_bindings())
        except Exception as exc:
            self.record_failure("runtime_refresh", exc)
            return False
        return True

    def invalidate_contexts(self, message: str) -> None:
        if self.invalidate_contexts_driver is not None:
            self.invalidate_contexts_driver(message)


__all__ = [
    "ExtensionRuntimeCoordinator",
    "ExtensionRuntimeOperation",
    "RecordFailure",
]
