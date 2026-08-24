from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol

from loushang.tui.terminal_backends import (
    NativeConsoleMode,
    NativeModifierKeys,
    NativeTerminalPlatform,
    native_terminal_platform,
)

APPLE_TERMINAL_SHIFT_ENTER_SEQUENCE = "\x1b[13;2u"


class TerminalPlatformAdapter(Protocol):
    def enable_windows_vt_input(self, stdin: object) -> bool: ...

    def disable_windows_vt_input(self) -> None: ...

    def enable_windows_vt_output(self, stdout: object) -> bool: ...

    def disable_windows_vt_output(self) -> None: ...

    def windows_console_mode_configured(self) -> bool: ...

    def windows_vt_input_active(self) -> bool: ...

    def windows_vt_output_active(self) -> bool: ...

    def apple_shift_pressed(self) -> bool: ...


class DefaultTerminalPlatformAdapter:
    """Stable public facade delegating platform calls to small native ports."""

    def __init__(
        self, platform: NativeTerminalPlatform | None = None
    ) -> None:
        self._platform = (
            platform
            if platform is not None
            else native_terminal_platform(sys.platform)
        )

    def enable_windows_vt_input(self, stdin: object) -> bool:
        return self._platform.console_mode.enable_vt_input(stdin)

    def disable_windows_vt_input(self) -> None:
        self._platform.console_mode.disable_vt_input()

    def windows_console_mode_configured(self) -> bool:
        return self._platform.console_mode.mode_configured()

    def windows_vt_input_active(self) -> bool:
        return self._platform.console_mode.vt_input_active()

    def enable_windows_vt_output(self, stdout: object) -> bool:
        return self._platform.console_mode.enable_vt_output(stdout)

    def disable_windows_vt_output(self) -> None:
        self._platform.console_mode.disable_vt_output()

    def windows_vt_output_active(self) -> bool:
        return self._platform.console_mode.vt_output_active()

    def apple_shift_pressed(self) -> bool:
        return self._platform.modifier_keys.shift_pressed()


def adapt_terminal_platform_adapter(
    adapter: TerminalPlatformAdapter,
) -> NativeTerminalPlatform:
    """Bridge the legacy public adapter into the neutral native ports."""

    return NativeTerminalPlatform(
        console_mode=_AdapterConsoleMode(adapter),
        modifier_keys=_AdapterModifierKeys(adapter),
    )


@dataclass(frozen=True, slots=True)
class _AdapterConsoleMode(NativeConsoleMode):
    adapter: TerminalPlatformAdapter

    def enable_vt_input(
        self,
        stdin: object,
        *,
        preserve_native_selection: bool = False,
    ) -> bool:
        del preserve_native_selection
        return _call_bool(self.adapter, "enable_windows_vt_input", stdin)

    def disable_vt_input(self) -> None:
        _call_void(self.adapter, "disable_windows_vt_input")

    def enable_vt_output(self, stdout: object) -> bool:
        return _call_bool(self.adapter, "enable_windows_vt_output", stdout)

    def disable_vt_output(self) -> None:
        _call_void(self.adapter, "disable_windows_vt_output")

    def mode_configured(self) -> bool:
        return _call_bool(self.adapter, "windows_console_mode_configured")

    def vt_input_active(self) -> bool:
        return _call_bool(self.adapter, "windows_vt_input_active")

    def vt_output_active(self) -> bool:
        return _call_bool(self.adapter, "windows_vt_output_active")


@dataclass(frozen=True, slots=True)
class _AdapterModifierKeys(NativeModifierKeys):
    adapter: TerminalPlatformAdapter

    def shift_pressed(self) -> bool:
        return _call_bool(self.adapter, "apple_shift_pressed")


def _call_bool(target: object, method_name: str, *args: object) -> bool:
    method = getattr(target, method_name, None)
    if not callable(method):
        return False
    return bool(method(*args))


def _call_void(target: object, method_name: str) -> None:
    method = getattr(target, method_name, None)
    if callable(method):
        method()


__all__ = [
    "APPLE_TERMINAL_SHIFT_ENTER_SEQUENCE",
    "DefaultTerminalPlatformAdapter",
    "TerminalPlatformAdapter",
    "adapt_terminal_platform_adapter",
]
