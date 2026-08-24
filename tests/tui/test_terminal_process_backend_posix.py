from __future__ import annotations

import os
import re
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
    pytest.mark.skipif(os.name == "nt", reason="POSIX PTY native contract"),
]


@pytest.fixture(autouse=True)
def _record_backend(record_testsuite_property) -> None:
    record_testsuite_property("terminal_backend", selected_backend_name())


def test_posix_pty_answers_application_dsr_queries(tmp_path: Path) -> None:
    with spawn_terminal_process(
        _fixture_args("query"),
        cwd=tmp_path,
        env=terminal_test_environment(_repo_root()),
        columns=80,
        rows=24,
    ) as driver:
        output = driver.read_until(lambda text: "QUERY_OK:" in text, timeout=10)
        status = driver.wait(timeout=10)

    assert status == 0, output
    query = re.search(r"QUERY_OK:([0-9a-f]+):([0-9a-f]+)", output)
    assert query is not None
    assert bytes.fromhex(query.group(1)) == b"\x1b[0n"
    cursor = bytes.fromhex(query.group(2)).decode("ascii")
    assert re.fullmatch(r"\x1b\[[1-9]\d*;[1-9]\d*R", cursor)


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
