"""Bind and refresh an extension runtime for one Product session."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.context import SessionRefreshEvent, SessionStartEvent
from loushang.harness.extensions.lifecycle import (
    ExtensionRuntimeCoordinator,
    ExtensionRuntimeOperation,
)

BindingT_contra = TypeVar("BindingT_contra", contravariant=True)
BindingT = TypeVar("BindingT")


class SessionExtensionRuntimePort(Protocol[BindingT_contra]):
    """Extension runtime operations common to a bound Product session."""

    def bind_runtime(self, bindings: BindingT_contra) -> None: ...

    def refresh_runtime(self, bindings: BindingT_contra) -> None: ...

    async def emit_session_start(self, event: SessionStartEvent) -> None: ...

    async def emit_session_refresh(self, event: SessionRefreshEvent) -> None: ...

    def invalidate_contexts(self, message: str) -> None: ...


RefreshResources = Callable[[], object | None]
RecordRuntimeDiagnostic = Callable[[DiagnosticDraft], None]
SyncExtensionDiagnostics = Callable[..., None]


@dataclass
class ExtensionSessionRuntime(Generic[BindingT]):
    """Adapt the neutral extension lifecycle coordinator to one session."""

    extension_runtime: SessionExtensionRuntimePort[BindingT] | None
    build_bindings: Callable[[], BindingT]
    session_start_event: SessionStartEvent
    refresh_resources: RefreshResources
    record_runtime_diagnostic: RecordRuntimeDiagnostic
    sync_extension_diagnostics: SyncExtensionDiagnostics
    reload_generation: Callable[[BindingT], object | Awaitable[object]] | None = None
    _coordinator: (
        ExtensionRuntimeCoordinator[BindingT, SessionStartEvent, SessionRefreshEvent]
        | None
    ) = field(init=False, default=None)

    def __post_init__(self) -> None:
        extension_runtime = self.extension_runtime
        if extension_runtime is None:
            return
        self._coordinator = ExtensionRuntimeCoordinator(
            build_bindings=self.build_bindings,
            bind_runtime=extension_runtime.bind_runtime,
            refresh_runtime=extension_runtime.refresh_runtime,
            emit_session_start=extension_runtime.emit_session_start,
            emit_session_refresh=extension_runtime.emit_session_refresh,
            refresh_resources=self.refresh_resources,
            record_failure=self._record_failure,
            sync_diagnostics=lambda: self.sync_extension_diagnostics(phase="runtime"),
            invalidate_contexts_driver=extension_runtime.invalidate_contexts,
            reload_generation=self.reload_generation,
        )

    @property
    def is_refreshing(self) -> bool:
        coordinator = self._coordinator
        return coordinator is not None and coordinator.is_refreshing

    async def bind(self, *, reason: str) -> None:
        coordinator = self._coordinator
        if coordinator is None:
            return
        await coordinator.bind(
            self._start_event_for_reason(reason),
            reload=reason == "reload",
            stale_context_message="Extension context is stale after extension reload.",
        )

    def bind_bindings(self) -> None:
        if self._coordinator is not None:
            self._coordinator.bind_bindings()

    async def refresh(self, *, reason: str) -> None:
        if self._coordinator is not None:
            await self._coordinator.refresh(SessionRefreshEvent(reason=reason))

    def refresh_bindings(self) -> None:
        if self._coordinator is not None:
            self._coordinator.refresh_bindings()

    def invalidate_contexts(self, message: str) -> None:
        if self._coordinator is not None:
            self._coordinator.invalidate_contexts(message)

    def _record_failure(
        self,
        operation: ExtensionRuntimeOperation,
        error: Exception,
    ) -> None:
        code, prefix = _FAILURE_DIAGNOSTICS[operation]
        self.record_runtime_diagnostic(
            DiagnosticDraft(code=code, message=f"{prefix}: {error}")
        )

    def _start_event_for_reason(self, reason: str) -> SessionStartEvent:
        if self.session_start_event.reason == reason:
            return self.session_start_event
        return SessionStartEvent(reason=reason)


_FAILURE_DIAGNOSTICS: dict[ExtensionRuntimeOperation, tuple[str, str]] = {
    "resource_refresh": (
        "extension_resource_refresh_failed",
        "Extension resource refresh failed",
    ),
    "runtime_bind": (
        "extension_runtime_bind_failed",
        "Extension runtime bind failed",
    ),
    "runtime_refresh": (
        "extension_runtime_refresh_failed",
        "Extension runtime refresh failed",
    ),
    "session_start": (
        "extension_session_start_failed",
        "Extension hook 'session_start' failed",
    ),
    "session_refresh": (
        "extension_session_refresh_failed",
        "Extension hook 'session_refresh' failed",
    ),
}


__all__ = ["ExtensionSessionRuntime", "SessionExtensionRuntimePort"]
