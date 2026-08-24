from __future__ import annotations

from types import SimpleNamespace

from loushang.tui.terminal_backends.darwin import DarwinModifierKeys

SHIFT_MASK = 1 << 17


def test_darwin_terminal_platform_reads_shift_from_quartz() -> None:
    flags_state = _FlagsState(SHIFT_MASK)
    native_calls: list[str] = []
    modifier_keys = DarwinModifierKeys(
        application_services_loader=lambda: SimpleNamespace(
            CGEventSourceFlagsState=flags_state
        ),
        native_modifiers_loader=lambda: SimpleNamespace(
            is_shift_pressed=lambda: native_calls.append("called") or False
        ),
    )

    assert modifier_keys.shift_pressed() is True
    assert flags_state.sources == [0]
    assert native_calls == []


def test_darwin_terminal_platform_falls_back_to_native_modifier_probe() -> None:
    flags_state = _FlagsState(0)
    modifier_keys = DarwinModifierKeys(
        application_services_loader=lambda: SimpleNamespace(
            CGEventSourceFlagsState=flags_state
        ),
        native_modifiers_loader=lambda: SimpleNamespace(is_shift_pressed=lambda: True),
    )

    assert modifier_keys.shift_pressed() is True


def test_darwin_terminal_platform_declines_when_loaders_fail() -> None:
    def fail() -> object:
        raise OSError("probe unavailable")

    modifier_keys = DarwinModifierKeys(
        application_services_loader=fail,
        native_modifiers_loader=fail,
    )

    assert modifier_keys.shift_pressed() is False


class _FlagsState:
    def __init__(self, flags: int) -> None:
        self.flags = flags
        self.sources: list[int] = []
        self.argtypes: object = None
        self.restype: object = None

    def __call__(self, source: int) -> int:
        self.sources.append(source)
        return self.flags
