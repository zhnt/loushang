from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

from tests.tui.terminal_process_support import (
    selected_backend_name,
    spawn_terminal_process,
    terminal_test_environment,
)

pytestmark = pytest.mark.tui_terminal_backend


@pytest.fixture(autouse=True)
def _record_backend(record_testsuite_property) -> None:
    record_testsuite_property("terminal_backend", selected_backend_name())


def test_terminal_backend_preserves_argv_cwd_env_unicode_vt_and_initial_size(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "目录 with space"
    cwd.mkdir()
    env = _environment(extra={"LOUSHANG_FIXTURE_VALUE": "环境 value"})
    argument = "参数 with space"

    with spawn_terminal_process(
        _fixture_args(
            "metadata",
            "--argument",
            argument,
            "--env-name",
            "LOUSHANG_FIXTURE_VALUE",
        ),
        cwd=cwd,
        env=env,
        columns=91,
        rows=27,
    ) as driver:
        output = driver.read_until(lambda text: "NO_NEWLINE" in text, timeout=10)
        status = driver.wait(timeout=10)

    metadata_text = output.split("META:", 1)[1].splitlines()[0]
    metadata = json.loads(metadata_text)
    assert status == 0
    assert metadata == {
        "argument": argument,
        "cwd": str(cwd),
        "env": "环境 value",
        "size": [91, 27],
    }
    assert "UNICODE:中文🙂" in output
    assert any(
        sequence in output
        for sequence in (
            "VT:\x1b[31mred\x1b[0m:NO_NEWLINE",
            "VT:\x1b[31mred\x1b[m:NO_NEWLINE",
        )
    )
    assert driver.diagnostics.reader_alive is False


def test_terminal_backend_resize_is_visible_to_child(tmp_path: Path) -> None:
    with spawn_terminal_process(
        _fixture_args("resize"),
        cwd=tmp_path,
        env=_environment(),
        columns=80,
        rows=24,
    ) as driver:
        driver.read_until(lambda text: "INITIAL_SIZE:80x24" in text, timeout=10)
        driver.resize(columns=103, rows=31)
        driver.write("continue\r")
        output = driver.read_until(
            lambda text: "RESIZED_SIZE:103x31" in text, timeout=10
        )
        assert driver.wait(timeout=10) == 0

    assert "RESIZED_SIZE:103x31" in output


def test_terminal_backend_drains_large_no_newline_output_and_exit_status(
    tmp_path: Path,
) -> None:
    with spawn_terminal_process(
        # 22,000 three-byte UTF-8 code points keep the unbroken payload above
        # 64 KiB while bounding the ConHost screen-render workload.
        _fixture_args("large", "--size", "22000", "--code", "7"),
        cwd=tmp_path,
        env=_environment(),
        # ConHost interprets and re-emits VT output. A narrow viewport turns a
        # large double-width line into thousands of scroll/repaint operations,
        # obscuring the transport/drain behavior this contract is testing.
        columns=4096,
        rows=64,
    ) as driver:
        for index in range(22):
            marker = f"LARGE_CHUNK:{index}:"
            driver.read_until(
                lambda text, marker=marker: marker in text,
                timeout=10,
            )
            driver.write("c")
        driver.read_until(lambda text: "LARGE_END" in text, timeout=10)
        driver.write("c")
        assert driver.wait(timeout=10) == 7
        output = driver.raw_output

    assert "LARGE_BEGIN" in output
    assert "LARGE_END" in output
    assert output.count("界") == 22_000


def test_terminal_backend_answers_split_dsr_queries(tmp_path: Path) -> None:
    with spawn_terminal_process(
        _fixture_args("query"),
        cwd=tmp_path,
        env=_environment(),
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


def test_terminal_backend_timeout_terminates_root_and_descendant(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "tree-pids.json"
    driver = spawn_terminal_process(
        _fixture_args("tree", "--pid-file", str(pid_file)),
        cwd=tmp_path,
        env=_environment(),
        columns=80,
        rows=24,
    )
    try:
        driver.read_until(lambda text: "TREE_READY:" in text, timeout=10)
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        driver.terminate_tree(timeout=10)
        _wait_until_processes_exit(tuple(pids.values()), timeout=5)
    finally:
        driver.close(timeout=5)
        driver.close(timeout=5)

    assert driver.is_alive() is False
    assert driver.diagnostics.reader_alive is False


def test_terminal_backend_close_is_idempotent_after_normal_exit(tmp_path: Path) -> None:
    driver = spawn_terminal_process(
        _fixture_args("metadata", "--argument", "x", "--env-name", "PATH"),
        cwd=tmp_path,
        env=_environment(),
        columns=80,
        rows=24,
    )
    driver.read_until(lambda text: "NO_NEWLINE" in text, timeout=10)
    assert driver.wait(timeout=10) == 0
    driver.close(timeout=5)
    driver.close(timeout=5)

    assert driver.diagnostics.reader_alive is False


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


def _environment(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    return terminal_test_environment(_repo_root(), extra=extra)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _wait_until_processes_exit(pids: tuple[int, ...], *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = tuple(pid for pid in pids if _process_is_alive(pid))
        if not alive:
            return
        time.sleep(0.02)
    raise AssertionError(f"terminal process tree still alive: {alive}")


def _process_is_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                process, ctypes.byref(exit_code)
            ):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
