"""Real installed foreground command and native terminal; wheel isolation is separate."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.appserver.protocol import SessionScopeV1
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.session_manager import SessionManager
from loushang.tui.cell_width import strip_control_sequences
from tests.tui.terminal_process_support import (
    selected_backend_name,
)

from ._hosted_terminal import foreground_terminal, process_table
from .test_hosted_client import _argv, _launch
from .test_mux_terminal_process import _terminal_environment


def _installed() -> str:
    command = Path(sys.executable).parent / (
        "loushang-hosted-tui.exe" if os.name == "nt" else "loushang-hosted-tui"
    )
    assert command.is_file(), "the installed foreground client command must exist"
    return str(command)


def test_G17_TERMINAL_ENTRY_installed_help_ready_and_foreground_exit(
    tmp_path, record_testsuite_property
):
    _installed_help(tmp_path)
    environment = _terminal_environment(tmp_path)
    record_testsuite_property("terminal_backend", selected_backend_name())
    with foreground_terminal(
        [_installed(), *_argv(tmp_path)], cwd=tmp_path, env=environment,
        columns=100, rows=30,
    ) as driver:
        driver.read_until(lambda out: "/exit ends app" in strip_control_sequences(out), timeout=35)
        driver.write("/exit\r")
        assert driver.wait(timeout=25) == 0, driver.diagnostics
        assert not driver.is_alive()


def _installed_help(root):
    help_result = subprocess.run(
        [_installed(), "--help"], env=_terminal_environment(root),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
    )
    assert help_result.returncode == 0 and not help_result.stderr
    assert "exit ends its application" in help_result.stdout


@pytest.mark.parametrize("scope_kind", list(SessionScopeV1))
def test_G17_TERMINAL_PICKER_resumes_canonical_history_and_recovers_on_relaunch(
    tmp_path, record_testsuite_property, scope_kind
):
    record_testsuite_property("terminal_backend", selected_backend_name())
    _picker_workflow(tmp_path, scope_kind, run_cli=_picker_cli)


def _picker_cli(root, arguments, interaction, *, exit_command):
    with foreground_terminal(
        [_installed(), *arguments], cwd=root, env=_terminal_environment(root),
        columns=100, rows=30,
    ) as driver:
        driver.read_until(lambda out: "/exit ends app" in strip_control_sequences(out), timeout=35)
        interaction(driver)
        driver.write(exit_command)
        assert driver.wait(timeout=25) == 0, driver.diagnostics


def _picker_workflow(tmp_path, scope_kind, *, run_cli):
    """The same real history assertions with an explicit CLI lifetime owner."""
    launch = _launch(tmp_path)
    scope = next(item for item in launch.scopes if item.scope is scope_kind)
    text = f"G17 canonical history recovered in {scope_kind.value}"
    # Creation is an actual installed CLI operation, not a catalog substitute.
    def create(creator):
        creator.write(f"/new {scope_kind.value} Native history\r")
        creator.read_until(lambda out: "*1" in strip_control_sequences(out), timeout=20)
        checkpoint = len(creator.raw_output)
        creator.write("/close --yes\r")
        creator.read_until(
            lambda out: "no-session" in strip_control_sequences(out[checkpoint:]), timeout=20
        )

    run_cli(tmp_path, _argv(tmp_path), create, exit_command="/exit\r")

    async def seed():
        (path,) = scope.session_dir.glob("*.jsonl")
        manager = await SessionManager.open(path)
        try:
            await manager.append_message(UserMessage(role="user", content=text, timestamp=1.0))
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(seed())
    arguments = _argv(tmp_path)
    if scope_kind is SessionScopeV1.USER_HOME:
        # Global identity does not depend on the new admitted execution cwd.
        workspace = tmp_path / "other-workspace"
        workspace.mkdir()
        arguments[1] = str(workspace)
        other = CodingHostedLaunchV1(
            workspace, launch.application_root, launch.application_id,
            launch.cwd_sessions, launch.home_sessions,
        )
        assert other.scopes[1].fingerprint == scope.fingerprint
    # An empty named mux must explicitly select history; it cannot satisfy the
    # first predicate by automatically restoring the creator's existing member.
    arguments.extend(["--mux", "picker"])

    for attempt in range(2):
        run_cli(tmp_path, arguments,
                lambda driver, attempt=attempt: _picker_resume(driver, text, scope_kind, attempt),
                exit_command="\x02d")  # Foreground detach ends this application's child.
    assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1


def _picker_resume(driver, text, scope_kind, attempt):
    """Shared original witness for live CLI2 and live/restored CLI3."""
    driver.read_until(lambda out: "picker |" in strip_control_sequences(out), timeout=10)
    checkpoint = 0
    if attempt == 0:
        assert text not in strip_control_sequences(driver.raw_output)
        selected_scope = "global" if scope_kind is SessionScopeV1.USER_HOME else "cwd"
        driver.write(f"/sessions {selected_scope}\r")
        driver.read_until(
            lambda out: "select a saved Session" in strip_control_sequences(out), timeout=15
        )
        assert text not in strip_control_sequences(driver.raw_output)
        checkpoint = len(driver.raw_output)
        driver.write("\r")
    driver.read_until(
        lambda out, start=checkpoint: text in strip_control_sequences(out[start:]), timeout=20
    )
    driver.read_until(
        lambda out, start=checkpoint: "*1" in strip_control_sequences(out[start:]), timeout=10
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX independent process-group regression")
def test_G17_TERMINAL_failed_predicate_reaps_actual_hosted_child(tmp_path):
    children = []
    with pytest.raises(TimeoutError, match="terminal output predicate"):
        with foreground_terminal(
            [_installed(), *_argv(tmp_path)], cwd=tmp_path,
            env=_terminal_environment(tmp_path), columns=100, rows=30,
        ) as driver:
            driver.read_until(
                lambda out: "/exit ends app" in strip_control_sequences(out), timeout=35
            )
            parent = driver.diagnostics.pid
            children = [pid for pid, entry in process_table().items() if entry[0] == parent]
            assert children, "the real foreground controller must own a hosted child"
            assert all(os.getpgid(pid) != os.getpgid(parent) for pid in children)
            driver.read_until(lambda _: False, timeout=0.05)
    assert not driver.is_alive()
    assert all(pid not in process_table() for pid in children)


@pytest.mark.skipif(os.name != "posix", reason="POSIX test cleanup guard")
def test_G17_TERMINAL_cleanup_adoption_bound_resumes_without_partial_kill(monkeypatch):
    from . import _hosted_terminal

    root = 100_000
    table = {root: (1, "T"), **{root + i: (root, "T") for i in range(1, 131)}}
    signals = []
    monkeypatch.setattr(_hosted_terminal, "process_table", lambda **_: table)
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(TimeoutError, match="exceeded its bound"):
        _hosted_terminal._reclaim_posix_descendants(root)
    stops = [pid for pid, sig in signals if sig == signal.SIGSTOP]
    resumes = [pid for pid, sig in signals if sig == signal.SIGCONT]
    assert len(stops) == 129  # Root plus at most 128 adopted descendants.
    assert resumes == list(reversed(stops))
    assert not any(sig == signal.SIGKILL for _, sig in signals)


def test_G17_TERMINAL_cleanup_ps_uses_remaining_budget(monkeypatch):
    from types import SimpleNamespace

    from . import _hosted_terminal

    timeouts = []

    def run(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(_hosted_terminal.subprocess, "run", run)
    now = _hosted_terminal.time.monotonic()
    assert _hosted_terminal.process_table(deadline=now + 0.25) == {}
    assert 0 < timeouts[0] <= 0.25
    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        _hosted_terminal.process_table(deadline=now - 1)
    assert len(timeouts) == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX independent process-group regression")
def test_G17_TERMINAL_failed_predicate_fallback_reclaims_separate_group(tmp_path, monkeypatch):
    from . import _hosted_terminal

    settle = _hosted_terminal._settle
    monkeypatch.setattr(
        _hosted_terminal, "_settle", lambda driver: settle(driver, graceful_timeout=0.1)
    )
    script = (
        "import signal, subprocess, sys; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'], "
        "start_new_session=True); "
        "print('child-ready', flush=True); child.wait()"
    )
    children = []
    with pytest.raises(TimeoutError, match="terminal output predicate"):
        with foreground_terminal(
            [sys.executable, "-I", "-c", script], cwd=tmp_path,
            env=_terminal_environment(tmp_path), columns=100, rows=30,
        ) as driver:
            driver.read_until(lambda out: "child-ready" in out, timeout=10)
            parent = driver.diagnostics.pid
            children = [pid for pid, entry in process_table().items() if entry[0] == parent]
            assert children
            assert all(os.getpgid(pid) != os.getpgid(parent) for pid in children)
            driver.read_until(lambda _: False, timeout=0.05)
    assert not driver.is_alive()
    assert all(pid not in process_table() for pid in children)
