"""Supplemental Linux ENTRY proof; macOS/Windows guarded observation is pending."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.tui.cell_width import strip_control_sequences

from ._hosted_terminal import foreground_terminal, process_table
from .test_hosted_client import _argv
from .test_hosted_client_terminal import _installed
from .test_mux_terminal_process import _terminal_environment


def _pidfd_open(pid):
    # Some portable Python builds omit os.pidfd_open even on supported Linux.
    # Use libc's typed API, never a numeric-PID signalling fallback.
    libc = ctypes.CDLL(None, use_errno=True)
    operation = libc.pidfd_open
    operation.argtypes = [ctypes.c_int, ctypes.c_uint]
    operation.restype = ctypes.c_int
    descriptor = operation(pid, 0)
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "pidfd admission failed")
    return descriptor


def _pidfd_signal(descriptor, signum):
    libc = ctypes.CDLL(None, use_errno=True)
    operation = libc.pidfd_send_signal
    operation.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    if operation(descriptor, signum, None, 0) < 0:
        raise OSError(ctypes.get_errno(), "pidfd signal failed")


def _stop_children(parent, children):
    # Bind identity before checking ancestry. A recycled numeric PID must never
    # turn this fault injector into a signal to an unrelated process.
    with ExitStack() as handles:
        descriptors = []
        for pid in children:
            descriptor = _pidfd_open(pid)
            handles.callback(os.close, descriptor)
            descriptors.append(descriptor)
        table = process_table()
        assert parent in table and "Z" not in table[parent][1], "controller exited"
        assert all(pid in table and table[pid][0] == parent for pid in children), "child changed"
        for descriptor in descriptors:
            _pidfd_signal(descriptor, signal.SIGSTOP)
        deadline = time.monotonic() + 5
        while True:
            table = process_table(deadline=deadline)
            assert all(pid in table and table[pid][0] == parent for pid in children)
            if all("T" in table[pid][1] for pid in children):
                break
            assert time.monotonic() < deadline, "service did not enter stopped state"
            time.sleep(0.01)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd fault injection")
def test_fault_injection_rejects_changed_child_before_signalling(monkeypatch):
    module = sys.modules[__name__]
    closed, sent = [], []
    monkeypatch.setattr(module, "_pidfd_open", lambda pid: 900)
    monkeypatch.setattr(os, "close", closed.append)
    monkeypatch.setattr(module, "_pidfd_signal", lambda *args: sent.append(args))
    monkeypatch.setattr(module, "process_table", lambda: {100: (1, "S"), 101: (999, "S")})
    with pytest.raises(AssertionError, match="child changed"):
        _stop_children(100, [101])
    assert closed == [900]
    assert not sent


def _observe_entry(tmp_path, *, force_exit=False, cancel_start=False, cancel_recovery=False):
    import pty
    import termios

    opened = []
    openpty = pty.openpty

    def observe():
        master, slave = openpty()
        # Observe the real driver's PTY before Product starts. No Product
        # terminal, process owner, or installed CLI implementation is replaced.
        opened.append((master, termios.tcgetattr(slave)))
        return master, slave

    cancelled = cancel_start or cancel_recovery
    script = "_hosted_recovery_cancel.py" if cancel_recovery else "_hosted_start_cancel.py"
    executable = ([sys.executable, "-I", str(Path(__file__).with_name(script))]
                  if cancelled else [_installed()])
    with patch.object(pty, "openpty", observe), foreground_terminal(
        [*executable, *_argv(tmp_path)], cwd=tmp_path,
        env=_terminal_environment(tmp_path), columns=100, rows=30,
    ) as driver:
        driver.read_until(
            lambda out: (tmp_path / "recovery-held").is_file() if cancel_recovery else
            ("G17 publication held" if cancel_start else "/exit ends app")
            in strip_control_sequences(out), timeout=35,
        )
        (master, baseline), = opened
        active = termios.tcgetattr(master)
        if cancelled:
            assert active == baseline, "unpublished startup must not enter raw mode"
        else:
            assert active != baseline, "ready must actually enter native terminal mode"
            assert not active[3] & (termios.ECHO | termios.ICANON)
        diagnostics = driver.diagnostics
        assert diagnostics.exit_status is None, "controller exited before observation"
        parent = diagnostics.pid
        children = [pid for pid, entry in process_table().items() if entry[0] == parent]
        assert children, "installed foreground command must own a real Hosted process"
        assert all(os.getpgid(pid) != os.getpgid(parent) for pid in children)
        if force_exit:
            # The actual service cannot process detach or EOF while stopped.
            # Leave Product grace/force budgets and its real Hosting backend intact.
            _stop_children(parent, children)
        if cancelled:
            os.kill(parent, signal.SIGINT)
        else:
            driver.write("/exit\r")
        code = driver.wait(timeout=25)
        assert code == (130 if cancelled else 1 if force_exit else 0), driver.diagnostics
        if cancel_start:
            assert "G17 publication cancelled" in driver.raw_output
            assert "G17 late lease returned" in driver.raw_output
        if cancelled:
            assert "G17 terminal invoked" not in driver.raw_output
            assert "hosted_interrupted" in driver.raw_output
            assert "/exit ends app" not in strip_control_sequences(driver.raw_output)
        assert termios.tcgetattr(master) == baseline
        table = process_table()
        assert all(pid not in table for pid in children), "a zombie is not a reaped child"
        assert driver.diagnostics.termination is None, "fixture fallback is not normal exit"


def _guarded(operation):
    import ctypes

    # This runs in a private, retained pytest wrapper, never the calling suite.
    # Adopt an orphan even if a broken CLI exits before our first tree scan.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "entry fixture subreaper admission failed")
    leftovers = False
    try:
        operation()
    finally:
        deadline = time.monotonic() + 5
        while True:
            try:
                child, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            leftovers = True
            if child:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("entry fixture reclamation pending")
            children = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
            for pid in map(int, children.read_text().split()):
                os.kill(pid, signal.SIGKILL)
            time.sleep(0.01)
    if leftovers:
        # Physical fallback must never manufacture successful user evidence.
        # This executes only if operation itself returned without an exception.
        raise AssertionError("native observer left descendants for fixture cleanup")


def _scenario(root, case):
    if case == "recovery-cancel":
        _guarded(lambda: _observe_recovery_cancel(root))
    elif case in {"real", "forced-exit", "start-cancel"}:
        _guarded(lambda: _observe_entry(
            root, force_exit=case == "forced-exit", cancel_start=case == "start-cancel",
        ))
    else:
        def broken_controller():
            script = (
                "import subprocess,sys; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(60)'],"
                "start_new_session=True); Path('orphan.pid').write_text(str(child.pid))"
            )
            controller = subprocess.Popen([sys.executable, "-I", "-c", script], cwd=root)
            assert controller.wait(timeout=5) == 0
            pid = int((root / "orphan.pid").read_text())
            os.kill(pid, 0)
            if case == "controller-leak":
                raise AssertionError("controller exited but Hosted child remains")

        expected = "Hosted child remains" if case == "controller-leak" else "observer left descendants"
        with pytest.raises(AssertionError, match=expected):
            _guarded(broken_controller)
        with pytest.raises(ProcessLookupError):
            os.kill(int((root / "orphan.pid").read_text()), 0)
    (root / "observer.settled").touch()


@pytest.mark.skipif(sys.platform != "linux", reason="supplemental Linux independent reaper evidence")
@pytest.mark.parametrize("case", ["real", "controller-leak", "silent-leak"])
def test_G17_TERMINAL_ENTRY_native_observation_retains_failure_reaper(tmp_path, case):
    _run_observation(tmp_path, case)


@pytest.mark.skipif(sys.platform != "linux", reason="supplemental Linux independent reaper evidence")
def test_G17_TERMINAL_FORCED_EXIT_stopped_service_restores_terminal_and_reaps(tmp_path):
    _run_observation(tmp_path, "forced-exit")


@pytest.mark.skipif(sys.platform != "linux", reason="supplemental Linux independent reaper evidence")
def test_G17_TERMINAL_START_CANCEL_late_actual_lease_cannot_activate_terminal(tmp_path):
    _run_observation(tmp_path, "start-cancel")


@pytest.mark.skipif(sys.platform != "linux", reason="supplemental Linux independent reaper evidence")
def test_G17_TERMINAL_START_CANCEL_durable_recovery_reclaims_and_can_relaunch(tmp_path):
    _run_observation(tmp_path, "recovery-cancel", timeout=150)


def _observe_recovery_cancel(root, *, observer=_observe_entry):
    from loushang.ai.types import UserMessage
    from loushang.appservice.continuity import decode_application_continuity_record
    from loushang.coding.session_manager import SessionManager

    _recovery_cli(root, create=True)
    historical = "G17 history survives recovery cancellation without replay"
    (canonical,) = (root / "cwd").glob("*.jsonl")

    async def seed_history():
        manager = await SessionManager.open(canonical)
        try:
            await manager.append_message(UserMessage(role="user", content=historical, timestamp=1.0))
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(seed_history())
    history_bytes = canonical.read_bytes()
    (record,) = (root / "application").glob("*.json")
    snapshot = record.read_bytes()
    (mux,) = decode_application_continuity_record(snapshot).mux_spaces
    (member,) = mux.members
    observer(root, cancel_recovery=True)
    assert json.loads((root / "recovery-held").read_text()) == asdict(member.session)
    assert record.read_bytes() == snapshot, "cancelled recovery must not rewrite desired state"
    assert canonical.read_bytes() == history_bytes, "cancelled recovery must preserve history"
    _recovery_cli(root, create=False, historical=historical)
    (reopened,) = decode_application_continuity_record(record.read_bytes()).mux_spaces
    assert reopened.mux_space_id == mux.mux_space_id
    assert reopened.members == mux.members
    assert tuple((root / "cwd").glob("*.jsonl")) == (canonical,)
    assert canonical.read_bytes() == history_bytes


def _recovery_cli(root, *, create, historical=None):
    environment = _terminal_environment(root)
    with foreground_terminal(
        [_installed(), *_argv(root)], cwd=root, env=environment, columns=100, rows=30,
    ) as driver:
        driver.read_until(lambda out: "/exit ends app" in strip_control_sequences(out), timeout=35)
        if create:
            driver.write("/new cwd Recovery sentinel\r")
        driver.read_until(lambda out: "*1" in strip_control_sequences(out), timeout=20)
        driver.read_until(lambda out: "Recovery sentinel" in strip_control_sequences(out), timeout=10)
        if historical:
            driver.read_until(lambda out: historical in strip_control_sequences(out), timeout=20)
        driver.write("/exit\r")
        assert driver.wait(timeout=25) == 0, driver.diagnostics
        assert driver.diagnostics.termination is None


def _run_observation(tmp_path, case, *, timeout=90):
    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "observation"
    root.mkdir()
    probe = tmp_path / "test_entry_probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        "from tests.coding.test_hosted_entry_evidence import _scenario\n"
        f"def test_entry():\n    _scenario(Path({str(root)!r}), {case!r})\n"
    )
    supervisor = runpy.run_path(str(repository / "scripts/dev/_evidence_process.py"))
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    supervisor["run_pytest"](
        [sys.executable, "-I", "-m", "pytest", "-c", str(repository / "pyproject.toml"),
         "-o", f"pythonpath={repository}", "--import-mode=importlib", str(probe),
         "-q", "-m", "not live"],
        cwd=tmp_path, environment=environment, timeout=timeout,
    )
    assert (root / "observer.settled").exists()
