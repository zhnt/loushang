"""Line commands retain original terminal ownership without TUI marker claims."""
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from . import _g18_native_probe as probe

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux PTY receipts")


def test_real_line_command_publishes_settled_receipt_without_tui_markers(tmp_path):
    receipts = []
    argv = [sys.executable, "-I", "-c", "print('line-ready')"]
    with probe.observed_terminal(argv, tmp_path, dict(os.environ),
                                 line_settlements=receipts) as (driver, _, _):
        assert driver.wait(timeout=10) == 0
    assert "line-ready" in driver.raw_output
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["presentation"] == "line" and receipt["argv"] == argv
    assert receipt["exit_status"] == 0 and receipt["reader_settled"]
    assert not receipt["fallback"]
    assert receipt["termios_restored_at"] <= receipt["settled_at"]
    assert "cursor_restored" not in receipt and "bracketed_paste_disabled" not in receipt


@pytest.mark.parametrize("failure", ["exit", "reader", "fallback", "modes", "close"])
def test_failed_line_settlement_publishes_no_receipt(tmp_path, monkeypatch, failure):
    import pty
    import termios

    monkeypatch.setattr(pty, "openpty", lambda: (1, 2))
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [fd] if failure == "modes" else [])
    monkeypatch.setattr(probe, "FAILURE_TREE_DIAGNOSTIC", False)
    driver = NS(is_alive=lambda: False, diagnostics=NS(
        pid=123, exit_status=1 if failure == "exit" else 0,
        reader_alive=failure == "reader", termination="fallback" if failure == "fallback" else None))

    @contextmanager
    def terminal(*args, **kwargs):
        pty.openpty()
        yield driver
        if failure == "close":
            raise RuntimeError("close receipt lost")

    monkeypatch.setattr(probe, "foreground_terminal", terminal)
    receipts = []
    with pytest.raises((AssertionError, RuntimeError)):
        with probe.observed_terminal([], tmp_path, {}, line_settlements=receipts):
            pass
    assert receipts == []
