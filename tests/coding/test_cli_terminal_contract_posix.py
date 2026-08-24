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
    pytest.mark.skipif(os.name == "nt", reason="POSIX PTY CLI contract"),
]


@pytest.fixture(autouse=True)
def _record_backend(record_testsuite_property) -> None:
    record_testsuite_property("terminal_backend", selected_backend_name())


def test_posix_cli_exposes_raw_cursor_and_synchronized_output_lifecycle() -> None:
    output = _run_cli_and_quit()

    assert "\x1b[?25l" in output
    assert "\x1b[?2026h" in output
    final_sync_end = output.rfind("\x1b[?2026l")
    assert final_sync_end != -1
    final_tail = strip_control_sequences(output[final_sync_end:])
    assert " | idle" not in final_tail
    assert " | running" not in final_tail


def _run_cli_and_quit() -> str:
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
        return driver.raw_output
