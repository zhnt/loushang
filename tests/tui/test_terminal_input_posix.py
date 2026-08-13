from __future__ import annotations

import os
from io import StringIO
from typing import Any

from loushang.tui.keyboard_protocol import (
    KITTY_QUERY_SEQUENCE,
    MODIFY_OTHER_KEYS_DISABLE_SEQUENCE,
    MODIFY_OTHER_KEYS_ENABLE_SEQUENCE,
)
from loushang.tui.terminal_input import TerminalInputMode, drain_input


def test_terminal_input_mode_enables_and_restores_tty_modes(monkeypatch: Any) -> None:
    import termios

    stdin = _TtyInput()
    stdout = StringIO()
    original_attrs = [
        getattr(termios, "ICRNL", 0),
        0,
        0,
        termios.ECHO
        | termios.ICANON
        | getattr(termios, "ISIG", 0)
        | getattr(termios, "IEXTEN", 0),
        0,
        0,
        [0] * 32,
    ]
    tcsetattr_calls: list[tuple[int, int, list[Any]]] = []

    monkeypatch.setattr("termios.tcgetattr", lambda fd: original_attrs)
    monkeypatch.setattr(
        "termios.tcsetattr",
        lambda fd, when, attrs: tcsetattr_calls.append((fd, when, attrs)),
    )
    monkeypatch.setattr("tty.setcbreak", lambda fd: None)
    monkeypatch.setattr(
        "loushang.tui.terminal_input.drain_input", lambda *args, **kwargs: ""
    )

    with TerminalInputMode(stdin=stdin, stdout=stdout):
        pass

    output = stdout.getvalue()
    assert "\x1b[?2004h" in output
    assert "\x1b[?1004h" in output
    assert KITTY_QUERY_SEQUENCE in output
    assert MODIFY_OTHER_KEYS_ENABLE_SEQUENCE in output
    assert "\x1b[?2004l" in output
    assert "\x1b[?1004l" in output
    assert MODIFY_OTHER_KEYS_DISABLE_SEQUENCE in output
    active_attrs = tcsetattr_calls[0][2]
    assert active_attrs[3] & getattr(termios, "IEXTEN", 0) == 0
    assert tcsetattr_calls[-1] == (stdin.fileno(), termios.TCSADRAIN, original_attrs)


def test_terminal_input_mode_delivers_control_v() -> None:
    import pty
    import select

    master_fd, slave_fd = pty.openpty()
    try:
        with os.fdopen(slave_fd, "r", closefd=False) as stdin:
            with TerminalInputMode(
                stdin=stdin,
                stdout=StringIO(),
                bracketed_paste=False,
                focus_events=False,
                keyboard_protocols=False,
                drain_on_exit=False,
            ):
                os.write(master_fd, b"\x16")
                readable, _, _ = select.select([slave_fd], [], [], 1.0)
                assert readable == [slave_fd]
                assert os.read(slave_fd, 1) == b"\x16"
    finally:
        os.close(master_fd)
        os.close(slave_fd)


def test_drain_input_respects_max_duration_for_continuous_tty_input(
    monkeypatch: Any,
) -> None:
    calls: list[int] = []

    def fake_select(
        read_list: list[int], _write: list[Any], _error: list[Any], _timeout: float
    ) -> tuple[list[int], list[Any], list[Any]]:
        return read_list, [], []

    def fake_read(_fd: int, size: int) -> bytes:
        calls.append(size)
        return b"x"

    clock = _FloatClock(step=0.004)
    monkeypatch.setattr("select.select", fake_select)
    monkeypatch.setattr("os.read", fake_read)

    drained = drain_input(
        _TtyInput(), max_bytes=1_000, idle_timeout=0.01, max_duration=0.01, now=clock
    )

    assert 1 <= len(drained) < 1_000


class _TtyInput:
    def fileno(self) -> int:
        return 42

    def isatty(self) -> bool:
        return True


class _FloatClock:
    def __init__(self, *, step: float) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current
