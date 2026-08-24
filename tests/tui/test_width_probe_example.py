from __future__ import annotations

import os
import runpy
import sys
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="the width probe is a POSIX termios example",
)


def test_width_probe_restores_termios_when_cleanup_output_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path("examples/tui/36_width_probe.py", run_name="__test__")
    measure_terminal_widths = namespace["_measure_terminal_widths"]

    original = [1, 2, 3, 4, 5, 6, [7, 8]]
    restored: list[list[Any]] = []

    def tcgetattr(_fd: int) -> list[Any]:
        return original

    def tcsetattr(_fd: int, _when: int, attrs: list[Any]) -> None:
        restored.append(attrs)

    fake_termios = SimpleNamespace(
        ECHO=1,
        ICANON=2,
        VMIN=0,
        VTIME=1,
        TCSADRAIN=3,
        TCIFLUSH=4,
        tcgetattr=tcgetattr,
        tcsetattr=tcsetattr,
        tcflush=lambda *_args: None,
    )

    class FakeStdin:
        @staticmethod
        def isatty() -> bool:
            return True

        @staticmethod
        def fileno() -> int:
            return 7

    class FailingStdout:
        @staticmethod
        def isatty() -> bool:
            return True

        @staticmethod
        def write(_text: str) -> None:
            raise OSError("cleanup failed")

        @staticmethod
        def flush() -> None:
            return None

    monkeypatch.setitem(sys.modules, "termios", fake_termios)
    monkeypatch.setitem(
        measure_terminal_widths.__globals__,
        "_query_cursor_position",
        lambda **_kwargs: (1, 1),
    )

    with pytest.raises(OSError, match="cleanup failed"):
        measure_terminal_widths(
            stdin=FakeStdin(),
            stdout=FailingStdout(),
            query_interval=0,
        )

    assert len(restored) == 2
    assert restored[-1] is original
