from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loushang.tui import strip_control_sequences
from tests.coding.test_hosted_legacy_evidence import _private_environment
from tests.tui.terminal_process_support import (
    selected_backend_name,
    spawn_terminal_process,
    terminal_test_environment,
)


def _cli_sandbox(root: Path) -> tuple[Path, dict[str, str]]:
    """Keep real CLI probes independent of developer config and project size."""
    workspace = root / "p"
    workspace.mkdir()
    repo_root = Path(__file__).resolve().parents[2]
    return workspace, terminal_test_environment(repo_root, base=_private_environment(root))

pytestmark = [
    pytest.mark.tui_terminal_contract,
    pytest.mark.requires_host_runtime,
]


@pytest.fixture(autouse=True)
def _record_backend(record_testsuite_property) -> None:
    record_testsuite_property("terminal_backend", selected_backend_name())


def test_real_cli_quit_restores_shared_terminal_modes(tmp_path: Path) -> None:
    workspace, env = _cli_sandbox(tmp_path)

    with spawn_terminal_process(
        [sys.executable, "-m", "loushang.coding.cli", "--tui"],
        cwd=workspace,
        env=env,
        columns=80,
        rows=24,
    ) as driver:
        driver.read_until(
            lambda output: "Welcome to Loushang CLI"
            in strip_control_sequences(output),
            timeout=15,
        )
        # Welcome is now first-frame, not a promise that Session is executable.
        driver.read_until(
            lambda output: " | idle" in strip_control_sequences(output),
            timeout=15,
        )
        driver.write("/quit\r")
        assert driver.wait(timeout=15) == 0
        output = driver.raw_output

    assert driver.diagnostics.backend == selected_backend_name()
    assert driver.diagnostics.reader_alive is False
    assert "Welcome to Loushang CLI" in strip_control_sequences(output)
    _assert_paired_mode(output, enable="\x1b[?2004h", disable="\x1b[?2004l")
    _assert_paired_mode(output, enable="\x1b[?1004h", disable="\x1b[?1004l")
    cleanup_end = max(output.rfind("\x1b[?2004l"), output.rfind("\x1b[?1004l"))
    final_tail = strip_control_sequences(output[cleanup_end:])
    assert " | idle" not in final_tail
    assert " | running" not in final_tail


def _assert_paired_mode(output: str, *, enable: str, disable: str) -> None:
    enabled_at = output.find(enable)
    disabled_at = output.rfind(disable)
    assert enabled_at != -1
    assert disabled_at > enabled_at
