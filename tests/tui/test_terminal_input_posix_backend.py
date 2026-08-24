from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from loushang.tui.terminal_backends.posix import (
    PosixTerminalInput,
    PosixTerminalMode,
)


def test_blocking_reader_decodes_one_utf8_scalar(monkeypatch: Any) -> None:
    chunks = iter((b"\xf0", b"\x9f", b"\x91", b"\x8b"))
    monkeypatch.setattr(
        "loushang.tui.terminal_backends.posix.os.read",
        lambda _fd, _size: next(chunks),
    )

    result = PosixTerminalInput().read_chunk_blocking(_TtyInput())

    assert result == "👋"
    assert result.encode("utf-8") == b"\xf0\x9f\x91\x8b"


def test_terminal_mode_configures_and_restores_posix_state() -> None:
    original_attrs = [1, 0, 0, 0b1111, 0, 0, [9, 9]]
    calls: list[tuple[int, int, list[Any]]] = []
    cbreak_fds: list[int] = []
    termios = SimpleNamespace(
        ICRNL=0b0001,
        ECHO=0b0001,
        ICANON=0b0010,
        ISIG=0b0100,
        IEXTEN=0b1000,
        VMIN=0,
        VTIME=1,
        TCSADRAIN=7,
        tcgetattr=lambda fd: original_attrs,
        tcsetattr=lambda fd, when, attrs: calls.append((fd, when, attrs)),
    )
    tty = SimpleNamespace(setcbreak=lambda fd: cbreak_fds.append(fd))

    lease = PosixTerminalMode(module_loader=lambda: (termios, tty)).open(_TtyInput())

    assert lease is not None
    assert cbreak_fds == [42]
    active_attrs = calls[0][2]
    assert active_attrs is not original_attrs
    assert active_attrs[6] is not original_attrs[6]
    assert active_attrs[0] & termios.ICRNL == 0
    assert active_attrs[3] == 0
    assert active_attrs[6] == [1, 0]

    lease.restore()

    assert calls[-1] == (42, termios.TCSADRAIN, original_attrs)


def test_terminal_mode_declines_when_posix_modules_are_unavailable() -> None:
    mode = PosixTerminalMode(module_loader=lambda: None)

    assert mode.open(_TtyInput()) is None


def test_terminal_mode_restores_original_state_when_configuration_fails() -> None:
    original_attrs = [0, 0, 0, 0, 0, 0, [0, 0]]
    calls: list[tuple[int, int, list[Any]]] = []

    def set_attrs(fd: int, when: int, attrs: list[Any]) -> None:
        calls.append((fd, when, attrs))
        if attrs is not original_attrs:
            raise RuntimeError("configuration failed")

    termios = SimpleNamespace(
        ECHO=1,
        ICANON=2,
        VMIN=0,
        VTIME=1,
        TCSADRAIN=7,
        tcgetattr=lambda fd: original_attrs,
        tcsetattr=set_attrs,
    )
    tty = SimpleNamespace(setcbreak=lambda fd: None)

    with pytest.raises(RuntimeError, match="configuration failed"):
        PosixTerminalMode(module_loader=lambda: (termios, tty)).open(_TtyInput())

    assert calls[-1] == (42, termios.TCSADRAIN, original_attrs)


class _TtyInput:
    def fileno(self) -> int:
        return 42
