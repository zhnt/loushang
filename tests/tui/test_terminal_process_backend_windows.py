from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.tui.terminal_process_support import (
    selected_backend_name,
    spawn_terminal_process,
    terminal_test_environment,
)

pytestmark = [
    pytest.mark.tui_terminal_backend,
    pytest.mark.requires_host_runtime,
    pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY native contract"),
]


@pytest.fixture(autouse=True)
def _record_backend(record_testsuite_property) -> None:
    record_testsuite_property("terminal_backend", selected_backend_name())


def test_conpty_mediates_application_dsr_through_its_renderer(
    tmp_path: Path,
) -> None:
    """Do not mistake ConPTY's reconstructed screen stream for raw stdout."""
    with spawn_terminal_process(
        _fixture_args("query-output"),
        cwd=tmp_path,
        env=terminal_test_environment(_repo_root()),
        columns=80,
        rows=24,
    ) as driver:
        output = driver.read_until(
            lambda text: "QUERY_OUTPUT_DONE" in text,
            timeout=10,
        )
        status = driver.wait(timeout=10)

    assert status == 0, output
    assert "QUERY_OUTPUT_DONE" in output
    assert "\x1b[5n" not in output
    assert driver.diagnostics.unknown_queries == ()


def _fixture_args(*args: str) -> list[str]:
    return [
        sys.executable,
        str(
            Path(__file__).parent
            / "terminal_process_support"
            / "fixture_child.py"
        ),
        *args,
    ]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
