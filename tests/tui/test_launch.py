from __future__ import annotations

import asyncio
import subprocess
import sys
from io import StringIO

from loushang.tui.launch import (
    TuiLaunchProfile,
    is_interactive_terminal,
    run_tui_launch_shell,
    select_tui_launch_runner,
)


class _Stream(StringIO):
    def __init__(self, *, tty: bool = False) -> None:
        super().__init__()
        self.tty = tty
        self.flush_count = 0

    def isatty(self) -> bool:
        return self.tty

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


class _BrokenTtyStream(_Stream):
    def isatty(self) -> bool:
        raise RuntimeError("tty probe failed")


def test_importing_launch_does_not_load_product_or_session_layers() -> None:
    script = """
import importlib
import sys

importlib.import_module("loushang.tui.launch")

for prefix in (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
    "loushang.harnesstui",
):
    assert not any(
        name == prefix or name.startswith(prefix + ".") for name in sys.modules
    ), prefix
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_interactive_terminal_requires_both_streams_to_be_ttys() -> None:
    assert is_interactive_terminal(stdin=_Stream(tty=True), stdout=_Stream(tty=True))
    assert not is_interactive_terminal(
        stdin=_Stream(tty=True), stdout=_Stream(tty=False)
    )
    assert not is_interactive_terminal(
        stdin=_Stream(tty=False), stdout=_Stream(tty=True)
    )


def test_launch_runner_selection_does_not_invoke_runners() -> None:
    async def run_screen() -> int:
        raise AssertionError("selection must not invoke the runner")

    async def run_plain() -> int:
        raise AssertionError("selection must not invoke the runner")

    profile = TuiLaunchProfile(
        run_screen=run_screen,
        run_plain=run_plain,
        error_prefix="failure: ",
    )
    assert (
        select_tui_launch_runner(
            stdin=_Stream(tty=True), stdout=_Stream(tty=True), profile=profile
        )
        is run_screen
    )
    assert (
        select_tui_launch_runner(
            stdin=_Stream(tty=True), stdout=_Stream(tty=False), profile=profile
        )
        is run_plain
    )


def test_launch_shell_routes_screen_and_plain_without_owning_product_state() -> None:
    calls: list[str] = []

    async def run_screen() -> int:
        calls.append("screen")
        return 7

    async def run_plain() -> int:
        calls.append("plain")
        return 8

    profile = TuiLaunchProfile(
        run_screen=run_screen,
        run_plain=run_plain,
        error_prefix="failure: ",
    )

    async def scenario() -> tuple[int, int]:
        screen_result = await run_tui_launch_shell(
            stdin=_Stream(tty=True),
            stdout=_Stream(tty=True),
            stderr=_Stream(),
            profile=profile,
        )
        plain_result = await run_tui_launch_shell(
            stdin=_Stream(tty=False),
            stdout=_Stream(tty=True),
            stderr=_Stream(),
            profile=profile,
        )
        return screen_result, plain_result

    assert asyncio.run(scenario()) == (7, 8)
    assert calls == ["screen", "plain"]


def test_launch_shell_maps_runner_failure_and_only_emits_verbose_traceback() -> None:
    async def fail() -> int:
        raise RuntimeError("runner failed")

    async def unused() -> int:
        raise AssertionError("plain runner should not run")

    async def scenario(*, verbose: bool) -> tuple[int, _Stream, _Stream]:
        stdout = _Stream(tty=True)
        stderr = _Stream()
        result = await run_tui_launch_shell(
            stdin=_Stream(tty=True),
            stdout=stdout,
            stderr=stderr,
            profile=TuiLaunchProfile(
                run_screen=fail,
                run_plain=unused,
                error_prefix="problem: ",
                failure_exit_code=23,
            ),
            verbose=verbose,
        )
        return result, stdout, stderr

    quiet_result, quiet_stdout, quiet_stderr = asyncio.run(scenario(verbose=False))
    verbose_result, verbose_stdout, verbose_stderr = asyncio.run(scenario(verbose=True))

    assert quiet_result == verbose_result == 23
    assert (
        quiet_stdout.getvalue()
        == verbose_stdout.getvalue()
        == ("problem: runner failed\n")
    )
    assert quiet_stdout.flush_count == verbose_stdout.flush_count == 1
    assert quiet_stderr.getvalue() == ""
    assert quiet_stderr.flush_count == 0
    assert "Traceback (most recent call last)" in verbose_stderr.getvalue()
    assert "RuntimeError: runner failed" in verbose_stderr.getvalue()
    assert verbose_stderr.flush_count == 1


def test_launch_shell_maps_tty_probe_failure_and_empty_exception_message() -> None:
    class EmptyError(Exception):
        pass

    async def fail_with_empty_message() -> int:
        raise EmptyError()

    async def unused() -> int:
        raise AssertionError("runner should not be selected")

    stdout = _Stream()
    result = asyncio.run(
        run_tui_launch_shell(
            stdin=_BrokenTtyStream(),
            stdout=stdout,
            stderr=_Stream(),
            profile=TuiLaunchProfile(
                run_screen=unused,
                run_plain=unused,
                error_prefix="error: ",
                failure_exit_code=4,
            ),
        )
    )
    assert result == 4
    assert stdout.getvalue() == "error: tty probe failed\n"

    stdout = _Stream()
    result = asyncio.run(
        run_tui_launch_shell(
            stdin=_Stream(),
            stdout=stdout,
            stderr=_Stream(),
            profile=TuiLaunchProfile(
                run_screen=unused,
                run_plain=fail_with_empty_message,
                error_prefix="error: ",
                failure_exit_code=4,
            ),
        )
    )
    assert result == 4
    assert stdout.getvalue() == "error: EmptyError\n"
