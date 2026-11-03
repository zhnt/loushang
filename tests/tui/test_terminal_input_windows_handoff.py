"""Transferable Windows console input, exercised without a native console."""

import asyncio
import ctypes
from collections import deque

import pytest

from loushang.tui.terminal_backends import native_terminal_input_backend
from loushang.tui.terminal_backends import windows as backend_module
from loushang.tui.terminal_backends.windows import (
    WindowsConsoleInput,
    WindowsTerminalInputReader,
)


class Console:
    def __init__(self, chars=()):
        self.chars = deque(chars)

    def kbhit(self):
        return bool(self.chars)

    def getwch(self):
        assert self.chars, "getwch must never wait for a missing native unit"
        return self.chars.popleft()

    def at_input_boundary(self):
        return not self.chars


def test_backend_selection_shares_posix_reader_for_linux_and_macos():
    assert native_terminal_input_backend("linux") is native_terminal_input_backend(
        "darwin"
    )
    assert isinstance(native_terminal_input_backend("win32"), WindowsConsoleInput)


@pytest.mark.parametrize(
    "head,tail,expected",
    [
        (["\ud83d"], ["\udc4b"], "👋"),
        (["\x1b"], ["[", "A"], "\x1b[A"),
        (["\x1b", "[", "2"], list("00~draft\x1b[201~"), "\x1b[200~draft\x1b[201~"),
    ],
)
def test_partial_native_input_survives_cancel_and_new_loop(head, tail, expected):
    console = Console(head)
    reader = WindowsTerminalInputReader(console)
    assert not reader.at_input_boundary()

    async def pause():
        task = asyncio.create_task(reader.read_chunk())
        await asyncio.sleep(0)
        assert not console.chars and not task.done()
        with pytest.raises(RuntimeError, match="already active"):
            await reader.read_chunk()
        with pytest.raises(RuntimeError, match="read is active"):
            reader.at_input_boundary()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(pause())
    assert not reader.at_input_boundary()
    console.chars.extend(tail)
    assert asyncio.run(reader.read_chunk()) == expected
    assert reader.at_input_boundary()


@pytest.mark.parametrize(
    "chars,expected",
    [
        (list("draft\r"), "draft\r"),
        (["\ud83d", "x"], "\ufffdx"),
        (["\udc4b"], "\ufffd"),
        (["\ud83d", "\ud83d", "\udc4b"], "\ufffd👋"),
        (["\x1b", "[", "I"], "\x1b[I"),
        (["\x03"], "\x03"),
    ],
)
def test_complete_input_and_empty_boundary(chars, expected):
    console = Console(chars)
    reader = WindowsTerminalInputReader(console)
    assert not reader.at_input_boundary()
    assert list(console.chars) == chars, "boundary probe must not consume input"
    assert asyncio.run(reader.read_chunk()) == expected
    assert reader.at_input_boundary()


def test_native_alt_v_sequence_is_preserved():
    reader = WindowsTerminalInputReader(Console(["\x1bv"]))
    assert asyncio.run(reader.read_chunk()) == "\x1bv"


def test_idle_read_cancels_without_leaving_a_background_reader():
    reader = WindowsTerminalInputReader(Console())

    async def scenario():
        task = asyncio.create_task(reader.read_chunk())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert reader.at_input_boundary()


def native_reader(monkeypatch, records):
    class Kernel:
        def __init__(self):
            self.records = deque(records)

        def GetStdHandle(self, _):
            return 123

        def PeekConsoleInputW(self, handle, buffer, capacity, count):
            snapshot = list(self.records)[:capacity]
            for index, record in enumerate(snapshot):
                buffer[index] = record
            ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32)).contents.value = len(
                snapshot
            )
            return True

        def ReadConsoleInputW(self, handle, buffer, capacity, count):
            assert self.records, "native read must have already-peeked input"
            record = self.records.popleft()
            ctypes.memmove(buffer, ctypes.byref(record), ctypes.sizeof(record))
            ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32)).contents.value = 1
            return True

    kernel = Kernel()
    monkeypatch.setattr(backend_module, "_load_kernel32", lambda: kernel)

    def forbidden_crt():
        raise AssertionError("transferable reads must not use CRT console filtering")

    return WindowsConsoleInput(module_loader=forbidden_crt).open_reader(None), kernel


def key_record(char="\0", *, scan=0, vk=0, down=True, repeat=1, modifiers=0):
    record = backend_module._WindowsInputRecord()
    record.EventType = 1
    key = record.Event.KeyEvent
    key.bKeyDown = down
    key.wRepeatCount = repeat
    key.wVirtualKeyCode = vk
    key.wVirtualScanCode = scan
    key.uChar.UnicodeChar = char
    key.dwControlKeyState = modifiers
    return record


def test_native_vt_records_with_no_virtual_key_cancel_and_transfer(monkeypatch):
    # ConPTY terminal replies have UnicodeChar but can have VK/scan code zero.
    reader, kernel = native_reader(monkeypatch, [key_record("\x1b")])

    async def pause():
        task = asyncio.create_task(reader.read_chunk())
        await asyncio.sleep(0)
        assert not kernel.records and not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(pause())
    assert not reader.at_input_boundary()
    kernel.records.extend(key_record(char) for char in "[?0u")
    assert asyncio.run(reader.read_chunk()) == "\x1b[?0u"
    assert reader.at_input_boundary()


@pytest.mark.parametrize(
    "records,expected",
    [
        ([key_record(scan=0x48, repeat=3)], "\x1b[A" * 3),
        ([key_record("v", vk=0x56, modifiers=0x02)], "\x1bv"),
        ([key_record("@", vk=0x56, modifiers=0x09)], "@"),  # AltGr layout text
        ([key_record("à")], "à"),
        ([key_record("\x03")], "\x03"),
        ([key_record("\ud83d"), key_record("\udc4b")], "👋"),
        ([key_record("é", vk=0x12, down=False)], "é"),
    ],
)
def test_native_record_decoding(monkeypatch, records, expected):
    reader, kernel = native_reader(monkeypatch, records)
    assert not reader.at_input_boundary()
    assert len(kernel.records) == len(records)
    assert asyncio.run(reader.read_chunk()) == expected
    assert reader.at_input_boundary()


def test_non_text_records_do_not_block_admission_or_corrupt_partial_utf16(monkeypatch):
    ignored = backend_module._WindowsInputRecord()
    ignored.EventType = 16  # focus/window/mouse records carry no character here.
    reader, kernel = native_reader(monkeypatch, [ignored, key_record("x", down=False)])
    assert reader.at_input_boundary()
    assert len(kernel.records) == 2, "boundary probes must not consume records"
    kernel.records.extend([key_record("\ud83d"), ignored, key_record("\udc4b")])
    assert asyncio.run(reader.read_chunk()) == "👋"
    assert reader.at_input_boundary()
