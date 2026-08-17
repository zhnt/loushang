"""Product-neutral sequencing and presentation for terminal debug actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harnesstui.conversation.run_context import StableEmit

EnableResultT = TypeVar("EnableResultT")
DebugScopes = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DebugActionCopy(Generic[EnableResultT]):
    """Product-owned status copy and stable-write labels."""

    enabled_status: Callable[[EnableResultT, DebugScopes], str]
    disabled_status: str
    enabled_emit_label: str
    disabled_emit_label: str


@dataclass(frozen=True, slots=True)
class DebugActionPorts(Generic[EnableResultT]):
    """Product effects used by the shared debug action sequence."""

    enable: Callable[[DebugScopes], EnableResultT]
    disable: Callable[[], None]
    on_enabled: Callable[[EnableResultT, DebugScopes], None]
    on_disabled: Callable[[], None]
    emit: StableEmit
    render_status: Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DebugActionHandler(Generic[EnableResultT]):
    """Run enable/disable effects, callbacks, and one stable status write."""

    copy: DebugActionCopy[EnableResultT]
    ports: DebugActionPorts[EnableResultT]

    async def handle(self, *, enabled: bool, scopes: DebugScopes) -> None:
        if not enabled:
            self.ports.disable()
            self.ports.on_disabled()
            await self.ports.emit(
                lambda: self.ports.render_status(self.copy.disabled_status),
                label=self.copy.disabled_emit_label,
            )
            return

        result = self.ports.enable(scopes)
        self.ports.on_enabled(result, scopes)
        await self.ports.emit(
            lambda: self.ports.render_status(self.copy.enabled_status(result, scopes)),
            label=self.copy.enabled_emit_label,
        )


__all__ = [
    "DebugActionCopy",
    "DebugActionHandler",
    "DebugActionPorts",
    "DebugScopes",
]
