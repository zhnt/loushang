from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Literal, TextIO

from loushang.tui.input import InputEvent
from loushang.tui.keyboard_protocol import KeyboardProtocolController
from loushang.tui.terminal_capabilities import (
    ImageProtocol,
    TerminalEnvironment,
    TerminalRuntimeCapabilities,
    detect_terminal_capabilities,
    terminal_environment_from_env,
)
from loushang.tui.terminal_image import CellDimensions
from loushang.tui.terminal_input import TerminalInputMode, drain_input, stream_is_tty
from loushang.tui.terminal_platform import (
    APPLE_TERMINAL_SHIFT_ENTER_SEQUENCE,
    DefaultTerminalPlatformAdapter,
    TerminalPlatformAdapter,
)

TerminalModeFactory = Callable[[TextIO, TextIO, TerminalRuntimeCapabilities], AbstractContextManager[object]]
DrainInputFunc = Callable[..., str]
MOUSE_ENABLE_SEQUENCES = ("\x1b[?1002h", "\x1b[?1006h")
MOUSE_DISABLE_SEQUENCES = ("\x1b[?1006l", "\x1b[?1002l")
ALTERNATE_SCREEN_ENABLE_SEQUENCE = "\x1b[?1049h"
ALTERNATE_SCREEN_DISABLE_SEQUENCE = "\x1b[?1049l"
KeyboardProtocolRuntimeState = Literal["none", "querying", "kitty", "modify_other_keys"]


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


@dataclass(frozen=True, slots=True)
class TerminalSessionDiagnostics:
    keyboard_protocol_state: KeyboardProtocolRuntimeState
    mouse_mode_active: bool
    cell_size: CellDimensions | None
    image_protocol: ImageProtocol
    alternate_screen: bool
    tmux_passthrough: bool
    windows_vt_input: bool
    windows_vt_output: bool
    windows_console_mode_active: bool
    windows_output_mode_active: bool
    termux_session: bool
    is_multiplexer: bool
    inside_ssh: bool


@dataclass(slots=True)
class TerminalSession:
    stdin: TextIO
    stdout: TextIO
    environment: TerminalEnvironment | None = None
    capabilities: TerminalRuntimeCapabilities | None = None
    mode_factory: TerminalModeFactory | None = None
    now_ms: Callable[[], int] = _monotonic_ms
    drain_input_func: DrainInputFunc = drain_input
    drain_on_exit: bool = True
    drain_limit: int = 4096
    drain_idle_timeout: float = 0.05
    drain_max_duration: float = 1.0
    platform_adapter: TerminalPlatformAdapter | None = None
    cell_size: CellDimensions | None = None
    _mode: AbstractContextManager[object] | None = field(default=None, init=False, repr=False)
    _keyboard_controller: KeyboardProtocolController | None = field(default=None, init=False, repr=False)
    _mouse_mode_active: bool = field(default=False, init=False, repr=False)
    _windows_vt_input_active: bool = field(default=False, init=False, repr=False)
    _windows_vt_output_active: bool = field(default=False, init=False, repr=False)
    _windows_console_mode_active: bool = field(default=False, init=False, repr=False)
    _windows_output_mode_active: bool = field(default=False, init=False, repr=False)
    _entered: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> TerminalSession:
        if self.environment is None:
            self.environment = terminal_environment_from_env()
        if self.capabilities is None:
            self.capabilities = detect_terminal_capabilities(self.environment)
        if self.platform_adapter is None:
            self.platform_adapter = DefaultTerminalPlatformAdapter()
        if self.capabilities.windows_vt_input and self._control_writes_allowed():
            self._windows_vt_output_active = _enable_windows_vt_output(
                self.platform_adapter, self.stdout
            )
            self._windows_output_mode_active = self._windows_vt_output_active
        if self._control_writes_allowed() and self.capabilities.alternate_screen:
            self._write_sequences((ALTERNATE_SCREEN_ENABLE_SEQUENCE,))
        factory = self.mode_factory or _default_mode_factory
        self._mode = factory(self.stdin, self.stdout, self.capabilities)
        self._mode.__enter__()
        if self.capabilities.windows_vt_input and self._control_writes_allowed():
            self._windows_vt_input_active = bool(self.platform_adapter.enable_windows_vt_input(self.stdin))
            self._windows_console_mode_active = _windows_console_mode_configured(self.platform_adapter)
        if self._control_writes_allowed() and self.capabilities.keyboard_protocol_strategy != "legacy":
            self._keyboard_controller = KeyboardProtocolController(strategy=self.capabilities.keyboard_protocol_strategy)
            self._write_sequences(self._keyboard_controller.startup_sequences(now_ms=self.now_ms()))
        if self._control_writes_allowed() and self.capabilities.enable_mouse:
            self._write_sequences(MOUSE_ENABLE_SEQUENCES)
            self._mouse_mode_active = True
        if self._control_writes_allowed() and self.capabilities.query_cell_size:
            self._write_sequences(("\x1b[16t",))
        self._entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if not self._entered or self._mode is None:
            return False
        self._entered = False
        if self._keyboard_controller is not None:
            self._write_sequences(self._keyboard_controller.shutdown_sequences())
        if self._mouse_mode_active:
            self._write_sequences(MOUSE_DISABLE_SEQUENCES)
            self._mouse_mode_active = False
        if self.drain_on_exit and self._control_writes_allowed():
            self.drain_input_func(
                self.stdin,
                max_bytes=self.drain_limit,
                idle_timeout=self.drain_idle_timeout,
                max_duration=self.drain_max_duration,
            )
        if self._windows_console_mode_active and self.platform_adapter is not None:
            self.platform_adapter.disable_windows_vt_input()
            self._windows_console_mode_active = False
            self._windows_vt_input_active = False
        try:
            suppress = self._mode.__exit__(exc_type, exc, traceback)
        finally:
            if self.capabilities is not None and self.capabilities.alternate_screen and self._control_writes_allowed():
                self._write_sequences((ALTERNATE_SCREEN_DISABLE_SEQUENCE,))
            if self._windows_output_mode_active and self.platform_adapter is not None:
                _disable_windows_vt_output(self.platform_adapter)
                self._windows_output_mode_active = False
                self._windows_vt_output_active = False
        return suppress

    def consume_control_events(self, events: tuple[InputEvent, ...]) -> None:
        if self._keyboard_controller is not None:
            self._write_sequences(self._keyboard_controller.consume_control_events(events))
        for event in events:
            if event.kind == "signal" and event.signal == "cell_size":
                self._consume_cell_size(event.text)

    def flush_keyboard_protocol_fallback_if_due(self) -> bool:
        if self._keyboard_controller is None:
            return False
        return self._write_sequences(self._keyboard_controller.fallback_sequences_if_due(now_ms=self.now_ms()))

    def next_wakeup_delay_ms(self) -> int | None:
        if self._keyboard_controller is None:
            return None
        return self._keyboard_controller.next_fallback_delay_ms(now_ms=self.now_ms())

    def normalize_input_chunk(self, data: str) -> str:
        capabilities = self.capabilities or TerminalRuntimeCapabilities()
        if (
            data == "\r"
            and capabilities.apple_terminal_normalization
            and self._platform_adapter().apple_shift_pressed()
        ):
            return APPLE_TERMINAL_SHIFT_ENTER_SEQUENCE
        return data

    def diagnostics(self) -> TerminalSessionDiagnostics:
        capabilities = self.capabilities or TerminalRuntimeCapabilities()
        return TerminalSessionDiagnostics(
            keyboard_protocol_state=self._keyboard_protocol_state(),
            mouse_mode_active=self._mouse_mode_active,
            cell_size=self.cell_size,
            image_protocol=capabilities.image_protocol,
            alternate_screen=capabilities.alternate_screen,
            tmux_passthrough=capabilities.tmux_passthrough,
            windows_vt_input=self._windows_vt_input_active,
            windows_vt_output=self._windows_vt_output_active,
            windows_console_mode_active=self._windows_console_mode_active,
            windows_output_mode_active=self._windows_output_mode_active,
            termux_session=capabilities.termux_session,
            is_multiplexer=capabilities.is_multiplexer,
            inside_ssh=capabilities.inside_ssh,
        )

    def _keyboard_protocol_state(self) -> KeyboardProtocolRuntimeState:
        controller = self._keyboard_controller
        if controller is None:
            return "none"
        if controller.kitty_active:
            return "kitty"
        if controller.modify_other_keys_active:
            return "modify_other_keys"
        return "querying"

    def _control_writes_allowed(self) -> bool:
        return self.mode_factory is not None or stream_is_tty(self.stdin)

    def _write_sequences(self, sequences: tuple[str, ...]) -> bool:
        if not sequences:
            return False
        self.stdout.write("".join(sequences))
        flush = getattr(self.stdout, "flush", None)
        if callable(flush):
            flush()
        return True

    def _consume_cell_size(self, text: str) -> None:
        try:
            height, width = (int(part) for part in text.split(";", 1))
        except ValueError:
            return
        if height <= 0 or width <= 0:
            return
        self.cell_size = CellDimensions(width_px=width, height_px=height)

    def _platform_adapter(self) -> TerminalPlatformAdapter:
        if self.platform_adapter is None:
            self.platform_adapter = DefaultTerminalPlatformAdapter()
        return self.platform_adapter


def _default_mode_factory(
    stdin: TextIO,
    stdout: TextIO,
    capabilities: TerminalRuntimeCapabilities,
) -> AbstractContextManager[object]:
    return TerminalInputMode(
        stdin=stdin,
        stdout=stdout,
        bracketed_paste=capabilities.enable_bracketed_paste,
        focus_events=capabilities.enable_focus_events,
        keyboard_protocols=False,
        drain_on_exit=False,
    )


def _windows_console_mode_configured(adapter: TerminalPlatformAdapter | None) -> bool:
    if adapter is None:
        return False
    configured = getattr(adapter, "windows_console_mode_configured", None)
    if callable(configured):
        return bool(configured())
    return False


def _enable_windows_vt_output(adapter: TerminalPlatformAdapter | None, stdout: TextIO) -> bool:
    if adapter is None:
        return False
    enable = getattr(adapter, "enable_windows_vt_output", None)
    if not callable(enable):
        return False
    return bool(enable(stdout))


def _disable_windows_vt_output(adapter: TerminalPlatformAdapter | None) -> None:
    if adapter is None:
        return
    disable = getattr(adapter, "disable_windows_vt_output", None)
    if callable(disable):
        disable()


__all__ = [
    "ALTERNATE_SCREEN_DISABLE_SEQUENCE",
    "ALTERNATE_SCREEN_ENABLE_SEQUENCE",
    "DrainInputFunc",
    "MOUSE_DISABLE_SEQUENCES",
    "MOUSE_ENABLE_SEQUENCES",
    "KeyboardProtocolRuntimeState",
    "TerminalModeFactory",
    "TerminalPlatformAdapter",
    "TerminalSession",
    "TerminalSessionDiagnostics",
]
