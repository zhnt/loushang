from __future__ import annotations

from loushang.tui.terminal_backends.windows import WindowsConsoleMode

ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def test_windows_console_input_mode_disables_quick_edit_and_enables_vt() -> None:
    initial_mode = ENABLE_QUICK_EDIT_MODE | 0x0004
    kernel32 = _FakeKernel32(initial_mode=initial_mode)
    adapter = _platform(kernel32)

    assert adapter.enable_vt_input(object()) is True

    expected_mode = (
        initial_mode | ENABLE_EXTENDED_FLAGS | ENABLE_VIRTUAL_TERMINAL_INPUT
    ) & ~ENABLE_QUICK_EDIT_MODE
    assert kernel32.set_modes == [expected_mode]
    assert adapter.mode_configured() is True
    assert adapter.vt_input_active() is True

    adapter.disable_vt_input()

    assert kernel32.set_modes == [expected_mode, initial_mode]
    assert adapter.mode_configured() is False
    assert adapter.vt_input_active() is False


def test_windows_console_input_mode_preserves_quick_edit_for_native_selection() -> None:
    initial_mode = ENABLE_QUICK_EDIT_MODE | 0x0004
    kernel32 = _FakeKernel32(initial_mode=initial_mode)
    adapter = _platform(kernel32)

    assert adapter.enable_vt_input(
        object(), preserve_native_selection=True
    ) is True

    expected_mode = (
        initial_mode | ENABLE_EXTENDED_FLAGS | ENABLE_VIRTUAL_TERMINAL_INPUT
    )
    assert kernel32.set_modes == [expected_mode]

    adapter.disable_vt_input()

    assert kernel32.set_modes == [expected_mode, initial_mode]


def test_windows_console_input_mode_disables_quick_edit_when_vt_is_rejected() -> (
    None
):
    initial_mode = ENABLE_QUICK_EDIT_MODE | 0x0004
    kernel32 = _FakeKernel32(initial_mode=initial_mode, reject_vt_input=True)
    adapter = _platform(kernel32)

    assert adapter.enable_vt_input(object()) is False

    vt_mode = (
        initial_mode | ENABLE_EXTENDED_FLAGS | ENABLE_VIRTUAL_TERMINAL_INPUT
    ) & ~ENABLE_QUICK_EDIT_MODE
    quick_edit_mode = (initial_mode | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE
    assert kernel32.set_modes == [vt_mode, quick_edit_mode]
    assert adapter.mode_configured() is True
    assert adapter.vt_input_active() is False

    adapter.disable_vt_input()

    assert kernel32.set_modes == [vt_mode, quick_edit_mode, initial_mode]
    assert adapter.mode_configured() is False


def test_windows_console_output_mode_enables_vt_processing_and_restores() -> None:
    initial_mode = 0x0002
    kernel32 = _FakeKernel32(initial_mode=initial_mode)
    adapter = _platform(kernel32)

    assert adapter.enable_vt_output(object()) is True

    expected_mode = (
        initial_mode
        | ENABLE_PROCESSED_OUTPUT
        | ENABLE_VIRTUAL_TERMINAL_PROCESSING
    )
    assert kernel32.set_modes == [expected_mode]
    assert adapter.vt_output_active() is True

    adapter.disable_vt_output()

    assert kernel32.set_modes == [expected_mode, initial_mode]
    assert adapter.vt_output_active() is False


def test_windows_console_uses_stream_os_handle_when_available() -> None:
    kernel32 = _FakeKernel32(initial_mode=0)
    console = _FakeConsoleModule(os_handle=456)
    adapter = WindowsConsoleMode(
        kernel32_loader=lambda: kernel32,
        console_module_loader=lambda: console,
    )

    assert adapter.enable_vt_input(_Stream(fd=9)) is True

    assert console.fds == [9]
    assert kernel32.get_std_handle_calls == []
    assert kernel32.console_handles == [456]


def test_windows_console_backend_declines_when_kernel_loader_fails() -> None:
    def fail() -> object:
        raise OSError("kernel unavailable")

    adapter = WindowsConsoleMode(kernel32_loader=fail)

    assert adapter.enable_vt_input(object()) is False
    assert adapter.enable_vt_output(object()) is False
    assert adapter.mode_configured() is False


def _platform(kernel32: _FakeKernel32) -> WindowsConsoleMode:
    return WindowsConsoleMode(
        kernel32_loader=lambda: kernel32,
        console_module_loader=lambda: None,
    )


class _FakeKernel32:
    def __init__(self, *, initial_mode: int, reject_vt_input: bool = False) -> None:
        self.initial_mode = initial_mode
        self.reject_vt_input = reject_vt_input
        self.set_modes: list[int] = []
        self.get_std_handle_calls: list[int] = []
        self.console_handles: list[int | None] = []

    def GetStdHandle(self, handle_id: int) -> int:
        self.get_std_handle_calls.append(handle_id)
        return 123

    def GetConsoleMode(self, handle: object, mode_ptr: object) -> int:
        self.console_handles.append(getattr(handle, "value", None))
        mode_ptr._obj.value = self.initial_mode
        return 1

    def SetConsoleMode(self, _handle: object, mode: object) -> int:
        value = int(getattr(mode, "value", mode))
        self.set_modes.append(value)
        if self.reject_vt_input and value & ENABLE_VIRTUAL_TERMINAL_INPUT:
            return 0
        return 1


class _FakeConsoleModule:
    def __init__(self, *, os_handle: int) -> None:
        self.os_handle = os_handle
        self.fds: list[int] = []

    def get_osfhandle(self, fd: int) -> int:
        self.fds.append(fd)
        return self.os_handle


class _Stream:
    def __init__(self, *, fd: int) -> None:
        self.fd = fd

    def fileno(self) -> int:
        return self.fd
