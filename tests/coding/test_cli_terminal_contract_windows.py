from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from loushang.tui import strip_control_sequences
from tests.tui.terminal_process_support import (
    selected_backend_name,
    spawn_terminal_process,
    terminal_test_environment,
)

pytestmark = [
    pytest.mark.tui_terminal_contract,
    pytest.mark.requires_host_runtime,
    pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY CLI contract"),
]


@pytest.fixture(autouse=True)
def _record_backend(record_testsuite_property) -> None:
    record_testsuite_property("terminal_backend", selected_backend_name())


def test_windows_cli_conpty_stream_ends_with_cursor_restoration() -> None:
    """Assert renderer-visible restoration, not raw application VT output."""
    repo_root = Path(__file__).resolve().parents[2]
    with spawn_terminal_process(
        [sys.executable, "-m", "loushang.coding.cli", "--tui"],
        cwd=repo_root,
        env=terminal_test_environment(repo_root),
        columns=80,
        rows=24,
    ) as driver:
        driver.read_until(
            lambda output: "Welcome to Loushang CLI"
            in strip_control_sequences(output),
            timeout=15,
        )
        driver.write("/quit\r")
        assert driver.wait(timeout=15) == 0
        output = driver.raw_output

    show_cursor = output.rfind("\x1b[?25h")
    paste_disable = output.rfind("\x1b[?2004l")
    focus_disable = output.rfind("\x1b[?1004l")
    assert show_cursor != -1
    assert paste_disable > show_cursor
    assert focus_disable > show_cursor
    assert driver.diagnostics.reader_alive is False
