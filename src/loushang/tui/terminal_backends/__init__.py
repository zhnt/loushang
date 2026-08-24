"""Platform-owned terminal transport implementations.

Shared TUI input semantics stay in :mod:`loushang.tui.terminal_input`. Modules
in this package own operating-system APIs and must not depend on composer,
conversation, or product code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol


class NativeTerminalInputBackend(Protocol):
    """Operating-system boundary used only after a stream is known to be a TTY."""

    async def read_chunk(self, stdin: Any) -> str: ...

    def read_chunk_blocking(self, stdin: Any) -> str: ...

    def drain(
        self,
        stdin: Any,
        *,
        max_bytes: int,
        idle_timeout: float,
        max_duration: float | None,
        now: Callable[[], float],
    ) -> str: ...


class NativeTerminalModeLease(Protocol):
    """One entered native terminal mode that can restore its original state."""

    def restore(self) -> None: ...


class NativeTerminalModeFactory(Protocol):
    """Create an entered mode lease, or decline unsupported terminal streams."""

    def open(self, stdin: Any) -> NativeTerminalModeLease | None: ...


class NativeConsoleMode(Protocol):
    """Optional native console mode lifecycle for one terminal session."""

    def enable_vt_input(
        self,
        stdin: object,
        *,
        preserve_native_selection: bool = False,
    ) -> bool: ...

    def disable_vt_input(self) -> None: ...

    def enable_vt_output(self, stdout: object) -> bool: ...

    def disable_vt_output(self) -> None: ...

    def mode_configured(self) -> bool: ...

    def vt_input_active(self) -> bool: ...

    def vt_output_active(self) -> bool: ...


class NativeModifierKeys(Protocol):
    """Optional native modifier-key state probe."""

    def shift_pressed(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class NativeTerminalPlatform:
    """Small cohesive native ports selected for one host platform."""

    console_mode: NativeConsoleMode
    modifier_keys: NativeModifierKeys


class NeutralConsoleMode:
    """No-op console mode port for platforms without Win32-style hooks."""

    def enable_vt_input(
        self,
        stdin: object,
        *,
        preserve_native_selection: bool = False,
    ) -> bool:
        del stdin, preserve_native_selection
        return False

    def disable_vt_input(self) -> None:
        pass

    def enable_vt_output(self, stdout: object) -> bool:
        del stdout
        return False

    def disable_vt_output(self) -> None:
        pass

    def mode_configured(self) -> bool:
        return False

    def vt_input_active(self) -> bool:
        return False

    def vt_output_active(self) -> bool:
        return False


class NeutralModifierKeys:
    """No-op modifier port for platforms without a native key-state probe."""

    def shift_pressed(self) -> bool:
        return False


@cache
def native_terminal_input_backend(platform_name: str) -> NativeTerminalInputBackend:
    """Select one native backend without importing it on other platforms."""

    if platform_name == "win32":
        from loushang.tui.terminal_backends.windows import WINDOWS_CONSOLE_INPUT

        return WINDOWS_CONSOLE_INPUT
    from loushang.tui.terminal_backends.posix import POSIX_TERMINAL_INPUT

    return POSIX_TERMINAL_INPUT


@cache
def native_terminal_mode_factory(platform_name: str) -> NativeTerminalModeFactory:
    """Select native mode ownership independently from input decoding."""

    if platform_name == "win32":
        from loushang.tui.terminal_backends.windows import WINDOWS_TERMINAL_MODE

        return WINDOWS_TERMINAL_MODE
    from loushang.tui.terminal_backends.posix import POSIX_TERMINAL_MODE

    return POSIX_TERMINAL_MODE


def native_terminal_platform(platform_name: str) -> NativeTerminalPlatform:
    """Compose small native ports for one terminal session."""

    if platform_name == "win32":
        from loushang.tui.terminal_backends.windows import WindowsConsoleMode

        return NativeTerminalPlatform(
            console_mode=WindowsConsoleMode(),
            modifier_keys=NeutralModifierKeys(),
        )
    if platform_name == "darwin":
        from loushang.tui.terminal_backends.darwin import DarwinModifierKeys

        return NativeTerminalPlatform(
            console_mode=NeutralConsoleMode(),
            modifier_keys=DarwinModifierKeys(),
        )
    return NativeTerminalPlatform(
        console_mode=NeutralConsoleMode(),
        modifier_keys=NeutralModifierKeys(),
    )


__all__ = [
    "NativeConsoleMode",
    "NativeModifierKeys",
    "NativeTerminalInputBackend",
    "NativeTerminalModeFactory",
    "NativeTerminalModeLease",
    "NativeTerminalPlatform",
    "NeutralConsoleMode",
    "NeutralModifierKeys",
    "native_terminal_input_backend",
    "native_terminal_mode_factory",
    "native_terminal_platform",
]
