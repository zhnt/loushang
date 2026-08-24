from __future__ import annotations

from dataclasses import dataclass, field

from loushang.tui.terminal_backends import (
    NativeTerminalPlatform,
    NeutralConsoleMode,
    NeutralModifierKeys,
)
from loushang.tui.terminal_platform import (
    DefaultTerminalPlatformAdapter,
    adapt_terminal_platform_adapter,
)


def test_default_terminal_platform_adapter_delegates_to_small_native_ports() -> None:
    console_mode = _RecordingConsoleMode()
    modifier_keys = _RecordingModifierKeys()
    adapter = DefaultTerminalPlatformAdapter(
        platform=NativeTerminalPlatform(
            console_mode=console_mode,
            modifier_keys=modifier_keys,
        )
    )

    assert adapter.enable_windows_vt_output("stdout") is True
    assert adapter.enable_windows_vt_input("stdin") is True
    assert adapter.windows_console_mode_configured() is True
    assert adapter.windows_vt_input_active() is True
    assert adapter.windows_vt_output_active() is True
    assert adapter.apple_shift_pressed() is True
    adapter.disable_windows_vt_input()
    adapter.disable_windows_vt_output()

    assert console_mode.calls == [
        "enable_output:stdout",
        "enable_input:stdin:preserve_selection=False",
        "mode_configured",
        "input_active",
        "output_active",
        "disable_input",
        "disable_output",
    ]
    assert modifier_keys.calls == ["shift_pressed"]


def test_neutral_terminal_platform_has_no_native_side_effects() -> None:
    adapter = DefaultTerminalPlatformAdapter(
        platform=NativeTerminalPlatform(
            console_mode=NeutralConsoleMode(),
            modifier_keys=NeutralModifierKeys(),
        )
    )

    assert adapter.enable_windows_vt_output(object()) is False
    assert adapter.enable_windows_vt_input(object()) is False
    assert adapter.windows_console_mode_configured() is False
    assert adapter.windows_vt_input_active() is False
    assert adapter.windows_vt_output_active() is False
    assert adapter.apple_shift_pressed() is False
    adapter.disable_windows_vt_input()
    adapter.disable_windows_vt_output()


def test_legacy_adapter_bridge_tolerates_older_missing_optional_hooks() -> None:
    adapter = _MinimalLegacyAdapter()
    platform = adapt_terminal_platform_adapter(adapter)  # type: ignore[arg-type]

    assert platform.console_mode.enable_vt_output(object()) is False
    assert platform.console_mode.enable_vt_input("stdin") is True
    assert platform.console_mode.mode_configured() is False
    assert platform.console_mode.vt_input_active() is False
    assert platform.console_mode.vt_output_active() is False
    assert platform.modifier_keys.shift_pressed() is True
    platform.console_mode.disable_vt_input()
    platform.console_mode.disable_vt_output()

    assert adapter.calls == ["enable_input:stdin", "shift_pressed", "disable_input"]


@dataclass
class _RecordingConsoleMode:
    calls: list[str] = field(default_factory=list)

    def enable_vt_input(
        self,
        stdin: object,
        *,
        preserve_native_selection: bool = False,
    ) -> bool:
        self.calls.append(
            f"enable_input:{stdin}:preserve_selection={preserve_native_selection}"
        )
        return True

    def disable_vt_input(self) -> None:
        self.calls.append("disable_input")

    def enable_vt_output(self, stdout: object) -> bool:
        self.calls.append(f"enable_output:{stdout}")
        return True

    def disable_vt_output(self) -> None:
        self.calls.append("disable_output")

    def mode_configured(self) -> bool:
        self.calls.append("mode_configured")
        return True

    def vt_input_active(self) -> bool:
        self.calls.append("input_active")
        return True

    def vt_output_active(self) -> bool:
        self.calls.append("output_active")
        return True


@dataclass
class _RecordingModifierKeys:
    calls: list[str] = field(default_factory=list)

    def shift_pressed(self) -> bool:
        self.calls.append("shift_pressed")
        return True


@dataclass
class _MinimalLegacyAdapter:
    calls: list[str] = field(default_factory=list)

    def enable_windows_vt_input(self, stdin: object) -> bool:
        self.calls.append(f"enable_input:{stdin}")
        return True

    def disable_windows_vt_input(self) -> None:
        self.calls.append("disable_input")

    def apple_shift_pressed(self) -> bool:
        self.calls.append("shift_pressed")
        return True
