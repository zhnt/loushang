from __future__ import annotations

from io import StringIO
from typing import Literal

from loushang.tui.input import InputEvent
from loushang.tui.terminal_backends import NativeTerminalPlatform
from loushang.tui.terminal_capabilities import TerminalRuntimeCapabilities
from loushang.tui.terminal_image import CellDimensions
from loushang.tui.terminal_session import TerminalSession


def test_terminal_session_is_noop_for_non_tty_streams() -> None:
    stdout = StringIO()

    with TerminalSession(stdin=StringIO(), stdout=stdout) as session:
        assert isinstance(session.capabilities, TerminalRuntimeCapabilities)

    assert stdout.getvalue() == ""


def test_terminal_session_uses_context_manager_mode_factory() -> None:
    mode = _RecordingMode()
    stdout = StringIO()

    with TerminalSession(stdin=StringIO(), stdout=stdout, mode_factory=lambda _stdin, _stdout, _capabilities: mode):
        assert mode.entered == 1

    assert mode.exited == 1


def test_terminal_session_cleanup_is_idempotent() -> None:
    mode = _RecordingMode()
    session = TerminalSession(stdin=StringIO(), stdout=StringIO(), mode_factory=lambda _stdin, _stdout, _capabilities: mode)

    session.__enter__()
    session.__exit__(None, None, None)
    session.__exit__(None, None, None)

    assert mode.entered == 1
    assert mode.exited == 1


def test_terminal_session_owns_exit_drain_after_runtime_protocol_cleanup() -> None:
    stdout = StringIO()
    calls: list[str] = []
    capabilities = TerminalRuntimeCapabilities(keyboard_protocol_strategy="kitty_then_modify_other_keys")

    def drain(_stdin: object, *, max_bytes: int, idle_timeout: float, max_duration: float) -> str:
        calls.append(f"drain:{max_bytes}:{idle_timeout}:{max_duration}")
        return "late-release"

    with TerminalSession(
        stdin=StringIO("late-release"),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _WritingMode(_stdout, calls),
        now_ms=lambda: 1_000,
        drain_input_func=drain,
    ) as session:
        session.consume_control_events((InputEvent(kind="signal", signal="kitty_protocol", text="7"),))

    output = stdout.getvalue()
    assert calls == ["mode:enter", "drain:4096:0.05:1.0", "mode:exit"]
    assert output.index("\x1b[<u") < output.index("\x1b[?1004l")


def test_terminal_session_disables_modify_other_keys_before_exit_drain() -> None:
    stdout = StringIO()
    drain_observations: list[bool] = []
    now = _FakeClock(1_000)
    capabilities = TerminalRuntimeCapabilities(keyboard_protocol_strategy="kitty_then_modify_other_keys")

    def drain(_stdin: object, *, max_bytes: int, idle_timeout: float, max_duration: float) -> str:
        del max_bytes, idle_timeout, max_duration
        drain_observations.append("\x1b[>4;0m" in stdout.getvalue())
        return ""

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        now_ms=now,
        drain_input_func=drain,
    ) as session:
        now.value = 1_150
        assert session.flush_keyboard_protocol_fallback_if_due() is True

    assert drain_observations == [True]


def test_terminal_session_can_enable_and_disable_alternate_screen() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities(alternate_screen=True)

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
    ):
        pass

    output = stdout.getvalue()
    assert output.startswith("\x1b[?1049h")
    assert output.endswith("\x1b[?1049l")


def test_terminal_session_queries_cell_size_when_capability_enabled() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities(query_cell_size=True)

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
    ):
        pass

    assert "\x1b[16t" in stdout.getvalue()


def test_terminal_session_skips_cell_size_query_when_capability_disabled() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities(query_cell_size=False)

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
    ):
        pass

    assert "\x1b[16t" not in stdout.getvalue()


def test_terminal_session_consumes_cell_size_control_event() -> None:
    session = TerminalSession(stdin=StringIO(), stdout=StringIO())

    session.consume_control_events((InputEvent(kind="signal", signal="cell_size", text="18;9"),))

    assert session.cell_size == CellDimensions(width_px=9, height_px=18)


def test_terminal_session_starts_keyboard_protocol_without_immediate_fallback() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities(keyboard_protocol_strategy="kitty_then_modify_other_keys")

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        now_ms=lambda: 1_000,
    ):
        pass

    output = stdout.getvalue()
    assert "\x1b[?u" in output
    assert "\x1b[>4;2m" not in output


def test_terminal_session_consumes_kitty_protocol_response_and_disables_kitty_on_exit() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities(keyboard_protocol_strategy="kitty_then_modify_other_keys")

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        now_ms=lambda: 1_000,
    ) as session:
        session.consume_control_events((InputEvent(kind="signal", signal="kitty_protocol", text="7"),))

    output = stdout.getvalue()
    assert "\x1b[?u" in output
    assert "\x1b[>7u" in output
    assert "\x1b[<u" in output
    assert "\x1b[>4;0m" not in output


def test_terminal_session_falls_back_to_modify_other_keys_after_deadline_and_disables_it_on_exit() -> None:
    stdout = StringIO()
    now = _FakeClock(1_000)
    capabilities = TerminalRuntimeCapabilities(keyboard_protocol_strategy="kitty_then_modify_other_keys")

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        now_ms=now,
    ) as session:
        assert session.flush_keyboard_protocol_fallback_if_due() is False
        now.value = 1_150
        assert session.flush_keyboard_protocol_fallback_if_due() is True

    output = stdout.getvalue()
    assert "\x1b[?u" in output
    assert "\x1b[>4;2m" in output
    assert "\x1b[>4;0m" in output
    assert "\x1b[<u" not in output


def test_terminal_session_enables_mouse_tracking_when_application_owns_selection() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities(mouse_selection_owner="application")

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
    ):
        pass

    output = stdout.getvalue()
    assert "\x1b[?1002h" in output
    assert "\x1b[?1006h" in output
    assert "\x1b[?1006l" in output
    assert "\x1b[?1002l" in output


def test_terminal_session_preserves_legacy_enable_mouse_compatibility() -> None:
    stdout = StringIO()

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=TerminalRuntimeCapabilities(enable_mouse=True),
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
    ):
        pass

    assert all(
        sequence in stdout.getvalue()
        for sequence in ("\x1b[?1002h", "\x1b[?1006h")
    )


def test_terminal_session_disables_mouse_mode_before_exit_drain() -> None:
    stdout = StringIO()
    drain_observations: list[bool] = []
    capabilities = TerminalRuntimeCapabilities(enable_mouse=True)

    def drain(_stdin: object, *, max_bytes: int, idle_timeout: float, max_duration: float) -> str:
        del max_bytes, idle_timeout, max_duration
        drain_observations.append("\x1b[?1006l\x1b[?1002l" in stdout.getvalue())
        return ""

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        drain_input_func=drain,
    ):
        pass

    assert drain_observations == [True]


def test_terminal_session_keeps_mouse_mode_off_by_default() -> None:
    stdout = StringIO()
    capabilities = TerminalRuntimeCapabilities()

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
    ) as session:
        diagnostics = session.diagnostics()

    output = stdout.getvalue()
    assert "\x1b[?1002h" not in output
    assert "\x1b[?1006h" not in output
    assert "\x1b[?1006l" not in output
    assert "\x1b[?1002l" not in output
    assert diagnostics.mouse_selection_owner == "terminal"


def test_terminal_session_diagnostics_report_runtime_state() -> None:
    stdout = StringIO()
    now = _FakeClock(1_000)
    platform = _RecordingPlatformAdapter(windows_enabled=True)
    capabilities = TerminalRuntimeCapabilities(
        image_protocol="kitty",
        keyboard_protocol_strategy="kitty_then_modify_other_keys",
        enable_mouse=True,
        alternate_screen=True,
        tmux_passthrough=True,
        windows_vt_input=True,
        termux_session=True,
        is_multiplexer=True,
        inside_ssh=True,
    )

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=platform,
        now_ms=now,
    ) as session:
        session.consume_control_events(
            (
                InputEvent(kind="signal", signal="kitty_protocol", text="7"),
                InputEvent(kind="signal", signal="cell_size", text="18;9"),
            )
        )
        diagnostics = session.diagnostics()

    assert diagnostics.keyboard_protocol_state == "kitty"
    assert diagnostics.mouse_mode_active is True
    assert diagnostics.mouse_selection_owner == "application"
    assert diagnostics.cell_size == CellDimensions(width_px=9, height_px=18)
    assert diagnostics.image_protocol == "kitty"
    assert diagnostics.alternate_screen is True
    assert diagnostics.tmux_passthrough is True
    assert diagnostics.windows_vt_input is True
    assert diagnostics.windows_vt_output is True
    assert diagnostics.termux_session is True
    assert diagnostics.is_multiplexer is True
    assert diagnostics.inside_ssh is True
    assert platform.calls == [
        "enable_windows_vt_output",
        "enable_windows_vt_input",
        "disable_windows_vt_input",
        "disable_windows_vt_output",
    ]


def test_terminal_session_diagnostics_report_modify_other_keys_fallback() -> None:
    now = _FakeClock(1_000)
    capabilities = TerminalRuntimeCapabilities(keyboard_protocol_strategy="kitty_then_modify_other_keys")

    with TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        now_ms=now,
    ) as session:
        now.value = 1_150
        session.flush_keyboard_protocol_fallback_if_due()
        diagnostics = session.diagnostics()

    assert diagnostics.keyboard_protocol_state == "modify_other_keys"
    assert diagnostics.mouse_mode_active is False


def test_terminal_session_enables_and_disables_windows_vt_input_when_adapter_accepts() -> None:
    platform = _RecordingPlatformAdapter(windows_enabled=True)
    capabilities = TerminalRuntimeCapabilities(windows_vt_input=True)

    with TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=platform,
    ) as session:
        assert session.diagnostics().windows_vt_input is True
        assert session.diagnostics().windows_vt_output is True

    assert platform.calls == [
        "enable_windows_vt_output",
        "enable_windows_vt_input",
        "disable_windows_vt_input",
        "disable_windows_vt_output",
    ]


def test_terminal_session_reports_windows_vt_input_inactive_when_adapter_declines() -> None:
    platform = _RecordingPlatformAdapter(windows_enabled=False)
    capabilities = TerminalRuntimeCapabilities(windows_vt_input=True)

    with TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=platform,
    ) as session:
        assert session.diagnostics().windows_vt_input is False

    assert platform.calls == ["enable_windows_vt_output", "enable_windows_vt_input"]


def test_terminal_session_restores_windows_console_mode_when_vt_input_declines() -> None:
    platform = _RecordingPlatformAdapter(windows_enabled=False, windows_configured=True)
    capabilities = TerminalRuntimeCapabilities(windows_vt_input=True)

    with TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=platform,
    ) as session:
        diagnostics = session.diagnostics()
        assert diagnostics.windows_vt_input is False
        assert diagnostics.windows_console_mode_active is True

    assert platform.calls == [
        "enable_windows_vt_output",
        "enable_windows_vt_input",
        "disable_windows_vt_input",
    ]


def test_terminal_session_enables_windows_vt_output_before_terminal_mode_writes() -> None:
    stdout = StringIO()
    calls: list[str] = []
    platform = _RecordingPlatformAdapter(windows_enabled=True)
    capabilities = TerminalRuntimeCapabilities(windows_vt_input=True)

    with TerminalSession(
        stdin=StringIO(),
        stdout=stdout,
        capabilities=capabilities,
        mode_factory=lambda _stdin, output, _capabilities: _WritingMode(output, calls),
        platform_adapter=platform,
    ):
        pass

    assert platform.calls == [
        "enable_windows_vt_output",
        "enable_windows_vt_input",
        "disable_windows_vt_input",
        "disable_windows_vt_output",
    ]
    assert calls == ["mode:enter", "mode:exit"]


def test_terminal_session_uses_native_ports_instead_of_legacy_platform_names() -> (
    None
):
    console_mode = _RecordingConsoleMode()
    modifier_keys = _RecordingModifierKeys(shift_pressed=True)
    native_platform = NativeTerminalPlatform(
        console_mode=console_mode,
        modifier_keys=modifier_keys,
    )
    capabilities = TerminalRuntimeCapabilities(
        windows_vt_input=True,
        apple_terminal_normalization=True,
    )

    with TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=_UnexpectedPlatformAdapter(),
        native_platform=native_platform,
    ) as session:
        assert session.normalize_input_chunk("\r") == "\x1b[13;2u"

    assert console_mode.calls == [
        "enable_output",
        "enable_input:True",
        "mode_configured",
        "disable_input",
        "disable_output",
    ]
    assert modifier_keys.calls == ["shift_pressed"]


def test_terminal_session_releases_native_selection_when_application_owns_mouse() -> None:
    console_mode = _RecordingConsoleMode()
    native_platform = NativeTerminalPlatform(
        console_mode=console_mode,
        modifier_keys=_RecordingModifierKeys(shift_pressed=False),
    )
    capabilities = TerminalRuntimeCapabilities(
        windows_vt_input=True,
        mouse_selection_owner="application",
    )

    with TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        native_platform=native_platform,
    ):
        pass

    assert console_mode.calls == [
        "enable_output",
        "enable_input:False",
        "mode_configured",
        "disable_input",
        "disable_output",
    ]


def test_terminal_session_normalizes_apple_terminal_shift_enter_before_input_parsing() -> None:
    platform = _RecordingPlatformAdapter(shift_pressed=True)
    capabilities = TerminalRuntimeCapabilities(apple_terminal_normalization=True)
    session = TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=platform,
    )

    assert session.normalize_input_chunk("\r") == "\x1b[13;2u"
    assert platform.calls == ["apple_shift_pressed"]


def test_terminal_session_leaves_return_unchanged_when_apple_shift_is_not_pressed() -> None:
    platform = _RecordingPlatformAdapter(shift_pressed=False)
    capabilities = TerminalRuntimeCapabilities(apple_terminal_normalization=True)
    session = TerminalSession(
        stdin=StringIO(),
        stdout=StringIO(),
        capabilities=capabilities,
        mode_factory=lambda _stdin, _stdout, _capabilities: _RecordingMode(),
        platform_adapter=platform,
    )

    assert session.normalize_input_chunk("\r") == "\r"


class _RecordingMode:
    def __init__(self, calls: list[str] | None = None) -> None:
        self.calls = calls
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> _RecordingMode:
        self.entered += 1
        if self.calls is not None:
            self.calls.append("mode:enter")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        del exc_type, exc, traceback
        self.exited += 1
        if self.calls is not None:
            self.calls.append("mode:exit")
        return False


class _WritingMode(_RecordingMode):
    def __init__(self, stdout: StringIO, calls: list[str] | None = None) -> None:
        super().__init__(calls)
        self.stdout = stdout

    def __enter__(self) -> _WritingMode:
        super().__enter__()
        self.stdout.write("\x1b[?1004h")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        self.stdout.write("\x1b[?1004l")
        return super().__exit__(exc_type, exc, traceback)


class _FakeClock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class _RecordingPlatformAdapter:
    def __init__(
        self,
        *,
        windows_enabled: bool = False,
        windows_configured: bool | None = None,
        shift_pressed: bool = False,
    ) -> None:
        self.windows_enabled = windows_enabled
        self.windows_configured = windows_enabled if windows_configured is None else windows_configured
        self.shift_pressed = shift_pressed
        self.calls: list[str] = []

    def enable_windows_vt_output(self, stdout: object) -> bool:
        del stdout
        self.calls.append("enable_windows_vt_output")
        return self.windows_enabled

    def disable_windows_vt_output(self) -> None:
        self.calls.append("disable_windows_vt_output")

    def enable_windows_vt_input(self, stdin: object) -> bool:
        del stdin
        self.calls.append("enable_windows_vt_input")
        return self.windows_enabled

    def disable_windows_vt_input(self) -> None:
        self.calls.append("disable_windows_vt_input")

    def windows_console_mode_configured(self) -> bool:
        return self.windows_configured

    def windows_vt_input_active(self) -> bool:
        return self.windows_enabled

    def windows_vt_output_active(self) -> bool:
        return self.windows_enabled

    def apple_shift_pressed(self) -> bool:
        self.calls.append("apple_shift_pressed")
        return self.shift_pressed


class _RecordingConsoleMode:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def enable_vt_input(
        self,
        stdin: object,
        *,
        preserve_native_selection: bool = False,
    ) -> bool:
        del stdin
        self.calls.append(f"enable_input:{preserve_native_selection}")
        return True

    def disable_vt_input(self) -> None:
        self.calls.append("disable_input")

    def enable_vt_output(self, stdout: object) -> bool:
        del stdout
        self.calls.append("enable_output")
        return True

    def disable_vt_output(self) -> None:
        self.calls.append("disable_output")

    def mode_configured(self) -> bool:
        self.calls.append("mode_configured")
        return True

    def vt_input_active(self) -> bool:
        return True

    def vt_output_active(self) -> bool:
        return True


class _RecordingModifierKeys:
    def __init__(self, *, shift_pressed: bool) -> None:
        self._shift_pressed = shift_pressed
        self.calls: list[str] = []

    def shift_pressed(self) -> bool:
        self.calls.append("shift_pressed")
        return self._shift_pressed


class _UnexpectedPlatformAdapter:
    def __getattribute__(self, name: str) -> object:
        if name.startswith("__"):
            return super().__getattribute__(name)
        raise AssertionError(f"legacy platform adapter was used: {name}")
