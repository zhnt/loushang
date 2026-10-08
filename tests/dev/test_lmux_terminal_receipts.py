"""Receipt publication order; mocked native owner, not installed acceptance."""

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests.coding import _g18_native_probe as probe


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX terminal observer")
@pytest.mark.parametrize("fault", [None, "body", "alive", "modes", "fallback", "reader", "exit", "close", "cursor", "paste"])
def test_terminal_receipt_requires_original_complete_settlement(tmp_path, monkeypatch, fault):
    import pty
    import termios

    receipts, events = [], []
    diagnostics = SimpleNamespace(pid=123, reader_alive=fault == "reader",
                                  termination="fallback" if fault == "fallback" else None,
                                  exit_status=1 if fault == "exit" else 0)
    monkeypatch.setattr(probe, "FAILURE_TREE_DIAGNOSTIC", False)
    monkeypatch.setattr(pty, "openpty", lambda: (1, 2))
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [1] if fault == "modes" and fd == 1 else [])
    output = "\x1b[?25l\x1b[?2004h\x1b[?25h\x1b[?2004l"
    if fault == "cursor":
        output += "\x1b[?25l"
    if fault == "paste":
        output += "\x1b[?2004h"

    @contextmanager
    def terminal(*args, **kwargs):
        pty.openpty()
        try:
            yield SimpleNamespace(diagnostics=diagnostics, is_alive=lambda: fault == "alive", raw_output=output)
        finally:
            assert receipts == [], "receipt preceded original owner close"
            events.append("closed")
            if fault == "close":
                raise RuntimeError("late close failure")

    monkeypatch.setattr(probe, "foreground_terminal", terminal)
    clock = iter([10.0, 12.0])
    monkeypatch.setattr(probe.time, "perf_counter", lambda: next(clock))

    def run():
        with probe.observed_terminal(["lmux", "attach"], tmp_path, {}, settlements=receipts):
            assert receipts == []
            if fault == "body":
                raise RuntimeError("body failure")

    if fault is None:
        run()
        assert receipts == [{
            "pid": 123, "argv": ["lmux", "attach"], "cwd": str(tmp_path.resolve()),
            "exit_status": 0, "termios_restored_at": 10.0, "settled_at": 12.0,
            "cursor_restored": True, "bracketed_paste_disabled": True,
            "reader_settled": True, "fallback": False,
        }]
    else:
        with pytest.raises((AssertionError, RuntimeError)):
            run()
        assert receipts == []
    assert events == ["closed"]
